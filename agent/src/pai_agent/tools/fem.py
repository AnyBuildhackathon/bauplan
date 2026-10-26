"""Printed parts on the user's printer: the material per part, and FEM on each part's real shape.

`material_pick` chooses the material of one printed part from what it must survive (heat, sun,
crashes, bending on purpose), only among the filaments the user's printer prints
(`pai_agent.printers`), and says why in one sentence. The part's mass follows the new density.

`fem_check` meshes the printed part's STEP and solves it in CalculiX (`pai_agent.fem`) under its
real loads, derived from the spec when the call names none:
- any product: the part is held where it rests (its lowest face), and each external load near it
  (the phone, the water, the pot) presses at its own position with twice its weight, as when it is
  set down; without one nearby, a 10 N press on its top; every case adds the part's own weight;
- the drone frame: held at the centre stack, all four motors at full thrust, and a crash that lands
  on one motor at `CRASH_G` times the drone's weight.
Mechanic's own cases may spread a force or a pressure over the part's CAD faces (`face_id`, the
faces a `near` patch touched are named in the result) and add its weight with `gravity_g`.
The printed modulus and strengths follow the infill, the walls and the print direction. The result
is stored like every check (state.checks, key fem:<part>), judges the `strength` requirement (a
minimum safety factor, proposed at 2x when the user set none), reruns after cad_update, and its
stress-coloured model goes to the Simulation tab as a `fem` event. It carries the FEM's self-checks:
a part that is not held fails with the free motion named, the reactions balance the loads, and a
peak that moves by more than 15 % with smaller elements round it comes with a note.
"""

from __future__ import annotations

import asyncio
import math
import shutil
from pathlib import Path

import numpy as np

from pai_agent import fem, printers
from pai_agent.analysis import GRAVITY
from pai_agent.assembly import rotation
from pai_agent.context import Ctx
from pai_agent.requirements import attribute
from pai_agent.spec import find_part

MIN_SAFETY = 2.0
# Something set down on the part, or a hand pressing it, meets about twice its weight.
DYNAMIC = 2.0
PRESS_N = 10.0
# A hard landing on one motor, as a multiple of the drone's weight; Mechanic's proposal, not a measurement.
CRASH_G = 10.0
CARBON_G_CM3 = 1.55
NEAR_MM = 40.0
_LOCK = asyncio.Lock()


def _fail(message: str, **extra) -> dict:
    return {"ok": False, "error": message, "detail": message[:160], **extra}


def fem_rows(state, part_id: str | None = None) -> list[dict]:
    return [v for k, v in state.checks.items() if k.startswith("fem:") and part_id in (None, v.get("part_id"))]


def strength_value(state, requirement: dict) -> float | None:
    rows = fem_rows(state, requirement.get("part_id"))
    return min(r["safety"] for r in rows) if rows else None


def _session_dir(state) -> Path:
    return Path(state.directory)


def _frame_material(state) -> str:
    chosen = state.print_materials.get("frame")
    return chosen["material"] if chosen else "PETG"


def _orientation(state, part_id: str) -> str:
    plan = state.print_plan or {}
    row = next((r for r in plan.get("parts", []) if r.get("id") == part_id), None)
    return str(row.get("orientation")) if row else "flat"


def _build_axis(size: list[float], orientation: str) -> np.ndarray:
    axis = 2
    if orientation == "flat":
        axis = int(np.argmin(size))
    elif orientation == "upright":
        axis = int(np.argmax(size))
    vector = np.zeros(3)
    vector[axis] = 1.0
    return vector


def _geometry(state, part_id: str) -> dict:
    """The part's STEP, its transform into the assembly frame, size, thinnest wall, material and print direction."""

    directory = _session_dir(state)
    if state.product == "drone":
        step = directory / "frame.step"
        if not step.is_file():
            raise ValueError("No frame yet: run cad_frame first.")
        thickness = float(state.cad_params.get("thickness_mm") or 2.0)
        arm = float(state.cad_params.get("arm_length_mm") or 42.5)
        return {
            "part_id": "frame",
            "name": "Frame",
            "step": step,
            "transform": None,
            "size_mm": [2 * arm + 20, 2 * arm + 20, thickness],
            "min_wall_mm": thickness,
            "material": _frame_material(state),
            "direction": np.array([0.0, 0.0, 1.0]),
            "bbox": None,
        }
    spec = state.spec
    if state.product != "generic" or not spec:
        raise ValueError("fem_check works on a product spec's printed parts or the drone frame.")
    part = find_part(spec, part_id, "printed")
    if part is None:
        raise ValueError("part_id must be a printed part. Printed: " + ", ".join(p["id"] for p in spec["parts"] if p["kind"] == "printed") + ".")
    info = state.built.get(part["id"])
    if info is None:
        raise ValueError(part["name"] + " is not built yet: cad_part first.")
    step = directory / ("part-" + part["id"] + ".step")
    if not step.is_file():
        step = directory / ("part-" + part["id"] + ".stl")
    if info.get("fallback"):
        raise ValueError(part["name"] + " is only a simplified block; FEM on it would mean nothing. Rebuild it with cad_part first.")
    box = info["bbox_mm"]
    size = [box[i + 3] - box[i] for i in range(3)]
    matrix = rotation(part.get("rotation_deg"))
    center = [(box[i] + box[i + 3]) / 2.0 for i in range(3)]
    target = part.get("position_mm") or center
    offset = [target[i] - sum(matrix[i][j] * center[j] for j in range(3)) for i in range(3)]
    walls = [float(v) for k, v in (info.get("params") or {}).items() if "thick" in k or "wall" in k]
    direction = np.array(matrix) @ _build_axis(size, _orientation(state, part["id"]))
    corners = np.array([[x, y, z] for x in (box[0], box[3]) for y in (box[1], box[4]) for z in (box[2], box[5])])
    placed = corners @ np.array(matrix).T + np.array(offset)
    return {
        "part_id": part["id"],
        "name": part["name"],
        "step": step,
        "transform": (matrix, offset),
        "size_mm": size,
        "min_wall_mm": min(walls) if walls else None,
        "material": str(info["material"]),
        "direction": direction,
        "bbox": [*placed.min(axis=0).tolist(), *placed.max(axis=0).tolist()],
    }


def _distance_to_box(point: list[float], box: list[float]) -> float:
    return math.dist(point, [min(max(point[i], box[i]), box[i + 3]) for i in range(3)])


def default_loads(state, geo: dict) -> tuple[dict, list[dict], list[str]]:
    """The clamp and the load cases from the spec, with one line each on where they come from."""

    if state.product == "drone":
        arm = float(state.cad_params.get("arm_length_mm") or 42.5)
        thickness = float(state.cad_params.get("thickness_mm") or 2.0)
        motor = state.selected.get("motor") or {}
        thrust_n = float(motor.get("thrust_g") or 0.0) / 1000.0 * GRAVITY
        mass_g = float(state.metrics.get("weight_g") or 0.0)
        if not mass_g:
            from pai_agent.tools.physics import compute

            try:
                mass_g = float(compute(state)["weight_g"])
            except Exception:  # noqa: BLE001 - parts missing; the crash case then uses the frame alone
                mass_g = float(state.frame_mass_g or 10.0)
        d = arm / math.sqrt(2.0)
        motors = [[sx * d, sy * d, thickness / 2] for sx in (1, -1) for sy in (1, -1)]
        pad = max(3.0, float(state.cad_params.get("motor_spacing_mm") or 6.6) * 0.75)
        crash_n = CRASH_G * mass_g / 1000.0 * GRAVITY
        fixed = {"near": [0.0, 0.0, thickness / 2], "radius_mm": max(8.0, arm * 0.3)}
        cases = []
        notes = [f"Held at the flight stack, {fixed['radius_mm']:.0f} mm round the centre."]
        if thrust_n > 0:
            cases.append({"name": "full thrust", "loads": [{"region": {"near": m, "radius_mm": pad}, "force_n": [0, 0, thrust_n]} for m in motors]})
            notes.append(f"Full thrust: {motor.get('name', 'the motor')} pulls {thrust_n:.2f} N at each of the four motor mounts.")
        cases.append({"name": "crash on one motor", "loads": [{"region": {"near": motors[0], "radius_mm": pad}, "force_n": [0, 0, crash_n]}]})
        notes.append(f"Crash: lands on one motor at {CRASH_G:g} g, {crash_n:.1f} N for {mass_g:.0f} g (proposed by Mechanic).")
        return fixed, cases, notes
    fixed = {"face": "z_min"}
    notes = [geo["name"] + " is held where it rests, on its lowest face."]
    cases = []
    for part in state.spec["parts"]:
        if part["kind"] != "external" or not part.get("mass_g") or not part.get("position_mm"):
            continue
        if geo["bbox"] is not None and _distance_to_box(part["position_mm"], geo["bbox"]) > NEAR_MM:
            continue
        force = DYNAMIC * float(part["mass_g"]) / 1000.0 * GRAVITY
        cases.append({"name": part["name"].lower() + " set down", "loads": [{"region": {"near": list(part["position_mm"])}, "force_n": [0, 0, -force]}], "gravity_g": 1.0})
        notes.append(f"{part['name']}: {part['mass_g']:.0f} g set down on it, {DYNAMIC:g}x its weight, {force:.1f} N.")
    if not cases:
        cases.append({"name": f"{PRESS_N:g} N press on top", "loads": [{"region": {"face": "z_max"}, "force_n": [0, 0, -PRESS_N]}], "gravity_g": 1.0})
        notes.append(f"No load rests on it: a {PRESS_N:g} N press on its top (proposed by Mechanic).")
    notes.append("Each case adds the part's own weight.")
    return fixed, cases, notes


def _clean_region(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(
            "A region is {face_id: n or [n, ...]} (the part's CAD faces, as a result names them), {face: z_min|z_max|x_min|x_max|y_min|y_max}, "
            "{near: [x, y, z], radius_mm}, or {box: [x0, y0, z0, x1, y1, z1]} in mm."
        )
    if "face_id" in raw:
        ids = raw["face_id"] if isinstance(raw["face_id"], list) else [raw["face_id"]]
        try:
            faces = [int(float(v)) for v in ids if float(v) == int(float(v))]
        except (TypeError, ValueError):
            faces = []
        if not faces or len(faces) != len(ids) or min(faces) < 1:
            raise ValueError("face_id is a face number of the part (1 or more), or a list of them, as a fem_check result names them.")
        return {"face_id": faces}
    if "face" in raw:
        face = str(raw["face"]).lower()
        if face not in {a + "_" + e for a in "xyz" for e in ("min", "max")}:
            raise ValueError("face must be x_min, x_max, y_min, y_max, z_min or z_max.")
        if raw.get("depth_mm") is not None and float(raw["depth_mm"]) <= 0:
            raise ValueError("depth_mm must be more than 0 mm.")
        return {"face": face, **({"depth_mm": float(raw["depth_mm"])} if raw.get("depth_mm") else {})}
    if "near" in raw:
        point = [float(v) for v in raw["near"]]
        if len(point) != 3:
            raise ValueError("near must be three numbers in mm.")
        if raw.get("radius_mm") is not None and float(raw["radius_mm"]) <= 0:
            raise ValueError("radius_mm must be more than 0 mm.")
        return {"near": point, **({"radius_mm": float(raw["radius_mm"])} if raw.get("radius_mm") else {})}
    if "box" in raw:
        box = [float(v) for v in raw["box"]]
        if len(box) != 6:
            raise ValueError("box must be six numbers: x0, y0, z0, x1, y1, z1 in mm.")
        return {"box": box}
    raise ValueError("A region needs face_id, face, near or box.")


def _clean_load(raw: object, where: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(where + " must be an object.")
    region = _clean_region(raw.get("region"))
    if raw.get("pressure_mpa") is not None:
        return {"region": region, "pressure_mpa": float(raw["pressure_mpa"])}
    force = raw.get("force_n")
    if not isinstance(force, list) or len(force) != 3:
        raise ValueError(where + ".force_n must be [fx, fy, fz] in N; Z is up, so a weight is negative Z. Or give pressure_mpa (positive pushes on the face).")
    return {"region": region, "force_n": [float(v) for v in force]}


def _clean_cases(raw: object) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("cases must be a list of {name, region, force_n: [fx, fy, fz]} in N, or {name, loads: [{region, force_n} or {region, pressure_mpa}], gravity_g}.")
    cases = []
    for index, case in enumerate(raw[:4]):
        where = "cases[" + str(index) + "]"
        if not isinstance(case, dict):
            raise ValueError(where + " must be an object.")
        items = case.get("loads")
        if items is not None and not isinstance(items, list):
            raise ValueError(where + ".loads must be a list of {region, force_n} or {region, pressure_mpa}.")
        if items is None and (case.get("region") is not None or case.get("force_n") is not None or case.get("pressure_mpa") is not None):
            items = [case]
        loads = [_clean_load(item, where + (".loads[" + str(i) + "]" if case.get("loads") is not None else "")) for i, item in enumerate((items or [])[:6])]
        gravity = float(case.get("gravity_g") or 0.0)
        if not 0.0 <= gravity <= 100.0:
            raise ValueError(where + ".gravity_g is the part's own weight as a multiple of g, from 0 to 100.")
        if not loads and not gravity:
            raise ValueError(where + " needs a force_n, a pressure_mpa, loads or gravity_g.")
        cases.append({"name": str(case.get("name") or "case " + str(index + 1)), "loads": loads, **({"gravity_g": gravity} if gravity else {})})
    return cases


def _ensure_requirement(ctx: Ctx) -> dict:
    """The strength row: the user's when the spec has one, else proposed by Mechanic at 2x."""

    state = ctx.state
    row = next((r for r in state.requirements if r.get("check") == "strength" or r.get("id") == "strength"), None)
    if row is not None:
        return row
    text = f"Printed parts carry their loads with a safety factor of {MIN_SAFETY:g}"
    reason = "Proposed by Mechanic: printed plastic scatters, so it should hold twice the load it sees."
    row = {"id": "strength", "text": text, "check": "strength", "min": MIN_SAFETY, "unit": "x", "quote": "", "proposed": True, **attribute(state, "", True, reason), "changed_from": None}
    state.requirements.append(row)
    if state.product == "generic" and state.spec is not None:
        state.spec["requirements"].append({k: row[k] for k in ("id", "text", "check", "min", "unit", "quote", "proposed")})
    return row


def _limit(ctx: Ctx, part_id: str) -> float:
    rows = [r for r in ctx.state.requirements if (r.get("check") == "strength" or r.get("id") == "strength") and r.get("part_id") in (None, part_id)]
    return max([float(r.get("min", MIN_SAFETY)) for r in rows] or [MIN_SAFETY])


def _findings(result: dict, limit: float) -> tuple[list[str], str]:
    """The self-check notes worth telling, and the FEM's own checks in one line.

    A peak that moves with the mesh only matters near the limit: when the safety factor from either
    mesh is under twice the limit, more refinement could still turn the verdict; far above it neither does.
    """

    notes = list(result["notes"])
    checks = result["checks"]
    mesh = checks["mesh"]
    line = f"Self-check: held against every motion, the reactions balance the loads to {checks['equilibrium']['error_pct']:.2f} %"
    if mesh.get("change_pct") is None:
        return notes, line + "."
    line += f", the peak moves {abs(mesh['change_pct']):.0f} % with {mesh['element_size_mm']:.2g} mm elements round it"
    if mesh["ok"]:
        return notes, line + "."
    finer = result["safety"] / (1 + mesh["change_pct"] / 100)
    if min(result["safety"], finer) < 2 * limit:
        return notes, line + ", so it depends on the mesh."
    notes.remove(mesh["text"])
    return notes, line + ", but the part is far stronger than it needs either way."


async def fem_check(ctx: Ctx, args: dict) -> dict:
    state = ctx.state
    part_id = str(args.get("part_id") or ("frame" if state.product == "drone" else ""))
    try:
        geo = await asyncio.to_thread(_geometry, state, part_id)
        fixed, cases, notes = default_loads(state, geo)
        # The first note always says where the part is held.
        if args.get("fixed") is not None:
            fixed = _clean_region(args["fixed"])
            notes[0] = "Held at " + ", ".join(f"{k} {v}" for k, v in fixed.items()) + "."
        custom = args.get("cases") is not None
        if custom:
            cases = _clean_cases(args["cases"])
    except ValueError as exc:
        return _fail(str(exc))
    if fem.find_tools() is None:
        return _fail("FEM is offline: gmsh and CalculiX (FreeCAD's FEM tools) are not on this machine. check_deflection gives the beam estimate.")
    printer = printers.current()
    infill = float(args.get("infill_pct") or printers.PRINT["infill_pct"])
    walls = int(args.get("walls") or printers.PRINT["walls"])
    nozzle = float(printer["nozzle_mm"]) if printer else 0.4
    fill = printers.fill_fraction(geo["min_wall_mm"], walls, infill, nozzle)
    try:
        props = printers.printed_properties(geo["material"], fill)
    except KeyError:
        return _fail(geo["name"] + " is " + geo["material"] + ", which is not a printed plastic; FEM here models printed parts.")
    h = fem.mesh_size(geo["size_mm"], geo["min_wall_mm"])
    stem = "fem-" + geo["part_id"]
    n = state.cad_builds
    glb = _session_dir(state) / (stem + ".glb")
    work = _session_dir(state) / ("fem-work-" + geo["part_id"])
    try:
        async with _LOCK:  # one mesher and solver at a time, they are memory hungry
            try:
                result = await asyncio.to_thread(
                    fem.analyse, geo["step"], geo["transform"], props, fixed, cases, geo["direction"].tolist(), work, h, glb, geo["name"],
                )
            finally:
                # The mesh and the CalculiX result files run to megabytes; the coloured GLB keeps what is shown.
                shutil.rmtree(work, ignore_errors=True)
    except fem.FemUnavailable as exc:
        return _fail(str(exc))
    except fem.FemUnheld as exc:
        # No safety factor for a part that would fly away: say what moves, so the hold can be fixed.
        return _fail("FEM on " + geo["name"] + " stopped before solving. " + str(exc), free_motions=exc.motions, hint="Call fem_check again with fixed on the faces that really hold it.")
    except (fem.FemFailed, ValueError, TimeoutError) as exc:
        return _fail("FEM on " + geo["name"] + " failed: " + str(exc))
    except Exception as exc:  # noqa: BLE001 - a solver crash must not end the build
        return _fail("FEM on " + geo["name"] + " failed: " + type(exc).__name__ + ": " + str(exc)[:160])
    # The lines stay short for the Stress pane; the faces each hold and load landed on are in `held` and the cases' `loads`.
    if custom:
        notes = notes[:1] + [c["name"][:1].upper() + c["name"][1:] + f": {math.hypot(*c['force_n']):.1f} N." for c in result["cases"]]
    requirement = _ensure_requirement(ctx)
    limit = _limit(ctx, geo["part_id"])
    outcome = "pass" if result["safety"] >= limit else "fail"
    findings, self_check = _findings(result, limit)
    worst = next(c for c in result["cases"] if c["name"] == result["governing"])
    stored = {
        "part_id": geo["part_id"],
        "part_name": geo["name"],
        "material": props["material"],
        "fill": fill,
        "infill_pct": infill,
        "walls": walls,
        "modulus_mpa": props["modulus_mpa"],
        "strength_mpa": props["strength_mpa"],
        "z_strength_mpa": props["z_strength_mpa"],
        "safety": result["safety"],
        "max_von_mises_mpa": result["max_von_mises_mpa"],
        "max_deflection_mm": result["max_deflection_mm"],
        "governing": result["governing"],
        "governs": worst["governs"],
        "limit": limit,
        "result": outcome,
        "self_check": self_check,
        "notes": findings,
    }
    state.checks["fem:" + geo["part_id"]] = {**stored, "tool": "fem_check", "args": dict(args)}
    session = state.session_id
    await ctx.emit(
        {
            "type": "fem",
            **stored,
            "cases": result["cases"],
            "loads": notes,
            "checks": result["checks"],
            "glb_url": "/files/" + session + "/" + glb.name + "?build=" + str(n) + "-" + str(len(fem_rows(state))),
            "scale_mpa": result["scale_mpa"],
            "nodes": result["nodes"],
            "elements": result["elements"],
            "solver": result["solver"],
            "printer": printer["name"] if printer else None,
            "hot_spot_mm": worst["hot_spot_mm"],
        }
    )
    if state.product == "generic":
        from pai_agent.tools.product import emit_cards

        await emit_cards(ctx)
    weak = "across the layers" if worst["governs"] == "layers" else "in the layer plane"
    detail = (
        f"{outcome}: {geo['name']} in {props['material']} ({fill * 100:.0f} % plastic), worst case {result['governing']}: "
        f"{result['max_von_mises_mpa']:.1f} MPa, bends {result['max_deflection_mm']:.2f} mm, safety {result['safety']:.1f}x (needs {limit:g}x, weakest {weak})"
    )
    if findings:
        detail += "; " + str(len(findings)) + " self-check note" + ("s" if len(findings) > 1 else "")
    out = {
        "ok": True,
        "detail": detail,
        "result": outcome,
        **stored,
        "cases": result["cases"],
        "loads": notes,
        "held": result["held"],
        "checks": result["checks"],
        "mesh": {"nodes": result["nodes"], "elements": result["elements"], "element_size_mm": result["element_size_mm"], "solver": result["solver"]},
        "requirement": requirement["id"],
    }
    if outcome == "fail":
        thicken = "a thicker plate with cad_frame thickness_mm" if state.product == "drone" else "a thicker wall there with cad_update"
        out["hint"] = (
            f"Most stressed at {worst['hot_spot_mm']} mm. Try {thicken} (bending stress falls with the square of the thickness), "
            "pick a stronger material with material_pick, or print it so the layers run along the load (print_prep orientations), then fem_check again."
        )
    if findings:
        out["hint"] = ((out.get("hint") or "") + " Tell the user the self-check notes with the safety factor.").strip()
    return out


async def refresh_fem(ctx: Ctx, part_id: str) -> dict | None:
    """Runs the part's FEM again after its shape or material changed, with the same arguments."""

    entry = ctx.state.checks.get("fem:" + part_id)
    if entry is None:
        return None
    return await fem_check(ctx, dict(entry["args"]))


async def material_pick(ctx: Ctx, args: dict) -> dict:
    state = ctx.state
    printer = printers.current()
    needs = {
        "max_temp_c": args.get("max_temp_c"),
        "outdoor": bool(args.get("outdoor")),
        "impact": bool(args.get("impact")),
        "flex": bool(args.get("flex")),
    }
    try:
        if needs["max_temp_c"] is not None:
            needs["max_temp_c"] = float(needs["max_temp_c"])
    except (TypeError, ValueError):
        return _fail("max_temp_c must be a number in °C.")
    candidates = printer["printable"] if printer else list(printers.MATERIALS)
    if printer and not candidates:
        return _fail(f"The {printer['name']} prints none of the user's filaments ({', '.join(printer['filaments']) or 'none set'}). Ask them to add one it prints: {', '.join(printer['materials'])}.")
    wanted = printers.normalise_material(args.get("material")) if args.get("material") else None
    if wanted is not None and wanted not in candidates:
        where = f"the {printer['name']} with the user's filaments" if printer else "the material table"
        return _fail(f"{wanted} is not printable on {where}. Choose from: {', '.join(candidates)}.")
    try:
        choice = printers.choose_material(needs, [wanted] if wanted else candidates)
    except ValueError as exc:
        return _fail(str(exc))
    if wanted:
        choice["reason"] = (str(args.get("reason") or "").strip() or choice["reason"])
    material = choice["material"]
    if state.product == "drone":
        part_id, name = "frame", "Frame"
        before = _frame_material(state) if state.print_materials.get("frame") else None
        if state.frame_mass_g is not None:
            old = printers.density(before) if before else CARBON_G_CM3
            state.frame_mass_g = round(state.frame_mass_g * printers.density(material) / old, 2)
    else:
        spec = state.spec
        part = find_part(spec, str(args.get("part_id") or ""), "printed") if state.product == "generic" and spec else None
        if part is None:
            return _fail("part_id must be a printed part of the spec (or call it for the drone frame).")
        part_id, name = part["id"], part["name"]
        info = state.built.get(part_id)
        old = printers.density(info["material"]) if info and info["material"] in printers.MATERIALS else None
        part["material"] = material
        if info is not None:
            scale = printers.density(material) / old if old else 1.0
            info["material"] = material
            info["mass_g"] = round(float(info["mass_g"]) * scale, 2)
            info["parts"] = [{**row, "material": material, "mass_g": round(float(row.get("mass_g") or 0.0) * scale, 3)} for row in info["parts"]]
            state.assembly_stale = True
            state.bom = None
    state.print_materials[part_id] = {"material": material, "reason": choice["reason"], "needs": needs, "ok": choice["ok"]}
    entry = printers.MATERIALS[material]
    result = {
        "ok": True,
        "detail": f"{name}: {material}" + ("" if choice["ok"] else ", best of what is printable, short of the need"),
        "part_id": part_id,
        "material": material,
        "reason": choice["reason"],
        "meets_needs": choice["ok"],
        "rejected": choice["rejected"],
        "printer": printer["name"] if printer else None,
        "properties": {k: entry[k] for k in ("modulus_mpa", "strength_mpa", "z_strength_mpa", "hdt_c", "elongation_pct", "uv", "density_g_cm3", "eur_per_kg")},
        "source": entry["source"],
    }
    if state.product == "generic" and state.built.get(part_id):
        from pai_agent.tools.product import ensure_assembly, rerun_checks

        if state.checks:
            result["checks"] = await rerun_checks(ctx)
        else:
            await ensure_assembly(ctx)
    elif state.product == "drone":
        refreshed = await refresh_fem(ctx, "frame")
        if refreshed is not None:
            result["fem"] = {k: refreshed.get(k) for k in ("result", "safety", "detail")}
    return result


CHECK_TOOLS = {"fem_check": fem_check}
