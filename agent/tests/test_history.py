"""Chat history: a reset keeps the chat, reopening one brings back its events, state and Claude memory."""

from __future__ import annotations

import asyncio

import pytest

from pai_agent import history
from pai_agent.session import Session

pytestmark = pytest.mark.history


async def _chat(session: Session, text: str) -> None:
    await session.bus.publish({"type": "chat", "role": "user", "text": text})
    await session.bus.publish({"type": "chat", "role": "agent", "text": "On it."})
    session.messages.append({"role": "user", "content": text})
    session.state.metrics = {"weight_g": 42}


def test_untouched_bench_is_not_saved() -> None:
    async def run() -> None:
        session = Session()
        await session.bootstrap()
        await session.reset()

    asyncio.run(run())
    assert history.list_chats() == []


def test_reset_saves_and_open_restores() -> None:
    async def run() -> tuple[str, Session]:
        session = Session()
        await session.bootstrap()
        await _chat(session, "Build me a desk fan that runs on USB power for a long afternoon")
        first = session.state.session_id
        await session.reset()
        await _chat(session, "A phone stand")
        rows = history.list_chats()
        assert [r["id"] for r in rows if r["id"] == first] == [first]
        result = await session.open_chat(first)
        assert result == {"ok": True, "id": first, "status": "opened"}
        return first, session

    first, session = asyncio.run(run())
    assert session.state.session_id == first
    assert session.state.metrics == {"weight_g": 42}
    assert session.messages == [{"role": "user", "content": "Build me a desk fan that runs on USB power for a long afternoon"}]
    texts = [ev["text"] for ev in session.bus.events if ev.get("type") == "chat"]
    assert texts == ["Build me a desk fan that runs on USB power for a long afternoon", "On it."]
    # Opening the old chat saved the newer one, so both are in the list.
    rows = history.list_chats()
    assert len(rows) == 2
    old = next(r for r in rows if r["id"] == first)
    assert old["title"].endswith("…") and len(old["title"]) == history.TITLE_MAX
    assert old["messages"] == 2
    assert history.transcript(first)["chat"][0]["role"] == "user"


def test_open_unknown_or_bad_id() -> None:
    async def run() -> list[dict]:
        session = Session()
        await session.bootstrap()
        return [await session.open_chat("nope0000"), await session.open_chat("../etc")]

    for result in asyncio.run(run()):
        assert result["ok"] is False and result["missing"] is True


def test_open_question_is_settled_on_reopen() -> None:
    async def run() -> Session:
        session = Session()
        await session.bootstrap()
        await _chat(session, "Drone")
        question = {"type": "question", "id": "q1", "text": "Which?", "options": [{"id": "a", "label": "A"}], "default_id": "a", "status": "open", "answer_id": None}
        await session.bus.publish(question)
        first = session.state.session_id
        await session.reset()
        await session.open_chat(first)
        return session

    session = asyncio.run(run())
    question = next(ev for ev in session.bus.events if ev.get("type") == "question")
    assert question["status"] == "answered" and question["answer_id"] == "a"


def test_replay_reaches_connected_clients() -> None:
    async def run() -> list[dict]:
        session = Session()
        await session.bootstrap()
        await _chat(session, "Drone")
        first = session.state.session_id
        await session.reset()
        queue = await session.bus.subscribe()
        await session.open_chat(first)
        seen = []
        while not queue.empty():
            seen.append(queue.get_nowait())
        return seen

    seen = asyncio.run(run())
    start = seen.index({"type": "reset", "replay": True})
    end = seen.index({"type": "replayed"}, start)
    assert any(ev.get("text") == "Drone" for ev in seen[start:end])
