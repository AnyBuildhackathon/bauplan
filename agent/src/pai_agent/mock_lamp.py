"""Deterministic desk lamp run for the safety check, through the same tools Claude uses, for runs without a key.

A lamp request that names mains (230 V, mains, a wall socket) puts it into a printed desk lamp. Mechanic writes the spec, the safety
check flags the mains voltage inside PETG, and Mechanic offers the fix it can apply: a
USB-C 5 V supply, so only safety extra-low voltage enters the printed parts. The revised
spec runs the check again. Without a key the run stops before FreeCAD; with Claude the
same tools build it.
"""

from __future__ import annotations

import copy
import re

from pai_agent.context import Ctx
from pai_agent.mock_story import _beat, _need, _safety, _say
from pai_agent.tools.safety import MAINS

LAMP_WORDS = re.compile(r"\b(desk|table|bedside|reading|floor)?\s*lamp\b", re.IGNORECASE)

_PRINTED = [
    {
        "id": "base",
        "name": "Weighted base",
        "kind": "printed",
        "material": "PETG",
        "description": "Plate 150 x 175 x 10 mm with rounded corners, an 18 mm square socket for the post at the back and a switch cut-out at the front.",
        "size_mm": [150, 175, 10],
        "params": {"width_mm": 150, "depth_mm": 175, "thickness_mm": 10},
    },
    {
        "id": "post",
        "name": "Post",
        "kind": "printed",
        "material": "PETG",
        "description": "Square post 18 x 18 mm standing 272 mm tall in the base socket, with an 11 mm bore along its length for the wires.",
        "size_mm": [18, 18, 272],
        "params": {"side_mm": 18, "height_mm": 272, "bore_mm": 11},
    },
    {
        "id": "arm",
        "name": "Arm",
        "kind": "printed",
        "material": "PETG",
        "description": "Horizontal bar 16 x 13 mm on top of the post reaching 200 mm forwards, with a wire groove along the underside.",
        "size_mm": [16, 232, 13],
        "params": {"width_mm": 16, "thickness_mm": 13, "reach_mm": 200},
    },
    {
        "id": "head",
        "name": "Lamp head",
        "kind": "printed",
        "material": "PETG",
        "description": "Open-bottom square shade 64 x 64 x 32 mm with 2 mm walls hanging under the arm end, two vent slots in the roof.",
        "size_mm": [64, 64, 32],
        "params": {"width_mm": 64, "height_mm": 32, "wall_mm": 2},
    },
]

_MAINS_PARTS = [
    {"id": "light", "name": "230 V LED bulb with E14 socket", "kind": "bought", "category": "light", "query": "E14 LED bulb 230 V 4 W with socket"},
    {"id": "power", "name": "Mains cord with inline switch, 230 V", "kind": "bought", "category": "power", "query": "230 V mains cord with inline switch"},
]

_USB_PARTS = [
    {"id": "light", "name": "1 W white LED on a star", "kind": "bought", "category": "light", "query": "1 W white LED star"},
    {"id": "power", "name": "USB-C cable and CE-marked 5 V wall adapter", "kind": "bought", "category": "power", "query": "USB-C cable and 5 V 2 A wall adapter"},
]


def wants_lamp(text: str) -> bool:
    """A lamp on mains; a USB-C lamp is no safety story."""

    return bool(LAMP_WORDS.search(text) and MAINS.search(text))


def _spec(quote: str, function: str, bought: list[dict]) -> dict:
    return {
        "name": "Desk lamp",
        "function": function,
        "quote": quote,
        "requirements": [
            {"id": "mass", "text": "Weighs under 600 g", "check": "mass", "max": 600, "unit": "g"},
            {"id": "cost", "text": "Parts under 30 €", "check": "cost", "max": 30, "unit": "eur"},
            {"id": "printable", "text": "Printable parts with STL and STEP", "check": "printable"},
        ],
        "parts": copy.deepcopy(_PRINTED) + copy.deepcopy(bought) + [{"id": "feet", "name": "Rubber feet", "kind": "bought", "qty": 4, "category": "hardware", "query": "rubber feet"}],
    }


async def run_lamp_mock(ctx: Ctx, text: str) -> None:
    await _beat()
    await ctx.step("meeting", "running")
    await _say(
        ctx,
        "denkt",
        "A desk lamp. Spec first.",
        "A desk lamp on a 200 mm arm. I write the spec first, and before any part is ordered the safety check reads it.",
    )
    quote = text.strip()
    await _need(
        ctx,
        "product_spec",
        _spec(quote, "A reading lamp on mains: a 230 V E14 LED bulb in a printed shade on a 200 mm arm, a mains cord with an inline switch into the base.", _MAINS_PARTS),
    )
    await ctx.step("meeting", "done")

    await _beat()
    await ctx.step("stueckliste", "running")
    first = await _safety(ctx, quote)
    top = first.get("top") or {}
    if top.get("id") != "mains-voltage":
        await ctx.step("stueckliste", "done")
        return
    answer = await _need(
        ctx,
        "ask_user",
        {
            "question": "Mains inside printed PETG needs class II insulation and a CE assessment. Switch the lamp to a USB-C 5 V supply, or keep 230 V?",
            "options": [
                {"id": "usb-c", "label": "Switch to USB-C 5 V (recommended)"},
                {"id": "mains", "label": "Keep 230 V with a certified driver"},
            ],
            "default_id": "usb-c",
        },
    )
    if answer["answer_id"] != "usb-c":
        await _say(
            ctx,
            "besorgt",
            "Keeping 230 V. Careful.",
            "Keeping 230 V. Then the bulb socket and cord must be bought CE-marked, the cord gets a strain relief, and the printed parts stay class II with no exposed metal. "
            "A hint, not legal advice: a lamp you sell needs its own Low Voltage Directive assessment.",
        )
        await ctx.step("stueckliste", "done")
        return
    await _need(
        ctx,
        "product_spec",
        _spec(
            answer["answer"],
            "A reading lamp powered over USB-C: a 1 W white LED in a printed shade on a 200 mm arm, a CE-marked 5 V wall adapter outside the lamp.",
            _USB_PARTS,
        ),
    )
    second = await _safety(ctx)
    left = second.get("top")
    await _say(
        ctx,
        "freut_sich",
        "Mains is out of the lamp now.",
        "Fixed: only 5 V from the USB-C adapter reaches the printed parts, so the mains warning is gone."
        + (" Still open: " + left["title"] + "." if left else "")
        + " Without a key the run stops here; with Claude, FreeCAD builds the four printed parts next.",
    )
    await ctx.step("stueckliste", "done")
