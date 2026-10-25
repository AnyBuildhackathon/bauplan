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


def keep_user_limits(state: BuildState, old_rows: list[dict], new_rows: list[dict]) -> list[str]:
    """A limit the user typed stays theirs: it may not get looser, nor lose its "You" label, on Mechanic's say-so.

    It may loosen only when the new limit is in words the user typed (a later message) or the user
    themselves answered an ask_user question since (`state.relax_consent`); a question that timed out
    on its default is not their answer. A revision that keeps the limit but would relabel the row as
    proposed keeps the user's quote instead. Returns the problems for the rows it refuses.
    """

    problems = []
    before = {row["id"]: row for row in old_rows if row.get("source") == "user"}
    for row in new_rows:
        old = before.get(row["id"])
        if old is None:
            continue
        key = "max" if "max" in old else "min" if "min" in old else None
        if key is None or key not in row:
            if row.get("source") != "user" and row.get("text") == old.get("text"):
                row.update({k: old[k] for k in ("source", "source_quote", "speaker", "time")})
            continue
        new, was = float(row[key]), float(old[key])
        looser = new > was if key == "max" else new < was
        if looser and row.get("source") != "user" and not state.relax_consent:
            problems.append(
                row["id"] + ": the user typed " + key + " " + f"{was:g}" + " (" + repr(old["source_quote"]) + "). A looser " + f"{new:g}" + " needs the user's own answer: "
                "a question that timed out on its default is not consent. Keep " + f"{was:g}" + " and swap parts until it passes, or ask_user again and wait for their answer."
            )
        elif new == was and row.get("source") != "user":
            row.update({k: old[k] for k in ("source", "source_quote", "speaker", "time")})
        elif looser and row.get("source") != "user":
            row.update({"source": "user", "speaker": "You", "source_quote": state.consent_quote or old["source_quote"]})
    return problems


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
    if requirement_id == "strength":
        # The printed frame's FEM safety factor (tools/fem.py), on a printer the user has.
        from pai_agent.tools.fem import strength_value

        value = strength_value(state, requirement)
        if value is None:
            return None
        requirement["_detail"] = f"{value:.1f}x, min. {float(requirement.get('min', 2)):g}x"
        return value >= float(requirement.get("min", 2))
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
