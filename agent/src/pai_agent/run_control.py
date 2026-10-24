"""Pause, resume and stop for the run on the bench.

A run only ever stops at a checkpoint: before a tool call and before a model round.
A tool that is running finishes first, so nothing is left half written.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class RunStopped(BaseException):
    """Raised at the next checkpoint after Stop.

    A BaseException like CancelledError, so the `except Exception` around tools does not swallow it.
    """


class RunControl:
    """`status` is `idle`, `running`, `pausing` (asked, the current step still finishes), `paused` or `stopping`."""

    def __init__(self, publish: Callable[[dict], Awaitable[None]]) -> None:
        self._publish = publish
        self._go = asyncio.Event()
        self._go.set()
        self.status = "idle"

    async def _set(self, status: str) -> None:
        self.status = status
        await self._publish({"type": "run", "status": status})

    async def started(self) -> None:
        # A Pause or Stop that came before the task began keeps its status.
        if self.status in {"idle", "running"}:
            self._go.set()
            self.status = "running"
        await self._set(self.status)

    async def finished(self) -> None:
        self._go.set()
        await self._set("idle")

    async def pause(self) -> bool:
        if self.status in {"pausing", "paused"}:
            return True
        if self.status != "running":
            return False
        self._go.clear()
        await self._set("pausing")
        return True

    async def resume(self) -> bool:
        if self.status == "running":
            return True
        if self.status not in {"pausing", "paused"}:
            return False
        self._go.set()
        await self._set("running")
        return True

    async def stop(self) -> bool:
        if self.status == "stopping":
            return True
        if self.status not in {"running", "pausing", "paused"}:
            return False
        await self._set("stopping")
        # A paused run wakes up only to stop.
        self._go.set()
        return True

    async def checkpoint(self) -> None:
        if self.status == "stopping":
            raise RunStopped
        if not self._go.is_set():
            if self.status != "paused":
                await self._set("paused")
            await self._go.wait()
            if self.status == "stopping":
                raise RunStopped
