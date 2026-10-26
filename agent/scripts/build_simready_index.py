"""Builds agent/data/simready/index.json, the offline catalogue of NVIDIA SimReady objects.

Run once per pinned revision, with network (one to two hours with the default three workers;
Hugging Face allows 3,000 file requests per 5 minutes without a token, HF_TOKEN raises it):

    cd agent && uv run --extra simready python scripts/build_simready_index.py

For every package of nvidia/simready-assets at the pinned revision it reads four small files,
each verified the way `fetch` verifies a package: the packaging file (its license; a package
under any license but CC-BY-4.0 is left out and listed under `excluded`), the bill of materials
(against the packaging file's hash), the root USD's layer metadata (extents, mass, Q-code,
author) and payloads/base.usda (the Wikidata class and the description). Where a part of the
object is rotated, the declared extents are the box around a rotated box and too large; for
those packages the USD files (no textures) are read and the size is measured from the points.

Each package's row is kept under <cache>/<revision>/index-build/, so an interrupted run picks
up where it stopped. --only id,id rebuilds some rows; --limit N stops after N packages.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pai_agent.simready import LICENSE, REPO_ID, REVISION, source_tag
from pai_agent.simready.fetch import (
    BOM,
    PACKAGING,
    ROOTS,
    HubSource,
    SimReadyError,
    _bom_hash,
    _bom_items,
    check_license,
    fetch_file,
    pick_thumbnail,
    revision_dir,
    safe_relative,
    verify,
)
from pai_agent.simready.index import INDEX_PATH

# Bumped when a row gains or changes a field, so the kept rows are read again.
ROW_VERSION = 1
# Each package is read in its own folder here, emptied when a run starts (an interrupted run leaves some).
WORK_DIR = revision_dir() / "index-work"


def package_ids() -> list[str]:
    """Every package folder at the pinned revision (the listing is paged; huggingface_hub follows the pages)."""

    from huggingface_hub import HfApi
    from huggingface_hub.hf_api import RepoFolder

    tree = HfApi().list_repo_tree(REPO_ID, repo_type="dataset", revision=REVISION, recursive=False)
    return sorted(entry.path for entry in tree if isinstance(entry, RepoFolder))


def _words(text: str) -> list[str]:
    """camelCase split into words ('handTool' is 'hand tool'); an acronym ('CT', 'IV') stays as it is."""

    return [w if w.isupper() else w.lower() for w in re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).split()]


def category_label(asset_id: str) -> str:
    text = " ".join(_words(asset_id.split("_")[0]))
    return text[:1].upper() + text[1:]


def title_of(asset_id: str, cls: str) -> str:
    """The Wikidata class ("Frying pan"), else the words of the id without its category and variant."""

    text = cls
    if not text:
        middle = asset_id.split("_")[1:]
        if middle and len(middle[-1]) == 3 and middle[-1][0].isalpha() and middle[-1][1:].isdigit():
            middle = middle[:-1]
        text = " ".join(word for part in middle for word in _words(part)) or asset_id
    return text[:1].upper() + text[1:]


def _layer_info(root_usd: Path) -> dict:
    from pxr import Sdf

    layer = Sdf.Layer.FindOrOpen(str(root_usd))
    meta = dict(layer.customLayerData.get("SimReady_Metadata") or {})
    pseudo = layer.pseudoRoot
    meters = float(pseudo.GetInfo("metersPerUnit") or 1.0) if pseudo.HasInfo("metersPerUnit") else 1.0
    kilograms = float(pseudo.GetInfo("kilogramsPerUnit") or 1.0) if pseudo.HasInfo("kilogramsPerUnit") else 1.0
    extents = meta.get("asset_extents")
    return {
        "size_mm": [round(float(v) * meters * 1000.0, 1) for v in extents] if extents is not None else None,
        "mass_g": round(float(meta["mass"]) * kilograms * 1000.0, 1) if meta.get("mass") is not None else None,
        "qcode": str(meta.get("qcode") or "") or None,
        "author": str(meta.get("author") or ""),
        "bodies": int(meta.get("rigid_body_count") or 1),
    }


def _base_info(base_usda: Path) -> dict:
    """The Wikidata class and description on the default prim, and whether any part below it is rotated."""

    from pxr import Sdf

    layer = Sdf.Layer.FindOrOpen(str(base_usda))
    prim = layer.GetPrimAtPath("/" + layer.defaultPrim) if layer.defaultPrim else None
    info = {"class": None, "doc": "", "rotated": False}
    if prim is None:
        return info
    attributes = prim.attributes
    for name in ("semantics:labels:wikidata_class", "semantic:wikidata_class:params:semanticData"):
        spec = attributes.get(name)
        if spec is not None and spec.default:
            # A token array in the labels schema, a plain string in the older semantics schema.
            value = spec.default
            info["class"] = str(value if isinstance(value, str) else value[0])
            break
    doc = attributes.get("omni:simready:documentation")
    if doc is not None and doc.default:
        info["doc"] = str(doc.default)

    def rotated(spec) -> bool:
        for attribute in spec.attributes:
            name, value = attribute.name, attribute.default
            if value is None:
                continue
            if name.startswith("xformOp:rotate"):
                angles = list(value) if hasattr(value, "__len__") else [value]
                if any(abs(float(a)) % 90.0 > 1e-3 and abs(abs(float(a)) % 90.0 - 90.0) > 1e-3 for a in angles):
                    return True
            elif name.startswith("xformOp:orient") or name.startswith("xformOp:transform"):
                return True
        return any(rotated(child) for child in spec.nameChildren)

    info["rotated"] = rotated(prim)
    return info


def _measured_size(asset_id: str, items: dict, root: str, source, work: Path) -> list[float]:
    """The size measured from the points of every visible mesh, for a package whose declared extents are inflated."""

    from pxr import Usd, UsdGeom
    import numpy as np

    for path, info in items.items():
        if path.endswith((".usd", ".usda", ".usdc")):
            fetch_file(asset_id, path, info["size"], info["sha256"], work / path, source=source)
    stage = Usd.Stage.Open(str(work / root))
    meters = UsdGeom.GetStageMetersPerUnit(stage) or 1.0
    cache = UsdGeom.XformCache()
    low, high = np.full(3, np.inf), np.full(3, -np.inf)
    for prim in stage.Traverse(Usd.TraverseInstanceProxies()):
        if not prim.IsA(UsdGeom.Mesh) or UsdGeom.Imageable(prim).ComputeVisibility() == UsdGeom.Tokens.invisible:
            continue
        if UsdGeom.Imageable(prim).ComputePurpose() not in (UsdGeom.Tokens.default_, UsdGeom.Tokens.render):
            continue
        points = UsdGeom.Mesh(prim).GetPointsAttr().Get()
        if not points:
            continue
        matrix = np.array(cache.GetLocalToWorldTransform(prim), dtype=float)
        world = np.asarray(points, dtype=float) @ matrix[:3, :3] + matrix[3, :3]
        low, high = np.minimum(low, world.min(axis=0)), np.maximum(high, world.max(axis=0))
    if not np.all(np.isfinite(low)):
        raise SimReadyError(f"{asset_id} has no visible mesh to measure.")
    return [round(float(v) * meters * 1000.0, 1) for v in high - low]


def build_row(asset_id: str, source) -> dict:
    work = Path(tempfile.mkdtemp(prefix=f"{asset_id}-", dir=WORK_DIR))
    try:
        source.get(f"{asset_id}/{PACKAGING}", work / PACKAGING)
        packaging = json.loads((work / PACKAGING).read_text(encoding="utf-8"))
        try:
            check_license(packaging, asset_id)
        except SimReadyError:
            return {"id": asset_id, "excluded": str(packaging.get("license") or "no license")}
        source.get(f"{asset_id}/{BOM}", work / BOM)
        verify(work / BOM, None, _bom_hash(packaging, asset_id), f"{asset_id}'s bill of materials")
        items = _bom_items(json.loads((work / BOM).read_text(encoding="utf-8")))
        root = None
        try:
            source.get(f"{asset_id}/{ROOTS}", work / ROOTS)
            entries = json.loads((work / ROOTS).read_text(encoding="utf-8")).get("entries") or []
            root = next((safe_relative(e) for e in entries if safe_relative(e) in items), None)
        except (SimReadyError, OSError, ValueError):
            root = None
        root = root or next(iter(sorted(p for p in items if p.startswith("simready_usd/") and p.count("/") == 1 and p.endswith((".usd", ".usda", ".usdc")))), None)
        if root is None:
            raise SimReadyError(f"{asset_id} has no root USD file.")
        fetch_file(asset_id, root, items[root]["size"], items[root]["sha256"], work / root, source=source)
        row = {"id": asset_id, "category": category_label(asset_id), **_layer_info(work / root)}
        base = "simready_usd/payloads/base.usda"
        semantics = {"class": None, "doc": "", "rotated": False}
        if base in items:
            fetch_file(asset_id, base, items[base]["size"], items[base]["sha256"], work / base, source=source)
            semantics = _base_info(work / base)
        if semantics["rotated"] or row["size_mm"] is None:
            row["size_mm"] = _measured_size(asset_id, items, root, source, work)
            row["size_measured"] = True
        cls, doc = (semantics["class"] or "").strip(), (semantics["doc"] or "").strip()
        thumb = pick_thumbnail(items, root)
        row.update(
            {
                "class": cls or None,
                "doc": doc,
                "root": root,
                "thumb": [thumb, items[thumb]["size"], items[thumb]["sha256"]] if thumb else None,
                "download_mb": round(sum(i["size"] for p, i in items.items() if not p.startswith("simready_usd/source_assets/") and "/.thumbs/" not in p) / 1e6, 1),
            }
        )
        return row
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=3, help="packages read at once (default 3; each parses USD on a CPU)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", default="", help="comma-separated package ids to read again")
    parser.add_argument("--out", type=Path, default=INDEX_PATH)
    args = parser.parse_args()

    rows_dir = revision_dir() / "index-build"
    rows_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True)
    ids = package_ids()
    print(f"{len(ids)} packages at {source_tag()}", flush=True)
    redo = {i for i in args.only.split(",") if i}
    todo = []
    for asset_id in ids[: args.limit or None]:
        kept = rows_dir / f"{asset_id}.json"
        if asset_id in redo or not kept.is_file():
            todo.append(asset_id)
            continue
        try:
            if json.loads(kept.read_text(encoding="utf-8")).get("_version") != ROW_VERSION:
                todo.append(asset_id)
        except (OSError, ValueError):
            todo.append(asset_id)
    print(f"{len(todo)} to read, {len(ids[: args.limit or None]) - len(todo)} kept from an earlier run", flush=True)
    source = HubSource()
    started, failed = time.time(), {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(build_row, asset_id, source): asset_id for asset_id in todo}
        for done, future in enumerate(as_completed(futures), start=1):
            asset_id = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                failed[asset_id] = f"{type(exc).__name__}: {exc}"[:300]
                print(f"  failed {asset_id}: {failed[asset_id]}", flush=True)
                continue
            (rows_dir / f"{asset_id}.json").write_text(json.dumps({**row, "_version": ROW_VERSION}), encoding="utf-8")
            if done % 50 == 0 or done == len(todo):
                print(f"  {done}/{len(todo)} in {time.time() - started:.0f} s", flush=True)

    objects, excluded, authors = [], [], set()
    for asset_id in ids[: args.limit or None]:
        try:
            row = json.loads((rows_dir / f"{asset_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        row.pop("_version", None)
        if "excluded" in row:
            excluded.append({"id": asset_id, "license": row["excluded"]})
        else:
            authors.add(row.get("author") or "")
            # The root USD is found again from the package, the author is the same for all: neither repeats per row.
            objects.append(
                {
                    **{k: v for k, v in row.items() if k not in ("root", "author")},
                    "class": (row.get("class") or "").strip() or None,
                    "doc": (row.get("doc") or "").strip(),
                    "category": category_label(asset_id),
                    "title": title_of(asset_id, (row.get("class") or "").strip()),
                }
            )
    header = {
        "dataset": REPO_ID,
        "revision": REVISION,
        "license": LICENSE,
        "author": ", ".join(sorted(a for a in authors if a)),
        "built": time.strftime("%Y-%m-%d"),
        "count": len(objects),
        "excluded": excluded,
        "failed": [{"id": k, "error": v} for k, v in sorted(failed.items())],
        "fields": "id, title, category, class (Wikidata), qcode, doc (SimReady description), size_mm [x, y, z] (size_measured: from the points, the declared extents were inflated by a rotated part), mass_g (SimReady estimate), bodies (rigid bodies), thumb [path, bytes, sha256], download_mb (what fetch() downloads)",
    }
    lines = ["{"]
    for key, value in header.items():
        lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)},")
    lines.append('  "objects": [')
    lines.append(",\n".join("    " + json.dumps(row, ensure_ascii=False, sort_keys=True) for row in objects))
    lines.append("  ]")
    lines.append("}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    measured = sum(1 for row in objects if row.get("size_measured"))
    print(f"wrote {args.out}: {len(objects)} objects, {measured} measured from points, {len(excluded)} excluded, {len(failed)} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
