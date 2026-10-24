"""Versions: a snapshot copies the model and records the build, diff finds what changed, restore rebuilds."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pai_agent import versions
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState

SPEC = {
    "id": "phone-stand",
    "name": "Desk phone stand",
    "function": "Holds a phone",
    "parts": [
        {"id": "base", "name": "Base", "kind": "printed", "material": "PETG", "description": "Plate", "params": {"length_mm": 110}},
        {"id": "feet", "name": "Rubber feet", "kind": "bought", "description": "Feet"},
    ],
}


def _generic_ctx(length: float, feet: str, met: bool) -> Ctx:
    directory = Path(tempfile.mkdtemp())
    (directory / "assembly.glb").write_bytes(b"glb")
    state = BuildState(session_id="test", directory=directory)
    state.product = "generic"
    state.spec = json.loads(json.dumps(SPEC))
    state.built = {"base": {"params": {"length_mm": length}, "script": "print('base')", "generated": True}}
    state.picked = {"feet": {"id": feet, "name": feet.replace("-", " ").title()}}
    state.checks = {"tip_over": {"tool": "check_tip_over", "args": {"tilt_deg": 15}}}
    state.assembly = {"glb": "assembly.glb", "product_mass_g": 95.0 + length / 10, "cost_eur": 4.0}
    state.bom = {"total_eur": 4.5, "items": []}
    state.requirements = [{"id": "stable", "text": "Does not tip over", "_met": met}]
    ctx = Ctx(EventBus(), state, auto_steps=False)
    ctx.bus.events.append({"type": "metrics", "weight_g": 106.0, "price_eur": 4.5, "cards": [{"key": "tip", "label": "Tip angle", "value": 20 + length / 10, "unit": "°", "digits": 0}]})
    return ctx


class SnapshotAndDiff(unittest.TestCase):
    def test_commit_copies_the_model_and_diffs_against_the_last_version(self):
        ctx = _generic_ctx(110, "rubber-feet-10mm", met=False)
        ctx.trigger = "chat"
        first = asyncio.run(versions.commit(ctx, label="Design a phone stand"))
        self.assertEqual(first["n"], 1)
        self.assertEqual(first["trigger"], "chat")
        self.assertEqual(first["files"]["glb_url"], "/files/test/v1-assembly.glb")
        self.assertTrue((ctx.state.directory / "v1-assembly.glb").is_file())
        self.assertEqual(first["parts"], {"base": "Base", "feet": "Rubber Feet 10Mm"})
        self.assertEqual(first["nodes"]["feet"], "Rubber feet")
        self.assertEqual(first["params"], {"base.length_mm": 110})
        saved = json.loads((ctx.state.directory / "versions" / "v1" / "reference.json").read_text())
        self.assertEqual(saved["picks"], {"feet": {"select_id": "rubber-feet-10mm"}})
        self.assertEqual(saved["scripts"]["base"]["file"], "base.py")

        # The second build changes the base, swaps the feet and now passes the failed check.
        ctx.state.built["base"]["params"]["length_mm"] = 130
        ctx.state.picked["feet"] = {"id": "rubber-feet-12mm", "name": "Rubber Feet 12Mm"}
        ctx.state.assembly["product_mass_g"] = 108.0
        ctx.state.requirements[0]["_met"] = True
        second = asyncio.run(versions.commit(ctx, label="Make the base longer"))
        self.assertEqual(second["trigger"], "check_failed")
        keys = {row["key"]: row for row in second["diff"]}
        self.assertEqual(keys["weight_g"]["before"], 106.0)
        self.assertEqual(keys["weight_g"]["after"], 108.0)
        self.assertEqual(keys["part:feet"]["after"], "Rubber Feet 12Mm")
        self.assertEqual((keys["param:base.length_mm"]["before"], keys["param:base.length_mm"]["after"]), (110, 130))
        self.assertEqual((keys["req:stable"]["before"], keys["req:stable"]["after"]), ("fail", "pass"))
        published = [ev for ev in ctx.bus.events if ev["type"] == "version"]
        self.assertEqual([ev["n"] for ev in published], [1, 2])

    def test_drone_diff_has_numbers_and_the_battery_swap(self):
        v1 = {"product": "drone", "weight_g": 48.3, "flight_time_min": 8.2, "price_eur": 117.38, "thrust_to_weight": 4.14, "parts": {"battery": "Tattu R-Line 1S 550mAh 95C", "motor": "1103"}}
        v2 = {**v1, "weight_g": 49.5, "flight_time_min": 10.1, "parts": {"battery": "BetaFPV LAVA II 1S 680mAh 95C", "motor": "1103"}}
        rows = {row["key"]: row for row in versions.diff(v1, v2)}
        self.assertEqual(set(rows), {"weight_g", "flight_time_min", "part:battery"})
        self.assertEqual(rows["part:battery"]["before"], "Tattu R-Line 1S 550mAh 95C")
        self.assertEqual(versions.diff(None, v2), [])


class Restore(unittest.TestCase):
    def test_generic_restore_rebuilds_the_saved_build_through_the_tools(self):
        ctx = _generic_ctx(110, "rubber-feet-10mm", met=True)
        ctx.trigger = "chat"
        asyncio.run(versions.commit(ctx, label="Design a phone stand"))
        calls = []

        async def call_tool(ctx, name, args):
            calls.append((name, args))
            if name == "bom_build":
                await versions.after_tool(ctx, name, args, {"ok": True})
            return {"ok": True, "total_eur": 4.5}

        with mock.patch("pai_agent.tools.registry.call_tool", call_tool):
            restored = asyncio.run(versions.restore(ctx, 1))
        names = [name for name, _args in calls]
        self.assertEqual(names, ["product_spec", "cad_part", "part_pick", "assemble", "check_tip_over", "blender_render", "bom_build"])
        self.assertEqual(calls[1][1]["script"], "print('base')\n")
        self.assertEqual(calls[2][1], {"part_id": "feet", "select_id": "rubber-feet-10mm"})
        self.assertEqual(restored["n"], 2)
        self.assertEqual(restored["trigger"], "restore")
        self.assertEqual(restored["restored_from"], 1)
        self.assertEqual(len(ctx.state.versions), 2)

    def test_unknown_version_is_refused(self):
        ctx = _generic_ctx(110, "rubber-feet-10mm", met=True)
        with self.assertRaises(ValueError):
            asyncio.run(versions.restore(ctx, 4))


if __name__ == "__main__":
    unittest.main()
