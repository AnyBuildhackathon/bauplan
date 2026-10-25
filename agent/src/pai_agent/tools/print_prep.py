"""Print-ready output for every printed part: slicer when installed, else an honest estimate.

PrusaSlicer or OrcaSlicer on this machine slices each STL headless and the G-code is served
for download; the time and filament come from the comments the slicer writes. Without a
slicer the numbers come from the mesh: shell and infill volume at a default profile, an
average volumetric flow and a per-layer overhead, labelled 'estimate', with no G-code.
Printability warnings always come from the mesh itself: overhangs past 45 degrees, walls
thinner than 0.8 mm, and parts that do not fit a 220 mm bed.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

from pai_agent.context import Ctx

BED_MM = (220.0, 220.0, 250.0)
OVERHANG_DEG = 45.0
MIN_WALL_MM = 0.8
PROFILE = {"printer": "Generic 220 mm bed, 0.4 mm nozzle", "nozzle_mm": 0.4, "layer_height_mm": 0.2, "infill_pct": 20, "walls": 2}
# Average extrusion rate and per-layer overhead of a stock bed slinger with the profile above.
FLOW_MM3_S = 7.0
LAYER_OVERHEAD_S = 2.5
START_S = 180.0
# g/cm³ and €/g of a 1 kg spool.
FILAMENTS = {
    "PLA": (1.24, 0.025),
    "PETG": (1.27, 0.025),
    "PETG-CF": (1.30, 0.045),
    "ABS": (1.04, 0.025),
    "ASA": (1.07, 0.03),
    "TPU": (1.21, 0.04),
    "NYLON": (1.14, 0.05),
}
FILAMENT_DIAMETER_MM = 1.75
ORIENTATIONS = ("as_modeled", "flat", "upright")
_SLICERS = (
    ("PrusaSlicer", ("prusa-slicer", "PrusaSlicer", "prusa-slicer-console"), "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"),
    ("OrcaSlicer", ("orca-slicer", "OrcaSlicer"), "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"),
)


def find_slicer() -> tuple[str, str] | None:
    """(name, executable) of the first slicer found, PAI_SLICER overrides."""

    override = os.environ.get("PAI_SLICER", "").strip()
    if override.lower() == "off":
        return None
    if override and Path(override).is_file():
        return ("OrcaSlicer" if "orca" in override.lower() else "PrusaSlicer", override)
    for name, commands, app in _SLICERS:
        for command in commands:
            found = shutil.which(command)
            if found:
                return name, found
        if Path(app).is_file():
            return name, app
    return None


def read_stl(path: Path) -> np.ndarray:
    """Triangles as an (n, 3, 3) array, binary or ASCII STL."""

    data = path.read_bytes()
    if len(data) >= 84:
        count = int.from_bytes(data[80:84], "little")
        if 84 + count * 50 == len(data):
            rows = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=count, offset=84)
            return rows["v"].astype(np.float64)
    numbers = re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)
    return np.array(numbers, dtype=np.float64).reshape(-1, 3, 3)


def orient(tris: np.ndarray, orientation: str) -> tuple[np.ndarray, list[float]]:
    """Rotate so the requested axis is up and drop the part onto the bed; returns the X/Y rotation used."""

    size = np.ptp(tris.reshape(-1, 3), axis=0) if tris.size else np.zeros(3)
    rotation = [0.0, 0.0]
    if orientation in {"flat", "upright"} and tris.size:
        # flat puts the smallest extent on Z, upright the largest.
        axis = int(np.argmin(size) if orientation == "flat" else np.argmax(size))
        if axis == 0:
            tris = tris[..., [2, 1, 0]] * np.array([-1.0, 1.0, 1.0])
            rotation = [0.0, 90.0]
        elif axis == 1:
            tris = tris[..., [0, 2, 1]] * np.array([1.0, -1.0, 1.0])
            rotation = [90.0, 0.0]
    if tris.size:
        tris = tris - np.array([0.0, 0.0, tris[..., 2].min()])
    return tris, rotation


def analyse(tris: np.ndarray) -> dict:
    """Volume, surface, size and the overhang area of one oriented mesh."""

    if not tris.size:
        return {"volume_mm3": 0.0, "area_mm2": 0.0, "size_mm": [0.0, 0.0, 0.0], "overhang_mm2": 0.0, "overhang_max_deg": 0.0}
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    cross = np.cross(b - a, c - a)
    areas = np.linalg.norm(cross, axis=1) / 2
    volume = abs(float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6)
    normals = cross / np.maximum(np.linalg.norm(cross, axis=1, keepdims=True), 1e-12)
    # A face hangs over when it faces down more steeply than 45 degrees from vertical; the bed face is excluded.
    on_bed = tris[..., 2].max(axis=1) < 0.05
    limit = -math.sin(math.radians(OVERHANG_DEG))
    hanging = (normals[:, 2] < limit) & ~on_bed & (areas > 0)
    worst = 0.0
    if hanging.any():
        worst = math.degrees(math.asin(min(1.0, float(-normals[hanging, 2].min()))))
    return {
        "volume_mm3": volume,
        "area_mm2": float(areas.sum()),
        "size_mm": [round(float(v), 1) for v in np.ptp(tris.reshape(-1, 3), axis=0)],
        "overhang_mm2": float(areas[hanging].sum()),
        "overhang_max_deg": round(worst, 0),
    }


def estimate(mesh: dict, material: str) -> dict:
    """Print time and filament from shell plus infill volume at the default profile."""

    density, eur_per_g = FILAMENTS.get(material, FILAMENTS["PETG"])
    wall = PROFILE["walls"] * PROFILE["nozzle_mm"] * 1.1
    shell = min(mesh["volume_mm3"], mesh["area_mm2"] * wall)
    extruded = shell + (mesh["volume_mm3"] - shell) * PROFILE["infill_pct"] / 100
    # Supports under overhangs: a sparse column 0.15 of the area times half the part height.
    support = mesh["overhang_mm2"] * 0.15 * mesh["size_mm"][2] / 2
    extruded += support
    layers = max(1, math.ceil(mesh["size_mm"][2] / PROFILE["layer_height_mm"]))
    seconds = START_S + extruded / FLOW_MM3_S + layers * LAYER_OVERHEAD_S
    grams = extruded * density / 1000
    return {
        "time_min": round(seconds / 60, 0),
        "filament_g": round(grams, 1),
        "filament_m": round(extruded / (math.pi * (FILAMENT_DIAMETER_MM / 2) ** 2) / 1000, 2),
        "cost_eur": round(grams * eur_per_g, 2),
    }


def warnings_for(mesh: dict, min_wall_mm: float | None) -> list[dict]:
    out = []
    if mesh["overhang_mm2"] > 1.0:
        out.append(
            {
                "kind": "overhang",
                "text": f"{mesh['overhang_mm2'] / 100:.1f} cm² hangs over more than {OVERHANG_DEG:.0f}°, up to {mesh['overhang_max_deg']:.0f}°: needs supports or another orientation",
            }
        )
    thinnest = min([v for v in mesh["size_mm"] if v > 0] or [0.0])
    wall = min(v for v in (min_wall_mm, thinnest) if v is not None) if (min_wall_mm is not None or thinnest) else None
    if wall is not None and wall < MIN_WALL_MM:
        out.append({"kind": "thin_wall", "text": f"Wall {wall:.2f} mm is thinner than {MIN_WALL_MM} mm: two 0.4 mm perimeters cannot print it"})
    x, y, z = mesh["size_mm"]
    fits = (max(x, y) <= BED_MM[0] and min(x, y) <= BED_MM[1]) and z <= BED_MM[2]
    if not fits:
        out.append({"kind": "bed_size", "text": f"{x:.0f} × {y:.0f} × {z:.0f} mm does not fit a {BED_MM[0]:.0f} mm bed: split it or rotate it"})
    return out


_TIME = re.compile(r";\s*(?:estimated printing time \(normal mode\)|total estimated time)\s*[=:]\s*(.+)", re.I)
_GRAMS = re.compile(r";\s*(?:total )?filament (?:used \[g\]|weight \[g\])\s*[=:]\s*([\d.]+)", re.I)
_METRES = re.compile(r";\s*(?:total )?filament used \[mm\]\s*[=:]\s*([\d.]+)", re.I)


def _minutes(text: str) -> float:
    total = 0.0
    for value, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])", text):
        total += float(value) * {"d": 1440, "h": 60, "m": 1, "s": 1 / 60}[unit]
    return total


def parse_gcode(path: Path) -> dict:
    """Time and filament from the comments PrusaSlicer and OrcaSlicer write."""

    text = path.read_text(errors="ignore")
    tail = text[-60000:] + text[:20000]
    out: dict = {}
    if match := _TIME.search(tail):
        out["time_min"] = round(_minutes(match.group(1)), 0)
    if match := _GRAMS.search(tail):
        out["filament_g"] = round(float(match.group(1)), 1)
    if match := _METRES.search(tail):
        out["filament_m"] = round(float(match.group(1)) / 1000, 2)
    return out


def _slice(slicer: tuple[str, str], stl: Path, gcode: Path, rotation: list[float], material: str) -> dict:
    name, executable = slicer
    if name == "PrusaSlicer":
        command = [
            executable,
            "--export-gcode",
            "--layer-height", str(PROFILE["layer_height_mm"]),
            "--fill-density", f"{PROFILE['infill_pct']}%",
            "--perimeters", str(PROFILE["walls"]),
            "--nozzle-diameter", str(PROFILE["nozzle_mm"]),
            "--filament-type", material if material in {"PLA", "PETG", "ABS", "ASA", "FLEX", "NYLON"} else "PETG",
            "--bed-shape", f"0x0,{BED_MM[0]:g}x0,{BED_MM[0]:g}x{BED_MM[1]:g},0x{BED_MM[1]:g}",
            "--center", f"{BED_MM[0] / 2:g},{BED_MM[1] / 2:g}",
            "--support-material",
            "--support-material-threshold", f"{90 - OVERHANG_DEG:g}",
        ]
        if rotation[0]:
            command += ["--rotate-x", f"{rotation[0]:g}"]
        if rotation[1]:
            command += ["--rotate-y", f"{rotation[1]:g}"]
        command += ["--output", str(gcode), str(stl)]
    else:
        command = [executable, "--slice", "0", "--outputdir", str(gcode.parent), str(stl)]
    done = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if name != "PrusaSlicer" and not gcode.is_file():
        produced = sorted(gcode.parent.glob(stl.stem + "*.gcode")) or sorted(gcode.parent.glob("plate_*.gcode"))
        if produced:
            produced[-1].replace(gcode)
    if done.returncode != 0 or not gcode.is_file():
        raise RuntimeError((done.stderr or done.stdout or name + " failed").strip().splitlines()[-1][:200])
    return parse_gcode(gcode)


def printed_parts(ctx: Ctx) -> list[dict]:
    """Every printed part of the current build with its STL, material, quantity and thinnest designed wall."""

    state = ctx.state
    directory = Path(state.directory)
    parts = []
    if state.product == "generic" and state.spec:
        for part in state.spec["parts"]:
            info = state.built.get(part["id"])
            if part["kind"] != "printed" or not info:
                continue
            walls = [float(v) for k, v in (info.get("params") or {}).items() if "thick" in k or "wall" in k]
            parts.append(
                {
                    "id": part["id"],
                    "name": part["name"],
                    "material": str(info.get("material") or "PETG").upper(),
                    "qty": int(part.get("qty") or 1),
                    "stl": directory / ("part-" + part["id"] + ".stl"),
                    "min_wall_mm": min(walls) if walls else None,
                }
            )
    elif state.product == "gripper" and state.part:
        from pai_agent.paths import REPO_ROOT

        # cad_part records the newest STL on the state (part-<name>.stl), not on the part.
        stl = REPO_ROOT / state.stl_path if state.stl_path else directory / "part.stl"
        parts.append({"id": "body", "name": state.part.get("name", "Gripper") + " body", "material": str(state.part.get("material") or "PETG").upper(), "qty": 1, "stl": stl, "min_wall_mm": None})
    elif state.product == "drone" and state.stl_path:
        from pai_agent.paths import REPO_ROOT

        thickness = state.cad_params.get("thickness_mm")
        parts.append(
            {
                "id": "frame",
                "name": "Frame prototype",
                "material": "PETG-CF",
                "qty": 1,
                "stl": REPO_ROOT / state.stl_path,
                "min_wall_mm": float(thickness) if thickness is not None else None,
            }
        )
    return [p for p in parts if Path(p["stl"]).is_file()]


def _plan_part(part: dict, orientation: str, slicer: tuple[str, str] | None, session_id: str) -> dict:
    stl = Path(part["stl"])
    tris, rotation = orient(read_stl(stl), orientation)
    mesh = analyse(tris)
    row = {
        "id": part["id"],
        "name": part["name"],
        "material": part["material"],
        "qty": part["qty"],
        "orientation": orientation,
        "size_mm": mesh["size_mm"],
        "volume_cm3": round(mesh["volume_mm3"] / 1000, 2),
        "warnings": warnings_for(mesh, part["min_wall_mm"]),
        "stl_url": "/files/" + session_id + "/" + stl.name if stl.parent.name == session_id else "",
        "gcode_url": "",
        "source": "estimate",
        **estimate(mesh, part["material"]),
    }
    if slicer is not None:
        gcode = stl.with_name("print-" + part["id"] + ".gcode")
        try:
            sliced = _slice(slicer, stl, gcode, rotation, part["material"])
            eur_per_g = FILAMENTS.get(part["material"], FILAMENTS["PETG"])[1]
            row.update({k: v for k, v in sliced.items() if v})
            row["cost_eur"] = round(row["filament_g"] * eur_per_g, 2)
            row["gcode_url"] = "/files/" + session_id + "/" + gcode.name
            row["source"] = "slicer"
        except Exception as exc:  # The estimate stays; the row says why the slicer did not help.
            row["slicer_error"] = str(exc)
    return row


def filament_line(plan: dict) -> dict:
    """The bill-of-materials line for the filament the print plan uses."""

    materials = sorted({row["material"] for row in plan["parts"]})
    grams = plan["totals"]["filament_g"]
    count = sum(row["qty"] for row in plan["parts"])
    return {
        "name": "Filament " + " + ".join(materials) + f", {grams:.0f} g for {count} printed part{'s' if count != 1 else ''}",
        "qty": 1,
        "unit_price_eur": plan["totals"]["cost_eur"],
        "weight_g": 0.0,
        "shop": "printed",
        "url": "",
        "price_source": "estimated",
        "category": "filament",
    }


async def print_prep(ctx: Ctx, args: dict) -> dict:
    orientation = str(args.get("orientation") or "flat")
    if orientation not in ORIENTATIONS:
        orientation = "flat"
    per_part = args.get("orientations") if isinstance(args.get("orientations"), dict) else {}
    parts = printed_parts(ctx)
    if not parts:
        message = "No printed part with an STL yet: build the CAD first."
        return {"ok": False, "error": message, "detail": message}
    slicer = find_slicer()
    session_id = ctx.state.session_id
    rows = []
    for part in parts:
        chosen = str(per_part.get(part["id"]) or orientation)
        rows.append(await asyncio.to_thread(_plan_part, part, chosen if chosen in ORIENTATIONS else orientation, slicer, session_id))
    source = "slicer" if rows and all(row["source"] == "slicer" for row in rows) else "estimate"
    totals = {
        "parts": sum(row["qty"] for row in rows),
        "time_min": round(sum(row["time_min"] * row["qty"] for row in rows), 0),
        "filament_g": round(sum(row["filament_g"] * row["qty"] for row in rows), 1),
        "cost_eur": round(sum(row["cost_eur"] * row["qty"] for row in rows), 2),
        "warnings": sum(len(row["warnings"]) for row in rows),
    }
    plan = {
        "source": source,
        "slicer": slicer[0] if slicer and source == "slicer" else "",
        "profile": {**PROFILE, "bed_mm": list(BED_MM)},
        "parts": rows,
        "totals": totals,
    }
    ctx.state.print_plan = plan
    await ctx.emit({"type": "print", **plan})
    bom = ctx.state.bom
    if bom is not None:
        # The bill of materials gets one filament line, replaced on every new plan.
        items = [item for item in bom["items"] if item.get("category") != "filament"]
        line = filament_line(plan)
        if any(item.get("shop") == "printed" for item in items):
            # Printed part lines already carry their material cost; this line only shows the grams.
            line["name"] += ", cost in the printed part lines"
        else:
            # The drone buys its carbon frame: the printed frame is an optional test print, kept out of the total.
            line["name"] += f", {line['unit_price_eur']:.2f} € optional test print"
        line["unit_price_eur"] = 0.0
        items.append(line)
        bom["items"] = items
        bom["total_eur"] = round(sum(item["unit_price_eur"] * item["qty"] for item in items), 2)
        await ctx.emit({"type": "bom", **bom})
    label = "slicer " + plan["slicer"] if source == "slicer" else "estimate, no slicer installed"
    detail = (
        f"{totals['parts']} printed part{'s' if totals['parts'] != 1 else ''}, {totals['time_min']:.0f} min, "
        f"{totals['filament_g']:.0f} g, {totals['cost_eur']:.2f} €, {totals['warnings']} warning{'s' if totals['warnings'] != 1 else ''} ({label})"
    )
    return {"ok": True, "detail": detail, **plan}
