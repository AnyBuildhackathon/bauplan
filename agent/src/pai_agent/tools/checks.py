"""The check library for any product. Each check judges the spec requirements of its kind.

A check stores its result in state.checks under its key (the kind, or kind:part for a
deflection), with the arguments it ran with, so a parameter change can rerun it. The
requirement rows read pass or fail and a detail line from those results.
"""

from __future__ import annotations

import asyncio
import math

from pai_agent import analysis
from pai_agent.context import Ctx
from pai_agent.spec import part_of, slug
from pai_agent.tools.product import _fail, emit_cards, ensure_assembly, require_spec

UNIT_LABEL = {"deg_c": "°C", "g": "g", "eur": "€", "mm": "mm", "deg": "°", "n": "N", "x": "×", "min": "min", "h": "h", "days": "days"}
TIME_FACTOR = {"min": 60.0, "h": 1.0, "days": 1.0 / 24.0}


def _requirements(state, check: str, part_id: str | None = None) -> list[dict]:
    rows = [r for r in state.requirements if r.get("check") == check]
    if part_id is not None:
        rows = [r for r in rows if r.get("part_id") in (None, part_id)]
    return rows


def _fmt(value: float, unit: str) -> str:
    digits = 2 if unit == "eur" or abs(value) < 1 else 0 if abs(value) >= 100 else 1
    return f"{value:.{digits}f}" + ("" if unit in {"x", "deg", "deg_c"} else " ") + UNIT_LABEL.get(unit, unit)


def product_cost(state, fallback: float | None) -> float | None:
    """One price for the product: the bill of materials once it exists (it carries the live
    shop prices), else the assembly's catalog estimate."""

    return float(state.bom["total_eur"]) if state.bom else fallback


def _value_for(state, requirement: dict) -> float | None:
    """The number a requirement is judged on, in the requirement's own unit."""

    check = requirement["check"]
    unit = requirement.get("unit")
    if check in {"mass", "cost", "size"}:
        totals = state.checks.get("totals")
        if not totals:
            return None
        return {"mass": totals["mass_g"], "cost": product_cost(state, totals["cost_eur"]), "size": totals["largest_mm"]}[check]
    if check == "tip_over":
        tip = state.checks.get("tip_over")
        return None if not tip else tip["force_n"] if unit == "n" else tip["angle_deg"]
    if check == "deflection":
        rows = [v for k, v in state.checks.items() if k.startswith("deflection:") and requirement.get("part_id") in (None, v["part_id"])]
        return max(v["deflection_mm"] for v in rows) if rows else None
    if check == "torque":
        torque = state.checks.get("torque")
        return None if not torque else torque["safety"]
    if check == "runtime":
        run = state.checks.get("runtime") or state.checks.get("power")
        return None if not run or run.get("runtime_h") is None else run["runtime_h"] * TIME_FACTOR[unit or "h"]
    if check == "power":
        power = state.checks.get("power")
        return None if not power else power["headroom"]
    if check == "thermal":
        heat = state.checks.get("thermal")
        return None if not heat else heat["internal_c"]
    if check == "rollover":
        roll = state.checks.get("rollover")
        return None if not roll else roll["side_slope_deg"] if unit == "deg" else roll["max_lateral_g"]
    if check == "stability":
        sim = state.checks.get("stability")
        return None if not sim else sim["final_tilt_deg"]
    if check == "drop":
        sim = state.checks.get("drop")
        return None if not sim else sim["peak_g"]
    if check == "strength":
        from pai_agent.tools.fem import strength_value

        return strength_value(state, requirement)
    return None


def judge(state, requirement: dict) -> tuple[bool | None, str]:
    """pass/fail and the detail line for one generic requirement."""

    if requirement["check"] == "printable":
        printed = [p for p in (state.spec or {}).get("parts", []) if p["kind"] == "printed"]
        if not printed or any(p["id"] not in state.built for p in printed):
            return None, ""
        blocks = [state.built[p["id"]]["name"] for p in printed if state.built[p["id"]].get("fallback")]
        if blocks:
            return False, "Simplified block for " + ", ".join(blocks)
        return True, str(len(printed)) + " printed part(s) with STL and STEP"
    value = _value_for(state, requirement)
    if value is None:
        return None, ""
    unit = requirement.get("unit", "")
    if "max" in requirement:
        met = value <= requirement["max"]
        detail = _fmt(value, unit) + ", max. " + _fmt(requirement["max"], unit)
    else:
        met = value >= requirement["min"]
        detail = _fmt(value, unit) + ", min. " + _fmt(requirement["min"], unit)
    if requirement["check"] == "deflection":
        weak = [v for k, v in state.checks.items() if k.startswith("deflection:") and v["stress_safety"] < analysis.MIN_STRESS_SAFETY]
        if weak:
            met = False
            detail += ", stress safety only " + f"{min(v['stress_safety'] for v in weak):.1f}" + "×"
    if requirement["check"] == "drop" and state.checks.get("drop", {}).get("final_tilt_deg", 0) > 30:
        detail += ", lands on its side"
    return bool(met), detail


_CARD = {
    "tip_over": ("Tip-over", "deg"),
    "deflection": ("Deflection", "mm"),
    "torque": ("Torque safety", "x"),
    "runtime": ("Runtime", "h"),
    "stability": ("Push test tilt", "deg"),
    "drop": ("Drop load", "g"),
    "size": ("Size", "mm"),
    "power": ("Power headroom", "x"),
    "thermal": ("Thermal", "deg_c"),
    "rollover": ("Roll-over", "g"),
    "strength": ("Strength safety", "x"),
}


def metric_cards(state) -> list[dict]:
    """Mass and cost always, then the next two requirements that have a number."""

    totals = state.checks.get("totals")
    built = state.assembly or {}
    cards = []
    for check, key, label, unit, value in (
        ("mass", "mass_g", "Mass", "g", (totals or {}).get("mass_g", built.get("product_mass_g"))),
        ("cost", "cost_eur", "Cost", "eur", product_cost(state, (totals or {}).get("cost_eur", built.get("cost_eur")))),
    ):
        requirement = next((r for r in state.requirements if r.get("check") == check), None)
        limit = ""
        ok = True
        if requirement and value is not None:
            limit = "max. " + _fmt(requirement["max"], unit)
            ok = value <= requirement["max"]
        cards.append({"key": key, "label": label, "value": round(float(value or 0.0), 2), "unit": UNIT_LABEL[unit], "digits": 2 if unit == "eur" else 0, "limit": limit, "ok": ok, "pending": value is None})
    shown = set()
    for requirement in state.requirements:
        check = requirement.get("check")
        if check not in _CARD or check in shown or len(cards) >= 4:
            continue
        value = _value_for(state, requirement)
        met, _detail = judge(state, requirement)
        unit = requirement.get("unit") or _CARD[check][1]
        bound = ("max. " + _fmt(requirement["max"], unit)) if "max" in requirement else ("min. " + _fmt(requirement["min"], unit))
        shown.add(check)
        cards.append(
            {
                "key": check,
                "label": _CARD[check][0],
                "value": round(float(value), 2) if value is not None else 0.0,
                "unit": UNIT_LABEL.get(unit, unit),
                "digits": 2 if unit in {"x", "mm", "n"} and value is not None and value < 10 else 1,
                "limit": bound,
                "ok": met is not False,
                "pending": value is None,
            }
        )
    return cards


async def _store(ctx: Ctx, key: str, tool: str, args: dict, result: dict) -> None:
    ctx.state.checks[key] = {**result, "tool": tool, "args": args}
    await emit_cards(ctx)


def _verdict(state, check: str, part_id: str | None = None) -> tuple[str, list[dict]]:
    rows = []
    for requirement in _requirements(state, check, part_id):
        met, detail = judge(state, requirement)
        rows.append({"requirement": requirement["id"], "text": requirement["text"], "met": met, "detail": detail})
    failed = any(r["met"] is False for r in rows)
    return ("fail" if failed else "pass"), rows


async def _assembly_or_fail(ctx: Ctx) -> tuple[dict | None, dict | None]:
    try:
        require_spec(ctx.state)
        return await ensure_assembly(ctx), None
    except ValueError as exc:
        return None, _fail(str(exc))


async def check_totals(ctx: Ctx, args: dict) -> dict:
    built, error = await _assembly_or_fail(ctx)
    if error:
        return error
    result = {
        "mass_g": built["product_mass_g"],
        "mass_with_loads_g": built["total_mass_g"],
        "printed_g": built["printed_mass_g"],
        "bought_g": built["bought_mass_g"],
        "cost_eur": built["cost_eur"],
        "printed_cost_eur": built["printed_cost_eur"],
        "bought_cost_eur": built["bought_cost_eur"],
        "size_mm": built["size_mm"],
        "largest_mm": max(built["size_mm"]),
    }
    await _store(ctx, "totals", "check_totals", {}, result)
    verdict = []
    for check in ("mass", "cost", "size"):
        verdict += _verdict(ctx.state, check)[1]
    outcome = "fail" if any(r["met"] is False for r in verdict) else "pass"
    detail = outcome + ": " + f"{result['mass_g']:.0f} g, {result['cost_eur']:.2f} €, largest side {result['largest_mm']:.0f} mm"
    return {"ok": True, "detail": detail, "result": outcome, **result, "requirements": verdict, "warnings": built["warnings"]}


async def check_tip_over(ctx: Ctx, args: dict) -> dict:
    built, error = await _assembly_or_fail(ctx)
    if error:
        return error
    floor = built["bbox_mm"][2]
    push = args.get("push_height_mm")
    try:
        push_height = float(push) + floor if push is not None else built["bbox_mm"][5]
    except (TypeError, ValueError):
        return _fail("push_height_mm must be a number (height above the table).")
    tip = analysis.tip_over(built["footprint_mm"], built["com_mm"], floor, built["total_mass_g"], push_height)
    await _store(ctx, "tip_over", "check_tip_over", dict(args), tip)
    outcome, rows = _verdict(ctx.state, "tip_over")
    if not tip["inside"]:
        outcome = "fail"
    detail = outcome + ": tips at " + f"{tip['angle_deg']:.1f}°" + ", a push of " + f"{tip['force_n']:.2f} N" + " at " + f"{tip['push_height_mm']:.0f} mm" + " tips it"
    return {
        "ok": True,
        "detail": detail,
        "result": outcome,
        **tip,
        "com_mm": built["com_mm"],
        "footprint_mm": built["footprint_mm"],
        "requirements": rows,
        "hint": "To raise it: widen or deepen the footprint towards the tip direction, lower the centre of mass, or add ballast low down.",
    }


async def check_deflection(ctx: Ctx, args: dict) -> dict:
    try:
        spec = require_spec(ctx.state)
    except ValueError as exc:
        return _fail(str(exc))
    part_id = slug(args.get("part_id") or "")
    part = part_of(spec, part_id)
    if part is None or part["kind"] != "printed":
        return _fail("part_id must be a printed part of the spec.")
    info = ctx.state.built.get(part_id)
    material = (info or part)["material"]
    try:
        values = {k: float(args[k]) for k in ("span_mm", "width_mm", "thickness_mm", "load_n")}
    except (KeyError, TypeError, ValueError):
        return _fail("check_deflection needs span_mm, width_mm, thickness_mm and load_n as numbers.")
    support = "simple" if str(args.get("support") or "").lower().startswith("simpl") else "cantilever"
    try:
        result = analysis.deflection(material, values["span_mm"], values["width_mm"], values["thickness_mm"], values["load_n"], support)
    except ValueError as exc:
        return _fail(str(exc))
    result.update({"part_id": part_id, "material": material, **values})
    await _store(ctx, "deflection:" + part_id, "check_deflection", dict(args), result)
    outcome, rows = _verdict(ctx.state, "deflection", part_id)
    if result["stress_safety"] < analysis.MIN_STRESS_SAFETY:
        outcome = "fail"
    detail = (
        outcome + ": " + part["name"] + " bends " + f"{result['deflection_mm']:.2f} mm" + " under " + f"{values['load_n']:g} N"
        + ", stress safety " + f"{result['stress_safety']:.1f}×"
    )
    return {"ok": True, "detail": detail, "result": outcome, **result, "requirements": rows, "min_stress_safety": analysis.MIN_STRESS_SAFETY}


async def check_torque(ctx: Ctx, args: dict) -> dict:
    try:
        spec = require_spec(ctx.state)
    except ValueError as exc:
        return _fail(str(exc))
    part_id = slug(args.get("actuator_part_id") or "")
    item = ctx.state.picked.get(part_id)
    if part_of(spec, part_id) is None or item is None:
        return _fail("actuator_part_id must be a bought part that has been picked (a motor or servo).")
    try:
        if args.get("required_torque_nm") is not None:
            required = float(args["required_torque_nm"])
            how = "given"
        else:
            lever = float(args["lever_mm"]) / 1000.0
            force = float(args["force_n"]) if args.get("force_n") is not None else float(args["load_mass_g"]) / 1000.0 * analysis.GRAVITY
            required = force * lever
            how = f"{force:.2f} N at {lever * 1000:.0f} mm"
        result = analysis.torque(item, required)
    except (KeyError, TypeError, ValueError) as exc:
        return _fail("check_torque needs required_torque_nm, or lever_mm with force_n or load_mass_g. " + str(exc))
    result.update({"actuator": item["name"], "load": how})
    await _store(ctx, "torque", "check_torque", dict(args), result)
    outcome, rows = _verdict(ctx.state, "torque")
    detail = outcome + ": " + item["name"] + " gives " + f"{result['usable_torque_nm'] * 100:.1f} N cm" + " for " + f"{required * 100:.1f} N cm" + ", safety " + f"{result['safety']:.1f}×"
    return {"ok": True, "detail": detail, "result": outcome, **result, "requirements": rows}


async def check_runtime(ctx: Ctx, args: dict) -> dict:
    try:
        spec = require_spec(ctx.state)
    except ValueError as exc:
        return _fail(str(exc))
    part_id = slug(args.get("battery_part_id") or "")
    battery = ctx.state.picked.get(part_id)
    if part_of(spec, part_id) is None or battery is None:
        return _fail("battery_part_id must be a picked bought part with capacity_mah and voltage_v.")
    loads = []
    for index, load in enumerate(args.get("loads") or []):
        if not isinstance(load, dict):
            return _fail("loads must be objects {name, power_w, duty} or {part_id, duty}.")
        item = ctx.state.picked.get(slug(load.get("part_id") or "")) if load.get("part_id") else None
        power = load.get("power_w", item.get("power_w") if item else None)
        if power is None:
            return _fail("loads[" + str(index) + "] needs power_w, or a part_id whose catalog part has power_w.")
        loads.append({"name": str(load.get("name") or (item or {}).get("name") or "load " + str(index + 1)), "power_w": float(power), "duty": float(load.get("duty", 1.0))})
        if item and load.get("sleep_duty") is None and item.get("sleep_power_w") and float(load.get("duty", 1.0)) < 1:
            loads.append({"name": loads[-1]["name"] + " asleep", "power_w": float(item["sleep_power_w"]), "duty": 1.0 - float(load.get("duty", 1.0))})
    if not loads:
        return _fail("loads must list what draws power: {name, power_w, duty} or {part_id, duty}.")
    try:
        result = analysis.runtime(battery, loads)
    except ValueError as exc:
        return _fail(str(exc))
    result["battery"] = battery["name"]
    await _store(ctx, "runtime", "check_runtime", dict(args), result)
    outcome, rows = _verdict(ctx.state, "runtime")
    hours = result["runtime_h"]
    shown = f"{hours / 24:.1f} days" if hours >= 48 else f"{hours:.1f} h" if hours >= 2 else f"{hours * 60:.0f} min"
    detail = outcome + ": " + battery["name"] + " runs " + shown + " at " + f"{result['average_w']:.3g} W" + " average"
    return {"ok": True, "detail": detail, "result": outcome, **result, "requirements": rows}


async def simulate_assembly(ctx: Ctx, args: dict) -> dict:
    built, error = await _assembly_or_fail(ctx)
    if error:
        return error
    mode = "drop" if str(args.get("mode") or "push").lower() == "drop" else "push"
    key = "drop" if mode == "drop" else "stability"
    requirement = next((r for r in _requirements(ctx.state, key)), None)
    floor = built["bbox_mm"][2]
    tip = analysis.tip_over(built["footprint_mm"], built["com_mm"], floor, built["total_mass_g"], built["bbox_mm"][5])
    direction = args.get("direction") or tip["direction"]
    try:
        force = float(args.get("force_n") or 1.0)
        height = float(args.get("drop_height_mm") or 300.0)
        point = args.get("push_point_mm")
        if point is None:
            # The top of the assembly, on the side away from the tip direction, pushed towards it.
            point = [built["com_mm"][0], built["com_mm"][1], built["bbox_mm"][5]]
        point = [float(v) for v in point]
    except (TypeError, ValueError):
        return _fail("force_n, drop_height_mm and push_point_mm must be numbers.")
    outcome = await asyncio.to_thread(
        _run_sim, built, mode, force, point, [float(direction[0]), float(direction[1])], height
    )
    if not outcome["finite"]:
        return _fail("The MuJoCo run became unstable; check the masses and sizes.")
    ctx.state.sim_run += 1
    await _store(ctx, key, "simulate_assembly", dict(args), {k: outcome[k] for k in ("final_tilt_deg", "max_tilt_deg", "peak_g")})
    result, rows = _verdict(ctx.state, key)
    if mode == "push":
        limit = requirement["max"] if requirement else 5.0
        passed = outcome["final_tilt_deg"] <= limit
        if outcome["final_tilt_deg"] > 45:
            summary = f"A {force:g} N push tips it over: it ends at {outcome['final_tilt_deg']:.0f}°."
        elif passed:
            summary = f"A {force:g} N push rocks it to {outcome['max_tilt_deg']:.1f}°, it settles back upright."
        else:
            summary = f"A {force:g} N push leaves it leaning at {outcome['final_tilt_deg']:.1f}°, more than {limit:g}°."
    else:
        limit = requirement["max"] if requirement else None
        passed = limit is None or outcome["peak_g"] <= limit
        summary = f"Dropped from {height:.0f} mm it lands with {outcome['peak_g']:.0f} g" + (", on its side." if outcome["final_tilt_deg"] > 30 else ", upright.")
    if requirement is None:
        result = "pass" if passed else "fail"
    ctx.state.last_sim = {"result": result, "summary": summary}
    session = ctx.state.session_id
    await ctx.emit(
        {
            "type": "sim",
            "kind": "rigid",
            "mode": mode,
            "run": ctx.state.sim_run,
            "result": result,
            "summary": summary,
            "trajectory": outcome["trajectory"],
            "poses": outcome["poses"],
            "tilt": outcome["tilt"],
            "glb_url": "/files/" + session + "/" + built["glb"] + "?build=" + str(ctx.state.cad_builds),
            "floor_mm": floor,
            "size_mm": built["size_mm"],
            "bbox_mm": built["bbox_mm"],
            "force_n": force if mode == "push" else None,
            "push_point_mm": outcome["push_point_mm"],
            "push_dir": [round(direction[0], 3), round(direction[1], 3)] if mode == "push" else None,
            "push_window_s": outcome["push_window_s"],
            "limit_deg": limit if mode == "push" else None,
        }
    )
    return {
        "ok": True,
        "detail": "MuJoCo " + mode + " test " + str(ctx.state.sim_run) + ": " + result,
        "result": result,
        "summary": summary,
        "final_tilt_deg": outcome["final_tilt_deg"],
        "max_tilt_deg": outcome["max_tilt_deg"],
        "peak_g": outcome["peak_g"],
        "static_tip_force_n": tip["force_n"],
        "requirements": rows,
    }


def _run_sim(built: dict, mode: str, force: float, point: list[float], direction: list[float], height: float) -> dict:
    from pai_agent.rigid_sim import run

    length = math.hypot(direction[0], direction[1]) or 1.0
    return run(
        built["hull_points_mm"],
        built["bbox_mm"][2],
        built["total_mass_g"],
        built["com_mm"],
        built["size_mm"],
        mode,
        force_n=force,
        push_point_mm=point,
        direction=[direction[0] / length, direction[1] / length],
        drop_height_mm=height,
    )


CHECK_TOOLS = {
    "check_totals": check_totals,
    "check_tip_over": check_tip_over,
    "check_deflection": check_deflection,
    "check_torque": check_torque,
    "check_runtime": check_runtime,
    "simulate_assembly": simulate_assembly,
}
