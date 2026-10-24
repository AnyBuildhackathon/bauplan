"""Messages after a failed or busy run are answered, and a slow but streaming model round is not cut."""

import asyncio
import time
from types import SimpleNamespace

from anthropic.types import TextBlock

from pai_agent import agents
from pai_agent.orchestrator import _add_request


def _answer(text: str):
    return SimpleNamespace(content=[TextBlock(type="text", text=text)], usage=None)


def _session(monkeypatch, tmp_path, rounds):
    """A session in live Claude mode whose model rounds come from `rounds`, one call each."""

    monkeypatch.setattr("pai_agent.session.SESSIONS_DIR", tmp_path)
    monkeypatch.setattr("pai_agent.session.claude_enabled", lambda: True)
    monkeypatch.setattr("pai_agent.orchestrator.claude_enabled", lambda: True)
    seen: list[list[dict]] = []

    async def stream_round(_model, _effort, on_text, **kwargs):
        seen.append([dict(m) for m in kwargs["messages"]])
        outcome = await rounds.pop(0)()
        for block in outcome.content:
            await on_text(block.text)
        return outcome

    monkeypatch.setattr(agents, "stream_round", stream_round)
    from pai_agent.session import Session

    return Session(), seen


def _chat(session, role):
    return [e["text"] for e in session.bus.events if e.get("type") == "chat" and e.get("role") == role]


def test_message_after_failed_run_is_answered(monkeypatch, tmp_path):
    async def fails():
        raise TimeoutError("no progress for 90 s (PAI_MODEL_TIMEOUT_S), the run stops here")

    async def answers():
        return _answer("A simple phone stand, coming up.")

    async def run():
        session, seen = _session(monkeypatch, tmp_path, [fails, answers])
        assert (await session.start("Build something on your own."))["status"] == "started"
        await session.task
        assert any("model request failed" in text for text in _chat(session, "agent"))
        assert (await session.start("Can you build something really simple?"))["status"] == "started"
        await session.task
        assert "A simple phone stand, coming up." in _chat(session, "agent")
        # The failed turn and the new request are one user turn, so the history stays valid.
        assert [m["role"] for m in seen[1]] == ["user"]
        assert "really simple" in str(seen[1][0]["content"])

    asyncio.run(run())


def test_message_while_busy_is_queued_and_run_next(monkeypatch, tmp_path):
    gate = asyncio.Event()

    async def slow_fail():
        await gate.wait()
        raise TimeoutError("stopped")

    async def answers():
        return _answer("Here is the simple one.")

    async def run():
        session, seen = _session(monkeypatch, tmp_path, [slow_fail, answers])
        await session.start("Build an electric skateboard.")
        await asyncio.sleep(0.01)
        # Typed while the first run is still busy: shown, acknowledged and kept, never dropped.
        assert (await session.start("please?"))["status"] == "queued"
        assert _chat(session, "user")[-1] == "please?"
        assert "take that on" in _chat(session, "agent")[-1]
        first = session.task
        gate.set()
        await first
        assert session.task is not first
        await session.task
        assert "Here is the simple one." in _chat(session, "agent")
        assert "please?" in str(seen[1])
        assert session.pending == []

    asyncio.run(run())


def test_request_after_stopped_tool_call_answers_the_dangling_call():
    messages = [
        {"role": "user", "content": "Build it"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "cad_part", "input": {}}]},
    ]
    _add_request(messages, "Try again")
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[2]["content"][0]["tool_use_id"] == "t1"
    assert messages[2]["content"][-1] == {"type": "text", "text": "Try again"}


def _fake_stream(monkeypatch, gaps):
    """stream_message that waits `gaps` seconds between events, then answers."""

    class Stream:
        closed = False

        def close(self):
            Stream.closed = True

    def stream_message(_model, _effort, on_event, on_text, **_kwargs):
        stream = Stream()
        on_event(stream)
        for gap in gaps:
            time.sleep(gap)
            if Stream.closed:
                raise RuntimeError("closed")
            on_event(stream)
        on_text("Done thinking.")
        return _answer("Done thinking.")

    monkeypatch.setattr(agents, "stream_message", stream_message)
    return Stream


def test_slow_but_streaming_round_is_not_cut(monkeypatch):
    monkeypatch.setenv("PAI_MODEL_TIMEOUT_S", "0.5")
    _fake_stream(monkeypatch, [0.3] * 5)
    texts: list[str] = []

    async def on_text(text):
        texts.append(text)

    started = time.monotonic()
    response = asyncio.run(agents.stream_round("m", "high", on_text))
    # 1.5 s in all, three times the silence limit, and still answered.
    assert time.monotonic() - started > 1.2
    assert response.content[0].text == "Done thinking."
    assert texts == ["Done thinking."]


def test_silent_round_stops_and_closes_the_stream(monkeypatch):
    monkeypatch.setenv("PAI_MODEL_TIMEOUT_S", "0.3")
    stream = _fake_stream(monkeypatch, [1.0])

    async def on_text(_text):
        raise AssertionError("a stopped round writes nothing")

    async def run():
        try:
            await agents.stream_round("m", "high", on_text)
        except TimeoutError as exc:
            assert "PAI_MODEL_TIMEOUT_S" in str(exc)
        else:
            raise AssertionError("a silent stream must stop")
        assert stream.closed

    asyncio.run(run())
