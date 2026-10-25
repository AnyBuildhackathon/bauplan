"""Learning mode: Mechanic explains one engineering decision with the physics and the real numbers.

`facts_for` collects the exact numbers of one decision from the build state and the events
already published (a part swap needs the numbers before and after). `formula_for` turns them
into a formula line with the real values, from the same formulas as analysis.py and
tools/physics.py, so the numbers on screen are computed, not generated. `explain` writes two
or three plain sentences: a fixed template per kind, or with a Claude key Claude Haiku from
the facts and the formula only. A Haiku answer with a number that is in neither is thrown
away and the template stays. Answers are cached per decision and facts, so a repeated click
is instant and a rebuild with new numbers gets a new explanation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re

from pai_agent import speech
from pai_agent.provider import active
from pai_agent.state import BuildState

log = logging.getLogger(__name__)

KINDS = ("part", "swap", "requirement", "sim", "param")

# The MuJoCo hover test (docs/events.md): a downdraft of 35 % of the weight from 1.6 to 1.9 s.
GUST_SHARE = 0.35
# cad_frame keeps this gap between the propeller tips of neighbouring motors.
PROP_CLEARANCE_MM = 4.0
DRONE_REQUIREMENTS = {"budget", "weight", "flight_time", "hover", "printable"}

_SYSTEM = """You explain one engineering decision of AnyBuild, an agent that designs physical products, to a teammate who is not an engineer.
Write two or three short sentences of plain English: what was decided, why, and the physics behind it.
Use only the numbers in the facts and the formula, exactly as given; never estimate, round differently or add a number.
No markdown, lists, emoji or file paths."""

_TIMEOUT_S = 6.0
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
# "4.23 : 1" reads a ratio against one; zero and one never carry a claim on their own.
_ALWAYS = {"0", "1"}
_CACHE_MAX = 256

_cache: dict[str, dict] = {}
_client = None


class NotFound(LookupError):
    """The decision does not exist yet, such as a check that has not run."""


def n(value: float, digits: int = 1) -> str:
    """At most `digits` decimals, no trailing zeros: 4.230 -> 4.23, 10.0 -> 10."""

    text = f"{float(value):.{digits}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _num(value: float, digits: int = 1) -> float:
    return float(n(value, digits))


def _catalog_part(part_id: str) -> dict:
    from pai_agent.tools.parts import find

    return find(part_id) or {}


def _chosen(events: list[dict], category: str) -> list[tuple[int, dict]]:
    return [(i, e) for i, e in enumerate(events) if e.get("type") == "part" and e.get("category") == category and not e.get("considered")]


def _last(events: list[dict], kind: str, before: int | None = None, after: int | None = None) -> tuple[int, dict] | None:
    found = None
    for i, e in enumerate(events):
        if e.get("type") != kind or (before is not None and i >= before) or (after is not None and i <= after):
            continue
        if after is not None:
            return i, e
        found = (i, e)
    return found


def _drone_thrust_g(state: BuildState) -> float | None:
    motor = state.selected.get("motor")
    if not motor or not motor.get("thrust_g"):
        return None
    return float(motor["thrust_g"]) * int(motor.get("bom_qty", 4))


def _battery(part_id: str) -> dict:
    p = _catalog_part(part_id)
    if not p.get("capacity_mah"):
        return {}
    return {
        "cells": p.get("cells"),
        "voltage_v": p.get("voltage_v"),
        "capacity_mah": p.get("capacity_mah"),
        "energy_wh": _num(float(p["voltage_v"]) * float(p["capacity_mah"]) / 1000, 1),
    }


# ---------------------------------------------------------------- facts


def facts_for(state: BuildState, events: list[dict], kind: str, target_id: str) -> dict:
    if kind == "swap":
        return _swap_facts(state, events, target_id)
    if kind == "part":
        return _part_facts(state, events, target_id)
    if kind == "requirement":
        return _requirement_facts(state, events, target_id)
    if kind == "sim":
        return _sim_facts(events, target_id)
    if kind == "param":
        return _param_facts(state, events, target_id)
    raise NotFound(f"unknown kind {kind}")


def _swap_facts(state: BuildState, events: list[dict], category: str) -> dict:
    picks = _chosen(events, category)
    swap = next(((a, b) for a, b in zip(picks[::-1][1:], picks[::-1]) if a[1]["id"] != b[1]["id"]), None)
    if swap is None:
        raise NotFound(f"no swap in {category}")
    (_, prev), (at, nxt) = swap
    before = _last(events, "metrics", before=at)
    after = _last(events, "metrics", after=at)
    sim = _last(events, "sim", before=at)
    facts: dict = {
        "category": category,
        "from": prev["name"],
        "to": nxt["name"],
        "from_mass_g": prev.get("mass_g"),
        "to_mass_g": nxt.get("mass_g"),
        "reason": nxt.get("reason", ""),
        "quote": (nxt.get("why") or {}).get("text"),
        "speaker": (nxt.get("why") or {}).get("speaker"),
    }
    if sim is not None:
        facts.update({"run_before": sim[1]["run"], "result_before": sim[1]["result"], "summary_before": sim[1]["summary"]})
    sim_after = _last(events, "sim", after=at)
    if sim_after is not None:
        facts.update({"run_after": sim_after[1]["run"], "result_after": sim_after[1]["result"]})
    if before and after and before[1].get("thrust_to_weight") and after[1].get("thrust_to_weight"):
        b, a = before[1], after[1]
        facts.update(
            {
                "weight_before_g": b["weight_g"],
                "weight_after_g": a["weight_g"],
                "tw_before": b["thrust_to_weight"],
                "tw_after": a["thrust_to_weight"],
                "flight_before_min": b["flight_time_min"],
                "flight_after_min": a["flight_time_min"],
                "gust_share_pct": 35,
                "gust_min_tw": 1 + GUST_SHARE,
            }
        )
        thrust = _drone_thrust_g(state)
        if thrust:
            facts["thrust_g"] = _num(thrust, 0)
    if category == "battery":
        for side, part in (("from", prev), ("to", nxt)):
            for key, value in _battery(part["id"]).items():
                facts[f"{side}_{key}"] = value
    return facts


def _part_facts(state: BuildState, events: list[dict], target: str) -> dict:
    picks = _chosen(events, target)
    if picks:
        part = picks[-1][1]
        facts = {
            "category": target,
            "part": part["name"],
            "mass_g": part.get("mass_g"),
            "reason": part.get("reason", ""),
            "quote": (part.get("why") or {}).get("text"),
            "speaker": (part.get("why") or {}).get("speaker"),
            "warnings": [w.get("text") for w in part.get("warnings") or []][:2],
        }
        if target == "battery":
            facts.update(_battery(part["id"]))
            if state.metrics.get("flight_time_min") is not None:
                facts["flight_time_min"] = state.metrics["flight_time_min"]
        if target == "motor":
            thrust = _drone_thrust_g(state)
            motor = state.selected.get("motor") or {}
            if thrust and state.metrics.get("weight_g"):
                facts.update({"thrust_each_g": motor.get("thrust_g"), "motors": motor.get("bom_qty"), "thrust_g": _num(thrust, 0), "weight_g": state.metrics["weight_g"]})
        if target == "propeller" and part.get("diameter_mm"):
            facts["diameter_mm"] = part["diameter_mm"]
        return facts
    picked = state.picked.get(target)
    if picked:
        item = picked.get("item") or picked
        return {
            "category": target,
            "part": item.get("name"),
            "mass_g": item.get("mass_g"),
            "unit_price_eur": item.get("unit_price_eur"),
            "reason": picked.get("reason") or "",
        }
    raise NotFound(f"no part {target}")


def _requirement(state: BuildState, events: list[dict], rid: str) -> dict:
    found = next((r for r in state.requirements if r.get("id") == rid), None)
    shown = None
    for e in events:
        if e.get("type") == "requirement" and e.get("id") == rid:
            shown = {**(shown or {}), **e}
    if found is None and shown is None:
        raise NotFound(f"no requirement {rid}")
    return {**(shown or {}), **(found or {}), "met": (shown or {}).get("met", (found or {}).get("met")), "detail": (shown or {}).get("detail")}


def _requirement_facts(state: BuildState, events: list[dict], rid: str) -> dict:
    r = _requirement(state, events, rid)
    if r.get("met") is None:
        raise NotFound(f"requirement {rid} not checked yet")
    facts: dict = {"requirement": r.get("text"), "met": r.get("met"), "detail": r.get("detail"), "quote": r.get("source_quote") or r.get("quote"), "speaker": r.get("speaker")}
    for key in ("min", "max", "unit", "check"):
        if r.get(key) is not None:
            facts[key] = r[key]
    metrics = state.metrics
    if state.product == "drone" and rid in DRONE_REQUIREMENTS:
        facts["check"] = rid
        if rid == "weight":
            facts["weight_g"] = metrics.get("weight_g")
        elif rid == "budget":
            facts["price_eur"] = metrics.get("price_eur")
        elif rid == "flight_time":
            facts["flight_time_min"] = metrics.get("flight_time_min")
            battery = state.selected.get("battery")
            if battery:
                facts.update({"battery": battery.get("name"), **_battery(battery["id"]), "usable_pct": 80})
        elif rid == "hover":
            facts.update({"weight_g": metrics.get("weight_g"), "thrust_to_weight": metrics.get("thrust_to_weight"), "gust_share_pct": 35})
            thrust = _drone_thrust_g(state)
            if thrust:
                facts["thrust_g"] = _num(thrust, 0)
            sim = _last(events, "sim")
            if sim:
                facts.update({"run": sim[1]["run"], "result": sim[1]["result"]})
        return facts
    check = r.get("check")
    data = None
    if check == "tip_over":
        data = state.checks.get("tip_over")
        if data:
            facts.update({k: data.get(k) for k in ("angle_deg", "force_n", "margin_mm", "com_height_mm", "push_height_mm")})
            mass = (state.assembly or {}).get("total_mass_g")
            if mass:
                facts["mass_g"] = mass
    elif check == "deflection":
        data = next((v for k, v in state.checks.items() if k.startswith("deflection:")), None)
        if data:
            facts.update({k: data.get(k) for k in ("deflection_mm", "stress_mpa", "stress_safety", "modulus_mpa", "strength_mpa", "support")})
            facts.update({k: (data.get("args") or {}).get(k) for k in ("span_mm", "width_mm", "thickness_mm", "load_n")})
    elif check == "torque":
        data = state.checks.get("torque")
        if data:
            facts.update({k: data.get(k) for k in ("stall_torque_nm", "usable_torque_nm", "required_torque_nm", "safety", "family")})
    elif check == "runtime":
        data = state.checks.get("runtime")
        if data:
            facts.update({k: data.get(k) for k in ("energy_wh", "average_w", "runtime_h")})
            facts["usable_pct"] = 80
    elif check in ("stability", "drop"):
        data = state.checks.get(check)
        if data:
            facts.update({k: data.get(k) for k in ("final_tilt_deg", "max_tilt_deg", "peak_g")})
    elif check in ("mass", "cost", "size"):
        data = state.checks.get("totals")
        if data:
            facts.update({k: data.get(k) for k in ("mass_g", "cost_eur", "size_mm") if data.get(k) is not None})
    return {k: v for k, v in facts.items() if v is not None}


def _sim_facts(events: list[dict], run: str) -> dict:
    sim = next((e for e in reversed(events) if e.get("type") == "sim" and str(e.get("run")) == str(run)), None)
    if sim is None:
        raise NotFound(f"no run {run}")
    at = max(i for i, e in enumerate(events) if e is sim)
    facts = {"run": sim["run"], "result": sim["result"], "summary": sim["summary"], "test": sim.get("kind") or "hover"}
    if facts["test"] == "hover":
        metrics = _last(events, "metrics", before=at)
        if metrics and metrics[1].get("thrust_to_weight"):
            m = metrics[1]
            spare = m["weight_g"] * (m["thrust_to_weight"] - 1)
            facts.update(
                {
                    "weight_g": m["weight_g"],
                    "thrust_to_weight": m["thrust_to_weight"],
                    "spare_g": _num(spare, 0),
                    "gust_g": _num(m["weight_g"] * GUST_SHARE, 0),
                    "gust_share_pct": 35,
                }
            )
    else:
        for key in ("force_n", "slip_mm", "payload_g", "limit_deg", "mode"):
            if sim.get(key) is not None:
                facts[key] = sim[key]
    return facts


def _param_facts(state: BuildState, events: list[dict], name: str) -> dict:
    values = []
    for i, e in enumerate(events):
        param = (e.get("params") or {}).get(name) if e.get("type") == "cad" else None
        if param and (not values or values[-1][1] != param["value"]):
            values.append((i, param["value"], param.get("unit", "mm")))
    errors = [(i, e["detail"]) for i, e in enumerate(events) if e.get("type") == "tool" and e.get("name") == "cad_frame" and e.get("status") == "error"]
    if not values or (len(values) < 2 and not errors):
        raise NotFound(f"no change of {name}")
    at, value, unit = values[-1]
    facts: dict = {"param": name, "value": value, "unit": unit}
    if len(values) >= 2:
        facts["before"] = values[-2][1]
    error = next((d for i, d in reversed(errors) if i < at), None)
    if error and name == "arm_length_mm":
        facts["error"] = error
    if name == "arm_length_mm":
        prop = (state.selected.get("propeller") or {}).get("diameter_mm")
        if prop:
            facts.update({"propeller_mm": prop, "clearance_mm": PROP_CLEARANCE_MM, "motor_gap_mm": _num(value * math.sqrt(2)), "needed_mm": _num(float(prop) + PROP_CLEARANCE_MM)})
        return facts
    # A spec part's slider: the requirement details just before and after the rebuild.
    changed = []
    start = values[-2][0] if len(values) >= 2 else 0
    for r in state.requirements:
        before = next((e.get("detail") for e in reversed(events[start:at]) if e.get("type") == "requirement" and e.get("id") == r["id"] and e.get("detail")), None)
        after_ev = [e for e in events[at:] if e.get("type") == "requirement" and e.get("id") == r["id"]]
        after = after_ev[-1] if after_ev else None
        if after and before and after.get("detail") and before != after.get("detail"):
            changed.append({"requirement": r["id"], "text": r.get("text"), "before": before, "after": after["detail"], "met": after.get("met")})
    facts["checks"] = changed[:4]
    return facts


# ---------------------------------------------------------------- formula


def _number(label: str, value, unit: str = "") -> dict:
    return {"label": label, "value": value, "unit": unit}


def formula_for(kind: str, facts: dict) -> dict:
    f = facts
    if kind in ("swap", "sim") and f.get("tw_after", f.get("thrust_to_weight")) is not None and f.get("test", "hover") == "hover":
        if kind == "swap":
            thrust = f.get("thrust_g") or _num(f["weight_after_g"] * f["tw_after"], 0)
            text = f"T/W = total motor thrust / weight = {n(thrust, 0)} g / {n(f['weight_after_g'])} g = {n(f['tw_after'], 2)} (was {n(thrust, 0)} g / {n(f['weight_before_g'])} g = {n(f['tw_before'], 2)})"
            numbers = [
                _number(f"Weight {f['from']}", f["weight_before_g"], "g"),
                _number(f"Weight {f['to']}", f["weight_after_g"], "g"),
                _number("T/W before", f["tw_before"]),
                _number("T/W after", f["tw_after"]),
                _number("Flight time before", f["flight_before_min"], "min"),
                _number("Flight time after", f["flight_after_min"], "min"),
            ]
            if f.get("from_energy_wh") and f.get("to_energy_wh"):
                numbers += [_number(f"Energy {f['from']}", f["from_energy_wh"], "Wh"), _number(f"Energy {f['to']}", f["to_energy_wh"], "Wh")]
            return {"formula": text, "numbers": numbers}
        if f.get("spare_g") is not None:
            return {
                "formula": f"spare thrust = weight × (T/W − 1) = {n(f['weight_g'])} g × ({n(f['thrust_to_weight'], 2)} − 1) = {n(f['spare_g'], 0)} g vs gust = 35 % × {n(f['weight_g'])} g = {n(f['gust_g'], 0)} g",
                "numbers": [_number("T/W", f["thrust_to_weight"]), _number("Spare thrust", f["spare_g"], "g"), _number("Gust", f["gust_g"], "g")],
            }
    if kind == "swap":
        return {"formula": f"mass {n(f.get('from_mass_g') or 0)} g → {n(f.get('to_mass_g') or 0)} g", "numbers": []}
    if kind == "sim":
        if f.get("test") == "grip" and f.get("force_n"):
            return {"formula": "holding force = 2 × μ × finger force; passes when the object lags the hand ≤ 10 mm", "numbers": [_number("Finger force", f["force_n"], "N"), _number("Slip", f.get("slip_mm", 0), "mm")]}
        if f.get("test") == "rigid":
            return {"formula": "tips once the centre of mass passes the footprint edge", "numbers": [_number("Push", f["force_n"], "N")] if f.get("force_n") else []}
        return {"formula": "", "numbers": []}
    if kind == "param":
        if f.get("motor_gap_mm"):
            return {
                "formula": f"motor gap = arm × √2 = {n(f['value'])} mm × 1.414 = {n(f['motor_gap_mm'])} mm ≥ prop + clearance = {n(f['propeller_mm'])} + {n(f['clearance_mm'])} = {n(f['needed_mm'])} mm",
                "numbers": [_number("Arm", f["value"], "mm"), _number("Motor gap", f["motor_gap_mm"], "mm"), _number("Needed", f["needed_mm"], "mm")],
            }
        rows = [_number(c["text"] or c["requirement"], f"{c['before']} → {c['after']}") for c in f.get("checks", [])]
        return {"formula": f"{f['param']} = {n(f.get('before', f['value']))} → {n(f['value'])} {f.get('unit', '')}".strip(), "numbers": rows}
    if kind == "part":
        if f.get("energy_wh"):
            return {
                "formula": f"energy = voltage × capacity = {n(f['voltage_v'])} V × {n(f['capacity_mah'], 0)} mAh = {n(f['energy_wh'])} Wh",
                "numbers": [_number("Mass", f.get("mass_g"), "g"), _number("Energy", f["energy_wh"], "Wh")] + ([_number("Flight time", f["flight_time_min"], "min")] if f.get("flight_time_min") else []),
            }
        if f.get("thrust_g"):
            return {
                "formula": f"total thrust = {n(f['thrust_each_g'], 0)} g × {f['motors']} motors = {n(f['thrust_g'], 0)} g for {n(f['weight_g'])} g of drone",
                "numbers": [_number("Thrust", f["thrust_g"], "g"), _number("Weight", f["weight_g"], "g")],
            }
        return {"formula": "", "numbers": [_number("Mass", f["mass_g"], "g")] if f.get("mass_g") is not None else []}
    # requirement
    check = f.get("check")
    if check == "hover" and f.get("thrust_to_weight"):
        thrust = f.get("thrust_g") or _num(f["weight_g"] * f["thrust_to_weight"], 0)
        return {
            "formula": f"T/W = {n(thrust, 0)} g / {n(f['weight_g'])} g = {n(f['thrust_to_weight'], 2)}, needs > 1 to lift and > 1.35 for the 35 % gust",
            "numbers": [_number("T/W", f["thrust_to_weight"]), _number("Weight", f["weight_g"], "g")],
        }
    if check == "flight_time" and f.get("energy_wh"):
        return {
            "formula": f"runtime = 80 % of {n(f['energy_wh'])} Wh / hover power = {n(f['flight_time_min'])} min",
            "numbers": [_number("Flight time", f["flight_time_min"], "min"), _number("Energy", f["energy_wh"], "Wh")],
        }
    if check == "weight" and f.get("weight_g") is not None:
        return {"formula": f"weight = Σ part masses = {n(f['weight_g'])} g", "numbers": [_number("Weight", f["weight_g"], "g")]}
    if check == "budget" and f.get("price_eur") is not None:
        return {"formula": f"price = Σ unit price × qty = {n(f['price_eur'], 2)} €", "numbers": [_number("Price", f["price_eur"], "€")]}
    if check == "tip_over" and f.get("margin_mm") is not None:
        mass = f.get("mass_g")
        push = f"push = m g d / H = {n(mass / 1000, 3)} kg × 9.81 × {n(f['margin_mm'])} mm / {n(f['push_height_mm'], 0)} mm = {n(f['force_n'], 2)} N" if mass else f"push = m g d / H = {n(f['force_n'], 2)} N"
        return {
            "formula": f"angle = atan(d / h) = atan({n(f['margin_mm'])} / {n(f['com_height_mm'])}) = {n(f['angle_deg'])}°; {push}",
            "numbers": [_number("d (centre of mass to edge)", f["margin_mm"], "mm"), _number("H (push height)", f["push_height_mm"], "mm"), _number("Tipping push", f["force_n"], "N")]
            + ([_number("Limit", f["min"], f.get("unit", ""))] if f.get("min") is not None else []),
        }
    if check == "deflection" and f.get("deflection_mm") is not None:
        div = "48" if f.get("support") == "simple" else "3"
        return {
            "formula": f"δ = F L³ / ({div} E I) = {n(f['deflection_mm'], 2)} mm; stress {n(f['stress_mpa'])} MPa vs strength {n(f['strength_mpa'])} MPa = safety {n(f['stress_safety'])}×",
            "numbers": [_number("Deflection", f["deflection_mm"], "mm"), _number("Stress safety", f["stress_safety"], "×")],
        }
    if check == "torque" and f.get("safety") is not None:
        return {
            "formula": f"safety = usable torque / required = {n(f['usable_torque_nm'], 3)} / {n(f['required_torque_nm'], 3)} N m = {n(f['safety'], 2)}×",
            "numbers": [_number("Usable torque", f["usable_torque_nm"], "N m"), _number("Required", f["required_torque_nm"], "N m")],
        }
    if check == "runtime" and f.get("energy_wh") is not None:
        return {
            "formula": f"runtime = 80 % × {n(f['energy_wh'])} Wh / {n(f['average_w'], 3)} W = {n(f['runtime_h'])} h",
            "numbers": [_number("Energy", f["energy_wh"], "Wh"), _number("Average power", f["average_w"], "W"), _number("Runtime", f["runtime_h"], "h")],
        }
    return {"formula": f.get("detail") or "", "numbers": []}


# ---------------------------------------------------------------- templates


def _quote(f: dict) -> str:
    if not f.get("quote"):
        return ""
    who = f.get("speaker") or ""
    return f"{who}: “{f['quote']}”" if who else f"“{f['quote']}”"


def template(kind: str, facts: dict) -> tuple[str, str]:
    """Title and text from the facts alone."""

    f = facts
    if kind == "swap":
        s = [f"Swapped the {f['from']} ({n(f.get('from_mass_g') or 0)} g) for the {f['to']} ({n(f.get('to_mass_g') or 0)} g)."]
        if f.get("result_before") == "fail":
            s.append(f"MuJoCo run {f['run_before']} failed: {f['summary_before']}")
        elif f.get("quote"):
            s.append(f"The reason is {_quote(f)}.")
        if f.get("tw_after") is not None:
            s.append(f"Thrust-to-weight goes from {n(f['tw_before'], 2)} to {n(f['tw_after'], 2)}: the same motors now lift {n(f['weight_after_g'])} g instead of {n(f['weight_before_g'])} g.")
            if f["tw_before"] < 1 + GUST_SHARE <= f["tw_after"]:
                s.append("The gust pushes down with 35 % of the weight, so below 1.35 the drone cannot hold its height; now it has thrust to spare.")
            if f.get("from_energy_wh") and f.get("to_energy_wh"):
                longer = f["flight_after_min"] > f["flight_before_min"]
                s.append(
                    f"Battery runtime goes from {n(f['flight_before_min'])} to {n(f['flight_after_min'])} min with {n(f['to_energy_wh'])} Wh instead of {n(f['from_energy_wh'])} Wh"
                    + (": more energy for little extra weight." if longer else ", because hover power falls with weight, so the time drops far less than the energy.")
                )
            if f.get("result_after"):
                s.append(f"Run {f['run_after']} {'passed' if f['result_after'] == 'pass' else 'failed'}.")
        return f"Why swap to the {f['to']}?", " ".join(s)
    if kind == "part":
        s = [f.get("reason") or f"{f['part']} was picked."]
        if f.get("quote"):
            s.append(f"Asked for by {_quote(f)}")
        if f.get("energy_wh"):
            s.append(f"It stores {n(f['energy_wh'])} Wh; runtime is usable energy over the power it takes to hover.")
        if f.get("thrust_g"):
            s.append(f"Together the motors give {n(f['thrust_g'], 0)} g of thrust for a {n(f['weight_g'])} g drone.")
        return f"Why the {f['part']}?", " ".join(s)
    if kind == "sim":
        if f["test"] == "hover":
            s = [f"MuJoCo flies the drone to 0.5 m, then a downdraft of 35 % of its weight pushes on it; it passes when it never drops below 0.2 m and holds 0.35 m at the end. {f['summary']}"]
            if f.get("spare_g") is not None:
                s.append(f"The motors have {n(f['spare_g'], 0)} g of thrust above the weight and the gust takes {n(f['gust_g'], 0)} g, {'so it holds' if f['spare_g'] > f['gust_g'] else 'so it sinks'}.")
        elif f["test"] == "grip":
            s = [f"MuJoCo lifts the object and shakes it; friction turns the finger squeeze into holding force. {f['summary']}"]
        else:
            s = [f"MuJoCo treats the product as one rigid body; it tips once its centre of mass passes the edge of its footprint. {f['summary']}"]
        return f"Why run {f['run']} {'passed' if f['result'] == 'pass' else 'failed'}", " ".join(s)
    if kind == "param":
        if f.get("motor_gap_mm"):
            text = (f["error"] + " " if f.get("error") else "") + (
                f"On an X frame neighbouring motors stand arm × 1.414 apart: at {n(f['value'])} mm that is {n(f['motor_gap_mm'])} mm, "
                f"{'enough for' if f['motor_gap_mm'] >= f['needed_mm'] else 'less than'} the {n(f['propeller_mm'])} mm propeller plus {n(f['clearance_mm'])} mm clearance."
            )
            return f"Why a {n(f['value'])} mm arm?", text
        label = f["param"].replace("_mm", "").replace(".", " ").replace("_", " ")
        s = [f"{label} went from {n(f.get('before', f['value']))} to {n(f['value'])} {f.get('unit', 'mm')}."]
        for c in f.get("checks", []):
            s.append(f"“{c['text']}” moved from {c['before']} to {c['after']}, {'now met' if c.get('met') else 'still not met'}.")
        if any(c.get("requirement") and "tip" in str(c.get("text", "")).lower() + str(c.get("requirement")) for c in f.get("checks", [])) or "depth" in f["param"]:
            s.append("A deeper base moves the tipping edge away from the centre of mass, so the lever d in m g d / H grows and a harder push is needed to tip it.")
        return f"Why change {label}?", " ".join(s)
    # requirement
    state = "Met" if f.get("met") else "Not met"
    check = f.get("check")
    lines = {
        "weight": "Weight is the sum of every part's mass, with the frame weighed from its CAD model; every gram also costs thrust and flight time.",
        "budget": "Price is unit price × quantity summed over the bill of materials.",
        "flight_time": "Battery runtime is 80 % of the pack's energy divided by the power it takes to hover, and hover power grows with weight; it is a data-sheet estimate, not a logbook.",
        "hover": "To lift off the motors must push more than the drone weighs; to hold height in the gust they need 35 % more.",
        "printable": "The frame is modelled in FreeCAD, which writes the STL for printing or cutting and the STEP for other CAD tools.",
        "tip_over": "It tips once its centre of mass passes the footprint edge. The angle is atan(d / h), and a push at height H tips it at m g d / H, so a wider base (bigger d) or a lower push point helps.",
        "deflection": "A beam bends by F L³ over its stiffness E I, and the bending stress must stay under half the printed material's strength.",
        "torque": "The actuator gives a usable share of its stall torque, which must beat the torque the load needs.",
        "runtime": "Battery runtime is 80 % of the battery energy over the average power of all loads.",
        "mass": "Mass is the printed parts from their CAD volume and density plus the bought parts.",
        "cost": "Cost is unit price × quantity over the bill of materials.",
        "size": "Size is the largest side of the assembled bounding box.",
        "stability": "MuJoCo pushes the assembly and measures how far it tilts.",
        "drop": "MuJoCo drops the assembly and measures the peak load in g.",
    }
    detail = f"The check found {f['detail']}. " if f.get("detail") else ""
    return f"{state}: {f.get('requirement', '')}", detail + lines.get(str(check), "Mechanic turned the sentence into a number and a check that runs on every rebuild.")


# ---------------------------------------------------------------- explain


def numbers(text: str) -> set[str]:
    out = set()
    for raw in _NUMBER.findall(text):
        value = raw.rstrip("0").rstrip(".") if "." in raw else raw
        out.add(value.lstrip("0") or "0")
    return out


def grounded(text: str, *sources: str) -> bool:
    """True when every number in `text` also appears in one of the sources."""

    allowed = set(_ALWAYS)
    for source in sources:
        allowed |= numbers(source)
    return numbers(text) <= allowed


def cache_key(kind: str, target_id: str, facts: dict) -> str:
    raw = json.dumps([kind, target_id, facts], sort_keys=True, ensure_ascii=False, default=str)
    return kind + ":" + target_id + ":" + hashlib.sha256(raw.encode()).hexdigest()[:12]


async def _local(prompt: str):
    """The same call on the local Claude Code subscription; a process per call, so it gets more time."""

    from pai_agent import subscription

    return await asyncio.to_thread(
        subscription.create_message, speech.voice_model(), "low", system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}], thinking=False, timeout=_TIMEOUT_S + 30,
    )


def _anthropic():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.AsyncAnthropic()
    return _client


async def _haiku(title: str, facts_json: str, formula: str, draft: str) -> str | None:
    prompt = f"Decision: {title}\nFacts: {facts_json}\nFormula: {formula}\nDraft: {draft}"
    try:
        if active() == "subscription":
            message = await _local(prompt)
        else:
            async with asyncio.timeout(_TIMEOUT_S):
                message = await _anthropic().messages.create(
                    model=speech.voice_model(),
                    max_tokens=220,
                    thinking={"type": "disabled"},
                    system=_SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                )
    except Exception as exc:
        log.info("explanation failed: %s", type(exc).__name__)
        return None
    text = "".join(getattr(block, "text", "") for block in message.content).strip()
    if not text or not grounded(text, facts_json, formula, draft, title):
        log.info("explanation dropped: empty or a number not in the facts")
        return None
    return text


async def explain(state: BuildState, events: list[dict], kind: str, target_id: str) -> dict:
    if kind not in KINDS:
        raise NotFound(f"unknown kind {kind}")
    facts = facts_for(state, events, kind, target_id)
    key = cache_key(kind, target_id, facts)
    if key in _cache:
        return _cache[key]
    formula = formula_for(kind, facts)
    title, draft = template(kind, facts)
    facts_json = json.dumps(facts, ensure_ascii=False, default=str)
    text = await _haiku(title, facts_json, formula["formula"], draft) if speech.enabled() else None
    payload = {
        "ok": True,
        "key": key,
        "kind": kind,
        "target_id": target_id,
        "title": title,
        "text": text or draft,
        "formula": formula["formula"],
        "numbers": formula["numbers"],
        "source": "claude" if text else "template",
        "model": speech.voice_model() if text else None,
    }
    # A Haiku call that failed may work next time; everything else is final for these facts.
    if text or not speech.enabled():
        if len(_cache) >= _CACHE_MAX:
            _cache.pop(next(iter(_cache)))
        _cache[key] = payload
    return payload


def clear() -> None:
    _cache.clear()
