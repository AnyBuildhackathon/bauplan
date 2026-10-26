"""Deterministic SolidCraft runs for PAI_CAD_ENGINE=solidcraft without a key, through the same tools Claude calls.

With SolidCraft as the CAD engine, a request that names a four-bar, a linkage or SolidCraft itself builds a design
from the library with solidcraft_part: the Chebyshev four-bar, or the two-finger gripper when it asks for a gripper.
export_urdf then writes its URDF and MJCF and runs it in MuJoCo through the design's motion study. Without
solidcraft-cli on the machine, Mechanic says how to install it.
"""

from __future__ import annotations

import re

from pai_agent import solidcraft
from pai_agent.context import Ctx
from pai_agent.mock_story import _beat, _say
from pai_agent.tools.registry import call_tool

_LINKAGE = re.compile(r"\b(four[- ]?bar|4[- ]bar|linkage|chebyshev)\b", re.IGNORECASE)
_SOLIDCRAFT = re.compile(r"\bsolid ?craft\b", re.IGNORECASE)
_GRIPPER = re.compile(r"\b(gripper|claw)\b", re.IGNORECASE)

_INTRO = {
    "four_bar": (
        "A four-bar. SolidCraft builds it.",
        (
            "The Chebyshev four-bar from SolidCraft's library: four parts on four hinges, and the last hinge closes the loop. "
            "SolidCraft builds it with its joints, then MuJoCo runs its robot description."
        ),
    ),
    "two_finger_gripper": (
        "A gripper on gears. SolidCraft builds it.",
        (
            "The two-finger gripper from the library: two fingers on meshing gears, so one drive closes both. "
            "SolidCraft builds it with its joints, then MuJoCo runs its robot description."
        ),
    ),
}


def wants_solidcraft(text: str) -> bool:
    """With SolidCraft as the CAD engine: a linkage, or anything asked of SolidCraft by name."""

    return solidcraft.engine() == "solidcraft" and bool(_LINKAGE.search(text) or _SOLIDCRAFT.search(text))


async def run_solidcraft_mock(ctx: Ctx, text: str) -> None:
    template = "two_finger_gripper" if _GRIPPER.search(text) and not _LINKAGE.search(text) else "four_bar"
    await _beat()
    await ctx.step("cad", "running")
    short, intro = _INTRO[template]
    await _say(ctx, "denkt", short, intro)
    part = await call_tool(ctx, "solidcraft_part", {"name": "", "template": template})
    if part.get("ok") is False:
        await ctx.step("cad", "failed")
        await _say(ctx, "besorgt", "SolidCraft is not installed here.", str(part.get("error")))
        return
    parts, joints = len(part["parts"]), len(part["joints"])
    await _say(
        ctx,
        "erklaert",
        f"{part['mass_g']:.1f} g, {joints} joints.",
        f"{part['design']} is built: {part['mass_g']:.1f} g of {part['material']}, {parts} parts on {joints} joints. Now its robot description, run in MuJoCo.",
    )
    await _beat()
    # The robot description stays on the CAD step: its MuJoCo check has no run to show in the Simulation tab.
    robot = await call_tool(ctx, "export_urdf", {})
    if robot.get("ok") is False:
        await ctx.step("cad", "failed")
        await _say(ctx, "besorgt", "The export failed.", str(robot.get("error")))
        return
    passed = robot.get("result") == "pass"
    await ctx.step("cad", "done" if passed else "failed")
    if passed:
        loops = [row["joint"] for row in robot["loops_closed"]]
        text = (
            f"URDF and MJCF are written. MuJoCo drove {robot['study']}: {'both' if len(robot['joints']) == 2 else 'all ' + str(len(robot['joints']))} joints moved"
            + (f", {', '.join(loops)} kept the loop closed" if loops else "")
            + (", the gears kept the fingers together" if robot["couplings"] else "")
            + f", and every part stayed where SolidCraft's study puts it. Masses match SolidCraft's measure within {max(r['error_pct'] for r in robot['masses']):.2f} %."
        )
        await _say(ctx, "freut_sich", "MuJoCo agrees with SolidCraft.", text)
    else:
        failed = ", ".join(key.replace("_", " ") for key, ok in robot["checks"].items() if not ok)
        await _say(ctx, "besorgt", "MuJoCo does not agree yet.", "The MuJoCo check failed: " + failed + ". " + robot["detail"])
