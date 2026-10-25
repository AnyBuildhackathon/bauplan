"""A library part's model as CadQuery solids with their finishes, for STEP assemblies.

Look-alikes are rebuilt from sources.json by their generator (the STEP files are not kept, the
generator is); official models are read from their STEP. Built once per process.
"""

from __future__ import annotations

import json
from functools import lru_cache

from .build import GENERATORS, SOURCES_PATH, _official_step, _value
from .official import official_model


@lru_cache(maxsize=1)
def _sources() -> dict:
    return json.loads(SOURCES_PATH.read_text())["parts"]


@lru_cache(maxsize=64)
def _solids(part_id: str) -> tuple:
    spec = _sources().get(part_id)
    if spec is None:
        return ()
    if spec["type"] == "official":
        model = official_model({"id": part_id, **spec["official"]}, _official_step(spec["official"]))
    else:
        dims = {name: _value(v) for name, v in spec.get("dims", {}).items()}
        model = GENERATORS[spec["type"]]({"id": part_id, **spec.get("style", {}), **spec.get("estimate", {}), **dims})
        model.rest_on_floor()
    return tuple((finish, shape) for _, shape, finish in model.pieces)


def model_solids(entry: dict) -> list:
    """(finish, shape) pairs in the part's own frame (mm, z up), or [] for a part not in the library."""

    return list(_solids(str(entry.get("id"))))
