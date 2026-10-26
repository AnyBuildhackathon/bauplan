"""Standard parts: sizes from the tables, holes that fit, the fit check, and the bill of materials.

Run with: cd agent && uv run --with pytest pytest tests/test_fasteners.py
No network and no keys. The FreeCAD tests skip without freecadcmd; the CadQuery fallback runs everywhere.
"""

from __future__ import annotations

import asyncio
import csv
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest

from pai_agent.context import Ctx
from pai_agent.export import bundle
from pai_agent.fasteners import hardware
from pai_agent.fasteners.fasteners import HeatSetInsert, Screw
from pai_agent.freecad_run import find_freecadcmd
from pai_agent.paths import SESSIONS_DIR
from pai_agent.state import BuildState
from pai_agent.tools.registry import call_tool

DATA = hardware.PACKAGE / "data"
needs_freecad = pytest.mark.skipif(find_freecadcmd() is None, reason="freecadcmd is not installed")

PLATE = 'shape = Part.makeBox(20, 20, 5, Vector(-10, -10, 0))\n'
LID_SCREWS = {"name": "Lid screw", "kind": "screw", "standard": "ISO 4762", "size": "M3x8", "at": [[25, 15, 23], [-25, 15, 23], [25, -15, 23], [-25, -15, 23]], "fit": "medium"}
LID_INSERTS = {"name": "Lid insert", "kind": "insert", "size": "M3 short", "at": [[25, 15, 20], [-25, 15, 20], [25, -15, 20], [-25, -15, 20]]}
BASE = """W, D, H = P.get("width_mm", 60.0), P.get("depth_mm", 40.0), P.get("height_mm", 20.0)
wall = 2.0
body = Part.makeBox(W, D, H, Vector(-W / 2, -D / 2, 0)).cut(Part.makeBox(W - 2 * wall, D - 2 * wall, H, Vector(-W / 2 + wall, -D / 2 + wall, wall)))
for x in (-W / 2 + 5, W / 2 - 5):
    for y in (-D / 2 + 5, D / 2 - 5):
        body = body.fuse(Part.makeCylinder(4.0, H - wall, Vector(x, y, wall)))
shape = body
"""
LID = 'shape = Part.makeBox(60, 40, P.get("thickness_mm", 3.0), Vector(-30, -20, 20))\n'
SPEC = {
    "name": "Sensor box",
    "function": "A small box for a sensor board, its lid screwed down at the four corners.",
    "quote": "a small sensor box with a screwed lid, under 30 euros",
    "requirements": [{"text": "Costs under 30 euros", "check": "cost", "max": 30, "unit": "eur", "quote": "under 30 euros"}],
    "parts": [
        {
            "id": "base", "name": "Base", "kind": "printed", "material": "PETG", "size_mm": [60, 40, 20],
            "description": "Open box 60 x 40 x 20 mm with 2 mm walls and a post for an M3 insert in each corner, standing on Z = 0.",
            "params": {"width_mm": 60, "depth_mm": 40, "height_mm": 20}, "fasteners": [LID_INSERTS],
        },
        {
            "id": "lid", "name": "Lid", "kind": "printed", "material": "PETG", "size_mm": [60, 40, 3], "position_mm": [0, 0, 21.5],
            "description": "Flat lid 60 x 40 x 3 mm on top of the base at Z = 20, screwed down at the four corners.",
            "params": {"thickness_mm": 3}, "fasteners": [LID_SCREWS],
        },
    ],
}


def _table(name: str) -> dict[str, dict[str, str]]:
    with open(DATA / name, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    head = [cell.strip() for cell in rows[0]]
    return {row[0].strip(): {key: value.strip() for key, value in zip(head[1:], row[1:])} for row in rows[1:] if row}


def _width(shape, axis: str = "x") -> float:
    box = shape.BoundingBox()
    return {"x": box.xlen, "y": box.ylen, "z": box.zlen}[axis]


def _plate():
    import cadquery as cq

    return cq.Solid.makeBox(20, 20, 5, cq.Vector(-10, -10, 0))


class Bus:
    def __init__(self):
        self.events: list[dict] = []

    async def publish(self, event: dict) -> None:
        self.events.append(event)


@pytest.fixture
def session_dir():
    """A session folder inside the repository, where builds keep their files relative to it, removed afterwards."""

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="test-fasteners-", dir=SESSIONS_DIR))
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


def _ctx(directory: Path) -> Ctx:
    state = BuildState(session_id=directory.name, directory=directory)
    state.requests.append(SPEC["quote"])
    return Ctx(Bus(), state, auto_steps=False)


def _run(ctx: Ctx, name: str, args: dict) -> dict:
    return asyncio.run(call_tool(ctx, name, args))


def test_m3x10_iso_4762_with_a_medium_clearance_hole_is_3_4_mm():
    """The acceptance numbers: ISO 273 medium for M3 is 3.4 mm, in the table, the module and the cutting tool."""

    assert float(_table("clearance_hole_sizes.csv")["M3"]["Normal"]) == 3.4
    screw = Screw("ISO 4762", "M3x10", at=(0, 0, 5))
    assert (screw.clearance("fine"), screw.clearance("medium"), screw.clearance("coarse")) == (3.2, 3.4, 3.6)
    assert _width(screw.clearance_hole("medium")) == pytest.approx(3.4, abs=1e-6)
    items, problems = hardware.normalize([{"kind": "screw", "standard": "ISO 4762", "size": "M3x10", "at": [0, 0, 5], "fit": "medium"}], "Plate")
    assert problems == []
    row = hardware.row_of(hardware.build(items)[0], "x.stl")
    assert (row["designation"], row["hole_d_mm"], row["radial_gap_mm"]) == ("ISO 4762 M3x10", 3.4, 0.2)
    assert (row["standard"], row["size"], row["length_mm"]) == ("ISO 4762", "M3", 10.0)
    assert 1.0 < row["mass_g"] < 1.2


def test_a_short_m3_insert_gets_the_hole_its_table_row_names():
    """ruthex's short M3 insert is M3x4; its hole is the table's drill #21, 0.159 inch."""

    row = _table("heatset_nut_parameters.csv")["M3-0.5-4.0"]
    drill_mm = float(_table("drill_sizes.csv")[row["ruthex:drill"]]["Diameter"]) * 25.4
    assert row["ruthex:drill"] == "#21" and drill_mm == pytest.approx(4.0386)
    items, problems = hardware.normalize([{"kind": "insert", "size": "M3 short", "at": [0, 0, 5]}], "Plate")
    assert problems == []
    assert (items[0]["brand"], items[0]["size"], items[0]["length_mm"]) == ("ruthex", "M3", 4.0)
    made = hardware.build(items)[0]
    assert made.numbers["hole_d"] == pytest.approx(drill_mm)
    assert _width(made.hole) == pytest.approx(drill_mm, abs=1e-6)
    assert made.part_number == row["ruthex:part"]
    assert HeatSetInsert("M3x4", at=(0, 0, 5)).hole_diameter == pytest.approx(drill_mm)


def test_a_screw_and_its_hole_do_not_overlap_and_leave_the_iso_273_gap():
    """The fit check: the screw in its clearance hole fills no material, and its shank is 0.2 mm off the wall."""

    import cadquery as cq

    items, _ = hardware.normalize([{"kind": "screw", "standard": "ISO 4762", "size": "M3x10", "at": [0, 0, 5], "fit": "medium"}], "Plate")
    made = hardware.build(items)
    screw = made[0].shape
    plate = _plate().cut(made[0].hole)
    assert plate.intersect(screw).Volume() < 1e-6
    # Inside the plate only the shank is left, 1.5 mm in radius in a 1.7 mm hole.
    shank = screw.intersect(cq.Solid.makeBox(20, 20, 4, cq.Vector(-10, -10, 0.5)))
    assert plate.distance(shank) == pytest.approx(0.2, abs=1e-6)
    fit, problems = hardware.check_cadquery(made, {"Plate": plate})
    assert problems == [] and fit[0]["overlap_mm3"] == 0.0 and fit[0]["touches"]
    # Without the hole the shank fills 35 mm3 of the plate, and the check says so.
    fit, problems = hardware.check_cadquery(made, {"Plate": _plate()})
    assert fit[0]["overlap_mm3"] == pytest.approx(3.14159 * 1.5**2 * 5, rel=0.01)
    assert "inside 'Plate'" in problems[0]


def test_a_sunk_screw_must_be_free_only_as_deep_as_its_hole():
    """depth_mm counts from at, for the hole and for the space the screw needs: a sunk head sits below at."""

    import cadquery as cq

    # M3x16 sunk flush into a 10 mm plate, its clearance hole 6 mm deep; below that it threads into the plastic.
    items, problems = hardware.normalize([{"kind": "screw", "size": "M3x16", "at": [0, 0, 10], "sunk": True, "depth_mm": 6}], "Plate")
    assert problems == []
    made = hardware.build(items)
    hole, keep = made[0].hole.BoundingBox(), made[0].keep.BoundingBox()
    assert (hole.zmin, keep.zmin) == (pytest.approx(4.0), pytest.approx(4.0))
    plate = cq.Solid.makeBox(20, 20, 10, cq.Vector(-10, -10, 0)).cut(made[0].hole)
    fit, problems = hardware.check_cadquery(made, {"Plate": plate})
    assert problems == [] and fit[0]["overlap_mm3"] == 0.0


def test_normalize_names_every_seat_and_lists_every_problem():
    items, problems = hardware.normalize([LID_SCREWS, {"kind": "nut", "size": "M3", "at": [0, 0, 0], "direction": "+Z", "sunk": True}], "Lid")
    assert problems == []
    assert [item["name"] for item in items] == ["Lid screw 1", "Lid screw 2", "Lid screw 3", "Lid screw 4", "Lid nut 1"]
    assert items[4]["direction"] == [0.0, 0.0, 1.0] and items[4]["hole"] == "trap" and items[4]["sunk"] == 0.0
    assert hardware.normalize(items, "Lid") == (items, [])
    _, problems = hardware.normalize(
        [
            {"kind": "screw", "size": "M3x11", "at": [0, 0, 0]},
            {"kind": "nut", "size": "M3x5", "at": [0, 0, 0]},
            {"kind": "washer", "size": "M3", "at": [0, 0, 0], "sunk": True},
            {"kind": "screw", "standard": "ISO 10642", "size": "M3x10", "at": [0, 0, 0], "hole": "tap"},
            {"kind": "screw", "size": "M3x10"},
            {"size": "M3", "at": [0, 0, 0]},
        ],
        "Part",
    )
    assert len(problems) == 6
    assert problems[0].startswith("fasteners[0]: ISO 4762 M3x11: 11 mm is not a standard length. Standard lengths: 5, 6, 8, 10")
    assert "check_length" not in problems[0]
    assert "countersink" in problems[3] and "at is missing" in problems[4] and "kind must be" in problems[5]


def test_bom_lines_name_standard_size_and_length_and_price_from_the_catalog():
    items, _ = hardware.normalize([LID_SCREWS, {"kind": "washer", "size": "M5", "at": [0, 0, 0]}], "Lid")
    rows = [hardware.price(row) for row in (hardware.row_of(one, "x.stl") for one in hardware.build(items))]
    lines = hardware.bom_lines([({"id": "lid", "qty": 2}, rows)])
    screws, washer = lines
    assert screws["name"] == "ISO 4762 M3x8 socket head cap screw" and screws["qty"] == 8
    assert (screws["role"], screws["standard"], screws["size"], screws["length_mm"], screws["category"]) == ("hardware", "ISO 4762", "M3", 8.0, "hw-iso-4762-m3x8")
    # The catalog's M3 screw set, 1.80 EUR for 20, is the sample price per piece.
    assert (screws["unit_price_eur"], screws["price_source"], screws["pack_qty"], screws["parts"]) == (0.09, "sample", 20, ["lid"])
    assert rows[0]["priced_from"] == "m3-screw-set"
    # No M5 washer in the catalog: estimated from the nearest pack, with a shop search for the line itself.
    assert washer["name"] == "ISO 7089 M5 washer" and washer["length_mm"] is None and washer["qty"] == 2
    assert washer["price_source"] == "estimated" and washer["url"].startswith("https://www.amazon.de/s?k=ISO+7089+M5")


def test_the_gripper_bill_lists_the_standard_parts_of_its_body(tmp_path):
    """A single generated part (the gripper's body) orders its standard parts too, next to its catalog picks."""

    from pai_agent.tools.gripper import CATEGORIES

    items, _ = hardware.normalize([{"kind": "screw", "size": "M2x6", "at": [[0, 0, 5], [10, 0, 5]]}], "Gripper")
    rows = [hardware.price(hardware.row_of(one, "x.stl")) for one in hardware.build(items)]
    state = BuildState(session_id=tmp_path.name, directory=tmp_path)
    state.product = "gripper"
    state.selected = {c: {"name": c, "bom_qty": 1, "unit_price_eur": 1.0, "mass_g": 1.0, "shop": "Shop", "url": "https://shop.example/" + c} for c in CATEGORIES}
    state.part = {"name": "Gripper", "mass_g": 40.0, "material": "PETG", "hardware": rows}
    bom = _run(Ctx(Bus(), state, auto_steps=False), "bom_build", {})
    assert bom["ok"], bom
    lines = [item for item in bom["items"] if item.get("role") == "hardware"]
    assert [(line["name"], line["qty"], line["length_mm"]) for line in lines] == [("ISO 4762 M2x6 socket head cap screw", 2, 6.0)]
    # No M2 screws in the catalog: estimated from the M3 set, with a shop search for the line itself.
    assert lines[0]["price_source"] == "estimated" and bom["total_eur"] == pytest.approx(1.0 + 4 * 1.0 + 2 * lines[0]["unit_price_eur"], abs=0.011)


def test_a_product_with_fasteners_builds_on_the_cadquery_fallback(fallback_apps, session_dir):
    """The whole flow without FreeCAD: the blocks get the holes, the assembly the parts, the bill of materials the lines."""

    ctx = _ctx(session_dir)
    _product_flow(ctx)
    assert all(info["fallback"] for info in ctx.state.built.values())
    # When Mechanic looks at the model, the lid takes its screws along, and standard parts answer to their kind.
    lid = _run(ctx, "cad_view", {"only": ["lid"]})
    assert lid["ok"], lid
    assert [(part["name"], part["kind"]) for part in lid["parts"]] == [("Lid", "printed")] + [("Lid screw " + str(n), "hardware") for n in range(1, 5)]
    standard = _run(ctx, "cad_view", {"only": ["hardware"]})
    assert standard["ok"] and len(standard["parts"]) == 8


@needs_freecad
def test_a_product_with_fasteners_builds_in_freecad(monkeypatch, tmp_path, session_dir):
    monkeypatch.setattr("pai_agent.cache.CACHE_DIR", tmp_path / "cache")
    ctx = _ctx(session_dir)
    _product_flow(ctx)
    base = ctx.state.built["base"]
    assert not base["fallback"]
    # Four insert holes, 4.0386 mm wide and 5 mm deep, came out of the posts.
    assert base["parts"][0]["volume_mm3"] < _volume_without_holes() - 4 * 3.14159 * 2.0193**2 * 4.9


def _volume_without_holes() -> float:
    import math

    outer = 60 * 40 * 20 - 56 * 36 * 18
    return outer + 4 * math.pi * 4.0**2 * 18 - 4 * _post_in_wall()


def _post_in_wall() -> float:
    """The part of each corner post that overlaps the walls, measured once with CadQuery."""

    import cadquery as cq

    post = cq.Solid.makeCylinder(4.0, 18, cq.Vector(25, 15, 2))
    walls = cq.Solid.makeBox(60, 40, 20, cq.Vector(-30, -20, 0)).cut(cq.Solid.makeBox(56, 36, 20, cq.Vector(-28, -18, 2)))
    return float(post.intersect(walls).Volume())


def _product_flow(ctx: Ctx) -> None:
    result = _run(ctx, "product_spec", SPEC)
    assert result["ok"], result
    assert [len(part.get("fasteners", [])) for part in ctx.state.spec["parts"]] == [4, 4]
    for part_id, script in (("base", BASE), ("lid", LID)):
        result = _run(ctx, "cad_part", {"part_id": part_id, "script": script})
        assert result["ok"], result
        assert "hardware_warnings" not in result, result.get("hardware_warnings")
    lid = ctx.state.built["lid"]["hardware"]
    assert [row["name"] for row in lid] == ["Lid screw 1", "Lid screw 2", "Lid screw 3", "Lid screw 4"]
    assert all(row["hole_d_mm"] == 3.4 and row["radial_gap_mm"] == 0.2 and row["touches"] for row in lid)
    assert {row["hole_d_mm"] for row in ctx.state.built["base"]["hardware"]} == {4.0386}
    built = _run(ctx, "assemble", {})
    assert built["ok"] and built["warnings"] == [], built.get("warnings")
    standard = [body for body in built["parts"] if body["kind"] == "hardware"]
    assert len(standard) == 8 and {body["part_id"] for body in standard} == {"hw-iso-4762-m3x8", "hw-heat-set-insert-ruthex-m3x4"}
    # The screws sit on the lid where it ended up in the assembly: their heads on its top at Z = 23.
    assert all(body["bbox_mm"][5] == pytest.approx(26.0, abs=0.05) for body in standard if body["part_id"] == "hw-iso-4762-m3x8")
    hardware_mass = sum(body["mass_g"] for body in standard)
    assert built["product_mass_g"] == pytest.approx(ctx.state.assembly["printed_mass_g"] + hardware_mass, abs=0.11)
    cad = [event for event in ctx.bus.events if event.get("type") == "cad" and event.get("assembly")][-1]
    assert {row["kind"] for row in cad["bodies"]} == {"printed", "hardware"}
    # The explode view takes every standard part out of its hole: the part it sits in and its axis into the material.
    pieces = [row for row in cad["bodies"] if row["kind"] == "hardware"]
    assert {(row["holder"], tuple(row["direction"])) for row in pieces} == {("base", (0.0, 0.0, -1.0)), ("lid", (0.0, 0.0, -1.0))}
    labels = [child["label"] for node in cad["tree"][0]["children"] for child in node["children"]]
    assert labels == ["Heat-set insert ruthex M3x4 ×4 (hardware)", "ISO 4762 M3x8 ×4 (hardware)"]
    # Each such row names the GLB nodes of its pieces, so the Assembly tab can select and hide them.
    rows = {child["id"]: child["nodes"] for node in cad["tree"][0]["children"] for child in node["children"]}
    assert rows == {
        "base/hw-heat-set-insert-ruthex-m3x4": ["Lid insert 1", "Lid insert 2", "Lid insert 3", "Lid insert 4"],
        "lid/hw-iso-4762-m3x8": ["Lid screw 1", "Lid screw 2", "Lid screw 3", "Lid screw 4"],
    }
    assert {name for names in rows.values() for name in names} <= {row["name"] for row in cad["bodies"]}
    part = [event for event in ctx.bus.events if event.get("type") == "cad" and not event.get("assembly") and event["part"]["name"] == "Lid"][-1]
    assert part["tree"][0]["children"][-1]["nodes"] == rows["lid/hw-iso-4762-m3x8"]
    bom = _run(ctx, "bom_build", {})
    assert bom["ok"], bom
    lines = {item["category"]: item for item in bom["items"] if item.get("role") == "hardware"}
    screws, inserts = lines["hw-iso-4762-m3x8"], lines["hw-heat-set-insert-ruthex-m3x4"]
    assert (screws["name"], screws["qty"], screws["standard"], screws["size"], screws["length_mm"]) == ("ISO 4762 M3x8 socket head cap screw", 4, "ISO 4762", "M3", 8.0)
    assert (inserts["name"], inserts["qty"], inserts["brand"], inserts["part_number"], inserts["length_mm"]) == (
        "Heat-set insert ruthex M3x4 (GE-M3Sx40-002)", 4, "ruthex", "GE-M3Sx40-002", 4.0,
    )
    assert (screws["unit_price_eur"], inserts["unit_price_eur"]) == (0.09, 0.15)
    printed = sum(item["unit_price_eur"] * item["qty"] for item in bom["items"] if item["shop"] == "printed")
    assert bom["total_eur"] == pytest.approx(printed + 4 * 0.09 + 4 * 0.15, abs=0.011)
    # The export gives the slicer the printed parts only; the standard parts go along as one STEP per printed part.
    path = bundle(ctx.state, ctx.bus.events)
    archive = zipfile.ZipFile(path)
    files = sorted(name.split("/cad/")[1] for name in archive.namelist() if "/cad/" in name)
    assert [name for name in files if "hardware" in name or hardware.is_mesh(name)] == ["part-base.hardware.step", "part-lid.hardware.step"]
    assert "Missing files" not in archive.read(path.stem + "/README.md").decode()


@needs_freecad
def test_freecad_fails_a_part_whose_screw_heads_sit_in_material(monkeypatch, tmp_path, session_dir):
    """A lid one millimetre too thick buries the screw heads: the build fails with what to change."""

    monkeypatch.setattr("pai_agent.cache.CACHE_DIR", tmp_path / "cache")
    ctx = _ctx(session_dir)
    assert _run(ctx, "product_spec", SPEC)["ok"]
    result = _run(ctx, "cad_part", {"part_id": "lid", "script": LID, "params": {"thickness_mm": 4}})
    assert result["ok"] is False
    # One line for the four screws, what to change, and no traceback: the script ran, its geometry is in the way.
    assert "ISO 4762 M3x8 'Lid screw 1', 'Lid screw 2', 'Lid screw 3', 'Lid screw 4' sit up to " in result["error"]
    assert "mm3 inside 'Part': the head needs a flat face at the seat" in result["error"]
    assert "Traceback" not in result["error"] and "part_harness.py" not in result["error"]


@needs_freecad
def test_the_harness_shows_h_and_reuses_a_cached_build(monkeypatch, tmp_path):
    from pai_agent.cad_script import run_script_cached

    monkeypatch.setattr("pai_agent.cache.CACHE_DIR", tmp_path / "cache")
    items, _ = hardware.normalize([{"name": "Screw", "kind": "screw", "standard": "ISO 4762", "size": "M3x10", "at": [0, 0, 5]}], "Plate")
    # The script reads H: a boss under the screw, as wide as its head plus 2 mm.
    script = PLATE + 'shape = shape.fuse(Part.makeCylinder(H["Screw"]["head_d"] / 2 + 1, 2, Vector(0, 0, -2)))\n'
    first, cached = run_script_cached(script, {}, tmp_path / "a", "part-plate", fasteners=items)
    assert not cached and first.hardware[0]["touches"] and first.hardware_warnings == []
    assert first.volume_mm3 == pytest.approx(20 * 20 * 5 + 3.14159 * 3.84**2 * 2 - 3.14159 * 1.7**2 * 7, rel=0.002)
    again, cached = run_script_cached(script, {}, tmp_path / "b", "part-plate", fasteners=items)
    assert cached and [row["stl"] for row in again.hardware] == ["part-plate.hw0.stl"]
    assert (tmp_path / "b" / "part-plate.hw0.stl").is_file() and (tmp_path / "b" / "part-plate.hardware.step").is_file()
    assert again.hardware[0]["designation"] == "ISO 4762 M3x10"
    # The same part without its screw keeps no file of it from the build before.
    plain, _ = run_script_cached(script.replace('H["Screw"]["head_d"]', "5.68"), {}, tmp_path / "b", "part-plate")
    assert plain.hardware == [] and sorted(p.name for p in (tmp_path / "b").glob("*hw*")) == []
    assert not (tmp_path / "b" / "part-plate.hardware.step").exists()
