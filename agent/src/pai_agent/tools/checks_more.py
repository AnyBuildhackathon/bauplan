"""More checks for any product: the power budget, the heat in a closed case and roll-over in a turn.

Same pattern as tools/checks.py: each check stores its result and arguments in state.checks
so cad_update and part_pick rerun it, and judges the requirements of its kind.
"""

from __future__ import annotations

from pai_agent import analysis_more
from pai_agent.context import Ctx
from pai_agent.spec import part_of, slug
from pai_agent.tools.checks import _assembly_or_fail, _store, _verdict
from pai_agent.tools.product import _fail, require_spec


def _built_param(state, key: str) -> tuple[float, str] | None:
    """The first built printed part that has this parameter, and its name."""

    for info in state.built.values():
        if key in (info.get("params") or {}):
            return float(info["params"][key]), info["name"]
    return None


async def check_power(ctx: Ctx, args: dict) -> dict:
    try:
        spec = require_spec(ctx.state)
    except ValueError as exc:
        return _fail(str(exc))
    part_id = slug(args.get("supply_part_id") or "")
    supply = ctx.state.picked.get(part_id)
    if part_of(spec, part_id) is None or supply is None:
        return _fail("supply_part_id must be a picked bought part: a power supply with voltage_v and max_current_a, or a battery with c_rating and capacity_mah.")
    if supply.get("voltage_v") is None:
        return _fail(supply["name"] + " has no voltage_v. Pick a supply or battery with a voltage rating.")
    loads = []
    for index, load in enumerate(args.get("loads") or []):
        if not isinstance(load, dict):
            return _fail("loads must be objects {part_id or name, power_w or current_a, voltage_v, duty, peak_factor}.")
        item = ctx.state.picked.get(slug(load.get("part_id") or "")) if load.get("part_id") else None
        power = load.get("power_w", (item or {}).get("power_w", (item or {}).get("tdp_w")))
        current = load.get("current_a")
        if power is None and current is None:
            return _fail("loads[" + str(index) + "] needs power_w or current_a, or a part_id whose catalog part has power_w or tdp_w.")
        loads.append(
            {
                "name": str(load.get("name") or (item or {}).get("name") or "load " + str(index + 1)),
                "power_w": None if power is None else float(power),
                "current_a": None if current is None else float(current),
                "voltage_v": load.get("voltage_v", (item or {}).get("voltage_v")),
                "duty": float(load.get("duty", 1.0)),
                "peak_factor": float(load.get("peak_factor", (item or {}).get("peak_factor", 1.0))),
            }
        )
    if not loads:
        return _fail("loads must list what draws power: {part_id or name, power_w or current_a, duty, peak_factor}.")
    try:
        result = analysis_more.power_budget(supply, loads)
    except (KeyError, TypeError, ValueError) as exc:
        return _fail(str(exc))
    result["supply"] = supply["name"]
    await _store(ctx, "power", "check_power", dict(args), result)
    outcome, rows = _verdict(ctx.state, "power")
    if result["headroom"] < 1.0:
        outcome = "fail"
    if result.get("runtime_h") is not None and "runtime" not in ctx.state.checks:
        # A battery supply also judges the runtime requirements (checks._value_for reads it here).
        runtime_outcome, runtime_rows = _verdict(ctx.state, "runtime")
        rows += runtime_rows
        if runtime_outcome == "fail":
            outcome = "fail"
    detail = (
        outcome + ": " + supply["name"] + " gives " + f"{result['supply_limit_a']:.2f} A" + " for a peak of " + f"{result['peak_a']:.2f} A"
        + ", headroom " + f"{result['headroom']:.1f}×" + (f", runs {result['runtime_h']:.1f} h" if result.get("runtime_h") is not None else "")
    )
    return {"ok": True, "detail": detail, "result": outcome, **result, "requirements": rows}


async def check_thermal(ctx: Ctx, args: dict) -> dict:
    try:
        spec = require_spec(ctx.state)
    except ValueError as exc:
        return _fail(str(exc))
    part_id = slug(args.get("enclosure_part_id") or "")
    part = part_of(spec, part_id)
    if part is None or part["kind"] != "printed":
        return _fail("enclosure_part_id must be the printed shell of the spec that closes the heat in.")
    info = ctx.state.built.get(part_id) or {}
    material = str(args.get("material") or info.get("material") or part.get("material") or "PLA")
    power = args.get("power_w")
    heat = []
    if power is None:
        for heat_id in args.get("heat_part_ids") or []:
            item = ctx.state.picked.get(slug(heat_id))
            if item is None:
                return _fail("heat_part_ids: " + str(heat_id) + " is not a picked part.")
            watts = item.get("tdp_w", item.get("power_w"))
            if watts is None:
                return _fail(item["name"] + " has no tdp_w or power_w. Pass power_w or pick a part with a power rating.")
            heat.append(item["name"])
            power = float(power or 0.0) + float(watts)
    if power is None:
        return _fail("check_thermal needs power_w, or heat_part_ids of picked parts with tdp_w or power_w.")
    fans = [item for key, item in ctx.state.picked.items() if item.get("airflow_m3h") and (not args.get("fan_part_ids") or key in args["fan_part_ids"])]
    wall = args.get("wall_mm")
    if wall is None:
        found = (info.get("params") or {}).get("wall_mm")
        wall = found if found is not None else 2.0
    vents = args.get("vents_mm2")
    if vents is None:
        found = _built_param(ctx.state, "vents_mm2")
        vents = found[0] if found else 0.0
    try:
        bbox = [float(v) for v in (args.get("bbox_mm") or part["size_mm"])]
        result = analysis_more.thermal(
            float(power),
            bbox,
            float(wall),
            material,
            vents_mm2=float(vents),
            fan_m3h=sum(float(f["airflow_m3h"]) for f in fans),
            ambient_c=float(args.get("ambient_c", 25.0)),
            component_limit_c=float(args.get("component_limit_c", analysis_more.COMPONENT_LIMIT_C)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _fail("check_thermal needs numbers for power_w, bbox_mm and wall_mm. " + str(exc))
    result.update({"power_w": float(power), "heat_sources": heat, "fans": [f["name"] for f in fans], "vents_mm2": float(vents), "enclosure": part["name"]})
    await _store(ctx, "thermal", "check_thermal", dict(args), result)
    outcome, rows = _verdict(ctx.state, "thermal")
    if result["margin_c"] < 0:
        outcome = "fail"
    cooling = ", ".join(result["fans"]) if fans else (f"{float(vents):.0f} mm² vents" if vents else "closed, no vents or fan")
    detail = (
        outcome + ": " + f"{float(power):g} W" + " inside the " + material + " " + part["name"].lower() + " reach " + f"{result['internal_c']:.0f} °C"
        + " (" + cooling + "), limit " + f"{result['limit_c']:.0f} °C"
    )
    return {
        "ok": True,
        "detail": detail,
        "result": outcome,
        **result,
        "requirements": rows,
        "hint": "To cool it: add a fan with part_pick (airflow_m3h), cut vents (a vents_mm2 parameter), or choose a wall material with a higher limit.",
    }


async def check_rollover(ctx: Ctx, args: dict) -> dict:
    built, error = await _assembly_or_fail(ctx)
    if error:
        return error
    values = {}
    for key in ("track_mm", "wheelbase_mm"):
        if args.get(key) is not None:
            values[key] = float(args[key])
            continue
        found = _built_param(ctx.state, key)
        if found is None:
            return _fail("check_rollover needs " + key + ", or a built printed part with a " + key + " parameter.")
        values[key] = found[0]
    floor = built["bbox_mm"][2]
    try:
        height = float(args["com_height_mm"]) if args.get("com_height_mm") is not None else built["com_mm"][2] - floor
        result = analysis_more.rollover(values["track_mm"], values["wheelbase_mm"], height, float(args.get("speed_mps", 0.0)), float(args.get("turn_radius_m", 0.0)))
    except (TypeError, ValueError) as exc:
        return _fail(str(exc))
    await _store(ctx, "rollover", "check_rollover", dict(args), result)
    outcome, rows = _verdict(ctx.state, "rollover")
    if result["rolls_in_turn"]:
        outcome = "fail"
    detail = (
        outcome + ": track " + f"{result['track_mm']:.0f} mm" + ", centre of mass " + f"{result['com_height_mm']:.0f} mm" + " high, rolls at "
        + f"{result['max_lateral_g']:.2f} g" + (f", the turn needs {result['turn_g']:.2f} g" if result["turn_g"] else "")
    )
    return {
        "ok": True,
        "detail": detail,
        "result": outcome,
        **result,
        "requirements": rows,
        "hint": "To raise it: widen the track (track_mm) or lower the heavy parts (battery, electronics) towards the axles.",
    }


CHECK_TOOLS = {"check_power": check_power, "check_thermal": check_thermal, "check_rollover": check_rollover}
