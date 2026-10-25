"""The library that learns: every part validated during a build, kept for the next build.

A part found on the web (`web_parts`) or at a distributor (`distributors`) that passes validation
is written to `agent/data/learned/parts.json` (or `PAI_LEARNED_PARTS`) with its sources, the
date they were checked and the confidence of each number. `parts_search` and `part_pick` list
these parts next to the curated catalogs, and a web search for a need already answered, or for
a part the library already holds with every field the build needs, returns it at once instead of
searching again.

The same product found twice (same manufacturer and part number) is one entry: the better
sourced answer wins, and the sources, needs and use counts of both are kept. Parts with estimated
numbers are kept too, labelled; a build that is not in exploration mode never sees them.
`agent/scripts/learned_parts.py` lists, shows and prunes the library. The file is local
(gitignored): it is what this machine has learned, not a curated catalog.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import date
from pathlib import Path

from pai_agent.paths import DATA_DIR, RUNS_DIR

log = logging.getLogger(__name__)

DEFAULT_PATH = DATA_DIR / "learned" / "parts.json"
# The short cache web finds were kept in before the library existed; imported once.
LEGACY_CACHE = RUNS_DIR / "cache" / "web_parts.json"
RANK = {"sourced": 2, "derived": 1, "estimated": 0}

_STATE: dict = {}


def path() -> Path:
    override = os.environ.get("PAI_LEARNED_PARTS", "").strip()
    return Path(override) if override else DEFAULT_PATH


def norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


_MAKER_WORDS = {"inc", "ltd", "llc", "gmbh", "co", "corp", "corporation", "company", "technology", "technologies", "electronics", "industries", "the"}


def maker_token(text) -> str:
    """The distinctive part of a manufacturer's name: "Arducam Technology Co., Ltd." is "arducam"."""

    words = [w for w in re.findall(r"[a-z0-9]+", str(text or "").lower()) if w not in _MAKER_WORDS]
    return "".join(words[:2]) if words else norm(text)


def same_maker(a, b) -> bool:
    x, y = maker_token(a), maker_token(b)
    return bool(x and y) and (x == y or x.startswith(y) or y.startswith(x))


def names_mpn(named, mpn) -> bool:
    """Whether what a page names (its model or part number, maybe with more words) is this part number."""

    target = norm(mpn)
    return bool(target) and target in norm(named)


def key(part: dict) -> str:
    """Manufacturer and part number when the part has them, else its id."""

    if part.get("mpn"):
        return norm(part.get("manufacturer")) + "|" + norm(part["mpn"])
    return "id|" + str(part.get("id"))


def _load() -> dict:
    target = path()
    if _STATE.get("path") == target:
        return _STATE["data"]
    data = {"parts": [], "needs": {}}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data["parts"] = [p for p in loaded.get("parts", []) if isinstance(p, dict) and p.get("id")]
            data["needs"] = {k: v for k, v in (loaded.get("needs") or {}).items() if isinstance(v, str)}
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        log.warning("learned parts not read from %s: %s", target, exc)
    _STATE.update({"path": target, "data": data})
    if target == DEFAULT_PATH and not data["parts"] and LEGACY_CACHE.is_file():
        try:
            legacy = json.loads(LEGACY_CACHE.read_text(encoding="utf-8"))
            for part in legacy.get("parts", []):
                if isinstance(part, dict) and part.get("id"):
                    _merge_in(data, part)
            if data["parts"]:
                _save()
        except (OSError, ValueError):
            pass
    return data


def _save() -> None:
    data = _STATE.get("data")
    target = _STATE.get("path")
    if data is None or target is None:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=target.parent, prefix=".parts.", suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=1, ensure_ascii=False)
        os.replace(temp, target)
    except OSError as exc:
        log.warning("learned parts not written to %s: %s", target, exc)


def _score(part: dict) -> tuple:
    return (RANK.get(part.get("confidence") or "sourced", 2), len(part.get("fields") or {}), str(part.get("checked") or ""))


def merge(old: dict, new: dict) -> dict:
    """One entry from two finds of the same product: the better sourced one, with what both know."""

    base, other = (dict(new), old) if _score(new) >= _score(old) else (dict(old), new)
    fields = dict(base.get("fields") or {})
    for name, meta in (other.get("fields") or {}).items():
        # A simple number the better answer lacks is taken over with its own source.
        if name not in fields and name in other and name not in base and not isinstance(other[name], (dict, list)):
            base[name] = other[name]
            fields[name] = meta
    if fields:
        base["fields"] = fields
    sources = []
    for source in list(base.get("sources") or []) + list(other.get("sources") or []):
        if isinstance(source, dict) and source.get("url") and source["url"] not in {s["url"] for s in sources}:
            sources.append(source)
    if sources:
        base["sources"] = sources
    base["id"] = old["id"]
    base["used"] = int(old.get("used") or 0) + int(new.get("used") or 0)
    base["learned"] = min(str(old.get("learned") or base.get("checked") or ""), str(new.get("learned") or base.get("checked") or "")) or date.today().isoformat()
    return base


def _merge_in(data: dict, part: dict) -> dict:
    part = {**part, "learned": part.get("learned") or date.today().isoformat()}
    wanted = key(part)
    for index, existing in enumerate(data["parts"]):
        if key(existing) == wanted or existing["id"] == part["id"]:
            data["parts"][index] = merge(existing, part)
            return data["parts"][index]
    data["parts"].append(part)
    return part


def add(part: dict) -> dict:
    """Keeps a validated part; the same product found before is merged into one entry. Returns the entry."""

    stored = _merge_in(_load(), part)
    _save()
    return dict(stored)


def usable(part: dict, allow_estimated: bool) -> bool:
    return allow_estimated or part.get("confidence") != "estimated"


def all_parts(category: str | None = None, allow_estimated: bool = True) -> list[dict]:
    return [dict(p) for p in _load()["parts"] if (category is None or p.get("category") == category) and usable(p, allow_estimated)]


def get(part_id: str) -> dict | None:
    return next((dict(p) for p in _load()["parts"] if p["id"] == part_id), None)


def has_fields(part: dict, required) -> bool:
    known = set(part.get("fields") or {}) | set(part)
    return all(name in known for name in required)


def _need_key(category: str, need: str) -> str:
    return category + "|" + " ".join(need.lower().split())


def remember_need(category: str, need: str, part_id: str) -> None:
    _load()["needs"][_need_key(category, need)] = part_id
    _save()


def for_need(category: str, need: str, required=(), allow_estimated: bool = False) -> dict | None:
    """The part an earlier build found for this exact need, if it still covers the fields asked for."""

    part_id = _load()["needs"].get(_need_key(category, need))
    part = get(part_id) if part_id else None
    if part and usable(part, allow_estimated) and has_fields(part, required):
        return part
    return None


def match(category: str, query: str, required=(), allow_estimated: bool = False) -> dict | None:
    """A learned part whose part number, or every word of the query, matches, with the fields asked for."""

    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 3 and w not in category]
    if not words:
        return None
    best = None
    for part in all_parts(category, allow_estimated):
        if not has_fields(part, required):
            continue
        haystack = " ".join([str(part.get(k) or "") for k in ("name", "manufacturer", "mpn", "id")] + list(part.get("aliases") or [])).lower()
        by_mpn = bool(part.get("mpn")) and norm(part["mpn"]) in norm(query)
        if by_mpn or all(w in haystack for w in words):
            if best is None or _score(part) > _score(best):
                best = part
    return best


def mark_used(part_id: str) -> None:
    for part in _load()["parts"]:
        if part["id"] == part_id:
            part["used"] = int(part.get("used") or 0) + 1
            part["last_used"] = date.today().isoformat()
            _save()
            return


def remove(part_id: str) -> bool:
    data = _load()
    before = len(data["parts"])
    data["parts"] = [p for p in data["parts"] if p["id"] != part_id]
    data["needs"] = {k: v for k, v in data["needs"].items() if v != part_id}
    if len(data["parts"]) != before:
        _save()
        return True
    return False


def prune(estimated: bool = False, older_than_days: int | None = None, unused: bool = False, today: str | None = None, dry_run: bool = False) -> list[str]:
    """Removes the parts matching every given condition (only lists them with dry_run); returns their ids."""

    if not (estimated or older_than_days is not None or unused):
        return []
    now = date.fromisoformat(today) if today else date.today()
    gone = []
    for part in all_parts():
        if estimated and part.get("confidence") != "estimated":
            continue
        if unused and int(part.get("used") or 0) > 0:
            continue
        if older_than_days is not None:
            try:
                age = (now - date.fromisoformat(str(part.get("checked") or part.get("learned")))).days
            except ValueError:
                age = 10**6
            if age < older_than_days:
                continue
        gone.append(part["id"])
    if not dry_run:
        for part_id in gone:
            remove(part_id)
    return gone


def reset() -> None:
    """Forget the loaded library in this process (tests); the file stays."""

    _STATE.clear()
