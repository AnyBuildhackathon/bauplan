"""Requirement rows: whether each requirement is met, recomputed from the measured state.

The brief or the product spec owns the wording and the limits; this module owns `met` and who a
requirement is attributed to (`attribute`). `refresh_requirements` runs after every successful tool call (`tools/registry.py`), so a
row only turns green when a tool produced a number that satisfies its limit. For a generic
product the verdict comes from the check library (`tools/checks.judge`); the drone and gripper
compare their metrics against fixed requirement ids, the drone's mission rows the latest
`simulate_mission` result for that mission.
"""

from __future__ import annotations

import re
import time

from pai_agent.context import Ctx
from pai_agent.paths import REPO_ROOT
from pai_agent.state import BuildState


def _words(text: str) -> str:
    return " ".join(re.findall(r"[\w€$%.,]+", text.lower())).strip(" .,")


def typed_by_user(state: BuildState, quote: str) -> bool:
    """True when `quote` is words the user actually typed or said in this session."""

    needle = _words(quote)
    if len(needle) < 3:
        return False
    return any(needle in _words(text) for text in state.requests)


def attribute(state: BuildState, quote: str, proposed: bool, reason: str = "") -> dict:
    """Who a requirement row names: the user with their own words, or Mechanic's proposal.

    A requirement counts as the user's only when its quote is in what they typed; anything
    else, a sensible default or a quote the model made up, is shown as proposed by Mechanic.
    """

    stamp = time.strftime("%H:%M")
    if not proposed and quote and typed_by_user(state, quote):
        return {"source": "user", "source_quote": quote.strip(), "speaker": "You", "time": stamp}
    note = reason.strip() or ("Proposed by Mechanic: no number for this in your request." if not quote else quote.strip())
    return {"source": "proposed", "source_quote": note, "speaker": "Mechanic", "time": stamp}


_MISSION_REQUIREMENTS = {"top_speed", "turn_rate", "hold_error", "chase_time"}


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
    if requirement_id in _MISSION_REQUIREMENTS:
        # Judged by simulate_mission against this row's limit; a changed limit waits for the next run.
        run = next((m for m in state.missions.values() if m.get("requirement") == requirement_id), None)
        if run is None or run.get("limit") != float(requirement.get("min", requirement.get("max", 0))):
            return None
        return run["result"] == "pass"
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
            "source": requirement.get("source", "user"),
            "changed_from": requirement.get("changed_from"),
            "detail": detail or None,
        }
    )


async def refresh_requirements(ctx: Ctx) -> None:
    for requirement in ctx.state.requirements:
        await emit_requirement(ctx, requirement, met_for(ctx.state, requirement))
