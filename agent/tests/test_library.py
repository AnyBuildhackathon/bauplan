"""Library: every registry reference is a complete, valid build, and promoting one needs PAI_ADMIN.

Run with: cd agent && uv run --with pytest pytest tests/test_library.py
Rebuilding the references through FreeCAD is agent/scripts/smoke_product.py (needs freecadcmd).
"""

from __future__ import annotations

import json

import pytest

from pai_agent.references import REFERENCES_DIR, list_references
from pai_agent.spec import validate_spec
from pai_agent.tools.product import catalog_items

REFERENCES = sorted(path.parent for path in REFERENCES_DIR.glob("*/reference.json"))


def test_library_lists_the_new_reference_builds() -> None:
    rows = {row["id"]: row for row in list_references()}
    for ref_id in ("desk-lamp", "bike-mount", "pet-feeder"):
        assert rows[ref_id]["source"] == "registry"
        assert rows[ref_id]["thumbnail_url"] == "/api/library/" + ref_id + "/thumbnail"


def test_library_lists_the_camera_builds() -> None:
    rows = {row["id"]: row for row in list_references()}
    for ref_id in ("face-tracking-cam", "bird-feeder-cam", "motion-camera-trap"):
        assert rows[ref_id]["source"] == "registry"
        assert rows[ref_id]["thumbnail_url"] == "/api/library/" + ref_id + "/thumbnail"


def test_camera_builds_buy_from_exact_product_pages() -> None:
    """Every part the camera builds add to the catalog links its product page, not a search."""

    catalog = {item["id"]: item for item in catalog_items()}
    for ref_id in ("face-tracking-cam", "bird-feeder-cam", "motion-camera-trap"):
        ref = json.loads((REFERENCES_DIR / ref_id / "reference.json").read_text(encoding="utf-8"))
        for pick in ref["picks"].values():
            item = catalog[pick["select_id"]]
            if item["id"].endswith("-bb") or item["id"].endswith("-u082x"):
                assert item["url"].startswith("https://www.berrybase.de/en/") and "search" not in item["url"]


@pytest.mark.parametrize("folder", REFERENCES, ids=lambda folder: folder.name)
def test_reference_is_complete(folder) -> None:
    ref = json.loads((folder / "reference.json").read_text(encoding="utf-8"))
    assert ref["id"] == folder.name
    spec = validate_spec(ref["spec"])
    catalog = {item["id"] for item in catalog_items()}
    for part in spec["parts"]:
        if part["kind"] == "printed":
            assert (folder / ref["scripts"][part["id"]]["file"]).is_file()
        elif part["kind"] == "bought":
            pick = ref["picks"][part["id"]]
            assert "select_id" in pick or "estimate" in pick
            if "select_id" in pick:
                assert pick["select_id"] in catalog
    assert sum(1 for pick in ref["picks"].values() if "estimate" in pick) <= 1
    assert (folder / "thumbnail.png").is_file()


def test_promoting_a_reference_needs_admin(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from pai_agent.app import app

    monkeypatch.delenv("PAI_ADMIN", raising=False)
    response = TestClient(app).post("/api/library", json={"id": "x", "kind": "reference"})
    assert response.status_code == 403
    response = TestClient(app).post("/api/library", json={"kind": "nonsense"})
    assert response.status_code == 400
