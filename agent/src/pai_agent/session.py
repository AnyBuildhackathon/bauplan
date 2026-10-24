"""One local session. The demo is single-user."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from pathlib import Path

from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.env import claude_enabled
from pai_agent.orchestrator import run_meeting, run_prompt, run_reference
from pai_agent.paths import SESSIONS_DIR
from pai_agent.scene import STEPS
from pai_agent.speech import Voice
from pai_agent.state import BuildState
from pai_agent.tools.jamie import forget_client, init_timeline, meeting_event, resolve_meeting, set_task_done
from pai_agent.tools.registry import emit_connections

log = logging.getLogger(__name__)


def ask_timeout() -> float:
    raw = os.environ.get("PAI_ASK_TIMEOUT_S", "").strip() or "20"
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 20.0


class Session:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.state: BuildState = _new_state()
        self.messages: list[dict] = []
        self.task: asyncio.Task | None = None
        self.question: dict | None = None
        self._answer: asyncio.Future | None = None
        # Webhooks can arrive twice (retries); one meeting-ended at a time decides what happens.
        self._meeting_lock = asyncio.Lock()
        # Mechanic answers out loud right away while the orchestrator works, and speaks again at milestones.
        self.voice = Voice(self.bus, busy=self._busy)
        self.bus.observer = self.voice.observe

    async def bootstrap(self) -> None:
        await self._baseline()

    def _ctx(self, auto_steps: bool) -> Ctx:
        return Ctx(self.bus, self.state, auto_steps=auto_steps, asker=self.ask)

    def _busy(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self, text: str) -> dict:
        mode = "claude" if claude_enabled() else "mock"
        if self._busy():
            question = self.question
            if question is not None and await self._answer_from_text(text):
                self.voice.reply(text, self.state, "answered", question)
                return {"ok": True, "mode": mode, "status": "answered"}
            self.voice.reply(text, self.state, "already_running")
            return {"ok": True, "mode": mode, "status": "already_running"}
        self.voice.reply(text, self.state, "started")
        ctx = self._ctx(auto_steps=claude_enabled())
        self.task = asyncio.create_task(self._run(run_prompt(ctx, text, self.messages), ctx))
        return {"ok": True, "mode": mode, "status": "started"}

    async def start_reference(self, ref_id: str) -> dict:
        """Starts from a reference build on a fresh bench; the chat then changes it."""

        mode = "claude" if claude_enabled() else "mock"
        if self._busy():
            return {"ok": True, "mode": mode, "status": "already_running"}
        if self.state.started:
            await self.reset()
        ctx = self._ctx(auto_steps=False)
        self.task = asyncio.create_task(self._run(run_reference(ctx, ref_id), ctx))
        return {"ok": True, "mode": mode, "status": "started", "reference": ref_id}

    def save_reference(self, ref_id: str | None, name: str | None, summary: str) -> dict:
        from pai_agent.references import save_reference

        if self._busy():
            return {"ok": False, "error": "Mechanic is building. Save when the build is done.", "busy": True}
        try:
            return {"ok": True, "item": save_reference(self.state, ref_id, name, summary)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    async def meeting_started(self, meeting_id: str, title: str) -> dict:
        meta = resolve_meeting(self.state, meeting_id, title)
        if meta["status"] != "done":
            meta["status"] = "live"
        await self.bus.publish(meeting_event(meta))
        return {"ok": True, "status": "live", "meeting_id": meta["id"]}

    async def start_from_meeting(self, meeting_id: str, title: str) -> dict:
        """A meeting ended in Jamie: the kickoff starts a fresh build, a review rebuilds the current one."""

        mode = "claude" if claude_enabled() else "mock"
        async with self._meeting_lock:
            if self._busy():
                return {"ok": True, "mode": mode, "status": "already_running"}
            meta = resolve_meeting(self.state, meeting_id, title)
            if meta["version"] is not None:
                # A retried webhook for a meeting that already has its version builds nothing.
                return {"ok": True, "mode": mode, "status": "already_built", "meeting_id": meta["id"], "version": meta["version"]}
            if meta["kind"] == "kickoff" and self.state.started:
                await self.reset()
                meta = resolve_meeting(self.state, meeting_id, title)
            await self.bus.publish(meeting_event(meta))
            ctx = self._ctx(auto_steps=claude_enabled())
            self.task = asyncio.create_task(self._run(run_meeting(ctx, meta, self.messages), ctx))
            return {"ok": True, "mode": mode, "status": "started", "meeting_id": meta["id"], "kind": meta["kind"]}

    async def ask(self, question: dict) -> str:
        """Shows a question with options and waits for a click, a spoken or typed answer, or the timeout."""

        timeout = ask_timeout()
        options = question["options"]
        default = question.get("default_id") or options[0]["id"]
        self.question = {
            "type": "question",
            "id": question.get("id") or "q" + uuid.uuid4().hex[:6],
            "text": question["text"],
            "options": options,
            "default_id": default,
            "timeout_s": timeout,
            "status": "open",
            "answer_id": None,
        }
        loop = asyncio.get_running_loop()
        self._answer = loop.create_future()
        await self.bus.publish(dict(self.question))
        try:
            answer = await asyncio.wait_for(asyncio.shield(self._answer), timeout=timeout) if timeout else default
        except TimeoutError:
            answer = default
        closed = {**self.question, "status": "answered", "answer_id": answer}
        self.question = None
        self._answer = None
        await self.bus.publish(closed)
        return str(answer)

    async def answer(self, question_id: str, answer_id: str) -> bool:
        if self.question is None or self.question["id"] != question_id or self._answer is None:
            return False
        if answer_id not in {option["id"] for option in self.question["options"]}:
            return False
        if not self._answer.done():
            self._answer.set_result(answer_id)
        return True

    async def _answer_from_text(self, text: str) -> bool:
        """'Fünfzehn', '15 bitte' or 'ja, passt' answer the open question."""

        assert self.question is not None
        lowered = text.lower()
        words = {"zehn": "10", "ten": "10", "fünfzehn": "15", "fifteen": "15", "zwölf": "12", "twelve": "12", "zwanzig": "20", "twenty": "20"}
        for word, digits in words.items():
            lowered = re.sub(r"\b" + word + r"\b", digits, lowered)
        for option in self.question["options"]:
            numbers = re.findall(r"\d+", option["label"])
            if numbers and any(re.search(r"\b" + n + r"\b", lowered) for n in numbers):
                await self.bus.publish({"type": "chat", "role": "user", "text": text})
                return await self.answer(self.question["id"], option["id"])
        if re.search(r"\b(ja|passt|okay|ok|genau|neu|neue|yes|fine|sure|new)\b", lowered):
            await self.bus.publish({"type": "chat", "role": "user", "text": text})
            return await self.answer(self.question["id"], self.question["default_id"])
        return False

    async def toggle_task(self, task_id: str, done: bool) -> dict:
        return await set_task_done(self._ctx(auto_steps=False), task_id, done)

    async def update_params(self, body: dict) -> dict:
        from pai_agent.tools.cad import apply_param_body, cad_frame

        if self._busy():
            message = "Mechanic is building. Try again in a moment."
            return {"ok": False, "error": message, "detail": message, "busy": True}
        if self.state.product == "generic":
            return await self._update_generic(body)
        if self._part_is_current():
            return await self._rebuild_part(body)
        try:
            args = apply_param_body(self.state.cad_params, body)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc), "detail": str(exc)}
        return await cad_frame(self._ctx(auto_steps=False), args)

    def _part_is_current(self) -> bool:
        # The newest CAD build decides: cad_frame writes frame.stl, cad_part writes part-<name>.stl.
        return self.state.part is not None and Path(self.state.stl_path or "").name.startswith("part-")

    async def _rebuild_part(self, body: dict) -> dict:
        from pai_agent.requirements import refresh_requirements
        from pai_agent.tools.cad_part import rebuild_part
        from pai_agent.tools.gripper import grip_calc

        changes = {str(body["name"]): body.get("value")} if "name" in body else dict(body)
        ctx = self._ctx(auto_steps=False)
        try:
            result = await rebuild_part(ctx, changes)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc), "detail": str(exc)}
        if result.get("ok") and self.state.product == "gripper" and self.state.metrics:
            # A longer finger is a longer lever: the grip numbers follow the slider.
            await grip_calc(ctx, {})
        await refresh_requirements(ctx)
        return result

    async def _update_generic(self, body: dict) -> dict:
        """A slider of an assembled product: `part_id.param` names the part and its number."""

        from pai_agent.tools.product import cad_update

        changes = {str(body["name"]): body.get("value")} if "name" in body else dict(body)
        by_part: dict[str, dict] = {}
        for key, value in changes.items():
            part_id, _, param = key.partition(".")
            info = self.state.built.get(part_id)
            slider = (info or {}).get("sliders", {}).get(param)
            if slider is None:
                message = key + " is not a parameter of this product."
                return {"ok": False, "error": message, "detail": message}
            try:
                number = float(value)
            except (TypeError, ValueError):
                message = key + " must be a number."
                return {"ok": False, "error": message, "detail": message}
            if not slider["min"] <= number <= slider["max"]:
                message = key + " must be between " + str(slider["min"]) + " and " + str(slider["max"]) + "."
                return {"ok": False, "error": message, "detail": message}
            by_part.setdefault(part_id, {})[param] = number
        ctx = self._ctx(auto_steps=False)
        result: dict = {"ok": True}
        for part_id, params in by_part.items():
            result = await cad_update(ctx, {"part_id": part_id, "params": params})
            if result.get("ok") is False:
                return result
        from pai_agent.requirements import refresh_requirements

        await refresh_requirements(ctx)
        return result

    async def open_current(self) -> dict:
        from pai_agent.freecad_run import FreeCADFailed, open_in_freecad

        names = ("frame.FCStd", "frame.step", "frame.stl")
        if self.state.product == "generic":
            names = tuple("part-" + part_id + ".step" for part_id in self.state.built) or ("assembly.stl",)
        elif self._part_is_current():
            names = (Path(self.state.stl_path).with_suffix(".step").name,)
        for name in names:
            path = self.state.directory / name
            if not path.is_file():
                continue
            try:
                open_in_freecad(path)
            except (FreeCADFailed, OSError) as exc:
                return {"ok": False, "detail": str(exc)}
            return {"ok": True, "path": name}
        return {"ok": False, "detail": "Noch kein Rahmen."}

    async def reset(self) -> None:
        if self._busy():
            assert self.task is not None
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.task = None
        self.question = None
        self._answer = None
        self.voice.cancel()
        forget_client(self.state.session_id)
        self.state = _new_state()
        self.messages.clear()
        await self.bus.clear()
        await self._baseline()

    async def shutdown(self) -> None:
        self.voice.cancel()
        if self._busy():
            assert self.task is not None
            self.task.cancel()

    async def _run(self, work, ctx: Ctx) -> None:
        try:
            await work
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("run failed")
            await ctx.chat("agent", "The run stopped: " + str(exc))
            await ctx.emit({"type": "mascot", "state": "besorgt", "say": "Something went wrong in the run."})

    async def _baseline(self) -> None:
        # Every stream starts with this marker, so a client that reconnects or misses a reset starts clean.
        await self.bus.publish({"type": "reset"})
        await emit_connections(self.bus.publish)
        for step_id, label in STEPS:
            await self.bus.publish({"type": "step", "id": step_id, "status": "pending", "label": label})
        for meta in self.state.meetings.values():
            await self.bus.publish(meeting_event(meta))


def _new_state() -> BuildState:
    session_id = uuid.uuid4().hex[:8]
    directory = SESSIONS_DIR / session_id
    directory.mkdir(parents=True, exist_ok=True)
    state = BuildState(session_id=session_id, directory=directory)
    init_timeline(state)
    return state
