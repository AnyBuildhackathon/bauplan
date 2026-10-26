"""Reference tests for the CAD outputs: every reference part's STEP and STL measure what they must.

Run with: cd agent && uv run --with pytest pytest tests/test_cad_oracle.py
The parts, their formulas and the checks are in tests/cad_oracle (README.md there says how to add a part);
tests/cad_oracle/run.py runs the same suite with a table and records values. No network and no keys. Parts
that need freecadcmd or solidcraft-cli skip without them; the standard parts and the CadQuery fallbacks
run everywhere. The last tests make sure the oracle itself catches what it is there to catch.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest
from cad_oracle import measure, oracle, parts

NAMES = [reference.name for reference in parts.REFERENCES]


@pytest.fixture(scope="session")
def results(request, tmp_path_factory) -> dict[str, oracle.Result]:
    """Builds every reference part this session runs, all at once, the first time a test asks."""

    chosen = [item.callspec.params["name"] for item in request.session.items if getattr(item, "originalname", "") == "test_reference_part"]
    references = [reference for reference in parts.REFERENCES if reference.name in chosen]
    return oracle.run(references, tmp_path_factory.mktemp("cad-oracle"))


@pytest.mark.parametrize("name", NAMES)
def test_reference_part(results, name):
    result = results[name]
    if result.skipped:
        pytest.skip(result.skipped)
    assert result.error is None, result.error
    failed = [row for row in result.rows if not row.ok and not row.known]
    assert not failed, name + ":\n" + "\n".join(oracle.describe(row) for row in failed)


def test_every_reference_part_has_its_values():
    """A part's quantities come from a formula or from recorded.json, and every record belongs to a part."""

    recorded = oracle.load_recorded()
    assert set(recorded) <= set(NAMES), sorted(set(recorded) - set(NAMES))
    assert len(NAMES) == len(set(NAMES)) and 15 <= len(NAMES) <= 25
    for reference in parts.REFERENCES:
        missing = [q for q in ("volume_mm3", "area_mm2", "com_mm", "bbox_mm", "solids") if getattr(reference.expect, q) is None and q not in recorded.get(reference.name, {})]
        assert not missing, reference.name + " has neither a formula nor a record for " + ", ".join(missing)


# --- The oracle catches what it is there to catch -------------------------------------------------------------------


def _box_files(tmp_path: Path, holes: int = 0) -> tuple[Path, Path]:
    import cadquery as cq
    from cadquery import exporters

    box = cq.Workplane("XY").box(30, 20, 10)
    for i in range(holes):
        box = box.cut(cq.Workplane("XY").center(-10 + 10 * i, 0).circle(2).extrude(20, both=True))
    stl, step = tmp_path / "box.stl", tmp_path / "box.step"
    exporters.export(box, str(stl))
    exporters.export(box, str(step))
    return stl, step


def _write(path: Path, triangles) -> Path:
    data = bytearray(b"oracle test".ljust(80, b" ") + struct.pack("<I", len(triangles)))
    for triangle in triangles:
        data += struct.pack("<3f", 0, 0, 0) + struct.pack("<9f", *[v for corner in triangle for v in corner]) + b"\0\0"
    path.write_bytes(bytes(data))
    return path


def test_the_genus_counts_through_holes_and_a_closed_mesh_passes(tmp_path):
    stl, step = _box_files(tmp_path, holes=3)
    mesh = measure.mesh(stl)
    assert mesh.watertight and mesh.genus == 3 and mesh.shells == 1
    assert measure.step(step).solids[0].volume_mm3 == pytest.approx(30 * 20 * 10 - 3 * math.pi * 4 * 10, rel=1e-6)


def test_a_missing_or_flipped_triangle_breaks_watertightness(tmp_path):
    stl, _step = _box_files(tmp_path)
    triangles = measure.read_stl(stl).tolist()
    open_mesh = measure.mesh(_write(tmp_path / "open.stl", triangles[1:]))
    assert open_mesh.open_edges == 3 and not open_mesh.watertight
    flipped = [triangles[0][::-1]] + triangles[1:]
    assert measure.mesh(_write(tmp_path / "flipped.stl", flipped)).flipped_edges == 3
    inside_out = [t[::-1] for t in triangles]
    assert "the triangles face inwards (negative volume)" in measure.mesh(_write(tmp_path / "inside-out.stl", inside_out)).problems


def test_an_stl_in_metres_or_inches_fails_the_unit_check(tmp_path):
    stl, step = _box_files(tmp_path)
    solid = measure.step(step).solids[0]
    triangles = measure.read_stl(stl)
    for scale, name in ((1.0, "mm"), (0.001, "m"), (1 / 25.4, "inch")):
        rows: list[oracle.Row] = []
        oracle.mesh_checks(rows, "", measure.mesh(_write(tmp_path / (name + ".stl"), (triangles * scale).tolist())), solid, [(0.0, 0.1, 0.1)])
        units = next(row for row in rows if row.check == "STL bbox_mm (units)")
        assert units.ok == (name == "mm"), name


def test_a_step_says_its_length_unit():
    millimetre = "#5=(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.));"
    metre = "#5 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT($,.METRE.) );"
    inch = "#7=(CONVERSION_BASED_UNIT('INCH',#6)LENGTH_UNIT()NAMED_UNIT(#4));"
    assert [measure.step_unit_mm(text) for text in (millimetre, metre, inch, "")] == [1.0, 1000.0, 25.4, None]


def test_overlapping_bodies_are_measured_and_touching_ones_are_not(tmp_path):
    import cadquery as cq

    a = cq.Solid.makeBox(10, 10, 10)
    overlapping = cq.Solid.makeBox(10, 10, 10, cq.Vector(7, 0, 0))
    touching = cq.Solid.makeBox(10, 10, 10, cq.Vector(0, 10, 0))
    path = tmp_path / "pair.step"
    cq.Compound.makeCompound([a, overlapping, touching]).exportStep(str(path))
    found = measure.step(path, overlaps=True).overlaps
    assert [(i, j) for i, j, _v in found] == [(0, 1)] and found[0][2] == pytest.approx(300.0, rel=1e-9)


def test_a_known_defect_that_no_longer_fails_fails():
    rows = [oracle.Row("STEP overlap_mm3", True), oracle.Row("STEP volume_mm3", False)]
    marked = oracle._known(rows, {"STEP overlap_mm3": "fixed meanwhile", "STEP volume_mm3": "still wrong"})
    assert [(row.ok, bool(row.known)) for row in marked] == [(False, False), (False, True)]
