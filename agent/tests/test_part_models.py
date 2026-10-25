"""Every library part has a 3D model that loads and matches the real part's recorded numbers.

The numbers come from agent/data/models/manifest.json, where each one carries its source. The
checks measure the GLB itself: bounding boxes of named pieces, the motor bolt circle, the propeller
diameter and blade count, board hole patterns, frame motor spacing and bearing bores.
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
