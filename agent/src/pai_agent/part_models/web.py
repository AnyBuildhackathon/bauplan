"""A 3D model for a part found on the web during a build (web_parts.py, kept in the learned library), which the library has none for.

First the official model: an Adafruit product's STEP from Adafruit's MIT-licensed CAD repository,
found by the product number in the part's shop link. Other makers' published models are not
fetched: their terms do not allow passing them on (Pololu gives none, GrabCAD uploads forbid it).
Otherwise the look-alike for the part's category, built from the numbers the web page gave; a
number the page did not give is drawn in proportion and the model says so (`approximate`).
Models are cached in agent/runs/cache/part-models/web/ so a part is built once.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..paths import RUNS_DIR

log = logging.getLogger(__name__)

CACHE_DIR = RUNS_DIR / "cache" / "part-models" / "web"
ADAFRUIT_API = "https://api.github.com/repos/adafruit/Adafruit_CAD_Parts/contents/"
ADAFRUIT_RAW = "https://raw.githubusercontent.com/adafruit/Adafruit_CAD_Parts/main/"
STEP_LIMIT_BYTES = 6_000_000
_MEMO: dict[str, tuple[Path, dict] | None] = {}


def _get(url: str, timeout: float = 15.0) -> bytes:
    request = Request(url, headers={"User-Agent": "AnyBuild part models", "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def adafruit_step(part: dict) -> tuple[Path, str] | None:
    """Adafruit's STEP for the product in the part's link, downloaded once; None when there is none."""

    links = " ".join(str(part.get(key) or "") for key in ("source_url", "url"))
    match = re.search(r"adafruit\.com/product/(\d+)", links)
    if not match:
        return None
    number = match.group(1)
    target = CACHE_DIR / f"adafruit-{number}.step"
    folder_url = ADAFRUIT_API
    if not target.exists():
        try:
            folders = [item["name"] for item in json.loads(_get(ADAFRUIT_API)) if item.get("type") == "dir"]
            folder = next((name for name in folders if name.split(" ")[0] == number), None)
            if folder is None:
                return None
            files = json.loads(_get(ADAFRUIT_API + quote(folder)))
            step = next((f for f in files if f["name"].lower().endswith((".step", ".stp")) and f.get("size", 0) <= STEP_LIMIT_BYTES), None)
            if step is None:
                return None
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_get(ADAFRUIT_RAW + quote(folder) + "/" + quote(step["name"]), timeout=60.0))
            folder_url = "https://github.com/adafruit/Adafruit_CAD_Parts/tree/main/" + quote(folder)
        except (OSError, ValueError, KeyError) as error:
            log.info("no Adafruit model for %s: %s", number, error)
            return None
    else:
        folder_url = "https://github.com/adafruit/Adafruit_CAD_Parts"
    return target, folder_url


def _num(part: dict, key: str) -> float | None:
    try:
        value = float(part[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def spec_for(part: dict) -> dict:
    """The sources.json-style spec of a web part: its type and the numbers its page gave."""

    category = str(part.get("category") or "")
    source = part.get("source_url") or part.get("url")
    fields = part.get("fields") or {}
    estimated = set(part.get("estimated") or [])

    def origin(field: str):
        # Each number cites the page it came from (the maker page, the datasheet) when the part says so.
        return (fields.get(field) or {}).get("source") or source
    size = part.get("size_mm") if isinstance(part.get("size_mm"), list) and len(part["size_mm"]) == 3 else None

    def take(*pairs):
        out = {}
        for field, name in pairs:
            value = _num(part, field)
            if value is not None and field not in estimated:
                out[name] = {"value": value, "source": origin(field)}
        return out

    def size_dims():
        if not size or "size_mm" in estimated:
            return {}
        return {name: {"value": float(v), "source": origin(name)} for name, v in zip(("length_mm", "width_mm", "height_mm"), size) if name not in estimated}

    estimate: dict = {}
    style: dict = {}
    if category == "motor" and (part.get("kv") or part.get("mount_diameter_mm")):
        kind = "brushless_motor"
        dims = take(("diameter_mm", "diameter_mm"), ("height_mm", "height_mm"), ("shaft_mm", "shaft_mm"), ("mount_diameter_mm", "bolt_circle_mm"))
        estimate = {"diameter_mm": 14.0, "height_mm": 13.5, "shaft_mm": 1.5, "bolt_circle_mm": 6.6, "bolts": 3 if (_num(part, "mount_diameter_mm") or 6.6) < 9 else 4, "bolt_thread_mm": 1.4 if (_num(part, "mount_diameter_mm") or 6.6) < 9 else 2.0}
    elif category == "motor" and (part.get("steps_per_rev") or part.get("holding_torque_nm")) and size:
        kind = "stepper"
        dims = {"face_mm": {"value": float(size[0]), "source": source}, "length_mm": {"value": float(size[2]), "source": source}} if "size_mm" not in estimated else {}
        dims.update(take(("shaft_mm", "shaft_mm")))
        estimate = {"face_mm": float(size[0]), "length_mm": float(size[2]), "shaft_mm": 5.0, "hole_spacing_mm": round(float(size[0]) * 0.733, 1)}
    elif category == "motor" and size and abs(size[0] - size[1]) < 0.5:
        kind = "round_gearmotor"
        dims = {"diameter_mm": {"value": float(size[0]), "source": source}, "length_mm": {"value": float(size[2]), "source": source}} if "size_mm" not in estimated else {}
        dims.update(take(("shaft_mm", "shaft_mm")))
        estimate = {"diameter_mm": float(size[0]), "length_mm": float(size[2]), "shaft_mm": 4.0, "face_hole_circle_mm": float(size[0]) * 0.7}
    elif category == "propeller":
        kind = "propeller"
        dims = take(("diameter_mm", "diameter_mm"), ("blades", "blades"), ("shaft_mm", "shaft_mm"), ("pitch_in", "pitch_in"))
        estimate = {"diameter_mm": 51.0, "blades": 3, "shaft_mm": 1.5, "hub_h_mm": 4.5}
    elif category == "battery" and (part.get("length_mm") or size):
        kind = "lipo_pack"
        dims = take(("length_mm", "length_mm"), ("width_mm", "width_mm"), ("height_mm", "height_mm")) or size_dims()
        cells = int(_num(part, "cells") or 1)
        plug = str(part.get("connector") or "").lower().replace(" ", "")
        plug = next((k for k in ("xt60", "xt30", "bt2.0", "ph2.0") if k in plug), None)
        if plug:
            dims["connector"] = {"value": plug, "source": source}
        estimate = {"length_mm": float(size[0]) if size else 60.0, "width_mm": float(size[1]) if size else 18.0, "height_mm": float(size[2]) if size else 8.0, "connector": "bt2.0" if cells == 1 else "xt30"}
        style = {"cells": cells, "lead_len_mm": 30, "balance_lead": cells > 1}
    elif category == "camera" and (part.get("width_mm") or part.get("size_mm")):
        kind = "fpv_camera"
        dims = take(("length_mm", "length_mm"), ("width_mm", "width_mm"), ("height_mm", "height_mm"))
        side = _num(part, "size_mm") or 14.0
        estimate = {"length_mm": side, "width_mm": side, "height_mm": side}
    elif category == "frame":
        kind = "whoop_frame" if part.get("ducted") else "carbon_frame"
        dims = take(("wheelbase_mm", "wheelbase_mm"), ("mount_mm", "mount_mm"), ("mount_diameter_mm", "mount_diameter_mm"), ("arm_thickness_mm", "arm_thickness_mm"))
        if isinstance(part.get("size_mm"), list):
            dims.update({"size_mm": {"value": part["size_mm"], "source": source}})
        estimate = {"wheelbase_mm": 85.0, "mount_mm": 26.0, "mount_diameter_mm": 6.6, "arm_thickness_mm": 2.5, "size_mm": [120.0, 120.0, 16.0]}
    elif category == "servo" and size:
        kind = "servo"
        dims = take(("length_mm", "length_mm"), ("width_mm", "width_mm"))
        estimate = {"length_mm": float(size[0]), "width_mm": float(size[1]), "overall_height_mm": float(size[2]), "tab_bottom_mm": float(size[2]) * 0.55, "tab_span_mm": float(size[0]) * 1.35}
    elif category == "wheel":
        kind = "wheel"
        dims = take(("diameter_mm", "diameter_mm"), ("bore_mm", "bore_mm"))
        estimate = {"diameter_mm": float(size[0]) if size else 60.0, "width_mm": float(size[2]) if size else 8.0, "bore_mm": 3.0}
    elif category in ("flight_controller", "vtx", "controller", "sensor", "driver", "power") or size:
        kind = "board" if category != "vtx" else "vtx"
        dims = size_dims()
        board = _num(part, "board_mm") or (_num(part, "mount_mm") or 26.0) + 4.0
        estimate = {"length_mm": float(size[0]) if size else board, "width_mm": float(size[1]) if size else board, "height_mm": float(size[2]) if size else 4.0, "holes": []}
        if category == "flight_controller" or (category == "vtx" and part.get("mount_mm")):
            half = (_num(part, "mount_mm") or 26.0) / 2
            estimate["holes"] = [[half, half, 2.0], [-half, half, 2.0], [-half, -half, 2.0], [half, -half, 2.0]]
            if category == "vtx":
                estimate["mount_mm"] = half * 2
        style = {"pcb_color": "black", "pcb_mm": 1.0, "parts": [{"k": "chip", "x": 0, "y": 0, "w": 6, "l": 6, "h": 0.9}]}
    else:
        kind = "enclosure"
        dims = size_dims()
        estimate = {"length_mm": 20.0, "width_mm": 20.0, "height_mm": 10.0}
    return {
        "name": part.get("name") or part.get("id"),
        "category": category,
        "type": kind,
        "source": source,
        "checked": part.get("checked"),
        "dims": dims,
        "estimate": estimate,
        "style": style,
        "note": "Built during a build for a part found on the web; numbers from its page, the rest drawn in proportion.",
    }


def web_model(part: dict) -> tuple[Path, dict] | None:
    """The model of a part the library has no model for: Adafruit's official STEP, else a look-alike."""

    from .build import build_part

    part_id = str(part.get("id") or "")
    if not part_id:
        return None
    if part_id in _MEMO:
        return _MEMO[part_id]
    safe = re.sub(r"[^a-z0-9._-]+", "-", part_id.lower())
    glb = CACHE_DIR / f"{safe}.glb"
    meta = CACHE_DIR / f"{safe}.json"
    result: tuple[Path, dict] | None = None
    if glb.exists() and meta.exists():
        result = (glb, json.loads(meta.read_text()))
    else:
        try:
            official = adafruit_step(part)
            if official is not None:
                step, url = official
                spec = {"name": part.get("name") or part_id, "category": part.get("category"), "type": "official", "source": part.get("source_url"),
                        "official": {"file": step.name, "path": str(step), "url": url, "author": "Adafruit Industries", "license": "MIT (Adafruit Industries)"}}
            else:
                spec = spec_for(part)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            entry = build_part(part_id, spec, glb_path=glb)
            meta.write_text(json.dumps(entry))
            result = (glb, entry)
        except Exception as error:  # a web part without a model keeps the simple solid
            log.warning("no model for web part %s: %s", part_id, error)
            result = None
    _MEMO[part_id] = result
    return result
