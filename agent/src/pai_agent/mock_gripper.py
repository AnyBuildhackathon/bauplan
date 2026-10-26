"""Deterministic gripper demo through the same tools Claude uses.

The brief asks for a gripper that holds a 200 g can. The cheap SG90 is tried first:
the numbers say it is too weak, and the MuJoCo grip test shows the can sliding out
when the arm lifts. The swap to the MG996R passes; an object it cannot hold at twice
its weight steps up to the DS3218. Then the part is built in FreeCAD headless (servo
pocket sized for the chosen servo), rendered in Blender, weighed again and put into a
bill of materials.

A request that says where the object goes ("Gripper that puts a 400 g cube into a bowl") gets an outside judge
after that first version: Robo Use runs the built gripper on exactly that task (robouse_trial), and its verdict
lands in the version's verdict book. When it fails, the fix loop names the cause from the trial, offers two or
three fixes with AnyBuild's own grip numbers as a question, builds the chosen one as the next version and has
Robo Use judge that again; after two fix rounds the user decides. "Test it in Robo Use" on a built gripper runs
the same judge and loop. A cube without a size gets the size of one that heavy in aluminium, proposed by Mechanic.
"""

from __future__ import annotations

import copy
import re

from pai_agent.context import Ctx
from pai_agent.mock_story import _beat, _need, _safety, _say
from pai_agent.tools.cad_part import LIBRARY
from pai_agent.tools.gripper import compute_grip, gripper_catalog, jaw_opening_mm
from pai_agent.tools.registry import call_tool
from pai_agent.tools.robouse_trial import run_trial_mock

GRIPPER_WORDS = re.compile(r"\b(gripper|greifer|claw|robot ?hand|end ?effector)\b", re.IGNORECASE)
SERVO_NAMES = {"towerpro-sg90": "SG90", "towerpro-mg90s": "MG90S", "towerpro-mg996r": "MG996R", "dsservo-ds3218": "DS3218"}
# Where the request puts the object: the two goals Robo Use can judge.
_GOAL = re.compile(r"\b(?:in|into|on|onto)\s+(?:a|the|its)\s+(bowl|pad)\b", re.IGNORECASE)
_CUBE = re.compile(r"\b(cube|block)\b", re.IGNORECASE)
_CAN = re.compile(r"\bcan\b", re.IGNORECASE)
# A cube the request gives no size: as big as one that heavy in this material (g/cm³), aluminium unless it names another.
_MATERIALS = (("aluminium", r"alumin(?:i)?um", 2.70), ("steel", r"steel|iron", 7.85), ("wood", r"wood(?:en)?", 0.70), ("plastic", r"plastic|pla", 1.24))
# Fix rounds after a failed Robo Use verdict before the user decides, and how much a finger fix shortens the fingers.
FIX_ROUNDS = 2
SHORTER_BY_MM = 15.0


def wants_gripper(text: str) -> bool:
    return bool(GRIPPER_WORDS.search(text))


def placed_goal(text: str) -> str | None:
    """'puts a 400 g cube into a bowl' -> 'bowl': the request names where the object goes, a task Robo Use can judge."""

    match = _GOAL.search(text)
    return match.group(1).lower() if match else None


def cube_side(mass_g: float, text: str) -> tuple[float, str]:
    """The side in mm of a cube this heavy, and the material that assumes."""

    name, density = next(((name, density) for name, pattern, density in _MATERIALS if re.search(r"\b(?:" + pattern + r")\b", text, re.IGNORECASE)), ("aluminium", 2.70))
    return float(round((mass_g / density) ** (1.0 / 3.0) * 10.0)), name


def _brief_numbers(text: str) -> tuple[dict, str | None]:
    """Pulls '200 g', '66 mm', '150 g' style numbers from the request; the demo values fill the gaps.

    Returns the numbers and, when Mechanic sized a cube the request gave no size, the material that size assumes."""

    grams = [float(g) for g in re.findall(r"(\d+(?:\.\d+)?)\s*g\b", text)]
    mm = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*mm\b", text)] or [float(v) * 10 for v in re.findall(r"(\d+(?:\.\d+)?)\s*cm\b", text)]
    euros = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*(?:€|eur|euro)", text, re.IGNORECASE)]
    mass = grams[0] if grams else 200.0
    width, material = (mm[0], None) if mm else cube_side(mass, text) if _CUBE.search(text) else (66.0, None)
    numbers = {
        "object_mass_g": mass,
        "object_width_mm": width,
        "max_weight_g": grams[1] if len(grams) > 1 else 150.0,
        "budget_eur": euros[0] if euros else 30.0,
    }
    return numbers, material


def _noun(text: str) -> str:
    return "cube" if _CUBE.search(text) else "can" if _CAN.search(text) else "object"


async def run_gripper_mock(ctx: Ctx, text: str) -> None:
    await _beat()
    numbers, material = _brief_numbers(text)
    noun = _noun(text)
    await ctx.step("meeting", "running")
    sized = (
        f" Your request gives the cube no size: {numbers['object_mass_g']:g} g of {material} is a {numbers['object_width_mm']:g} mm cube, so that is my proposal."
        if material
        else ""
    )
    await _say(ctx, "denkt", "A gripper, not a drone. Same workshop.", "Got it: a two-finger robot gripper. I turn your request into checks first." + sized)
    await _need(ctx, "product_brief", {"product": "gripper", "quote": text.strip(), **numbers})
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": "From your request"})

    await _beat()
    await ctx.step("teile", "running")
    await _need(ctx, "catalog_search", {"category": "servo"})
    await _need(
        ctx,
        "catalog_search",
        {"category": "servo", "select_id": "towerpro-sg90", "reason": "Lightest and cheapest servo, 9 g for 2.49 €."},
    )
    await _need(ctx, "catalog_search", {"category": "pads", "select_id": "pads-tpu-printed", "reason": "Printed with the fingers, no extra part to buy."})
    await _need(ctx, "catalog_search", {"category": "hardware", "select_id": "m3-hardware-set", "reason": "M3 bolts as gear axles and for the wrist flange."})
    await _need(ctx, "catalog_search", {"category": "driver", "select_id": "pca9685-driver", "reason": "Runs the gripper servo next to the arm servos over I2C."})
    calc = await _need(ctx, "grip_calc", {})
    await _say(
        ctx,
        "besorgt",
        f"Safety only {calc['safety_factor']:.1f}x. Let's see it.",
        f"With the SG90 each finger pushes {calc['grip_force_n']:.1f} N. Friction holds {calc['hold_force_n']:.1f} N, "
        f"the {noun} weighs {numbers['object_mass_g'] / 1000 * 9.81:.1f} N. That is a safety of {calc['safety_factor']:.1f}x, I want 2x. MuJoCo will show it.",
    )

    await _beat()
    sim = await _need(ctx, "simulate_grip", {})
    if sim["result"] == "fail":
        await _need(ctx, "ui_point_at", {"target": "metrics", "label": "Grip safety too low"})
        await _say(ctx, "besorgt", "It slips. The SG90 is too weak.", sim["summary"] + " I swap the servo for the MG996R: 9.4 kg cm, metal gears.")
        await _need(
            ctx,
            "catalog_search",
            {"category": "servo", "select_id": "towerpro-mg996r", "reason": "Five times the torque of the SG90 for 6.41 € more."},
        )
        calc = await _need(ctx, "grip_calc", {})
        sim = await _need(ctx, "simulate_grip", {})
    if sim["result"] == "fail":
        await _say(ctx, "besorgt", "Still slips. More torque.", sim["summary"] + " I swap to the DS3218: 19 kg cm, twice the MG996R.")
        await _need(
            ctx,
            "catalog_search",
            {"category": "servo", "select_id": "dsservo-ds3218", "reason": "Twice the torque of the MG996R for 7.00 € more."},
        )
        calc = await _need(ctx, "grip_calc", {})
        sim = await _need(ctx, "simulate_grip", {})
    if sim["result"] == "pass":
        await _say(ctx, "freut_sich", "Holds through lift and shake.", sim["summary"])
    else:
        await _say(ctx, "besorgt", "No servo here holds it.", sim["summary"] + " There is no stronger servo in the catalog, so I build it with this one. Silicone pads or a lighter object would help.")
    servo = SERVO_NAMES[ctx.state.selected["servo"]["id"]]

    await _beat()
    await ctx.step("cad", "running")
    await _say(
        ctx,
        "erklaert",
        "Now the part in FreeCAD.",
        f"Now the body in FreeCAD, headless: palm with wrist flange, two meshing gears, fingers with TPU pads. The servo pocket follows the {servo}.",
    )
    cad = await _need(
        ctx,
        "cad_part",
        {
            "name": "Robot gripper",
            "template": "gripper",
            "description": "Two-finger gear gripper for a robot arm",
            "material": "PLA",
            "params": {"jaw_opening_mm": jaw_opening_mm(numbers["object_width_mm"]), "finger_length_mm": 70},
        },
    )
    await _need(ctx, "ui_point_at", {"target": "viewport", "label": f"Printed parts {cad['mass_g']:.0f} g"})
    calc = await _need(ctx, "grip_calc", {})

    await _beat()
    await ctx.step("render", "running")
    await call_tool(ctx, "blender_render", {})

    await _beat()
    await ctx.step("stueckliste", "running")
    await _safety(ctx)
    bom = await _need(ctx, "bom_build", {})
    await _need(ctx, "firmware", {})
    await ctx.step("stueckliste", "done")
    ctx.state.finished = True
    goal = placed_goal(text)
    if goal is None:
        await _say(
            ctx,
            "freut_sich",
            f"Gripper done: {calc['weight_g']:.0f} g, {bom['total_eur']:.2f} €.",
            f"Done. The gripper weighs {calc['weight_g']:.0f} g, holds up to {calc['max_payload_g']:.0f} g at 2x safety and costs {bom['total_eur']:.2f} € in parts. "
            "Drag the sliders in the CAD tab and FreeCAD rebuilds it.",
        )
        return
    first = ctx.state.versions[-1]["n"]
    own = f"my own grip test passes it at {calc['safety_factor']:.1f}x" if sim["result"] == "pass" else "my own grip test still fails it"
    await _say(
        ctx,
        "freut_sich" if sim["result"] == "pass" else "erklaert",
        f"v{first} is built. Now an outside judge.",
        f"Version {first} is built: {calc['weight_g']:.0f} g and {bom['total_eur']:.2f} € in parts, and {own}. "
        f"Your request says where the {noun} goes, so Robo Use, an outside benchmark, now runs this gripper on exactly that.",
    )
    await _beat()
    result = await run_trial_mock(ctx, "", goal)
    if result is not None and result.get("verdict") == "fail":
        await _close(ctx, first, await fix_loop(ctx, result, goal))


async def run_trial_story(ctx: Ctx, text: str) -> None:
    """'Test it in Robo Use': the outside verdict on the built gripper, and the fix loop when it fails."""

    goal = placed_goal(text) or "bowl"
    result = await run_trial_mock(ctx, text, goal)
    if result is not None and result.get("verdict") == "fail" and ctx.state.versions:
        first = ctx.state.versions[-1]["n"]
        await _close(ctx, first, await fix_loop(ctx, result, goal))


# The fix loop.


def _what_if(state, option: dict | None = None):
    """A copy of the bench with one fix applied, to weigh it with AnyBuild's own grip calculation; the bench stays."""

    trial = copy.copy(state)
    trial.selected = dict(state.selected)
    trial.part = {**(state.part or {}), "params": dict((state.part or {}).get("params") or {})}
    if option is not None and option["kind"] in {"servo", "pads"}:
        trial.selected[option["kind"]] = dict(option["part"])
    if option is not None and option["kind"] == "fingers":
        trial.part["params"]["finger_length_mm"] = option["finger_length_mm"]
    return trial


def fix_options(state) -> list[dict]:
    """The changes that make the fingers hold harder, each with AnyBuild's own grip numbers for it, best first.

    A stronger servo (the next one up in the catalog), grippier pads (the catalog's highest friction) and shorter
    fingers (the squeeze at the pad tips grows as the lever shrinks), each only when the bench can still take it."""

    catalog = gripper_catalog()["parts"]
    servo, pads = state.selected["servo"], state.selected["pads"]
    options: list[dict] = []
    stronger = sorted((p for p in catalog if p["category"] == "servo" and p["stall_torque_kgcm"] > servo["stall_torque_kgcm"]), key=lambda p: p["stall_torque_kgcm"])
    if stronger:
        part = stronger[0]
        name = SERVO_NAMES.get(part["id"], part["name"])
        what = f"{name} servo, {part['stall_torque_kgcm']:g} kg cm"
        options.append({"id": "servo", "kind": "servo", "part": part, "short": name + " servo", "what": what, "phrase": f"the {name} servo ({part['stall_torque_kgcm']:g} kg cm)"})
    grippier = max((p for p in catalog if p["category"] == "pads"), key=lambda p: p["friction"])
    if grippier["friction"] > pads["friction"]:
        name = "Silicone pads" if "silicone" in grippier["id"] else grippier["name"]
        what = f"{name}, friction {grippier['friction']:g}"
        options.append({"id": "pads", "kind": "pads", "part": grippier, "short": name.lower(), "what": what, "phrase": f"{name.lower()} (friction {grippier['friction']:g})"})
    length = float(((state.part or {}).get("params") or {}).get("finger_length_mm", LIBRARY["gripper"]["params"]["finger_length_mm"][0]))
    shorter = length - SHORTER_BY_MM
    if shorter >= LIBRARY["gripper"]["params"]["finger_length_mm"][1]:
        what = f"Fingers {length:g} → {shorter:g} mm"
        options.append({"id": "fingers", "kind": "fingers", "finger_length_mm": shorter, "short": f"{shorter:g} mm fingers", "what": what, "phrase": f"{shorter:g} mm fingers instead of {length:g} mm"})
    now = compute_grip(_what_if(state))
    for option in options:
        metrics = compute_grip(_what_if(state, option))
        extra = metrics["price_eur"] - now["price_eur"]
        option["safety_factor"] = metrics["safety_factor"]
        option["label"] = option["what"] + f": grip safety {metrics['safety_factor']:.1f}x, " + (f"+{extra:.2f} €" if option["kind"] != "fingers" and extra >= 0.005 else "no new parts")
    return sorted(options, key=lambda option: -option["safety_factor"])


def cause(state, result: dict) -> str:
    """Why the grip failed in Robo Use, from the trial's analysis, and why AnyBuild's own test did not catch it.

    The trial's summary has just said what happened; this says what it means for the design."""

    a = result.get("analysis") or {}
    target = "the pad" if (result.get("design") or {}).get("goal") == "pad" else "the bowl"
    own = (state.last_sim or {}).get("result") == "pass"
    if a.get("dropped") == "carry" and own:
        return (
            f"My own grip test passes it at {state.metrics.get('safety_factor', 0):.1f}x, but it only lifts, shakes and pulls the cube straight down; "
            f"Robo Use also carries it sideways to {target}, and that is where the {(a.get('lift_slip_mm') or 0):.1f} mm of slip from the lift turns into a drop."
        )
    if a.get("dropped"):
        return f"The fingers do not squeeze hard enough: the cube slides out during the {a['dropped']}."
    if not a.get("held"):
        return "The fingers never close on the cube, so there is nothing to carry."
    return f"The cube stays in the fingers but ends outside {target}."


async def fix_loop(ctx: Ctx, result: dict, goal: str) -> dict | None:
    """Up to FIX_ROUNDS fixes for a failed Robo Use verdict, each built as the next version and judged again.

    Returns the last verdict on this build, or None when Robo Use could not judge the fixed design here."""

    options: list[dict] = []
    for _round in range(FIX_ROUNDS):
        options = fix_options(ctx.state)
        if not options:
            break
        await _say(ctx, "besorgt", "Robo Use says 0. Time for a fix.", cause(ctx.state, result) + " Here is how I would grip harder; you pick.")
        n = len(ctx.state.versions) + 1
        answer = await _need(
            ctx,
            "ask_user",
            {
                "question": f"Which fix goes into v{n}? Each line is my own grip calculation; Robo Use judges v{n} again.",
                "options": [{"id": option["id"], "label": option["label"]} for option in options],
                "default_id": options[0]["id"],
            },
        )
        option = next(option for option in options if option["id"] == answer["answer_id"])
        result = await _build_fix(ctx, option, goal, n)
        if result is None or result.get("verdict") != "fail":
            return result
    last = ctx.state.versions[-1]["n"]
    await _say(
        ctx,
        "besorgt",
        "Still no pass. Your call." if options else "Nothing left to fix here. Your call.",
        cause(ctx.state, result) + (" That was my last fix round, so you decide." if options else " I have no stronger fix in the catalog, so you decide."),
    )
    answer = await _need(
        ctx,
        "ask_user",
        {
            "question": f"Robo Use still drops the cube with v{last}. What now?",
            "options": [{"id": "keep", "label": f"Keep v{last} and stop here"}, {"id": "brief", "label": "Change the brief: a lighter or smaller object"}],
            "default_id": "keep",
        },
    )
    if answer["answer_id"] == "brief":
        await ctx.chat("agent", "Tell me the new object, its weight and size, and I design the gripper for it again.")
    else:
        await ctx.chat("agent", f"v{last} stays the current version. Robo Use's verdict on it is 0, so it is not ready for this task yet.")
    return result


async def _build_fix(ctx: Ctx, option: dict, goal: str, n: int) -> dict | None:
    """The chosen fix as version n: the part swap or the new fingers in FreeCAD, AnyBuild's own grip test, the render,
    the bill of materials, the firmware, then Robo Use again."""

    state = ctx.state
    await _say(ctx, "erklaert", f"v{n}: {option['short']}.", f"Building v{n} with {option['phrase']}, then Robo Use judges it again.")
    await _beat()
    await ctx.step("teile", "running")
    if option["kind"] in {"servo", "pads"}:
        reason = f"The fix for Robo Use's verdict: {option['safety_factor']:.1f}x grip safety in my own calculation."
        await _need(ctx, "catalog_search", {"category": option["kind"], "select_id": option["part"]["id"], "reason": reason})
    # Every dimension of the bench stays, a slider move included; cad_part sizes the servo pocket for the chosen servo.
    params = {key: value for key, value in ((state.part or {}).get("params") or {}).items() if not key.startswith("servo_")}
    taken = {}
    if option["kind"] == "fingers":
        params["finger_length_mm"] = option["finger_length_mm"]
        # The user picked this fix, so it replaces a finger length they set with the slider.
        taken = {"replace_user_values": ["finger_length_mm"]}
    await ctx.step("cad", "running")
    await _need(
        ctx,
        "cad_part",
        {"name": "Robot gripper", "template": "gripper", "description": "Two-finger gear gripper for a robot arm", "material": "PLA", "params": params, **taken},
    )
    await _need(ctx, "grip_calc", {})
    sim = await _need(ctx, "simulate_grip", {})
    await _say(ctx, "freut_sich" if sim["result"] == "pass" else "besorgt", "My own test: " + ("holds." if sim["result"] == "pass" else "slips."), sim["summary"])
    await _beat()
    await ctx.step("render", "running")
    await call_tool(ctx, "blender_render", {})
    await ctx.step("stueckliste", "running")
    await _need(ctx, "safety_check", {})
    # versions.commit marks it a fix (trigger check_failed): Robo Use failed the last version in this run.
    ctx.label = "Fix for Robo Use: " + option["short"]
    await _need(ctx, "bom_build", {})
    await _need(ctx, "firmware", {})
    await ctx.step("stueckliste", "done")
    await _beat()
    return await run_trial_mock(ctx, "", goal, again=True)


async def _close(ctx: Ctx, first: int, result: dict | None) -> None:
    """The end of a fix loop: the verdicts side by side when the fix passed, or why the last version has none."""

    state = ctx.state
    last = state.versions[-1]
    if result is None:
        await _say(
            ctx,
            "erklaert",
            f"v{last['n']} is built, not judged yet.",
            f"v{last['n']} is built, but Robo Use is not installed here and there is no recorded trial of this design, so its verdict is open. "
            "Install it (cd anybuild-robouse && uv sync) and say 'Test it in Robo Use'.",
        )
        return
    if result.get("verdict") != "pass":
        return
    # Showing the comparison is a courtesy; a dashboard that cannot open it does not end the build.
    await call_tool(ctx, "ui_control", {"control": "panel:compare", "versions": [first, last["n"]], "say": f"v{first} next to v{last['n']}."})
    await _say(
        ctx,
        "freut_sich",
        f"Robo Use: v{first} 0, v{last['n']} 1.",
        f"Done. v{last['n']} puts the cube where it belongs: Robo Use scores v{first} 0 and v{last['n']} 1. "
        f"v{last['n']} weighs {last['weight_g']:.0f} g and costs {last['price_eur']:.2f} € in parts.",
    )
