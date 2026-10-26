"""The 3D printer beats of the offline demos: material per printed part, then FEM on its real shape.

Runs only when the user has set a printer (`pai_agent.printers`); without one the stories play as
before. The phone stand and the drone call `printed_parts` after their CAD, through the same tools
Claude uses, so the offline run shows the material choice, the CalculiX stress result on the
Simulation tab and the printer's own slicing and filament prices in the bill of materials.
"""

from __future__ import annotations

from pai_agent import printers
from pai_agent.context import Ctx
from pai_agent.tools.registry import call_tool


async def printed_parts(ctx: Ctx, parts: list[tuple[str, dict]], cases: dict[str, list[dict]] | None = None) -> list[dict]:
    """material_pick then fem_check for each (part_id, needs); cases names a part's own load cases. Returns the FEM results that ran."""

    from pai_agent.mock_story import _say

    printer = printers.current()
    if printer is None:
        return []
    await _say(
        ctx,
        "erklaert",
        "Your " + printer["name"] + ". Materials first.",
        "You print these on your " + printer["name"] + " with " + (", ".join(printer["printable"]) or "no filament it prints")
        + ". I pick each part's material from what it has to survive, then simulate it in CalculiX on its real shape.",
    )
    results = []
    for part_id, needs in parts:
        picked = await call_tool(ctx, "material_pick", {"part_id": part_id, **needs})
        if picked.get("ok") is False:
            await ctx.chat("agent", str(picked.get("error")))
            continue
        await ctx.chat("agent", picked["reason"])
    await call_tool(ctx, "ui_control", {"control": "tab:simulation"})
    for part_id, _needs in parts:
        result = await call_tool(ctx, "fem_check", {"part_id": part_id, **({"cases": cases[part_id]} if cases and part_id in cases else {})})
        if result.get("ok") is False:
            await ctx.chat("agent", "No FEM for this part: " + str(result.get("error")))
            continue
        results.append(result)
        worst = next(c for c in result["cases"] if c["name"] == result["governing"])
        safety = f"{result['safety']:.1f}x" if result["safety"] < 99 else "over 99x"
        await _say(
            ctx,
            "freut_sich" if result["result"] == "pass" else "besorgt",
            f"{result['part_name']}: {safety} safety.",
            f"FEM on the {result['part_name'].lower()} in {result['material']}: worst case {result['governing']}, {worst['max_von_mises_mpa']:.1f} MPa, "
            f"it bends {worst['max_deflection_mm']:.2f} mm, safety {safety} against {result['limit']:g}x. "
            + ("It holds." if result["result"] == "pass" else "Not enough. The plastic needs more section where it is most stressed.")
            + "".join(" " + note for note in result["notes"]),
        )
    return results
