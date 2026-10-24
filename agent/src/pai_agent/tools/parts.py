"""Curated parts catalog."""

from __future__ import annotations

import json

from pai_agent.context import Ctx
from pai_agent.paths import PARTS_PATH
from pai_agent.scene import PART_CATEGORIES

_CATALOG: dict | None = None


def catalog() -> dict:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = json.loads(PARTS_PATH.read_text(encoding="utf-8"))
    return _CATALOG


def _public(part: dict) -> dict:
    hidden = {"bom_qty"}
    shown = {key: value for key, value in part.items() if key not in hidden}
    shown["qty"] = part["bom_qty"]
    shown["price_is_sample"] = part.get("price_is_sample", True)
    return shown


async def parts_search(ctx: Ctx, args: dict) -> dict:
    category = str(args.get("category", "")).strip()
    if category not in PART_CATEGORIES:
        message = "category must be motor, propeller, battery, flight_controller or frame."
        return {"ok": False, "error": message, "detail": message}
    query = str(args.get("query", "")).strip().lower()
    matches = []
    for part in catalog()["parts"]:
        if part["category"] != category:
            continue
        haystack = " ".join(
            [str(part.get(key, "")) for key in ("id", "name", "shop", "note")] + list(part.get("aliases") or [])
        ).lower()
        if query and query not in haystack:
            continue
        matches.append(part)
    if not matches:
        message = "No match for " + category + (" " + query if query else "") + "."
        return {"ok": False, "error": message, "detail": message}

    from pai_agent.tools.jamie import emit_part, part_notes, warn_candidates

    selected = None
    select_id = str(args.get("select_id", "")).strip()
    if select_id:
        chosen = next((part for part in matches if part["id"] == select_id), None)
        if chosen is None:
            known = ", ".join(part["id"] for part in matches)
            message = "select_id " + select_id + " is not in this search. Here: " + known + "."
            return {"ok": False, "error": message, "detail": message}
        ctx.state.selected[category] = dict(chosen)
        selected = select_id
        await emit_part(ctx, chosen, str(args.get("because", "")).strip(), str(args.get("reason", "")).strip())
    else:
        await warn_candidates(ctx, matches)

    shown = []
    for part in matches[:8]:
        public = _public(part)
        public["jamie_notes"] = [
            {key: note[key] for key in ("speaker", "time", "meeting_title", "text", "tone")} for note in part_notes(ctx.state, part)
        ]
        shown.append(public)
    detail = category + ": " + str(len(shown)) + " hits"
    if selected:
        detail = "Picked: " + ctx.state.selected[category]["name"]
    return {
        "ok": True,
        "detail": detail,
        "price_note": catalog().get("price_note", ""),
        "selected_id": selected,
        "parts": shown,
    }
