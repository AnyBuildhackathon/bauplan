"""3D models of library parts: official manufacturer models where the license allows, else look-alikes.

agent/data/models/manifest.json maps each part id to its GLB (served from web/public/models/parts/),
its kind (official, look-alike from measured numbers, or approximate with the missing numbers
listed), its source, license and bounding box. Rebuild with `python -m pai_agent.part_models.build`.
"""

from __future__ import annotations

import json
from functools import lru_cache

from ..paths import DATA_DIR

MANIFEST_PATH = DATA_DIR / "models" / "manifest.json"


@lru_cache(maxsize=1)
def load_manifest() -> dict:
    """Every part's model entry, keyed by part id (empty when the manifest is missing)."""

    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["parts"]


def model_for(part_id: str) -> dict | None:
    """The manifest entry of one part, or None when it has no model."""

    return load_manifest().get(part_id)
