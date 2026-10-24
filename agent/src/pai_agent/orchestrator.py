"""Claude tool loop. Without a key, the mock story runs the same tools."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from pai_agent.context import Ctx
from pai_agent.env import claude_enabled, model_name
from pai_agent.mock_gripper import run_gripper_mock, wants_gripper
from pai_agent.mock_story import run_mock, run_mock_followup, run_review
from pai_agent.scene import STEPS
from pai_agent.tools.registry import SCHEMAS, call_tool

log = logging.getLogger(__name__)

_SYSTEM = """You are Bolzen, AnyBuild's engineering agent. Help develop physical products; the drone is the demo example.
Respond in English, in short sentences, including when the user speaks another language.
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

AnyBuild builds more than drones. Pick the product from the request:
- A drone or a meeting that ended: the flow above (call product_brief with product drone first when the user asks in chat).
- A robot gripper (gripper, claw, end effector): product_brief with product gripper, object_mass_g, object_width_mm, max_weight_g, budget_eur and quote.
  Then catalog_search with select_id for servo, pads, hardware and driver, grip_calc, simulate_grip. On fail, swap to a stronger servo and test again.
  Then cad_part with template gripper (params jaw_opening_mm at least object width plus 10, finger_length_mm), grip_calc again, blender_render, bom_build.
- Any other part (a mount, an enclosure, a bracket, an adapter): cad_part with name, a precise description, params in mm and material. FreeCAD builds it headless;
  if the script fails, cad_part fixes and retries it. Report mass, size and material, then blender_render.
For anything that is not the drone, answer in English.

Der Motor-Schub ist der Datenblattwert. Eine höhere Zellenspannung erzeugt keinen extra Schub.
Ein Katalog-Motor sitzt viermal in der Szene. Für den Motortyp zeigst du auf motor_front_left.
Ruf mascot_say, wenn du etwas erklärst. state ist ruhig, denkt, erklaert, freut_sich oder besorgt.
Wenn ein Werkzeug einen Fehler zurückgibt, lies ihn und ruf es mit korrigierten Argumenten noch einmal auf.

Omniverse requests: use isaac_test for gusty wind, a camera/payload mass or hover stability.
These tools and product_usd support the drone only. For a gripper, use simulate_grip and explain that the GPU hover controller does not support it.
Build CAD and select the parts first when a live product test needs them. USD export happens automatically.
Use isaac_train for Isaac Lab reinforcement learning; it trains the stock Crazyflie reference task.
The tools return finished MP4 and JSON artifacts, so no polling or live stream is needed.
Read source and status: recorded means an illustrative replay, never a new test of the user's product.
Explain the recorded conditions separately from requested wind/payload. Never claim a recorded value was measured for this request.
Only change the design after actual measured evidence and describe any approximation.
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
    if not claude_enabled() and await _mock_omniverse(ctx, text):
        return
    first = await _first(ctx)
    if not claude_enabled():
        if wants_gripper(text) and not (ctx.state.product == "gripper" and ctx.state.finished):
            await run_gripper_mock(ctx, text)
            return
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


async def _mock_omniverse(ctx: Ctx, text: str) -> bool:
    """Exercise the real tool dispatch without an LLM key in the offline demo."""
    if not re.search(r"\b(omniverse|isaac|gusty|gusts?|wind|payload|hover stability|train|training)\b|\d\s*g\s+camera", text, re.I):
        return False
    training = bool(re.search(r"\b(train|training|learn|policy)\b", text, re.I))
    payload = re.search(r"(\d+(?:\.\d+)?)\s*g\b", text, re.I)
    wind = re.search(r"(\d+(?:\.\d+)?)\s*m/s\b", text, re.I)
    args = {} if training else {"scenario": "payload" if payload else "wind" if re.search(r"wind|gust", text, re.I) else "hover"}
    if payload and not training:
        args["payload_g"] = float(payload[1])
    if wind and not training:
        args["wind_m_s"] = float(wind[1])
    result = await call_tool(ctx, "isaac_train" if training else "isaac_test", args)
    explanation = result.get("detail") or result.get("error") or "Omniverse job finished."
    if result.get("source") == "live" and result.get("status") == "done":
        metrics = result["metrics"]
        if training:
            explanation += f" Final mean reward: {metrics['final_reward']:.2f}. This is the stock Crazyflie reference policy."
        else:
            outcome = "passed" if result["passed"] else "failed"
            explanation += f" Hover criteria {outcome}: error {metrics['hover_rmse_m']:.3f} m, peak tilt {metrics['max_tilt_deg']:.1f} degrees, lateral drift {metrics['max_drift_m']:.3f} m."
    await ctx.chat("agent", explanation)
    return True


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
                max_tokens=4000,
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
