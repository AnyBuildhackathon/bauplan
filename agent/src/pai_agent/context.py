"""Helpers shared by the orchestrator and the tools."""

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

    async def emit(self, event: dict) -> None:
        await self.bus.publish(event)

    async def chat(self, role: str, text: str) -> None:
        await self.emit({"type": "chat", "role": role, "text": text})

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
    return f"{value:.{digits}f}".replace(".", ",")
