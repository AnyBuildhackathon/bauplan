"""Export: the CSV, the order by shop, and the ZIP with the CAD files, guide, firmware and README."""

import asyncio
import csv
import io
import shutil
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.export import bom_csv, build_guide_md, bundle, order
from pai_agent.paths import SESSIONS_DIR
from pai_agent.state import BuildState
from pai_agent.tools.jamie import init_timeline

BOM = {
    "items": [
        {"name": "Motor 1103", "qty": 4, "unit_price_eur": 7.5, "weight_g": 3.6, "shop": "Shop A", "url": "https://a.example/m", "price_source": "live", "availability": "in_stock"},
        {"name": "Bolts", "qty": 10, "unit_price_eur": 0.05, "weight_g": 0.1, "shop": "Shop A", "url": "https://a.example/b"},
        {"name": "Feet", "qty": 1, "unit_price_eur": 3.2, "weight_g": 2, "shop": "Shop B", "url": "https://b.example/f", "price_source": "estimated"},
        {"name": "Base plate, printed PETG", "qty": 1, "unit_price_eur": 1.13, "weight_g": 45.2, "shop": "printed", "url": "/files/s/part-base.stl", "category": "base"},
    ],
    "total_eur": 34.83,
    "stl_path": "",
}
GUIDE = {
    "type": "build_guide",
    "version": 1,
    "total_minutes": 15,
    "steps": [
        {"n": 1, "title": "Mount the motors", "instructions": "Four M1.4 bolts each.", "parts": ["frame"], "tools": ["1.5 mm hex"], "minutes": 10, "items": ["Motor 1103"]},
        {"n": 2, "title": "Props on", "instructions": "Check the direction.", "parts": ["frame"], "tools": [], "minutes": 5, "items": []},
    ],
}


def _stl_ok(data: bytes) -> bool:
    """A binary STL is 84 header bytes plus 50 per triangle; an ASCII one starts with solid and has facets."""

    if len(data) >= 84 and 84 + 50 * struct.unpack("<I", data[80:84])[0] == len(data):
        return True
    return data.lstrip().startswith(b"solid") and b"facet normal" in data


def _state() -> BuildState:
    return BuildState(session_id="test", directory=Path(tempfile.mkdtemp()))


class ExportTest(unittest.TestCase):
    def test_csv_has_a_bom_line_totals_and_a_total_row(self):
        text = bom_csv(BOM)
        self.assertTrue(text.startswith("﻿"))
        rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
        self.assertEqual(rows[0], ["name", "qty", "unit_price_eur", "line_total_eur", "weight_g", "shop", "url", "price_source", "availability", "checked_at"])
        self.assertEqual(rows[1][:4], ["Motor 1103", "4", "7.50", "30.00"])
        self.assertEqual(rows[1][8], "in_stock")
        self.assertEqual(rows[2][7], "catalog")
        self.assertEqual(rows[-1][0], "Total")
        self.assertEqual(rows[-1][3], "34.83")

    def test_order_groups_by_shop_and_adds_up(self):
        state = _state()
        state.bom = BOM
        state.built = {"base": {"material": "PETG"}}
        plan = order(state)
        self.assertEqual([g["shop"] for g in plan["shops"]], ["Shop A", "Shop B"])
        self.assertEqual(plan["shops"][0]["total_eur"], 30.5)
        self.assertTrue(plan["shops"][0]["live"])
        self.assertFalse(plan["shops"][1]["live"])
        self.assertEqual(plan["print"]["items"], [{"name": "Base plate, printed PETG", "qty": 1, "material": "PETG", "mass_g": 45.2}])
        self.assertEqual(plan["print"]["filament_g"], 45.2)
        total = sum(g["total_eur"] for g in plan["shops"]) + plan["print"]["cost_eur"]
        self.assertAlmostEqual(total, BOM["total_eur"], delta=0.01)

    def test_guide_markdown_lists_every_step(self):
        text = build_guide_md(GUIDE, "drone")
        self.assertIn("# drone: build guide", text)
        self.assertIn("## Step 1: Mount the motors", text)
        self.assertIn("Tools: 1.5 mm hex", text)
        self.assertIn("## Step 2: Props on", text)

    def test_bundle_holds_cad_scripts_guide_firmware_render_and_readme(self):
        state = _state()
        state.bom = BOM
        state.requirements = [{"id": "mass", "text": "Under 150 g", "_met": True, "_detail": "48 g"}]
        state.metrics = {"weight_g": 48.3}
        d = state.directory
        (d / "frame.stl").write_bytes(b"solid x\nfacet normal 0 0 1\nendsolid x\n")
        (d / "frame.step").write_text("ISO-10303-21;")
        (d / "part-base.stl").write_bytes(b"solid y\nendsolid y\n")
        (d / "part-base.py").write_text("import FreeCAD")
        (d / "asm-base.stl").write_bytes(b"solid z\nendsolid z\n")
        (d / "frame.glb").write_bytes(b"glb")
        (d / "studio-v1.png").write_bytes(b"png1")
        (d / "studio-v2.png").write_bytes(b"png2")
        (d / "fw.txt").write_text("set p_roll = 40")
        path = bundle(state, [GUIDE, {"type": "firmware", "filename": "fw.txt"}])
        self.assertEqual(path.parent, d)
        archive = zipfile.ZipFile(path)
        names = sorted(n.split("/", 1)[1] for n in archive.namelist())
        self.assertEqual(
            names,
            sorted(["cad/frame.step", "cad/frame.stl", "cad/part-base.stl", "scripts/part-base.py", "bom.csv", "build-guide.md", "firmware/fw.txt", "render.png", "README.md"]),
        )
        folder = path.stem
        self.assertEqual(archive.read(f"{folder}/render.png"), b"png2")
        readme = archive.read(f"{folder}/README.md").decode()
        self.assertIn("- pass: Under 150 g (48 g)", readme)
        self.assertIn("Weight: 48.3 g", readme)
        self.assertIn("PETG: 0.2 mm layers, 25 % infill", readme)
        self.assertIn("## Missing files\n\n- part-base.step", readme)

    def test_bundle_writes_a_simple_guide_without_an_agent_guide(self):
        state = _state()
        state.bom = BOM
        path = bundle(state, [])
        guide = zipfile.ZipFile(path).read(f"{path.stem}/build-guide.md").decode()
        self.assertIn("1. Print 1 × Base plate, printed PETG in PETG (45.2 g)", guide)
        self.assertIn("Fit 4 × Motor 1103", guide)

    def test_bundle_needs_a_bill_of_materials(self):
        with self.assertRaises(ValueError):
            bundle(_state(), [])


class DroneExportTest(unittest.TestCase):
    def test_mock_drone_exports_a_slicer_ready_zip(self):
        # CAD writes under the sessions folder, since the build reports paths relative to the repository.
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(dir=SESSIONS_DIR))
        self.addCleanup(shutil.rmtree, directory, True)
        state = BuildState(session_id=directory.name, directory=directory)
        init_timeline(state)
        ctx = Ctx(EventBus(), state, auto_steps=False)
        from pai_agent.mock_story import run_mock

        asyncio.run(run_mock(ctx))
        path = bundle(state, ctx.bus.events)
        archive = zipfile.ZipFile(path)
        names = [n.split("/", 1)[1] for n in archive.namelist()]
        for expected in ("cad/frame.stl", "cad/frame.step", "bom.csv", "build-guide.md", "README.md", "firmware/anybuild-drone-v1-betaflight.txt"):
            self.assertIn(expected, names)
        self.assertTrue(_stl_ok(archive.read(f"{path.stem}/cad/frame.stl")))
        plan = order(state)
        self.assertAlmostEqual(sum(g["total_eur"] for g in plan["shops"]) + plan["print"]["cost_eur"], state.bom["total_eur"], delta=0.01)


if __name__ == "__main__":
    unittest.main()
