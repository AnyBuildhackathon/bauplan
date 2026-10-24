"""Bill of materials from the selected parts."""

from __future__ import annotations

from collections.abc import Callable

from pai_agent.context import Ctx, de
from pai_agent.scene import PART_CATEGORIES
from pai_agent.tools.parts_search import catalog_line, live_lines, live_prices_enabled


async def bom_build(ctx: Ctx, args: dict) -> dict:
    del args
    if ctx.state.product == "gripper":
        return await _gripper_bom(ctx)
    if ctx.state.product == "generic":
        return await _generic_bom(ctx)
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
    return await _priced_bom(ctx, items, lambda total: "Bill of materials €" + de(total, 2) + ", prices are samples")


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
    return await _priced_bom(ctx, items, lambda total: "Bill of materials " + f"{total:.2f}" + " €, prices are samples")


async def _priced_bom(ctx: Ctx, items: list[dict], catalog_detail: Callable[[float], str]) -> dict:
    """Emit the catalog list first, then the live-priced one when a key is set."""

    live = live_prices_enabled()
    bom = _bom(ctx, [catalog_line(item) for item in items], "searching" if live else "catalog")
    await ctx.emit({"type": "bom", **bom})
    if live:
        await ctx.emit({"type": "tool", "name": "bom_build", "status": "running", "detail": "Searching shop prices"})
        bom = _bom(ctx, await live_lines(items), "live")
        found = sum(1 for item in bom["items"] if item["price_source"] == "live")
        if not found:
            bom["prices"] = "catalog"
        await ctx.emit({"type": "bom", **bom})
        await _sync_metrics(ctx, bom["total_eur"])
        detail = "Bill of materials " + f"{bom['total_eur']:.2f}" + " €, live prices for " + str(found) + " of " + str(len(items)) + " lines"
    else:
        detail = catalog_detail(bom["total_eur"])
    return {"ok": True, "detail": detail, **bom}


def _bom(ctx: Ctx, items: list[dict], prices: str) -> dict:
    total = round(sum(item["unit_price_eur"] * item["qty"] for item in items), 2)
    bom = {
        "items": items,
        "total_eur": total,
        "stl_path": ctx.state.stl_path or "",
        "prices": prices,
    }
    ctx.state.bom = bom
    return bom


async def _sync_metrics(ctx: Ctx, total: float) -> None:
    """The key numbers and the budget check follow the live total."""

    metrics = ctx.state.metrics
    if "price_eur" not in metrics or abs(float(metrics["price_eur"]) - total) < 0.005:
        return
    metrics["price_eur"] = total
    if ctx.state.product == "gripper":
        from pai_agent.tools.gripper import emit_grip_metrics

        await emit_grip_metrics(ctx)
        return
    await ctx.emit(
        {
            "type": "metrics",
            "weight_g": metrics["weight_g"],
            "thrust_to_weight": metrics["thrust_to_weight"],
            "flight_time_min": metrics["flight_time_min"],
            "price_eur": total,
        }
    )


async def _generic_bom(ctx: Ctx) -> dict:
    """Printed parts at filament cost, bought parts with their price source; external loads are not ordered."""

    from pai_agent.assembly import COST_EUR_PER_G
    from pai_agent.tools.product import ensure_assembly

    state = ctx.state
    if not state.spec:
        message = "Call product_spec first."
        return {"ok": False, "error": message, "detail": message}
    missing = [p["name"] for p in state.spec["parts"] if p["kind"] == "printed" and p["id"] not in state.built]
    unpicked = [p["name"] for p in state.spec["parts"] if p["kind"] == "bought" and p["id"] not in state.picked]
    if missing or unpicked:
        message = "Not ready: " + ", ".join(["build " + n for n in missing] + ["pick " + n for n in unpicked])
        return {"ok": False, "error": message, "detail": message}
    await ensure_assembly(ctx)
    items = []
    for part in state.spec["parts"]:
        if part["kind"] == "printed":
            info = state.built[part["id"]]
            mass = float(info["mass_g"])
            items.append(
                {
                    "name": part["name"] + ", printed " + info["material"],
                    "qty": part["qty"],
                    "unit_price_eur": round(mass * COST_EUR_PER_G.get(info["material"], 0.03), 2),
                    "weight_g": round(mass, 2),
                    "shop": "printed",
                    "url": "/files/" + state.session_id + "/part-" + part["id"] + ".stl",
                    "price_source": "estimated",
                    "category": part["id"],
                }
            )
        elif part["kind"] == "bought":
            item = state.picked[part["id"]]
            items.append(
                {
                    "name": item["name"],
                    "qty": part["qty"],
                    "unit_price_eur": round(float(item.get("unit_price_eur") or 0.0), 2),
                    "weight_g": round(float(item.get("mass_g") or 0.0), 2),
                    "shop": item.get("shop", ""),
                    "url": item.get("url", ""),
                    "price_source": item.get("price_source", "sample"),
                    "category": part["id"],
                }
            )
    estimated = sum(1 for item in items if item["price_source"] == "estimated" and item["shop"] != "printed")

    def detail(total: float) -> str:
        text = "Bill of materials " + f"{total:.2f}" + " €, catalog prices are samples"
        return text + (", " + str(estimated) + " estimated" if estimated else "")

    return await _priced_bom(ctx, items, detail)
