"""Deterministic demo. Same tools as the Claude loop, fixed choices.

run_mock builds v1 from the kickoff, run_review builds the next version from a review.
"""

from __future__ import annotations

import asyncio
import math

from pai_agent.context import Ctx, de
from pai_agent.env import pace_seconds
from pai_agent.meetings import fmt_number, short_date
from pai_agent.tools.build_guide import mock_steps
from pai_agent.tools.registry import call_tool

_UNITS = {"Minuten": "min", "minutes": "min"}


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
        de(metrics["weight_g"], 1)
        + " g, thrust-to-weight "
        + de(metrics["thrust_to_weight"], 2)
        + ", "
        + de(metrics["flight_time_min"], 1)
        + " min, €"
        + de(metrics["price_eur"], 2)
    )


def _who(quote: dict) -> str:
    """'Ben at 20:06', or just 'Ben' when the transcript has no times."""

    return quote["speaker"] + (" at " + quote["time"] if quote.get("time") else "")


def _unit(raw: str) -> str:
    return _UNITS.get(raw, raw)


def _tip_speed(part: dict) -> float:
    """Idle blade-tip speed in m/s: KV times volts is rpm, times the propeller circumference."""

    return float(part["kv"]) * 3.8 * math.pi * 0.040 / 60.0


async def _build_tail(ctx: Ctx, meeting_id: str, label: str) -> dict:
    """Frame in FreeCAD, real frame mass, Blender, bill of materials, Jamie tasks, version."""

    await _beat()
    await ctx.step("cad", "running")
    arm = float(ctx.state.cad_params.get("arm_length_mm") or 0)
    if not arm:
        await _say(
            ctx,
            "erklaert",
            "Frame in FreeCAD. Compact first.",
            "Now the frame in FreeCAD: 28 mm from the center to the motor shaft, 2 mm thick, 6.6 mm bolt circle for the 1102s.",
        )
        tight = await call_tool(ctx, "cad_frame", {"arm_length_mm": 28, "thickness_mm": 2, "motor_spacing_mm": 6.6})
        if tight.get("ok") is False:
            await _say(ctx, "besorgt", "Too tight. The propellers hit each other.", tight["error"] + " I will use 36 mm, which leaves 11 mm of clearance.")
        arm = 36.0
    cad = await _need(ctx, "cad_frame", {"arm_length_mm": arm, "thickness_mm": 2, "motor_spacing_mm": 6.6})
    await ctx.step("cad", "done")
    await _need(ctx, "ui_point_at", {"target": "frame", "label": "Frame " + de(cad["mass_g"], 1) + " g"})
    metrics = await _need(ctx, "physics_calc", {})
    await ctx.chat(
        "agent",
        "The frame weighs "
        + de(cad["mass_g"], 1)
        + " g of PLA according to "
        + ("FreeCAD" if cad["source"] == "freecad" else "CadQuery")
        + ". With the real parts: "
        + _numbers(metrics)
        + ".",
    )

    await _beat()
    await ctx.step("render", "running")
    rendered = await _need(ctx, "blender_render", {})
    await ctx.step("render", "done")
    if rendered.get("status") == "offline":
        await _say(ctx, "ruhig", "Blender is missing here. The STL is enough to print.")
    else:
        await _say(ctx, "erklaert", "Blender rendered " + label + " in the studio.")

    await _beat()
    await ctx.step("stueckliste", "running")
    await _need(ctx, "bom_build", {})
    await _need(ctx, "build_guide", {"steps": mock_steps(ctx)})
    tasks = await _need(ctx, "jamie_create_tasks", {"meeting_id": meeting_id})
    version = await _need(ctx, "version_commit", {"meeting_id": meeting_id})
    await ctx.step("stueckliste", "done")
    version["tasks"] = tasks
    return version


async def run_mock(ctx: Ctx, meeting_id: str = "") -> None:
    await _beat()
    await ctx.step("meeting", "running")
    await _say(ctx, "denkt", "Meeting first. Otherwise we optimize into the blue.")
    await _need(ctx, "jamie_templates", {})
    requirements = await _need(ctx, "jamie_requirements", {"meeting_id": meeting_id})
    kickoff_id = requirements["meeting_id"]
    await ctx.chat(
        "agent",
        str(len(requirements["requirements"]))
        + " requirements from “"
        + requirements["title"]
        + "”. Budget, flight time and weight sit in the Hardware requirements template, each with the sentence and who said it. I created the kickoff and review templates in Jamie myself.",
    )
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": requirements["title"]})
    motors = await _need(ctx, "jamie_search", {"query": "1102"})
    funfly = await _need(ctx, "jamie_search", {"query": "FunFly"})
    warned = any(meeting["quotes"] for meeting in funfly["meetings"])
    if motors["meetings"] and warned:
        await _say(
            ctx,
            "erklaert",
            "Last week the 22000KV flew cleanly. Someone warned about the FunFly.",
            "Jamie has it: in the flight test on 17 Oct the 1102 at 22000KV hovered cleanly. In the workshop note from 2 Sep, Lea warns against the FunFly 4S on the 1102s. I will run the numbers once anyway, or nobody believes it.",
        )
    else:
        await _say(
            ctx,
            "denkt",
            "No old notes on these parts. I will check every number.",
            "Jamie has no earlier meetings about the 1102s or the FunFly. Then I check every part myself.",
        )
    await ctx.step("meeting", "done")

    await _beat()
    await ctx.step("teile", "running")
    await _say(ctx, "denkt", "Ten minutes sounds like a big battery. That is the trap.")
    await _need(
        ctx,
        "parts_search",
        {"category": "motor", "query": "22000", "select_id": "betafpv-1102-22000kv", "reason": "Flew cleanly in last week's flight test, 46.3 g of thrust per motor."},
    )
    await _need(
        ctx,
        "parts_search",
        {"category": "propeller", "query": "1635", "select_id": "gemfan-1635-3", "reason": "BetaFPV measures the 1102 thrust on this propeller."},
    )
    await _need(
        ctx,
        "parts_search",
        {
            "category": "battery",
            "query": "FunFly",
            "select_id": "tattu-funfly-4s-1300",
            "because": "flight_time",
            "reason": "1300 mAh looks like ten minutes. I will check it.",
        },
    )
    await _need(
        ctx,
        "parts_search",
        {
            "category": "flight_controller",
            "query": "AIO",
            "select_id": "betafpv-f4-1s-12a-aio-v3",
            "because": "weight",
            "reason": "Controller and four ESCs on one board, 4.7 g.",
        },
    )
    await _need(
        ctx,
        "parts_search",
        {"category": "frame", "query": "frame", "select_id": "printed-whoop-frame", "because": "printable", "reason": "Comes off your printer, as an STL."},
    )
    first = await _need(ctx, "physics_calc", {})
    battery_g = float(ctx.state.selected["battery"]["mass_g"])
    await ctx.chat("agent", "First pass: " + _numbers(first) + ". The battery alone weighs " + de(battery_g, 1) + " g. " + " ".join(first["warnings"]))

    await _beat()
    await ctx.step("simulation", "running")
    failed = await _need(ctx, "simulate_drone", {})
    await ctx.step("simulation", "failed")
    await _say(
        ctx,
        "besorgt",
        "The gust pushes it into the ground. The battery is the lump.",
        ("Lea was right: " if warned else "")
        + "At a thrust-to-weight of "
        + de(failed["thrust_to_weight"], 2)
        + " there is no reserve for the gust. The battery is the lump.",
    )
    await _need(ctx, "ui_point_at", {"target": "battery", "label": ctx.state.selected["battery"]["name"]})
    await _need(ctx, "ui_draw", {"kind": "halo", "target": "battery", "text": "too heavy"})
    await _need(ctx, "ui_draw", {"kind": "arrow", "target": "battery", "text": de(battery_g, 1) + " g"})
    await _need(ctx, "ui_draw", {"kind": "circle", "target": "battery", "text": "4S on a 1S motor"})
    await _need(
        ctx,
        "ui_draw",
        {"kind": "note", "target": "battery", "text": "Thrust " + de(first["thrust_g"], 0) + " g, mass " + de(first["weight_g"], 0) + " g"},
    )

    await _beat()
    await ctx.step("teile", "running")
    await _say(
        ctx,
        "erklaert",
        "Off 4S. Same motors, different battery.",
        "I only swap the battery: Lava 1S 550, 14 g, 3.8 V. The 1102s stay. Their datasheet thrust is for exactly this voltage.",
    )
    await _need(
        ctx,
        "parts_search",
        {
            "category": "battery",
            "query": "Lava",
            "select_id": "betafpv-lava-1s-550",
            "because": "weight",
            "reason": "14 g instead of 150 g, and 1S matches the motors.",
        },
    )
    second = await _need(ctx, "physics_calc", {})
    await ctx.step("teile", "done")
    await ctx.chat("agent", "Updated: " + _numbers(second) + ". Flight time is a datasheet estimate, not a flight log.")

    await _beat()
    await ctx.step("simulation", "running")
    passed = await _need(ctx, "simulate_drone", {})
    if passed.get("result") != "pass":
        raise RuntimeError("The second MuJoCo run should hover: " + passed.get("summary", ""))
    await ctx.step("simulation", "done")
    await _say(ctx, "freut_sich", "The second run holds the gust. Capacity is not free.")
    await _need(ctx, "ui_draw", {"kind": "halo", "target": "battery", "text": "fits"})

    version = await _build_tail(ctx, kickoff_id, "v1")
    await _need(ctx, "ui_point_at", {"target": "timeline", "label": "v1 is on the kickoff"})
    await _say(
        ctx,
        "freut_sich",
        "v1 is in. Note, tags and tasks are in Jamie.",
        "Version 1 hangs on the kickoff: "
        + version["detail"].split(" · ", 1)[-1]
        + ". Jamie has a note, the tags drohne and drohne-v1, and "
        + str(version["tasks"]["task_count"])
        + " order tasks for Lea and Ben. Prices are samples. Check them before ordering.",
    )
    ctx.state.finished = True


async def run_review(ctx: Ctx, meeting_id: str) -> None:
    ctx.state.finished = False
    await _beat()
    await ctx.step("meeting", "running")
    await _say(ctx, "denkt", "The review is over. I am reading what changed.")
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
        await _need(ctx, "mascot_say", {"state": "denkt", "say": "That contradicts the kickoff. I had better ask."})
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
            "“The motor from last week” is the 22000KV from the flight test.",
            "“The motor from last week”: Jamie has the flight test from "
            + short_date(refers["date"])
            + ", "
            + _who(refers["quote"])
            + ": “"
            + refers["quote"]["text"]
            + "” That is the "
            + refers["name"]
            + ", the same motor in v1.",
        )
    elif complaint and complaint["last_week"]:
        await _say(
            ctx,
            "denkt",
            "I cannot find a meeting from last week. They probably mean the v1 motor.",
            "Jamie has no meeting from last week that names a motor. I will assume they mean the motor from v1: "
            + ctx.state.selected["motor"]["name"]
            + ".",
        )
    await ctx.step("meeting", "done")

    await _beat()
    await ctx.step("teile", "running")
    if complaint:
        old_motor = ctx.state.selected["motor"]
        await _need(ctx, "parts_search", {"category": "motor", "query": "1102"})
        from pai_agent.tools.parts import catalog

        quiet = next(p for p in catalog()["parts"] if p["id"] == "betafpv-1102-18000kv")
        await _need(
            ctx,
            "parts_search",
            {
                "category": "motor",
                "query": "18000",
                "select_id": quiet["id"],
                "because": "complaint",
                "reason": "Lower speed: blade tip "
                + de(_tip_speed(quiet), 0)
                + " instead of "
                + de(_tip_speed(old_motor), 0)
                + " m/s, so quieter, and 2.11 instead of 1.90 g/W.",
            },
        )
        await _need(ctx, "ui_point_at", {"target": "motor_front_left", "label": "18000KV, quieter"})
    target = next((r for r in ctx.state.requirements if r["id"] == "flight_time"), None)
    if target and float(target.get("min", 10)) > 12:
        await _need(ctx, "parts_search", {"category": "battery", "query": ""})
        await _say(
            ctx,
            "denkt",
            "More flight time means more battery. Not the FunFly.",
            "For "
            + de(float(target["min"]), 0)
            + " minutes I need more capacity. The FunFly would have it, but Jamie still has Lea's warning. I stay on 1S and take 1100 mAh.",
        )
        await _need(
            ctx,
            "parts_search",
            {
                "category": "battery",
                "query": "1100",
                "select_id": "lihv-1s-1100",
                "because": "flight_time",
                "reason": "1100 mAh for " + de(float(target["min"]), 0) + " minutes, 26 g, stays on 1S.",
            },
        )
    metrics = await _need(ctx, "physics_calc", {})
    await ctx.step("teile", "done")
    await ctx.chat("agent", "Calculated: " + _numbers(metrics) + ".")

    await _beat()
    await ctx.step("simulation", "running")
    run = await _need(ctx, "simulate_drone", {})
    await ctx.step("simulation", "done" if run["result"] == "pass" else "failed")
    if run["result"] == "pass":
        await _say(ctx, "freut_sich", "Quieter, longer in the air, and it still holds the gust.")
    else:
        await _say(ctx, "besorgt", "This does not hold the gust. I will look at the parts again.")

    version = await _build_tail(ctx, meeting_id, "v" + str(len(ctx.state.versions) + 1))
    changes = [
        item
        for item in version["diff"]
        if item["key"] in {"weight_g", "flight_time_min", "price_eur"}
    ]
    digits = {"weight_g": 1, "flight_time_min": 1, "price_eur": 2}
    parts = ", ".join(
        item["label"] + " " + de(item["before"], digits[item["key"]]) + " → " + de(item["after"], digits[item["key"]]) + " " + item["unit"]
        for item in changes
    )
    await _need(ctx, "ui_point_at", {"target": "metrics", "label": "v" + str(version["version"])})
    await _say(
        ctx,
        "freut_sich",
        "v" + str(version["version"]) + " is in. The difference is a note in Jamie.",
        "Version "
        + str(version["version"])
        + " hangs on “"
        + review["title"]
        + "”: "
        + parts
        + ". The difference is a note on the meeting, "
        + str(version["tasks"]["new"])
        + " new order tasks are open, "
        + str(version["tasks"]["closed"])
        + " old ones are closed.",
    )
    ctx.state.finished = True


async def run_mock_followup(ctx: Ctx) -> None:
    if not ctx.state.finished:
        await _say(
            ctx,
            "besorgt",
            "The last run stopped halfway. Reset once.",
            "Reset the session and send the sentence again. I will not build on a half-finished state.",
        )
        return
    await _say(
        ctx,
        "ruhig",
        "This version is in. The next Jamie review builds the next one.",
        "This version is in. As soon as the next review ends in Jamie, I rebuild and write the difference back.",
    )
