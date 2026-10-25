"""Second product: a parametric two-finger robot gripper.

The flow mirrors the drone: a brief with requirements, parts from a small catalog,
a grip-force calculation, a MuJoCo grip test, the CAD part (cad_part with the
gripper template or a script Claude writes), a Blender render and the bill of materials.

Grip force: one servo drives the left gear, which meshes with the right one, so the
servo torque closes both fingers: torque = 2 * F * lever, where the lever is the
distance from the gear axis to the pad centre. The servo holds about 70 % of its
stall torque. Friction from both pads, 2 * mu * F, has to carry the object.
"""

from __future__ import annotations

import asyncio
import json

from pai_agent.context import Ctx
from pai_agent.paths import DATA_DIR
from pai_agent.requirements import attribute
from pai_agent.tools.parts_search import unit_price_eur

GRAVITY = 9.80665
HOLD_FRACTION = 0.7
MIN_SAFETY = 2.0
FILAMENT_EUR_PER_G = 0.025
# Until cad_part weighs the printed parts, the gripper body is this estimate.
BODY_ESTIMATE_G = 60.0
CATEGORIES = ("servo", "pads", "hardware", "driver")
PRODUCTS = {"drone": "Micro drone", "gripper": "Robot gripper"}

_CATALOG: dict | None = None


def gripper_catalog() -> dict:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = json.loads((DATA_DIR / "catalogs" / "gripper.json").read_text(encoding="utf-8"))
    return _CATALOG


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message}


def _num(args: dict, key: str, default: float | None = None) -> float | None:
    try:
        return float(args[key])
    except (KeyError, TypeError, ValueError):
        return default


# The drone's requirements a request can set: id, limit key, wording.
DRONE_LIMITS = {
    "budget": ("max", "Total price under €{n:g}"),
    "flight_time": ("min", "At least {n:g} minutes of flight time"),
    "weight": ("max", "Total mass under {n:g} g"),
}


def _reset_build(state) -> None:
    state.selected = {}
    state.metrics = {}
    state.last_sim = None
    state.sim_run = 0
    state.stl_path = None
    state.part = None
    state.frame_mass_g = None
    state.bom = None
    state.cad_params = {}
    state.reasons = {}
    state.spec = None


def drone_requirements(state, entries: list) -> tuple[list[dict], list[str]]:
    """Requirement rows from the request: budget, flight time and weight with their limits, then hover and the printable frame."""

    rows: list[dict] = []
    problems: list[str] = []
    for index, entry in enumerate(entries if isinstance(entries, list) else []):
        if not isinstance(entry, dict):
            problems.append("requirements[" + str(index) + "] must be an object.")
            continue
        rid = str(entry.get("id") or "").strip()
        if rid not in DRONE_LIMITS:
            problems.append("requirements[" + str(index) + "].id must be one of " + ", ".join(DRONE_LIMITS) + ".")
            continue
        limit = _num(entry, "limit")
        if limit is None or limit <= 0:
            problems.append(rid + " needs a positive limit.")
            continue
        key, wording = DRONE_LIMITS[rid]
        said = attribute(state, str(entry.get("quote") or ""), bool(entry.get("proposed")))
        rows = [row for row in rows if row["id"] != rid]
        rows.append({"id": rid, "text": wording.format(n=limit), key: limit, **said, "changed_from": None})
    rows.append({"id": "hover", "text": "Must lift off and hover steadily", **attribute(state, "", True, "Proposed by Mechanic: every drone has to hold a hover in the gust test."), "changed_from": None})
    rows.append({"id": "printable", "text": "Frame as STL and STEP", **attribute(state, "", True, "Proposed by Mechanic: the frame is built in CAD, so it can be printed or cut."), "changed_from": None})
    return rows, problems


async def product_brief(ctx: Ctx, args: dict) -> dict:
    """Picks the product for this session and turns the request into requirement checks."""

    product = str(args.get("product") or "").strip().lower()
    if product not in PRODUCTS:
        return _fail("product must be one of: " + ", ".join(PRODUCTS) + ".")
    state = ctx.state
    if state.product != product:
        state.omniverse_result = None
        state.isaac_job_id = None
        state.training_video = None
    if product == "drone":
        requirements, problems = drone_requirements(state, args.get("requirements") or [])
        if problems:
            return _fail("Fix the requirements and call product_brief again: " + " | ".join(problems))
        revision = state.product == "drone" and bool(state.selected)
        if not revision:
            _reset_build(state)
        else:
            before = {r["id"]: r for r in state.requirements}
            for row in requirements:
                old = before.get(row["id"])
                if old and old["text"] != row["text"]:
                    row["changed_from"] = old["text"]
        state.product = product
        state.requirements = requirements
        await ctx.emit({"type": "product", "id": product, "label": PRODUCTS[product]})
        return {
            "ok": True,
            "detail": "Micro drone, " + str(len(requirements)) + " requirements from the request",
            "product": product,
            "requirements": [{k: r[k] for k in ("id", "text", "source")} | {k: r[k] for k in ("min", "max") if k in r} for r in requirements],
            "next": "parts_search for every category, physics_calc, simulate_drone, cad_frame, physics_calc, blender_render, safety_check, bom_build.",
        }

    state.product = product
    await ctx.emit({"type": "product", "id": product, "label": PRODUCTS[product]})
    mass = _num(args, "object_mass_g", 200.0)
    width = _num(args, "object_width_mm", 66.0)
    max_weight = _num(args, "max_weight_g")
    budget = _num(args, "budget_eur")
    quote = str(args.get("quote") or "").strip()
    if not mass or mass <= 0 or not width or width <= 0:
        return _fail("object_mass_g and object_width_mm must be positive numbers.")
    _reset_build(state)
    state.brief = {"object_mass_g": mass, "object_width_mm": width, "max_weight_g": max_weight, "budget_eur": budget}
    said = {**attribute(state, quote, False), "changed_from": None}
    requirements = [
        {"id": "payload", "text": f"Holds {mass:g} g while the arm moves", **said},
        {"id": "opening", "text": f"Opens wider than {width:g} mm", **said},
    ]
    if max_weight:
        requirements.append({"id": "weight", "text": f"Gripper under {max_weight:g} g", "max": max_weight, **said})
    if budget:
        requirements.append({"id": "budget", "text": f"Parts under {budget:g} €", "max": budget, **said})
    requirements.append({"id": "printable", "text": "Printable body with STL and STEP", **attribute(state, "", True, "Proposed by Mechanic: the body is printed, so it needs STL and STEP."), "changed_from": None})
    state.requirements = requirements
    return {
        "ok": True,
        "detail": f"Robot gripper for {mass:g} g, {width:g} mm wide",
        "product": product,
        "requirements": [{k: r[k] for k in ("id", "text")} for r in requirements],
        "next": "catalog_search for servo, pads, hardware and driver, then grip_calc and simulate_grip.",
    }


def _public(part: dict) -> dict:
    shown = {key: value for key, value in part.items() if key not in {"bom_qty", "aliases"}}
    shown["qty"] = part["bom_qty"]
    shown["price_is_sample"] = True
    return shown


async def catalog_search(ctx: Ctx, args: dict) -> dict:
    if ctx.state.product == "drone":
        return _fail("catalog_search serves the gripper catalog. For the drone use parts_search.")
    category = str(args.get("category") or "").strip()
    if category not in CATEGORIES:
        return _fail("category must be one of: " + ", ".join(CATEGORIES) + ".")
    query = str(args.get("query") or "").strip().lower()
    matches = []
    for part in gripper_catalog()["parts"]:
        if part["category"] != category:
            continue
        haystack = " ".join([part["id"], part["name"], part.get("note", ""), *part.get("aliases", [])]).lower()
        if query and query not in haystack:
            continue
        matches.append(part)
    if not matches:
        return _fail("No " + category + " matches " + repr(query) + ".")
    select_id = str(args.get("select_id") or "").strip()
    selected = None
    if select_id:
        chosen = next((part for part in matches if part["id"] == select_id), None)
        if chosen is None:
            return _fail("select_id " + select_id + " is not in this search. Found: " + ", ".join(p["id"] for p in matches) + ".")
        ctx.state.selected[category] = dict(chosen)
        selected = chosen
        brief_quote = ctx.state.requirements[0] if ctx.state.requirements else None
        why = None
        if brief_quote:
            why = {"text": brief_quote["source_quote"], "speaker": brief_quote["speaker"], "time": brief_quote["time"]}
        await ctx.emit(
            {
                "type": "part",
                "category": category,
                "id": chosen["id"],
                "name": chosen["name"],
                "mass_g": chosen["mass_g"],
                "size_mm": [chosen["length_mm"], chosen["width_mm"], chosen["height_mm"]] if "length_mm" in chosen else None,
                "diameter_mm": None,
                "why": why,
                "reason": str(args.get("reason") or "").strip(),
            }
        )
    detail = ("Chose " + selected["name"]) if selected else (category + ": " + str(len(matches)) + " found")
    return {
        "ok": True,
        "detail": detail,
        "price_note": gripper_catalog()["price_note"],
        "selected_id": selected["id"] if selected else None,
        "parts": [_public(p) for p in matches],
    }


def finger_lever_mm(state) -> float:
    """Gear axis to pad centre. The pads cover the outer 45 % of the finger."""

    finger = 70.0
    if state.part and "finger_length_mm" in state.part.get("params", {}):
        finger = float(state.part["params"]["finger_length_mm"])
    return finger * 0.775


def compute_grip(state) -> dict:
    missing = [c for c in CATEGORIES if c not in state.selected]
    if missing:
        raise ValueError("Parts missing: " + ", ".join(missing))
    servo = state.selected["servo"]
    pads = state.selected["pads"]
    brief = state.brief or {"object_mass_g": 200.0, "object_width_mm": 66.0}
    lever_m = finger_lever_mm(state) / 1000.0
    torque_nm = float(servo["stall_torque_kgcm"]) * GRAVITY / 100.0
    force_n = torque_nm * HOLD_FRACTION / (2 * lever_m)
    mu = float(pads["friction"])
    hold_n = 2 * mu * force_n
    load_n = float(brief["object_mass_g"]) / 1000.0 * GRAVITY
    safety = hold_n / load_n
    body_g = float(state.frame_mass_g) if state.frame_mass_g is not None else BODY_ESTIMATE_G
    weight = body_g
    price = body_g * FILAMENT_EUR_PER_G
    for category in CATEGORIES:
        part = state.selected[category]
        if category == "pads" and part["shop"] == "printed":
            continue  # Printed with the body; its mass is in the CAD weight.
        weight += float(part["mass_g"]) * int(part["bom_qty"])
        price += unit_price_eur(part) * int(part["bom_qty"])
    opening = 76.0
    if state.part and "jaw_opening_mm" in state.part.get("params", {}):
        opening = float(state.part["params"]["jaw_opening_mm"])
    warnings = []
    if servo.get("gear") == "nylon" and safety < MIN_SAFETY:
        warnings.append("Nylon gears strip when they hold near stall for long.")
    if state.frame_mass_g is None:
        warnings.append("The body mass is an estimate until cad_part weighs the printed parts.")
    metrics = {
        "weight_g": round(weight, 1),
        "price_eur": round(price, 2),
        "grip_force_n": round(force_n, 2),
        "hold_force_n": round(hold_n, 2),
        "safety_factor": round(safety, 2),
        "max_payload_g": round(hold_n / MIN_SAFETY / GRAVITY * 1000.0, 0),
        "opening_mm": opening,
        "lever_mm": round(lever_m * 1000.0, 1),
        "friction": mu,
        "warnings": warnings,
    }
    state.metrics = metrics
    return metrics


def metric_cards(state) -> list[dict]:
    m = state.metrics
    brief = state.brief or {}
    cards = [
        {
            "key": "safety_factor",
            "label": "Grip safety",
            "value": m["safety_factor"],
            "unit": "×",
            "digits": 1,
            "limit": f"min. {MIN_SAFETY:g} ×",
            "ok": m["safety_factor"] >= MIN_SAFETY,
        },
        {
            "key": "grip_force_n",
            "label": "Finger force",
            "value": m["grip_force_n"],
            "unit": "N",
            "digits": 1,
            "limit": f"holds up to {m['max_payload_g']:g} g",
            "ok": m["safety_factor"] >= MIN_SAFETY,
        },
        {
            "key": "weight_g",
            "label": "Weight",
            "value": m["weight_g"],
            "unit": "g",
            "digits": 0,
            "limit": f"max. {brief['max_weight_g']:g} g" if brief.get("max_weight_g") else "",
            "ok": not brief.get("max_weight_g") or m["weight_g"] <= brief["max_weight_g"],
        },
        {
            "key": "price_eur",
            "label": "Price",
            "value": m["price_eur"],
            "unit": "€",
            "digits": 2,
            "limit": f"max. {brief['budget_eur']:g} €" if brief.get("budget_eur") else "",
            "ok": not brief.get("budget_eur") or m["price_eur"] <= brief["budget_eur"],
        },
    ]
    return cards


async def emit_grip_metrics(ctx: Ctx) -> None:
    m = ctx.state.metrics
    await ctx.emit(
        {
            "type": "metrics",
            "weight_g": m["weight_g"],
            "price_eur": m["price_eur"],
            "grip_force_n": m["grip_force_n"],
            "safety_factor": m["safety_factor"],
            "cards": metric_cards(ctx.state),
        }
    )


async def grip_calc(ctx: Ctx, args: dict) -> dict:
    del args
    try:
        metrics = compute_grip(ctx.state)
    except ValueError as exc:
        return _fail(str(exc))
    await emit_grip_metrics(ctx)
    detail = (
        f"{metrics['grip_force_n']:.1f} N per finger, safety {metrics['safety_factor']:.1f}x, "
        f"{metrics['weight_g']:.0f} g, {metrics['price_eur']:.2f} €"
    )
    return {"ok": True, "detail": detail, **metrics}


async def simulate_grip(ctx: Ctx, args: dict) -> dict:
    del args
    try:
        metrics = compute_grip(ctx.state)
    except ValueError as exc:
        return _fail(str(exc))
    from pai_agent.grip_sim import run_grip

    brief = ctx.state.brief or {"object_mass_g": 200.0, "object_width_mm": 66.0}
    outcome = await asyncio.to_thread(
        run_grip, float(brief["object_mass_g"]), float(brief["object_width_mm"]), metrics["grip_force_n"], metrics["friction"]
    )
    ctx.state.sim_run += 1
    servo = ctx.state.selected["servo"]["name"]
    if outcome["result"] == "pass":
        summary = f"{servo}: {metrics['grip_force_n']:.1f} N per finger, the object stays put through lift and shake ({outcome['slip_mm']:.1f} mm slip)."
    elif outcome["dropped"]:
        summary = f"{servo}: only {metrics['grip_force_n']:.1f} N per finger, the object slides out when the arm lifts."
    else:
        summary = f"{servo}: {metrics['grip_force_n']:.1f} N per finger, the object slips {outcome['slip_mm']:.0f} mm when the arm shakes."
    ctx.state.last_sim = {"result": outcome["result"], "summary": summary, "slip_mm": outcome["slip_mm"]}
    await ctx.emit(
        {
            "type": "sim",
            "kind": "grip",
            "run": ctx.state.sim_run,
            "result": outcome["result"],
            "summary": summary,
            "trajectory": outcome["trajectory"],
            "hand": outcome["hand"],
            "object_width_mm": brief["object_width_mm"],
            "payload_g": brief["object_mass_g"],
            "force_n": metrics["grip_force_n"],
            "slip_mm": outcome["slip_mm"],
        }
    )
    return {
        "ok": True,
        "detail": "Grip test " + str(ctx.state.sim_run) + ": " + outcome["result"],
        "result": outcome["result"],
        "summary": summary,
        "slip_mm": outcome["slip_mm"],
        "dropped": outcome["dropped"],
        "safety_factor": metrics["safety_factor"],
    }


def servo_params(state) -> dict:
    """The servo pocket in the CAD part follows the chosen servo."""

    servo = state.selected.get("servo")
    if not servo:
        return {}
    return {
        "servo_length_mm": float(servo["length_mm"]),
        "servo_width_mm": float(servo["width_mm"]),
        "servo_height_mm": float(servo["height_mm"]),
        "servo_shaft_offset_mm": float(servo["shaft_offset_mm"]),
    }
