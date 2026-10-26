"""Surface checks of printed parts: where a part hangs over, where its walls are thin and where it sits too
close to another part, with a number on every spot of its surface.

Each printed body is checked in the build's frame (mm, Z up), in the pose it is printed in. Its surface is
cut into sample triangles: the longest edges are split at their middle, on both triangles that share them,
round by round until the body has its share of `SAMPLES` by its area (at most `MAX_SAMPLES` on one), so
neighbouring samples share their edges and every spot of a large flat face is measured too. Every sample
gets one value per check:

- overhang: how far a downward face leans out from the vertical, from its normal and the print direction,
  0 to 90 degrees (a ceiling is 90); a face on the bed is -1 and never critical. Critical above the limit
  (print_prep's 45 degrees). The six axis directions of the part are checked the same way, and the one
  that leaves clearly less overhang is named.
- thickness: a ray from the middle of the sample straight into the part, to where it comes out again, in
  mm. A ray that slips between two triangles is cast again tilted by a degree, twice; one that never
  comes out is -1. Critical below two extrusion lines of the nozzle (2 x 1.1 x 0.4 mm = 0.88 mm).
- clearance: a ray along the outward normal to the next other part (any other body of the build but those
  marked as no neighbour, such as a load or a standard part in its hole), in mm up to `RANGE_MM`,
  which also stands for anything farther; negative where the sample lies inside another part (they
  overlap), 0 where the faces touch, as parts that sit on each other are meant to. Critical below one
  nozzle width, and wherever parts overlap.

A value within float noise of a limit counts as on the limit, so a 45 degree roof is not critical by
rounding. Critical samples that share a corner form a spot (SciPy's connected_components): its area, size,
worst value and where that is. Spots of the same size and worst value are counted together, such as the
teeth of a gear or the holes of a pattern. Of the walls and gaps some spots need no fix and are marked
(`spots`): a speck smaller than one sample, the taper of a blunt sharp edge, the wedge where two parts meet
at an angle; `finding_mm2` is the critical area without them, what a fix is for.

The rays run on VTK's vtkModifiedBSPTree, built on the body's own triangles, not the samples. vtkOBBTree
finds the same hits about five times slower (19 against 4 microseconds a ray on the test bracket, 410
against 78 on a sphere of 14,400 triangles); vtkStaticCellLocator and vtkCellLocator are faster still but
let about a third of the rays on the bracket's flat faces through without a hit.

`write_glb` stores the sampled surface of each checked body as a node named like the source node, in that
node's own frame, so the studio lays it over the model; each triangle carries its value at its three
corners (`_OVERHANG`, `_THICKNESS`, `_CLEARANCE`) and the extras say each check's limit and unit.

`python -m pai_agent.surface_checks job.json` runs a job written by `tools/surface.py` in its own process,
so a long ray loop never holds the server's interpreter, and prints one JSON line.
"""

from __future__ import annotations

import json
import math
import struct
import sys
import time
from pathlib import Path

import numpy as np

CHECKS = ("overhang", "thickness", "clearance")
UNITS = {"overhang": "deg", "thickness": "mm", "clearance": "mm"}
# Which side of the limit is critical.
CRITICAL = {"overhang": "above", "thickness": "below", "clearance": "below"}
ATTRIBUTES = {check: "_" + check.upper() for check in CHECKS}
OVERHANG_DEG = 45.0
# A face within this of the body's lowest point along the print direction rests on the bed.
BED_MM = 0.05
# Extrusion width over the nozzle diameter, as print_prep's shell estimate takes it.
LINE = 1.1
# Clearance looks this far; a farther part counts as free.
RANGE_MM = 5.0
# Faces this close count as touching, which is meant so.
TOUCH_MM = 0.01
# Overhang (degrees) and lengths (mm) within this of a limit count as on the limit.
ANGLE_TOL = 0.01
LENGTH_TOL = 1e-3
# The sentinel for a face on the bed (overhang) and a ray that never came out (thickness).
NONE = -1.0
# Sample triangles over all checked bodies, at most MAX_SAMPLES on one, and no edge cut below MIN_SPACING_MM.
SAMPLES = 40_000
MAX_SAMPLES = 200_000
MIN_SPACING_MM = 0.25
TILT_DEG = 1.0
SPOTS = 3
# The axis directions a better print direction is chosen from, in the part's own frame.
AXES = ("+x", "-x", "+y", "-y", "+z", "-z")
# A better direction must save half the overhang and at least this much.
BETTER_MM2 = 100.0
# A critical area under this is noise on the mesh, not a finding (print_prep's rule for an overhang).
FINDING_MM2 = 1.0


def min_wall_mm(nozzle_mm: float) -> float:
    """The thinnest wall that holds two extrusion lines of the nozzle."""

    return round(2.0 * LINE * nozzle_mm, 2)


def min_gap_mm(nozzle_mm: float) -> float:
    """The tightest gap that counts as free: one nozzle width."""

    return round(float(nozzle_mm), 2)


def area_text(mm2: float) -> str:
    """An area as people read it: cm² from 1 cm² up, else whole mm²."""

    return f"{mm2 / 100:.1f} cm²" if mm2 >= 100 else f"{mm2:.0f} mm²"


def default_limits(nozzle_mm: float = 0.4) -> dict:
    return {"overhang": OVERHANG_DEG, "thickness": min_wall_mm(nozzle_mm), "clearance": min_gap_mm(nozzle_mm)}


# ---------------------------------------------------------------- surface


def weld(points: np.ndarray, faces: np.ndarray, tol: float = 1e-4) -> tuple[np.ndarray, np.ndarray]:
    """One surface from a triangle soup (STL, GLB): corners closer than tol merge, degenerate triangles go."""

    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if not len(faces):
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    _, first, inverse = np.unique(np.round(points / tol).astype(np.int64), axis=0, return_index=True, return_inverse=True)
    merged = points[first]
    faces = inverse.reshape(-1)[faces]
    keep = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 2] != faces[:, 0])
    faces = faces[keep]
    a, b, c = merged[faces[:, 0]], merged[faces[:, 1]], merged[faces[:, 2]]
    # Outward normals: a body wound the other way round (negative volume) is turned over.
    if float(np.einsum("ij,ij->", a, np.cross(b, c))) < 0:
        faces = faces[:, [0, 2, 1]]
    return merged, faces


def _edges(faces: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray]:
    """The unique edges as corner pairs, and per face the ids of its edges 01, 12 and 20."""

    pairs = np.stack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=1).reshape(-1, 2)
    low, high = pairs.min(axis=1), pairs.max(axis=1)
    keys, inverse = np.unique(low * count + high, return_inverse=True)
    return np.stack([keys // count, keys % count], axis=1), inverse.reshape(-1, 3)


def refine(points: np.ndarray, faces: np.ndarray, samples: int, shortest: float = MIN_SPACING_MM) -> tuple[np.ndarray, np.ndarray, float]:
    """Splits the longest edges at their middle, on both their triangles, round by round, until there are
    `samples` triangles or no edge is longer than `shortest`; returns the triangles and the longest edge left.

    Each round splits the edges within a factor of 1.4 of the longest one, or only the longest of them when
    the budget runs short, so the spacing stays even. A triangle with one split edge becomes two, with two
    three (the quad left over takes its shorter diagonal), with three four; the surface keeps no cracks."""

    longest = 0.0
    for _ in range(64):
        edges, of_face = _edges(faces, len(points))
        lengths = np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1)
        longest = float(lengths.max()) if len(lengths) else 0.0
        # A split edge adds a triangle on each side.
        budget = (samples - len(faces)) // 2
        if longest <= shortest or budget <= 0:
            break
        long = lengths > max(shortest, longest / 1.4)
        if long.sum() > budget:
            long[:] = False
            long[np.argsort(-lengths, kind="stable")[:budget]] = True
        split = long[of_face]
        code = split[:, 0] * 1 + split[:, 1] * 2 + split[:, 2] * 4
        middle = np.full(len(edges), -1, dtype=np.int64)
        middle[long] = len(points) + np.arange(int(long.sum()))
        points = np.concatenate([points, (points[edges[long, 0]] + points[edges[long, 1]]) / 2.0])
        m = middle[of_face]
        a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
        out = [faces[code == 0]]
        # One edge split, turned so it is the edge from the first corner to the second.
        for k, (p, q, r, mid) in {1: (a, b, c, m[:, 0]), 2: (b, c, a, m[:, 1]), 4: (c, a, b, m[:, 2])}.items():
            s = code == k
            out += [np.stack([p[s], mid[s], r[s]], 1), np.stack([mid[s], q[s], r[s]], 1)]
        # Two edges split, turned so they are p-q and q-r; the corner at q comes off, the quad p, m1, m2, r is left.
        for k, (p, q, r, m1, m2) in {3: (a, b, c, m[:, 0], m[:, 1]), 6: (b, c, a, m[:, 1], m[:, 2]), 5: (c, a, b, m[:, 2], m[:, 0])}.items():
            s = code == k
            p, q, r, m1, m2 = p[s], q[s], r[s], m1[s], m2[s]
            out.append(np.stack([m1, q, m2], 1))
            short = (np.linalg.norm(points[p] - points[m2], axis=1) <= np.linalg.norm(points[m1] - points[r], axis=1))[:, None]
            out.append(np.where(short, np.stack([p, m1, m2], 1), np.stack([p, m1, r], 1)))
            out.append(np.where(short, np.stack([p, m2, r], 1), np.stack([m1, m2, r], 1)))
        s = code == 7
        m01, m12, m20 = m[s, 0], m[s, 1], m[s, 2]
        out += [np.stack([a[s], m01, m20], 1), np.stack([m01, b[s], m12], 1), np.stack([m20, m12, c[s]], 1), np.stack([m01, m12, m20], 1)]
        faces = np.concatenate(out)
    else:
        edges, _ = _edges(faces, len(points))
        longest = float(np.linalg.norm(points[edges[:, 0]] - points[edges[:, 1]], axis=1).max())
    return points, faces, longest


class Surface:
    """A body's sample triangles with their normals, areas and middles, the longest edge among them and the
    typical spacing (the leg of a right triangle of the median area; slivers on round caps leave it be)."""

    def __init__(self, points: np.ndarray, faces: np.ndarray, longest: float) -> None:
        self.points, self.faces, self.longest = points, faces, longest
        a, b, c = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
        cross = np.cross(b - a, c - a)
        length = np.linalg.norm(cross, axis=1)
        self.areas = length / 2.0
        self.normals = cross / np.maximum(length, 1e-12)[:, None]
        self.centroids = (a + b + c) / 3.0
        self.spacing = float(np.sqrt(2.0 * np.median(self.areas))) if len(faces) else 0.0

    def __len__(self) -> int:
        return len(self.faces)


def surface_area(points: np.ndarray, faces: np.ndarray) -> float:
    a, b, c = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
    return float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2.0)


def sample(points: np.ndarray, faces: np.ndarray, samples: int) -> Surface:
    refined, cut, longest = refine(points, faces, min(MAX_SAMPLES, samples))
    return Surface(refined, cut, longest)


# ---------------------------------------------------------------- rays


def _polydata(points: np.ndarray, faces: np.ndarray):
    from vtkmodules.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData

    vtk_points = vtkPoints()
    vtk_points.SetData(numpy_to_vtk(np.ascontiguousarray(points, dtype=np.float64), deep=True))
    cells = vtkCellArray()
    offsets = np.arange(0, 3 * len(faces) + 1, 3, dtype=np.int64)
    cells.SetData(numpy_to_vtkIdTypeArray(offsets, deep=True), numpy_to_vtkIdTypeArray(np.ascontiguousarray(faces.ravel(), dtype=np.int64), deep=True))
    poly = vtkPolyData()
    poly.SetPoints(vtk_points)
    poly.SetPolys(cells)
    return poly


def locator(points: np.ndarray, faces: np.ndarray):
    """A vtkModifiedBSPTree over the triangles; cell ids are face indices."""

    from vtkmodules.vtkFiltersFlowPaths import vtkModifiedBSPTree

    found = vtkModifiedBSPTree()
    found.SetDataSet(_polydata(points, faces))
    found.BuildLocator()
    return found


def cast(found, starts: np.ndarray, directions: np.ndarray, length: float) -> tuple[np.ndarray, np.ndarray]:
    """The first hit of each ray within length: its distance (inf for none) and the face it hit (-1)."""

    from vtkmodules.vtkCommonCore import mutable

    distance = np.full(len(starts), np.inf)
    cell = np.full(len(starts), -1, dtype=np.int64)
    if not len(starts):
        return distance, cell
    begin = np.ascontiguousarray(starts, dtype=np.float64)
    a, b = begin.tolist(), (begin + directions * length).tolist()
    t, sub, cid = mutable(0.0), mutable(0), mutable(0)
    x, pcoords = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    intersect = found.IntersectWithLine
    for i in range(len(a)):
        if intersect(a[i], b[i], 0.0, t, x, pcoords, sub, cid):
            p = a[i]
            distance[i] = math.sqrt((x[0] - p[0]) ** 2 + (x[1] - p[1]) ** 2 + (x[2] - p[2]) ** 2)
            cell[i] = cid.get()
    return distance, cell


def _tilted(directions: np.ndarray, turn: int) -> np.ndarray:
    """The directions turned by TILT_DEG, about one of two axes square to each (turn 0 or 1)."""

    helper = np.where(np.abs(directions[:, :1]) < 0.9, np.array([[1.0, 0.0, 0.0]]), np.array([[0.0, 1.0, 0.0]]))
    side = np.cross(directions, helper)
    side /= np.linalg.norm(side, axis=1, keepdims=True)
    if turn:
        side = np.cross(directions, side)
    angle = math.radians(TILT_DEG)
    return directions * math.cos(angle) + side * math.sin(angle)


def _offset(scale: float) -> float:
    """How far inside its face a ray starts, so it never hits that face itself."""

    return min(1e-2, max(1e-4, 1e-4 * scale))


def _snap(values: np.ndarray, limit: float, tol: float) -> np.ndarray:
    values = values.copy()
    values[np.abs(values - limit) <= tol] = limit
    return values


# ---------------------------------------------------------------- checks


def overhang(points: np.ndarray, faces: np.ndarray, normals: np.ndarray, up: np.ndarray, limit: float) -> np.ndarray:
    """Per triangle the angle it leans out over the vertical, 0 to 90 degrees, -1 on the bed."""

    up = np.asarray(up, dtype=float) / np.linalg.norm(up)
    heights = points @ up
    on_bed = heights[faces].max(axis=1) < heights.min() + BED_MM
    angle = np.degrees(np.arcsin(np.clip(-(normals @ up), 0.0, 1.0)))
    angle = _snap(angle, limit, ANGLE_TOL)
    angle[on_bed] = NONE
    return angle


def thickness(surface: Surface, found, scale: float, limit: float) -> np.ndarray:
    """Per sample the distance straight into the part to where it comes out again; -1 where no ray came out."""

    eps = _offset(scale)
    inward = -surface.normals
    starts = surface.centroids + inward * eps
    length = 2.0 * scale + 1.0
    distance, _ = cast(found, starts, inward, length)
    for turn in (0, 1):
        missed = np.flatnonzero(~np.isfinite(distance))
        if not len(missed):
            break
        again, _ = cast(found, starts[missed], _tilted(inward[missed], turn), length)
        distance[missed] = again
    values = _snap(distance + eps, limit, LENGTH_TOL)
    values[~np.isfinite(distance)] = NONE
    return values


def clearance(surface: Surface, others: dict | None, scale: float, limit: float) -> tuple[np.ndarray, np.ndarray]:
    """Per sample the gap along its outward normal to the next other part: up to RANGE_MM, negative inside one,
    0 touching; and which of the other bodies that is (-1 for none within RANGE_MM)."""

    values = np.full(len(surface), RANGE_MM)
    neighbour = np.full(len(surface), -1, dtype=np.int64)
    if not others or not len(surface):
        return values, neighbour
    reach = RANGE_MM + surface.longest
    lo, hi = others["boxes"][:, :3] - reach, others["boxes"][:, 3:] + reach
    c = surface.centroids
    near = np.zeros(len(surface), dtype=bool)
    for box_lo, box_hi in zip(lo, hi):
        near |= np.all((c >= box_lo) & (c <= box_hi), axis=1)
    idx = np.flatnonzero(near)
    if not len(idx):
        return values, neighbour
    eps = _offset(scale)
    n = surface.normals[idx]
    # Long enough to come out of any other part, so a start inside one shows.
    length = 2.0 * others["scale"] + RANGE_MM
    distance, cell = cast(others["locator"], c[idx] - n * eps, n, length)
    hit = np.isfinite(distance)
    gap = distance - eps
    # The first face the ray meets looks the same way it goes, so the ray leaves a part. The sample lies inside
    # that part only when the ray the other way leaves it too: a ray along a face it grazes can miss one side.
    leaves = np.zeros(len(idx), dtype=bool)
    leaves[hit] = np.einsum("ij,ij->i", others["normals"][cell[hit]], n[hit]) > 0
    if leaves.any():
        j = np.flatnonzero(leaves)
        back, back_cell = cast(others["locator"], c[idx[j]] + n[j] * eps, -n[j], length)
        seen = np.isfinite(back)
        inside = seen & (np.einsum("ij,ij->i", others["normals"][np.where(seen, back_cell, 0)], -n[j]) > 0)
        inside &= others["owner"][np.where(seen, back_cell, 0)] == others["owner"][cell[j]]
        j, back = j[inside], back[inside]
        gap[j] = -np.minimum(gap[j], back - eps)
    gap[~hit] = RANGE_MM
    gap = np.minimum(gap, RANGE_MM)
    gap[np.abs(gap) <= TOUCH_MM] = 0.0
    values[idx] = _snap(gap, limit, LENGTH_TOL)
    neighbour[idx[hit & (gap < RANGE_MM)]] = others["owner"][cell[hit & (gap < RANGE_MM)]]
    return values, neighbour


def critical(check: str, values: np.ndarray, limit: float) -> np.ndarray:
    if check == "overhang":
        return values > limit
    if check == "thickness":
        return (values < limit) & (values != NONE)
    return (values < limit) & (values != 0.0)


def _round(values, digits: int = 1) -> list[float]:
    return [round(float(v), digits) for v in values]


def spots(surface: Surface, mask: np.ndarray, values: np.ndarray, worst_high: bool, tol: float, near: list[str | None] | None = None, soft: tuple[str, float] | None = None) -> dict:
    """The critical spots: `spots`, similar ones counted together, largest first, and `count`. Critical
    samples that share a corner are one spot, so a band one sample wide along an edge stays whole.

    `soft` is (kind, limit) for the ray checks, whose spots may need no fix; those are marked:
    a `speck` is smaller than one sample cell (the spacing squared), below what the samples resolve.
    A wedge ramps up from almost nothing, where a thin rib or a fit is even: a `taper` (thickness) starts
    under half the limit, spans a quarter of it and is at most twice the limit wide (its area over its
    longest side, both faces of the edge), the edge of a wedge blunter than 45 degrees, which a slicer
    only rounds off; a `contact` (clearance) starts under a quarter of the limit and spans half of it,
    where two parts meet at an angle. `soft_mm2` is their area, `softened` marks their samples.
    `near` names, per sample, the other part a clearance ray met; a spot names the one most of its area meets."""

    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    idx = np.flatnonzero(mask)
    if not len(idx):
        return {"spots": [], "count": 0, "soft_mm2": 0.0, "softened": np.zeros(len(surface), dtype=bool)}
    # Each critical sample linked to its three corners; the samples one corner joins are one spot.
    corners_of = surface.faces[idx]
    graph = coo_matrix((np.ones(3 * len(idx)), (np.repeat(np.arange(len(idx)), 3), len(idx) + corners_of.ravel())), shape=(len(idx) + len(surface.points),) * 2)
    labels = connected_components(graph, directed=False)[1][: len(idx)]
    _, labels = np.unique(labels, return_inverse=True)
    count = int(labels.max()) + 1
    area = surface.areas[idx]
    total = np.bincount(labels, weights=area, minlength=count)
    center = np.stack([np.bincount(labels, weights=area * surface.centroids[idx, k], minlength=count) for k in range(3)], axis=1) / np.maximum(total, 1e-12)[:, None]
    corners = surface.points[corners_of]
    order = np.argsort(labels, kind="stable")
    starts = np.searchsorted(labels[order], np.arange(count))
    low = np.minimum.reduceat(corners.min(axis=1)[order], starts, axis=0)
    high = np.maximum.reduceat(corners.max(axis=1)[order], starts, axis=0)
    least = np.minimum.reduceat(values[idx][order], starts)
    most = np.maximum.reduceat(values[idx][order], starts)
    rank = np.lexsort((-values[idx] if worst_high else values[idx], labels))
    worst = rank[np.searchsorted(labels[rank], np.arange(count))]
    kind, limit = soft or ("", 0.0)
    flags = np.full(count, "", dtype=object)
    if kind == "taper":
        flags[(least <= limit / 2) & (most - least >= limit / 4) & (total / np.maximum((high - low).max(axis=1), 1e-9) <= 2 * limit)] = "taper"
    elif kind == "contact":
        flags[(least >= 0) & (least <= limit / 4) & (most - least >= limit / 2)] = "contact"
    if kind:
        flags[(flags == "") & (total < surface.spacing**2)] = "speck"
    gentle = flags != ""
    names = sorted({name for name in near or [] if name}) if near is not None else []
    if names:
        which = np.array([names.index(name) if name else len(names) for name in near])[idx]
        votes = np.zeros((count, len(names) + 1))
        np.add.at(votes, (labels, which), area)
    groups: list[dict] = []
    for spot in np.argsort(-total, kind="stable"):
        size = high[spot] - low[spot]
        value = float(values[idx[worst[spot]]])
        other = names[int(np.argmax(votes[spot, :-1]))] if names and votes[spot, :-1].any() else None
        for group in groups:
            # The same area, size, worst value, part and kind: one more of the same (the teeth of a gear, a row of holes).
            if (
                abs(total[spot] - group["area_mm2"]) <= 0.02 * group["area_mm2"] + 0.1
                and np.all(np.abs(np.sort(size) - np.sort(group["_size"])) <= 0.02 * max(group["_size"].max(), 1e-9) + surface.spacing / 2)
                and abs(value - group["worst"]) <= max(tol, 0.01 * abs(group["worst"]))
                and other == group.get("with")
                and flags[spot] == group["_flag"]
            ):
                group["count"] += 1
                if len(group["centers_mm"]) < 12:
                    group["centers_mm"].append(_round(center[spot]))
                break
        else:
            groups.append(
                {
                    "count": 1,
                    "area_mm2": round(float(total[spot]), 1),
                    "size_mm": _round(size),
                    "worst": round(value, 2),
                    "at_mm": _round(surface.centroids[idx[worst[spot]]]),
                    "centers_mm": [_round(center[spot])],
                    **({"with": other} if near is not None else {}),
                    **({str(flags[spot]): True} if flags[spot] else {}),
                    "_size": size,
                    "_flag": flags[spot],
                }
            )
    # The spots to fix lead, the soft ones follow.
    groups.sort(key=lambda g: (bool(g["_flag"]), -g["count"] * g["area_mm2"]))
    for group in groups:
        group.pop("_size")
        group.pop("_flag")
    softened = np.zeros(len(surface), dtype=bool)
    softened[idx[gentle[labels]]] = True
    return {"spots": groups[:SPOTS], "count": count, "soft_mm2": round(float(total[gentle].sum()), 1), "softened": softened}


def summary(check: str, surface: Surface, values: np.ndarray, limit: float, near: list[str | None] | None = None) -> dict:
    """Range, critical area, the area that needs a fix, the worst value and where it is, and the largest
    critical spots of one check.

    `finding_mm2` is the critical area without the soft spots (see `spots`), and `worst` the worst value
    outside them and away from touching faces: what a fix is for; `min` keeps them all. Thickness adds
    `unread_mm2`, clearance `overlap_mm2` and the other part each spot and the worst value are next to
    (`near`, per sample)."""

    valid = values != NONE if check != "clearance" else np.ones(len(values), dtype=bool)
    mask = critical(check, values, limit)
    high = check == "overhang"
    soft = {"thickness": ("taper", limit), "clearance": ("contact", limit)}.get(check)
    found = spots(surface, mask, values, high, ANGLE_TOL if high else LENGTH_TOL, near, soft)
    critical_mm2 = float(surface.areas[mask].sum())
    out: dict = {
        "min": round(float(values[valid].min()), 2) if valid.any() else None,
        "max": round(float(values[valid].max()), 2) if valid.any() else None,
        "critical_mm2": round(critical_mm2, 1),
        "finding_mm2": round(max(0.0, critical_mm2 - found["soft_mm2"]), 1),
    }
    judged = valid & ~found["softened"] & ((values != 0.0) if check == "clearance" else True)
    if not judged.any():
        judged = valid
    if judged.any():
        pick = np.flatnonzero(judged)
        at = pick[int(np.argmax(values[pick]) if high else np.argmin(values[pick]))]
        out["worst"] = {"value": round(float(values[at]), 2), "at_mm": _round(surface.centroids[at])}
        if near is not None:
            out["worst"]["with"] = near[at]
    out["spots"], out["spot_count"] = found["spots"], found["count"]
    if check == "clearance":
        out["overlap_mm2"] = round(float(surface.areas[values < -TOUCH_MM].sum()), 1)
    if check == "thickness":
        out["unread_mm2"] = round(float(surface.areas[values == NONE].sum()), 1)
    return out


def better_up(points: np.ndarray, faces: np.ndarray, normals: np.ndarray, areas: np.ndarray, frame: np.ndarray, up: np.ndarray, limit: float) -> dict:
    """The overhang area for each of the part's six axis directions, and the best one when it saves clearly."""

    def hanging(direction: np.ndarray) -> float:
        return float(areas[overhang(points, faces, normals, direction, limit) > limit].sum())

    current = hanging(up)
    by_axis = {name: hanging(sign * frame[:, axis]) for name, (axis, sign) in zip(AXES, [(i, s) for i in range(3) for s in (1.0, -1.0)])}
    best = min(by_axis, key=lambda name: (round(by_axis[name], 1), AXES.index(name)))
    out = {"by_axis_mm2": {name: round(v, 1) for name, v in by_axis.items()}, "better": None}
    if by_axis[best] <= 0.5 * current and current - by_axis[best] >= BETTER_MM2:
        axis, sign = divmod(AXES.index(best), 2)
        out["better"] = {"axis": best, "up": _round(frame[:, axis] * (1.0 if sign == 0 else -1.0), 4), "critical_mm2": round(by_axis[best], 1)}
    return out


def _others(bodies: list[dict], skip: int) -> dict | None:
    """Every other body in one locator, with each face's outward normal and body, and the bodies' boxes."""

    rows = [body for k, body in enumerate(bodies) if k != skip and len(body["faces"]) and body.get("neighbour", True) is not False]
    if not rows:
        return None
    offsets = np.cumsum([0] + [len(body["points"]) for body in rows])
    points = np.concatenate([body["points"] for body in rows])
    faces = np.concatenate([body["faces"] + offsets[k] for k, body in enumerate(rows)])
    owner = np.concatenate([np.full(len(body["faces"]), k) for k, body in enumerate(rows)])
    a, b, c = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
    cross = np.cross(b - a, c - a)
    normals = cross / np.maximum(np.linalg.norm(cross, axis=1, keepdims=True), 1e-12)
    boxes = np.array([[*body["points"].min(axis=0), *body["points"].max(axis=0)] for body in rows])
    scale = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
    return {"locator": locator(points, faces), "normals": normals, "owner": owner, "names": [body["name"] for body in rows], "boxes": boxes, "scale": scale}


def check(bodies: list[dict], checks: tuple[str, ...] | list[str] = CHECKS, limits: dict | None = None, samples: int = SAMPLES) -> dict:
    """Checks every body with `analyse`; bodies: {name, points, faces, analyse, up, frame, neighbour} in mm, Z up.

    A body with `neighbour` false is no other part for the clearance: a load the product carries (the phone on
    a stand) rests where its block is drawn, and a standard part sits in a hole made for it.

    Returns the limits and per checked body its sample surface, values per check and a summary per check.
    """

    limits = {**default_limits(), **(limits or {})}
    started = time.perf_counter()
    prepared = []
    for body in bodies:
        points, faces = weld(body["points"], body["faces"])
        prepared.append({**body, "points": points, "faces": faces})
    checked = [k for k, body in enumerate(prepared) if body.get("analyse") and len(body["faces"])]
    areas = {k: surface_area(prepared[k]["points"], prepared[k]["faces"]) for k in checked}
    total = sum(areas.values()) or 1.0
    out = []
    for k in checked:
        body = prepared[k]
        points, faces = body["points"], body["faces"]
        # One body gets all samples; several share them by their surface, at most MAX_SAMPLES on one.
        share = samples if len(checked) == 1 else max(5_000, int(samples * areas[k] / total))
        surface = sample(points, faces, min(MAX_SAMPLES, share))
        scale = float(np.linalg.norm(points.max(axis=0) - points.min(axis=0)))
        up = np.asarray(body.get("up") or [0.0, 0.0, 1.0], dtype=float)
        up /= np.linalg.norm(up)
        values: dict[str, np.ndarray] = {}
        near = None
        if "overhang" in checks:
            values["overhang"] = overhang(surface.points, surface.faces, surface.normals, up, limits["overhang"])
        if "thickness" in checks:
            values["thickness"] = thickness(surface, locator(points, faces), scale, limits["thickness"])
        if "clearance" in checks:
            others = _others(prepared, k)
            values["clearance"], which = clearance(surface, others, scale, limits["clearance"])
            near = [others["names"][i] if i >= 0 else None for i in which.tolist()] if others else [None] * len(surface)
        summaries = {name: summary(name, surface, values[name], limits[name], near if name == "clearance" else None) for name in values}
        if "overhang" in summaries:
            whole = Surface(points, faces, 0.0)
            frame = np.asarray(body.get("frame") if body.get("frame") is not None else np.eye(3), dtype=float)
            summaries["overhang"]["up"] = _round(up, 4)
            summaries["overhang"].update(better_up(points, faces, whole.normals, whole.areas, frame, up, limits["overhang"]))
        out.append({"index": k, "name": body["name"], "part_id": body.get("part_id"), "surface": surface, "values": values, "summary": summaries})
    return {"limits": {name: limits[name] for name in checks}, "bodies": out, "seconds": round(time.perf_counter() - started, 2)}


# ---------------------------------------------------------------- GLB


def meta(limits: dict) -> dict:
    """What the GLB's extras and the event say about each check."""

    out = {}
    for name, limit in limits.items():
        row = {"limit": limit, "unit": UNITS[name], "critical": CRITICAL[name], "attribute": ATTRIBUTES[name]}
        if name == "overhang":
            row["bed"] = NONE
        elif name == "thickness":
            row["unread"] = NONE
        else:
            row.update({"range": RANGE_MM, "touch": TOUCH_MM})
        out[name] = row
    return out


def write_glb(path: Path, bodies: list[dict], limits: dict) -> None:
    """One node per checked body with its sample triangles in the source node's frame (`local`, a 4x4 from the
    build's mm to it), three corners per triangle, each with the triangle's value per check."""

    blobs: list[bytes] = []
    views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []
    nodes: list[dict] = []
    offset = 0

    def add(data: np.ndarray, kind: str, bounds: bool = False) -> int:
        nonlocal offset
        raw = np.ascontiguousarray(data, dtype="<f4").tobytes()
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), "target": 34962})
        blobs.append(raw)
        offset += len(raw)
        accessor = {"bufferView": len(views) - 1, "componentType": 5126, "count": int(len(data)), "type": kind}
        if bounds:
            accessor["min"] = [float(v) for v in data.min(axis=0)]
            accessor["max"] = [float(v) for v in data.max(axis=0)]
        accessors.append(accessor)
        return len(accessors) - 1

    for body in bodies:
        surface = body["surface"]
        corners = surface.points[surface.faces.ravel()]
        local = np.asarray(body.get("local") if body.get("local") is not None else np.eye(4), dtype=float)
        placed = corners @ local[:3, :3].T + local[:3, 3]
        attributes = {"POSITION": add(placed, "VEC3", bounds=True)}
        for name, values in body["values"].items():
            attributes[ATTRIBUTES[name]] = add(np.repeat(values, 3), "SCALAR")
        meshes.append({"name": body["name"], "primitives": [{"attributes": attributes, "material": 0}]})
        # to_mm takes a point of the node back into the build's mm, Z up (row by row), for a picked spot.
        extras = {"part_id": body.get("part_id"), "mm_per_unit": float(body.get("mm_per_unit", 1.0)), "to_mm": [round(float(v), 9) for v in np.linalg.inv(local).ravel()]}
        nodes.append({"name": body["name"], "mesh": len(meshes) - 1, "extras": extras})
    document = {
        "asset": {"version": "2.0", "generator": "AnyBuild surface checks", "extras": {"checks": meta(limits)}},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": [{"name": "surface check", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0, "roughnessFactor": 0.7}, "doubleSided": False}],
        "buffers": [{"byteLength": offset}],
        "bufferViews": views,
        "accessors": accessors,
    }
    header = json.dumps(document, separators=(",", ":")).encode("utf-8")
    header += b" " * (-len(header) % 4)
    body_bytes = b"".join(blobs)
    body_bytes += b"\x00" * (-len(body_bytes) % 4)
    chunks = struct.pack("<I4s", len(header), b"JSON") + header + struct.pack("<I4s", len(body_bytes), b"BIN\x00") + body_bytes
    Path(path).write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)


# ---------------------------------------------------------------- job


def _from_millimetres(axes: str) -> np.ndarray:
    """The 4x4 from the build's mm, Z up, back into the GLB's own axes (view_render.to_millimetres undone)."""

    if axes != "gltf":
        return np.eye(4)
    turn = np.zeros((4, 4))
    turn[0, 0], turn[1, 2], turn[2, 1], turn[3, 3] = 1e-3, 1e-3, -1e-3, 1.0
    return turn


def run(job: dict) -> dict:
    """Reads the job's GLB nodes, checks the chosen ones against all, writes the GLB and returns the summaries."""

    from pai_agent.view_render import mesh_nodes, read_glb, read_meshes

    glb, axes = Path(job["glb"]), job.get("axes", "zup_mm")
    wanted = {int(row["node"]): row for row in job["bodies"]}
    worlds = {node["index"]: node["world"] for node in mesh_nodes(read_glb(glb)[0])}
    merged: dict[int, dict] = {}
    for mesh in read_meshes(glb, axes, set(wanted)):
        row = merged.setdefault(mesh["node"], {"name": mesh["name"], "points": [], "faces": [], "count": 0})
        row["points"].append(mesh["points"])
        row["faces"].append(mesh["faces"] + row["count"])
        row["count"] += len(mesh["points"])
    bodies = []
    for index, row in merged.items():
        spec = wanted[index]
        bodies.append(
            {
                "name": row["name"],
                "part_id": spec.get("part_id"),
                "points": np.concatenate(row["points"]),
                "faces": np.concatenate(row["faces"]),
                "analyse": bool(spec.get("analyse")),
                "neighbour": spec.get("neighbour", True) is not False,
                "up": spec.get("up"),
                "frame": np.array(spec["frame"], dtype=float) if spec.get("frame") is not None else None,
                "node": index,
            }
        )
    if not any(body["analyse"] for body in bodies):
        raise ValueError("None of the parts to check has triangles in the model.")
    result = check(bodies, tuple(job.get("checks") or CHECKS), job.get("limits"), int(job.get("samples") or SAMPLES))
    unit = 1000.0 if axes == "gltf" else 1.0
    for row in result["bodies"]:
        world = worlds[bodies[row["index"]]["node"]]
        row["local"] = np.linalg.inv(world) @ _from_millimetres(axes)
        row["mm_per_unit"] = unit
    write_glb(Path(job["out"]), result["bodies"], result["limits"])
    return {
        "ok": True,
        "limits": result["limits"],
        "checks": meta(result["limits"]),
        "seconds": result["seconds"],
        "bodies": [
            {"name": row["name"], "part_id": row["part_id"], "samples": len(row["surface"]), "spacing_mm": round(row["surface"].spacing, 2), **row["summary"]}
            for row in result["bodies"]
        ],
    }


def main(argv: list[str]) -> int:
    job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    try:
        result = run(job)
    except Exception as exc:  # noqa: BLE001 - the tool reads the reason from the JSON line
        result = {"ok": False, "error": str(exc) or type(exc).__name__}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
