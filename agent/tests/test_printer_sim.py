"""The user's 3D printer: FEM against the analytic cantilever, the material choice limited to the printer,
print planning per printer, the settings round trip, and the offline phone stand with a printer set."""

import asyncio
from pathlib import Path

import pytest

from pai_agent import fem, printers, settings
from pai_agent.tools import print_prep as pp


@pytest.fixture(autouse=True)
def _no_printer():
    printers.set_printer(None)
    yield
    printers.set_printer(None)


needs_fem = pytest.mark.skipif(fem.find_tools() is None, reason="gmsh and CalculiX (FreeCAD's FEM tools) are not installed")


@needs_fem
def test_fem_cantilever_matches_beam_theory(tmp_path):
    import cadquery as cq

    step = tmp_path / "beam.step"
    cq.exporters.export(cq.Workplane().box(100, 10, 10, centered=False), str(step))
    props = {"modulus_mpa": 2000.0, "poisson": 0.35, "strength_mpa": 40.0, "z_strength_mpa": 20.0}
    result = fem.analyse(step, None, props, {"face": "x_min"}, [{"name": "tip", "region": {"face": "x_max"}, "force_n": [0, 0, -10]}], [0, 0, 1], tmp_path / "w", 3.0, tmp_path / "beam.glb")
    case = result["cases"][0]
    # delta = F L^3 / (3 E I) = 2.0 mm, sigma = F L c / I = 6.0 MPa at the root.
    assert case["max_deflection_mm"] == pytest.approx(2.0, rel=0.03)
    assert case["max_von_mises_mpa"] == pytest.approx(6.0, rel=0.05)
    assert case["safety_in_plane"] == pytest.approx(40.0 / case["max_von_mises_mpa"], rel=0.01)
    assert (tmp_path / "beam.glb").read_bytes()[:4] == b"glTF"


@needs_fem
def test_fem_judges_tension_across_layers_with_the_interlayer_strength(tmp_path):
    import cadquery as cq

    step = tmp_path / "beam.step"
    cq.exporters.export(cq.Workplane().box(100, 10, 10, centered=False), str(step))
    props = {"modulus_mpa": 2000.0, "poisson": 0.35, "strength_mpa": 40.0, "z_strength_mpa": 10.0}
    # Printed upright along X: the bending stress runs across the layers.
    upright = fem.analyse(step, None, props, {"face": "x_min"}, [{"name": "tip", "region": {"face": "x_max"}, "force_n": [0, 0, -10]}], [1, 0, 0], tmp_path / "w", 3.0)
    case = upright["cases"][0]
    assert case["governs"] == "layers"
    assert case["safety"] < case["safety_in_plane"]


def test_material_choice_only_from_what_the_printer_prints():
    printer = printers.set_printer({"model": "bambu-a1", "filaments": ["PLA", "PETG", "ASA"]})
    # An open printer cannot print ASA, so it is not among the candidates.
    assert printer["printable"] == ["PLA", "PETG"]
    assert printer["not_printable"] == ["ASA"]
    outdoor = printers.choose_material({"outdoor": True})
    assert outdoor["material"] in {"PLA", "PETG"}
    assert outdoor["material"] == "PETG"
    hot = printers.choose_material({"max_temp_c": 60})
    assert hot["material"] == "PETG" and "PLA softens at 55 °C" in hot["reason"]
    too_hot = printers.choose_material({"max_temp_c": 80})
    assert too_hot["ok"] is False

    printers.set_printer({"model": "bambu-p1s", "filaments": ["PLA", "PETG", "ASA"]})
    assert printers.choose_material({"outdoor": True})["material"] == "ASA"
    assert printers.choose_material({"max_temp_c": 80})["material"] == "ASA"


def test_settings_carry_the_printer():
    body = settings.update({"printer": {"model": "prusa-mk4s", "filaments": ["pla", "PETG", "TPU"]}})
    assert body["printer"]["name"] == "Original Prusa MK4S"
    assert body["printer"]["bed_mm"] == [250, 210, 220]
    assert body["printer"]["printable"] == ["PLA", "PETG", "TPU"]
    assert all(p["source_url"].startswith("https://") for p in body["printer_catalog"]["printers"])
    assert "Original Prusa MK4S" in printers.summary()
    with pytest.raises(ValueError):
        settings.update({"printer": {"model": "no-such-printer"}})
    assert settings.update({"printer": None})["printer"] is None


def _mesh(x: float, y: float, z: float, overhang: float = 0.0) -> dict:
    return {"volume_mm3": x * y * z, "area_mm2": 2 * (x * y + y * z + x * z), "size_mm": [x, y, z], "overhang_mm2": overhang, "overhang_max_deg": 0.0}


def test_print_plan_follows_the_printer():
    part = _mesh(200, 40, 10)
    # Without a printer: the generic 220 mm bed, as before.
    assert not [w for w in pp.warnings_for(part, None, "PLA") if w["kind"] == "bed_size"]
    printers.set_printer({"model": "bambu-a1-mini", "filaments": ["PLA"]})
    small = pp.profile()
    assert small["bed_mm"] == [180, 180, 180]
    assert [w for w in pp.warnings_for(part, None, "PLA", small) if w["kind"] == "bed_size"]
    slow = pp.estimate(part, "PLA", small)
    printers.set_printer({"model": "bambu-p1s", "filaments": ["PLA", "ABS"]})
    fast = pp.profile()
    assert not [w for w in pp.warnings_for(part, None, "PLA", fast) if w["kind"] == "bed_size"]
    assert pp.estimate(part, "PLA", fast)["time_min"] < slow["time_min"]
    assert pp.estimate(part, "PLA", fast)["cost_eur"] == pytest.approx(pp.estimate(part, "PLA", fast)["filament_g"] * 0.025, abs=0.01)
    # ABS on an enclosed printer is fine; on an open one it is not printable and warps.
    assert not [w for w in pp.warnings_for(_mesh(60, 40, 10), None, "ABS", fast) if w["kind"] == "material"]
    printers.set_printer({"model": "creality-ender-3-v3", "filaments": ["PLA", "ABS"]})
    open_frame = pp.warnings_for(_mesh(180, 40, 10), None, "ABS", pp.profile())
    assert any(w["kind"] == "material" and "no enclosure" in w["text"] for w in open_frame)
    assert any(w["kind"] == "warp" and w["text"].startswith("High") for w in open_frame)


def test_auto_orientation_picks_the_pose_without_supports(tmp_path):
    from tests.test_print_prep import _box, _write_stl

    # A T standing on its stem hangs its bar out; lying on the bar's top it needs no support.
    stl = _write_stl(tmp_path / "t.stl", _box(10, 10, 40) + _box(60, 10, 5, x0=-25, z0=40))
    raw = pp.read_stl(stl)
    chosen = pp.best_orientation(raw, [256, 256, 256])
    assert pp.analyse(pp.orient(raw, chosen)[0])["overhang_mm2"] <= pp.analyse(pp.orient(raw, "as_modeled")[0])["overhang_mm2"]


@needs_fem
def test_offline_phone_stand_with_a_printer(monkeypatch):
    monkeypatch.setenv("PAI_FORCE_MOCK", "1")
    printers.set_printer({"model": "bambu-p1s", "filaments": ["PLA", "PETG"]})
    from pai_agent.session import Session

    async def run():
        session = Session()
        await session.start("Build a phone stand for my desk, under 150 g.")
        await session.task
        return session

    session = asyncio.run(run())
    events = list(session.bus.events)
    fem_events = [e for e in events if e["type"] == "fem"]
    assert {e["part_id"] for e in fem_events} == {"back-rest", "base"}
    assert all(e["material"] in {"PLA", "PETG"} and e["safety"] > 0 for e in fem_events)
    assert all(Path(session.state.directory, e["glb_url"].split("/")[-1].split("?")[0]).is_file() for e in fem_events)
    plan = [e for e in events if e["type"] == "print"][-1]
    assert plan["printer"] == "Bambu Lab P1S"
    bom = [e for e in events if e["type"] == "bom"][-1]
    printed = [item for item in bom["items"] if item["shop"] == "printed" and item.get("category") != "filament"]
    assert printed and all(item["price_source"] == "printer" and "Bambu Lab P1S" in item["name"] for item in printed)
    strength = [e for e in events if e["type"] == "requirement" and e["id"] == "strength"]
    assert strength and strength[-1]["met"] is not None
