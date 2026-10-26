"""Print-ready output for every printed part: slicer when installed, else an honest estimate.

PrusaSlicer or OrcaSlicer on this machine slices each STL headless and the G-code is served
for download; the time and filament come from the comments the slicer writes. Without a
slicer the numbers come from the mesh: shell and infill volume at a default profile, an
average volumetric flow and a per-layer overhead, labelled 'estimate', with no G-code.
Printability warnings always come from the mesh itself: overhangs past 45 degrees, walls
thinner than two extrusion lines of the nozzle (0.88 mm on 0.4 mm), and parts that do not fit
a 220 mm bed. The walls are measured by the surface check (`tools/surface.py`), which runs
in the poses planned here, shows its colour map in the studio and names a print direction
with clearly less overhang; without it the designed wall or the part's thinnest side stands in.

With the user's 3D printer set (`pai_agent.printers`) everything follows that printer: its bed
and nozzle in the slicer and the estimate, its typical flow, the bed-fit check against its own
bed, an orientation chosen per part (`auto`: the fitting pose that needs the least support), the
warping risk of the material on that printer (enclosed or open, part length on the bed), a
warning for a material it cannot print, and the cost of each part from the grams and the price
of that filament. The bill of materials then prices printed parts as filament on the user's own
printer; the drone's frame is printed instead of bought.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

from pai_agent import printers, surface_checks
from pai_agent.context import Ctx

log = logging.getLogger(__name__)

BED_MM = (220.0, 220.0, 250.0)
OVERHANG_DEG = 45.0
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
CHOICES = (*ORIENTATIONS, "auto")
_SLICERS = (
    ("PrusaSlicer", ("prusa-slicer", "PrusaSlicer", "prusa-slicer-console"), "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer"),
    ("OrcaSlicer", ("orca-slicer", "OrcaSlicer"), "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"),
)


def profile() -> dict:
    """The print profile: the user's printer when one is set, else the generic 220 mm bed slinger."""

    printer = printers.current()
    if printer is None:
        return {**PROFILE, "bed_mm": list(BED_MM), "flow_mm3_s": FLOW_MM3_S, "enclosure": None, "model": None}
    return {
        "printer": printer["name"],
        "model": printer["model"],
        "nozzle_mm": printer["nozzle_mm"],
        "layer_height_mm": PROFILE["layer_height_mm"],
        "infill_pct": printers.PRINT["infill_pct"],
        "walls": printers.PRINT["walls"],
        "bed_mm": list(printer["bed_mm"]),
        "flow_mm3_s": printer["flow_mm3_s"],
        "enclosure": printer["enclosure"],
        "source_url": printer["source_url"],
    }


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


def filament_price(material: str) -> tuple[float, float]:
    """(g/cm³, €/g) of the material: the user's filament table with a printer set, else the generic spools."""

    if printers.current() is not None and printers.normalise_material(material) in printers.MATERIALS:
        return printers.density(material), printers.eur_per_g(material)
    return FILAMENTS.get(material, FILAMENTS["PETG"])


def estimate(mesh: dict, material: str, prof: dict | None = None) -> dict:
    """Print time and filament from shell plus infill volume at the profile."""

    prof = prof or profile()
    density, eur_per_g = filament_price(material)
    wall = prof["walls"] * prof["nozzle_mm"] * 1.1
    shell = min(mesh["volume_mm3"], mesh["area_mm2"] * wall)
    extruded = shell + (mesh["volume_mm3"] - shell) * prof["infill_pct"] / 100
    # Supports under overhangs: a sparse column 0.15 of the area times half the part height.
    support = mesh["overhang_mm2"] * 0.15 * mesh["size_mm"][2] / 2
    extruded += support
    layers = max(1, math.ceil(mesh["size_mm"][2] / prof["layer_height_mm"]))
    seconds = START_S + extruded / prof["flow_mm3_s"] + layers * LAYER_OVERHEAD_S
    grams = extruded * density / 1000
    return {
        "time_min": round(seconds / 60, 0),
        "filament_g": round(grams, 1),
        "filament_m": round(extruded / (math.pi * (FILAMENT_DIAMETER_MM / 2) ** 2) / 1000, 2),
        "cost_eur": round(grams * eur_per_g, 2),
        "support_g": round(support * density / 1000, 1),
    }


def fits(mesh: dict, bed: list[float]) -> bool:
    x, y, z = mesh["size_mm"]
    return max(x, y) <= max(bed[0], bed[1]) and min(x, y) <= min(bed[0], bed[1]) and z <= bed[2]


def warnings_for(mesh: dict, min_wall_mm: float | None, material: str | None = None, prof: dict | None = None, measured: dict | None = None) -> list[dict]:
    """The part's printability warnings. `measured` is its surface check (`tools/surface.py`): the real walls
    then stand in for the designed wall and the part's thinnest side, and it may name a better print direction."""

    out = []
    prof = prof or profile()
    if mesh["overhang_mm2"] > surface_checks.FINDING_MM2:
        fix = "needs supports or another orientation"
        better = (measured or {}).get("better")
        if better:
            how = f"{better['pose']} ({better['axis'].upper()} up)" if better.get("pose") else f"with {better['axis'].upper()} up"
            left = surface_checks.area_text(better["critical_mm2"]) if better["critical_mm2"] >= surface_checks.FINDING_MM2 else "none"
            fix = f"needs supports, or print it {how}: {left} left"
        out.append({"kind": "overhang", "text": f"{mesh['overhang_mm2'] / 100:.1f} cm² hangs over more than {OVERHANG_DEG:.0f}°, up to {mesh['overhang_max_deg']:.0f}°: {fix}"})
    nozzle = float(prof["nozzle_mm"])
    limit, line = surface_checks.min_wall_mm(nozzle), round(surface_checks.LINE * nozzle, 2)
    if measured and measured.get("min_wall_mm") is not None:
        if measured["thin_mm2"] >= surface_checks.FINDING_MM2:
            at = ", ".join(f"{v:.1f}" for v in measured["wall_at_mm"])
            out.append(
                {
                    "kind": "thin_wall",
                    "text": f"Walls under {limit:g} mm on {surface_checks.area_text(measured['thin_mm2'])}, down to {measured['min_wall_mm']:.2f} mm at ({at}) mm: two {line:g} mm lines of the {nozzle:g} mm nozzle do not fit",
                }
            )
    else:
        thinnest = min([v for v in mesh["size_mm"] if v > 0] or [0.0])
        wall = min(v for v in (min_wall_mm, thinnest) if v is not None) if (min_wall_mm is not None or thinnest) else None
        if wall is not None and wall < limit:
            out.append({"kind": "thin_wall", "text": f"Wall {wall:.2f} mm is thinner than {limit:g} mm: two {line:g} mm lines of the {nozzle:g} mm nozzle do not fit"})
    x, y, z = mesh["size_mm"]
    bed = prof["bed_mm"]
    if not fits(mesh, bed):
        where = f"the {prof['printer']} bed ({bed[0]:g} × {bed[1]:g} × {bed[2]:g} mm)" if prof.get("model") else f"a {bed[0]:.0f} mm bed"
        out.append({"kind": "bed_size", "text": f"{x:.0f} × {y:.0f} × {z:.0f} mm does not fit {where}: split it or rotate it"})
    printer = printers.current()
    key = printers.normalise_material(material) if material else None
    if printer is not None and key in printers.MATERIALS:
        if key not in printer["materials"]:
            why = "it has no enclosure" if key in printers.NEEDS_ENCLOSURE and not printer["enclosure"] else "it is not on its material list"
            out.append({"kind": "material", "text": f"The {printer['name']} cannot print {key}: {why}"})
        elif key not in printer["filaments"]:
            out.append({"kind": "material", "text": f"{key} is not among your filaments: load a spool before printing"})
        risk = printers.warp_risk(key, printer, (x, y))
        if risk["level"] != "low":
            out.append({"kind": "warp", "text": f"{risk['level'].capitalize()} warping risk: {risk['text']}" + ("; use a brim" if risk["level"] == "medium" else "; use a brim and a draft shield, or split it")})
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


def _slice(slicer: tuple[str, str], stl: Path, gcode: Path, rotation: list[float], material: str, prof: dict | None = None) -> dict:
    name, executable = slicer
    prof = prof or profile()
    bed = prof["bed_mm"]
    if name == "PrusaSlicer":
        kind = {"TPU": "FLEX", "PETG-CF": "PETG"}.get(material, material)
        command = [
            executable,
            "--export-gcode",
            "--layer-height", str(prof["layer_height_mm"]),
            "--fill-density", f"{prof['infill_pct']}%",
            "--perimeters", str(prof["walls"]),
            "--nozzle-diameter", str(prof["nozzle_mm"]),
            "--filament-type", kind if kind in {"PLA", "PETG", "ABS", "ASA", "FLEX", "NYLON"} else "PETG",
            "--bed-shape", f"0x0,{bed[0]:g}x0,{bed[0]:g}x{bed[1]:g},0x{bed[1]:g}",
            "--max-print-height", f"{bed[2]:g}",
            "--center", f"{bed[0] / 2:g},{bed[1] / 2:g}",
            "--support-material",
            "--support-material-threshold", f"{90 - OVERHANG_DEG:g}",
        ]
        entry = printers.MATERIALS.get(printers.normalise_material(material))
        if prof.get("model") and entry:
            command += ["--temperature", str(entry["nozzle_c"]), "--bed-temperature", str(entry["bed_c"])]
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
        chosen = state.print_materials.get("frame") if printers.current() else None
        parts.append(
            {
                "id": "frame",
                "name": "Frame" if chosen else "Frame prototype",
                "material": chosen["material"] if chosen else "PETG-CF",
                "qty": 1,
                "stl": REPO_ROOT / state.stl_path,
                "min_wall_mm": float(thickness) if thickness is not None else None,
            }
        )
    return [p for p in parts if Path(p["stl"]).is_file()]


def best_orientation(raw: np.ndarray, bed: list[float]) -> str:
    """The pose that fits the bed and needs the least support; flat wins a tie (more bed contact, less warping)."""

    scored = []
    for rank, orientation in enumerate(("flat", "as_modeled", "upright")):
        mesh = analyse(orient(raw, orientation)[0])
        scored.append((not fits(mesh, bed), round(mesh["overhang_mm2"], -1), rank, orientation))
    return min(scored)[3]


def _plan_part(part: dict, orientation: str, slicer: tuple[str, str] | None, session_id: str, prof: dict | None = None, measured: dict | None = None) -> dict:
    prof = prof or profile()
    stl = Path(part["stl"])
    raw = read_stl(stl)
    if orientation == "auto":
        orientation = best_orientation(raw, prof["bed_mm"])
    tris, rotation = orient(raw, orientation)
    mesh = analyse(tris)
    row = {
        "id": part["id"],
        "name": part["name"],
        "material": part["material"],
        "qty": part["qty"],
        "orientation": orientation,
        "size_mm": mesh["size_mm"],
        "volume_cm3": round(mesh["volume_mm3"] / 1000, 2),
        "warnings": warnings_for(mesh, part["min_wall_mm"], part["material"], prof, measured),
        "wall_mm": (measured or {}).get("min_wall_mm"),
        "better_up": ((measured or {}).get("better") or {}).get("axis"),
        "supports": mesh["overhang_mm2"] > surface_checks.FINDING_MM2,
        "stl_url": "/files/" + session_id + "/" + stl.name if stl.parent.name == session_id else "",
        "gcode_url": "",
        "source": "estimate",
        **estimate(mesh, part["material"], prof),
    }
    if slicer is not None:
        gcode = stl.with_name("print-" + part["id"] + ".gcode")
        try:
            sliced = _slice(slicer, stl, gcode, rotation, part["material"], prof)
            eur_per_g = filament_price(part["material"])[1]
            row.update({k: v for k, v in sliced.items() if v})
            row["cost_eur"] = round(row["filament_g"] * eur_per_g, 2)
            row["gcode_url"] = "/files/" + session_id + "/" + gcode.name
            row["source"] = "slicer"
        except Exception as exc:  # The estimate stays; the row says why the slicer did not help.
            row["slicer_error"] = str(exc)
    return row


async def _measure(ctx: Ctx, poses: dict[str, str]) -> dict[str, dict]:
    """The surface check in these poses, per printed part id; empty when it cannot run, and the plan goes on without it."""

    from pai_agent.tools.surface import run

    try:
        return (await run(ctx, orientations=poses, source="print_prep"))[1]
    except Exception as exc:  # noqa: BLE001 - the designed walls and the part's size stand in
        log.warning("The surface check for print_prep failed: %s", exc)
        return {}


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
    prof = profile()
    printer = printers.current()
    # On the user's own printer each part gets the pose that fits and needs the least support.
    fallback = "auto" if printer else "flat"
    orientation = str(args.get("orientation") or fallback)
    if orientation not in CHOICES:
        orientation = fallback
    per_part = args.get("orientations") if isinstance(args.get("orientations"), dict) else {}
    parts = printed_parts(ctx)
    if not parts:
        message = "No printed part with an STL yet: build the CAD first."
        return {"ok": False, "error": message, "detail": message}
    slicer = find_slicer()
    session_id = ctx.state.session_id
    # Each part's pose first: the surface check measures the parts the way they will be printed.
    poses = {}
    for part in parts:
        chosen = str(per_part.get(part["id"]) or orientation)
        chosen = chosen if chosen in CHOICES else orientation
        if chosen == "auto":
            chosen = await asyncio.to_thread(lambda stl=Path(part["stl"]): best_orientation(read_stl(stl), prof["bed_mm"]))
        poses[part["id"]] = chosen
    measured = await _measure(ctx, poses)
    rows = []
    for part in parts:
        rows.append(await asyncio.to_thread(_plan_part, part, poses[part["id"]], slicer, session_id, prof, measured.get(part["id"])))
    source = "slicer" if rows and all(row["source"] == "slicer" for row in rows) else "estimate"
    totals = {
        "parts": sum(row["qty"] for row in rows),
        "time_min": round(sum(row["time_min"] * row["qty"] for row in rows), 0),
        "filament_g": round(sum(row["filament_g"] * row["qty"] for row in rows), 1),
        "cost_eur": round(sum(row["cost_eur"] * row["qty"] for row in rows), 2),
        "warnings": sum(len(row["warnings"]) for row in rows),
        "support_g": round(sum(row.get("support_g", 0.0) * row["qty"] for row in rows), 1),
    }
    plan = {
        "source": source,
        "slicer": slicer[0] if slicer and source == "slicer" else "",
        "profile": {k: v for k, v in prof.items() if k != "flow_mm3_s"},
        "printer": printer["name"] if printer else None,
        "parts": rows,
        "totals": totals,
    }
    ctx.state.print_plan = plan
    await ctx.emit({"type": "print", **plan})
    bom = ctx.state.bom
    if bom is not None:
        # The bill of materials gets one filament line, replaced on every new plan.
        items = [item for item in bom["items"] if item.get("category") != "filament"]
        if printer:
            # On the user's printer each printed line costs the grams this plan prints (supports included).
            by_id = {row["id"]: row for row in rows}
            for item in items:
                row = by_id.get(item.get("category")) if item.get("shop") == "printed" else None
                if row is not None:
                    item["unit_price_eur"] = row["cost_eur"]
                    item["name"] = printers.printed_line_name(row["name"], row["material"]) + f", {row['filament_g']:.0f} g"
                    item["price_source"] = "printer"
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
        if printer:
            from pai_agent.tools.bom import _sync_metrics

            await _sync_metrics(ctx, bom["total_eur"])
    label = "slicer " + plan["slicer"] if source == "slicer" else "estimate, no slicer installed"
    if printer:
        label += ", " + printer["name"]
    detail = (
        f"{totals['parts']} printed part{'s' if totals['parts'] != 1 else ''}, {totals['time_min']:.0f} min, "
        f"{totals['filament_g']:.0f} g, {totals['cost_eur']:.2f} €, {totals['warnings']} warning{'s' if totals['warnings'] != 1 else ''} ({label})"
    )
    return {"ok": True, "detail": detail, **plan}
