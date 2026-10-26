"""The offline catalogue of SimReady objects: search by name, Wikidata class or category without the network.

`agent/data/simready/index.json` lists every package of the pinned revision with what a search
result shows: title, category, Wikidata class and Q-code, size, mass and the thumbnail file with
its size and SHA-256. `agent/scripts/build_simready_index.py` builds it once from the packages'
own metadata (and their geometry where a rotated part makes the declared extents too large).
PAI_SIMREADY_INDEX points at another index file, for the tests.

Search is word based: every query word must match the object's class, title, id, category or
description (a plural matches its singular, a word of three letters or more matches as a
prefix). The class weighs most, and among equally good matches the smaller download comes first,
so "pan" lists the frying pans (2 MB) before the engine oil pans (15 to 96 MB).
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from pai_agent.paths import DATA_DIR
from pai_agent.simready import LICENSE, REVISION, source_tag

INDEX_PATH = DATA_DIR / "simready" / "index.json"

# How much a query word counts when it matches a field; a prefix match counts 60 %.
_WEIGHTS = (("class", 5.0), ("title", 4.0), ("id", 3.0), ("category", 2.0), ("doc", 2.0))
_PREFIX = 0.6
_PHRASE_BONUS = 3.0


def index_path() -> Path:
    raw = os.environ.get("PAI_SIMREADY_INDEX", "").strip()
    return Path(raw).expanduser() if raw else INDEX_PATH


def words(text: str) -> list[str]:
    """Lower-case words with camelCase split ('handTool' is 'hand tool') and plurals made singular."""

    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text or ""))
    return [_singular(word) for word in re.findall(r"[a-z0-9]+", spaced.lower())]


def _singular(word: str) -> str:
    if len(word) <= 3 or word.endswith("ss"):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "xes", "sses", "oes")):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    del mtime
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for row in data.get("objects") or []:
        fields = {
            "class": set(words(row.get("class") or "")),
            "title": set(words(row.get("title") or "")),
            "id": set(words(str(row["id"]).replace("_", " "))),
            "category": set(words(row.get("category") or "")),
            "doc": set(words(row.get("doc") or "")),
        }
        rows.append((row, fields, " ".join(words(row.get("class") or ""))))
    rows.sort(key=lambda entry: entry[0]["id"])
    return {"meta": {k: v for k, v in data.items() if k != "objects"}, "rows": rows, "by_id": {row["id"]: row for row, _, _ in rows}}


def _data() -> dict:
    path = index_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {"meta": {}, "rows": [], "by_id": {}}
    return _load(str(path), mtime)


def revision() -> str:
    return str(_data()["meta"].get("revision") or REVISION)


def count() -> int:
    return len(_data()["rows"])


def get(asset_id: str) -> dict | None:
    return _data()["by_id"].get(str(asset_id))


def search(query: str, limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
    """(rows, total): the best matches for the query, best first; an empty query lists the catalogue by id."""

    rows = _data()["rows"]
    wanted = words(query)
    if not wanted:
        ordered = [row for row, _, _ in rows]
        return ordered[offset:offset + limit], len(ordered)
    phrase = " ".join(wanted)
    scored = []
    for row, fields, class_phrase in rows:
        total = 0.0
        for word in wanted:
            best = 0.0
            for name, weight in _WEIGHTS:
                field = fields[name]
                if word in field:
                    best = max(best, weight)
                elif len(word) >= 3 and any(candidate.startswith(word) for candidate in field):
                    best = max(best, weight * _PREFIX)
            if best == 0.0:
                break
            total += best
        else:
            if class_phrase == phrase:
                total += _PHRASE_BONUS
            scored.append((-total, float(row.get("download_mb") or 0.0), row["id"], row))
    # Among equally good matches the smaller download comes first: it is placed sooner.
    scored.sort(key=lambda item: item[:3])
    return [row for *_, row in scored[offset:offset + limit]], len(scored)


def public(row: dict) -> dict:
    """A catalogue row as the API and the tool show it."""

    return {
        "id": row["id"],
        "title": row.get("title") or row["id"],
        "category": row.get("category") or "",
        "description": row.get("doc") or "",
        "wikidata": {"class": row.get("class") or None, "qcode": row.get("qcode") or None},
        "size_mm": row.get("size_mm"),
        "mass_g": row.get("mass_g"),
        # SimReady computes every mass from the material's density, the volume and a fill ratio.
        "mass_estimated": True,
        "download_mb": row.get("download_mb"),
        "thumbnail_url": f"/api/objects/{row['id']}/thumbnail",
        "license": LICENSE,
        "source": source_tag(revision()),
    }
