"""Deterministic gripper demo through the same tools Claude uses.

The brief asks for a gripper that holds a 200 g can. The cheap SG90 is tried first:
the numbers say it is too weak, and the MuJoCo grip test shows the can sliding out
when the arm lifts. The swap to the MG996R passes. Then the part is built in
FreeCAD headless (servo pocket sized for the MG996R), rendered in Blender, weighed
again and put into a bill of materials.
"""

from __future__ import annotations

import re

from pai_agent.context import Ctx
from pai_agent.mock_story import _beat, _need, _safety, _say
from pai_agent.tools.registry import call_tool

GRIPPER_WORDS = re.compile(r"\b(gripper|greifer|claw|robot ?hand|end ?effector)\b", re.IGNORECASE)


def wants_gripper(text: str) -> bool:
    return bool(GRIPPER_WORDS.search(text))


def _brief_numbers(text: str) -> dict:
    """Pulls '200 g', '66 mm', '150 g' style numbers from the request; the demo values fill the gaps."""

    grams = [float(g) for g in re.findall(r"(\d+(?:\.\d+)?)\s*g\b", text)]
    mm = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*mm\b", text)]
    euros = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*(?:€|eur|euro)", text, re.IGNORECASE)]
    return {
        "object_mass_g": grams[0] if grams else 200.0,
        "object_width_mm": mm[0] if mm else 66.0,
        "max_weight_g": grams[1] if len(grams) > 1 else 150.0,
        "budget_eur": euros[0] if euros else 30.0,
    }


async def run_gripper_mock(ctx: Ctx, text: str) -> None:
    await _beat()
    numbers = _brief_numbers(text)
    await ctx.step("meeting", "running")
    await _say(ctx, "denkt", "A gripper, not a drone. Same workshop.", "Got it: a two-finger robot gripper. I turn your request into checks first.")
    await _need(ctx, "product_brief", {"product": "gripper", "quote": text.strip(), **numbers})
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": "From your request"})

    await _beat()
    await ctx.step("teile", "running")
    await _need(ctx, "catalog_search", {"category": "servo"})
    await _need(
        ctx,
        "catalog_search",
        {"category": "servo", "select_id": "towerpro-sg90", "reason": "Lightest and cheapest servo, 9 g for 2.49 €."},
    )
    await _need(ctx, "catalog_search", {"category": "pads", "select_id": "pads-tpu-printed", "reason": "Printed with the fingers, no extra part to buy."})
    await _need(ctx, "catalog_search", {"category": "hardware", "select_id": "m3-hardware-set", "reason": "M3 bolts as gear axles and for the wrist flange."})
    await _need(ctx, "catalog_search", {"category": "driver", "select_id": "pca9685-driver", "reason": "Runs the gripper servo next to the arm servos over I2C."})
    calc = await _need(ctx, "grip_calc", {})
    await _say(
        ctx,
        "besorgt",
        f"Safety only {calc['safety_factor']:.1f}x. Let's see it.",
        f"With the SG90 each finger pushes {calc['grip_force_n']:.1f} N. Friction holds {calc['hold_force_n']:.1f} N, "
        f"the can weighs {numbers['object_mass_g'] / 1000 * 9.81:.1f} N. That is a safety of {calc['safety_factor']:.1f}x, I want 2x. MuJoCo will show it.",
    )

    await _beat()
    sim = await _need(ctx, "simulate_grip", {})
    if sim["result"] == "fail":
        await _need(ctx, "ui_point_at", {"target": "metrics", "label": "Grip safety too low"})
        await _say(ctx, "besorgt", "It slips. The SG90 is too weak.", sim["summary"] + " I swap the servo for the MG996R: 9.4 kg cm, metal gears.")
        await _need(
            ctx,
            "catalog_search",
            {"category": "servo", "select_id": "towerpro-mg996r", "reason": "Five times the torque of the SG90 for 6.41 € more."},
        )
        calc = await _need(ctx, "grip_calc", {})
        sim = await _need(ctx, "simulate_grip", {})
    await _say(ctx, "freut_sich", "Holds through lift and shake.", sim["summary"])

    await _beat()
    await ctx.step("cad", "running")
    await _say(
        ctx,
        "erklaert",
        "Now the part in FreeCAD.",
        "Now the body in FreeCAD, headless: palm with wrist flange, two meshing gears, fingers with TPU pads. The servo pocket follows the MG996R.",
    )
    cad = await _need(
        ctx,
        "cad_part",
        {
            "name": "Robot gripper",
            "template": "gripper",
            "description": "Two-finger gear gripper for a robot arm",
            "material": "PLA",
            "params": {"jaw_opening_mm": max(76.0, numbers["object_width_mm"] + 10), "finger_length_mm": 70},
        },
    )
    await _need(ctx, "ui_point_at", {"target": "viewport", "label": f"Printed parts {cad['mass_g']:.0f} g"})
    calc = await _need(ctx, "grip_calc", {})

    await _beat()
    await ctx.step("render", "running")
    await call_tool(ctx, "blender_render", {})

    await _beat()
    await ctx.step("stueckliste", "running")
    await _safety(ctx)
    bom = await _need(ctx, "bom_build", {})
    await _need(ctx, "firmware", {})
    await ctx.step("stueckliste", "done")
    ctx.state.finished = True
    await _say(
        ctx,
        "freut_sich",
        f"Gripper done: {calc['weight_g']:.0f} g, {bom['total_eur']:.2f} €.",
        f"Done. The gripper weighs {calc['weight_g']:.0f} g, holds up to {calc['max_payload_g']:.0f} g at 2x safety and costs {bom['total_eur']:.2f} € in parts. "
        "Drag the sliders in the CAD tab and FreeCAD rebuilds it.",
    )
