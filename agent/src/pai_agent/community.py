"""The community: projects people published, for others to open and keep working on (remix).

An entry is a folder with entry.json. Seed entries live in the repository under
agent/data/community/<id>/ and rebuild from a library item (their "base"); published entries live
under agent/runs/community/<id>/ (local, not committed) and keep the whole project:

    {"id", "title", "description", "author", "published_at",
     "product": "drone" | "gripper" | "generic", "product_label",
     "base": library id to rebuild from, or null when the folder has its own reference.json,
     "remixed_from": entry id or null,
     "remixes": a seed's starting count (published entries count only their remixes),
     "metrics": {"mass_g", "cost_eur", "parts", "printed", "requirements_passed", "requirements", ...},
     "bom": [{"name", "qty", "unit_price_eur"}], "versions": [...], "files": ["studio-v1.png", "part-base.step", ...]}

A product built from a spec stores its reference.json and one FreeCAD script per printed part, so a
remix rebuilds exactly that build; the drone and the gripper are built by their own code, so a remix
of one runs that flow again (base micro-drone or robot-gripper) and the entry keeps the published
numbers, parts, versions, renders and CAD files alongside. Publishing a remix links back to its
original, whose remix count is its starting count plus the entries remixed from it.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

from pai_agent.paths import DATA_DIR, RUNS_DIR
from pai_agent.references import CODE_REFERENCES, build_folder, build_reference, thumbnail_of, write_snapshot

SEEDS_DIR = DATA_DIR / "community"
PUBLISHED_DIR = RUNS_DIR / "community"
FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
# What a published entry copies from the session: the studio renders and the CAD files.
_FILE_PATTERNS = ("studio-v*.png", "*.step", "*.stl")
_MAX_FILE_BYTES = 30 * 1024 * 1024


def _kept(path: Path) -> bool:
    """A file worth publishing: not an assembly piece and not an older build of a part whose current file is there."""

    if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES or not FILE_NAME.fullmatch(path.name) or path.name.startswith("asm-"):
        return False
    older = re.fullmatch(r"(.+)-\d+(\.stl)", path.name)
    return older is None or not (path.parent / (older[1] + older[2])).is_file()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "project"


def _folders() -> list[Path]:
    folders = []
    for root in (SEEDS_DIR, PUBLISHED_DIR):
        if root.is_dir():
            folders += [path.parent for path in root.glob("*/entry.json")]
    return folders


def folder_of_entry(entry_id: str) -> Path | None:
    if not FILE_NAME.fullmatch(entry_id):
        return None
    for root in (SEEDS_DIR, PUBLISHED_DIR):
        folder = root / entry_id
        if (folder / "entry.json").is_file():
            return folder
    return None


def _read(folder: Path) -> dict:
    return json.loads((folder / "entry.json").read_text(encoding="utf-8"))


def thumbnail(entry_id: str) -> Path | None:
    """The entry's own thumbnail.png, else its base library item's render."""

    folder = folder_of_entry(entry_id)
    if folder is None:
        return None
    if (folder / "thumbnail.png").is_file():
        return folder / "thumbnail.png"
    base = _read(folder).get("base")
    return thumbnail_of(base) if base else None


def file_of(entry_id: str, name: str) -> Path | None:
    folder = folder_of_entry(entry_id)
    if folder is None or not FILE_NAME.fullmatch(name):
        return None
    path = folder / "files" / name
    return path if path.is_file() else None


def _row(entry: dict, folder: Path, remixed: dict[str, int], titles: dict[str, dict]) -> dict:
    parent = titles.get(entry.get("remixed_from") or "")
    return {
        "id": entry["id"],
        "title": entry["title"],
        "description": entry.get("description", ""),
        "author": entry.get("author", ""),
        "published_at": entry.get("published_at"),
        "product": entry.get("product", "generic"),
        "product_label": entry.get("product_label", ""),
        "base": entry.get("base"),
        "seed": folder.parent == SEEDS_DIR,
        "remixed_from": {"id": entry["remixed_from"], **parent} if parent else None,
        "remixes": int(entry.get("remixes", 0)) + remixed.get(entry["id"], 0),
        "metrics": entry.get("metrics", {}),
        "bom": entry.get("bom", []),
        "versions": entry.get("versions", []),
        "files": [{"name": name, "url": "/api/community/" + entry["id"] + "/files/" + name} for name in entry.get("files", [])],
        "thumbnail_url": "/api/community/" + entry["id"] + "/thumbnail" if thumbnail(entry["id"]) else None,
    }


def list_entries(sort: str = "new", query: str = "") -> list[dict]:
    """Every entry, newest first, or with sort "popular" the most remixed first."""

    entries = [(_read(folder), folder) for folder in _folders()]
    remixed: dict[str, int] = {}
    for entry, _folder in entries:
        if entry.get("remixed_from"):
            remixed[entry["remixed_from"]] = remixed.get(entry["remixed_from"], 0) + 1
    titles = {entry["id"]: {"title": entry["title"], "author": entry.get("author", "")} for entry, _folder in entries}
    rows = [_row(entry, folder, remixed, titles) for entry, folder in entries]
    q = query.strip().lower()
    if q:
        rows = [r for r in rows if q in " ".join([r["title"], r["description"], r["author"], r["product_label"]]).lower()]
    rows.sort(key=lambda r: r["published_at"] or "", reverse=True)
    if sort == "popular":
        rows.sort(key=lambda r: r["remixes"], reverse=True)
    return rows


def get_entry(entry_id: str) -> dict | None:
    return next((row for row in list_entries() if row["id"] == entry_id), None)


def _metrics(state) -> dict:
    """The numbers a card shows, the same keys for every product."""

    bom = state.bom or {}
    requirements = state.requirements
    out = {
        "requirements_passed": sum(1 for r in requirements if r.get("_met") is True),
        "requirements": len(requirements),
        "parts": len(bom.get("items", [])) or None,
        "cost_eur": bom.get("total_eur", state.metrics.get("price_eur")),
    }
    if state.product == "generic":
        built = state.assembly or {}
        out["mass_g"] = built.get("product_mass_g")
        out["printed"] = len(state.built)
    else:
        out["mass_g"] = state.metrics.get("weight_g")
        for key in ("thrust_to_weight", "flight_time_min", "grip_force_n"):
            if state.metrics.get(key) is not None:
                out[key] = state.metrics[key]
    return out


def _product_label(state) -> str:
    if state.product == "generic":
        return (state.spec or {}).get("name", "")
    return {"drone": "Micro FPV drone", "gripper": "Robot gripper"}.get(state.product, state.product)


def publish(state, title: str, description: str, author: str) -> dict:
    """Publishes the current build with its spec, parts, CAD files, renders and versions. Returns its row."""

    title, description, author = title.strip(), description.strip(), author.strip()
    if not title or not author:
        raise ValueError("A title and an author name are required.")
    if not state.bom:
        raise ValueError("Finish the build first: publish it once it has a bill of materials.")
    entry_id = _slug(title) + "-" + uuid.uuid4().hex[:4]
    folder = PUBLISHED_DIR / entry_id
    try:
        if state.product == "generic":
            # The full build, so a remix rebuilds exactly this spec, these scripts and these picks.
            write_snapshot(state, folder, entry_id, title, description)
            base = None
        else:
            base = {"drone": "micro-drone", "gripper": "robot-gripper"}.get(state.product)
            if base not in CODE_REFERENCES:
                raise ValueError("This build cannot be published yet.")
            folder.mkdir(parents=True)
        files = []
        (folder / "files").mkdir()
        directory = Path(state.directory)
        for pattern in _FILE_PATTERNS:
            for path in sorted(directory.glob(pattern)):
                if _kept(path):
                    shutil.copyfile(path, folder / "files" / path.name)
                    files.append(path.name)
        renders = sorted(
            (name for name in files if name.startswith("studio-v")),
            key=lambda n: int(re.sub(r"\D", "", n) or 0),
        )
        if renders:
            shutil.copyfile(folder / "files" / renders[-1], folder / "thumbnail.png")
        bom = (state.bom or {}).get("items", [])
        entry = {
            "id": entry_id,
            "title": title,
            "description": description,
            "author": author,
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "product": state.product,
            "product_label": _product_label(state),
            "base": base,
            "remixed_from": (state.remixed_from or {}).get("id"),
            "remixes": 0,
            "metrics": _metrics(state),
            "bom": [
                {
                    "name": item.get("name"),
                    "qty": item.get("qty"),
                    "unit_price_eur": item.get("unit_price_eur"),
                }
                for item in bom
            ],
            "versions": json.loads(json.dumps(state.versions, default=str)),
            "files": files,
        }
        (folder / "entry.json").write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    row = get_entry(entry_id)
    assert row is not None
    return row


async def build_entry(ctx, entry_id: str) -> dict:
    """Rebuilds an entry on the bench through the normal tools. Raises ValueError for an unknown id."""

    folder = folder_of_entry(entry_id)
    if folder is None:
        raise ValueError("No community project " + entry_id + ".")
    entry = _read(folder)
    if entry.get("base"):
        return await build_reference(ctx, entry["base"])
    if (folder / "reference.json").is_file():
        return await build_folder(ctx, folder)
    raise ValueError("The community project " + entry_id + " has nothing to rebuild.")
