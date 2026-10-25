"""Deterministic demo. Same tools as the Claude loop, fixed choices.

The first build arrives at the reference micro build, the $59 toothpick from Mediocre Nerd's
"Build a Micro FPV Drone" video: Twiglet 2" carbon frame, 1103 15000KV motors, Gemfan 2020
four-blade props, Caddx Ant camera, BetaFPV Matrix 1S 5in1 AIO, canopy with battery holder,
M1.4 bolts and a 1S pack. The requirements come from the typed request (`limits_from_text`):
run_mock builds v1 to them, run_mock_followup builds the next version when a later message
changes a limit ("make it fly 10 minutes"). A MockTeam stands for the orchestrator: it fans the
parts, CAD, pricing and checks jobs out to sub-agents, as the live orchestrator delegates them.
"""

from __future__ import annotations

import asyncio
import math
import re

from pai_agent import printers
from pai_agent.env import pace_seconds
from pai_agent.context import Ctx
from pai_agent.mock_team import MockTeam, build_jobs, parts_job
from pai_agent.tools.build_guide import mock_steps
from pai_agent.tools.registry import call_tool

# The request the library's micro drone and the optimizer stand on when nobody typed one.
DEFAULT_REQUEST = "Build a micro drone under 120 euros with at least 8 minutes of flight time, under 50 g."

# The Twiglet's arm, centre to motor shaft, from its ~85 mm wheelbase: 2" props need 39 mm.
TWIGLET_ARM_MM = 42.5
# What the agent tries first, to keep the quad compact; the 51 mm props touch there.
COMPACT_ARM_MM = 34.0
FRAME_PLATE_MM = 2.0
MOTOR_BOLT_CIRCLE_MM = 6.6

_WORDS = {"five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "fifty": 50, "hundred": 100}
_NUMBER = r"(\d+(?:[.,]\d+)?|" + "|".join(_WORDS) + r")"
_LIMITS = (
    ("budget", re.compile(r"(?:(?:under|below|less than|at most|max(?:imum)?|within|for)\s+)?(?:€\s*" + _NUMBER + r"|" + _NUMBER + r"\s*(?:euros?|eur\b|€))", re.I)),
    ("flight_time", re.compile(r"(?:(?:at least|min(?:imum)?|for|fly(?:ing)?|of)\s+)?" + _NUMBER + r"\s*(?:minutes?|mins?\b)", re.I)),
    ("weight", re.compile(r"(?:under|below|less than|at most|max(?:imum)?|lighter than)\s+" + _NUMBER + r"\s*(?:grams?|g\b)", re.I)),
    # Mission limits (simulate_mission): speed, turn rate, hold precision, catch time.
    ("top_speed", re.compile(r"(?:(?:at least|over|above|faster than|min(?:imum)?|up to|reach(?:es)?|of)\s+)?" + _NUMBER + r"\s*(?:km/?h|kph)\b", re.I)),
    ("turn_rate", re.compile(r"(?:(?:at least|over|min(?:imum)?)\s+)?" + _NUMBER + r"\s*(?:°|deg(?:rees)?)\s*(?:/|per)\s*(?:s|sec(?:ond)?)\b", re.I)),
    ("hold_error", re.compile(r"(?:within|to|under|below|at most)\s+" + _NUMBER + r"\s*(?:cm|centimet(?:er|re)s?)\b", re.I)),
    ("chase_time", re.compile(r"(?:catch\w*|chas\w*|intercept\w*)\b[^.]*?(?:in|within|under)\s+" + _NUMBER + r"\s*(?:s|secs?|seconds?)\b", re.I)),
)
# What a request asks the drone to do, in words: the missions that test it (see the orchestrator prompt).
_MISSION_WORDS = (
    ("chase", re.compile(r"\b(hunt\w*|catch\w*|chas\w*|intercept\w*|pursu\w*)", re.I)),
    ("speed_run", re.compile(r"\b(fast\w*|speed\w*|quick\w*|rac(?:e|er|ing)|hunt\w*|catch\w*|chas\w*|intercept\w*)", re.I)),
    ("turn", re.compile(r"\b(agil\w*|nimble|turn\w*|fast\w*|rac(?:e|er|ing)|hunt\w*|catch\w*|chas\w*|intercept\w*)", re.I)),
    ("hold", re.compile(r"\b(precis\w*|steady|stable|hold\w*|hover\w* still|film\w*|inspect\w*)", re.I)),
)
_MISSION_ORDER = ("speed_run", "turn", "hold", "chase")


def _number(raw: str) -> float:
    word = raw.strip().lower()
    return float(_WORDS[word]) if word in _WORDS else float(word.replace(",", "."))


def limits_from_text(text: str) -> list[dict]:
    """product_brief requirements from a typed request, each quoting the words it came from."""

    found = []
    for rid, pattern in _LIMITS:
        match = pattern.search(text or "")
        if match:
            raw = next(group for group in match.groups() if group)
            found.append({"id": rid, "limit": _number(raw), "quote": match.group(0).strip()})
    return found


def missions_from_text(text: str) -> list[str]:
    """The mission tests a request calls for, in a fixed order; none for a request that names no task."""

    wanted = {mission for mission, pattern in _MISSION_WORDS if pattern.search(text or "")}
    for limit in limits_from_text(text):
        wanted |= {mission for mission, rid in _MISSION_LIMITS.items() if rid == limit["id"]}
    return [mission for mission in _MISSION_ORDER if mission in wanted]


_MISSION_LIMITS = {"speed_run": "top_speed", "turn": "turn_rate", "hold": "hold_error", "chase": "chase_time"}


def en(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


async def _thicken_until_strong(ctx: Ctx, cad: dict, arm: float) -> dict:
    """A printed frame that fails its FEM gets a thicker plate: bending stress falls with the square of the thickness."""

    thickness = FRAME_PLATE_MM
    for _attempt in range(3):
        row = ctx.state.checks.get("fem:frame")
        if not row or row["result"] != "fail" or thickness >= 6.0:
            break
        before = thickness
        thickness = min(6.0, math.ceil(thickness * math.sqrt(row["limit"] / max(row["safety"], 0.01)) * 1.05 * 2) / 2)
        await _say(
            ctx,
            "erklaert",
            f"Thicker plate: {before:g} to {thickness:g} mm.",
            f"Bending stress falls with the square of the plate thickness, so {before:g} to {thickness:g} mm should lift {row['safety']:.1f}x past {row['limit']:g}x. FreeCAD rebuilds it, CalculiX runs again.",
        )
        cad = await _need(ctx, "cad_frame", {"arm_length_mm": arm, "thickness_mm": thickness, "motor_spacing_mm": MOTOR_BOLT_CIRCLE_MM})
        row = ctx.state.checks.get("fem:frame")
        if row:
            await _say(
                ctx,
                "freut_sich" if row["result"] == "pass" else "besorgt",
                f"Now {row['safety']:.1f}x." + (" Holds." if row["result"] == "pass" else ""),
                f"FEM again at {thickness:g} mm: safety {row['safety']:.1f}x in the {row['governing']} case, "
                + ("it holds." if row["result"] == "pass" else f"still under {row['limit']:g}x."),
            )
    return cad


async def _beat() -> None:
    delay = pace_seconds()
    if delay:
        await asyncio.sleep(delay)


async def _need(ctx: Ctx, name: str, args: dict) -> dict:
    result = await call_tool(ctx, name, args)
    if result.get("ok") is False:
        raise RuntimeError(result.get("error") or name)
    return result


async def _say(ctx: Ctx, state: str, say: str, chat: str | None = None) -> None:
    await _need(ctx, "mascot_say", {"state": state, "say": say})
    await ctx.chat("agent", chat or say)


async def _safety(ctx: Ctx, context: str = "") -> dict:
    """safety_check before the parts are ordered; Mechanic names the top finding as a hint."""

    result = await _need(ctx, "safety_check", {"context": context} if context else {})
    top = result.get("top")
    if top:
        mood = "besorgt" if top["severity"] == "danger" else "erklaert"
        await _say(ctx, mood, top["title"] + ".", "Safety check before ordering: " + top["title"] + ". " + top["fix"] + " A hint, not legal advice; the card names the rule.")
    return result


def _numbers(metrics: dict) -> str:
    return (
        en(metrics["weight_g"], 1)
        + " g, thrust-to-weight "
        + en(metrics["thrust_to_weight"], 2)
        + ", "
        + en(metrics["flight_time_min"], 1)
        + " min, "
        + en(metrics["price_eur"], 2)
        + " €"
    )


def _part(part_id: str) -> dict:
    from pai_agent.tools.parts import catalog

    return next(p for p in catalog()["parts"] if p["id"] == part_id)


async def _pick(ctx: Ctx, category: str, query: str, part_id: str, reason: str, because: str = "") -> None:
    args = {"category": category, "query": query, "select_id": part_id, "reason": reason}
    if because:
        args["because"] = because
    await _need(ctx, "parts_search", args)


def _passes(ctx: Ctx) -> str:
    rows = ctx.state.requirements
    passed = sum(1 for r in rows if r.get("_met") is True)
    return str(passed) + " of " + str(len(rows)) + " requirements pass"


async def _build_tail(ctx: Ctx, label: str, team: MockTeam) -> dict:
    """Frame in FreeCAD, real frame mass, Blender, bill of materials and the version it commits."""

    return await team.alongside(build_jobs(label), _build(ctx, label))


async def _build(ctx: Ctx, label: str) -> dict:
    await _beat()
    await ctx.step("cad", "running")
    arm = float(ctx.state.cad_params.get("arm_length_mm") or 0)
    if not arm:
        await _say(
            ctx,
            "erklaert",
            "FreeCAD, compact frame first. Watch this.",
            "Now the Twiglet frame in FreeCAD: "
            + en(COMPACT_ARM_MM, 0)
            + " mm from the centre to the motor shaft, "
            + en(FRAME_PLATE_MM, 0)
            + " mm carbon, a "
            + en(MOTOR_BOLT_CIRCLE_MM, 1)
            + " mm bolt circle for the 1103s.",
        )
        tight = await call_tool(ctx, "cad_frame", {"arm_length_mm": COMPACT_ARM_MM, "thickness_mm": FRAME_PLATE_MM, "motor_spacing_mm": MOTOR_BOLT_CIRCLE_MM})
        if tight.get("ok") is False:
            await _say(
                ctx,
                "besorgt",
                "Too tight. The props would high-five. Fixing.",
                tight["error"] + " I take the Twiglet's " + en(TWIGLET_ARM_MM, 1) + " mm arm, the 2-inch frame from the video.",
            )
        arm = TWIGLET_ARM_MM
    cad = await _need(ctx, "cad_frame", {"arm_length_mm": arm, "thickness_mm": FRAME_PLATE_MM, "motor_spacing_mm": MOTOR_BOLT_CIRCLE_MM})
    await ctx.step("cad", "done")
    from pai_agent.mock_printer import printed_parts

    # With the user's printer the frame is printed: motors run near 60 °C and a whoop crashes a lot.
    await printed_parts(ctx, [("frame", {"max_temp_c": 60, "impact": True})])
    cad = await _thicken_until_strong(ctx, cad, arm)
    printed = printers.printed_frame(ctx.state)
    if printed:
        cad = {**cad, "mass_g": printed["mass_g"]}
    await _need(ctx, "ui_point_at", {"target": "frame", "label": "Frame " + en(cad["mass_g"], 1) + " g"})
    metrics = await _need(ctx, "physics_calc", {})
    await ctx.chat(
        "agent",
        ("FreeCAD" if cad["source"] == "freecad" else "CadQuery")
        + " weighs the "
        + (printed["material"] + " printed" if printed else "carbon")
        + " frame at "
        + en(cad["mass_g"], 1)
        + " g. With the real parts: "
        + _numbers(metrics)
        + ".",
    )

    await _beat()
    await ctx.step("render", "running")
    rendered = await _need(ctx, "blender_render", {})
    await ctx.step("render", "done")
    if rendered.get("status") == "offline":
        await _say(ctx, "ruhig", "No Blender on this machine. The STEP file proves the frame anyway.")
    else:
        await _say(ctx, "erklaert", "Blender rendered " + label + " in the studio.")

    await _beat()
    await ctx.step("stueckliste", "running")
    await _safety(ctx)
    # bom_build commits the version.
    await _need(ctx, "bom_build", {})
    await call_tool(ctx, "print_prep", {"orientation": "as_modeled"})
    await _need(ctx, "build_guide", {"steps": mock_steps(ctx)})
    await _need(ctx, "firmware", {})
    await call_tool(ctx, "electronics_plan", {})
    await ctx.step("stueckliste", "done")
    return ctx.state.versions[-1]


async def _first_picks(ctx: Ctx) -> None:
    motor = _part("generic-1103-15000kv")
    await _pick(ctx, "motor", "1103", motor["id"], "The micro-class motor, " + en(float(motor["thrust_g"]), 0) + " g thrust per motor on 1S.", "hover")
    await _pick(ctx, "propeller", "2020", "gemfan-2020-4", "The 2-inch four-blade the 1103 thrust figure is measured with.", "hover")
    await _pick(ctx, "battery", "FunFly", "tattu-funfly-4s-1300", "1300 mAh looks like plenty of flight time. I check that.", "flight_time")
    controller = _part("betafpv-matrix-1s-5in1-v2")
    await _pick(
        ctx,
        "flight_controller",
        "Matrix",
        controller["id"],
        "Flight controller, four ESCs, ELRS receiver and video transmitter on one board, " + en(float(controller["mass_g"]), 1) + " g.",
        "weight",
    )
    await _pick(ctx, "frame", "Twiglet", "twiglet-2in-carbon", "The 2-inch carbon toothpick frame; I model it in FreeCAD for STL and STEP.", "printable")
    await _pick(ctx, "camera", "Caddx", "caddx-ant", "Nano FPV camera that fits the canopy.")
    await _pick(ctx, "canopy", "canopy", "toothpick-canopy-holder", "Holds the camera and the 1S pack under the frame.")
    await _pick(ctx, "hardware", "M1.4", "m14-bolts", "Motor bolts, 3 mm, so they stop short of the windings.")


async def run_mock(ctx: Ctx, text: str = "") -> None:
    async with MockTeam(ctx, "build the drone from the request") as team:
        await _first_build(ctx, text, team)


async def _first_build(ctx: Ctx, text: str, team: MockTeam) -> None:
    request = text.strip()
    if not request:
        # The library and the optimizer start from the reference request, taken as the user's.
        request = DEFAULT_REQUEST
        ctx.state.requests.append(request)
    await _beat()
    await ctx.step("meeting", "running")
    if not re.search(r"\b(drone|quad\w*|copter|fpv|whoop)\b", request, re.I):
        await ctx.chat("agent", "Offline demo without the live model: I can only build the sample micro drone, so that is what you get.")
    await _say(ctx, "denkt", "Your numbers first. Then the parts.")
    brief = await _need(ctx, "product_brief", {"product": "drone", "requirements": limits_from_text(request)})
    typed = [r for r in brief["requirements"] if r["source"] == "user"]
    lines = "\n".join("- " + r["text"] for r in brief["requirements"])
    await ctx.chat(
        "agent",
        (str(len(typed)) + " requirement" + ("" if len(typed) == 1 else "s") + " from your request" if typed else "No numbers in your request")
        + ", plus what every drone needs:\n\n"
        + lines,
    )
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": "Your requirements"})
    await ctx.step("meeting", "done")

    await _beat()
    await ctx.step("teile", "running")
    await _say(ctx, "denkt", "Everyone grabs a big battery for flight time. That is the trap.")
    await team.alongside(
        [
            parts_job(
                "pick the bought parts for the 1S toothpick",
                ["1103 15000KV motors", "Gemfan 2020 props", "FunFly 4S battery", "Matrix 1S 5in1 AIO", "frame, camera, canopy and bolts"],
                "8 parts picked. The FunFly 4S looks like flight time; the checks decide.",
            )
        ],
        _first_picks(ctx),
    )
    first = await _need(ctx, "physics_calc", {})
    battery_g = float(ctx.state.selected["battery"]["mass_g"])
    await ctx.chat("agent", "First pass: " + _numbers(first) + ". The battery alone weighs " + en(battery_g, 1) + " g. " + " ".join(first["warnings"]))

    await _beat()
    await ctx.step("simulation", "running")
    failed = await _need(ctx, "simulate_drone", {})
    await ctx.step("simulation", "failed")
    await _say(
        ctx,
        "besorgt",
        "Downdraft test: failed. Spectacularly. The battery is a brick.",
        "At thrust-to-weight " + en(failed["thrust_to_weight"], 2) + " there is no reserve for the gust. The battery is the brick.",
    )
    await _need(ctx, "ui_point_at", {"target": "battery", "label": ctx.state.selected["battery"]["name"]})
    await _need(ctx, "ui_draw", {"kind": "halo", "target": "battery", "text": "too heavy"})
    await _need(ctx, "ui_draw", {"kind": "arrow", "target": "battery", "text": en(battery_g, 1) + " g"})
    await _need(ctx, "ui_draw", {"kind": "circle", "target": "battery", "text": "4S on 1S motors"})
    await _need(
        ctx,
        "ui_draw",
        {"kind": "note", "target": "battery", "text": "thrust " + en(first["thrust_g"], 0) + " g, mass " + en(first["weight_g"], 0) + " g"},
    )

    await _beat()
    await ctx.step("teile", "running")
    pack = _part("tattu-rline-1s-550")
    await _say(
        ctx,
        "erklaert",
        "Dropping the 4S. Same motors, smarter battery.",
        "I only swap the battery: "
        + pack["name"]
        + ", "
        + en(float(pack["mass_g"]), 1)
        + " g, "
        + en(float(pack["voltage_v"]), 1)
        + " V. The 1103s stay; their thrust figure is for exactly this voltage.",
    )
    await _pick(ctx, "battery", "R-Line", pack["id"], en(float(pack["mass_g"]), 0) + " g instead of 150 g, and 1S suits the motors.", "weight")
    second = await _need(ctx, "physics_calc", {})
    await ctx.step("teile", "done")
    await ctx.chat("agent", "New: " + _numbers(second) + ". The flight time is a hover estimate from the data sheets, not a logbook.")

    await _beat()
    await ctx.step("simulation", "running")
    passed = await _need(ctx, "simulate_drone", {})
    if passed.get("result") != "pass":
        raise RuntimeError("The second MuJoCo run should hover: " + passed.get("summary", ""))
    await ctx.step("simulation", "done")
    await _say(ctx, "freut_sich", "Second run holds the gust. Told you.")
    await _need(ctx, "ui_draw", {"kind": "halo", "target": "battery", "text": "fits"})
    await _swap_pack(ctx)
    await _missions(ctx, missions_from_text(request))

    version = await _build_tail(ctx, "v1", team)
    await _say(
        ctx,
        "freut_sich",
        "Mark 1, done. Tell me what to change.",
        "Version 1: " + version["summary"] + ", " + _passes(ctx) + ". Shop prices are from 2026-10-24; check them before ordering. Tell me what to change, for example a longer flight time.",
    )
    ctx.state.finished = True


async def _missions(ctx: Ctx, missions: list[str]) -> None:
    """The mission tests the request calls for, flown with the final parts; each judges one requirement."""

    if not missions:
        return
    await _beat()
    await ctx.step("simulation", "running")
    names = {"speed_run": "a speed run", "turn": "a hard turn", "hold": "a position hold in wind", "chase": "a chase of five dodging flies"}
    await _say(
        ctx,
        "erklaert",
        "Now the job itself. Missions in MuJoCo.",
        "Your request is a job, so I fly it: " + ", ".join(names[m] for m in missions) + ". Mass, inertia, thrust and drag come from the parts I picked.",
    )
    flown = await _need(ctx, "simulate_mission", {"missions": [{"mission": m} for m in missions]})
    await _need(ctx, "ui_control", {"control": "tab:simulation"})
    failed = [m for m in flown["missions"] if m["result"] == "fail"]
    await ctx.step("simulation", "failed" if failed else "done")
    if failed:
        worst = failed[0]
        await _say(ctx, "besorgt", "Mission check: not all green.", worst["summary"] + " " + worst["why"] + " The offline catalog has no stronger part for this; with the live model I would search for one.")
    else:
        await _say(ctx, "freut_sich", "All missions pass.", "All " + str(len(flown["missions"])) + " missions pass with these parts; the card has the numbers and every replay is in the Simulation tab.")


async def _swap_pack(ctx: Ctx) -> bool:
    """A flight time the 550 pack cannot reach takes the bigger 1S pack; the motors stay."""

    target = next((r for r in ctx.state.requirements if r["id"] == "flight_time"), None)
    if not target or float(target.get("min", 0)) <= float(ctx.state.metrics.get("flight_time_min", 0)):
        return False
    bigger = _part("betafpv-lava-1s-680")
    if ctx.state.selected.get("battery", {}).get("id") == bigger["id"]:
        return False
    await _need(ctx, "parts_search", {"category": "battery", "query": ""})
    await _say(
        ctx,
        "denkt",
        "More flight time means more battery. But not the 4S brick.",
        "For " + en(float(target["min"]), 0) + " minutes I need more capacity. I stay at 1S and take the " + bigger["name"] + ", the other pack from the video.",
    )
    await _pick(
        ctx,
        "battery",
        "680",
        bigger["id"],
        en(float(bigger["capacity_mah"]), 0) + " mAh for " + en(float(target["min"]), 0) + " minutes, " + en(float(bigger["mass_g"]), 1) + " g, still 1S.",
        "flight_time",
    )
    metrics = await _need(ctx, "physics_calc", {})
    await ctx.chat("agent", "Computed: " + _numbers(metrics) + ".")
    run = await _need(ctx, "simulate_drone", {})
    await ctx.step("simulation", "done" if run["result"] == "pass" else "failed")
    return True


async def run_mock_followup(ctx: Ctx, text: str = "") -> None:
    if not ctx.state.finished:
        await _say(
            ctx,
            "besorgt",
            "The last run stopped halfway. Reset once.",
            "Reset the session and send the sentence again. I do not build on half a state.",
        )
        return
    changes = limits_from_text(text)
    if not changes:
        await _say(
            ctx,
            "ruhig",
            "The version is done. Give me a new number.",
            "The version is done. Tell me a new limit, for example \"make it fly 10 minutes\" or \"under 100 euros\", and I rebuild and show the difference.",
        )
        return
    async with MockTeam(ctx, "build the next version from your change") as team:
        await _next_version(ctx, changes, team)


async def _next_version(ctx: Ctx, changes: list[dict], team: MockTeam) -> None:
    state = ctx.state
    state.finished = False
    await _beat()
    await ctx.step("meeting", "running")
    await _say(ctx, "denkt", "New numbers. Let me see what that breaks.")
    # The typed change wins over the earlier limit of the same kind; the others stay.
    keep = [
        {"id": r["id"], "limit": r.get("min", r.get("max")), "quote": r["source_quote"], "proposed": r.get("source") == "proposed"}
        for r in state.requirements
        if r["id"] in {"budget", "flight_time", "weight"} and r["id"] not in {c["id"] for c in changes}
    ]
    await _need(ctx, "product_brief", {"product": "drone", "requirements": keep + changes})
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": "Your change"})
    await ctx.step("meeting", "done")

    await _beat()
    await ctx.step("teile", "running")
    await team.alongside(
        [parts_job("find a pack for the new flight time", ["1S packs with more capacity", "BetaFPV LAVA II 1S 680"], "LAVA II 1S 680 fits: more capacity, still 1S, the motors stay.")],
        _swap_pack(ctx),
    )
    await ctx.step("teile", "done")
    # The missions already flown fly again with the new parts.
    await _missions(ctx, [m for m in _MISSION_ORDER if m in state.missions])
    run = state.last_sim or {}
    if run.get("result") == "pass":
        await _say(ctx, "freut_sich", "Longer in the air and still holds the gust. You are welcome.")
    elif run:
        await _say(ctx, "besorgt", "Gust wins this round. Back to the parts.")

    version = await _build_tail(ctx, "v" + str(len(state.versions) + 1), team)
    changes_shown = [item for item in version["diff"] if item["key"] in {"weight_g", "flight_time_min", "price_eur"}]
    digits = {"weight_g": 1, "flight_time_min": 1, "price_eur": 2}
    parts = ", ".join(
        item["label"] + " " + en(item["before"], digits[item["key"]]) + " → " + en(item["after"], digits[item["key"]]) + " " + item["unit"]
        for item in changes_shown
    )
    await _need(ctx, "ui_point_at", {"target": "metrics", "label": "v" + str(version["n"])})
    await _say(
        ctx,
        "freut_sich",
        "v" + str(version["n"]) + " is done. The difference is on the card.",
        "Version " + str(version["n"]) + ": " + (parts or version["summary"]) + ". " + _passes(ctx) + ".",
    )
    state.finished = True
