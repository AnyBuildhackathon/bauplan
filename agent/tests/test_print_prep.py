"""print_prep reads the printed STLs, warns about printability and estimates without a slicer."""

import asyncio
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools import print_prep as pp


def _box(x: float, y: float, z: float, x0: float = 0.0, z0: float = 0.0) -> list:
    v = [(x0, 0, z0), (x0 + x, 0, z0), (x0 + x, y, z0), (x0, y, z0), (x0, 0, z0 + z), (x0 + x, 0, z0 + z), (x0 + x, y, z0 + z), (x0, y, z0 + z)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return [[v[a], v[b], v[c]] for a, b, c in faces]


def _write_stl(path: Path, tris: list) -> Path:
    with path.open("wb") as out:
        out.write(b"\0" * 80 + struct.pack("<I", len(tris)))
        for tri in tris:
            out.write(struct.pack("<3f", 0, 0, 0))
            for vertex in tri:
                out.write(struct.pack("<3f", *vertex))
            out.write(b"\0\0")
    return path


def _ctx(directory: Path) -> Ctx:
    state = BuildState(session_id=directory.name, directory=directory)
    state.product = "generic"
    state.spec = {
        "parts": [
            {"id": "base", "name": "Base plate", "kind": "printed", "qty": 1},
            {"id": "arm", "name": "Arm", "kind": "printed", "qty": 2},
            {"id": "feet", "name": "Rubber feet", "kind": "bought", "qty": 4},
        ]
    }
    state.built = {
        "base": {"material": "PETG", "params": {"thickness_mm": 5.0}},
        # An L whose top bar hangs out flat: a 90 degree overhang.
        "arm": {"material": "PLA", "params": {"wall_mm": 0.6}},
    }
    _write_stl(directory / "part-base.stl", _box(80, 110, 5))
    _write_stl(directory / "part-arm.stl", _box(10, 10, 40) + _box(30, 10, 5, x0=10, z0=35))
    state.bom = {
        "items": [
            {"name": "Base plate, printed PETG", "qty": 1, "unit_price_eur": 1.1, "weight_g": 50, "shop": "printed", "url": ""},
            {"name": "Rubber feet", "qty": 4, "unit_price_eur": 0.5, "weight_g": 1, "shop": "Shop", "url": ""},
        ],
        "total_eur": 3.1,
        "stl_path": "",
        "prices": "catalog",
    }
    return Ctx(EventBus(), state, auto_steps=False)


class MeshTest(unittest.TestCase):
    def test_box_volume_area_and_no_overhang(self):
        mesh = pp.analyse(np.array(_box(20, 10, 5), dtype=float))
        self.assertAlmostEqual(mesh["volume_mm3"], 1000, places=3)
        self.assertAlmostEqual(mesh["area_mm2"], 2 * (200 + 100 + 50), places=3)
        self.assertEqual(mesh["size_mm"], [20.0, 10.0, 5.0])
        self.assertEqual(mesh["overhang_mm2"], 0.0)

    def test_flat_orientation_lays_the_largest_face_down(self):
        tris, rotation = pp.orient(np.array(_box(5, 80, 40), dtype=float), "flat")
        self.assertEqual(sorted(pp.analyse(tris)["size_mm"]), [5.0, 40.0, 80.0])
        self.assertEqual(pp.analyse(tris)["size_mm"][2], 5.0)
        self.assertEqual(rotation, [0.0, 90.0])

    def test_warnings_overhang_thin_wall_and_bed(self):
        hanging = pp.analyse(np.array(_box(10, 10, 40) + _box(30, 10, 5, x0=10, z0=35), dtype=float))
        kinds = [w["kind"] for w in pp.warnings_for(hanging, 0.6)]
        self.assertEqual(kinds, ["overhang", "thin_wall"])
        large = pp.analyse(np.array(_box(250, 30, 10), dtype=float))
        self.assertEqual([w["kind"] for w in pp.warnings_for(large, None)], ["bed_size"])

    def test_estimate_scales_with_volume(self):
        small = pp.estimate(pp.analyse(np.array(_box(20, 20, 20), dtype=float)), "PLA")
        big = pp.estimate(pp.analyse(np.array(_box(40, 40, 40), dtype=float)), "PLA")
        self.assertGreater(big["filament_g"], 4 * small["filament_g"])
        self.assertGreater(big["time_min"], small["time_min"])
        self.assertAlmostEqual(small["cost_eur"], round(small["filament_g"] * 0.025, 2), places=2)


class GcodeTest(unittest.TestCase):
    def test_parses_prusaslicer_and_orcaslicer_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            prusa = Path(tmp) / "a.gcode"
            prusa.write_text("G1 X1\n; filament used [mm] = 1234.5\n; filament used [g] = 3.71\n; estimated printing time (normal mode) = 1h 2m 30s\n")
            self.assertEqual(pp.parse_gcode(prusa), {"time_min": 62.0, "filament_g": 3.7, "filament_m": 1.23})
            orca = Path(tmp) / "b.gcode"
            orca.write_text("; total estimated time: 25m 10s\n; total filament weight [g] : 8.40\n")
            self.assertEqual(pp.parse_gcode(orca), {"time_min": 25.0, "filament_g": 8.4})


class PrintPrepTest(unittest.TestCase):
    def test_estimate_plan_event_and_filament_line(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"PAI_SLICER": "off"}):
            ctx = _ctx(Path(tmp))
            result = asyncio.run(pp.print_prep(ctx, {}))
            self.assertTrue(result["ok"], result.get("error"))
            self.assertEqual(result["source"], "estimate")
            events = [e for e in ctx.bus.events if e["type"] == "print"]
            self.assertEqual(len(events), 1)
            plan = events[0]
            self.assertEqual([row["id"] for row in plan["parts"]], ["base", "arm"])
            self.assertTrue(all(row["gcode_url"] == "" for row in plan["parts"]))
            self.assertEqual(plan["totals"]["parts"], 3)
            arm = plan["parts"][1]
            self.assertIn("thin_wall", [w["kind"] for w in arm["warnings"]])
            self.assertEqual(plan["totals"]["filament_g"], round(plan["parts"][0]["filament_g"] + 2 * arm["filament_g"], 1))
            self.assertIn("estimate", result["detail"])
            bom = [e for e in ctx.bus.events if e["type"] == "bom"][-1]
            filament = [item for item in bom["items"] if item.get("category") == "filament"]
            self.assertEqual(len(filament), 1)
            self.assertEqual(bom["total_eur"], 3.1)
            # A second plan replaces the line instead of adding one.
            asyncio.run(pp.print_prep(ctx, {"orientation": "upright"}))
            self.assertEqual(sum(1 for item in ctx.state.bom["items"] if item.get("category") == "filament"), 1)

    def test_no_printed_part_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = Ctx(EventBus(), BuildState(session_id="x", directory=Path(tmp)), auto_steps=False)
            ctx.state.stl_path = None
            self.assertFalse(asyncio.run(pp.print_prep(ctx, {}))["ok"])

    def test_slicer_off_and_override(self):
        with mock.patch.dict(os.environ, {"PAI_SLICER": "off"}):
            self.assertIsNone(pp.find_slicer())


if __name__ == "__main__":
    unittest.main()
