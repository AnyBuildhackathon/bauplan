"""Builds the reference parts, measures what each build wrote and compares it with what it must be.

Per part, every check is one row:

- the STEP: its length unit is mm, the shape is valid, every shell is closed, and its solids, volume, surface
  area, centre of mass, bounding box and the overlap between its bodies match the formulas (parts.py) or,
  where a part has none, recorded.json, to 1e-6 of the volume and area and 0.1 um of a length;
- AnyBuild's own numbers: the volume, bounding box, centre of mass and mass it reports match the exact solid;
- the STL a slicer gets: it holds every printed body and nothing else, each body is watertight (no open,
  overused or flipped edge, no degenerate triangle, facing out), its genus matches, and its bounding box,
  volume, area and centre of mass sit within what the exporter's deflection allows, which is also the unit
  check: a mesh in metres or inches is a thousand or 25 times off;
- per body: the same against its own formula or record, its STL against its solid, its node in the GLB;
- mirror pairs: one body is the other mirrored across x = 0.

Builds run in worker processes (FreeCAD and SolidCraft are programs of their own, CadQuery holds the GIL);
each worker builds one part and measures its files, the comparisons run here.
"""

from __future__ import annotations

import json
import math
import multiprocessing
import os
import re
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import measure, parts
from .build import Output
from .parts import Expect, Reference

RECORDED = Path(__file__).with_name("recorded.json")
QUANTITIES = ("volume_mm3", "area_mm2", "com_mm", "bbox_mm", "solids", "genus", "overlap_mm3")
# Exact solids agree with a formula to this much of their volume or area, and to this many mm in a length.
REL = 1e-6
LENGTH_MM = 1e-4
# AnyBuild rounds what it reports: volumes to 0.01 mm3, lengths to 0.001 mm, masses to 0.01 g.
REPORTED_VOLUME = 0.01
REPORTED_LENGTH = 0.001
REPORTED_MASS = 0.01
# Two bodies may touch; sharing more than this much volume means they overlap.
OVERLAP_MM3 = 0.01


@dataclass
class Row:
    check: str
    ok: bool
    expected: object = None
    measured: object = None
    tolerance: object = None
    source: str = ""
    # Set for a check the part lists as a known defect: why it fails. It then does not fail the part, until it passes.
    known: str | None = None


@dataclass
class BodyMeasure:
    name: str
    printed: bool
    reported: dict
    deflection_mm: float
    angular_rad: float
    density_g_cm3: float | None
    mesh: measure.Mesh
    # Its exact solid(s) from the STEP that holds it; None for a part shown for reference only.
    solid: measure.Solid | None
    solids: int
    glb_bbox: list[float] | None


@dataclass
class Measured:
    step: measure.Step
    stl: measure.Mesh | None
    stl_holds_bodies: bool
    bodies: list[BodyMeasure]
    overlaps: list[tuple[str, str, float]]
    unmatched: list[str]
    reported: dict
    reported_rel: float
    has_glb: bool
    notes: list[str]


@dataclass
class Result:
    reference: Reference
    seconds: float = 0.0
    skipped: str | None = None
    error: str | None = None
    measured: Measured | None = None
    rows: list[Row] = field(default_factory=list)
    record: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.skipped is None and self.error is None and all(row.ok or row.known for row in self.rows)


def missing(needs: str | None) -> str | None:
    """Why this machine cannot build a part that needs FreeCAD or SolidCraft, or None."""

    if needs == "freecad":
        from pai_agent.freecad_run import find_freecadcmd

        return None if find_freecadcmd() else "freecadcmd is not installed"
    if needs == "solidcraft":
        from pai_agent import solidcraft

        return solidcraft.missing()
    return None


# --- In the worker: build and measure -------------------------------------------------------------------------------


def _merge(solids: list[measure.Solid]) -> measure.Solid:
    volume = sum(s.volume_mm3 for s in solids)
    boxes = [s.bbox_mm for s in solids]
    return measure.Solid(
        volume,
        sum(s.area_mm2 for s in solids),
        sum(s.curved_area_mm2 for s in solids),
        [sum(s.volume_mm3 * s.com_mm[i] for s in solids) / volume for i in range(3)],
        [min(b[i] for b in boxes) for i in range(3)] + [max(b[i] for b in boxes) for i in range(3, 6)],
    )


def _inside(inner: list[float], outer: list[float], slack: float = 0.01) -> bool:
    return all(inner[i] >= outer[i] - slack for i in range(3)) and all(inner[i] <= outer[i] + slack for i in range(3, 6))


def _match(step: measure.Step, bodies: list) -> tuple[dict[str, list[int]], list[str]]:
    """Which solids of a STEP belong to which body: each body claims the unclaimed solids inside its reported box,
    smallest box first. A STEP of one body gives it every solid."""

    if len(bodies) == 1:
        return {bodies[0].name: list(range(len(step.solids)))}, []
    claimed: dict[str, list[int]] = {}
    free = set(range(len(step.solids)))

    def size(body) -> float:
        box = body.reported.get("bbox_mm") or [0.0] * 6
        return math.prod(box[i + 3] - box[i] for i in range(3))

    for body in sorted(bodies, key=size):
        box = body.reported.get("bbox_mm")
        mine = sorted(i for i in free if box and _inside(step.solids[i].bbox_mm, box, body.deflection_mm + 0.01))
        claimed[body.name] = mine
        free -= set(mine)
    problems = [f"{len(free)} solids in {Path(bodies[0].step).name} belong to no body"] if free else []
    problems += [f"{name} has no solid in its STEP" for name, found in claimed.items() if not found]
    return claimed, problems


def _triangles(path: Path):
    import numpy as np

    corners = measure.read_stl(path).astype(np.float32).reshape(-1, 9)
    return corners[np.lexsort(corners.T[::-1])]


def measure_output(output: Output) -> Measured:
    import numpy as np

    steps: dict[Path, measure.Step] = {}
    claims: dict[str, list[int]] = {}
    unmatched: list[str] = []
    for path in dict.fromkeys(body.step for body in output.bodies if body.step):
        steps[path] = measure.step(path, overlaps=path == output.step)
        found, problems = _match(steps[path], [body for body in output.bodies if body.step == path])
        claims.update(found)
        unmatched += problems
    primary = steps.get(output.step) or measure.step(output.step, overlaps=True)
    glb = measure.glb_nodes(output.glb) if output.glb else {}
    bodies = []
    for body in output.bodies:
        solids = [steps[body.step].solids[i] for i in claims.get(body.name, [])] if body.step else []
        bodies.append(
            BodyMeasure(
                body.name, body.printed, body.reported, body.deflection_mm, body.angular_rad, body.density_g_cm3, measure.mesh(body.stl),
                _merge(solids) if solids else None, len(solids), glb.get(body.name),
            )
        )
    holds = False
    if output.stl:
        # The same triangles, in any order: the slicer's file is the printed bodies' meshes and nothing else.
        printed = [_triangles(body.stl) for body in output.printed]
        together = np.concatenate(printed) if printed else np.zeros((0, 9), np.float32)
        combined = _triangles(output.stl)
        holds = combined.shape == together.shape and bool(np.array_equal(combined, together[np.lexsort(together.T[::-1])]))
    owner = {i: name for name, found in claims.items() for i in found if any(b.name == name and b.step == output.step for b in output.bodies)}
    overlaps = [(owner.get(i, f"solid {i}"), owner.get(j, f"solid {j}"), v) for i, j, v in primary.overlaps]
    return Measured(
        primary, measure.mesh(output.stl) if output.stl else None, holds, bodies, overlaps, unmatched,
        output.reported, output.reported_rel, output.glb is not None, output.notes,
    )


def build_and_measure(name: str, directory: str) -> tuple[Measured, float]:
    """One part, in a worker process: build it into directory, measure its files."""

    reference = next(r for r in parts.REFERENCES if r.name == name)
    started = time.monotonic()
    output = reference.build(Path(directory))
    return measure_output(output), time.monotonic() - started


# --- Here: compare ----------------------------------------------------------------------------------------------------


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _vector_ok(a, b, tol: float) -> bool:
    return len(a) == len(b) and all(_close(x, y, tol) for x, y in zip(a, b))


def _fmt(value: object) -> object:
    if isinstance(value, float):
        return round(value, 6) + 0.0
    if isinstance(value, (list, tuple)):
        return [_fmt(v) for v in value]
    return value


def _expected(quantity: str, formula: Expect, recorded: dict) -> tuple[object, str]:
    value = getattr(formula, quantity)
    if value is not None:
        return value, "formula"
    return recorded.get(quantity), "recorded"


def _against(rows: list[Row], label: str, quantity: str, measured: object, formula: Expect, recorded: dict, record: dict) -> None:
    """One row comparing a measured quantity with its formula or record; quantities without a formula are recorded."""

    expected, source = _expected(quantity, formula, recorded)
    if source == "recorded":
        record[quantity] = _fmt(measured)
    if expected is None:
        rows.append(Row(f"{label}{quantity}", False, None, _fmt(measured), None, "no formula and nothing recorded (run.py --record)"))
        return
    if quantity in ("solids", "genus"):
        rows.append(Row(f"{label}{quantity}", measured == expected, expected, measured, 0, source))
    elif quantity in ("com_mm", "bbox_mm"):
        rows.append(Row(f"{label}{quantity}", _vector_ok(measured, expected, LENGTH_MM), _fmt(expected), _fmt(measured), LENGTH_MM, source))
    elif quantity == "overlap_mm3":
        rows.append(Row(f"{label}{quantity}", _close(measured, expected, OVERLAP_MM3), _fmt(expected), _fmt(measured), OVERLAP_MM3, source))
    else:
        tol = REL * abs(expected) + 1e-3
        rows.append(Row(f"{label}{quantity}", _close(measured, expected, tol), _fmt(expected), _fmt(measured), _fmt(tol), source))


def mesh_checks(rows: list[Row], label: str, mesh: measure.Mesh, solid: measure.Solid, deflection: list[tuple[float, float, float]]) -> None:
    """An STL against its exact solid: per (curved area, linear, angular deflection) of the bodies in it, a mesh whose
    corners lie on the surface sits within curved area x deflection of its volume, loses at most 1 - cos(angular) of the
    curved area, and its box lies inside the solid's, at most the largest deflection short of it."""

    volume_tol = sum(area * linear for area, linear, _a in deflection) + REL * solid.volume_mm3
    area_tol = sum(area * (1 - math.cos(angular)) for area, _l, angular in deflection) + REL * solid.area_mm2 + 1e-6
    reach = max((linear for _c, linear, _a in deflection), default=0.0) + 1e-5
    inside = all(mesh.bbox_mm[i] >= solid.bbox_mm[i] - 1e-5 and mesh.bbox_mm[i + 3] <= solid.bbox_mm[i + 3] + 1e-5 for i in range(3))
    near = all(mesh.bbox_mm[i] - solid.bbox_mm[i] <= reach and solid.bbox_mm[i + 3] - mesh.bbox_mm[i + 3] <= reach for i in range(3))
    rows.append(Row(f"{label}STL bbox_mm (units)", inside and near, _fmt(solid.bbox_mm), _fmt(mesh.bbox_mm), _fmt(reach), "STEP"))
    rows.append(Row(f"{label}STL volume_mm3", _close(mesh.volume_mm3, solid.volume_mm3, volume_tol), _fmt(solid.volume_mm3), _fmt(mesh.volume_mm3), _fmt(volume_tol), "STEP"))
    rows.append(Row(f"{label}STL area_mm2", _close(mesh.area_mm2, solid.area_mm2, area_tol), _fmt(solid.area_mm2), _fmt(mesh.area_mm2), _fmt(area_tol), "STEP"))
    shift = volume_tol / max(solid.volume_mm3, 1e-9) * math.dist(solid.bbox_mm[:3], solid.bbox_mm[3:]) + 1e-4
    rows.append(Row(f"{label}STL com_mm", _vector_ok(mesh.com_mm, solid.com_mm, shift), _fmt(solid.com_mm), _fmt(mesh.com_mm), _fmt(shift), "STEP"))


def _reported_rows(rows: list[Row], label: str, reported: dict, solid: measure.Solid, rel: float) -> None:
    if reported.get("volume_mm3") is not None:
        tol = REPORTED_VOLUME + (REL + rel) * solid.volume_mm3
        rows.append(Row(f"{label}reported volume_mm3", _close(reported["volume_mm3"], solid.volume_mm3, tol), _fmt(solid.volume_mm3), reported["volume_mm3"], _fmt(tol), "STEP"))
    if reported.get("bbox_mm") is not None:
        rows.append(Row(f"{label}reported bbox_mm", _vector_ok(reported["bbox_mm"], solid.bbox_mm, REPORTED_LENGTH), _fmt(solid.bbox_mm), reported["bbox_mm"], REPORTED_LENGTH, "STEP"))
    if reported.get("com_mm") is not None:
        rows.append(Row(f"{label}reported com_mm", _vector_ok(reported["com_mm"], solid.com_mm, REPORTED_LENGTH), _fmt(solid.com_mm), reported["com_mm"], REPORTED_LENGTH, "STEP"))


def _mirrored(rows: list[Row], a: BodyMeasure, b: BodyMeasure) -> None:
    sa, sb = a.solid or a.mesh, b.solid or b.mesh
    flipped = [-sb.bbox_mm[3], sb.bbox_mm[1], sb.bbox_mm[2], -sb.bbox_mm[0], sb.bbox_mm[4], sb.bbox_mm[5]]
    same = (
        _close(sa.volume_mm3, sb.volume_mm3, REL * sa.volume_mm3)
        and _close(sa.area_mm2, sb.area_mm2, REL * sa.area_mm2)
        and _vector_ok(sa.com_mm, [-sb.com_mm[0], sb.com_mm[1], sb.com_mm[2]], LENGTH_MM)
        and _vector_ok(sa.bbox_mm, flipped, LENGTH_MM)
    )
    mine = [_fmt(sa.volume_mm3), _fmt(sa.area_mm2), _fmt(sa.com_mm)]
    theirs = [_fmt(sb.volume_mm3), _fmt(sb.area_mm2), _fmt([-sb.com_mm[0], sb.com_mm[1], sb.com_mm[2]])]
    rows.append(Row(f"{a.name} mirrors {b.name} across x = 0", same, mine, theirs, LENGTH_MM, "symmetry"))


def compare(reference: Reference, measured: Measured, recorded: dict) -> tuple[list[Row], dict]:
    """Every check of one part, and what --record would store for the quantities without a formula."""

    expect, rows, record = reference.expect, [], {}
    step = measured.step
    rows.append(Row("STEP length unit is mm", step.unit_mm == 1.0, 1.0, step.unit_mm, 0, "file"))
    rows.append(Row("STEP shape is valid", step.valid, True, step.valid, None, "BRepCheck"))
    rows.append(Row("STEP shells are closed", step.free_edges == 0 and step.bad_edges == 0, "0 free, 0 bad edges", f"{step.free_edges} free, {step.bad_edges} bad edges", None, "ShapeAnalysis"))
    rows.append(Row("STEP solids belong to the bodies", not measured.unmatched, [], measured.unmatched, None, "STEP"))
    totals = measure.Solid(step.volume_mm3, step.area_mm2, step.curved_area_mm2, step.com_mm, step.bbox_mm)
    printed = [body for body in measured.bodies if body.printed]
    for quantity, value in (
        ("solids", len(step.solids)),
        ("volume_mm3", totals.volume_mm3),
        ("area_mm2", totals.area_mm2),
        ("com_mm", totals.com_mm),
        ("bbox_mm", totals.bbox_mm),
    ):
        _against(rows, "STEP ", quantity, value, expect, recorded, record)
    if len(step.solids) > 1:
        _against(rows, "STEP ", "overlap_mm3", sum(v for _a, _b, v in measured.overlaps), expect, recorded, record)
        if measured.overlaps:
            rows.append(Row("STEP bodies that overlap", True, None, [[a, b, round(v, 3)] for a, b, v in measured.overlaps], None, "note"))
    if measured.notes:
        rows.append(Row("build warnings", True, None, measured.notes, None, "note"))
    # The topology of what a slicer gets, or of the part itself when nothing of it is printed.
    meshed = printed if measured.stl is not None else measured.bodies
    _against(rows, "STL ", "genus", round(sum(body.mesh.genus for body in meshed)), expect, recorded, record)
    _reported_rows(rows, "", measured.reported, totals, measured.reported_rel)
    mass = measured.reported.get("mass_g")
    if mass is not None:
        if expect.mass_g is not None:
            wanted, source = expect.mass_g, "formula"
        else:
            wanted = sum(b.solid.volume_mm3 * b.density_g_cm3 / 1000.0 for b in printed if b.solid and b.density_g_cm3) if printed else None
            source = "STEP x density"
        if wanted is not None:
            tol = REPORTED_MASS + (REL + measured.reported_rel) * wanted
            rows.append(Row("reported mass_g", _close(mass, wanted, tol), _fmt(wanted), mass, _fmt(tol), source))

    if measured.stl is not None:
        rows.append(Row("STL holds every printed body and nothing else", measured.stl_holds_bodies, True, measured.stl_holds_bodies, None, "per-body STLs"))
        leaks = [f"{b.name}: {', '.join(b.mesh.problems)}" for b in printed if b.mesh.problems]
        rows.append(Row("STL is watertight", not leaks, [], leaks, None, "edges"))
        deflection = [(b.solid.curved_area_mm2 if b.solid else b.mesh.area_mm2, b.deflection_mm, b.angular_rad) for b in printed]
        mesh_checks(rows, "", measured.stl, totals, deflection)

    record_bodies: dict[str, dict] = {}
    multi = len(measured.bodies) > 1
    for body in measured.bodies:
        label = body.name + ": "
        # A part's only printed body has the part's own formula.
        formula = expect.bodies.get(body.name) or (expect if body.printed and len(printed) == 1 else Expect())
        known = recorded.get("bodies", {}).get(body.name, {})
        mine: dict = {}
        # A printed body's mesh is in the STL checked above; the rest have only their own file.
        if not body.printed or measured.stl is None:
            rows.append(Row(f"{label}STL is watertight", not body.mesh.problems, [], body.mesh.problems, None, "edges"))
        exact = body.solid
        if exact is not None:
            _reported_rows(rows, label, body.reported, exact, measured.reported_rel)
            if multi or measured.stl is None:
                mesh_checks(rows, label, body.mesh, exact, [(exact.curved_area_mm2, body.deflection_mm, body.angular_rad)])
        elif body.reported.get("volume_mm3") is not None:
            # A part shown for reference only has no STEP: its mesh stands in, against what the build reported.
            tol = body.mesh.area_mm2 * body.deflection_mm + REPORTED_VOLUME
            rows.append(Row(f"{label}STL volume_mm3", _close(body.mesh.volume_mm3, body.reported["volume_mm3"], tol), body.reported["volume_mm3"], _fmt(body.mesh.volume_mm3), _fmt(tol), "reported"))
        if exact is not None and multi:
            for quantity, value in (("volume_mm3", exact.volume_mm3), ("area_mm2", exact.area_mm2), ("com_mm", exact.com_mm), ("bbox_mm", exact.bbox_mm)):
                _against(rows, label, quantity, value, formula, known, mine)
            _against(rows, label, "genus", round(body.mesh.genus), formula, known, mine)
        elif exact is None and multi and None not in (formula.volume_mm3, formula.area_mm2, formula.com_mm, formula.bbox_mm):
            # Without a STEP solid to know its curved area, the whole area bounds the mesh.
            solid = measure.Solid(formula.volume_mm3, formula.area_mm2, formula.area_mm2, formula.com_mm, formula.bbox_mm)
            mesh_checks(rows, label, body.mesh, solid, [(solid.curved_area_mm2, body.deflection_mm, body.angular_rad)])
        if formula.mass_g is not None and body.reported.get("mass_g") is not None:
            tol = REPORTED_MASS + 1e-6 * formula.mass_g
            rows.append(Row(f"{label}reported mass_g", _close(body.reported["mass_g"], formula.mass_g, tol), _fmt(formula.mass_g), body.reported["mass_g"], _fmt(tol), "formula"))
        if measured.has_glb:
            box = body.glb_bbox
            rows.append(Row(f"{label}GLB node matches its STL", box is not None and _vector_ok(box, body.mesh.bbox_mm, 1e-4), _fmt(body.mesh.bbox_mm), _fmt(box), 1e-4, "GLB"))
        if mine:
            record_bodies[body.name] = mine
    if record_bodies:
        record["bodies"] = record_bodies
    by_name = {body.name: body for body in measured.bodies}
    for a, b in expect.mirrored:
        if a in by_name and b in by_name:
            _mirrored(rows, by_name[a], by_name[b])
        else:
            rows.append(Row(f"{a} mirrors {b} across x = 0", False, [a, b], sorted(by_name), None, "symmetry"))
    return _known(rows, reference.known), record


def _known(rows: list[Row], known: dict[str, str]) -> list[Row]:
    """Marks the checks a part lists as known defects; one that passes again fails, so its entry goes."""

    names = {row.check for row in rows}
    for row in rows:
        if row.check in known:
            if row.ok:
                row.ok, row.source = False, "known defect no longer reproduces: remove it from the part's known defects"
            else:
                row.known = known[row.check]
    rows += [Row(check, False, None, None, None, "a known defect names a check this part does not have") for check in known if check not in names]
    return rows


# --- Running ----------------------------------------------------------------------------------------------------------


def load_recorded() -> dict:
    return json.loads(RECORDED.read_text(encoding="utf-8")) if RECORDED.is_file() else {}


def run(references: list[Reference], directory: Path, jobs: int | None = None) -> dict[str, Result]:
    """Builds and checks the references; a part this machine cannot build is skipped with the reason."""

    recorded = load_recorded()
    results = {r.name: Result(r) for r in references}
    todo = []
    for reference in references:
        reason = missing(reference.needs)
        if reason:
            results[reference.name].skipped = reason
        else:
            todo.append(reference)
    jobs = jobs or int(os.environ.get("CAD_ORACLE_JOBS") or min(4, os.cpu_count() or 1))
    # Fresh interpreters, also where fork is the default: a forked copy of a process that holds OCP or threads can hang.
    with ProcessPoolExecutor(max_workers=max(1, min(jobs, len(todo) or 1)), mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = {r.name: pool.submit(build_and_measure, r.name, str(directory / r.name)) for r in sorted(todo, key=lambda r: not r.slow)}
        for reference in todo:
            result = results[reference.name]
            try:
                result.measured, result.seconds = futures[reference.name].result()
            except Exception as exc:  # noqa: BLE001 - a build that fails is the part's failure, not the suite's.
                result.error = f"{type(exc).__name__}: {exc}\n" + "".join(traceback.format_exception(exc)[-3:])
                continue
            result.rows, result.record = compare(reference, result.measured, recorded.get(reference.name, {}))
    return results


def write_record(results: dict[str, Result]) -> dict:
    """Stores what each built part measured for its quantities without a formula; parts not built keep their record."""

    recorded = load_recorded()
    for name, result in results.items():
        if result.measured is not None:
            if result.record:
                recorded[name] = result.record
            else:
                recorded.pop(name, None)
    text = json.dumps(dict(sorted(recorded.items())), indent=1)
    # A vector on one line, so a changed record reads as one changed line.
    text = re.sub(r"\[\s+([^\[\]{}]*?)\s+\]", lambda m: "[" + ", ".join(v.strip() for v in m.group(1).split(",")) + "]", text)
    RECORDED.write_text(text + "\n", encoding="utf-8")
    return recorded


def describe(row: Row) -> str:
    tolerance = "" if row.tolerance in (None, 0) else f" +- {row.tolerance}"
    text = f"{row.check}: expected {row.expected}{tolerance} ({row.source}), measured {row.measured}"
    return text + (f"\n     known defect: {row.known}" if row.known else "")
