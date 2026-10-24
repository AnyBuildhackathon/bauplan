"""Bill of materials from the selected parts."""

from __future__ import annotations

from pai_agent.context import Ctx, de
from pai_agent.scene import PART_CATEGORIES


async def bom_build(ctx: Ctx, args: dict) -> dict:
    del args
    missing = [category for category in PART_CATEGORIES if category not in ctx.state.selected]
    if missing:
        message = "Teile fehlen: " + ", ".join(missing)
        return {"ok": False, "error": message, "detail": message}
    items = []
    for category in PART_CATEGORIES:
        part = ctx.state.selected[category]
        mass = float(part["mass_g"])
        if category == "frame" and ctx.state.frame_mass_g is not None:
            mass = float(ctx.state.frame_mass_g)
        items.append(
            {
                "name": part["name"],
                "qty": int(part["bom_qty"]),
                "unit_price_eur": round(float(part["unit_price_eur"]), 2),
                "weight_g": round(mass, 2),
                "shop": part["shop"],
                "url": part["url"],
            }
        )
    total = round(sum(item["unit_price_eur"] * item["qty"] for item in items), 2)
    bom = {
        "items": items,
        "total_eur": total,
        "stl_path": ctx.state.stl_path or "",
    }
    ctx.state.bom = bom
    await ctx.emit({"type": "bom", **bom})
    detail = "Stückliste " + de(total, 2) + " €, Preise sind Stichproben"
    return {"ok": True, "detail": detail, **bom}
