"""`parts_search`: the curated drone parts catalog (`agent/data/parts.json`) and the choice of one part.

A search filters one category; `select_id` binds a part to the build with a reason and the
requirement it serves, whose sentence from the user's request the dashboard shows next to the
part. Every catalog part carries its mass, price, shop link and the date the price was checked.
"""

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


# The requirement a part serves when the model names none.
_DEFAULT_BECAUSE = {"battery": "flight_time", "frame": "printable", "flight_controller": "weight", "motor": "hover", "propeller": "hover"}


def requirement_quote(state, requirement_id: str) -> dict | None:
    """The user's sentence behind a requirement, for the part it justifies."""

    item = next((r for r in state.requirements if r["id"] == requirement_id), None)
    if not item:
        return None
    return {"text": item["source_quote"], "speaker": item.get("speaker", ""), "time": item.get("time", "")}


async def emit_part(ctx: Ctx, part: dict, because: str = "", reason: str = "") -> dict:
    """Announces a chosen part with the requirement it serves and the sentence behind that requirement."""

    category = part["category"]
    why = requirement_quote(ctx.state, because) if because else None
    if why is None:
        why = requirement_quote(ctx.state, _DEFAULT_BECAUSE.get(category, "hover"))
    event = {
        "type": "part",
        "category": category,
        "id": part["id"],
        "name": part["name"],
        "why": why,
        "reason": reason,
        "mass_g": part.get("mass_g"),
        "size_mm": [part[k] for k in ("length_mm", "width_mm", "height_mm")] if "length_mm" in part else None,
        "diameter_mm": part.get("diameter_mm"),
    }
    ctx.state.reasons[category] = event
    await ctx.emit(event)
    return event


async def parts_search(ctx: Ctx, args: dict) -> dict:
    category = str(args.get("category", "")).strip()
    if category not in PART_CATEGORIES:
        message = "category must be motor, propeller, battery, flight_controller or frame."
        return {"ok": False, "error": message, "detail": message}
    query = str(args.get("query", "")).strip().lower()
    in_category = [part for part in catalog()["parts"] if part["category"] == category]
    if not in_category:
        message = "No " + category + " parts in the catalog."
        return {"ok": False, "error": message, "detail": message}
    # Word by word, best match first: "motor 1103 micro brushless" still finds the 1103.
    words = [word for word in query.replace(",", " ").split() if word != category.replace("_", " ")]
    scored = []
    for part in in_category:
        haystack = " ".join(
            [str(part.get(key, "")) for key in ("id", "name", "shop", "note")] + list(part.get("aliases") or [])
        ).lower()
        scored.append((sum(1 for word in words if word in haystack), part))
    matches = [part for score, part in sorted(scored, key=lambda row: -row[0]) if score > 0]
    unmatched = bool(words) and not matches
    if not matches:
        # Nothing matches the words: the whole category, so a select_id from it still works.
        matches = in_category

    selected = None
    select_id = str(args.get("select_id", "")).strip()
    if select_id:
        chosen = next((part for part in in_category if part["id"] == select_id), None)
        if chosen is None:
            known = ", ".join(part["id"] for part in in_category)
            message = "select_id " + select_id + " is not a " + category + " part. Here: " + known + "."
            return {"ok": False, "error": message, "detail": message}
        ctx.state.selected[category] = dict(chosen)
        selected = select_id
        await emit_part(ctx, chosen, str(args.get("because", "")).strip(), str(args.get("reason", "")).strip())

    shown = [_public(part) for part in matches[:8]]
    detail = category + ": " + str(len(shown)) + " hits" + (" (nothing matched " + repr(query) + ", showing the whole category)" if unmatched else "")
    if selected:
        detail = "Picked: " + ctx.state.selected[category]["name"]
    return {
        "ok": True,
        "detail": detail,
        "price_note": catalog().get("price_note", ""),
        "selected_id": selected,
        "parts": shown,
    }
