"""Deterministic demo. Same tools as the Claude loop, fixed choices.

The kickoff arrives at the reference micro build, the $59 toothpick from Mediocre Nerd's
"Build a Micro FPV Drone" video: Twiglet 2" carbon frame, 1103 15000KV motors, Gemfan 2020
four-blade props, Caddx Ant camera, BetaFPV Matrix 1S 5in1 AIO, canopy with battery holder,
M1.4 bolts and a 1S pack. run_mock builds v1 from the kickoff, run_review builds the next
version from a review.
"""

from __future__ import annotations

import asyncio

from pai_agent.env import pace_seconds
from pai_agent.context import Ctx
from pai_agent.meetings import fmt_number, short_date
from pai_agent.tools.build_guide import mock_steps
from pai_agent.tools.registry import call_tool

_UNITS = {"Minuten": "min", "minutes": "min"}

# The Twiglet's arm, centre to motor shaft, from its ~85 mm wheelbase: 2" props need 39 mm.
TWIGLET_ARM_MM = 42.5
# What the agent tries first, to keep the quad compact; the 51 mm props touch there.
COMPACT_ARM_MM = 34.0
FRAME_PLATE_MM = 2.0
MOTOR_BOLT_CIRCLE_MM = 6.6


def en(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


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


def _who(quote: dict) -> str:
    """'Ben at 20:06', or just 'Ben' when the transcript has no times."""

    return quote["speaker"] + (" at " + quote["time"] if quote.get("time") else "")


def _unit(raw: str) -> str:
    return _UNITS.get(raw, raw)


def _part(part_id: str) -> dict:
    from pai_agent.tools.parts import catalog

    return next(p for p in catalog()["parts"] if p["id"] == part_id)


async def _pick(ctx: Ctx, category: str, query: str, part_id: str, reason: str, because: str = "") -> None:
    args = {"category": category, "query": query, "select_id": part_id, "reason": reason}
    if because:
        args["because"] = because
    await _need(ctx, "parts_search", args)


async def _build_tail(ctx: Ctx, meeting_id: str, label: str) -> dict:
    """Frame in FreeCAD, real frame mass, Blender, bill of materials, Jamie tasks, version."""

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
    await _need(ctx, "ui_point_at", {"target": "frame", "label": "Frame " + en(cad["mass_g"], 1) + " g"})
    metrics = await _need(ctx, "physics_calc", {})
    await ctx.chat(
        "agent",
        ("FreeCAD" if cad["source"] == "freecad" else "CadQuery")
        + " weighs the carbon frame at "
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
    await _need(ctx, "bom_build", {})
    await _need(ctx, "build_guide", {"steps": mock_steps(ctx)})
    await _need(ctx, "firmware", {})
    tasks = await _need(ctx, "jamie_create_tasks", {"meeting_id": meeting_id})
    version = await _need(ctx, "version_commit", {"meeting_id": meeting_id})
    await ctx.step("stueckliste", "done")
    version["tasks"] = tasks
    return version


async def run_mock(ctx: Ctx, meeting_id: str = "") -> None:
    await _beat()
    await ctx.step("meeting", "running")
    await _say(ctx, "denkt", "Meeting first. Guessing is for people without Jamie.")
    await _need(ctx, "jamie_templates", {})
    requirements = await _need(ctx, "jamie_requirements", {"meeting_id": meeting_id})
    kickoff_id = requirements["meeting_id"]
    await ctx.chat(
        "agent",
        str(len(requirements["requirements"]))
        + " requirements from “"
        + requirements["title"]
        + "”. Budget, flight time and weight are in the Hardware-Anforderungen template, each with the sentence and who said it. I created the kickoff and review templates in Jamie myself.",
    )
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": requirements["title"]})
    motors = await _need(ctx, "jamie_search", {"query": "1103"})
    funfly = await _need(ctx, "jamie_search", {"query": "FunFly"})
    warned = any(meeting["quotes"] for meeting in funfly["meetings"])
    if motors["meetings"] and warned:
        await _say(
            ctx,
            "erklaert",
            "Last week the 1103s hovered cleanly. Lea warned about the FunFly.",
            "Jamie has it: in the flight test on 17.10. the 1103 15000KV with Gemfan 2020 props hovered cleanly. In the workshop note from 2.9. Lea warns against the FunFly 4S on the 1103s. I run the numbers anyway, or nobody believes it.",
        )
    else:
        await _say(
            ctx,
            "denkt",
            "No earlier notes on these. Fine, I check everything myself.",
            "Jamie has no earlier meetings on the 1103s or the FunFly. Then I check every part myself.",
        )
    await ctx.step("meeting", "done")

    await _beat()
    await ctx.step("teile", "running")
    await _say(ctx, "denkt", "Eight minutes? Everyone grabs a big battery. That is the trap.")
    motor = _part("generic-1103-15000kv")
    await _pick(ctx, "motor", "1103", motor["id"], "Hovered cleanly in last week's flight test, " + en(float(motor["thrust_g"]), 0) + " g thrust per motor.")
    await _pick(ctx, "propeller", "2020", "gemfan-2020-4", "The 2-inch four-blade the 1103 thrust figure is measured with.")
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
        ("Lea was right: " if warned else "")
        + "at thrust-to-weight "
        + en(failed["thrust_to_weight"], 2)
        + " there is no reserve for the gust. The battery is the brick.",
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

    version = await _build_tail(ctx, kickoff_id, "v1")
    await _need(ctx, "ui_point_at", {"target": "timeline", "label": "v1 hangs on the kickoff"})
    await _say(
        ctx,
        "freut_sich",
        "Mark 1, done. Notes, tags and tasks are in Jamie.",
        "Version 1 hangs on the kickoff: "
        + version["detail"].split(" · ", 1)[-1]
        + ". Jamie has a note, the tags drohne and drohne-v1 and "
        + str(version["tasks"]["task_count"])
        + " order tasks for Lea and Ben. Shop prices are from 2026-10-24; check them before ordering.",
    )
    ctx.state.finished = True


async def run_review(ctx: Ctx, meeting_id: str) -> None:
    ctx.state.finished = False
    await _beat()
    await ctx.step("meeting", "running")
    await _say(ctx, "denkt", "Review is over. Let me see what you changed.")
    review = await _need(ctx, "jamie_meeting", {"meeting_id": meeting_id})
    lines = []
    for change in review["changes"]:
        lines.append(_who(change["quote"]) + ": “" + change["quote"]["text"] + "”")
    for complaint in review["complaints"]:
        lines.append(_who(complaint["quote"]) + ": “" + complaint["quote"]["text"] + "”")
    if lines:
        await ctx.chat("agent", "From “" + review["title"] + "”:\n\n" + "\n\n".join(lines))

    accept: list[str] = [change["id"] for change in review["changes"]]
    for conflict in review["conflicts"]:
        old, new = conflict["old"], conflict["new"]
        await _need(ctx, "mascot_say", {"state": "denkt", "say": "That contradicts the kickoff. Better ask."})
        new_value = fmt_number(float(new["limit"])) + " " + _unit(conflict["unit"])
        old_value = fmt_number(float(old["limit"])) + " " + _unit(conflict["unit"])
        answer = await _need(
            ctx,
            "ask_user",
            {
                "question": old["meeting_title"]
                + ", "
                + _who(old)
                + ": “"
                + old["source_quote"]
                + "”\n"
                + new["meeting_title"]
                + ", "
                + _who(new)
                + ": “"
                + new["source_quote"]
                + "”\nDo I build for "
                + new_value
                + "?",
                "options": [
                    {"id": "new", "label": new_value + " (" + new["meeting_title"] + ")"},
                    {"id": "old", "label": old_value + " (" + old["meeting_title"] + ")"},
                ],
                "default_id": "new",
            },
        )
        if answer["answer_id"] == "old":
            accept.remove(conflict["id"])
    if accept:
        await _need(ctx, "requirements_accept", {"meeting_id": meeting_id, "ids": accept})
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": review["title"]})

    complaint = next((c for c in review["complaints"] if c["category"] == "motor"), None)
    refers = (complaint or {}).get("refers_to")
    if complaint and refers:
        await _say(
            ctx,
            "erklaert",
            "“Last week's motor” is the one from the flight test.",
            "“Last week's motor”: Jamie has the flight test on "
            + short_date(refers["date"])
            + ", "
            + _who(refers["quote"])
            + ": “"
            + refers["quote"]["text"]
            + "” That is "
            + refers["name"]
            + ", the motor in v1.",
        )
    await ctx.step("meeting", "done")

    await _beat()
    await ctx.step("teile", "running")
    target = next((r for r in ctx.state.requirements if r["id"] == "flight_time"), None)
    if target and float(target.get("min", 0)) > float(ctx.state.metrics.get("flight_time_min", 0)):
        await _need(ctx, "parts_search", {"category": "battery", "query": ""})
        bigger = _part("betafpv-lava-1s-680")
        await _say(
            ctx,
            "denkt",
            "More flight time means more battery. But not the FunFly.",
            "For "
            + en(float(target["min"]), 0)
            + " minutes I need more capacity. The FunFly would have it, but Jamie reminds me of Lea's warning. I stay at 1S and take the "
            + bigger["name"]
            + ", the other pack from the video.",
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
    await ctx.step("teile", "done")
    await ctx.chat("agent", "Computed: " + _numbers(metrics) + ".")

    await _beat()
    await ctx.step("simulation", "running")
    run = await _need(ctx, "simulate_drone", {})
    await ctx.step("simulation", "done" if run["result"] == "pass" else "failed")
    if run["result"] == "pass":
        await _say(ctx, "freut_sich", "Longer in the air and still holds the gust. You are welcome.")
    else:
        await _say(ctx, "besorgt", "Gust wins this round. Back to the parts.")

    version = await _build_tail(ctx, meeting_id, "v" + str(len(ctx.state.versions) + 1))
    changes = [item for item in version["diff"] if item["key"] in {"weight_g", "flight_time_min", "price_eur"}]
    digits = {"weight_g": 1, "flight_time_min": 1, "price_eur": 2}
    parts = ", ".join(
        item["label"] + " " + en(item["before"], digits[item["key"]]) + " → " + en(item["after"], digits[item["key"]]) + " " + item["unit"]
        for item in changes
    )
    await _need(ctx, "ui_point_at", {"target": "metrics", "label": "v" + str(version["version"])})
    await _say(
        ctx,
        "freut_sich",
        "v" + str(version["version"]) + " is done. The difference is a note in Jamie.",
        "Version "
        + str(version["version"])
        + " hangs on “"
        + review["title"]
        + "”: "
        + parts
        + ". The difference is a note on the meeting; order tasks: "
        + str(version["tasks"]["new"])
        + " new, "
        + str(version["tasks"]["closed"])
        + " closed.",
    )
    ctx.state.finished = True


async def run_mock_followup(ctx: Ctx) -> None:
    if not ctx.state.finished:
        await _say(
            ctx,
            "besorgt",
            "The last run stopped halfway. Reset once.",
            "Reset the session and send the sentence again. I do not build on half a state.",
        )
        return
    await _say(
        ctx,
        "ruhig",
        "The version is done. The next review in Jamie builds the next one.",
        "The version is done. As soon as the next review in Jamie ends, I rebuild and write the difference back.",
    )

