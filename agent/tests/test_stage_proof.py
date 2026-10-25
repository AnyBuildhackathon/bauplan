"""Stage-proofing: a stuck tool times out with a message, identical builds come from the cache, no FreeCAD still builds."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pai_agent import cache, cad_script, timeouts
from pai_agent.bus import EventBus
from pai_agent.cad_script import PartBuild
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools import registry


def _ctx(directory: Path) -> Ctx:
    return Ctx(EventBus(), BuildState(session_id="t", directory=directory), auto_steps=True)


class TimeoutTest(unittest.TestCase):
    def test_slow_tool_times_out_with_error_event(self):
        async def slow(ctx, args):
            await asyncio.sleep(5)
            return {"ok": True}

        with tempfile.TemporaryDirectory() as tmp, patch.dict(registry.TOOLS, {"slow_tool": slow}), patch.dict(os.environ, {"PAI_TIMEOUT_SLOW_TOOL": "0.05"}):
            ctx = _ctx(Path(tmp))
            result = asyncio.run(registry.call_tool(ctx, "slow_tool", {}))
            events = ctx.bus.events
        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])
        self.assertIn("took longer than 0.05 s", result["error"])
        final = [e for e in events if e["type"] == "tool" and e["name"] == "slow_tool"][-1]
        self.assertEqual(final["status"], "error")
        self.assertTrue(final["timed_out"])
        self.assertGreaterEqual(final["ms"], 40)
        self.assertTrue(any(e["type"] == "chat" and "took longer" in e["text"] for e in events))

    def test_fast_tool_reports_wall_time(self):
        async def fast(ctx, args):
            return {"ok": True, "detail": "done"}

        with tempfile.TemporaryDirectory() as tmp, patch.dict(registry.TOOLS, {"fast_tool": fast}):
            ctx = _ctx(Path(tmp))
            result = asyncio.run(registry.call_tool(ctx, "fast_tool", {}))
            final = ctx.bus.events[-1] if ctx.bus.events[-1]["type"] == "tool" else [e for e in ctx.bus.events if e["type"] == "tool"][-1]
        self.assertTrue(result["ok"])
        self.assertEqual(final["status"], "ok")
        self.assertIn("ms", final)
        self.assertNotIn("timed_out", final)

    def test_limits_and_overrides(self):
        self.assertEqual(timeouts.limit("blender_render"), 200.0)
        self.assertEqual(timeouts.limit("not_in_the_table"), timeouts.DEFAULT_S)
        with patch.dict(os.environ, {"PAI_TIMEOUT_BLENDER_RENDER": "0"}):
            self.assertIsNone(timeouts.limit("blender_render"))
        # Every outer limit sits above the tool's own subprocess timeout, so the inner fallback fires first.
        self.assertGreater(timeouts.limit("cad_part"), cad_script.TIMEOUT_S)


class CacheTest(unittest.TestCase):
    def test_second_identical_part_build_is_a_hit(self):
        calls = []

        def fake_run(source, params, out_dir, stem, material="PLA", timeout_s=60, expected_mm=None):
            calls.append(stem)
            out_dir.mkdir(parents=True, exist_ok=True)
            for suffix in (".stl", ".step", ".glb", "-0.stl"):
                (out_dir / (stem + suffix)).write_text("mesh " + suffix, encoding="utf-8")
            row = {"name": "Body", "volume_mm3": 1000.0, "mass_g": 1.24, "material": "PLA", "reference": False, "bbox_mm": [0, 0, 0, 10, 10, 10], "stl": stem + "-0.stl", "color": None}
            return PartBuild([row], [0, 0, 0, 10, 10, 10], 1000.0, 1.24, out_dir / (stem + ".stl"), out_dir / (stem + ".step"), out_dir / (stem + ".glb"))

        with tempfile.TemporaryDirectory() as tmp, patch.object(cache, "CACHE_DIR", Path(tmp) / "cache"), patch.object(cad_script, "run_script", fake_run), patch.dict(os.environ, {"PAI_CACHE": "1"}):
            first, first_cached = cad_script.run_script_cached("shape = 1", {"w": 10}, Path(tmp) / "a", "part-base", "PLA")
            second, second_cached = cad_script.run_script_cached("shape = 1", {"w": 10}, Path(tmp) / "b", "part-other", "PLA")
            _changed, changed_cached = cad_script.run_script_cached("shape = 1", {"w": 11}, Path(tmp) / "c", "part-base", "PLA")
            self.assertEqual((first_cached, second_cached, changed_cached), (False, True, False))
            self.assertEqual(calls, ["part-base", "part-base"])
            self.assertEqual(second.mass_g, first.mass_g)
            self.assertEqual(second.parts[0]["stl"], "part-other-0.stl")
            for path in (second.stl, second.step, second.glb, Path(tmp) / "b" / "part-other-0.stl", Path(tmp) / "b" / "part-other.py"):
                self.assertTrue(path.is_file(), path)

    def test_cache_off(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(cache, "CACHE_DIR", Path(tmp)), patch.dict(os.environ, {"PAI_CACHE": "0"}):
            source = Path(tmp) / "x.txt"
            source.write_text("x", encoding="utf-8")
            cache.store("k", "e", {"x.txt": source})
            self.assertIsNone(cache.restore("k", "e", {}))


class NoFreeCADTest(unittest.TestCase):
    def test_cadquery_block_stands_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            build = cad_script.run_block([80, 60, 17], None, Path(tmp), "part-base", "PETG")
            self.assertTrue(build.stl.is_file() and build.step.is_file() and build.glb.is_file())
            self.assertEqual(build.bbox_mm, [-40.0, -30.0, 0.0, 40.0, 30.0, 17.0])
            self.assertAlmostEqual(build.mass_g, 80 * 60 * 17 / 1000 * 1.27, places=1)

    def test_missing_freecad_counts_as_unavailable(self):
        with patch.object(cad_script, "find_freecadcmd", return_value=None):
            self.assertTrue(cad_script.freecad_unavailable("anything"))
        with patch.object(cad_script, "find_freecadcmd", return_value="/usr/bin/freecadcmd"):
            self.assertTrue(cad_script.freecad_unavailable("The script ran longer than 60 s."))
            self.assertFalse(cad_script.freecad_unavailable("NameError: name 'x' is not defined"))


if __name__ == "__main__":
    unittest.main()
