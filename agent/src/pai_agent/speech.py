"""What Mechanic says out loud: a fast reply to every prompt, and one short line per build milestone.

The orchestrator does the engineering and takes its time. While it starts, a fast model
(Claude Haiku) answers the person in one or two sentences, streamed token by token as
`say` events, so the browser speaks the first sentence while the rest is still being
written. When the build reaches a milestone (a CAD part, a simulation result, a finished
version) the same model phrases one short sentence from the facts in that event only, with
a fixed sentence as the fallback. Without a Claude key nothing here runs, and the browser
keeps reading the mascot's speech bubble aloud.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable

from pai_agent.bus import EventBus
from pai_agent.state import BuildState

log = logging.getLogger(__name__)

_PERSONA = """You are Mechanic, the voice of AnyBuild, an engineering agent that develops physical products from a team's meetings.
You are a confident, quick-witted inventor with dry humour: brilliant, a little cocky, always on the team's side.
Your words are read aloud. Plain spoken English only: no markdown, lists, emoji, or stage directions.
Never claim to be a real person and never imitate one."""

_REPLY = (
    _PERSONA
    + """
Behind your voice, your build pipeline does the engineering with real tools (Jamie meetings, a parts catalog, FreeCAD, MuJoCo, Blender) and has just received the person's message.
Speak as one agent, "I"; never mention a builder, a pipeline or another agent.
Answer in one or two short sentences, at most 35 words in total. Start with a short phrase of two to five words and a comma or full stop, so it can be spoken right away.
Acknowledge what they want and say what happens next, following the situation line. Never invent numbers, results or part names that are not in the state below; you report those later."""
)

_UPDATE = (
    _PERSONA
    + """
The builder just reached one or more milestones. Report them in one spoken sentence of at most 20 words.
Use only the facts given. Keep numbers exactly as given and say units as words (grams, minutes, euros)."""
)

# Milestones that land within this window (a fast offline run) become one sentence.
_GATHER_S = 0.4
_REPLY_TIMEOUT_S = 8.0
_UPDATE_TIMEOUT_S = 5.0
# Idle keep-alive connections close after about a minute; warming more often is wasted.
_WARM_EVERY_S = 20.0


def voice_model() -> str:
    return os.environ.get("ANTHROPIC_VOICE_MODEL", "").strip() or "claude-haiku-5-5"


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def milestone(event: dict) -> dict | None:
    """The facts worth one spoken sentence, or None for an event that is only progress."""

    kind = event.get("type")
    if kind == "sim":
        return {"milestone": "simulation", "result": event.get("result"), "summary": event.get("summary", "")}
    if kind == "cad":
        part = event.get("part") if isinstance(event.get("part"), dict) else None
        facts = {"milestone": "CAD model built", "tool": event.get("source")}
        if part:
            facts.update({"part": part.get("name"), "material": part.get("material"), "mass_g": part.get("mass_g")})
        return facts
    if kind == "version":
        diff = [
            f"{row.get('label')}: {row.get('before')} to {row.get('after')} {row.get('unit') or ''}".strip()
            for row in (event.get("diff") or [])[:4]
            if isinstance(row, dict)
        ]
        return {"milestone": "version finished", "version": event.get("n"), "summary": event.get("summary", ""), "changes": diff}
    if kind == "step" and event.get("status") == "failed":
        return {"milestone": "step failed", "step": event.get("label")}
    return None


def fallback_line(facts: list[dict]) -> str:
    last = facts[-1]
    name = last.get("milestone")
    if name == "simulation":
        return "The simulation passed." if last.get("result") == "pass" else "The simulation failed. Let me fix that."
    if name == "version finished":
        summary = str(last.get("summary") or "").replace(" · ", ", ")
        return f"Version {last.get('version')} is done" + (f": {summary}." if summary else ".")
    if name == "step failed":
        return f"The {last.get('step') or 'last'} step failed."
    return "The CAD model is built."


_SITUATION = {
    "started": "You are starting on this now.",
    "already_running": "You are still busy with the current run and did not take this message. Say so and ask them to repeat it once the run is done.",
    "answered": "The message answers your open question. Confirm the choice in a few words.",
}


def _reply_prompt(text: str, state: BuildState, status: str, question: dict | None, history: list[dict]) -> str:
    lines = ["Situation: " + _SITUATION[status], f"Product: {state.product}", f"Versions built: {len(state.versions)}"]
    if state.metrics:
        lines.append("Latest numbers: " + json.dumps(state.metrics, ensure_ascii=False))
    if question:
        lines.append("Open question: " + str(question.get("text", "")))
    if history:
        lines.append("Recent conversation:")
        lines.extend(f"{item['role']}: {item['text'][:200]}" for item in history)
    lines.append("Message: " + text)
    return "\n".join(lines)


class Voice:
    def __init__(self, bus: EventBus, busy: Callable[[], bool]) -> None:
        self.bus = bus
        self._busy = busy
        self._client = None
        self._reply: asyncio.Task | None = None
        self._update: asyncio.Task | None = None
        self._pending: list[dict] = []
        self._count = 0
        self._warmed = -_WARM_EVERY_S

    def reply(self, text: str, state: BuildState, status: str, question: dict | None = None) -> None:
        if not enabled():
            return
        if self._reply is not None and not self._reply.done():
            # A newer message makes the old answer moot.
            self._reply.cancel()
        history = [
            {"role": e["role"], "text": str(e.get("text", ""))}
            for e in self.bus.events
            if e.get("type") == "chat" and str(e.get("text", "")).strip() != text
        ][-6:]
        prompt = _reply_prompt(text, state, status, question, history)
        self._reply = asyncio.create_task(self._speak("reply", _REPLY, prompt, _REPLY_TIMEOUT_S, ""))

    def observe(self, event: dict) -> None:
        """Bus observer: queues a spoken update for milestones of a running build (not for slider moves)."""

        if not enabled() or not self._busy():
            return
        facts = milestone(event)
        if facts is None:
            return
        self._pending.append(facts)
        if self._update is None or self._update.done():
            self._update = asyncio.create_task(self._drain())

    def cancel(self) -> None:
        self._pending.clear()
        for task in (self._reply, self._update):
            if task is not None and not task.done():
                task.cancel()
        self._reply = self._update = None

    async def _drain(self) -> None:
        while self._pending:
            await asyncio.sleep(_GATHER_S)
            # The reply is said first; an update never cuts into it.
            if self._reply is not None and not self._reply.done():
                await asyncio.wait([self._reply])
            facts, self._pending = self._pending, []
            await self._speak("update", _UPDATE, json.dumps(facts, ensure_ascii=False), _UPDATE_TIMEOUT_S, fallback_line(facts))

    async def warm(self) -> None:
        """The person started talking: open the connections now, so the reply does not pay for TLS."""

        now = asyncio.get_running_loop().time()
        if now - self._warmed < _WARM_EVERY_S:
            return
        self._warmed = now
        from pai_agent.voice import warm_elevenlabs

        jobs = [warm_elevenlabs()]
        if enabled():
            jobs.append(self._anthropic().models.retrieve(voice_model()))
        for result in await asyncio.gather(*jobs, return_exceptions=True):
            if isinstance(result, Exception):
                log.info("voice warm-up failed: %s", type(result).__name__)

    def _anthropic(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic()
        return self._client

    async def _speak(self, kind: str, system: str, prompt: str, timeout: float, fallback: str) -> None:
        """Streams one line as `say` deltas (live only), then its full text; a reply also lands in the chat."""

        self._count += 1
        say_id = kind[0] + str(self._count)
        text = ""

        async def send(delta: str) -> None:
            await self.bus.publish({"type": "say", "id": say_id, "kind": kind, "delta": delta, "done": False}, keep=False)

        try:
            async with asyncio.timeout(timeout):
                async with self._anthropic().messages.stream(
                    model=voice_model(),
                    max_tokens=120,
                    # Thinking would spend the token budget and the first second on a one-line answer.
                    thinking={"type": "disabled"},
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream:
                    async for delta in stream.text_stream:
                        if delta:
                            text += delta
                            await send(delta)
        except asyncio.CancelledError:
            await self.bus.publish({"type": "say", "id": say_id, "kind": kind, "text": text.strip(), "done": True, "cancelled": True}, keep=False)
            raise
        except Exception:
            log.exception("voice model failed")
            if not text and fallback:
                text = fallback
                await send(fallback)
        line = text.strip()
        await self.bus.publish({"type": "say", "id": say_id, "kind": kind, "text": line, "done": True}, keep=False)
        if kind == "reply" and line:
            await self.bus.publish({"type": "chat", "role": "agent", "text": line})
