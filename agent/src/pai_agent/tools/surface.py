"""`surface_check`: where each printed part hangs over, where its walls are thin and where it sits too close
to another part, as numbers with places for Mechanic and as a colour map over the model in the studio.

It checks the build as it stands, from the GLB the Model tab shows (`tools/view.py` finds it): every printed
body in the pose print_prep prints it in (its plan, else as modelled), against every other printed or bought
part of the build; loads the product carries and standard parts in their holes are no part to keep clear of.
`pai_agent.surface_checks` does the work in its own process; identical inputs reuse the earlier result
(`cache.py`). Mechanic gets per part and check the range, the area that needs a fix and the largest critical
spots with their size and position in the build's frame; the studio gets the `analysis` event with
`analysis.glb`, the sampled surfaces with each check's value on every triangle.

The limits follow the user's printer: overhang past print_prep's 45 degrees, walls under two extrusion lines
of its nozzle, gaps under one nozzle width (0.88 and 0.4 mm on a 0.4 mm nozzle). print_prep runs the checks in
the poses it plans, for the real wall thickness and a better print direction; a change of the geometry
(cad_update, a slider, cad_frame) runs the last check again with its arguments (`refresh_surface`).
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from pai_agent import cache, surface_checks, view_render
from pai_agent.context import Ctx

CHECKS = surface_checks.CHECKS
LABELS = {"overhang": "Overhang", "thickness": "Wall thickness", "clearance": "Clearance"}
FILE = "analysis.glb"
TIMEOUT_S = 150
FINDING_MM2 = surface_checks.FINDING_MM2
# The arguments that change a limit, and the check each one belongs to.
LIMIT_ARGS = {"overhang_deg": "overhang", "min_wall_mm": "thickness", "min_gap_mm": "clearance"}
_CODE = (Path(surface_checks.__file__), Path(view_render.__file__))
_LOCK = asyncio.Lock()

SCHEMA = {
    "name": "surface_check",
    "description": (
        "Checks the surface of every printed part where it matters for printing and fit, with a value on every spot: "
        "overhang (faces that hang over more than 45 degrees in the print pose need support; also names a print direction with clearly less), "
        "thickness (walls thinner than two lines of the printer's nozzle, 0.88 mm on a 0.4 mm nozzle, print badly or not at all) and "
        "clearance (gaps to the other parts under one nozzle width fit only by force or fuse when printed together; negative where parts overlap; "
        "faces that touch are fine). Returns per part and check the range, the critical area, the worst value and where it is, and the largest "
        "critical spots with area, size and position in mm in the build's frame (Z up), so you can fix exactly that place: a thicker wall or a "
        "wider hole with cad_update, a part moved with assemble placements, another pose with print_prep orientations. The studio shows each check "
        "as a colour map over the model. part_ids limits it to some printed parts, checks to some checks; overhang_deg, min_wall_mm and min_gap_mm "
        "change the limits. print_prep runs it too."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "part_ids": {"type": "array", "items": {"type": "string"}, "description": "Printed part ids (or names) to check; all printed parts when left out."},
            "checks": {"type": "array", "items": {"type": "string", "enum": list(CHECKS)}},
            "overhang_deg": {"type": "number", "minimum": 10, "maximum": 80},
            "min_wall_mm": {"type": "number", "minimum": 0.1, "maximum": 10},
            "min_gap_mm": {"type": "number", "minimum": 0.05, "maximum": 5},
        },
    },
}


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message[:160]}


def limits_for(overrides: dict | None = None) -> dict:
    """Each check's limit on the user's printer (its nozzle, else 0.4 mm), with the arguments' overrides."""

    from pai_agent.tools.print_prep import OVERHANG_DEG, profile

    nozzle = float(profile()["nozzle_mm"])
    limits = {"overhang": OVERHANG_DEG, "thickness": surface_checks.min_wall_mm(nozzle), "clearance": surface_checks.min_gap_mm(nozzle)}
    for key, check in LIMIT_ARGS.items():
        if (overrides or {}).get(key) is not None:
            limits[check] = float(overrides[key])
    return limits


def _identities(state, names: list[str]) -> tuple[dict[str, str], dict[str, list[list[float]]]]:
    """For each printed node the part id print_prep plans it under, and the part's own axes in the build's frame."""

    if state.product == "generic" and state.spec and state.assembly:
        from pai_agent.assembly import rotation

        parts = {part["id"]: part for part in state.spec["parts"]}
        ids, frames = {}, {}
        for body in state.assembly.get("bodies", []):
            if body["name"] in names and body["part_id"] in parts:
                ids[body["name"]] = body["part_id"]
                frames[body["name"]] = rotation(parts[body["part_id"]].get("rotation_deg"))
        return ids, frames
    key = "frame" if state.product == "drone" else "body"
    return {name: key for name in names}, {name: np.eye(3).tolist() for name in names}


def _no_neighbours(state) -> set[str]:
    """Nodes that are no other part to keep clear of: a load the product carries (the phone on a stand) is a
    block drawn where it rests, and a standard part sits in a hole made for it (a tap hole or an insert holds
    it in the plastic on purpose), whose fit the FreeCAD harness checks (pai_agent/fasteners/hardware.py)."""

    if state.product == "generic":
        return {body["name"] for body in (state.assembly or {}).get("bodies", []) if body.get("kind") in ("external", "hardware")}
    return {str(row.get("name")) for row in (state.part or {}).get("hardware") or []}


def _sizes(state, part_ids: set[str]) -> dict[str, list[float]]:
    """Each printed part's size in its own frame, which decides what print_prep's flat and upright mean."""

    from pai_agent.paths import REPO_ROOT
    from pai_agent.tools.print_prep import read_stl

    if state.product == "generic":
        return {pid: [box[i + 3] - box[i] for i in range(3)] for pid in part_ids if (box := (state.built.get(pid) or {}).get("bbox_mm"))}
    stl = REPO_ROOT / state.stl_path if state.stl_path else None
    if stl is None or not stl.is_file():
        return {}
    size = np.ptp(read_stl(stl).reshape(-1, 3), axis=0).tolist()
    return {pid: size for pid in part_ids}


def pose_of(axis: str, size: list[float] | None) -> str | None:
    """print_prep's pose that prints with this axis of the part up, if one does."""

    if not size or not axis.startswith("+"):
        return None
    index = "xyz".index(axis[1])
    if index == int(np.argmin(size)):
        return "flat"
    if index == int(np.argmax(size)):
        return "upright"
    return "as_modeled" if index == 2 else None


def _run(job: dict) -> dict:
    """surface_checks in its own process; returns its JSON line."""

    with tempfile.TemporaryDirectory(prefix="pai-surface-") as work:
        path = Path(work) / "job.json"
        path.write_text(json.dumps(job), encoding="utf-8")
        completed = subprocess.run([sys.executable, "-m", "pai_agent.surface_checks", str(path)], capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    if not lines:
        tail = (completed.stderr or completed.stdout or "no output").strip().splitlines()
        raise RuntimeError("the checker stopped: " + (tail[-1] if tail else "no output")[:300])
    return json.loads(lines[-1])


area = surface_checks.area_text


def finding_mm2(summary: dict | None) -> float:
    """The area of a check that needs a fix: without the specks, the tapers of sharp edges and the wedges where
    parts meet at an angle (surface_checks.spots)."""

    return float((summary or {}).get("finding_mm2", 0.0))


def _findings(part: dict, limits: dict) -> list[str]:
    """What one part's checks found, a few words each."""

    out = []
    hang = part.get("overhang")
    if hang and hang["critical_mm2"] >= FINDING_MM2:
        out.append(f"{area(hang['critical_mm2'])} overhang past {limits['overhang']:g}°")
    wall = part.get("thickness")
    if wall and finding_mm2(wall) >= FINDING_MM2:
        out.append(f"walls under {limits['thickness']:g} mm on {area(finding_mm2(wall))}, down to {wall['worst']['value']:.2f} mm")
    gap = part.get("clearance")
    if gap and finding_mm2(gap) >= FINDING_MM2:
        worst = gap["worst"]
        other = worst.get("with") or next((spot["with"] for spot in gap["spots"] if spot.get("with")), None)
        if worst["value"] < 0:
            out.append(f"overlaps {other or 'another part'} on {area(finding_mm2(gap))}, by up to {-worst['value']:.2f} mm")
        else:
            out.append(f"gaps under {limits['clearance']:g} mm" + (f" to {other}" if other else "") + f" on {area(finding_mm2(gap))}, down to {worst['value']:.2f} mm")
    return out


def passes(part: dict) -> bool:
    """A part passes when no wall is too thin and no gap too tight; an overhang only needs support."""

    return finding_mm2(part.get("thickness")) < FINDING_MM2 and finding_mm2(part.get("clearance")) < FINDING_MM2


def _by_part(parts: list[dict], sizes: dict[str, list[float]]) -> dict[str, dict]:
    """Per printed part id what print_prep needs: the thinnest wall and where, the thin area, and a better
    print direction. A part of several bodies prints them in one pose, so their overhangs add up."""

    out: dict[str, dict] = {}
    for part in parts:
        row = out.setdefault(part["part_id"], {"min_wall_mm": None, "wall_at_mm": None, "thin_mm2": 0.0, "overhang_mm2": 0.0, "by_axis_mm2": {}})
        wall = part.get("thickness")
        if wall:
            if finding_mm2(wall) >= FINDING_MM2:
                row["thin_mm2"] += finding_mm2(wall)
            if wall.get("worst") and (row["min_wall_mm"] is None or wall["worst"]["value"] < row["min_wall_mm"]):
                row["min_wall_mm"], row["wall_at_mm"] = wall["worst"]["value"], wall["worst"]["at_mm"]
        hang = part.get("overhang")
        if hang:
            row["overhang_mm2"] += hang["critical_mm2"]
            for axis, mm2 in hang.get("by_axis_mm2", {}).items():
                row["by_axis_mm2"][axis] = row["by_axis_mm2"].get(axis, 0.0) + mm2
    for part_id, row in out.items():
        row["better"] = None
        if row["by_axis_mm2"]:
            axis = min(row["by_axis_mm2"], key=lambda name: (round(row["by_axis_mm2"][name], 1), surface_checks.AXES.index(name)))
            least = row["by_axis_mm2"][axis]
            if least <= 0.5 * row["overhang_mm2"] and row["overhang_mm2"] - least >= surface_checks.BETTER_MM2:
                row["better"] = {"axis": axis, "critical_mm2": round(least, 1), "pose": pose_of(axis, sizes.get(part_id))}
    return out


async def run(ctx: Ctx, checks: tuple[str, ...] = CHECKS, part_ids: list[str] | None = None, limits: dict | None = None, orientations: dict[str, str] | None = None, source: str = "surface_check", args: dict | None = None) -> tuple[dict, dict[str, dict]]:
    """Checks the build as it stands and emits `analysis`; returns the event and the summary per printed part id.

    Raises ValueError when there is nothing to check, RuntimeError or subprocess.TimeoutExpired when the checker fails.
    `args` are kept for `refresh_surface`."""

    from pai_agent.tools.view import _print_poses, _source

    state = ctx.state
    limits = {**limits_for(), **(limits or {})}
    found = await _source(ctx)
    nodes = view_render.mesh_nodes(found["document"])
    ups, poses = _print_poses(state, [node["name"] for node in nodes], orientations)
    ids, frames = _identities(state, list(ups))
    apart = _no_neighbours(state)
    wanted = {str(v).strip() for v in part_ids or [] if str(v).strip()}
    chosen = [name for name in ups if not wanted or ids.get(name) in wanted or name in wanted]
    if not chosen:
        if not ups:
            raise ValueError("The build has no printed part to check.")
        raise ValueError("None of " + ", ".join(sorted(wanted)) + " is a printed part. Printed: " + ", ".join(sorted({ids.get(name, name) for name in ups})) + ".")
    job = {
        "glb": str(found["glb"]),
        "axes": found["axes"],
        "bodies": [
            {
                "node": node["index"],
                "name": node["name"],
                "part_id": ids.get(node["name"]),
                "analyse": node["name"] in chosen,
                "neighbour": node["name"] not in apart,
                "up": ups.get(node["name"]),
                "frame": frames.get(node["name"]),
            }
            for node in nodes
        ],
        "checks": [check for check in CHECKS if check in checks],
        "limits": {check: limits[check] for check in CHECKS if check in checks},
        "samples": surface_checks.SAMPLES,
    }
    out = Path(state.directory) / FILE
    entry = cache.key("surface", cache.digest(found["glb"]), job, [cache.digest(path) for path in _CODE])
    async with _LOCK:  # one checker at a time: its rays keep a core busy
        result = cache.restore("surfaces", entry, {FILE: out})
        if result is None:
            result = await asyncio.to_thread(_run, {**job, "out": str(out)})
            if result.get("ok"):
                cache.store("surfaces", entry, {FILE: out}, result)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "the checker failed"))
    sizes = _sizes(state, {ids[name] for name in chosen if name in ids})
    parts = []
    for body in result["bodies"]:
        row = {"node": body["name"], "part_id": body["part_id"], "name": body["name"], "pose": poses.get(body["name"], "as modelled")}
        row.update({key: value for key, value in body.items() if key not in row})
        if (row.get("overhang") or {}).get("better"):
            row["overhang"]["better"]["pose"] = pose_of(row["overhang"]["better"]["axis"], sizes.get(body["part_id"]))
        parts.append(row)
    runs = (state.surface or {}).get("runs", 0) + 1
    found_lines = [part["name"] + ": " + "; ".join(lines) for part in parts if (lines := _findings(part, limits))]
    summary = ". ".join(found_lines) if found_lines else ", ".join(part["name"] for part in parts) + ": nothing critical"
    event = {
        "type": "analysis",
        "source": source,
        "build": state.cad_builds,
        "glb_url": "/files/" + state.session_id + "/" + FILE + "?build=" + str(state.cad_builds) + "-" + str(runs),
        "frame": found["frame"],
        "checks": {name: {**row, "label": LABELS[name]} for name, row in result["checks"].items()},
        "parts": parts,
        "result": "pass" if all(passes(part) for part in parts) else "fail",
        "summary": summary,
        "seconds": result.get("seconds"),
    }
    state.surface = {"args": dict(args or {}), "source": source, "product": state.product, "build": state.cad_builds, "runs": runs, "limits": job["limits"], "parts": parts}
    await ctx.emit(event)
    return event, _by_part(parts, sizes)


def _hint(parts: list[dict], limits: dict) -> str | None:
    lines = []
    if any(finding_mm2(part.get("thickness")) >= FINDING_MM2 for part in parts):
        lines.append(f"Thicken the thin walls at the spots listed to at least {limits['thickness']:g} mm (cad_update with the part's wall or thickness parameter).")
    tight = [part["clearance"] for part in parts if finding_mm2(part.get("clearance")) >= FINDING_MM2]
    if any(gap["worst"]["value"] < 0 for gap in tight):
        lines.append("Parts overlap where the clearance is negative: move them apart with assemble placements or cut the overlap in the script.")
    elif tight:
        lines.append(f"Open the tight gaps to at least {limits['clearance']:g} mm (a wider hole or slot with cad_update, or move the part with assemble placements).")
    better = next((part for part in parts if (part.get("overhang") or {}).get("better")), None)
    if better is not None:
        move = better["overhang"]["better"]
        how = "print_prep orientations " + json.dumps({better["part_id"]: move["pose"]}) if move.get("pose") else "no print_prep pose does that yet, so say it to the user"
        left = area(move["critical_mm2"]) if move["critical_mm2"] >= FINDING_MM2 else "none"
        lines.append(f"{better['name']} needs much less support with {move['axis'].upper()} up ({left} left): {how}.")
    return " ".join(lines) or None


async def surface_check(ctx: Ctx, args: dict) -> dict:
    checks = args.get("checks") or list(CHECKS)
    if isinstance(checks, str):
        checks = [checks]
    if not isinstance(checks, list) or any(check not in CHECKS for check in checks):
        return _fail("checks must be a list of " + ", ".join(CHECKS) + ".")
    part_ids = args.get("part_ids")
    if isinstance(part_ids, str):
        part_ids = [part_ids]
    if part_ids is not None and (not isinstance(part_ids, list) or not all(isinstance(v, str) for v in part_ids)):
        return _fail("part_ids must be a list of printed part ids.")
    try:
        overrides = {key: float(args[key]) for key in LIMIT_ARGS if args.get(key) is not None}
    except (TypeError, ValueError):
        return _fail("overhang_deg, min_wall_mm and min_gap_mm must be numbers.")
    if any(value <= 0 for value in overrides.values()):
        return _fail("The limits must be positive.")
    limits = limits_for(overrides)
    try:
        event, _ = await run(ctx, tuple(checks), part_ids, limits, args=args)
    except ValueError as exc:
        return _fail(str(exc))
    except subprocess.TimeoutExpired:
        return _fail(f"The surface check took longer than {TIMEOUT_S} s.")
    except (OSError, RuntimeError) as exc:
        return _fail("The surface check failed: " + str(exc))
    out = {
        "ok": True,
        "detail": event["summary"],
        "result": event["result"],
        "frame": event["frame"],
        "limits": {key: limits[check] for key, check in LIMIT_ARGS.items() if check in checks},
        "parts": [{key: value for key, value in part.items() if key != "node"} for part in event["parts"]],
    }
    hint = _hint(event["parts"], limits)
    if hint:
        out["hint"] = hint
    return out


async def refresh_surface(ctx: Ctx) -> dict | None:
    """Runs the last surface check again on a changed build, with the same arguments; None when there was none.

    Returns {ok, result, detail} as the tool does."""

    entry = ctx.state.surface
    if entry and entry.get("product") != ctx.state.product:
        ctx.state.surface = entry = None  # another product is on the bench now
    if not entry or entry.get("build") == ctx.state.cad_builds:
        return None
    if entry.get("source") != "print_prep":
        return await surface_check(ctx, dict(entry["args"]))
    try:
        event, _ = await run(ctx, source="print_prep")
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return _fail("The surface check failed: " + str(exc))
    return {"ok": True, "result": event["result"], "detail": event["summary"]}
