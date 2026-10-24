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
    """The hero drone GLB from FreeCAD, or what studio.py places around a bare frame STL: arm, plate,
    battery and propeller sizes in mm."""

    glb = Path(state.directory) / "frame.glb"
    if is_drone_glb(glb):
        return {"glb": str(glb)}

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


def is_drone_glb(path: Path) -> bool:
    """True for the assembly frame_build.py writes, False for a frame-only GLB from CadQuery."""

    try:
        with path.open("rb") as handle:
            header = handle.read(20)
            if len(header) < 20 or header[:4] != b"glTF":
                return False
            length = int.from_bytes(header[12:16], "little")
            gltf = json.loads(handle.read(length))
    except (OSError, ValueError):
        return False
    return any(node.get("name") == "motor_front_left" for node in gltf.get("nodes", []))


def _part_spec(state) -> dict:
    """A generated part: every printed and bought piece with its own color."""

    directory = Path(state.directory)
    return {
        "mode": "part",
        "parts": [{"stl": str(directory / part["stl"]), "color": part.get("color"), "name": part["name"]} for part in state.part["parts"]],
    }


def _generic_spec(state) -> dict:
    """Any product: every assembled body (printed parts, bought blocks, loads) with its own color."""

    directory = Path(state.directory)
    bodies = [body for body in state.assembly["bodies"] if body.get("stl")]
    return {"mode": "part", "parts": [{"stl": str(directory / b["stl"]), "color": b.get("color"), "name": b["name"]} for b in bodies]}


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
            if ctx.state.product == "generic" and ctx.state.assembly:
                spec = _generic_spec(ctx.state)
            elif ctx.state.product != "drone" and ctx.state.part:
                spec = _part_spec(ctx.state)
            else:
                spec = _assembly(ctx.state)
            await asyncio.to_thread(_render, binary, stl, png, spec)
        except (OSError, TimeoutError, RuntimeError, subprocess.SubprocessError):
            binary = None
    if binary is not None and png.is_file():
        url = "/files/" + ctx.state.session_id + "/" + name
        label = "v" + str(len(ctx.state.versions) + 1) + " · Studio"
        await ctx.emit({"type": "render", "source": "blender", "png_url": url, "label": label})
        return {"ok": True, "status": "ok", "detail": label + " render", "png_url": url}
    _ensure_fallback()
    url = "/files/fallback/render.png"
    await ctx.emit(
        {
            "type": "render",
            "source": "blender",
            "png_url": url,
            "label": "Recorded, Blender is offline",
        }
    )
    return {
        "ok": True,
        "status": "offline",
        "detail": "Blender is missing. Recorded still.",
        "png_url": url,
    }


def _ensure_fallback() -> None:
    if _FALLBACK_PNG.is_file():
        return
    _FALLBACK_PNG.parent.mkdir(parents=True, exist_ok=True)
    write_solid_png(_FALLBACK_PNG, 320, 180, (18, 20, 24))
