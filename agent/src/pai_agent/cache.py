"""Reuses FreeCAD and Blender results for identical inputs, so a rebuild or a reloaded reference skips the slow run.

An entry is a folder under agent/runs/cache/<kind>/<key>/ with the output files and meta.json.
The key hashes everything that decides the output: the script or parameters, the input meshes
and the code that builds them, so a changed script or harness never returns a stale file.
PAI_CACHE=0 turns it off.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from pai_agent.paths import RUNS_DIR

CACHE_DIR = RUNS_DIR / "cache"


def enabled() -> bool:
    return os.environ.get("PAI_CACHE", "").strip().lower() not in {"0", "false", "no", "off"}


def digest(path: Path) -> str:
    """Content hash of a file; a missing file hashes to its name, so the key still changes with it."""

    if not path.is_file():
        return "missing:" + path.name
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tool_version(binary: str | None) -> str:
    """Stands in for the FreeCAD or Blender version: an update replaces the binary and changes its mtime."""

    if not binary:
        return "none"
    try:
        return binary + "@" + str(int(Path(binary).resolve().stat().st_mtime))
    except OSError:
        return binary


def key(*parts: object) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def restore(kind: str, entry: str, targets: dict[str, Path]) -> dict | None:
    """Copies a cached entry's files to targets (cached name to destination) and returns its meta, or None on a miss."""

    if not enabled():
        return None
    folder = CACHE_DIR / kind / entry
    meta_path = folder / "meta.json"
    if not meta_path.is_file() or not all((folder / name).is_file() for name in targets):
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for name, target in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(folder / name, target)
    except (OSError, ValueError):
        return None
    return meta


def store(kind: str, entry: str, files: dict[str, Path], meta: dict | None = None) -> None:
    """Saves the files (cached name to source) under the key. A failed write only costs the next run its shortcut."""

    if not enabled():
        return
    folder = CACHE_DIR / kind / entry
    partial = folder.with_name(entry + ".partial-" + str(os.getpid()))
    try:
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True)
        for name, source in files.items():
            shutil.copyfile(source, partial / name)
        (partial / "meta.json").write_text(json.dumps(meta or {}, default=str), encoding="utf-8")
        shutil.rmtree(folder, ignore_errors=True)
        partial.rename(folder)
    except OSError:
        shutil.rmtree(partial, ignore_errors=True)
