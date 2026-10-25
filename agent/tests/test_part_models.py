"""Every library part has a 3D model that loads and matches the real part's recorded numbers.

The numbers come from agent/data/models/manifest.json, where each one carries its source. The
checks measure the GLB itself: bounding boxes of named pieces, the motor bolt circle, the propeller
diameter and blade count, board hole patterns, connector positions, frame motor spacing and bearing bores.
"""

from __future__ import annotations

import json
import math

import pytest

from pai_agent.part_models.glb import read_glb
from pai_agent.paths import DATA_DIR, REPO_ROOT

MODELS = DATA_DIR / "models"
MANIFEST = json.loads((MODELS / "manifest.json").read_text())["parts"]
WEB = REPO_ROOT / "web" / "public"
# The whole set ships with the web app, so it must stay small.
BUDGET_BYTES = 25_000_000


def _catalog_ids() -> set[str]:
    ids = set()
    for path in [DATA_DIR / "parts.json", *sorted((DATA_DIR / "catalogs").glob("*.json"))]:
        if path.exists():
            ids.update(part["id"] for part in json.loads(path.read_text())["parts"])
    return ids


def test_every_library_part_has_a_model():
    missing = sorted(_catalog_ids() - set(MANIFEST))
    assert not missing, f"library parts without a 3D model: {missing}"


@pytest.mark.parametrize("part_id", sorted(MANIFEST))
def test_manifest_entry_says_where_it_comes_from(part_id):
    entry = MANIFEST[part_id]
    assert entry["kind"] in ("official", "look-alike", "approximate")
    assert (WEB / entry["glb"]).exists()
    if entry["kind"] == "official":
        assert entry["license"] and entry["model_url"] and entry["author"]
    if entry["kind"] == "approximate":
        assert entry["missing"], "an approximate model lists the numbers no source gave"
    if entry["kind"] == "look-alike":
        assert not entry["missing"]
    for name, dim in entry["dims"].items():
        assert dim.get("source"), f"{name} has no source"
    if entry.get("step"):
        assert (REPO_ROOT / entry["step"]).exists()


def _pick(nodes: dict, prefixes) -> list[tuple[float, float, float]]:
    if prefixes is None:
        return [p for points in nodes.values() for p in points]
    return [p for name, points in nodes.items() if name.startswith(tuple(prefixes)) for p in points]


def _centres(nodes: dict, prefix: str) -> list[tuple[float, float]]:
    out = []
    for name, points in sorted(nodes.items()):
        if name.startswith(prefix) and points:
            out.append((sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)))
    return out


def _run(check: dict, nodes: dict) -> None:
    kind = check["check"]
    tol = check["tol"] if "tol" in check else 0.3
    if kind == "extent":
        points = _pick(nodes, check["nodes"])
        assert points, f"no pieces named {check['nodes']}"
        for axis, expect in zip(check["axes"], check["expect"]):
            i = "xyz".index(axis)
            size = max(p[i] for p in points) - min(p[i] for p in points)
            assert abs(size - expect) <= tol, f"{axis} extent {size:.2f} mm, expected {expect} mm"
    elif kind == "min_z":
        low = min(p[2] for p in _pick(nodes, check["nodes"]))
        assert abs(low - check["expect"]) <= tol, f"lowest point {low:.2f} mm, expected {check['expect']} mm"
    elif kind == "bolt_circle":
        centres = _centres(nodes, check["nodes"][0])
        assert len(centres) == check["count"], f"{len(centres)} holes, expected {check['count']}"
        cx = sum(c[0] for c in centres) / len(centres)
        cy = sum(c[1] for c in centres) / len(centres)
        for x, y in centres:
            assert abs(2 * math.hypot(x - cx, y - cy) - check["diameter"]) <= tol
    elif kind == "rotor_diameter":
        blades = [name for name in nodes if name.startswith(check["nodes"][0])]
        assert len(blades) == check["count"], f"{len(blades)} blades, expected {check['count']}"
        reach = max(math.hypot(p[0], p[1]) for p in _pick(nodes, check["nodes"]))
        assert abs(2 * reach - check["diameter"]) <= tol, f"rotor {2 * reach:.2f} mm, expected {check['diameter']} mm"
    elif kind == "holes":
        centres = _centres(nodes, check["nodes"][0])
        assert len(centres) == len(check["expect"]), f"{len(centres)} holes, expected {len(check['expect'])}"
        for ex, ey in check["expect"]:
            assert min(math.hypot(x - ex, y - ey) for x, y in centres) <= tol, f"no hole at ({ex}, {ey})"
    elif kind == "motor_spacing":
        centres = _centres(nodes, check["nodes"][0])
        assert len(centres) == 4
        diagonal = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a in centres for b in centres)
        assert abs(diagonal - check["wheelbase"]) <= tol, f"motor diagonal {diagonal:.2f} mm, expected {check['wheelbase']} mm"
    elif kind == "centre":
        points = _pick(nodes, check["nodes"])
        assert points, f"no pieces named {check['nodes']}"
        for i, expect in enumerate(check["expect"]):
            mid = (max(p[i] for p in points) + min(p[i] for p in points)) / 2
            assert abs(mid - expect) <= tol, f"{check['nodes'][0]} centre {'xy'[i]} {mid:.2f} mm, expected {expect} mm"
    elif kind == "bore":
        points = _pick(nodes, check["nodes"])
        cx = (max(p[0] for p in points) + min(p[0] for p in points)) / 2
        cy = (max(p[1] for p in points) + min(p[1] for p in points)) / 2
        bore = 2 * min(math.hypot(p[0] - cx, p[1] - cy) for p in points)
        assert abs(bore - check["diameter"]) <= tol
    else:
        raise AssertionError("unknown check " + kind)


@pytest.mark.parametrize("part_id", sorted(MANIFEST))
def test_model_loads_and_matches_its_numbers(part_id):
    entry = MANIFEST[part_id]
    nodes = read_glb(WEB / entry["glb"])
    points = _pick(nodes, None)
    assert len(points) >= 3
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    for i in range(3):
        assert abs((high[i] - low[i]) - entry["bbox_mm"][i]) <= 0.05 + 0.002 * entry["bbox_mm"][i]
    # Curved bottoms are tessellated, so the lowest vertex may sit a chord's sag above z = 0.
    assert abs(low[2]) <= 0.02 + 0.004 * max(entry["bbox_mm"]), "a part model rests on z = 0"
    assert entry["checks"] or entry["kind"] == "official", "every look-alike is checked against its numbers"
    for check in entry["checks"]:
        _run(check, nodes)


def test_whole_set_stays_small():
    total = sum((WEB / entry["glb"]).stat().st_size for entry in MANIFEST.values())
    assert total < BUDGET_BYTES, f"{total / 1e6:.1f} MB of part models"


def test_official_models_carry_their_licenses():
    text = (MODELS / "official" / "LICENSES.md").read_text()
    for entry in MANIFEST.values():
        if entry["kind"] == "official":
            assert entry["model_url"].split("/-/")[0].split("/tree/")[0] in text


def _library_drone(tmp_path):
    from types import SimpleNamespace

    from pai_agent import drone_assembly, drone_geometry
    from pai_agent.paths import PARTS_PATH

    parts = {p["id"]: p for p in json.loads(PARTS_PATH.read_text())["parts"]}
    pick = {
        "motor": "betafpv-0802-22000kv",
        "propeller": "gemfan-1614-3",
        "battery": "betafpv-lava-1s-300",
        "flight_controller": "betafpv-matrix-1s-5in1-v2",
        "camera": "betafpv-c03",
    }
    state = SimpleNamespace(selected={k: parts[v] for k, v in pick.items()}, cad_params={}, frame_mass_g=None, product="drone")
    params = {"arm_length_mm": 30.0, "thickness_mm": 2.0, "motor_spacing_mm": 6.6}
    drone_assembly.build(tmp_path, params, drone_geometry.geometry(state, params), state.selected)
    return state


def test_a_built_drone_shows_its_parts_own_models(tmp_path):
    from pai_agent.part_models import swap

    state = _library_drone(tmp_path)
    rows = swap.into_drone_glb(tmp_path / "frame.glb", state.selected)
    by_node = {row["node"]: row for row in rows}
    for corner in ("front_left", "front_right", "rear_left", "rear_right"):
        assert by_node["motor_" + corner]["part_id"] == "betafpv-0802-22000kv"
        assert by_node["propeller_" + corner]["model_kind"] == "look-alike"
    assert by_node["battery"]["part_id"] == "betafpv-lava-1s-300"
    assert by_node["flight_controller"]["model_kind"] == "approximate"
    assert by_node["flight_controller"]["model_missing"]
    document, blob = swap._read(tmp_path / "frame.glb")
    node = next(n for n in document["nodes"] if n.get("name") == "motor_front_left")
    assert node["extras"]["part_id"] == "betafpv-0802-22000kv"
    # The motor stands on its pad: its model's bell is the real 10.55 mm across, around the node origin.
    points = [p for prim in document["meshes"][node["mesh"]]["primitives"] for p in swap._accessor(document, blob, prim["attributes"]["POSITION"])]
    radius = max(math.hypot(p[0], p[2]) for p in points if p[1] > 0.004) * 1000
    assert abs(radius - 10.55 / 2) < 0.3


def test_the_cadquery_step_carries_the_models(tmp_path):
    import cadquery as cq

    _library_drone(tmp_path)
    names = [name for _, name, _, _ in cq.Assembly.importStep(str(tmp_path / "drone.step"))]
    assert sum(name.startswith("drone/motor_front_left_") for name in names) > 4


def test_a_products_bought_part_is_its_model_in_its_box(tmp_path):
    from pai_agent import assembly
    from pai_agent.mesh_export import stls_to_glb
    from pai_agent.part_models import swap

    vertices = assembly.box_triangles([22.2, 11.8, 31.0], (50.0, 0.0, 15.5), assembly.rotation(None))
    assembly.write_stl(tmp_path / "servo.stl", vertices)
    stls_to_glb([("Gripper servo", tmp_path / "servo.stl", "#888888")], tmp_path / "a.glb")
    bodies = [{"part_id": "servo", "name": "Gripper servo", "kind": "bought", "stl": "servo.stl", "com_mm": [50.0, 0.0, 15.5]}]
    picked = {"servo": {"id": "servo-sg90", "size_mm": [22.5, 12.2, 27.0]}}
    parts = [{"id": "servo", "size_mm": [22.2, 11.8, 31.0]}]
    rows = swap.into_product_glb(tmp_path / "a.glb", bodies, picked, parts, assembly.rotation)
    assert rows and rows[0]["part_id"] == "servo-sg90"
    # The servo stands upright in its box: its case's 22.2 mm along x, its spline up.
    nodes = read_glb(tmp_path / "a.glb")
    points = nodes["Gripper servo"]
    assert max(p[2] for p in points) - min(p[2] for p in points) > 28.0
    assert min(p[0] for p in points) < 50.0 - 11.0 and max(p[0] for p in points) > 50.0 + 11.0


def test_a_web_part_gets_a_look_alike_from_its_numbers(tmp_path, monkeypatch):
    from pai_agent.part_models import web

    monkeypatch.setattr(web, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(web, "_MEMO", {})
    part = {
        "id": "web-motor-1203",
        "name": "Some 1203 motor",
        "category": "motor",
        "kv": 8000,
        "diameter_mm": 16.0,
        "height_mm": 14.0,
        "shaft_mm": 1.5,
        "mount_diameter_mm": 9.0,
        "source_url": "https://example.com/motor",
        "estimated": [],
    }
    glb, entry = web.web_model(part)
    assert glb.exists() and entry["generator"] == "brushless_motor"
    assert entry["kind"] == "approximate" and "bolts" in entry["missing"]
    nodes = read_glb(glb)
    bell = nodes["bell"]
    assert abs(max(p[0] for p in bell) - min(p[0] for p in bell) - 16.0) < 0.4
