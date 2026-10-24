"""Checks general CAD without a network: sandbox rules, the retry loop and the gripper template.

    cd agent && uv run python scripts/smoke_cad_part.py

The script writer is replaced by a stub that first returns a broken script and then
the fix, so the retry path runs exactly as it does with Claude. Needs freecadcmd.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from pai_agent.bus import EventBus
from pai_agent.cad_script import ScriptRejected, check_script
from pai_agent.context import Ctx
from pai_agent.paths import SESSIONS_DIR
from pai_agent.state import BuildState
from pai_agent.tools import cad_part as cad

BROKEN = "W = P.get('width_mm', 40.0)\nshape = Part.makeBox(W, W, 'ten')\n"
FIXED = (
    "W = P.get('width_mm', 40.0)\n"
    "plate = Part.makeBox(W, W, 4)\n"
    "for x in (6, W - 6):\n"
    "    for y in (6, W - 6):\n"
    "        plate = plate.cut(Part.makeCylinder(1.7, 6, Vector(x, y, -1)))\n"
    "shape = plate\n"
)


def check(condition: bool, message: str) -> None:
    print(("ok   " if condition else "FAIL ") + message)
    if not condition:
        sys.exit(1)


def rejected(source: str) -> bool:
    try:
        check_script(source)
    except ScriptRejected:
        return True
    return False


async def main() -> None:
    check(rejected("import os\nshape = None"), "import os is rejected")
    check(rejected("shape = open('/etc/passwd')"), "open() is rejected")
    check(rejected("x = Part.__class__"), "dunder access is rejected")
    check(not rejected(FIXED), "a plain Part script passes the static check")

    events: list[dict] = []
    # Under the repository, because the build records its STL path relative to it.
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="smoke-", dir=SESSIONS_DIR))
    try:
        await run(directory, events)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


async def run(directory: Path, events: list[dict]) -> None:
    class Bus(EventBus):
        async def publish(self, event: dict) -> None:
            events.append(event)

    ctx = Ctx(Bus(), BuildState(session_id="smoke", directory=directory), auto_steps=False)

    calls: list[str | None] = []

    def stub(description: str, params: dict, previous: str | None, error: str | None) -> str:
        calls.append(error)
        return BROKEN if previous is None else FIXED

    cad._write_script = stub
    cad.claude_enabled = lambda: True
    result = await cad.cad_part(ctx, {"name": "Mounting plate", "description": "Square plate with four M3 holes", "params": {"width_mm": 40}})
    check(result["ok"] is True, "generated part builds: " + str(result.get("detail") or result.get("error")))
    check(len(result["attempts"]) == 2 and result["attempts"][0]["ok"] is False, "first script failed, second was fixed")
    check(calls[1] is not None and "Error" in calls[1], "the FreeCAD error went back to the writer")
    check(abs(result["mass_g"] - 7.85) < 0.3, f"mass {result['mass_g']} g PLA for a 40 x 40 x 4 plate minus holes")
    check(any(e["type"] == "cad" and e.get("script_url") for e in events), "a cad event carries the script")

    result = await cad.cad_part(ctx, {"name": "Robot gripper", "template": "gripper"})
    check(result["ok"] is True and len(result["parts"]) == 8, "gripper template builds 8 parts")
    rebuilt = await cad.rebuild_part(ctx, {"finger_length_mm": 90})
    check(rebuilt["ok"] is True and rebuilt["bbox_mm"][4] > result["bbox_mm"][4], "a longer finger makes a longer part")


if __name__ == "__main__":
    asyncio.run(main())
