"""Requirement rows: whether each requirement is met, recomputed from the measured state.

The meeting file (or the product spec) owns the wording and the limits; this module owns
`met`. `refresh_requirements` runs after every successful tool call (`tools/registry.py`), so a
row only turns green when a tool produced a number that satisfies its limit. For a generic
product the verdict comes from the check library (`tools/checks.judge`); the drone and gripper
compare their metrics against fixed requirement ids.
"""

from __future__ import annotations

from pai_agent.context import Ctx
from pai_agent.paths import REPO_ROOT
from pai_agent.state import BuildState


def met_for(state: BuildState, requirement: dict) -> bool | None:
    requirement_id = requirement["id"]
    metrics = state.metrics
    if state.product == "gripper":
        return _gripper_met(state, requirement)
    if state.product == "generic":
        from pai_agent.tools.checks import judge

        met, detail = judge(state, requirement)
        requirement["_detail"] = detail
        return met
    if requirement_id == "budget":
        if "price_eur" not in metrics:
            return None
        return bool(metrics["price_eur"] <= float(requirement.get("max", 80)))
    if requirement_id == "flight_time":
        if "flight_time_min" not in metrics:
            return None
        return bool(metrics["flight_time_min"] >= float(requirement.get("min", 10)))
    if requirement_id == "weight":
        if "weight_g" not in metrics:
            return None
        limit = requirement.get("max")
        if limit is None:
            return True
        return bool(metrics["weight_g"] <= float(limit))
    if requirement_id == "hover":
        if state.last_sim is None:
            return None
        return state.last_sim["result"] == "pass"
    if requirement_id == "printable":
        if not state.stl_path:
            return None
        return (REPO_ROOT / state.stl_path).is_file()
    return None


def _gripper_met(state: BuildState, requirement: dict) -> bool | None:
    requirement_id = requirement["id"]
    metrics = state.metrics
    if requirement_id == "payload":
        return None if state.last_sim is None else state.last_sim["result"] == "pass"
    if requirement_id == "opening":
        if not state.part:
            return None
        opening = float(state.part["params"].get("jaw_opening_mm", 0))
        return opening > float(state.brief.get("object_width_mm", 0))
    if requirement_id in {"weight", "budget"}:
        key = "weight_g" if requirement_id == "weight" else "price_eur"
        if key not in metrics:
            return None
        return bool(metrics[key] <= float(requirement["max"]))
    if requirement_id == "printable":
        return None if not state.stl_path else (REPO_ROOT / state.stl_path).is_file()
    return None


async def emit_requirement(ctx: Ctx, requirement: dict, met: bool | None) -> None:
    detail = requirement.get("_detail")
    if requirement.get("_emitted") and requirement.get("_met") is met and requirement.get("_shown_detail") == detail:
        return
    requirement["_emitted"] = True
    requirement["_met"] = met
    requirement["_shown_detail"] = detail
    await ctx.emit(
        {
            "type": "requirement",
            "id": requirement["id"],
            "text": requirement["text"],
            "source_quote": requirement["source_quote"],
            "met": met,
            "speaker": requirement.get("speaker", ""),
            "time": requirement.get("time", ""),
            "meeting_title": requirement.get("meeting_title", ""),
            "changed_from": requirement.get("changed_from"),
            "detail": detail or None,
        }
    )


async def refresh_requirements(ctx: Ctx) -> None:
    for requirement in ctx.state.requirements:
        await emit_requirement(ctx, requirement, met_for(ctx.state, requirement))
