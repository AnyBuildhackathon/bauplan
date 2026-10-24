"""Export: the CSV, the project ZIP with the CAD files and build guide, and the share id."""

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
from pai_agent.export import bom_csv, build_guide_md, project_zip, share, zip_name
from pai_agent.paths import SESSIONS_DIR
from pai_agent.state import BuildState
from pai_agent.tools.jamie import init_timeline

BOM = {
    "items": [
        {"name": "Motor 1103", "qty": 4, "unit_price_eur": 7.5, "weight_g": 3.6, "shop": "Shop A", "url": "https://a.example/m", "price_source": "live"},
        {"name": "Frame", "qty": 1, "unit_price_eur": 12, "weight_g": 9, "shop": "Shop B", "url": "https://b.example/f"},
    ],
    "total_eur": 42,
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


class ExportTest(unittest.TestCase):
    def _state(self) -> BuildState:
        return BuildState(session_id="test", directory=Path(tempfile.mkdtemp()))

    def test_csv_has_line_totals_and_a_total_row(self):
        rows = list(csv.reader(io.StringIO(bom_csv(BOM))))
        self.assertEqual(rows[0][:4], ["name", "qty", "unit_price_eur", "line_eur"])
        self.assertEqual(rows[1][:4], ["Motor 1103", "4", "7.50", "30.00"])
        self.assertEqual(rows[2][6], "catalog")
        self.assertEqual(rows[-1][0], "Total")
        self.assertEqual(rows[-1][3], "42.00")

    def test_guide_markdown_lists_every_step(self):
        text = build_guide_md(GUIDE, "drone")
        self.assertIn("# drone: build guide", text)
        self.assertIn("## Step 1: Mount the motors", text)
        self.assertIn("Tools: 1.5 mm hex", text)
        self.assertIn("## Step 2: Props on", text)

    def test_zip_holds_cad_bom_guide_and_firmware(self):
        state = self._state()
        state.bom = BOM
        (state.directory / "frame.stl").write_bytes(b"solid x\nfacet normal 0 0 1\nendsolid x\n")
        (state.directory / "frame.step").write_text("ISO-10303-21;")
        (state.directory / "frame.glb").write_bytes(b"glb")
        (state.directory / "fw.txt").write_text("set p_roll = 40")
        events = [GUIDE, {"type": "firmware", "filename": "fw.txt"}]
        names = zipfile.ZipFile(io.BytesIO(project_zip(state, events))).namelist()
        folder = zip_name(state).removesuffix(".zip")
        self.assertEqual(
            sorted(names),
            sorted(f"{folder}/{n}" for n in ("cad/frame.step", "cad/frame.stl", "bom.csv", "build-guide.md", "firmware/fw.txt")),
        )

    def test_zip_needs_a_build(self):
        with self.assertRaises(ValueError):
            project_zip(self._state(), [])

    def test_share_points_the_drone_at_its_code_reference(self):
        state = self._state()
        with self.assertRaises(ValueError):
            share(state)
        state.bom = BOM
        self.assertEqual(share(state), {"id": "micro-drone", "saved": False})

    def test_share_needs_a_finished_spec_product(self):
        state = self._state()
        state.product = "generic"
        with self.assertRaises(ValueError):
            share(state)


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
        archive = zipfile.ZipFile(io.BytesIO(project_zip(state, ctx.bus.events)))
        names = archive.namelist()
        stls = [n for n in names if n.endswith(".stl")]
        self.assertTrue(stls, names)
        self.assertTrue(any(n.endswith(".step") for n in names), names)
        self.assertTrue(any(n.endswith("build-guide.md") for n in names), names)
        for name in stls:
            self.assertTrue(_stl_ok(archive.read(name)), name)


if __name__ == "__main__":
    unittest.main()
