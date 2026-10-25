"""The Claude tool-use loop that drives a build, and the routing of every run type into it.

`run_prompt`, `run_sketch`, `run_reference` and `run_remix` are the entry points
the session calls. With `ANTHROPIC_API_KEY` they all end in `_run_claude`: the orchestrator
model (Opus 5.5 by default, `settings.py`) gets Mechanic's system prompt, which lays out the
engineering flow for any product and the worked drone and gripper flows, plus the tool
schemas from `tools/registry.py`. `_lead_loop` then runs up to 40 rounds: each round's text is
shown in the chat, each tool call goes through `call_tool`, and the JSON results go back as
`tool_result` blocks (`is_error` when the tool returned `ok: false`, so the model reads the
error and retries with corrected arguments).

Design decisions:
- The model plans and decides, the tools compute. The prompt forbids stating any number,
  price or pass that a tool did not return, and requirement rows are recomputed from tool
  output, not from model text.
- Requirements come from what the user typed. A requirement row names the user only when its
  quote is in their request (`requirements.attribute`); anything else shows as proposed by Mechanic.
- With delegation on, the check, part-pick and pricing tools are removed from the
  orchestrator's tool list (`DELEGATED`) and reached through `delegate`, so bounded jobs run on
  a cheaper sub-agent model with only the tools they need (`agents.py`).
- Several `cad_part` calls in one round run concurrently (`_PARALLEL`): each printed part's
  script is written by its own CAD agent, so a four-part product does not wait four times.
- The system prompt and tool list are identical every round and marked for prompt caching.
- Every model call has a timeout (`PAI_MODEL_TIMEOUT_S`) and the loop a round limit, so a
  stuck model ends the run with a message instead of freezing the stage.

Without a key, the same entry points route by keywords to deterministic mock runners
(`mock_story.py`, `mock_product.py`, `mock_gripper.py`, `mock_lamp.py`, `mock_categories.py`)
that call the very same tools through the same `call_tool`, so offline runs exercise the real
CAD, MuJoCo and Blender code paths.
"""

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
from pai_agent.mock_lamp import run_lamp_mock, wants_lamp
from pai_agent.mock_product import run_product_mock, wants_product
from pai_agent.mock_story import run_mock, run_mock_followup
from pai_agent.run_control import RunStopped
from pai_agent.scene import STEPS
from pai_agent.tools.browser_train import run_mock_training
from pai_agent.tools.optimize import run_optimize_mock, run_pick_mock, wants_optimize, wants_pick
from pai_agent.tools.registry import DELEGATED, SCHEMAS, call_tool
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
Requirements come from the user's request, never from a template. Take every number the user typed as a requirement with their words as quote,
copied exactly (for example "under 150 euros" is a cost requirement with max 150 and quote "under 150 euros"; a stated weight, size, runtime or load is its own requirement).
When they named no number for something the product needs, propose a sensible limit with proposed true and your one-line reason as quote; it shows as proposed by Mechanic.
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
3. part_pick for each bought part: search with query, then select_id. The catalogs hold real parts with specs from their product pages.
   When none fits, part_pick with web true finds one on the web with validated specs; select it. Only when that fails, pass an honest estimate.
4. assemble, read the warnings (a part that floats, a part without position) and fix them with placements.
5. The checks, right after the first assembly and before you tune anything: check_totals, then the ones your requirements need
   (check_tip_over, check_deflection, check_torque, check_runtime, check_power, check_thermal, check_rollover, simulate_assembly). Every check says pass or fail against the requirements.
6. On a fail: say which requirement failed and why in one sentence, point at it with ui_point_at, then change one parameter with cad_update
   (it rebuilds, reassembles and reruns every check) or swap a bought part with part_pick, and say whether it passes now. At most three fixes.
   Never relax a requirement's limit to make it pass. If it cannot be met, ask the user with ask_user (keep trying, or accept the lower limit),
   and only then revise it with product_spec.
7. blender_render, then bom_build and print_prep, then electronics_plan when the product has electronics. End with two sentences at most: mass, cost, which requirements pass.

A reference build is a known product with its real parts. When the user asks to rebuild one, build it fresh with the live tools from the spec in the message (the drone or gripper flow, or product_spec). Do not call reference_load for that rebuild: it replays a saved run. reference_load only lists references, or, without a live key, puts a saved build on the bench. After a build is already on the bench, the user changes it:
use cad_update for dimensions, part_pick to swap a bought part, or product_spec with the revised spec for new parts or requirements
(parts whose definition did not change keep their build); then rerun the checks, blender_render, bom_build and print_prep.
Keep runs short: at most four printed parts unless the product really needs more.
Every product, the drone and the gripper too: call safety_check right before bom_build (pass the user's request and any power details in context, add your own findings).
Then say the top finding honestly in one sentence, as a hint and not legal advice, and apply its fix first when it changes the design (for example mains voltage inside a printed part).
When the user uploaded a sketch, call sketch_to_spec first, say in one sentence what you read and what you guessed, then product_spec with that spec.

The drone (any drone or quadcopter):
1. product_brief with product drone and the requirements from the request: budget, flight_time and weight with every number the user typed, each with their words as quote,
   and top_speed, turn_rate, hold_error or chase_time when the user typed a number for one (km/h, °/s, cm, s).
2. parts_search with select_id, because and reason until motor, propeller, battery, flight controller and frame are chosen, plus a camera,
   a video transmitter when the controller has none, and a canopy and hardware when the frame needs them.
   Choose for what the user asked (what the drone is for: fast, agile, precise, long flight, small and light, cheap; its size; its budget), not for a stock build.
   The library spans 65 mm whoops to 5-inch racers with real specs: pair a motor with the propeller of its load table (bench), the pack's cells with the motor's
   cells, the controller's cells and ESC current with the motors, the frame's wheelbase and motor mount with the propeller and motor.
   When the library has nothing that fits, parts_search with web true and need finds a real part on the web with validated specs; then select it.
3. physics_calc. Say the numbers that matter for the request (top speed, acceleration, turn rate, climb rate, flight time in hover and at full speed) and that they are estimates.
   On a warning (a pack that cannot feed the motors, an ESC under the motor current, a thrust figure for another propeller) swap the part and calculate again.
4. simulate_drone. On fail point at the guilty part with ui_point_at and ui_draw, swap exactly one part, recalculate and simulate again.
4b. simulate_mission with the missions the request calls for: fast or racing means speed_run and turn, agile means turn, precise, steady or filming means hold,
   hunting, catching, chasing or intercepting means chase with speed_run and turn. Pass the user's number and quote as limit when they typed one; otherwise leave limit out and Mechanic's proposal is used.
   Each mission is a requirement check. On a fail, read its why: swap the one part it names (stronger or higher-kv motor, other propeller, lighter pack) or change a dimension,
   physics_calc, then simulate_mission again with only the failed missions, and say in one sentence what changed and why. At most three fixes; never lower a limit to pass.
5. cad_frame in FreeCAD. arm_length_mm runs from the centre to the motor shaft, the propellers need clearance. motor_spacing_mm is the motor bolt circle, 6.6 for the 1103 (the pads take the chosen motor's own bolt circle).
   The model is built from the chosen parts: motors, propellers, pack and board at their real sizes, so the 3D view, the simulation and the bill of materials show one drone.
   After swapping a part, run cad_frame again so the model matches, then simulate_mission again if a mission depends on it.
6. physics_calc again, because the frame now has a real mass.
7. blender_render.
8. safety_check, bom_build (it saves the version), print_prep, build_guide, firmware, electronics_plan. End with mass, flight time, cost and which requirements pass.
A change to a built drone: product_brief again with the revised requirements when the user changes a limit (the parts stay), parts_search to swap a part,
then from physics_calc to bom_build as above, with simulate_mission again for the missions already run. Name the difference in weight, flight time and price at the end.
The motor thrust is the datasheet value; a higher cell voltage creates no extra thrust.
A catalog motor sits four times in the scene; for the motor type point at motor_front_left.
Asked to make the built drone lighter, cheaper, longer-running or stronger, or for options and trade-offs: optimize_design with the goals and the limits to keep,
then name the recommended variant and what each trade costs, and let the user click a point; optimize_apply builds the pick when they choose one.

The robot gripper (gripper, claw, end effector): product_brief with product gripper, object_mass_g, object_width_mm, max_weight_g, budget_eur and quote.
Then catalog_search with select_id for servo, pads, hardware and driver, grip_calc, simulate_grip. On fail, swap to a stronger servo and test again.
Then cad_part with template gripper (params jaw_opening_mm at least object width plus 10, finger_length_mm), grip_calc again, blender_render, bom_build, firmware.
Asked to stress test the build or how robust it is: stress_test (after training it flies the trained gains), then mascot_say with its explanation and name the score in English.

Omniverse requests: use isaac_test for gusty wind, a camera/payload mass or hover stability.
These tools and product_usd support the drone only. For a gripper, use simulate_grip and explain that the GPU hover controller does not support it.
Build CAD and select the parts first when a live product test needs them. USD export happens automatically.
Use isaac_train for Isaac Lab reinforcement learning; it trains the stock Crazyflie reference task.
The tools return finished MP4 and JSON artifacts, so no polling or live stream is needed.
Read source and status: recorded means no GPU pod answered and nothing was measured for this request.
Then say in one calm sentence that the GPU is not connected and offer the MuJoCo checks instead; do not quote the recorded values.
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


async def run_prompt(ctx: Ctx, text: str, messages: list[dict], voice: bool = False, *, record_user: bool = True) -> None:
    if record_user:
        await ctx.chat("user", text, voice)
    ctx.state.requests.append(text)
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
        if wants_pick(text) and ctx.state.optimize:
            await run_pick_mock(ctx, wants_pick(text))
            return
        if wants_optimize(text) and ctx.state.product == "drone" and not wants_gripper(text) and (ctx.state.selected or _DRONE.search(text)):
            await run_optimize_mock(ctx, text)
            return
        if wants_gripper(text) and not (ctx.state.product == "gripper" and ctx.state.finished):
            await run_gripper_mock(ctx, text)
            return
        if wants_lamp(text) and not (ctx.state.product == "generic" and (ctx.state.spec or {}).get("name") == "Desk lamp"):
            await run_lamp_mock(ctx, text)
            return
        category = wants_category(text)
        if category and not (ctx.state.product == "generic" and ctx.state.finished and (ctx.state.spec or {}).get("name") == CATEGORY_NAMES[category]):
            await CATEGORY_RUNS[category](ctx, text)
            return
        if wants_product(text) and not (ctx.state.product == "generic" and ctx.state.finished):
            await run_product_mock(ctx, text)
            return
        if wants_stress(text, ctx.state.finished):
            await run_stress_mock(ctx)
        elif ctx.state.product == "drone" and (ctx.state.finished or (not first and (ctx.state.sim_run or ctx.state.selected))):
            await run_mock_followup(ctx, text)
        else:
            await run_mock(ctx, text)
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


_DRONE = re.compile(r"\b(drone|quad\w*)\b", re.IGNORECASE)
_TRAIN = re.compile(r"\btrain|\btrainier", re.IGNORECASE)
_OMNIVERSE = re.compile(r"\b(omniverse|isaac)\b", re.IGNORECASE)
_TRAIN_THEN_STRESS = re.compile(r"\btrain\w*\b.*\b(then|and|before)\b.*\bstress", re.IGNORECASE)


def wants_train_then_stress(text: str) -> bool:
    """One prompt that asks for a training run followed by a stress test."""

    return bool(_TRAIN_THEN_STRESS.search(text))

async def run_sketch(ctx: Ctx, name: str, note: str, messages: list[dict]) -> None:
    """The photo of a hand sketch starts a product: sketch_to_spec reads it, product_spec and the any-product flow build it."""

    await _first(ctx)
    await ctx.chat("user", "Build this from my sketch" + (": " + note if note else "."))
    if note:
        ctx.state.requests.append(note)
    if not claude_enabled():
        await run_product_mock(ctx, note, sketch=True)
        return
    text = "The user uploaded a sketch (" + name + ")" + (": " + note if note else "") + ". Read it with sketch_to_spec, then build it with product_spec and the normal flow."
    await _run_claude(ctx, text, messages)


async def run_reference(ctx: Ctx, ref_id: str, messages: list[dict] | None = None) -> None:
    """Start from a library reference.

    With a live key this is a fresh orchestrator run from that reference's spec and parts.
    Without a key, or with PAI_FORCE_MOCK, the saved build plays and the chat says it is offline.
    """

    from pai_agent.references import build_reference, reference_brief

    await _first(ctx)
    visible, model = reference_brief(ref_id)
    await ctx.chat("user", visible)
    # Rebuilding a reference takes its request and limits as the user's own.
    ctx.state.requests.append(model)
    if not claude_enabled():
        await ctx.chat("agent", "Offline: rebuilding the saved build without the live model.")
        await ctx.step("meeting", "running")
        await _on_bench(ctx, await build_reference(ctx, ref_id))
        return
    await _run_claude(ctx, model, [] if messages is None else messages)


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
    from pai_agent.agents import AgentRun

    config = settings.current()
    delegation = bool(config["delegation"])
    lead = AgentRun(ctx, "orchestrator", "Orchestrator", config["orchestrator_model"], config["orchestrator_effort"], text.strip()[:120])
    if not messages and ((ctx.state.product == "generic" and ctx.state.spec) or (ctx.state.finished and ctx.state.selected)):
        # A build Claude did not make (a loaded reference): it reads the build before the request.
        from pai_agent.references import build_context

        text = build_context(ctx.state) + text
    _add_request(messages, text)
    ctx.lead_id = lead.id
    # The first planning round takes a while; the person sees at once that Mechanic is on it.
    await ctx.emit({"type": "mascot", "state": "denkt", "say": "On it, thinking it through."})
    try:
        await _lead_loop(ctx, lead, delegation, messages)
    except RunStopped:
        _close_stopped(messages)
        await lead.emit("done", "stopped by the user after " + str(lead.rounds) + " round(s)")
        raise
    finally:
        ctx.lead_id = None


_STOPPED = {"ok": False, "error": "The user stopped the run before this tool ran."}


def _results(tool_uses: list, outcomes: list[dict]) -> list[dict]:
    """One tool_result per tool_use; a tool without an outcome was stopped before it ran."""

    return [
        {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": json.dumps(result, ensure_ascii=False, default=str),
            "is_error": result.get("ok") is False,
        }
        for block, result in zip(tool_uses, [*outcomes, *[_STOPPED] * (len(tool_uses) - len(outcomes))])
    ]


def _close_stopped(messages: list[dict]) -> None:
    """Leaves the conversation valid after Stop, so the next message continues it.

    Every tool_use gets a tool_result (the stopped ones say so), and a short assistant turn records the stop.
    """

    last = messages[-1] if messages else None
    if last and last["role"] == "assistant" and isinstance(last["content"], list):
        uses = [block for block in last["content"] if isinstance(block, dict) and block.get("type") == "tool_use"]
        if uses:
            note = json.dumps(_STOPPED)
            messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": block["id"], "content": note, "is_error": True} for block in uses]})
    if messages and messages[-1]["role"] == "user":
        messages.append({"role": "assistant", "content": "The user stopped this run here; what was built so far stays."})


def _add_request(messages: list[dict], text: str) -> None:
    """Adds the request so the history stays valid after a run that failed or was stopped midway."""

    last = messages[-1] if messages else None
    if last and last["role"] == "assistant":
        # Tool calls that never got their results (the run stopped) are answered as stopped.
        stopped = [
            {"type": "tool_result", "tool_use_id": block["id"], "content": "Stopped before it finished.", "is_error": True}
            for block in last["content"]
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        if stopped:
            messages.append({"role": "user", "content": stopped})
            last = messages[-1]
    if last and last["role"] == "user":
        # The request after a failed round joins the unanswered turn instead of a second user turn.
        content = last["content"]
        last["content"] = (content if isinstance(content, list) else [{"type": "text", "text": content}]) + [{"type": "text", "text": text}]
        return
    messages.append({"role": "user", "content": text})


async def _lead_loop(ctx: Ctx, lead, delegation: bool, messages: list[dict]) -> None:
    from pai_agent.agents import stream_round

    async def say(text: str) -> None:
        # Each text block reaches the chat as soon as it is written, not when the round ends.
        if text.strip():
            await ctx.chat("agent", text.strip())

    await lead.emit("running", "plans the build")
    for _round in range(40):
        await ctx.checkpoint()
        try:
            response = await stream_round(
                lead.model,
                lead.effort,
                say,
                max_tokens=16000,
                system=_system(delegation),
                tools=_tools(delegation),
                messages=messages,
            )
        except Exception as exc:
            log.exception("anthropic call failed")
            await lead.emit("error", str(exc)[:160])
            await ctx.chat("agent", "The model request failed: " + str(exc) + ". Send your request again.")
            await call_tool(
                ctx,
                "mascot_say",
                {"state": "besorgt", "say": "The model is not answering."},
            )
            return
        lead.count(response)
        blocks = list(response.content)
        tool_uses = [block for block in blocks if getattr(block, "type", None) == "tool_use"]
        # Thinking blocks go back unchanged, the model reads them on the next round.
        messages.append({"role": "assistant", "content": [_dump(block) for block in blocks]})
        if not tool_uses:
            await lead.emit("done", "finished in " + str(lead.rounds) + " round(s)")
            return
        doing = ", ".join(block.name for block in tool_uses)[:120]
        if len(tool_uses) > 1 and all(block.name in _PARALLEL for block in tool_uses):
            await lead.use(tool_uses[0].name, doing)
            outcomes = await asyncio.gather(
                *(call_tool(ctx, block.name, block.input if isinstance(block.input, dict) else {}) for block in tool_uses),
                return_exceptions=True,
            )
            # They pass the same checkpoint together; one Stop stops them all.
            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    raise outcome
            for block, outcome in zip(tool_uses, outcomes):
                lead.called(block.name, outcome)
        else:
            outcomes = []
            try:
                for block in tool_uses:
                    await lead.use(block.name, doing)
                    outcomes.append(await call_tool(ctx, block.name, block.input if isinstance(block.input, dict) else {}))
                    lead.called(block.name, outcomes[-1])
            except RunStopped:
                # The tools that ran keep their real results; the rest say they were stopped.
                messages.append({"role": "user", "content": _results(tool_uses, outcomes)})
                raise
        # What the person said while these tools ran reaches the model with their results.
        heard = [{"type": "text", "text": "The person said while you worked: " + text} for text in ctx.take_pending()]
        messages.append({"role": "user", "content": _results(tool_uses, outcomes) + heard})
        await lead.emit("running", "reads the results")
    await lead.emit("done", "stopped after 40 rounds")
    await ctx.chat("agent", "I am stopping after 40 tool rounds so the run does not hang.")


def _dump(block: object) -> dict:
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True)
    return dict(block)
