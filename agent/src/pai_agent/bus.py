"""In-memory fan-out for Server-Sent Events: the one channel from the backend to every dashboard.

Every state change is published as one JSON event and kept in `events`, so a client that
connects late (or reconnects after a drop) receives the whole backlog first and renders the
same state as a client that watched live; the dashboard therefore never polls and never asks
for state separately. `subscribe` puts a `replayed` marker after the backlog, only for that
subscriber, so the client can apply the backlog without animations or speech. `keep=False`
publishes live-only events that a reconnect must not replay.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


class EventBus:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self._subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def publish(self, event: dict, keep: bool = True) -> None:
        """`keep=False` is for live-only events (spoken text as it streams): a reconnect does not replay them."""

        async with self._lock:
            if keep:
                self.events.append(event)
            queues = list(self._subscribers)
        for queue in queues:
            queue.put_nowait(event)

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            for event in self.events:
                queue.put_nowait(event)
            # Only this subscriber sees the marker: everything before it is backlog, not news.
            queue.put_nowait({"type": "replayed"})
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def clear(self) -> None:
        async with self._lock:
            self.events.clear()
            for queue in self._subscribers:
                _drain(queue)

    async def stream(self) -> AsyncIterator[dict | None]:
        queue = await self.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield None
                    continue
                yield event
        finally:
            self.unsubscribe(queue)


def _drain(queue: asyncio.Queue) -> None:
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return
