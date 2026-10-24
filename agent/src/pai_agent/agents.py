"""Orchestrator and sub-agents, like a lead engineer with a small team.

The orchestrator (Opus 5.5 by default, effort up to max) plans the build and delegates bounded
jobs to smaller sub-agents (Sonnet 5.5 by default): one part's FreeCAD script, picking the
bought parts, running the checks, pricing the bill of materials. Each sub-agent sees only the
tools its job needs, works in its own short loop and reports back; the orchestrator reviews
the report and integrates it. Every agent streams as an `agent` event: who, which model, what
job, status, rounds, tokens and cost.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from pai_agent import settings
from pai_agent.context import Ctx

log = logging.getLogger(__name__)

MAX_ROUNDS = 12

ROLES = {
    "parts": {
        "label": "Parts agent",
        "tools": ("part_pick",),
        "prompt": (
            "You pick the bought parts of a product spec. For every bought part in your task: search with part_pick and query, "
            "then bind the best fit with select_id and a one-line reason, or pass an honest estimate when no catalog part fits. "
            "Match the specs the requirements need (voltage, torque, capacity, size). Do not touch anything else."
        ),
    },
    "checks": {
        "label": "Analysis agent",
        "tools": ("assemble", "check_totals", "check_tip_over", "check_deflection", "check_torque", "check_runtime", "simulate_assembly"),
        "prompt": (
            "You run the engineering checks of a product. Run check_totals, then every check the requirements name, with honest loads: "
            "the force a user really applies, the real lever arm, realistic duty cycles. Run simulate_assembly when a stability requirement exists. "
            "Do not change the design. Report each requirement as pass or fail with its number, and for each fail the smallest change that would fix it."
        ),
    },
    "pricing": {
        "label": "Pricing agent",
        "tools": ("part_pick", "bom_build"),
        "prompt": (
            "You price the bill of materials. Build it with bom_build. Where a bought part has an estimated price and a catalog part fits as well, "
            "swap it with part_pick select_id. Report the total, the most expensive lines and which prices are estimates."
        ),
    },
}
CAD_ROLE = {"label": "CAD agent"}


class AgentRun:
    """One agent's lifetime as `agent` events: started, progress per model call, finished."""

    def __init__(self, ctx: Ctx, role: str, label: str, model: str, effort: str, task: str) -> None:
        self.ctx = ctx
        self.id = role + "-" + uuid.uuid4().hex[:6]
        self.role = role
        self.label = label
        self.model = model
        self.effort = effort
        self.task = task
        self.rounds = 0
        self.usage: dict = {}

    async def emit(self, status: str, summary: str = "") -> None:
        await self.ctx.emit(
            {
                "type": "agent",
                "id": self.id,
                "role": self.role,
                "label": self.label,
                "model": self.model,
                "model_label": settings.label(self.model),
                "effort": self.effort,
                "task": self.task,
                "status": status,
                "rounds": self.rounds,
                "input_tokens": self.usage.get("input_tokens", 0),
                "output_tokens": self.usage.get("output_tokens", 0),
                "cache_read_tokens": self.usage.get("cache_read_tokens", 0),
                "cost_usd": self.cost(),
                "summary": summary,
            }
        )

    def count(self, response) -> None:
        self.rounds += 1
        settings.add_usage(self.usage, settings.usage_of(response))

    def cost(self) -> float:
        return settings.cost_usd(self.model, self.usage)


_CLIENT = None


def _client():
    """One client for the whole server: rounds reuse its warm connection instead of a new TLS handshake each."""

    global _CLIENT
    if _CLIENT is None:
        import anthropic

        from pai_agent.timeouts import model_timeout

        # The SDK's own limit matches the round's, so a stuck request does not linger in its thread.
        _CLIENT = anthropic.Anthropic(timeout=model_timeout(), max_retries=1)
    return _CLIENT


def create_message(model: str, effort: str, **kwargs):
    """One Messages call with adaptive thinking and the chosen effort."""

    return _client().messages.create(model=model, thinking={"type": "adaptive"}, output_config={"effort": effort}, **kwargs)


def _dump(block: object) -> dict:
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(block)


async def run_subagent(ctx: Ctx, role: str, task: str) -> dict:
    """Runs one bounded job with the role's tools only and returns its report."""

    from pai_agent.references import build_context
    from pai_agent.tools.registry import SCHEMAS, call_tool

    spec = ROLES[role]
    config = settings.current()
    run = AgentRun(ctx, role, spec["label"], config["subagent_model"], config["subagent_effort"], task)
    tools = [schema for schema in SCHEMAS if schema["name"] in spec["tools"]]
    context = build_context(ctx.state) if ctx.state.spec else ""
    messages: list[dict] = [{"role": "user", "content": context + "Your job: " + task}]
    system = (
        "You are the " + spec["label"] + " on AnyBuild's engineering bench, working for the lead engineer. " + spec["prompt"]
        + " Units are millimetres, grams, newtons and euros. Finish with a short report in plain English: what you did, the numbers, open issues."
    )
    calls: list[dict] = []
    await run.emit("running")
    report = ""
    try:
        for _round in range(MAX_ROUNDS):
            response = await asyncio.to_thread(
                create_message,
                run.model,
                run.effort,
                max_tokens=8000,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=tools,
                messages=messages,
            )
            run.count(response)
            blocks = list(response.content)
            messages.append({"role": "assistant", "content": [_dump(block) for block in blocks]})
            uses = [block for block in blocks if getattr(block, "type", None) == "tool_use"]
            text = " ".join(str(block.text).strip() for block in blocks if getattr(block, "type", None) == "text" and str(block.text).strip())
            if text:
                report = text
            await run.emit("running", (calls[-1]["detail"] if calls else "thinking")[:120])
            if not uses:
                break
            results = []
            for block in uses:
                raw = block.input if isinstance(block.input, dict) else {}
                result = await call_tool(ctx, block.name, raw)
                calls.append({"tool": block.name, "ok": result.get("ok") is not False, "detail": str(result.get("detail") or result.get("error") or "")[:160]})
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str)[:12000],
                        "is_error": result.get("ok") is False,
                    }
                )
            messages.append({"role": "user", "content": results})
        else:
            report = (report + " " if report else "") + "Stopped after " + str(MAX_ROUNDS) + " rounds."
    except Exception as exc:
        log.exception("sub-agent failed")
        await run.emit("error", str(exc)[:160])
        return {"ok": False, "error": run.label + " failed: " + str(exc), "detail": run.label + " failed", "tool_calls": calls}
    await run.emit("done", report[:240])
    return {
        "ok": True,
        "detail": run.label + ": " + str(len(calls)) + " tool call(s), " + f"${run.cost():.3f}",
        "agent": role,
        "model": run.model,
        "report": report,
        "tool_calls": calls,
        "tokens": run.usage,
        "cost_usd": run.cost(),
    }


async def delegate(ctx: Ctx, args: dict) -> dict:
    role = str(args.get("agent") or "").strip().lower()
    task = str(args.get("task") or "").strip()
    if role not in ROLES:
        return {"ok": False, "error": "agent must be one of " + ", ".join(ROLES) + ".", "detail": "unknown agent"}
    if not task:
        return {"ok": False, "error": "task is required: say exactly what the sub-agent should do.", "detail": "no task"}
    return await run_subagent(ctx, role, task)
