"""Sketch to build: the photo is checked by its bytes, read into a validated spec, and the phone stand is built and checked from it."""

import asyncio
import base64
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pai_agent.bus import EventBus
from pai_agent.cad_script import PartBuild
from pai_agent.context import Ctx
from pai_agent.paths import SESSIONS_DIR
from pai_agent.state import BuildState
from pai_agent.tools import cad_part as cad_part_module
from pai_agent.spec import validate_spec
from pai_agent.tools import sketch as sketch_module
from pai_agent.tools.sketch import MAX_BYTES, SAMPLE, decode_image, recorded, sketch_to_spec, store_sketch


def _ctx(directory: Path | None = None) -> Ctx:
    state = BuildState(session_id="test", directory=directory or Path(tempfile.mkdtemp()))
    return Ctx(EventBus(), state, auto_steps=False)


def _sketched(directory: Path | None = None) -> Ctx:
    ctx = _ctx(directory)
    store_sketch(ctx.state, SAMPLE.read_bytes())
    return ctx


def _cadquery_build(source, params, out_dir, stem, material="PLA", timeout_s=0, expected_mm=None) -> PartBuild:
    """Stands in for freecadcmd: the same envelopes as the phone stand scripts, built with CadQuery."""

    import cadquery as cq

    from pai_agent.cad_script import density
    from pai_agent.mesh_export import stls_to_glb

    if "depth_mm" in params:
        width, depth, thickness = params["width_mm"], params["depth_mm"], params["thickness_mm"]
        shape = cq.Workplane("XY").box(width, depth, thickness, centered=(True, False, False)).translate((0, -25, 0))
        shape = shape.union(cq.Workplane("XY").box(width, 5, thickness + params["lip_height_mm"], centered=(True, False, False)).translate((0, -25, 0)))
    else:
        width, length, thickness = params["width_mm"], params["support_length_mm"], params["thickness_mm"]
        slab = cq.Workplane("XY").box(width, thickness, length, centered=(True, True, False))
        shape = slab.rotate((0, 0, 0), (1, 0, 0), -(90 - params["angle_deg"])).translate((0, -10, 5))
    solid = shape.val()
    box = solid.BoundingBox()
    bbox = [box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax]
    out_dir.mkdir(parents=True, exist_ok=True)
    stl, step, glb, piece = (out_dir / (stem + ext) for ext in (".stl", ".step", ".glb", "-0.stl"))
    cq.exporters.export(shape, str(stl))
    cq.exporters.export(shape, str(step))
    cq.exporters.export(shape, str(piece))
    stls_to_glb([(stem, piece, None)], glb)
    (out_dir / (stem + ".py")).write_text(source, encoding="utf-8")
    mass = round(solid.Volume() / 1000.0 * density(material), 2)
    row = {"name": stem, "bbox_mm": bbox, "volume_mm3": solid.Volume(), "stl": piece.name, "material": material.upper(), "mass_g": mass, "reference": False}
    return PartBuild(parts=[row], bbox_mm=bbox, volume_mm3=solid.Volume(), mass_g=mass, stl=stl, step=step, glb=glb)


class StoreTest(unittest.TestCase):
    def test_data_url_and_plain_base64_decode(self):
        raw = SAMPLE.read_bytes()
        self.assertEqual(decode_image("data:image/png;base64," + base64.b64encode(raw).decode()), raw)
        self.assertEqual(decode_image(base64.b64encode(raw).decode()), raw)
        with self.assertRaisesRegex(ValueError, "base64"):
            decode_image("not base64!")

    def test_type_comes_from_the_bytes(self):
        state = _ctx().state
        self.assertEqual(store_sketch(state, SAMPLE.read_bytes()), "sketch-1.png")
        self.assertEqual(store_sketch(state, b"\xff\xd8\xff\xe0jpeg"), "sketch-2.jpg")
        self.assertEqual(store_sketch(state, b"RIFF\x00\x00\x00\x00WEBPVP8 "), "sketch-3.webp")
        self.assertTrue((state.directory / "sketch-1.png").is_file())
        with self.assertRaisesRegex(ValueError, "PNG, JPEG"):
            store_sketch(state, b"hello")
        with self.assertRaisesRegex(ValueError, "Please send PNG or JPEG"):
            store_sketch(state, b"\x00\x00\x00\x18ftypheic\x00\x00")
        with self.assertRaisesRegex(ValueError, "8 MB"):
            store_sketch(state, b"\x89PNG\r\n\x1a\n" + b"x" * MAX_BYTES)


class SketchToSpecTest(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.dict(os.environ, {"PAI_FORCE_MOCK": "1"}), mock.patch.object(sketch_module, "MOCK_PAUSE_S", 0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_recorded_reading_validates(self):
        record = recorded()
        self.assertEqual(validate_spec(record["spec"])["id"], "phone-stand")
        for item in record["read"]:
            self.assertEqual(set(item), {"label", "value", "unit", "confidence"})

    def test_without_a_sketch_it_says_what_to_do(self):
        result = asyncio.run(sketch_to_spec(_ctx(), {}))
        self.assertFalse(result["ok"])
        self.assertIn("drop a photo", result["error"])

    def test_recorded_reading_comes_back_as_the_spec(self):
        ctx = _sketched()
        result = asyncio.run(sketch_to_spec(ctx, {"sketch": "sketch-1.png", "note": "for my desk"}))
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["source"], "recorded")
        self.assertEqual(result["spec"]["name"], "Phone stand")
        self.assertEqual(result["spec"]["quote"], "for my desk")
        # It reads; the orchestrator starts the build with product_spec.
        self.assertIsNone(ctx.state.spec)
        events = [e for e in ctx.bus.events if e["type"] == "sketch"]
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual((event["status"], event["id"], event["url"], event["product"]), ("read", "sketch-1", "/files/test/sketch-1.png", "phone-stand"))
        self.assertEqual(event["read"], recorded()["read"])
        self.assertNotIn("base64", str(event))


class SketchBuildTest(unittest.TestCase):
    """The issue's done line: dropping the phone stand sketch produces a built, checked model."""

    def test_sample_sketch_builds_and_checks_the_phone_stand(self):
        from pai_agent.orchestrator import run_sketch

        # Built files are served from the session folder, which lives under the repo.
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix="test-sketch-", dir=SESSIONS_DIR))
        self.addCleanup(shutil.rmtree, directory, True)
        ctx = _sketched(directory)
        with mock.patch.dict(os.environ, {"PAI_FORCE_MOCK": "1", "DEMO_PACE_S": "0"}), mock.patch.object(
            cad_part_module, "run_script", _cadquery_build
        ), mock.patch.object(sketch_module, "MOCK_PAUSE_S", 0):
            asyncio.run(run_sketch(ctx, "sketch-1.png", "for my desk", []))
        state = ctx.state
        self.assertTrue(state.finished)
        self.assertEqual(sorted(state.built), ["back-rest", "base"])
        self.assertEqual(state.built["base"]["params"]["depth_mm"], 110)
        self.assertIn("feet", state.picked)
        for check in ("totals", "tip_over", "deflection"):
            self.assertTrue(any(key.startswith(check) for key in state.checks), (check, sorted(state.checks)))
        self.assertIsNotNone(state.bom)
        types = [e["type"] for e in ctx.bus.events]
        self.assertLess(types.index("sketch"), types.index("cad"))
        self.assertEqual([e["status"] for e in ctx.bus.events if e["type"] == "sketch"], ["read"])
        tools = {e["name"] for e in ctx.bus.events if e["type"] == "tool" and e["status"] == "ok"}
        self.assertTrue({"sketch_to_spec", "cad_part", "assemble", "check_tip_over", "simulate_assembly", "cad_update", "bom_build"} <= tools, tools)


if __name__ == "__main__":
    unittest.main()
