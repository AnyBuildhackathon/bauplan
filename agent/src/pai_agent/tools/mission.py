"""simulate_mission: flies the chosen drone through mission tests and judges each against a requirement.

Each mission maps to one requirement row with a limit (`mission_sim.MISSIONS`): the speed run to
top_speed, the hard turn to turn_rate, the position hold to hold_error, the chase to chase_time.
The limit is the user's when they typed a number (their words quoted), otherwise Mechanic proposes
one and the row says so. Every mission emits a `mission` event with its replay for the
Simulation tab, and the result names what limits the build, so a failed mission points at the
part to swap or the dimension to change.
"""

from __future__ import annotations

import asyncio

from pai_agent.context import Ctx
from pai_agent.drone_geometry import geometry
from pai_agent.mission_sim import MISSIONS, AirframeError, airframe, passes, run, value_of
from pai_agent.requirements import attribute
from pai_agent.tools.physics import PhysicsError, compute

# Mechanic's limits when the request has no number: what a quick micro quad should manage.
PROPOSED = {
    "speed_run": (60.0, "Proposed by Mechanic: no speed in your request; 60 km/h is fast for a micro quad."),
    "turn": (120.0, "Proposed by Mechanic: no turn rate in your request; 120°/s at 29 km/h is agile."),
    "hold": (15.0, "Proposed by Mechanic: no precision in your request; within 15 cm in gusty wind is precise."),
    "chase": (4.0, "Proposed by Mechanic: no catch time in your request; a hunter should catch a dodging fly in 4 s."),
}

WORDING = {
    "top_speed": "Top speed at least {n:g} km/h",
    "turn_rate": "Turns at least {n:g}°/s at 29 km/h",
    "hold_error": "Holds position within {n:g} cm in gusty wind",
    "chase_time": "Catches a dodging fly within {n:g} s",
}
LIMIT_KEY = {"top_speed": "min", "turn_rate": "min", "hold_error": "max", "chase_time": "max"}
MISSION_OF = {spec["requirement"]: mission for mission, spec in MISSIONS.items()}


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message}


def mission_row(state, requirement_id: str, limit: float, quote: str = "", proposed: bool = True, reason: str = "") -> dict:
    said = attribute(state, quote, proposed, reason)
    return {"id": requirement_id, "text": WORDING[requirement_id].format(n=limit), LIMIT_KEY[requirement_id]: limit, **said, "changed_from": None}


def _ensure_row(state, mission: str, entry: dict) -> dict:
    """The requirement row this mission is judged on: the given limit, else the existing row, else Mechanic's proposal."""

    rid = MISSIONS[mission]["requirement"]
    current = next((r for r in state.requirements if r["id"] == rid), None)
    try:
        limit = float(entry["limit"]) if entry.get("limit") is not None else None
    except (TypeError, ValueError):
        limit = None
    if limit is not None and limit > 0:
        row = mission_row(state, rid, limit, str(entry.get("quote") or ""), bool(entry.get("proposed")) or not entry.get("quote"))
        if current is not None and current["text"] != row["text"]:
            row["changed_from"] = current["text"]
    elif current is not None:
        return current
    else:
        value, reason = PROPOSED[mission]
        row = mission_row(state, rid, value, reason=reason)
    state.requirements = [r for r in state.requirements if r["id"] != rid] + [row]
    return row


def _limit(row: dict) -> float:
    return float(row.get("min", row.get("max", 0)))


def _why(mission: str, outcome: dict, frame: dict, metrics: dict) -> str:
    """What holds this build back in this mission, in one sentence, so a fix has a direction."""

    if outcome.get("crashed"):
        return "It hit the ground: thrust-to-weight " + f"{metrics['thrust_to_weight']:.2f}" + " leaves no reserve. Lighter parts or stronger motors."
    pitch_kmh = frame["pitch_speed"] * 3.6
    if mission == "speed_run":
        left = float(outcome.get("thrust_left_pct") or 100)
        if left < 75:
            return (
                "At top speed the props make only " + f"{left:.0f}" + " % of their static thrust, the air already coming at them at a good part of their pitch speed ("
                + f"{pitch_kmh:.0f}" + " km/h): more kv, more pitch or more cells raise it most."
            )
        return "Limited by thrust against drag at thrust-to-weight " + f"{metrics['thrust_to_weight']:.2f}" + ": stronger motors or less mass raise it."
    if mission == "turn":
        return "The turn needs sideways thrust: at thrust-to-weight " + f"{metrics['thrust_to_weight']:.2f}" + " a lighter build or stronger motors turn harder."
    if mission == "hold":
        return "Gusts push " + f"{metrics['weight_g']:.0f}" + " g around; faster motor response (smaller props) or more mass per drag area holds tighter."
    caught = outcome.get("captured", 0)
    return "Caught " + str(caught) + " of " + str(outcome.get("flies", 5)) + " flies: acceleration and turn rate decide a chase, so thrust-to-weight " + f"{metrics['thrust_to_weight']:.2f}" + " is the lever."


def _summary(mission: str, outcome: dict, row: dict, passed: bool) -> str:
    unit = MISSIONS[mission]["unit"]
    limit = _limit(row)
    sign = "≥" if MISSIONS[mission]["kind"] == "min" else "≤"
    goal = " (needs " + sign + " " + f"{limit:g}" + " " + unit + ")"
    verdict = "Pass" if passed else "Fail"
    if outcome.get("crashed"):
        return "Fail. It crashed during the " + MISSIONS[mission]["label"].lower() + "."
    if mission == "speed_run":
        return verdict + ". Top speed " + f"{outcome['top_speed_kmh']:.0f}" + " km/h, reached in " + f"{outcome['time_to_top_s']:.1f}" + " s" + goal + "."
    if mission == "turn":
        if not outcome.get("turn_time_s"):
            return "Fail. It never completed the 90° turn at " + f"{outcome['entry_speed_kmh']:.0f}" + " km/h" + goal + "."
        return verdict + ". 90° turn in " + f"{outcome['turn_time_s']:.2f}" + " s, " + f"{outcome['turn_rate_dps']:.0f}" + "°/s, overshoot " + f"{outcome['overshoot_pct']:.0f}" + " %" + goal + "."
    if mission == "hold":
        return verdict + ". Worst drift " + f"{outcome['hold_error_cm']:.1f}" + " cm, RMS " + f"{outcome['rms_error_cm']:.1f}" + " cm in 3 m/s gusting wind" + goal + "."
    if outcome.get("capture_s") is None:
        return "Fail. Caught " + str(outcome["captured"]) + " of " + str(outcome["flies"]) + " flies; the closest miss was " + f"{outcome['miss_distance_cm']:.0f}" + " cm" + goal + "."
    return verdict + ". Caught " + str(outcome["captured"]) + " of " + str(outcome["flies"]) + " dodging flies, median " + f"{outcome['capture_s']:.1f}" + " s" + goal + "."


def _parse(args: dict) -> tuple[list[dict], str | None]:
    raw = args.get("missions")
    if raw is None:
        raw = list(MISSIONS)
    if not isinstance(raw, list) or not raw:
        return [], "missions must be a list of speed_run, turn, hold or chase."
    entries: list[dict] = []
    for item in raw:
        entry = {"mission": item} if isinstance(item, str) else dict(item) if isinstance(item, dict) else {}
        name = str(entry.get("mission") or "").strip()
        if name not in MISSIONS:
            return [], "Unknown mission " + repr(name) + ". Use speed_run, turn, hold or chase."
        if all(e["mission"] != name for e in entries):
            entry["mission"] = name
            entries.append(entry)
    return entries, None


async def simulate_mission(ctx: Ctx, args: dict) -> dict:
    if ctx.state.product != "drone":
        return _fail("simulate_mission flies drones. For this product use its own checks.")
    entries, problem = _parse(args)
    if problem:
        return _fail(problem)
    try:
        metrics = compute(ctx.state)
        geo = geometry(ctx.state)
        frame = airframe(geo, ctx.state.selected)
    except (PhysicsError, AirframeError) as exc:
        return _fail(str(exc))
    state = ctx.state
    results = []
    for entry in entries:
        mission = entry["mission"]
        row = _ensure_row(state, mission, entry)
        # One MuJoCo flight at a time, off the event loop.
        outcome = await asyncio.to_thread(run, frame, mission)
        limit = _limit(row)
        passed = passes(outcome, limit)
        state.mission_run += 1
        summary = _summary(mission, outcome, row, passed)
        why = _why(mission, outcome, frame, metrics)
        spec = MISSIONS[mission]
        value = value_of(outcome)
        numbers = {k: v for k, v in outcome.items() if k not in {"series", "poses", "target", "wind", "mission"}}
        state.missions[mission] = {"result": "pass" if passed else "fail", "value": value, "limit": limit, "requirement": row["id"], "summary": summary, "why": why, "metrics": numbers}
        event = {
            "type": "mission",
            "run": state.mission_run,
            "mission": mission,
            "label": spec["label"],
            "result": "pass" if passed else "fail",
            "summary": summary,
            "why": why,
            "requirement_id": row["id"],
            "limit": limit,
            "limit_kind": spec["kind"],
            "unit": spec["unit"],
            "value": value,
            "metrics": numbers,
            "series": outcome.get("series", []),
            "poses": outcome.get("poses", []),
            "parts": frame["parts"],
            "mass_g": round(geo["total_mass_g"], 1),
        }
        if outcome.get("target"):
            event["target"] = outcome["target"]
        if outcome.get("wind"):
            event["wind"] = outcome["wind"]
        await ctx.emit(event)
        results.append({"mission": mission, "result": event["result"], "value": value, "unit": spec["unit"], "limit": limit, "requirement": row["id"], "source": row.get("source"), "summary": summary, "why": why, **numbers})
    failed = [r["mission"] for r in results if r["result"] == "fail"]
    detail = ", ".join(MISSIONS[r["mission"]]["label"] + " " + r["result"] for r in results)
    return {
        "ok": True,
        "detail": detail,
        "result": "fail" if failed else "pass",
        "missions": results,
        "mass_g": round(geo["total_mass_g"], 1),
        "thrust_to_weight": metrics["thrust_to_weight"],
        "pitch_speed_kmh": round(frame["pitch_speed"] * 3.6, 1),
        "next": "On a fail: swap the part named in why (parts_search with select_id) or change a dimension, physics_calc, then simulate_mission again with the failed missions, and say why it changed." if failed else "",
    }
