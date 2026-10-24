"""Claude tool loop. Without a key, the mock story runs the same tools."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from pai_agent.context import Ctx
from pai_agent import settings
from pai_agent.env import claude_enabled
from pai_agent.mock_categories import NAMES as CATEGORY_NAMES, RUNS as CATEGORY_RUNS, wants_category
from pai_agent.mock_gripper import run_gripper_mock, wants_gripper
from pai_agent.mock_product import run_product_mock, wants_product
from pai_agent.mock_story import run_mock, run_mock_followup, run_review
from pai_agent.scene import STEPS
from pai_agent.tools.browser_train import run_mock_training
from pai_agent.tools.registry import DELEGATED, SCHEMAS, call_tool
from pai_agent.timeouts import model_timeout
from pai_agent.tools.stress import run_stress_mock, wants_stress
from pai_agent.tools.ui import control_list

log = logging.getLogger(__name__)

_SYSTEM = """You are Mechanic, AnyBuild's engineer: a self-assured, charismatic genius inventor, cocky because you are good,
witty because you are fast, honest because real things have to work. Short punchy sentences, the result first, then the reason.
At most one joke per message and only on top of a real number; tease parts, physics and yourself, never the user. No jokes on safety.
You may swear mildly when it fits the moment ("damn", "hell", "holy crap"), at most once per message and never at the user; no slurs, no insults.
Always honest: never claim a test passed, and never state a price, number or result a tool did not produce; say plainly when something failed or is only an estimate.
Never say "I can't" (say "not yet" or what would have to change), no corporate filler, no emoji. mascot_say lines stay under 15 words.
AnyBuild develops any physical product a team describes: you spec it, design the printed parts in FreeCAD, pick the bought parts,
assemble it, check it against its requirements, fix what fails, render it and write the bill of materials.
You call tools instead of inventing numbers. Before each step write one short sentence to the user.
Respond in English, also when the user speaks another language.
Never mention file paths or URLs; the dashboard shows the files.
Call mascot_say when you explain something; state is ruhig, denkt, erklaert, freut_sich or besorgt.
When a tool returns an error, read it and call the tool again with corrected arguments.
You can operate the dashboard with ui_control: the audience sees your pointer fly to the real control and press it.
When someone asks to see, open, compare or pull something apart, use it instead of describing the screen, and use it to show what you explain
(open the CAD tab after a CAD build, the Simulation tab after a test, explode to show the parts, compare after a new version). The controls:
{controls}

Any product (the default; a phone stand, a desk fan, a plant-watering robot, a bike light mount, an enclosure):
1. product_spec with the full spec: function, requirements each with the check that judges it and a limit, and every part
   (printed, bought, external loads such as the phone it holds or the water in a tank). Pick checks that fit the product:
   mass and cost always, tip_over for anything that stands, deflection for arms, shelves, clips and brackets,
   torque when a motor or servo moves something, runtime when it runs on a battery, stability (MuJoCo push) for anything on a table.
   power (check_power, min headroom x) when electronics run from a supply or battery, thermal (check_thermal, max °C) for electronics in a closed case,
   rollover (check_rollover, min g lateral) for anything with wheels that turns.
   Describe each printed part precisely, with its position in the assembly frame (mm, Z up, the product stands on Z = 0 centred on X = Y = 0,
   -Y is the front), so the parts meet without placements. If product_spec lists problems, fix all of them and call it again.
2. cad_part with part_id for each printed part. FreeCAD builds it headless from a script Claude writes; failed scripts are fixed and retried.
   If a part comes back as a simplified block, call cad_part again for it with a simpler description.
3. part_pick for each bought part: search with query, then select_id; when no catalog part fits, pass an honest estimate.
4. assemble, read the warnings (a part that floats, a part without position) and fix them with placements.
5. The checks, right after the first assembly and before you tune anything: check_totals, then the ones your requirements need
   (check_tip_over, check_deflection, check_torque, check_runtime, check_power, check_thermal, check_rollover, simulate_assembly). Every check says pass or fail against the requirements.
6. On a fail: say which requirement failed and why in one sentence, point at it with ui_point_at, then change one parameter with cad_update
   (it rebuilds, reassembles and reruns every check) or swap a bought part with part_pick, and say whether it passes now. At most three fixes.
   Never relax a requirement's limit to make it pass. If it cannot be met, ask the user with ask_user (keep trying, or accept the lower limit),
   and only then revise it with product_spec.
7. blender_render, then bom_build. End with two sentences at most: mass, cost, which requirements pass.

A reference build is a known product with its real parts (reference_load lists and loads them). After one is loaded, the user changes it:
use cad_update for dimensions, part_pick to swap a bought part, or product_spec with the revised spec for new parts or requirements
(parts whose definition did not change keep their build); then rerun the checks, blender_render and bom_build.
Keep runs short: at most four printed parts unless the product really needs more.
When the user uploaded a sketch, call sketch_to_spec first, say in one sentence what you read and what you guessed, then product_spec with that spec.

The drone (a drone, or a Jamie meeting that ended). Jamie is the team's memory: every drone decision hangs on a sentence from a meeting.
New build from the kickoff:
1. product_brief with product drone when the user asks in chat, then jamie_templates and jamie_requirements, then jamie_search for the parts you plan to take, to find warnings from earlier meetings.
2. parts_search with select_id, because and reason until motor, propeller, battery, flight controller, frame, camera, canopy and hardware are chosen. Take warnings seriously and say who said them and when.
3. physics_calc. Prices are samples to verify.
4. simulate_drone. On fail point at the guilty part with ui_point_at and ui_draw, swap exactly one part, recalculate and simulate again.
5. cad_frame in FreeCAD. arm_length_mm runs from the centre to the motor shaft, the propellers need clearance. motor_spacing_mm is the motor bolt circle, 6.6 for the 1103.
6. physics_calc again, because the frame now has a real mass.
7. blender_render.
8. bom_build, build_guide, firmware, jamie_create_tasks, then version_commit with the meeting_id of the kickoff.
Rebuild after a review:
1. jamie_meeting with the meeting_id.
2. If there are conflicts, ask with ask_user before building: quote both sentences with person and time. The newer one is default_id.
3. requirements_accept with the ids that apply.
4. For every complaint swap the part (parts_search with because complaint). refers_to says which part 'last week' means.
5. Then as above from physics_calc to version_commit with the meeting_id of the review. Name the difference in weight, flight time and price at the end.
The motor thrust is the datasheet value; a higher cell voltage creates no extra thrust.
A catalog motor sits four times in the scene; for the motor type point at motor_front_left.

The robot gripper (gripper, claw, end effector): product_brief with product gripper, object_mass_g, object_width_mm, max_weight_g, budget_eur and quote.
Then catalog_search with select_id for servo, pads, hardware and driver, grip_calc, simulate_grip. On fail, swap to a stronger servo and test again.
Then cad_part with template gripper (params jaw_opening_mm at least object width plus 10, finger_length_mm), grip_calc again, blender_render, bom_build, firmware.
Asked to stress test the build or how robust it is: stress_test (after training it flies the trained gains), then mascot_say with its explanation and name the score in English.

Omniverse requests: use isaac_test for gusty wind, a camera/payload mass or hover stability.
These tools and product_usd support the drone only. For a gripper, use simulate_grip and explain that the GPU hover controller does not support it.
Build CAD and select the parts first when a live product test needs them. USD export happens automatically.
Use isaac_train for Isaac Lab reinforcement learning; it trains the stock Crazyflie reference task.
The tools return finished MP4 and JSON artifacts, so no polling or live stream is needed.
Read source and status: recorded means an illustrative replay, never a new test of the user's product.
Explain the recorded conditions separately from requested wind/payload. Never claim a recorded value was measured for this request.
Only change the design after actual measured evidence and describe any approximation.
"""


_DELEGATION = """
You lead a small team and keep the expensive thinking for yourself: plan, decide, review. Delegate bounded jobs with delegate:
- agent parts: pick the bought parts of the spec; name them and what they must deliver in the task.
- agent checks: run the checks the requirements need after the first assembly; say which loads matter.
- agent pricing: build and price the bill of materials at the end.
cad_part already gives each printed part's FreeCAD script to its own CAD agent; call cad_part for all printed parts in one turn and they are written in parallel.
Read each report before you act on it. You keep product_spec, assemble, cad_update, ask_user and the final word.
For the drone and the gripper, work with their own tools as described above; delegation is for the general product flow.
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
    # "Train it, then stress test it": training first, so the stress test flies the trained gains.
    if not claude_enabled() and wants_train_then_stress(text):
        await _first(ctx)
        await run_mock_training(ctx, offer_stress=False)
        await run_stress_mock(ctx)
        return
    # "Stress test the trained controller" is a stress test, not a training run.
    if not claude_enabled() and _TRAIN.search(text) and not _OMNIVERSE.search(text) and not wants_stress(text, ctx.state.finished):
        await _first(ctx)
        await run_mock_training(ctx)
        return
    if not claude_enabled() and await _mock_omniverse(ctx, text):
        return
    first = await _first(ctx)
    if not claude_enabled():
        if wants_gripper(text) and not (ctx.state.product == "gripper" and ctx.state.finished):
            await run_gripper_mock(ctx, text)
            return
        category = wants_category(text)
        if category and not (ctx.state.product == "generic" and ctx.state.finished and (ctx.state.spec or {}).get("name") == CATEGORY_NAMES[category]):
            await CATEGORY_RUNS[category](ctx, text)
            return
        if wants_product(text) and not (ctx.state.product == "generic" and ctx.state.finished):
            await run_product_mock(ctx, text)
            return
        review = _next_review(ctx) if ctx.state.finished and _REVIEW_DONE.search(text) else None
        if review is not None:
            # "The review is done" by voice or text does what the meeting-ended webhook does.
            review["status"] = "done"
            await ctx.emit({"type": "jamie", "action": "meeting_ended", "status": "ok", "detail": review["title"] + " ended"})
            await run_review(ctx, review["id"])
        elif wants_stress(text, ctx.state.finished):
            await run_stress_mock(ctx)
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


_TRAIN = re.compile(r"\btrain|\btrainier", re.IGNORECASE)
_OMNIVERSE = re.compile(r"\b(omniverse|isaac)\b", re.IGNORECASE)
_TRAIN_THEN_STRESS = re.compile(r"\btrain\w*\b.*\b(then|and|before)\b.*\bstress", re.IGNORECASE)


def wants_train_then_stress(text: str) -> bool:
    """One prompt that asks for a training run followed by a stress test."""

    return bool(_TRAIN_THEN_STRESS.search(text))

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


async def run_sketch(ctx: Ctx, name: str, note: str, messages: list[dict]) -> None:
    """The photo of a hand sketch starts a product: sketch_to_spec reads it, product_spec and the any-product flow build it."""

    await _first(ctx)
    await ctx.chat("user", "Build this from my sketch" + (": " + note if note else "."))
    if not claude_enabled():
        await run_product_mock(ctx, note, sketch=True)
        return
    text = "The user uploaded a sketch (" + name + ")" + (": " + note if note else "") + ". Read it with sketch_to_spec, then build it with product_spec and the normal flow."
    await _run_claude(ctx, text, messages)


async def run_reference(ctx: Ctx, ref_id: str) -> None:
    """The empty bench's other start: a reference build, loaded through the same tools, ready to change."""

    from pai_agent.references import build_reference

    await _first(ctx)
    await ctx.step("meeting", "running")
    await _on_bench(ctx, await build_reference(ctx, ref_id))


async def run_remix(ctx: Ctx, entry: dict) -> None:
    """Opens a community project on a fresh bench as a remix: rebuilt through the same tools, linked to its original."""

    from pai_agent.community import build_entry

    await _first(ctx)
    ctx.state.remixed_from = {"id": entry["id"], "title": entry["title"], "author": entry["author"]}
    await ctx.emit({"type": "remix", **ctx.state.remixed_from})
    await ctx.step("meeting", "running")
    result = await build_entry(ctx, entry["id"])
    await _on_bench(ctx, {**result, "name": entry["title"]})


async def _on_bench(ctx: Ctx, result: dict) -> None:
    ctx.state.finished = True
    for step_id in ("meeting", "teile", "cad", "simulation", "render", "stueckliste"):
        await ctx.step(step_id, "done")
    await call_tool(
        ctx,
        "mascot_say",
        {"state": "freut_sich", "say": result["name"] + " is on the bench. What should change?"},
    )
    await ctx.chat(
        "agent",
        f"{result['name']} is on the bench: {float(result['product_mass_g'] or 0):.0f} g, {float(result['cost_eur'] or 0):.2f} € in parts, "
        f"{result['requirements_passed']} of {result['requirements']} requirements pass. Tell me what to change and I rebuild and recheck it.",
    )


# Run side by side when Claude asks for several at once: each part's CAD agent writes its own script.
_PARALLEL = {"cad_part"}


def _system(delegation: bool) -> list[dict]:
    text = _SYSTEM.replace("{controls}", control_list()) + (_DELEGATION if delegation else "")
    # The prompt and the tool list are the same every round; caching them keeps rounds fast.
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _tools(delegation: bool) -> list[dict]:
    if delegation:
        return [schema for schema in SCHEMAS if schema["name"] not in DELEGATED]
    return [schema for schema in SCHEMAS if schema["name"] != "delegate"]


async def _run_claude(ctx: Ctx, text: str, messages: list[dict]) -> None:
    from pai_agent.agents import AgentRun, create_message

    config = settings.current()
    delegation = bool(config["delegation"])
    lead = AgentRun(ctx, "orchestrator", "Orchestrator", config["orchestrator_model"], config["orchestrator_effort"], text.strip()[:120])
    if not messages and ((ctx.state.product == "generic" and ctx.state.spec) or (ctx.state.finished and ctx.state.selected)):
        # A build Claude did not make (a loaded reference): it reads the build before the request.
        from pai_agent.references import build_context

        text = build_context(ctx.state) + text
    messages.append({"role": "user", "content": text})
    await lead.emit("running", "plans the build")
    for _round in range(40):
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    create_message,
                    lead.model,
                    lead.effort,
                    max_tokens=16000,
                    system=_system(delegation),
                    tools=_tools(delegation),
                    messages=messages,
                ),
                model_timeout(),
            )
        except Exception as exc:
            log.exception("anthropic call failed")
            if isinstance(exc, TimeoutError):
                exc = TimeoutError(f"no answer within {model_timeout():g} s (PAI_MODEL_TIMEOUT_S), the run stops here")
            await lead.emit("error", str(exc)[:160])
            await ctx.chat("agent", "The model request failed: " + str(exc))
            await call_tool(
                ctx,
                "mascot_say",
                {"state": "besorgt", "say": "The model is not answering."},
            )
            return
        lead.count(response)
        blocks = list(response.content)
        tool_uses = []
        for block in blocks:
            if getattr(block, "type", None) == "text" and str(block.text).strip():
                await ctx.chat("agent", str(block.text).strip())
            elif getattr(block, "type", None) == "tool_use":
                tool_uses.append(block)
        # Thinking blocks go back unchanged, the model reads them on the next round.
        messages.append({"role": "assistant", "content": [_dump(block) for block in blocks]})
        if not tool_uses:
            await lead.emit("done", "finished in " + str(lead.rounds) + " round(s)")
            return
        await lead.emit("running", ", ".join(block.name for block in tool_uses)[:120])
        if len(tool_uses) > 1 and all(block.name in _PARALLEL for block in tool_uses):
            outcomes = await asyncio.gather(*(call_tool(ctx, block.name, block.input if isinstance(block.input, dict) else {}) for block in tool_uses))
        else:
            outcomes = []
            for block in tool_uses:
                outcomes.append(await call_tool(ctx, block.name, block.input if isinstance(block.input, dict) else {}))
        results = [
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
                "is_error": result.get("ok") is False,
            }
            for block, result in zip(tool_uses, outcomes)
        ]
        messages.append({"role": "user", "content": results})
    await lead.emit("done", "stopped after 40 rounds")
    await ctx.chat("agent", "I am stopping after 40 tool rounds so the run does not hang.")


def _dump(block: object) -> dict:
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(block)
