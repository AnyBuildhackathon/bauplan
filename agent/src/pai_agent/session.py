"""The bench: one session that owns the build state, the event bus and the run in progress.

The demo is single-user, so there is exactly one `Session` per server (created in the app
lifespan). Every entry point (a chat prompt, a voice request from Gemini Live, a sketch, a
library reference, a remix, a slider change) arrives here and
becomes at most one background task; a second build while one runs is refused with
`already_running` instead of interleaving two runs on the same state. Pure dashboard commands
("show me the CAD") are matched first by `app_control.match_commands` and answered without a
model call.

`ask` is how the agent asks the room: it publishes a `question` event and waits for a click,
a typed or spoken answer (`_answer_from_text`) or the `PAI_ASK_TIMEOUT_S` timeout, after which
the default option is taken so a stage demo never stalls on an unanswered question.
`reset` cancels the run, clears the bus and starts a fresh state with a `reset` event.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from pathlib import Path

from pai_agent.app_control import match_commands
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.env import claude_enabled
from pai_agent.orchestrator import run_prompt, run_reference, run_remix, run_sketch
from pai_agent.paths import SESSIONS_DIR
from pai_agent.run_control import RunControl, RunStopped
from pai_agent.scene import STEPS
from pai_agent.state import BuildState
from pai_agent.tools.registry import emit_connections
from pai_agent.versions import label_of

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
        # Whether the last ask_user question got a person's answer, not its timeout default.
        self.answered_by_user = False
        self.created_at = time.time()
        self.task: asyncio.Task | None = None
        self.question: dict | None = None
        self._answer: asyncio.Future | None = None
        self.run = RunControl(self.bus.publish)
        # What the person sent while a run was busy: the run reads it next round, or it starts the next run.
        self.pending: list[str] = []
        # Mechanic greets once per project; a voice reconnect or a second Talk continues the conversation.
        self.greeted = False
        # The one Gemini Live voice session (`gemini_live.LiveVoice`), or None.
        self.live_voice = None

    async def bootstrap(self) -> None:
        await self._baseline()

    def _ctx(self, auto_steps: bool) -> Ctx:
        ctx = Ctx(self.bus, self.state, auto_steps=auto_steps, asker=self.ask)
        ctx.gate = self.run.checkpoint
        ctx.pending = self.pending
        return ctx

    def _busy(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self, text: str, voice: bool = False, record_user: bool = True) -> dict:
        mode = "claude" if claude_enabled() else "mock"
        commands = match_commands(text, self.state)
        if commands:
            return await self._control(text, commands, mode, record_user=record_user)
        if self._busy():
            question = self.question
            if question is not None and await self._answer_from_text(text, voice, record_user=record_user):
                return {"ok": True, "mode": mode, "status": "answered"}
            if self.run.status == "paused":
                # A message to a paused run replaces it: the run stops where it waits, the message continues.
                assert self.task is not None
                await self.run.stop()
                await self.task
            else:
                # Never dropped: the run reads it with its next tool results, or it starts the next run.
                if record_user:
                    await self.bus.publish({"type": "chat", "role": "user", "text": text, **({"voice": True} if voice else {})})
                    await self.bus.publish({"type": "chat", "role": "agent", "text": "Got it. I finish the current step, then take that on."})
                self.pending.append(text.strip())
                # The running build may revise its requirements from it, so it counts as typed now.
                self.state.requests.append(text.strip())
                return {"ok": True, "mode": mode, "status": "queued"}
        ctx = self._ctx(auto_steps=claude_enabled())
        ctx.trigger = "chat"
        ctx.label = label_of(text)
        self.task = self._launch(run_prompt(ctx, text, self.messages, voice, record_user=record_user), ctx)
        return {"ok": True, "mode": mode, "status": "started"}

    async def _control(self, text: str, commands: list[dict], mode: str, *, record_user: bool = True) -> dict:
        """A pure dashboard command: Mechanic operates the app at once, also while a build runs."""

        from pai_agent.tools.registry import call_tool
        from pai_agent.tools.ui import ui_event

        if record_user:
            await self.bus.publish({"type": "chat", "role": "user", "text": text})
        runs = [c for c in commands if c["control"].startswith("run:")]
        if runs and self._busy():
            if not claude_enabled():
                await self.bus.publish({"type": "chat", "role": "agent", "text": "I am still building. Ask again once this run is done."})
            return {"ok": True, "mode": mode, "status": "already_running"}
        ctx = self._ctx(auto_steps=False)

        async def work() -> None:
            for args in commands:
                result = await call_tool(ctx, "ui_control", args)
                if result.get("ok") is False:
                    await ctx.chat("agent", str(result.get("error")))
                elif not claude_enabled() and not args["control"].startswith("run:"):
                    await ctx.chat("agent", ui_event(args["control"], args)["say"])

        if runs:
            # A test or a rebuild is a run: the bench is busy until it finishes.
            self.task = self._launch(work(), ctx)
        else:
            await work()
        return {"ok": True, "mode": mode, "status": "ui", "controls": [c["control"] for c in commands]}

    async def press(self, control: str) -> dict:
        """Someone pressed Run test or Rebuild: the same run Mechanic starts with ui_control, without the pointer."""

        from pai_agent.tools.ui import _check, run_rebuild, run_test

        if control not in {"run:test", "run:rebuild"}:
            return {"ok": False, "error": "control must be run:test or run:rebuild."}
        if self._busy():
            return {"ok": False, "error": "Mechanic is building. Try again in a moment.", "busy": True}
        ctx = self._ctx(auto_steps=False)
        invalid = _check(ctx, control, {})
        if invalid:
            return invalid
        work = run_test(ctx) if control == "run:test" else run_rebuild(ctx)
        self.task = self._launch(work, ctx)
        return {"ok": True, "status": "started"}

    async def start_reference(self, ref_id: str) -> dict:
        """Starts from a reference build on a fresh bench; the chat then changes it."""

        mode = "claude" if claude_enabled() else "mock"
        if self._busy():
            return {"ok": True, "mode": mode, "status": "already_running"}
        if self.state.started:
            await self.reset()
        ctx = self._ctx(auto_steps=False)
        ctx.trigger = "library"
        from pai_agent.references import name_of

        ctx.label = "Library: " + name_of(ref_id)
        self.task = self._launch(run_reference(ctx, ref_id, self.messages), ctx)
        return {"ok": True, "mode": mode, "status": "started", "reference": ref_id}

    async def restore_version(self, n: int) -> dict:
        """Makes an old version current: it is rebuilt through the normal tools and committed as a new version."""

        from pai_agent.versions import restore

        mode = "claude" if claude_enabled() else "mock"
        if self._busy():
            return {"ok": False, "busy": True, "error": "Mechanic is building. Restore when the build is done."}
        if n not in self.state.version_files:
            return {"ok": False, "missing": True, "error": "No version " + str(n) + " to restore."}
        ctx = self._ctx(auto_steps=True)

        async def work() -> None:
            await ctx.chat("agent", "Restoring v" + str(n) + ": I rebuild it with the same tools and keep it as a new version.")
            version = await restore(ctx, n)
            await ctx.chat("agent", "v" + str(version["n"]) + " is v" + str(n) + " again: " + version["summary"] + ".")

        self.task = self._launch(work(), ctx)
        return {"ok": True, "mode": mode, "status": "started", "restoring": n}

    async def apply_variant(self, opt_id: str, variant: str) -> dict:
        """Someone clicked a point in the optimizer chart: that variant is built and committed as the next version."""

        from pai_agent.tools.optimize import apply_variant

        mode = "claude" if claude_enabled() else "mock"
        if self._busy():
            return {"ok": False, "busy": True, "error": "Mechanic is building. Pick a variant when the build is done."}
        event = self.state.optimize.get(opt_id)
        if event is None or not any(v["id"] == variant for v in event["variants"]):
            return {"ok": False, "missing": True, "error": "No variant " + variant + " in optimizer run " + opt_id + "."}
        ctx = self._ctx(auto_steps=True)
        await self.bus.publish({"type": "chat", "role": "user", "text": "Build variant " + variant + "."})
        self.task = self._launch(apply_variant(ctx, opt_id, variant), ctx)
        return {"ok": True, "mode": mode, "status": "started", "variant": variant}

    async def start_sketch(self, data: bytes, note: str) -> dict:
        """A photo of a hand sketch starts a new product on a fresh bench. Raises ValueError for a bad photo."""

        from pai_agent.tools.sketch import sketch_event, store_sketch

        mode = "claude" if claude_enabled() else "mock"
        if self._busy():
            return {"ok": False, "mode": mode, "status": "already_running", "busy": True}
        if self.state.started:
            await self.reset()
        name = store_sketch(self.state, data)
        event = sketch_event(self.state, name, "reading", note=note)
        await self.bus.publish(event)
        ctx = self._ctx(auto_steps=claude_enabled())
        self.task = self._launch(run_sketch(ctx, name, note, self.messages), ctx)
        return {"ok": True, "mode": mode, "status": "started", "sketch": name, "url": event["url"]}

    async def start_remix(self, entry: dict) -> dict:
        """Opens a community project on a fresh bench as a remix; the chat then changes it."""

        mode = "claude" if claude_enabled() else "mock"
        if self._busy():
            return {"ok": True, "mode": mode, "status": "already_running"}
        if self.state.started:
            await self.reset()
        ctx = self._ctx(auto_steps=False)
        self.task = self._launch(run_remix(ctx, entry), ctx)
        return {"ok": True, "mode": mode, "status": "started", "remix": entry["id"]}

    def publish(self, title: str, description: str, author: str) -> dict:
        from pai_agent.community import publish

        if self._busy():
            return {"ok": False, "error": "Mechanic is building. Publish when the build is done.", "busy": True}
        try:
            return {"ok": True, "item": publish(self.state, title, description, author)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    def save_reference(self, ref_id: str | None, name: str | None, summary: str, kind: str = "project") -> dict:
        from pai_agent.references import save_reference

        if self._busy():
            return {"ok": False, "error": "Mechanic is building. Save when the build is done.", "busy": True}
        try:
            return {"ok": True, "item": save_reference(self.state, ref_id, name, summary, kind)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

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
        self.answered_by_user = False
        try:
            answer = await asyncio.wait_for(asyncio.shield(self._answer), timeout=timeout) if timeout else default
            self.answered_by_user = bool(timeout)
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

    async def _answer_from_text(self, text: str, voice: bool = False, *, record_user: bool = True) -> bool:
        """'Fünfzehn', '15 bitte' or 'ja, passt' answer the open question."""

        assert self.question is not None
        lowered = text.lower()
        words = {"zehn": "10", "ten": "10", "fünfzehn": "15", "fifteen": "15", "zwölf": "12", "twelve": "12", "zwanzig": "20", "twenty": "20"}
        for word, digits in words.items():
            lowered = re.sub(r"\b" + word + r"\b", digits, lowered)
        for option in self.question["options"]:
            numbers = re.findall(r"\d+", option["label"])
            if numbers and any(re.search(r"\b" + n + r"\b", lowered) for n in numbers):
                if record_user:
                    await self.bus.publish({"type": "chat", "role": "user", "text": text, **({"voice": True} if voice else {})})
                return await self.answer(self.question["id"], option["id"])
        if re.search(r"\b(ja|passt|okay|ok|genau|neu|neue|yes|fine|sure|new)\b", lowered):
            if record_user:
                await self.bus.publish({"type": "chat", "role": "user", "text": text, **({"voice": True} if voice else {})})
            return await self.answer(self.question["id"], self.question["default_id"])
        return False

    async def update_params(self, body: dict) -> dict:
        if self._busy():
            message = "Mechanic is building. Try again in a moment."
            return {"ok": False, "error": message, "detail": message, "busy": True}
        before = len(self.bus.events)
        result = await self._update_params(body)
        # A slider rebuild calls the CAD tools directly, not through call_tool, so nothing ends the tool cards
        # their progress lines opened: they end here with the result.
        opened = {ev["name"] for ev in self.bus.events[before:] if ev.get("type") == "tool" and ev.get("status") == "running"}
        for name in sorted(opened):
            status = "error" if result.get("ok") is False else "ok"
            await self.bus.publish({"type": "tool", "name": name, "status": status, "detail": str(result.get("detail") or result.get("error") or "")})
        return result

    async def _update_params(self, body: dict) -> dict:
        from pai_agent.tools.cad import apply_param_body, cad_frame
        from pai_agent.tools.solidcraft_part import is_current, rebuild_solidcraft

        if is_current(self.state):
            # The CAD tab shows a SolidCraft design: its parameters rebuild it through SolidCraft's timeline.
            try:
                return await rebuild_solidcraft(self._ctx(auto_steps=False), {str(body["name"]): body.get("value")} if "name" in body else dict(body))
            except (TypeError, ValueError) as exc:
                return {"ok": False, "error": str(exc), "detail": str(exc)}
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
        """A slider of an assembled product: `part_id.param` names the part and its parameter; the value is the user's from now on."""

        from pai_agent.part_params import coerce, in_range
        from pai_agent.tools.product import user_change

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
                number = coerce(key, slider, value)
                in_range(key, slider, number)
            except ValueError as exc:
                return {"ok": False, "error": str(exc), "detail": str(exc)}
            by_part.setdefault(part_id, {})[param] = number
        ctx = self._ctx(auto_steps=False)
        result: dict = {"ok": True}
        for part_id, params in by_part.items():
            result = await user_change(ctx, part_id, params)
            if result.get("ok") is False:
                return result
        from pai_agent.requirements import refresh_requirements

        await refresh_requirements(ctx)
        return result

    async def open_current(self) -> dict:
        from pai_agent.freecad_run import FreeCADFailed, open_in_freecad
        from pai_agent.tools.solidcraft_part import is_current

        names = ("frame.FCStd", "frame.step", "frame.stl")
        if is_current(self.state):
            names = (self.state.solidcraft["files"]["step"],)
        elif self.state.product == "generic":
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
        return {"ok": False, "detail": "No CAD model to open yet."}

    async def reset(self) -> None:
        # A new chat ends the voice too; the next Talk starts fresh on the new project.
        if self.live_voice is not None:
            await self.live_voice.end("reset")
        await self._stop()
        # The chat that ends here stays in the history; the next one is a new entry.
        self.save_chat()
        self.state = _new_state()
        self.messages = []
        self.created_at = time.time()
        await self.bus.clear()
        await self._baseline()

    async def open_chat(self, chat_id: str) -> dict:
        """Reopens a saved chat: its build state, Claude's memory of it, and its events, replayed to every client."""

        from pai_agent import history

        if self._busy():
            return {"ok": False, "busy": True, "error": "Mechanic is building. Open the chat when the build is done."}
        if chat_id == self.state.session_id:
            return {"ok": True, "id": chat_id, "status": "current"}
        saved = history.load(chat_id)
        if saved is None:
            return {"ok": False, "missing": True, "error": "No saved chat " + chat_id + "."}
        await self._stop()
        self.save_chat()
        self.state, self.messages, events, self.created_at = saved
        await self.bus.load(events)
        await emit_connections(self.bus.publish)
        return {"ok": True, "id": chat_id, "status": "opened"}

    def save_chat(self) -> None:
        from pai_agent import history

        try:
            history.save(self.state, list(self.bus.events), self.messages, self.created_at)
        except Exception:
            # Losing one save must never break a build or a reset.
            log.exception("saving the chat failed")

    async def _stop(self) -> None:
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
        self.pending.clear()
        self.greeted = False

    async def shutdown(self) -> None:
        if self._busy():
            assert self.task is not None
            self.task.cancel()
        self.save_chat()

    async def pause(self) -> dict:
        """Pauses the run at its next checkpoint; the tool that runs now finishes first."""

        if not self._busy() or not await self.run.pause():
            return {"ok": False, "error": "Nothing is running.", "status": self.run.status}
        return {"ok": True, "status": self.run.status}

    async def resume(self) -> dict:
        if not self._busy() or not await self.run.resume():
            return {"ok": False, "error": "No paused run.", "status": self.run.status}
        return {"ok": True, "status": self.run.status}

    async def stop(self) -> dict:
        """Ends the run at its next checkpoint and keeps everything built so far."""

        if not self._busy() or not await self.run.stop():
            return {"ok": False, "error": "Nothing is running.", "status": self.run.status}
        return {"ok": True, "status": self.run.status}

    def _launch(self, work, ctx: Ctx) -> asyncio.Task:
        # Running from the moment the task exists, so a Pause right after the start is not lost.
        self.run.status = "running"
        return asyncio.create_task(self._run(work, ctx))

    async def _run(self, work, ctx: Ctx) -> None:
        await self.run.started()
        try:
            await work
        except asyncio.CancelledError:
            raise
        except RunStopped:
            # Stop means stop: what was waiting for this run is not started after it.
            self.pending.clear()
            await ctx.chat("agent", "Stopped. Everything built so far stays on the bench. Tell me what to do next.")
            await ctx.emit({"type": "mascot", "state": "ruhig", "say": "Stopped. Your move."})
        except Exception as exc:
            log.exception("run failed")
            await ctx.chat("agent", "The run stopped: " + str(exc))
            await ctx.emit({"type": "mascot", "state": "besorgt", "say": "Something went wrong in the run."})
        finally:
            await self.run.finished()
        self.save_chat()
        if self.pending:
            # Messages that came in while this run was busy start the next one, also after a failure.
            text = "\n".join(self.pending)
            self.pending.clear()
            follow = self._ctx(auto_steps=claude_enabled())
            follow.trigger = "chat"
            follow.label = label_of(text)
            self.task = self._launch(run_prompt(follow, text, self.messages, record_user=False), follow)

    async def _baseline(self) -> None:
        # Every stream starts with this marker, so a client that reconnects or misses a reset starts clean.
        await self.bus.publish({"type": "reset"})
        await emit_connections(self.bus.publish)
        for step_id, label in STEPS:
            await self.bus.publish({"type": "step", "id": step_id, "status": "pending", "label": label})


def _new_state() -> BuildState:
    session_id = uuid.uuid4().hex[:8]
    directory = SESSIONS_DIR / session_id
    directory.mkdir(parents=True, exist_ok=True)
    return BuildState(session_id=session_id, directory=directory)
