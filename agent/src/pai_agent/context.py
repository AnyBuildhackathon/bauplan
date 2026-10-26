"""`Ctx`: the handle every tool and runner gets, the build state plus the event bus.

Tools never touch HTTP or the session directly; they read and change `ctx.state`
(`state.py`) and report through `ctx.emit`, `ctx.chat` and `ctx.step`. That keeps one tool
implementation usable from the Claude loop, the offline mock runners, the sub-agents and the
dashboard controls alike. `asker` lets a tool ask the people in the room (`ask_user`) and wait
for the answer; `lead_id` links sub-agent events to the orchestrator run that spawned them.
"""

from __future__ import annotations

from pai_agent.bus import EventBus
from pai_agent.scene import STEP_LABELS
from pai_agent.state import BuildState


class Ctx:
    def __init__(self, bus: EventBus, state: BuildState, auto_steps: bool, asker=None) -> None:
        self.bus = bus
        self.state = state
        self.auto_steps = auto_steps
        # Asks the people in the room and waits for the answer; set by the session.
        self.asker = asker
        # The orchestrator run in progress; the sub-agents it delegates to name it as their parent.
        self.lead_id: str | None = None
        # Waits while the run is paused and raises RunStopped after Stop; set by the session.
        self.gate = None
        # Messages the person sent while this run was busy; the session shares its list.
        self.pending: list[str] = []

    async def checkpoint(self) -> None:
        if self.gate is not None:
            await self.gate()

    def take_pending(self) -> list[str]:
        taken = list(self.pending)
        self.pending.clear()
        return taken

    async def emit(self, event: dict) -> None:
        await self.bus.publish(event)

    async def chat(self, role: str, text: str, voice: bool = False, notes: list[dict] | None = None) -> None:
        # notes: the studio notes a person's message carries (notes.py), shown as chips under it.
        await self.emit({"type": "chat", "role": role, "text": text, **({"voice": True} if voice else {}), **({"notes": notes} if notes else {})})

    async def step(self, step_id: str, status: str) -> None:
        await self.emit(
            {
                "type": "step",
                "id": step_id,
                "status": status,
                "label": STEP_LABELS[step_id],
            }
        )


def de(value: float, digits: int) -> str:
    """Formats a number for the English UI. The name stays, the decimal point does not."""

    return f"{value:.{digits}f}"
