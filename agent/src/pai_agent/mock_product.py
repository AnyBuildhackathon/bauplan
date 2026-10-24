"""Deterministic generic-product demo through the same tools Claude uses, for runs without a key.

The request is a desk phone stand. Mechanic writes the spec, FreeCAD builds the base and
the back rest headless from the library scripts, the rubber feet come from the catalog.
The tip-over check fails: a 60 mm deep base tips back under a 0.75 N tap on the top of
the phone, and the MuJoCo push test shows it falling over. Mechanic deepens the base to
110 mm, every check runs again and passes, then Blender renders it and the bill of
materials closes the build.
"""

from __future__ import annotations

import re

from pai_agent.context import Ctx
from pai_agent.mock_story import _beat, _need, _say
from pai_agent.references import REFERENCES_DIR
from pai_agent.tools.registry import call_tool

# The scripts of the phone stand reference build; the story starts it with a shallower base.
SCRIPTS = REFERENCES_DIR / "phone-stand"
PRODUCT_WORDS = re.compile(r"\b(phone|smartphone|tablet)\b.*\b(stand|holder|dock|mount)\b|\b(stand|holder|dock)\b.*\b(phone|smartphone|tablet)\b", re.IGNORECASE)


def wants_product(text: str) -> bool:
    return bool(PRODUCT_WORDS.search(text))


def _spec(quote: str) -> dict:
    return {
        "name": "Phone stand",
        "function": "Holds a smartphone at 65 degrees on a desk for video calls, with a slot for the charging cable.",
        "quote": quote,
        "assemblies": [{"id": "stand", "name": "Stand"}],
        "requirements": [
            {"id": "mass", "text": "Weighs under 150 g", "check": "mass", "max": 150, "unit": "g"},
            {"id": "cost", "text": "Parts under 6 €", "check": "cost", "max": 6, "unit": "eur"},
            {"id": "tap", "text": "A 0.75 N tap on the phone top does not tip it", "check": "tip_over", "min": 0.75, "unit": "N"},
            {"id": "push", "text": "Settles upright after the MuJoCo push", "check": "stability", "max": 5, "unit": "deg"},
            {"id": "stiff", "text": "Back rest bends under 1 mm at 5 N", "check": "deflection", "max": 1, "unit": "mm", "part_id": "back-rest"},
            {"id": "printable", "text": "Printable parts with STL and STEP", "check": "printable"},
        ],
        "parts": [
            {
                "id": "base",
                "name": "Base plate",
                "kind": "printed",
                "assembly": "stand",
                "material": "PETG",
                "description": "Flat plate 80 mm wide from y = -25 backwards, 5 mm thick, with a 12 mm front lip the phone stands behind and a cable slot through the lip.",
                "size_mm": [80, 60, 17],
                "params": {"width_mm": 80, "depth_mm": 60, "thickness_mm": 5, "lip_height_mm": 12},
            },
            {
                "id": "back-rest",
                "name": "Back rest",
                "kind": "printed",
                "assembly": "stand",
                "material": "PETG",
                "description": "Plate 70 mm wide and 95 mm long leaning back at 65 degrees on the base top at y = -10, braced by two triangular gussets.",
                "size_mm": [70, 45, 88],
                "params": {"width_mm": 70, "support_length_mm": 95, "thickness_mm": 5, "angle_deg": 65},
            },
            {"id": "feet", "name": "Rubber feet", "kind": "bought", "qty": 4, "category": "hardware", "query": "rubber feet"},
            {
                "id": "phone",
                "name": "Smartphone",
                "kind": "external",
                "mass_g": 200,
                "size_mm": [75, 9, 160],
                "position_mm": [0, 19.7, 79.4],
                "rotation_deg": [-25, 0, 0],
            },
        ],
    }


async def run_product_mock(ctx: Ctx, text: str) -> None:
    await _beat()
    await ctx.step("meeting", "running")
    await _say(
        ctx,
        "denkt",
        "A phone stand. First the spec.",
        "A phone stand for the desk. I write the spec first: what it must do, every part, and the check that judges each requirement.",
    )
    await _need(ctx, "product_spec", _spec(text.strip()))
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": "Checks from your request"})

    await _beat()
    await ctx.step("cad", "running")
    await _say(ctx, "erklaert", "Now FreeCAD, part by part.", "FreeCAD builds the two printed parts headless: the base plate with a cable slot, then the back rest at 65 degrees.")
    await _need(
        ctx,
        "cad_part",
        {"part_id": "base", "script": (SCRIPTS / "base.py").read_text(encoding="utf-8"), "_generated": False},
    )
    await _need(
        ctx,
        "cad_part",
        {"part_id": "back-rest", "script": (SCRIPTS / "back-rest.py").read_text(encoding="utf-8"), "_generated": False},
    )

    await _beat()
    await ctx.step("teile", "running")
    await _need(ctx, "part_pick", {"part_id": "feet", "query": "rubber feet"})
    await _need(ctx, "part_pick", {"part_id": "feet", "select_id": "rubber-feet-10mm", "reason": "Four non-slip feet keep it from sliding on the desk."})
    assembled = await _need(ctx, "assemble", {})
    totals = await _need(ctx, "check_totals", {})
    await _say(
        ctx,
        "erklaert",
        f"{totals['mass_g']:.0f} g, {totals['cost_eur']:.2f} €.",
        f"Assembled: {totals['mass_g']:.0f} g of plastic and feet for {totals['cost_eur']:.2f} €. With the phone it weighs {assembled['total_mass_g_with_loads']:.0f} g. Now: does it stay put when you tap the screen?",
    )

    await _beat()
    await ctx.step("simulation", "running")
    tip = await _need(ctx, "check_tip_over", {})
    sim = await _need(ctx, "simulate_assembly", {"mode": "push", "force_n": 0.75})
    summary = sim["summary"]
    if tip["result"] == "fail" or sim["result"] == "fail":
        await _need(ctx, "ui_point_at", {"target": "viewport", "label": "Tips backwards"})
        await _say(
            ctx,
            "besorgt",
            f"It tips at {tip['force_n']:.2f} N. Too little.",
            f"Fail. The phone sits high and far back: a tap of {tip['force_n']:.2f} N on its top already tips the stand, I want 0.75 N. "
            + sim["summary"]
            + " I make the base deeper behind the phone, 60 to 110 mm, so the back edge moves out past the centre of mass. The checks run again on the new base.",
        )
        await _need(ctx, "cad_update", {"part_id": "base", "params": {"depth_mm": 110}})
        summary = (ctx.state.last_sim or {}).get("summary", summary)
    deflection = await _need(
        ctx,
        "check_deflection",
        {"part_id": "back-rest", "span_mm": 40, "width_mm": 70, "thickness_mm": 5, "load_n": 5, "support": "cantilever"},
    )
    await _say(
        ctx,
        "freut_sich",
        "Stays put now.",
        summary + f" The free top of the back rest bends {deflection['deflection_mm']:.2f} mm under a 5 N press, stress safety {deflection['stress_safety']:.0f}x.",
    )

    await _beat()
    await ctx.step("render", "running")
    await call_tool(ctx, "blender_render", {})

    await _beat()
    await ctx.step("stueckliste", "running")
    totals = await _need(ctx, "check_totals", {})
    bom = await _need(ctx, "bom_build", {})
    await ctx.step("stueckliste", "done")
    ctx.state.finished = True
    await _say(
        ctx,
        "freut_sich",
        f"Phone stand done: {totals['mass_g']:.0f} g, {bom['total_eur']:.2f} €.",
        f"Done. Two PETG parts and four rubber feet, {totals['mass_g']:.0f} g and {bom['total_eur']:.2f} € in parts. "
        "Drag the sliders in the CAD tab and FreeCAD rebuilds it, then every check runs again.",
    )
