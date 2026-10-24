"""Headless Blender studio render of the whole drone. Offline, with a recorded still, when Blender is absent."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

from pai_agent.context import Ctx
from pai_agent.mesh_export import write_solid_png
from pai_agent.paths import AGENT_ROOT, FALLBACK_DIR, REPO_ROOT

_SCRIPT = AGENT_ROOT / "blender" / "studio.py"
_FALLBACK_PNG = FALLBACK_DIR / "render.png"


_KNOWN_BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")


def find_blender() -> str | None:
    if _KNOWN_BLENDER.is_file() and os.access(_KNOWN_BLENDER, os.X_OK):
        return str(_KNOWN_BLENDER)
    found = shutil.which("blender")
    if found:
        return found
    return None


def _assembly(state) -> dict:
    """What studio.py places around the frame STL: arm, plate, battery and propeller sizes in mm."""

    battery = state.selected.get("battery") or {}
    propeller = state.selected.get("propeller") or {}
    spec = {
        "arm_mm": float(state.cad_params.get("arm_length_mm") or 36),
        "thickness_mm": float(state.cad_params.get("thickness_mm") or 2),
        "prop_mm": float(propeller.get("diameter_mm") or 40),
    }
    if "length_mm" in battery:
        spec["battery_mm"] = [float(battery[k]) for k in ("length_mm", "width_mm", "height_mm")]
    return spec


def _render(binary: str, stl: Path, png: Path, spec: dict) -> None:
    png.parent.mkdir(parents=True, exist_ok=True)
    spec_path = png.with_suffix(".json")
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    completed = subprocess.run(
        [binary, "-b", "--factory-startup", "-P", str(_SCRIPT), "--", str(stl), str(png), str(spec_path)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0 or not png.is_file() or png.stat().st_size < 32:
        tail = (completed.stderr or completed.stdout or "Blender hat kein Bild geschrieben").strip()[-400:]
        raise RuntimeError(tail)


async def blender_render(ctx: Ctx, args: dict) -> dict:
    del args
    if not ctx.state.stl_path:
        message = "Kein STL. Erst cad_frame aufrufen."
        return {"ok": False, "error": message, "detail": message}
    stl = REPO_ROOT / ctx.state.stl_path
    binary = find_blender()
    # One file per version, so the v1 render stays next to the v2 render.
    name = "studio-v" + str(len(ctx.state.versions) + 1) + ".png"
    png = Path(ctx.state.directory) / name
    if binary is not None:
        try:
            await asyncio.to_thread(_render, binary, stl, png, _assembly(ctx.state))
        except (OSError, TimeoutError, RuntimeError, subprocess.SubprocessError):
            binary = None
    if binary is not None and png.is_file():
        url = "/files/" + ctx.state.session_id + "/" + name
        label = "v" + str(len(ctx.state.versions) + 1) + " · Studio"
        await ctx.emit({"type": "render", "source": "blender", "png_url": url, "label": label})
        return {"ok": True, "status": "ok", "detail": label + "-Render", "png_url": url}
    _ensure_fallback()
    url = "/files/fallback/render.png"
    await ctx.emit(
        {
            "type": "render",
            "source": "blender",
            "png_url": url,
            "label": "Aufgezeichnet, Blender ist offline",
        }
    )
    return {
        "ok": True,
        "status": "offline",
        "detail": "Blender fehlt. Aufgezeichnetes Standbild.",
        "png_url": url,
    }


def _ensure_fallback() -> None:
    if _FALLBACK_PNG.is_file():
        return
    _FALLBACK_PNG.parent.mkdir(parents=True, exist_ok=True)
    write_solid_png(_FALLBACK_PNG, 320, 180, (18, 20, 24))
