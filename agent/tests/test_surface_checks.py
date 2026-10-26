"""Surface checks: overhang, wall thickness and clearance with a value on every spot of a printed part.

The test bracket of the SOMA review (fixtures/bracket, report section 2.12) has three faults built in: a
30 x 30 mm shelf whose 900 mm² underside hangs out at 90 degrees, a 0.8 mm rib and a 6.0 mm pin in a 6.4 mm
hole. The checks find each one with its number at its place, 200,000 samples on one part take well under
30 s, and the result reaches Mechanic, print_prep and the studio's colour map. No network, no key.
"""

from __future__ import annotations

import asyncio
import json
import math
import shutil
import time
from pathlib import Path

import numpy as np
import pytest

from pai_agent import assembly as asm
from pai_agent import surface_checks as sc
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools import print_prep as pp
from pai_agent.tools import surface
from pai_agent.view_render import read_glb, to_millimetres

FIXTURES = Path(__file__).parent / "fixtures" / "bracket"


def _stl(name: str) -> tuple[np.ndarray, np.ndarray]:
    tris = pp.read_stl(FIXTURES / (name + ".stl"))
    return tris.reshape(-1, 3), np.arange(len(tris) * 3).reshape(-1, 3)


def _bodies(up=(0.0, 0.0, 1.0)) -> list[dict]:
    out = []
    for name in ("bracket", "pin"):
        points, faces = _stl(name)
        out.append({"name": name.capitalize(), "points": points, "faces": faces, "analyse": True, "up": list(up)})
    return out


@pytest.fixture(scope="module")
def bracket() -> dict:
    """The bracket and the pin checked once, as every printed part is: 40,000 samples between them."""

    result = sc.check(_bodies())
    return {body["name"]: body for body in result["bodies"]}


def _box(size, center=(0.0, 0.0, 0.0)) -> tuple[np.ndarray, np.ndarray]:
    tris = np.array(asm.box_triangles(list(size), tuple(center), asm.rotation(None)))
    return tris, np.arange(len(tris)).reshape(-1, 3)


# ---------------------------------------------------------------- the test bracket


def test_the_shelf_hangs_over_by_9_cm2_and_another_direction_leaves_almost_none(bracket):
    hang = bracket["Bracket"]["summary"]["overhang"]
    assert hang["critical_mm2"] == pytest.approx(900.0, abs=0.5)
    assert hang["max"] == 90.0 and hang["worst"]["value"] == 90.0
    (spot,) = hang["spots"]
    assert spot["count"] == 1 and spot["area_mm2"] == pytest.approx(900.0, abs=0.5)
    # The shelf's underside: 30 x 30 mm at Z = 41, from x -26 to 4.
    assert spot["size_mm"] == [30.0, 30.0, 0.0] and spot["centers_mm"] == [[-11.0, 0.0, 41.0]]
    assert -26.0 <= hang["worst"]["at_mm"][0] <= 4.0 and hang["worst"]["at_mm"][2] == 41.0
    # Printed with +Y up only the top half of the pin's hole hangs over (a quarter of 2 pi 3.2 x 4 mm).
    assert hang["better"]["axis"] == "+y" and hang["better"]["critical_mm2"] == pytest.approx(math.pi / 2 * 3.2 * 4, rel=0.03)
    # The base plate stands on the bed; the pin's own faces never hang over.
    assert bracket["Pin"]["summary"]["overhang"]["critical_mm2"] == 0.0


def test_the_08_mm_rib_is_two_similar_thin_spots_and_nothing_else_is_thin(bracket):
    wall = bracket["Bracket"]["summary"]["thickness"]
    assert wall["min"] == 0.8 and wall["max"] == 60.0
    assert wall["critical_mm2"] == pytest.approx(600.0, abs=0.5) and wall["unread_mm2"] == 0.0
    (spot,) = wall["spots"]
    assert spot["count"] == 2 and spot["area_mm2"] == pytest.approx(300.0, abs=0.5) and spot["worst"] == 0.8
    assert spot["size_mm"] == [0.0, 30.0, 10.0]
    assert sorted(spot["centers_mm"]) == [[10.0, 0.0, 9.0], [10.8, 0.0, 9.0]]
    assert 10.0 <= wall["worst"]["at_mm"][0] <= 10.8 and 4.0 <= wall["worst"]["at_mm"][2] <= 14.0
    pin = bracket["Pin"]["summary"]["thickness"]
    assert pin["min"] == pytest.approx(6.0, abs=0.01) and pin["critical_mm2"] == 0.0


def test_the_pin_sits_in_its_hole_with_02_mm_all_round(bracket):
    gap = bracket["Bracket"]["summary"]["clearance"]
    assert gap["min"] == pytest.approx(0.2, abs=0.01) and gap["max"] == sc.RANGE_MM
    assert gap["overlap_mm2"] == 0.0
    (spot,) = gap["spots"]
    # The hole's wall, 2 pi 3.2 x 4 mm round the pin at x 20, y 0.
    assert spot["area_mm2"] == pytest.approx(2 * math.pi * 3.2 * 4, rel=0.01)
    assert spot["size_mm"] == [6.4, 6.4, 4.0] and spot["centers_mm"] == [[20.0, 0.0, 2.0]] and spot["with"] == "Pin"
    assert math.dist(gap["worst"]["at_mm"][:2], [20.0, 0.0]) == pytest.approx(3.2, abs=0.05) and gap["worst"]["with"] == "Pin"
    pin = bracket["Pin"]["summary"]["clearance"]
    assert pin["min"] == pytest.approx(0.2, abs=0.01) and pin["overlap_mm2"] == 0.0 and pin["spots"][0]["with"] == "Bracket"
    assert math.dist(pin["worst"]["at_mm"][:2], [20.0, 0.0]) == pytest.approx(3.0, abs=0.05) and 0.0 <= pin["worst"]["at_mm"][2] <= 4.0


def test_200000_samples_on_one_part_take_well_under_30_s():
    bodies = _bodies()
    started, cpu = time.perf_counter(), time.process_time()
    result = sc.check(bodies, samples=400_000)
    seconds, cpu_seconds = time.perf_counter() - started, time.process_time() - cpu
    first = result["bodies"][0]
    assert first["name"] == "Bracket" and len(first["surface"]) == sc.MAX_SAMPLES
    # The busy test machine stretches the wall clock; the work itself is the processor time.
    assert cpu_seconds < 30, (seconds, cpu_seconds)
    assert first["summary"]["thickness"]["critical_mm2"] == pytest.approx(600.0, abs=0.5)
    assert first["summary"]["overhang"]["critical_mm2"] == pytest.approx(900.0, abs=0.5)
    assert first["summary"]["clearance"]["min"] == pytest.approx(0.2, abs=0.01)


# ---------------------------------------------------------------- the pieces


def test_refine_keeps_one_closed_surface_with_its_area_volume_and_budget():
    points, faces = sc.weld(*_stl("bracket"))
    area = sc.surface_area(points, faces)
    refined, cut, spacing = sc.refine(points, faces, 20_000)
    assert len(faces) < len(cut) <= 20_000
    assert sc.surface_area(refined, cut) == pytest.approx(area, rel=1e-9)
    # Every edge still belongs to exactly two triangles: no crack, no T-junction.
    _, of_face = sc._edges(cut, len(refined))
    assert set(np.bincount(of_face.ravel()).tolist()) == {2}

    def volume(p, f):
        return float(np.einsum("ij,ij->", p[f[:, 0]], np.cross(p[f[:, 1]], p[f[:, 2]]))) / 6

    assert volume(refined, cut) == pytest.approx(volume(points, faces), rel=1e-9)
    edges, _ = sc._edges(cut, len(refined))
    assert np.linalg.norm(refined[edges[:, 0]] - refined[edges[:, 1]], axis=1).max() == pytest.approx(spacing)


def test_weld_joins_a_triangle_soup_and_turns_an_inside_out_body():
    tris, _ = _box([10.0, 10.0, 10.0])
    points, faces = sc.weld(tris, np.arange(len(tris)).reshape(-1, 3))
    assert len(points) == 8 and len(faces) == 12
    flipped, faces2 = sc.weld(tris, np.arange(len(tris)).reshape(-1, 3)[:, [0, 2, 1]])
    a, b, c = flipped[faces2[:, 0]], flipped[faces2[:, 1]], flipped[faces2[:, 2]]
    assert float(np.einsum("ij,ij->", a, np.cross(b, c))) > 0


def test_a_45_degree_roof_is_on_the_limit_not_over_it_and_the_bed_is_never_critical():
    # A prism on the bed whose sloped underside leans out at exactly 45 degrees.
    outline = [(0.0, 0.0), (10.0, 0.0), (20.0, 10.0), (0.0, 10.0)]
    front = [(x, 0.0, z) for x, z in outline]
    back = [(x, 10.0, z) for x, z in outline]
    tris = [front[0], front[1], front[2], front[0], front[2], front[3], back[0], back[2], back[1], back[0], back[3], back[2]]
    for i in range(4):
        j = (i + 1) % 4
        tris += [front[i], back[j], front[j], front[i], back[i], back[j]]
    tris = np.array(tris)
    points, faces = sc.weld(tris, np.arange(len(tris)).reshape(-1, 3))
    surf = sc.Surface(points, faces, 0.0)
    values = sc.overhang(points, faces, surf.normals, np.array([0.0, 0.0, 1.0]), 45.0)
    assert values.max() == 45.0 and not sc.critical("overhang", values, 45.0).any()
    assert (values == sc.NONE).sum() == 2  # the two triangles of the bottom face
    # Lying on its side, the 45 degree face counts as the vertical side it then is.
    sideways = sc.overhang(points, faces, surf.normals, np.array([0.0, 1.0, 0.0]), 45.0)
    assert sideways.max() == 0.0


def test_clearance_is_the_gap_zero_where_faces_touch_and_negative_where_parts_overlap():
    def gaps(other_center):
        a, fa = _box([10.0, 10.0, 10.0])
        b, fb = _box([10.0, 10.0, 10.0], other_center)
        result = sc.check([{"name": "A", "points": a, "faces": fa, "analyse": True}, {"name": "B", "points": b, "faces": fb, "analyse": False}], checks=("clearance",), samples=4_000)
        (body,) = result["bodies"]
        return body["summary"]["clearance"], body

    tight, body = gaps((10.3, 0.0, 0.0))
    assert tight["min"] == pytest.approx(0.3, abs=1e-6) and tight["critical_mm2"] == pytest.approx(100.0, abs=0.01)
    assert tight["worst"]["at_mm"][0] == pytest.approx(5.0)
    touch, _ = gaps((10.0, 0.0, 0.0))
    assert touch["min"] == 0.0 and touch["critical_mm2"] == 0.0
    overlap, body = gaps((9.5, 0.0, 0.0))
    assert overlap["min"] == pytest.approx(-0.5, abs=1e-6) and overlap["overlap_mm2"] > 0 and overlap["worst"]["with"] == "B"
    assert sc.critical("clearance", body["values"]["clearance"], 0.4).any()


def _prism_xz(outline, y0: float = 0.0, y1: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    """A closed prism of a convex XZ outline from y0 to y1, welded and wound outward by sc.weld."""

    front = [(x, y0, z) for x, z in outline]
    back = [(x, y1, z) for x, z in outline]
    tris = []
    for i in range(1, len(outline) - 1):
        tris += [front[0], front[i], front[i + 1], back[0], back[i + 1], back[i]]
    for i in range(len(outline)):
        j = (i + 1) % len(outline)
        tris += [front[i], back[j], front[j], front[i], back[i], back[j]]
    tris = np.array(tris)
    return tris, np.arange(len(tris)).reshape(-1, 3)


def _wedge(degrees: float) -> dict:
    """A 40 mm long block with one edge that closes at this angle (its other corners square or blunt), checked for its walls."""

    height = min(10.0, 15.0 * math.tan(math.radians(degrees)))
    run = height / math.tan(math.radians(degrees))
    wedge, faces = _prism_xz([(0.0, 0.0), (20.0, 0.0), (20.0 - run, height), (0.0, height)], 0.0, 40.0)
    (body,) = sc.check([{"name": "Wedge", "points": wedge, "faces": faces, "analyse": True}], checks=("thickness",), samples=40_000)["bodies"]
    return body["summary"]["thickness"]


def test_the_taper_of_a_blunt_edge_is_no_thin_wall_but_a_long_sharp_edge_is():
    # At 60 degrees the walls are under 0.88 mm only in the last half millimetre of the edge, which a slicer rounds off.
    blunt = _wedge(60.0)
    assert blunt["min"] < 0.2 and blunt["critical_mm2"] > 1.0
    assert blunt["finding_mm2"] == 0.0 and all(spot.get("taper") for spot in blunt["spots"])
    assert blunt["worst"]["value"] >= 0.88 and surface.passes({"thickness": blunt})
    # At 10 degrees the last 5 mm are too thin to print: that is a thin wall to fix.
    sharp = _wedge(10.0)
    assert sharp["critical_mm2"] > 300 and sharp["finding_mm2"] == sharp["critical_mm2"] and not surface.passes({"thickness": sharp})


def test_where_two_parts_meet_at_an_angle_the_gap_ramps_and_is_no_tight_fit():
    a, fa = _box([10.0, 10.0, 10.0], (0.0, 5.0, 0.0))
    # A block whose underside rises 5 degrees from the line where it rests on the top of a.
    rise = 10.0 * math.tan(math.radians(5.0))
    b, fb = _prism_xz([(-5.0, 5.0), (5.0, 5.0 + rise), (5.0, 15.0), (-5.0, 15.0)], 0.0, 10.0)
    result = sc.check([{"name": "A", "points": a, "faces": fa, "analyse": True}, {"name": "B", "points": b, "faces": fb, "analyse": False}], checks=("clearance",), samples=20_000)
    gap = result["bodies"][0]["summary"]["clearance"]
    # Under 0.4 mm from the contact line out to 0.4 / tan 5° = 4.6 mm, all of it the wedge of the contact.
    assert gap["critical_mm2"] == pytest.approx(10 * 0.4 / math.tan(math.radians(5.0)), rel=0.15)
    assert gap["finding_mm2"] == 0.0 and gap["spots"][0]["contact"] is True and surface.passes({"clearance": gap})


def test_the_glb_carries_each_triangles_values_in_the_source_nodes_own_frame(tmp_path):
    a, fa = _box([10.0, 10.0, 2.0])
    result = sc.check([{"name": "Plate", "points": a, "faces": fa, "analyse": True, "part_id": "plate"}], samples=500)
    body = result["bodies"][0]
    # A drone GLB: metres, Y up, the node 0.1 m along X.
    world = np.eye(4)
    world[0, 3] = 0.1
    body["local"] = np.linalg.inv(world) @ sc._from_millimetres("gltf")
    body["mm_per_unit"] = 1000.0
    sc.write_glb(tmp_path / "a.glb", result["bodies"], result["limits"])
    document, blob = read_glb(tmp_path / "a.glb")
    (node,) = document["nodes"]
    assert node["name"] == "Plate" and node["extras"]["part_id"] == "plate" and node["extras"]["mm_per_unit"] == 1000.0
    # The way back for a picked point: node frame to the build's mm.
    assert np.allclose(np.array(node["extras"]["to_mm"]).reshape(4, 4) @ body["local"], np.eye(4), atol=1e-9)
    attributes = document["meshes"][0]["primitives"][0]["attributes"]
    assert sorted(attributes) == ["POSITION", "_CLEARANCE", "_OVERHANG", "_THICKNESS"]
    count = 3 * len(body["surface"])
    assert all(document["accessors"][index]["count"] == count for index in attributes.values())
    positions = np.frombuffer(blob, dtype="<f4", count=count * 3, offset=document["bufferViews"][attributes["POSITION"]]["byteOffset"]).reshape(-1, 3)
    # Back through the node and into mm, Z up, the corners are the samples'.
    back = to_millimetres(positions.astype(float) + [0.1, 0.0, 0.0], "gltf")
    assert np.allclose(back, body["surface"].points[body["surface"].faces.ravel()], atol=1e-4)
    thickness = np.frombuffer(blob, dtype="<f4", count=count, offset=document["bufferViews"][attributes["_THICKNESS"]]["byteOffset"])
    assert np.allclose(thickness[0::3], body["values"]["thickness"]) and np.allclose(thickness[1::3], thickness[0::3])
    assert document["asset"]["extras"]["checks"]["thickness"] == {"limit": 0.88, "unit": "mm", "critical": "below", "attribute": "_THICKNESS", "unread": -1.0}


# ---------------------------------------------------------------- the tool


def _bench(tmp_path) -> Ctx:
    """The bracket and the pin as two printed parts of a product, assembled like any other."""

    for name in ("bracket", "pin"):
        shutil.copyfile(FIXTURES / (name + ".stl"), tmp_path / ("part-" + name + "-0.stl"))
        shutil.copyfile(FIXTURES / (name + ".stl"), tmp_path / ("part-" + name + ".stl"))
    spec = {
        "id": "test-bracket",
        "name": "Test bracket",
        "function": "Holds a shelf.",
        "requirements": [],
        "assemblies": [],
        "parts": [
            {"id": "bracket", "name": "Bracket", "kind": "printed", "qty": 1, "material": "PETG"},
            {"id": "pin", "name": "Pin", "kind": "printed", "qty": 1, "material": "PETG"},
        ],
    }
    built = {}
    for name in ("bracket", "pin"):
        points = pp.read_stl(FIXTURES / (name + ".stl")).reshape(-1, 3)
        box = [*points.min(axis=0).tolist(), *points.max(axis=0).tolist()]
        built[name] = {"name": name.capitalize(), "bbox_mm": box, "material": "PETG", "params": {}, "parts": [{"name": name.capitalize(), "stl": "part-" + name + "-0.stl", "mass_g": 5.0, "material": "PETG", "reference": False}]}
    state = BuildState(session_id="t", directory=tmp_path, product="generic", spec=spec, built=built, picked={})
    state.assembly = asm.build(spec, built, {}, tmp_path)
    state.assembly_stale = False
    return Ctx(EventBus(), state, auto_steps=False)


@pytest.fixture
def no_cache(monkeypatch, tmp_path):
    monkeypatch.setattr("pai_agent.cache.CACHE_DIR", tmp_path / "cache")


def test_surface_check_reports_numbers_and_places_and_emits_the_colour_map(tmp_path, no_cache):
    ctx = _bench(tmp_path)
    result = asyncio.run(surface.surface_check(ctx, {}))
    assert result["ok"] is True, result
    assert result["result"] == "fail" and result["limits"] == {"overhang_deg": 45.0, "min_wall_mm": 0.88, "min_gap_mm": 0.4}
    assert result["detail"] == (
        "Bracket: 9.0 cm² overhang past 45°; walls under 0.88 mm on 6.0 cm², down to 0.80 mm; gaps under 0.4 mm to Pin on 80 mm², down to 0.20 mm. "
        "Pin: gaps under 0.4 mm to Bracket on 95 mm², down to 0.20 mm"
    )
    parts = {part["part_id"]: part for part in result["parts"]}
    assert parts["bracket"]["pose"] == "as modelled" and parts["bracket"]["overhang"]["better"]["pose"] == "flat"
    assert '"bracket": "flat"' in result["hint"] and "0.88 mm" in result["hint"] and "0.4 mm" in result["hint"]
    (event,) = [e for e in ctx.bus.events if e["type"] == "analysis"]
    assert event["glb_url"] == "/files/t/analysis.glb?build=0-1" and event["source"] == "surface_check"
    assert event["checks"]["thickness"] == {"limit": 0.88, "unit": "mm", "critical": "below", "attribute": "_THICKNESS", "unread": -1.0, "label": "Wall thickness"}
    assert [part["node"] for part in event["parts"]] == ["Bracket", "Pin"]
    document, _ = read_glb(tmp_path / "analysis.glb")
    assert [node["name"] for node in document["nodes"]] == ["Bracket", "Pin"]
    assert json.loads(json.dumps(event)) == event
    assert ctx.state.surface["build"] == 0 and ctx.state.surface["runs"] == 1


def test_a_load_resting_on_a_part_is_no_tight_gap(tmp_path, no_cache):
    ctx = _bench(tmp_path)
    # A phone-sized load 0.2 mm above the shelf, as a load block may well sit.
    ctx.state.spec["parts"].append({"id": "phone", "name": "Phone", "kind": "external", "qty": 1, "mass_g": 180.0, "size_mm": [20.0, 20.0, 8.0], "position_mm": [-11.0, 0.0, 48.2]})
    ctx.state.assembly = asm.build(ctx.state.spec, ctx.state.built, {}, tmp_path)
    result = asyncio.run(surface.surface_check(ctx, {"checks": ["clearance"]}))
    assert "Phone" not in json.dumps(result)
    bracket = next(part for part in result["parts"] if part["part_id"] == "bracket")
    assert bracket["clearance"]["critical_mm2"] == pytest.approx(80.4, abs=1.0)


def test_a_standard_part_in_the_hole_made_for_it_is_no_tight_gap(tmp_path, no_cache):
    # The pin as a standard part of the bracket: its hole is made for it, and the FreeCAD harness checks that fit.
    ctx = _bench(tmp_path)
    spec, built = ctx.state.spec, ctx.state.built
    spec["parts"] = [part for part in spec["parts"] if part["id"] != "pin"]
    built.pop("pin")
    built["bracket"]["hardware"] = [{"key": "dowel-6", "line": "Dowel pin 6 mm", "name": "Dowel pin", "stl": "part-pin-0.stl", "mass_g": 2.0, "com_mm": [20.0, 0.0, 2.0], "color": "#8a8f98", "unit_price_eur": 0.1}]
    ctx.state.assembly = asm.build(spec, built, {}, tmp_path)
    assert [body["kind"] for body in ctx.state.assembly["bodies"]] == ["printed", "hardware"]
    result = asyncio.run(surface.surface_check(ctx, {"checks": ["clearance"]}))
    (part,) = result["parts"]
    assert part["part_id"] == "bracket" and part["clearance"]["critical_mm2"] == 0.0 and result["result"] == "pass"


def test_an_identical_check_comes_from_the_cache_and_limits_and_parts_can_be_chosen(tmp_path, no_cache, monkeypatch):
    ctx = _bench(tmp_path)
    first = asyncio.run(surface.surface_check(ctx, {"part_ids": ["bracket"], "checks": ["thickness"], "min_wall_mm": 0.7}))
    assert first["ok"] is True and [part["part_id"] for part in first["parts"]] == ["bracket"]
    assert first["result"] == "pass" and first["limits"] == {"min_wall_mm": 0.7} and set(first["parts"][0]) >= {"thickness"}
    assert "overhang" not in first["parts"][0]

    def no_second_run(job):
        raise AssertionError("the cache should answer")

    monkeypatch.setattr(surface, "_run", no_second_run)
    again = asyncio.run(surface.surface_check(ctx, {"part_ids": ["bracket"], "checks": ["thickness"], "min_wall_mm": 0.7}))
    assert again["parts"] == first["parts"]
    bad = asyncio.run(surface.surface_check(ctx, {"part_ids": ["shelf"]}))
    assert bad["ok"] is False and "Printed: bracket, pin" in bad["error"]
    assert asyncio.run(surface.surface_check(ctx, {"checks": ["volume"]}))["ok"] is False


def test_a_changed_build_checks_again_with_the_same_arguments_and_another_product_never(tmp_path, no_cache):
    ctx = _bench(tmp_path)
    asyncio.run(surface.surface_check(ctx, {"checks": ["clearance"]}))
    assert asyncio.run(surface.refresh_surface(ctx)) is None  # nothing changed
    ctx.state.cad_builds += 1
    again = asyncio.run(surface.refresh_surface(ctx))
    assert again["ok"] is True and "clearance" in again["parts"][0] and "thickness" not in again["parts"][0]
    events = [e for e in ctx.bus.events if e["type"] == "analysis"]
    assert [e["glb_url"] for e in events] == ["/files/t/analysis.glb?build=0-1", "/files/t/analysis.glb?build=1-2"]
    ctx.state.product, ctx.state.cad_builds = "drone", 5
    assert asyncio.run(surface.refresh_surface(ctx)) is None and ctx.state.surface is None


def test_print_prep_names_the_real_thin_wall_and_a_better_print_direction(tmp_path, no_cache, monkeypatch):
    monkeypatch.setenv("PAI_SLICER", "off")
    ctx = _bench(tmp_path)
    result = asyncio.run(pp.print_prep(ctx, {"orientation": "as_modeled"}))
    assert result["ok"] is True, result
    rows = {row["id"]: row for row in result["parts"]}
    bracket = {w["kind"]: w["text"] for w in rows["bracket"]["warnings"]}
    assert bracket["thin_wall"].startswith("Walls under 0.88 mm on 6.0 cm², down to 0.80 mm at (10.")
    assert bracket["thin_wall"].endswith("two 0.44 mm lines of the 0.4 mm nozzle do not fit")
    assert bracket["overhang"] == "9.0 cm² hangs over more than 45°, up to 90°: needs supports, or print it flat (+Y up): 20 mm² left"
    assert rows["bracket"]["wall_mm"] == 0.8 and rows["bracket"]["better_up"] == "+y"
    assert rows["pin"]["wall_mm"] == pytest.approx(6.0, abs=0.01) and "thin_wall" not in {w["kind"] for w in rows["pin"]["warnings"]}
    (event,) = [e for e in ctx.bus.events if e["type"] == "analysis"]
    assert event["source"] == "print_prep" and {part["pose"] for part in event["parts"]} == {"as_modeled"}
    # Printed flat, the shelf stands on its side: no better direction left to name.
    flat = asyncio.run(pp.print_prep(ctx, {}))
    overhang = next(w["text"] for w in next(r for r in flat["parts"] if r["id"] == "bracket")["warnings"] if w["kind"] == "overhang")
    assert overhang.endswith("needs supports or another orientation") and overhang.startswith("0.2 cm²")
    assert '"bracket": "flat"' not in json.dumps(flat)


def test_print_prep_without_the_check_falls_back_to_the_designed_wall(tmp_path, monkeypatch):
    monkeypatch.setenv("PAI_SLICER", "off")
    ctx = _bench(tmp_path)

    async def broken(*args, **kwargs):
        raise RuntimeError("no VTK here")

    monkeypatch.setattr(surface, "run", broken)
    ctx.state.built["bracket"]["params"] = {"rib_thickness_mm": 0.8}
    result = asyncio.run(pp.print_prep(ctx, {}))
    bracket = next(row for row in result["parts"] if row["id"] == "bracket")
    assert bracket["wall_mm"] is None and bracket["better_up"] is None
    assert {w["kind"]: w["text"] for w in bracket["warnings"]}["thin_wall"] == "Wall 0.80 mm is thinner than 0.88 mm: two 0.44 mm lines of the 0.4 mm nozzle do not fit"
