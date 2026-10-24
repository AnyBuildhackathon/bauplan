"""Checks the any-product flow without a network: spec validation, the checks and the phone stand story.

    cd agent && uv run python scripts/smoke_product.py

The phone stand mock runs through the same tools Claude uses: the spec, two printed parts
built by freecadcmd, a catalog pick, the assembly, a failed tip-over check and MuJoCo push,
the fix with cad_update, and the bill of materials. Then every reference build in
agent/data/references/ loads through the same tools and must pass its requirements.
Needs freecadcmd.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys

os.environ["PAI_FORCE_MOCK"] = "1"

from pai_agent import analysis
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.mock_product import _spec, run_product_mock
from pai_agent.paths import SESSIONS_DIR
from pai_agent.references import build_reference, list_references
from pai_agent.spec import SpecError, validate_spec
from pai_agent.state import BuildState
from pai_agent.tools.jamie import init_timeline


def check(condition: bool, message: str) -> None:
    print(("ok   " if condition else "FAIL ") + message)
    if not condition:
        sys.exit(1)


def problems(raw: dict) -> list[str]:
    try:
        validate_spec(raw)
    except SpecError as exc:
        return exc.problems
    return []


async def main() -> None:
    good = _spec("Build me a phone stand")
    check(problems(good) == [], "the phone stand spec validates")
    broken = {**good, "parts": [{**good["parts"][0], "size_mm": None, "material": "WOOD"}, *good["parts"][1:]]}
    found = problems(broken)
    check(any("material" in p for p in found) and any("size_mm" in p for p in found), "a spec lists every problem at once")
    check(any("check must be" in p for p in problems({**good, "requirements": [{"text": "Looks nice", "check": "beauty"}]})), "an unknown check is rejected")

    tip = analysis.tip_over([[-50, -50], [50, -50], [50, 50], [-50, 50]], [0, 0, 50], 0, 1000, 100)
    check(abs(tip["angle_deg"] - 45.0) < 0.1 and abs(tip["force_n"] - 4.9) < 0.05, "a 100 mm cube with its centre at 50 mm tips at 45 degrees")
    beam = analysis.deflection("ALUMINIUM", 100, 10, 2, 1, "cantilever")
    check(abs(beam["deflection_mm"] - 0.725) < 0.01, "cantilever deflection is F L^3 / 3 E I")
    run = analysis.runtime({"capacity_mah": 3000, "voltage_v": 3.6}, [{"name": "esp32", "power_w": 0.5, "duty": 1.0}])
    check(abs(run["runtime_h"] - 17.28) < 0.01, "runtime uses 80 percent of the battery energy")

    session = "smoke-product"
    directory = SESSIONS_DIR / session
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    bus = EventBus()
    state = BuildState(session_id=session, directory=directory)
    ctx = Ctx(bus, state, auto_steps=False)
    await run_product_mock(ctx, "Build me a phone stand for my desk")

    runs = [e for e in bus.events if e["type"] == "sim"]
    check(len(runs) == 2 and runs[0]["result"] == "fail" and runs[1]["result"] == "pass", "the 60 mm base tips over, the 110 mm base stays up")
    check(all(r["kind"] == "rigid" and r["poses"] and r["glb_url"].startswith("/files/" + session) for r in runs), "push runs carry poses and the assembly model")
    final = {e["id"]: e for e in bus.events if e["type"] == "requirement"}
    check(all(r["met"] is True for r in final.values()), "every requirement passes at the end: " + ", ".join(f"{k}={v['met']}" for k, v in final.items()))
    check(final["tap"]["detail"].startswith("0.81 N"), "the tip-over detail names the push that tips it")
    cad = [e for e in bus.events if e["type"] == "cad" and e.get("assembly")][-1]
    check("base.depth_mm" in cad["params"] and cad["params"]["base.depth_mm"]["value"] == 110, "the assembly sliders name the part and show the fix")
    bom = [e for e in bus.events if e["type"] == "bom"][-1]
    parts = [item for item in bom["items"] if not item["name"].startswith("Filament")]
    check(len(parts) == 3 and abs(bom["total_eur"] - 3.32) < 0.05, "the bill of materials has two printed parts and the feet for 3.32 EUR (plus the filament line)")
    check(all((directory / name).is_file() for name in ("assembly.glb", "assembly.stl", "part-base.step", "part-back-rest.step")), "assembly and part files are on disk")
    check(state.built["base"]["generated"] is False, "library scripts are not reported as written by Claude")

    from pai_agent.tools.product import cad_update

    result = await cad_update(ctx, {"part_id": "base", "params": {"depth_mm": 60}})
    rerun = {row["check"]: row["result"] for row in result.get("checks", [])}
    check(rerun.get("tip_over") == "fail" and rerun.get("stability") == "fail", "moving the slider back reruns every check and fails again")
    shutil.rmtree(directory, ignore_errors=True)

    references = list_references()
    check([r["id"] for r in references[:2]] == ["micro-drone", "robot-gripper"], "the library starts with the drone and the gripper, built by their own code")
    check(any(r["id"] == "phone-stand" for r in references), "the registry has the phone stand reference")
    ids = {r["id"] for r in references}
    check({"desk-lamp", "bike-mount", "pet-feeder"} <= ids, "the registry has the desk lamp, the bike mount and the pet feeder")
    check("otto-biped" in ids, "the registry has the Otto DIY biped robot")
    for row in references:
        folder = SESSIONS_DIR / ("smoke-ref-" + row["id"])
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        ref_state = BuildState(session_id=folder.name, directory=folder)
        init_timeline(ref_state)
        result = await build_reference(Ctx(EventBus(), ref_state, auto_steps=False), row["id"])
        check(
            result["requirements_passed"] == result["requirements"],
            f"reference {row['id']} rebuilds and passes {result['requirements_passed']}/{result['requirements']}",
        )
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
