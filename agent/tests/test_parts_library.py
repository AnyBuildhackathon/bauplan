"""The parts library: every part carries real specs, the page they come from, and says what is estimated."""

import json
import re

from pai_agent.paths import DATA_DIR, PARTS_PATH
from pai_agent.tools.parts import catalog, library

PROVENANCE = ("provenance", "source_url", "checked", "estimated", "shop", "url", "unit_price_eur", "mass_g")
# What physics, CAD and the missions read, per drone category; the names and units stay the catalog's.
DRONE_FIELDS = {
    "motor": ("thrust_g", "kv", "size", "diameter_mm", "height_mm", "efficiency_g_per_w", "cells_max", "mount_diameter_mm", "shaft_mm"),
    "propeller": ("diameter_mm", "blades"),
    "battery": ("capacity_mah", "voltage_v", "cells", "length_mm", "width_mm", "height_mm"),
    "flight_controller": ("cells_max", "mount_mm"),
    "frame": ("wheelbase_mm", "arm_length_mm"),
}


def _makers() -> list[dict]:
    return json.loads((DATA_DIR / "catalogs" / "makers.json").read_text(encoding="utf-8"))["parts"]


def test_every_drone_part_has_specs_and_provenance():
    for part in catalog()["parts"]:
        for key in PROVENANCE:
            assert key in part, part["id"] + " lacks " + key
        assert part["provenance"] == "curated"
        assert re.match(r"^https?://[^/\s]+\.[a-z]{2,}/", part["source_url"]), part["id"]
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", part["checked"]), part["id"]
        assert isinstance(part["estimated"], list)
        for key in DRONE_FIELDS.get(part["category"], ()):
            assert part.get(key) not in (None, ""), part["id"] + " lacks " + key


def test_estimated_fields_name_real_fields():
    for part in catalog()["parts"] + _makers():
        for field in part["estimated"]:
            head = field.split(".")[0]
            assert head in part, part["id"] + " marks a missing field " + field + " as estimated"


def test_the_library_spans_whoops_to_five_inch():
    parts = catalog()["parts"]
    motors = {p["size"] for p in parts if p["category"] == "motor"}
    assert {"0802", "1102", "1103", "1104", "1506", "2306"} <= motors
    cells = {p["cells"] for p in parts if p["category"] == "battery"}
    assert {1, 2, 3, 4, 6} <= cells
    assert len([p for p in parts if p["category"] == "frame"]) >= 8
    assert len([p for p in parts if p["category"] == "flight_controller"]) >= 5
    assert any(p["category"] == "vtx" for p in parts)


def test_motor_thrust_matches_its_load_table():
    for part in catalog()["parts"]:
        if part["category"] != "motor" or "bench" not in part:
            continue
        bench = part["bench"]
        assert bench["thrust_g"] == part["thrust_g"]
        if "power_w" in bench:
            assert abs(part["efficiency_g_per_w"] - bench["thrust_g"] / bench["power_w"]) < 0.02
        table = bench.get("load_table")
        if table:
            assert table[-1][0] == 100 and table[-1][1] == bench["thrust_g"] and table[-1][2] == bench["power_w"]
            assert [row[1] for row in table] == sorted(row[1] for row in table)


def test_bench_props_are_in_the_library():
    ids = {p["id"] for p in catalog()["parts"]}
    for part in catalog()["parts"]:
        if part["category"] == "motor" and part["id"] != "generic-1103-15000kv":
            assert part["bench_prop_id"] in ids, part["id"]


def test_maker_library_covers_robots_with_real_pages():
    parts = _makers()
    categories = {p["category"] for p in parts}
    assert {"motor", "servo", "driver", "controller", "sensor", "battery", "power", "wheel", "bearing", "hardware"} <= categories
    for part in parts:
        for key in PROVENANCE:
            assert key in part, part["id"] + " lacks " + key
        assert len(part["size_mm"]) == 3
        assert "search" not in part["url"], part["id"] + " links a search page, not a product page"


def test_existing_reference_parts_keep_their_numbers():
    by_id = {p["id"]: p for p in catalog()["parts"]}
    assert by_id["generic-1103-15000kv"]["thrust_g"] == 50
    assert by_id["generic-1103-15000kv"]["efficiency_g_per_w"] == 2.0
    assert by_id["tattu-rline-1s-550"]["mass_g"] == 15
    assert by_id["betafpv-lava-1s-680"]["capacity_mah"] == 680
    assert json.loads(PARTS_PATH.read_text(encoding="utf-8"))["parts"][0]["id"] == "generic-1103-15000kv"


def test_library_includes_web_finds(monkeypatch):
    from pai_agent import web_parts

    find = {"id": "web-test-motor", "name": "Test motor", "category": "motor", "provenance": "web"}
    monkeypatch.setattr(web_parts, "found_parts", lambda category=None: [find] if category in (None, "motor") else [])
    assert any(p["id"] == "web-test-motor" for p in library("motor"))
    assert not any(p["id"] == "web-test-motor" for p in library("battery"))
