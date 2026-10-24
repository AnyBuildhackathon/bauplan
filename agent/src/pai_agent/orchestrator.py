"""Claude tool loop. Without a key, the mock story runs the same tools."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from pai_agent.context import Ctx
from pai_agent.env import claude_enabled, model_name
from pai_agent.mock_story import run_mock, run_mock_followup, run_review
from pai_agent.scene import STEPS
from pai_agent.tools.registry import SCHEMAS, call_tool

log = logging.getLogger(__name__)

_SYSTEM = """Du bist Bolzen, ein ehrlicher, etwas großspuriger Mentor-Roboter.
Du baust eine kleine Drohne und erklärst jeden Schritt auf Deutsch, in kurzen Sätzen.
Du rufst Werkzeuge auf, statt Zahlen zu erfinden. Jamie ist euer Gedächtnis: jede Entscheidung hängt an einem Satz aus einem Meeting.

Neuer Bau aus dem Kickoff:
1. jamie_templates, dann jamie_requirements. Danach jamie_search nach den Teilen, die du nehmen willst, um Warnungen aus früheren Meetings zu finden.
2. parts_search mit select_id, because und reason, bis Motor, Propeller, Akku, Flugregler und Rahmen gewählt sind. Nimm Warnungen ernst und sag, wer sie wann gesagt hat.
3. physics_calc. Preise sind Stichproben zum Prüfen.
4. simulate_drone. Bei fail zeigst du mit ui_point_at und ui_draw auf das schuldige Teil, tauschst genau ein Teil, rechnest neu und simulierst neu.
5. cad_frame in FreeCAD. arm_length_mm ist die Strecke von der Mitte zur Motorwelle, die Propeller brauchen Luft zueinander. motor_spacing_mm ist der Lochkreis der Motorschrauben, beim 1102 sind das 6,6.
6. physics_calc noch einmal, weil der Rahmen dann eine echte Masse hat.
7. blender_render.
8. bom_build, jamie_create_tasks, dann version_commit mit der meeting_id des Kickoffs.

Neubau nach einem Review:
1. jamie_meeting mit der meeting_id.
2. Gibt es conflicts, fragst du mit ask_user nach, bevor du baust: zitiere beide Sätze mit Person und Uhrzeit. Die neuere Vorgabe ist default_id.
3. requirements_accept mit den ids, die gelten.
4. Für jede Beschwerde tauschst du das Teil (parts_search mit because complaint). refers_to sagt, welches Teil 'letzte Woche' gemeint ist.
5. Dann wie oben ab physics_calc bis version_commit mit der meeting_id des Reviews. Nenne am Ende die Differenz in Gewicht, Flugzeit und Preis.

Der Motor-Schub ist der Datenblattwert. Eine höhere Zellenspannung erzeugt keinen extra Schub.
Ein Katalog-Motor sitzt viermal in der Szene. Für den Motortyp zeigst du auf motor_front_left.
Ruf mascot_say, wenn du etwas erklärst. state ist ruhig, denkt, erklaert, freut_sich oder besorgt.
Wenn ein Werkzeug einen Fehler zurückgibt, lies ihn und ruf es mit korrigierten Argumenten noch einmal auf.
"""


async def _first(ctx: Ctx) -> bool:
    first = not ctx.state.started
    if first:
        ctx.state.started = True
        for step_id, _label in STEPS:
            await ctx.step(step_id, "pending")
    return first


async def run_prompt(ctx: Ctx, text: str, messages: list[dict]) -> None:
    await ctx.chat("user", text)
    first = await _first(ctx)
    if not claude_enabled():
        review = _next_review(ctx) if ctx.state.finished and _REVIEW_DONE.search(text) else None
        if review is not None:
            # "Das Review ist durch" by voice or text does what the meeting-ended webhook does.
            review["status"] = "done"
            await ctx.emit({"type": "jamie", "action": "meeting_ended", "status": "ok", "detail": review["title"] + " ist zu Ende"})
            await run_review(ctx, review["id"])
        elif ctx.state.finished or (not first and (ctx.state.sim_run or ctx.state.selected)):
            await run_mock_followup(ctx)
        else:
            await run_mock(ctx)
        return
    await _run_claude(ctx, text, messages)


_REVIEW_DONE = re.compile(
    r"\b(review|meeting)\b.*\b(durch|vorbei|zu ende|fertig|beendet|aus)\b|\b(bau|baue)\b.*\bneu\b",
    re.IGNORECASE,
)


def _next_review(ctx: Ctx) -> dict | None:
    pending = [m for m in ctx.state.meetings.values() if m["kind"] == "review" and m["status"] != "done"]
    return sorted(pending, key=lambda m: (m["date"], m["time"]))[0] if pending else None


async def run_meeting(ctx: Ctx, meta: dict, messages: list[dict]) -> None:
    """A meeting ended in Jamie. The kickoff builds v1; a review rebuilds from the current version."""

    review = meta["kind"] == "review"
    if review and not ctx.state.versions:
        # A review without a first version: build v1 from the kickoff first.
        kickoff = next((m for m in ctx.state.meetings.values() if m["kind"] == "kickoff"), None)
        if kickoff is not None:
            await run_meeting(ctx, kickoff, messages)
    await _first(ctx)
    title = meta["title"]
    if review:
        text = "Das Meeting „" + title + "“ ist zu Ende (meeting_id " + meta["id"] + "). Lies es und bau die nächste Version."
    else:
        text = "Das Meeting „" + title + "“ ist zu Ende (meeting_id " + meta["id"] + "). Bau die kleine Drohne aus dem Kickoff."
    await ctx.emit({"type": "jamie", "action": "meeting_ended", "status": "ok", "detail": title + " ist zu Ende"})
    if not claude_enabled():
        if review:
            await run_review(ctx, meta["id"])
        else:
            await run_mock(ctx, meta["id"])
        return
    await _run_claude(ctx, text, messages)


async def _run_claude(ctx: Ctx, text: str, messages: list[dict]) -> None:
    import anthropic

    client = anthropic.Anthropic()
    messages.append({"role": "user", "content": text})
    for _round in range(30):
        try:
            response = await asyncio.to_thread(
                client.messages.create,
                model=model_name(),
                max_tokens=1500,
                system=_SYSTEM,
                tools=SCHEMAS,
                messages=messages,
            )
        except Exception as exc:
            log.exception("anthropic call failed")
            await ctx.chat("agent", "Die Modellanfrage ist fehlgeschlagen: " + str(exc))
            await call_tool(
                ctx,
                "mascot_say",
                {"state": "besorgt", "say": "Das Modell antwortet nicht."},
            )
            return
        blocks = list(response.content)
        tool_uses = []
        for block in blocks:
            if getattr(block, "type", None) == "text" and str(block.text).strip():
                await ctx.chat("agent", str(block.text).strip())
            elif getattr(block, "type", None) == "tool_use":
                tool_uses.append(block)
        messages.append({"role": "assistant", "content": [_dump(block) for block in blocks]})
        if not tool_uses:
            return
        results = []
        for block in tool_uses:
            raw = block.input if isinstance(block.input, dict) else {}
            result = await call_tool(ctx, block.name, raw)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                    "is_error": result.get("ok") is False,
                }
            )
        messages.append({"role": "user", "content": results})
    await ctx.chat("agent", "Ich stoppe nach 30 Werkzeugrunden, damit der Lauf nicht hängt.")


def _dump(block: object) -> dict:
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(block)
