"""The bench team without a key: the orchestrator and its sub-agents as `agent` events.

The live orchestrator delegates bounded jobs to sub-agents (agents.py). The offline story shows
the same picture: the lead fans jobs out to a Parts agent, CAD agents, a Pricing agent and an
Analysis agent that waits for the geometry. Each job runs beside the real mock tools for a few
beats, reports its tool calls one by one and finishes with a fixed report. Token counts are
fixed per model call, the cost comes from the published prices like a live run's.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Self, TypeVar

from pai_agent import settings
from pai_agent.agents import CAD_ROLE, ROLES, AgentRun
from pai_agent.context import Ctx

T = TypeVar("T")

# One beat of a mock sub-agent: a model call and the tool call it asks for.
TICK_S = 1.2
# What one mock model call costs in tokens: the role's tools and the build context are cached.
SUB_ROUND = {"input_tokens": 1900, "output_tokens": 420, "cache_read_tokens": 7400}
LEAD_ROUND = {"input_tokens": 5200, "output_tokens": 900, "cache_read_tokens": 21000}


@dataclass
class Job:
    """One delegated job: who, what, the tool calls it makes and its report."""

    key: str
    role: str
    task: str
    calls: list[tuple[str, str]]
    report: str
    # Keys of jobs in the same fan-out that must finish first; the job shows as queued until then.
    after: tuple[str, ...] = field(default_factory=tuple)


def _label(role: str) -> str:
    return CAD_ROLE["label"] if role == "cad" else ROLES[role]["label"]


class MockTeam:
    """The orchestrator for one mock run; `async with` it around the run."""

    def __init__(self, ctx: Ctx, task: str) -> None:
        config = settings.current()
        self.ctx = ctx
        self.config = config
        self.lead = AgentRun(ctx, "orchestrator", "Orchestrator", config["orchestrator_model"], config["orchestrator_effort"], task)
        self.runs: list[AgentRun] = []

    async def __aenter__(self) -> Self:
        self.ctx.lead_id = self.lead.id
        self._round(self.lead, LEAD_ROUND)
        await self.lead.emit("running", "plans the build")
        return self

    async def __aexit__(self, kind, exc, _tb) -> None:
        self.ctx.lead_id = None
        if exc is not None:
            await self.lead.emit("error", str(exc)[:160] or "the run stopped")
            return
        total = self.lead.cost() + sum(run.cost() for run in self.runs)
        await self.lead.emit("done", f"{len(self.runs)} sub-agent(s), ${total:.3f} for the whole team")

    def _round(self, run: AgentRun, usage: dict) -> None:
        run.rounds += 1
        settings.add_usage(run.usage, usage)

    async def alongside(self, jobs: list[Job], work: Awaitable[T]) -> T:
        """Fans the jobs out to sub-agents while the real tools do `work`; returns its result."""

        await self.lead.use("delegate", "delegates to " + ", ".join(_label(job.role) for job in jobs))
        finished = {job.key: asyncio.Event() for job in jobs}
        tasks = [asyncio.create_task(self._job(job, finished)) for job in jobs]
        try:
            result = await work
            await asyncio.gather(*tasks)
        except BaseException:
            # A failed step or a reset stops the team too, so no sub-agent reports after it.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        self.lead.called("delegate", {"detail": str(len(jobs)) + " job(s) reported back"})
        self._round(self.lead, LEAD_ROUND)
        await self.lead.emit("running", "reviews the reports")
        return result

    async def _job(self, job: Job, finished: dict[str, asyncio.Event]) -> None:
        run = AgentRun(self.ctx, job.role, _label(job.role), self.config["subagent_model"], self.config["subagent_effort"], job.task)
        self.runs.append(run)
        try:
            waits = [finished[key] for key in job.after if key in finished]
            if waits:
                await run.emit("queued", "waits for the geometry")
                for event in waits:
                    await event.wait()
            self._round(run, SUB_ROUND)
            await run.emit("running", "thinking")
            for tool, detail in job.calls:
                await run.use(tool, detail)
                await asyncio.sleep(TICK_S)
                run.called(tool, {"detail": detail})
                self._round(run, SUB_ROUND)
            await run.emit("done", job.report)
        except asyncio.CancelledError:
            await asyncio.shield(run.emit("error", "stopped with the run"))
            raise
        finally:
            finished[job.key].set()


def parts_job(task: str, picks: list[str], report: str) -> Job:
    return Job("parts", "parts", task, [("part_pick", pick) for pick in picks], report)


def build_jobs(label: str) -> list[Job]:
    """The fan-out of one build: three CAD agents and pricing in parallel, the checks after the geometry."""

    return [
        Job(
            "cad-frame",
            "cad",
            "FreeCAD script for the frame",
            [("cad_part", "writes the Twiglet plate script"), ("freecad", "FreeCAD builds the frame"), ("freecad", "checks the 2-inch prop clearance")],
            "Frame built in FreeCAD, STEP and STL exported, props clear the arms.",
        ),
        Job(
            "cad-canopy",
            "cad",
            "FreeCAD script for the canopy",
            [("cad_part", "writes the canopy script"), ("freecad", "FreeCAD builds the canopy")],
            "Canopy built: holds the Caddx Ant at 20 degrees and the 1S pack underneath.",
        ),
        Job(
            "cad-mounts",
            "cad",
            "FreeCAD script for the mounts",
            [("cad_part", "writes the motor mount script"), ("freecad", "FreeCAD builds 4 motor mounts")],
            "Motor mounts built on the 6.6 mm bolt circle of the 1103s.",
        ),
        Job(
            "pricing",
            "pricing",
            "price the bill of materials of " + label,
            [("part_pick", "checks shop prices of the 8 parts"), ("bom_build", "builds the bill of materials")],
            "Bill of materials priced; the motors are the biggest line, prices are from today's shops.",
        ),
        Job(
            "checks",
            "checks",
            "run the checks on " + label,
            [("assemble", "assembles the parts"), ("check_totals", "mass and thrust-to-weight"), ("simulate_assembly", "MuJoCo hover with a gust")],
            "Every requirement passes: thrust-to-weight, flight time and weight are in range; the hover holds the gust.",
            after=("cad-frame", "cad-canopy", "cad-mounts"),
        ),
    ]
