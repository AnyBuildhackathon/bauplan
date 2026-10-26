"""`scene_object`: puts a real object from NVIDIA's SimReady library into the scene.

Objects are context for the build, never parts of it: the mug a holder is designed around, the
banana a gripper has to pick up, the pan it goes into. The tool finds the object in the offline
index (`simready/index.py`), fetches its package (license-checked and verified,
`simready/fetch.py`), converts it (`simready/convert.py`: an MJCF body with one convex hull, or
CoACD parts for a container, and a textured GLB), copies the files into the session so `/files/`
serves them, keeps the object on the bench (`state.objects`) and publishes an `object` event
with the CC BY 4.0 attribution and the list of changes. Objects never enter the bill of
materials, and their mass is marked as SimReady's estimate.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path

import numpy as np

from pai_agent.context import Ctx

ROLES = ("context", "payload", "target")
# A first use downloads the package; SimReady's largest ship gigabytes of textures. PAI_SIMREADY_MAX_MB raises it.
MAX_DOWNLOAD_MB = 300.0

SCHEMA = {
    "name": "scene_object",
    "description": (
        "Puts a real object into the scene from NVIDIA's SimReady library (2,575 objects under CC BY 4.0: food, kitchenware, boxes, bottles, "
        "tools, furniture and more), with its true size, its mass and friction from the USD, a MuJoCo body (one convex hull, or a convex "
        "decomposition for a container such as a pan or a bowl) and a textured 3D model. Use it for what a design is built around or has to "
        "handle: the mug a holder fits, the fruit a gripper picks up, the pan it goes into. query searches by name or class ('banana', "
        "'frying pan', 'mug') and places the best match; id places one exact object (from candidates). role: context (default), payload "
        "(what the product grips or carries) or target (where a payload goes). position_mm is the centre of the object's box in the scene "
        "(mm, Z up, the product's frame); without it the object stands on Z = 0 at the origin. Placing the same id again moves it; remove "
        "takes it out. Objects never enter the bill of materials and their mass is SimReady's estimate; say so when a number comes from one. "
        "The first use of an object downloads it (food and kitchenware 1 to 5 MB, equipment far more; over 300 MB is refused and a "
        "smaller match is taken) and converts it, up to a minute for a container."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for, e.g. 'banana' or 'coffee mug'."},
            "id": {"type": "string", "description": "An exact SimReady id, e.g. food_produce_banana_a01."},
            "role": {"type": "string", "enum": list(ROLES)},
            "position_mm": {"type": "array", "items": {"type": "number"}, "description": "Centre of the object's bounding box in the scene, [x, y, z] in mm."},
            "rotation_deg": {"type": "array", "items": {"type": "number"}, "description": "Degrees about X, then Y, then Z."},
            "collision": {"type": "string", "enum": ["auto", "hull", "decompose"], "description": "auto decomposes containers and gives everything else one convex hull."},
            "remove": {"type": "boolean", "description": "With id: take that object out of the scene."},
            "reason": {"type": "string", "description": "One line: why the object is in the scene."},
        },
    },
}


async def scene_object(ctx: Ctx, args: dict) -> dict:
    from pai_agent import simready
    from pai_agent.simready import fetch, index

    query = str(args.get("query") or "").strip()
    asset_id = str(args.get("id") or "").strip()
    if args.get("remove"):
        return await _remove(ctx, asset_id)

    def fits(row: dict) -> bool:
        return float(row.get("download_mb") or 0) <= max_download_mb() or fetch.cached_package(row["id"]) is not None

    candidates: list[dict] = []
    skipped: list[str] = []
    if asset_id:
        row = index.get(asset_id)
        if row is None:
            return _fail(f"{asset_id} is not a SimReady object of the pinned library; search with query first.")
        if not fits(row):
            smaller = [r for r in index.search(row.get("class") or row.get("title") or "", limit=20)[0] if fits(r)][:5]
            return {**_fail(_too_big(row, smaller)), "candidates": [_candidate(r) for r in smaller]}
    elif query:
        rows, _ = index.search(query, limit=20)
        if not rows:
            return _fail(f"No SimReady object matches '{query}'. Try one plain word: banana, mug, bowl, box, bottle, wrench.")
        fitting = [r for r in rows if fits(r)]
        if not fitting:
            return _fail(_too_big(rows[0], []))
        row, candidates = fitting[0], [_candidate(r) for r in rows if r is not fitting[0]][:5]
        skipped = [_too_big(r, []) for r in rows[: rows.index(row)]]
    else:
        return _fail("Give query (what to look for) or id (an exact SimReady id).")
    asset_id = row["id"]

    role = str(args.get("role") or "context")
    collision = str(args.get("collision") or "auto")
    if role not in ROLES:
        return _fail(f"role must be one of {', '.join(ROLES)}.")
    if collision not in ("auto", "hull", "decompose"):
        return _fail("collision must be auto, hull or decompose.")
    try:
        rotation_deg = _vector(args.get("rotation_deg"), [0.0, 0.0, 0.0], "rotation_deg")
        position = _vector(args.get("position_mm"), None, "position_mm")
    except ValueError as exc:
        return _fail(str(exc))
    missing = simready.missing("convert")
    if missing:
        return _fail(f"The SimReady converter needs {', '.join(missing)}. {simready.INSTALL_HINT}")

    from pai_agent.simready import convert

    title = row.get("title") or asset_id
    try:
        if fetch.cached_package(asset_id) is None:
            await _progress(ctx, f"Hugging Face: downloading {title}")
        package = await asyncio.to_thread(fetch.fetch, asset_id)
        _, meta = await asyncio.to_thread(convert.prepare, package)
        if convert.collision_mode(collision, meta) == "decompose":
            await _progress(ctx, f"CoACD: splitting {title} into convex parts")
        rotation = np.asarray(_rotation(rotation_deg))
        low, high = (np.asarray(v, dtype=float) for v in meta["bbox_m"])
        centre_m = (np.asarray(position, dtype=float) / 1000.0) if position is not None else np.array([0.0, 0.0, (high[2] - low[2]) / 2.0])
        origin_m = centre_m - rotation @ ((low + high) / 2.0)
        instance = asset_id
        prefix = f"simready-{instance}-"
        body = await asyncio.to_thread(
            convert.to_mjcf, asset_id, collision=collision, name=instance, file_prefix=prefix, pos=tuple(origin_m), quat=_quat(rotation), free=True
        )
        await _progress(ctx, f"Blender: 3D model of {title}")
        glb, glb_info = await asyncio.to_thread(convert.to_glb, asset_id)
    except fetch.SimReadyError as exc:
        return _fail(str(exc))

    directory = Path(ctx.state.directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, path in body.files.items():
        shutil.copyfile(path, directory / name)
    xml_name, glb_name = f"simready-{instance}.xml", f"simready-{instance}.glb"
    (directory / xml_name).write_text(body.standalone(), encoding="utf-8")
    shutil.copyfile(glb, directory / glb_name)

    changes = [*body.meta["changes"], glb_info["change"], f"Thumbnail resized to {fetch.THUMB_PX} px WebP"]
    attribution = convert.attribution(asset_id, body.meta["author"], package.revision, changes)
    info = body.meta
    position_mm = [round(float(v) * 1000.0, 1) for v in centre_m]
    event = {
        "type": "object",
        "id": asset_id,
        "title": title,
        "wikidata": info["wikidata"],
        "size_mm": info["size_mm"],
        "mass_g": info["mass_g"],
        "mass_estimated": True,
        "mass_source": info["mass_source"],
        "friction": info["friction"],
        "glb_url": _url(ctx, directory, glb_name),
        "thumbnail_url": f"/api/objects/{asset_id}/thumbnail",
        "mjcf_url": _url(ctx, directory, xml_name),
        "license": simready.LICENSE,
        "attribution": attribution,
        "changes": changes,
        "source": info["source"],
        "role": role,
        "position_mm": position_mm,
        "rotation_deg": rotation_deg,
        "origin_mm": [round(float(v) * 1000.0, 1) for v in origin_m],
        "collision": {key: info["collision"][key] for key in ("method", "parts", "cavity_mm") if key in info["collision"]},
        "grasp_points_mm": [[round(float(v) * 1000.0, 1) for v in grasp["pos"]] for grasp in info["grasps"]],
        "textured": bool(glb_info["textured"]),
        "warnings": info["warnings"],
        "reason": str(args.get("reason") or "")[:300],
    }
    ctx.state.objects[instance] = {
        **{key: event[key] for key in ("id", "title", "role", "position_mm", "rotation_deg", "origin_mm", "size_mm", "mass_g", "friction", "collision", "mjcf_url", "glb_url")},
        "quat": list(_quat(rotation)),
        "mjcf": xml_name,
        "glb": glb_name,
        "files": sorted(body.files),
    }
    await ctx.emit(event)
    method = "a CoACD decomposition into " + str(info["collision"]["parts"]) + " convex parts" if info["collision"]["method"] == "coacd" else "one convex hull per collision mesh"
    size = " x ".join(f"{v:g}" for v in info["size_mm"])
    return {
        "ok": True,
        "detail": f"{title} ({asset_id}): {size} mm, {info['mass_g']:g} g (SimReady estimate), friction {info['friction']:g}, {method}",
        "object": {key: event[key] for key in ("id", "title", "role", "size_mm", "mass_g", "friction", "position_mm", "rotation_deg", "collision", "grasp_points_mm")},
        "candidates": candidates,
        "warnings": [*skipped, *info["warnings"]],
        "attribution": attribution,
        "next": (
            "Use its size as a design input and say it comes from NVIDIA SimReady; its mass is an estimate. "
            "It stands in the scene as context and is not in the bill of materials."
        ),
    }


async def _remove(ctx: Ctx, asset_id: str) -> dict:
    if not asset_id or asset_id not in ctx.state.objects:
        placed = ", ".join(sorted(ctx.state.objects)) or "none"
        return _fail(f"No object {asset_id or '(no id)'} in the scene; placed: {placed}.")
    gone = ctx.state.objects.pop(asset_id)
    await ctx.emit({"type": "object", "id": gone["id"], "removed": True})
    return {"ok": True, "detail": f"{gone['title']} removed from the scene", "removed": gone["id"]}


async def _progress(ctx: Ctx, detail: str) -> None:
    await ctx.emit({"type": "tool", "name": "scene_object", "status": "running", "detail": detail})


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message}


def _candidate(row: dict) -> dict:
    return {key: row.get(key) for key in ("id", "title", "category", "size_mm", "mass_g", "download_mb")}


def max_download_mb() -> float:
    import os

    try:
        return float(os.environ.get("PAI_SIMREADY_MAX_MB", "") or MAX_DOWNLOAD_MB)
    except ValueError:
        return MAX_DOWNLOAD_MB


def _too_big(row: dict, smaller: list[dict]) -> str:
    message = (
        f"{row.get('title') or row['id']} ({row['id']}) is a {float(row.get('download_mb') or 0):g} MB download, "
        f"over the {max_download_mb():g} MB a first use may fetch (PAI_SIMREADY_MAX_MB)."
    )
    if smaller:
        message += " Smaller matches: " + ", ".join(f"{r['id']} ({float(r.get('download_mb') or 0):g} MB)" for r in smaller) + "."
    return message


def _vector(value, default, name: str):
    if value is None:
        return default
    try:
        numbers = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be three numbers.") from exc
    if len(numbers) != 3 or not all(np.isfinite(numbers)):
        raise ValueError(f"{name} must be three numbers.")
    return numbers


def _rotation(rotation_deg: list[float]) -> list[list[float]]:
    from pai_agent.assembly import rotation

    # The same convention as product_spec's parts: about X, then Y, then Z.
    return rotation(rotation_deg)


def _quat(rotation: np.ndarray) -> tuple[float, float, float, float]:
    import mujoco

    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, np.asarray(rotation, dtype=float).reshape(-1))
    return tuple(float(v) for v in quat)


def _url(ctx: Ctx, directory: Path, name: str) -> str:
    # The version keeps a browser from showing an earlier placement under the same name.
    version = hashlib.sha256((directory / name).read_bytes()).hexdigest()[:10]
    return f"/files/{ctx.state.session_id}/{name}?v={version}"
