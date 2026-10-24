"""Bill of materials from the selected parts."""

from __future__ import annotations

from pai_agent.context import Ctx, de
from pai_agent.scene import PART_CATEGORIES


async def bom_build(ctx: Ctx, args: dict) -> dict:
    del args
    if ctx.state.product == "gripper":
        return await _gripper_bom(ctx)
    missing = [category for category in PART_CATEGORIES if category not in ctx.state.selected]
    if missing:
        message = "Parts missing: " + ", ".join(missing)
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
    detail = "Bill of materials €" + de(total, 2) + ", prices are samples"
    return {"ok": True, "detail": detail, **bom}


async def _gripper_bom(ctx: Ctx) -> dict:
    from pai_agent.tools.gripper import CATEGORIES, FILAMENT_EUR_PER_G

    state = ctx.state
    missing = [category for category in CATEGORIES if category not in state.selected]
    if missing:
        message = "Parts missing: " + ", ".join(missing)
        return {"ok": False, "error": message, "detail": message}
    items = []
    if state.part:
        body = float(state.part["mass_g"])
        items.append(
            {
                "name": state.part["name"] + " body, printed " + state.part["material"],
                "qty": 1,
                "unit_price_eur": round(body * FILAMENT_EUR_PER_G, 2),
                "weight_g": round(body, 2),
                "shop": "printed",
                "url": "",
            }
        )
    for category in CATEGORIES:
        part = state.selected[category]
        if category == "pads" and part["shop"] == "printed":
            continue
        items.append(
            {
                "name": part["name"],
                "qty": int(part["bom_qty"]),
                "unit_price_eur": round(float(part["unit_price_eur"]), 2),
                "weight_g": round(float(part["mass_g"]), 2),
                "shop": part["shop"],
                "url": part["url"],
            }
        )
    total = round(sum(item["unit_price_eur"] * item["qty"] for item in items), 2)
    bom = {"items": items, "total_eur": total, "stl_path": state.stl_path or ""}
    state.bom = bom
    await ctx.emit({"type": "bom", **bom})
    return {"ok": True, "detail": "Bill of materials " + f"{total:.2f}" + " €, prices are samples", **bom}
