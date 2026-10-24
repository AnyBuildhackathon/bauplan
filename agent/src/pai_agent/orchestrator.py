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

_SYSTEM = """You are Mechanic, AnyBuild's engineering agent. Help develop physical products; the drone is the worked example.
Respond in English, in short sentences, including when the user speaks another language.
You call tools instead of inventing numbers. Jamie is the team's memory: every decision hangs on a sentence from a meeting.

New build from the kickoff:
1. jamie_templates, then jamie_requirements. Then jamie_search for the parts you want, to find warnings from earlier meetings.
2. parts_search with select_id, because and reason, until motor, propeller, battery, flight controller and frame are chosen. Take warnings seriously and say who said them, and when.
3. physics_calc. Prices are samples to check.
4. simulate_drone. On fail, point at the guilty part with ui_point_at and ui_draw, swap exactly one part, recalculate and simulate again.
5. cad_frame in FreeCAD. arm_length_mm is the distance from the center to the motor shaft. The propellers need clearance. motor_spacing_mm is the bolt circle of the motor screws. On the 1102 that is 6.6.
6. physics_calc again, because the frame then has a real mass.
7. blender_render.
8. bom_build, build_guide, jamie_create_tasks, then version_commit with the kickoff meeting_id.

Rebuild after a review:
1. jamie_meeting with the meeting_id.
2. If there are conflicts, ask with ask_user before you build: quote both sentences with person and time. The newer requirement is default_id.
3. requirements_accept with the ids that apply.
4. For each complaint, swap the part (parts_search with because complaint). refers_to says which part 'last week' means.
5. Then continue as above from physics_calc through version_commit with the review meeting_id. At the end, name the difference in weight, flight time and price.

AnyBuild builds more than drones. Pick the product from the request:
- A drone or a meeting that ended: the flow above (call product_brief with product drone first when the user asks in chat).
- A robot gripper (gripper, claw, end effector): product_brief with product gripper, object_mass_g, object_width_mm, max_weight_g, budget_eur and quote.
  Then catalog_search with select_id for servo, pads, hardware and driver, grip_calc, simulate_grip. On fail, swap to a stronger servo and test again.
  Then cad_part with template gripper (params jaw_opening_mm at least object width plus 10, finger_length_mm), grip_calc again, blender_render, bom_build.
- Any other part (a mount, an enclosure, a bracket, an adapter): cad_part with name, a precise description, params in mm and material. FreeCAD builds it headless;
  if the script fails, cad_part fixes and retries it. Report mass, size and material, then blender_render.
For anything that is not the drone, answer in English.

Motor thrust is the datasheet value. A higher cell voltage does not create extra thrust.
A catalog motor sits four times in the scene. For the motor type, point at motor_front_left.
Call mascot_say when you explain something. state is ruhig, denkt, erklaert, freut_sich or besorgt.
If a tool returns an error, read it and call the tool again with corrected arguments.

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
            # "The review is done" by voice or text does what the meeting-ended webhook does.
            review["status"] = "done"
            await ctx.emit({"type": "jamie", "action": "meeting_ended", "status": "ok", "detail": review["title"] + " ended"})
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
    r"\b(review|meeting)\b.*\b(durch|vorbei|zu ende|fertig|beendet|aus|done|over|ended|finished)\b|\b(bau|baue|rebuild|build)\b.*\b(neu|again)\b",
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
        text = "The meeting “" + title + "” has ended (meeting_id " + meta["id"] + "). Read it and build the next version."
    else:
        text = "The meeting “" + title + "” has ended (meeting_id " + meta["id"] + "). Build the small drone from the kickoff."
    await ctx.emit({"type": "jamie", "action": "meeting_ended", "status": "ok", "detail": title + " ended"})
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
            await ctx.chat("agent", "The model request failed: " + str(exc))
            await call_tool(
                ctx,
                "mascot_say",
                {"state": "besorgt", "say": "The model is not answering."},
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
    await ctx.chat("agent", "I am stopping after 30 tool rounds so the run does not hang.")


def _dump(block: object) -> dict:
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(block)
