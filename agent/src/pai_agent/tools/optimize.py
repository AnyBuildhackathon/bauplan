"""Design optimizer: explores variants of the current drone and shows the trade-offs.

optimize_design takes goals (lighter, cheaper, longer_runtime, stronger) and limits to keep
(at least 8 minutes, say). Variant agents each propose one variant: a battery from the catalog
and the frame's arm length and plate thickness. Live, every proposal is a Sonnet sub-agent
running in parallel; without a key the proposals are fixed strategies, so the demo is the same
every time. Each variant then runs the bench's own checks: the frame mass from the same CadQuery
model cad_frame builds, physics_calc's numbers, the MuJoCo gust test, the prop clearance and the
limits the user wants to keep. The feasible variants that no other variant beats on every goal
are the Pareto set. optimize_apply builds one through the normal tools and commits it as the next
version, so its difference to the last version shows like any other.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import types

from pai_agent.context import Ctx, de

log = logging.getLogger(__name__)

# goal -> (number, better direction)
GOALS = {
    "lighter": ("weight_g", "min"),
    "cheaper": ("price_eur", "min"),
    "longer_runtime": ("flight_time_min", "max"),
    "stronger": ("arm_stiffness", "max"),
}
GOAL_LABELS = {"lighter": "lighter", "cheaper": "cheaper", "longer_runtime": "longer runtime", "stronger": "stronger"}
# keep key -> (number, bound, label, unit)
KEEPS = {
    "min_flight_time_min": ("flight_time_min", "min", "Flight time", "min"),
    "max_weight_g": ("weight_g", "max", "Weight", "g"),
    "max_price_eur": ("price_eur", "max", "Price", "€"),
    "min_thrust_to_weight": ("thrust_to_weight", "min", "Thrust/weight", ": 1"),
    "min_arm_stiffness": ("arm_stiffness", "min", "Arm stiffness", "×"),
}
_LETTERS = "ABCDEFGH"
_PROP_GAP_MM = 4.0
_THICKNESS = (1.2, 3.0)

# What each variant agent tries. "min" for the arm is the shortest arm whose props keep the gap.
STRATEGIES = (
    {"label": "Smaller pack", "serves": ("lighter", "cheaper"), "battery": "tattu-rline-1s-550",
     "reason": "The 550 mAh pack is 1.2 g lighter; the frame stays."},
    {"label": "Thin plate", "serves": ("lighter",), "thickness_mm": 1.5,
     "reason": "1.5 mm carbon instead of 2 mm takes a quarter off the frame."},
    {"label": "Short arms", "serves": ("lighter", "stronger"), "arm_length_mm": "min",
     "reason": "The shortest arm the 2-inch props allow: less carbon, a shorter lever."},
    {"label": "Featherweight", "serves": ("lighter", "cheaper"), "battery": "tattu-rline-1s-550", "arm_length_mm": "min", "thickness_mm": 1.5,
     "reason": "Everything light at once: small pack, short arms, thin plate."},
    {"label": "Balanced", "serves": ("lighter", "stronger"), "battery": "tattu-rline-1s-550", "arm_length_mm": "min", "thickness_mm": 1.8,
     "reason": "Small pack and short arms pay for a 1.8 mm plate that stays stiff."},
    {"label": "Big pack, thin plate", "serves": ("longer_runtime", "lighter"), "battery": "betafpv-lava-1s-680", "thickness_mm": 1.5,
     "reason": "The 680 mAh pack for runtime; the thin plate pays for its weight."},
    {"label": "Stiff arms", "serves": ("stronger",), "arm_length_mm": "min", "thickness_mm": 2.5,
     "reason": "2.5 mm carbon on short arms: crash-proof, a few grams heavier."},
    {"label": "Long runner", "serves": ("longer_runtime",), "battery": "betafpv-lava-1s-680", "arm_length_mm": "min",
     "reason": "The 680 mAh pack on the shortest arms that fit."},
)

_frame_masses: dict[tuple[float, float, float], float] = {}


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message}


def _frame_mass(arm_mm: float, thickness_mm: float, spacing_mm: float) -> float:
    """The carbon frame's mass from the same CadQuery model cad_frame exports."""

    from pai_agent.tools.cad import _CARBON_G_PER_MM3, build_frame

    key = (round(arm_mm, 2), round(thickness_mm, 2), round(spacing_mm, 2))
    if key not in _frame_masses:
        _frame_masses[key] = float(build_frame(*key).val().Volume()) * _CARBON_G_PER_MM3
    return _frame_masses[key]


def _batteries() -> dict[str, dict]:
    from pai_agent.tools.parts import catalog

    return {part["id"]: part for part in catalog()["parts"] if part["category"] == "battery"}


def _min_arm(state) -> float:
    propeller = state.selected.get("propeller") or {}
    diameter = float(propeller.get("diameter_mm") or 0)
    return math.ceil((diameter + _PROP_GAP_MM) / math.sqrt(2) * 2) / 2 if diameter else 20.0


def _base(state) -> dict:
    from pai_agent.tools.cad import DEFAULT_PARAMS

    params = {**DEFAULT_PARAMS, **{k: v for k, v in state.cad_params.items() if k in DEFAULT_PARAMS and isinstance(v, (int, float))}}
    return {
        "battery": state.selected["battery"]["id"],
        "arm_length_mm": float(params["arm_length_mm"]),
        "thickness_mm": float(params["thickness_mm"]),
        "motor_spacing_mm": float(params["motor_spacing_mm"]),
    }


def _config(state, base: dict, proposal: dict) -> dict:
    arm = proposal.get("arm_length_mm", base["arm_length_mm"])
    arm = _min_arm(state) if arm == "min" else float(arm)
    thickness = float(proposal.get("thickness_mm", base["thickness_mm"]))
    return {
        "battery": str(proposal.get("battery") or base["battery"]),
        "arm_length_mm": round(min(80.0, max(20.0, arm)), 1),
        "thickness_mm": round(min(_THICKNESS[1], max(_THICKNESS[0], thickness)), 1),
        "motor_spacing_mm": base["motor_spacing_mm"],
    }


def evaluate(state, base: dict, config: dict, keep: dict) -> dict:
    """The bench's checks on one variant, without touching the bench."""

    from pai_agent.tools.physics import compute
    from pai_agent.tools.simulate import run_hover

    battery = _batteries().get(config["battery"])
    if battery is None:
        raise ValueError("No battery " + config["battery"] + " in the catalog.")
    selected = {**state.selected, "battery": battery}
    frame_g = _frame_mass(config["arm_length_mm"], config["thickness_mm"], config["motor_spacing_mm"])
    numbers = compute(types.SimpleNamespace(selected=selected, frame_mass_g=frame_g, metrics={}))
    hover = run_hover(numbers["weight_g"], numbers["thrust_g"])
    # The arm is a cantilever: stiffness goes with thickness cubed over length cubed, relative to now.
    stiffness = (config["thickness_mm"] / base["thickness_mm"]) ** 3 * (base["arm_length_mm"] / config["arm_length_mm"]) ** 3
    propeller = selected.get("propeller") or {}
    clearance = config["arm_length_mm"] * math.sqrt(2) - float(propeller.get("diameter_mm") or 0)
    variant = {
        "battery": battery["name"],
        "battery_id": battery["id"],
        "params": {"arm_length_mm": config["arm_length_mm"], "thickness_mm": config["thickness_mm"]},
        "frame_g": round(frame_g, 2),
        "weight_g": numbers["weight_g"],
        "thrust_to_weight": numbers["thrust_to_weight"],
        "flight_time_min": numbers["flight_time_min"],
        "price_eur": numbers["price_eur"],
        "arm_stiffness": round(stiffness, 2),
        "warnings": list(numbers["warnings"]),
    }
    checks = [
        {"id": "hover", "label": "MuJoCo gust test", "pass": hover["result"] == "pass", "detail": "lowest " + de(hover["gust_low_z_m"], 2) + " m after the gust"},
        {"id": "clearance", "label": "Prop clearance", "pass": clearance >= _PROP_GAP_MM, "detail": de(clearance, 1) + " mm between props"},
    ]
    for key, limit in keep.items():
        number, bound, label, unit = KEEPS[key]
        value = variant[number]
        ok = value >= limit if bound == "min" else value <= limit
        checks.append({"id": "keep:" + key, "label": label + (" ≥ " if bound == "min" else " ≤ ") + de(limit, 1) + " " + unit, "pass": ok, "detail": de(value, 1) + " " + unit})
    variant["checks"] = checks
    variant["feasible"] = all(check["pass"] for check in checks)
    return variant


def objectives(goals: list[str]) -> list[str]:
    """The goals, then the chart's axes as goals too: the front shows what each gram costs."""

    axes = _axes(goals)
    extra = [g for g, (number, _d) in GOALS.items() if number in (axes["x"], axes["y"])]
    return list(dict.fromkeys(goals + extra))


def pareto(variants: list[dict], goals: list[str]) -> None:
    """Marks the feasible variants no other feasible variant beats on every objective."""

    keys = [GOALS[goal] for goal in goals]

    def better_or_equal(a: dict, b: dict) -> bool:
        return all((a[k] <= b[k]) if d == "min" else (a[k] >= b[k]) for k, d in keys)

    def strictly(a: dict, b: dict) -> bool:
        return any((a[k] < b[k]) if d == "min" else (a[k] > b[k]) for k, d in keys)

    feasible = [v for v in variants if v["feasible"]]
    for variant in variants:
        variant["pareto"] = variant["feasible"] and not any(
            other is not variant and better_or_equal(other, variant) and strictly(other, variant) for other in feasible
        )


def _recommend(variants: list[dict], goals: list[str]) -> str | None:
    front = [v for v in variants if v["pareto"]]
    if not front:
        return None

    def score(v: dict) -> tuple:
        return tuple(v[GOALS[g][0]] if GOALS[g][1] == "min" else -v[GOALS[g][0]] for g in goals)

    return min(front, key=score)["id"]


def _axes(goals: list[str]) -> dict:
    y = "arm_stiffness" if "stronger" in goals and "longer_runtime" not in goals else "flight_time_min"
    return {"x": "weight_g", "y": y, "color": "price_eur"}


def parse_goals(raw) -> list[str]:
    goals = [str(g).strip().lower().replace(" ", "_") for g in (raw or [])]
    goals = [{"longer": "longer_runtime", "runtime": "longer_runtime", "lighter_weight": "lighter"}.get(g, g) for g in goals]
    return [g for g in dict.fromkeys(goals) if g in GOALS]


def parse_keep(raw) -> dict:
    keep = {}
    for key, value in (raw or {}).items():
        if key in KEEPS:
            try:
                keep[key] = float(value)
            except (TypeError, ValueError):
                continue
    return keep


def _strategies(goals: list[str], count: int) -> list[dict]:
    first = [s for s in STRATEGIES if any(goal in s["serves"] for goal in goals)]
    rest = [s for s in STRATEGIES if s not in first]
    return (first + rest)[:count]


async def _propose_live(ctx: Ctx, goals: list[str], keep: dict, plans: list[dict], base: dict) -> list[dict]:
    """One Sonnet sub-agent per variant, all at once; each answers with propose_variant."""

    from pai_agent import settings
    from pai_agent.agents import AgentRun, create_message

    config = settings.current()
    batteries = [
        {"id": p["id"], "name": p["name"], "mass_g": p["mass_g"], "capacity_mah": p["capacity_mah"], "cells": p.get("cells"), "unit_price_eur": p.get("unit_price_eur")}
        for p in _batteries().values()
    ]
    tool = {
        "name": "propose_variant",
        "description": "Proposes one variant of the drone: a battery from the list and the frame's arm length and plate thickness.",
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Two or three words."},
                "battery": {"type": "string", "enum": [b["id"] for b in batteries]},
                "arm_length_mm": {"type": "number"},
                "thickness_mm": {"type": "number"},
                "reason": {"type": "string", "description": "One sentence."},
            },
            "required": ["label", "battery", "arm_length_mm", "thickness_mm", "reason"],
        },
    }
    brief = {
        "goals": goals,
        "keep": keep,
        "current": {**base, "metrics": {k: ctx.state.metrics.get(k) for k in ("weight_g", "thrust_to_weight", "flight_time_min", "price_eur")}},
        "batteries": batteries,
        "arm_length_mm": {"min": _min_arm(ctx.state), "max": 80},
        "thickness_mm": {"min": _THICKNESS[0], "max": _THICKNESS[1]},
        "physics": "Weight and price add up; the 1S motors' thrust is fixed. Runtime grows with capacity and falls with weight to the 1.5. "
        "Arm stiffness goes with thickness cubed over arm length cubed. The frame is 1.55 g/cm³ carbon.",
    }

    async def one(index: int, plan: dict) -> dict:
        task = "Variant " + _LETTERS[index] + ": " + plan["label"] + ". " + plan["reason"]
        run = AgentRun(ctx, "optimizer", "Variant agent " + _LETTERS[index], config["subagent_model"], config["subagent_effort"], task)
        await run.emit("running")
        try:
            response = await asyncio.to_thread(
                create_message,
                run.model,
                run.effort,
                max_tokens=4000,
                system=[{"type": "text", "text": "You are a variant agent on AnyBuild's design optimizer. Propose exactly one variant with propose_variant. "
                         "Follow your strategy, meet the goals as far as the limits allow, and do not copy the current design."}],
                tools=[tool],
                messages=[{"role": "user", "content": json.dumps(brief, ensure_ascii=False) + "\nYour strategy: " + task}],
            )
            run.count(response)
            use = next((b for b in response.content if getattr(b, "type", None) == "tool_use" and b.name == "propose_variant"), None)
            if use is None or not isinstance(use.input, dict):
                raise ValueError("no proposal")
            proposal = {**use.input, "agent": run.label, "model": run.model}
            await run.emit("done", str(proposal.get("label", ""))[:120])
            return proposal
        except Exception as exc:
            log.warning("variant agent %s failed: %s", index, exc)
            await run.emit("error", "fell back to the fixed strategy")
            return {**plan, "agent": run.label + " (fixed strategy)"}

    return list(await asyncio.gather(*(one(i, plan) for i, plan in enumerate(plans))))


async def optimize_design(ctx: Ctx, args: dict) -> dict:
    from pai_agent.env import claude_enabled

    state = ctx.state
    if state.product != "drone" or not state.selected.get("battery") or not state.metrics:
        return _fail("The optimizer explores the drone so far: build it first (physics_calc), then optimize.")
    goals = parse_goals(args.get("goals")) or ["lighter"]
    keep = parse_keep(args.get("keep"))
    try:
        count = max(4, min(8, int(args.get("count") or 6)))
    except (TypeError, ValueError):
        count = 6
    base = _base(state)
    plans = _strategies(goals, len(STRATEGIES))
    opt_id = "opt" + str(len(state.optimize) + 1)
    event = {"type": "optimize", "id": opt_id, "status": "running", "goals": goals, "keep": keep, "axes": _axes(goals), "baseline": None, "variants": [], "recommended": None, "applied": None, "version": None}
    await ctx.emit(dict(event))
    if claude_enabled():
        # Spare strategies stay behind the live proposals, so a copy of the current design is replaced.
        proposals = await _propose_live(ctx, goals, keep, plans[:count], base) + plans[count:]
    else:
        proposals = list(plans)

    def run_all() -> tuple[dict, list[dict]]:
        baseline = evaluate(state, base, base, keep)
        seen = {json.dumps(base, sort_keys=True)}
        variants = []
        for proposal in proposals:
            if len(variants) == count:
                break
            config = _config(state, base, proposal)
            fingerprint = json.dumps(config, sort_keys=True)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            try:
                variant = evaluate(state, base, config, keep)
            except ValueError as exc:
                log.warning("variant skipped: %s", exc)
                continue
            letter = _LETTERS[len(variants)]
            agent = proposal.get("agent") or "Variant agent " + letter
            variant.update({"id": letter, "label": str(proposal.get("label") or "Variant"), "reason": str(proposal.get("reason") or ""), "agent": agent})
            variants.append(variant)
        return baseline, variants

    baseline, variants = await asyncio.to_thread(run_all)
    pareto(variants, objectives(goals))
    baseline["label"] = "v" + str(len(state.versions)) if state.versions else "now"
    recommended = _recommend(variants, goals)
    event.update({"status": "done", "baseline": baseline, "variants": variants, "recommended": recommended})
    state.optimize[opt_id] = event
    await ctx.emit(dict(event))
    front = [v for v in variants if v["pareto"]]
    detail = str(len(variants)) + " variants, " + str(len([v for v in variants if v["feasible"]])) + " pass, " + str(len(front)) + " on the Pareto front"
    return {
        "ok": True,
        "detail": detail,
        "id": opt_id,
        "goals": goals,
        "keep": keep,
        "baseline": {k: baseline[k] for k in ("weight_g", "flight_time_min", "price_eur", "thrust_to_weight", "arm_stiffness")},
        "variants": [{k: v[k] for k in ("id", "label", "battery", "params", "weight_g", "flight_time_min", "price_eur", "thrust_to_weight", "arm_stiffness", "feasible", "pareto")} | {"failed": [c["label"] for c in v["checks"] if not c["pass"]]} for v in variants],
        "recommended": recommended,
        "note": "Numbers come from the same CadQuery frame model, physics_calc and the MuJoCo gust test. Let the user pick; optimize_apply builds the pick as the next version.",
    }


async def optimize_apply(ctx: Ctx, args: dict) -> dict:
    """Builds one variant through the normal tools and commits it as the next version."""

    from pai_agent.tools.registry import call_tool
    from pai_agent.versions import commit

    state = ctx.state
    runs = list(state.optimize.values())
    event = state.optimize.get(str(args.get("id") or "")) or (runs[-1] if runs else None)
    if event is None:
        return _fail("No optimizer run yet. Call optimize_design first.")
    wanted = str(args.get("variant") or event.get("recommended") or "").strip().upper()
    variant = next((v for v in event["variants"] if v["id"] == wanted), None)
    if variant is None:
        return _fail("Variant " + wanted + " is not in " + event["id"] + ". Pick one of " + ", ".join(v["id"] for v in event["variants"]) + ".")
    if event.get("applied"):
        return _fail("Variant " + event["applied"] + " of this run is already v" + str(event["version"]) + ". Run the optimizer again for new variants.")
    ctx.trigger = "chat"
    ctx.label = "Optimizer: " + variant["id"] + " " + variant["label"]

    async def need(name: str, payload: dict) -> dict:
        result = await call_tool(ctx, name, payload)
        if result.get("ok") is False:
            raise RuntimeError(name + " failed while building variant " + variant["id"] + ": " + str(result.get("error")))
        return result

    if variant["battery_id"] != state.selected["battery"]["id"]:
        await need("parts_search", {"category": "battery", "query": "", "select_id": variant["battery_id"], "reason": "Optimizer variant " + variant["id"] + ": " + variant["reason"]})
    await need("cad_frame", {**_base(state), **variant["params"]})
    await need("physics_calc", {})
    await call_tool(ctx, "simulate_drone", {})
    await call_tool(ctx, "blender_render", {})
    await need("bom_build", {})
    version = await commit(ctx, label=ctx.label)
    event.update({"applied": variant["id"], "version": version["n"]})
    await ctx.emit(dict(event))
    return {"ok": True, "detail": "Variant " + variant["id"] + " is v" + str(version["n"]) + " · " + version["summary"], "version": version["n"], "diff": version["diff"], "summary": version["summary"]}


# Mock mode: the chat sentence decides goals and limits.

_OPTIMIZE = re.compile(
    r"\b(optimi[sz]\w*|lighter|cheaper|stronger|stiffer|sturdier|longer[- ](?:run|flight|battery)\w*|more (?:flight|run)\s*time|trade-?offs?|variants?)\b",
    re.IGNORECASE,
)
_PICK = re.compile(r"\b(?:take|pick|choose|build|load|apply|use|go with)\b.*?\b(?:variant|option)\s+([a-h])\b", re.IGNORECASE)
_KEEP_MIN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:min\b|mins\b|minutes?\b)", re.IGNORECASE)
_KEEP_GRAMS = re.compile(r"(?:under|below|max(?:imum)?|at most)\s*(\d+(?:[.,]\d+)?)\s*(?:g\b|grams?\b)", re.IGNORECASE)
_KEEP_EUR = re.compile(r"(?:under|below|max(?:imum)?|at most)\s*(\d+(?:[.,]\d+)?)\s*(?:€|eur\w*)", re.IGNORECASE)


def wants_optimize(text: str) -> bool:
    return bool(_OPTIMIZE.search(text))


def wants_pick(text: str) -> str | None:
    match = _PICK.search(text)
    return match.group(1).upper() if match else None


def goals_from_text(text: str) -> tuple[list[str], dict]:
    lowered = text.lower()
    goals = []
    if re.search(r"\b(light\w*|weight)\b", lowered):
        goals.append("lighter")
    if re.search(r"\b(cheap\w*|cost\w*|price)\b", lowered):
        goals.append("cheaper")
    if re.search(r"\b(longer|runtime|endurance|more (?:flight|run)\s*time)\b", lowered):
        goals.append("longer_runtime")
    if re.search(r"\b(strong\w*|stiff\w*|sturd\w*|robust\w*)\b", lowered):
        goals.append("stronger")
    keep = {}
    for pattern, key in ((_KEEP_MIN, "min_flight_time_min"), (_KEEP_GRAMS, "max_weight_g"), (_KEEP_EUR, "max_price_eur")):
        match = pattern.search(text)
        if match:
            keep[key] = float(match.group(1).replace(",", "."))
    return goals or ["lighter"], keep


def _default_keep(state, keep: dict) -> dict:
    if "min_flight_time_min" not in keep:
        target = next((r for r in state.requirements if r.get("id") == "flight_time" and r.get("min") is not None), None)
        if target:
            keep = {**keep, "min_flight_time_min": float(target["min"])}
    return keep


async def run_optimize_mock(ctx: Ctx, text: str) -> None:
    from pai_agent.mock_story import run_mock

    state = ctx.state
    if state.product != "drone":
        await ctx.chat("agent", "The optimizer explores the drone so far. Start a drone build, then ask me to make it lighter.")
        return
    if not state.finished:
        await ctx.chat("agent", "Nothing to optimize yet. I build the drone first, then I explore variants.")
        await run_mock(ctx)
    goals, keep = goals_from_text(text)
    keep = _default_keep(state, keep)
    wanted = " and ".join(GOAL_LABELS[g] for g in goals)
    limits = ", ".join(KEEPS[k][2].lower() + (" at least " if KEEPS[k][1] == "min" else " at most ") + de(v, 1) + " " + KEEPS[k][3] for k, v in keep.items())
    await ctx.emit({"type": "mascot", "state": "denkt", "say": "Six agents, six ideas. Let the numbers fight."})
    await ctx.chat("agent", "Optimizing for " + wanted + (", keeping " + limits if limits else "") + ". Six variant agents each try one idea; every variant runs the frame model, the physics and the MuJoCo gust test.")
    result = await call_tool_checked(ctx, "optimize_design", {"goals": goals, "keep": keep, "count": 6})
    best = next((v for v in result["variants"] if v["id"] == result["recommended"]), None)
    failed = [v for v in result["variants"] if not v["feasible"]]
    lines = [result["detail"] + "."]
    if best:
        base = result["baseline"]
        lines.append(
            "Best for " + wanted + ": " + best["id"] + " " + best["label"] + ", " + de(best["weight_g"], 1) + " g instead of " + de(base["weight_g"], 1)
            + " g, " + de(best["flight_time_min"], 1) + " min, arm stiffness " + de(best["arm_stiffness"], 2) + "×."
        )
    if failed:
        lines.append("Failed: " + "; ".join(v["id"] + " " + v["label"] + " (" + ", ".join(v["failed"]) + ")" for v in failed) + ".")
    lines.append("Click a point in the chart to build it as the next version.")
    await ctx.chat("agent", " ".join(lines))
    await ctx.emit({"type": "mascot", "state": "erklaert", "say": "Pick a point. I build it."})


async def run_pick_mock(ctx: Ctx, letter: str | None) -> None:
    result = await apply_variant(ctx, None, letter)
    if result.get("ok") is False:
        await ctx.chat("agent", str(result["error"]))


async def apply_variant(ctx: Ctx, opt_id: str | None, letter: str | None) -> dict:
    """Builds the pick and says the difference, as the review rebuild does."""

    from pai_agent.tools.registry import call_tool

    state = ctx.state
    state.finished = False
    await ctx.chat("agent", "Building variant " + (letter or "the recommended one") + " with the real tools: frame in CAD, physics, gust test, render, bill of materials.")
    result = await call_tool(ctx, "optimize_apply", {"id": opt_id or "", "variant": letter or ""})
    state.finished = True
    if result.get("ok") is False:
        return result
    digits = {"weight_g": 1, "flight_time_min": 1, "price_eur": 2, "thrust_to_weight": 2}
    changes = ", ".join(
        item["label"] + " " + (de(item["before"], digits.get(item["key"], 1)) + " → " + de(item["after"], digits.get(item["key"], 1)) + " " + item["unit"] if item["unit"] else str(item["before"]) + " → " + str(item["after"]))
        for item in result["diff"]
        if not str(item["key"]).startswith("req:")
    )
    await ctx.emit({"type": "mascot", "state": "freut_sich", "say": "v" + str(result["version"]) + " is on the bench."})
    await ctx.chat("agent", "v" + str(result["version"]) + " is the optimizer's pick: " + (changes or result["summary"]) + ".")
    return result


async def call_tool_checked(ctx: Ctx, name: str, args: dict) -> dict:
    from pai_agent.tools.registry import call_tool

    result = await call_tool(ctx, name, args)
    if result.get("ok") is False:
        raise RuntimeError(result.get("error") or name)
    return result
