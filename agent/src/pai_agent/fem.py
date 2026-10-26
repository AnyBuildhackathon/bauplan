"""Finite element stress analysis of one printed part on its real shape: gmsh meshes it, CalculiX solves it.

Both binaries ship inside FreeCAD (they are what FreeCAD's FEM workbench runs), so the same
freecadcmd lookup finds them; `PAI_CCX` and `PAI_GMSH` override, and `ccx`/`gmsh` on PATH work too.
The part's STEP (or a closed STL) is meshed into quadratic tetrahedra (C3D10), moved into the
assembly frame with the same rotation and offset the assembly uses, then solved as linear static
for each load case.

Regions are the faces of the CAD model. gmsh keeps the face each surface triangle lies on, numbered
as in the STEP, which for a FreeCAD part is its FaceN, so a region names faces (`face_id`), the
faces on one side of the part (`face: z_min`), a round patch of the surface round a point (`near`,
whose result names the faces it touched) or a box. A force is spread over the region's area, a
pressure pushes along its normals, and the part's own weight loads every element, each as the
consistent nodal loads of the quadratic elements: Gauss integration over the six-node triangles, the
closed form over the ten-node tetrahedra.

Every result checks itself:
- held: each connected body must be held against all six rigid motions, the rank of the six-column
  rigid-body matrix of its held degrees of freedom; a loaded body that can still move stops the run
  with the free motion named (turning about an axis along X through a point), a loose one without
  load is left out;
- equilibrium: the reaction forces CalculiX prints for the held nodes must balance the loads to
  0.1 %, and a load that lands on held nodes is reported, since it goes straight into the support;
- mesh: the governing case runs again with 1.6 times smaller elements round its peak, and a peak
  that moves by more than 15 % depends on the mesh (a sharp corner, a point load) more than on the part;
- a watchdog reads the CalculiX output as it comes and stops it at the first error or at a
  displacement past ten times the part's size, instead of waiting out the time limit; a linear
  solve that ends with such a displacement fails the same way.

Printed plastic is not solid plastic. The modulus is the data sheet value times the plastic share
of the section (perimeters solid, the core at the infill), and two strengths judge the result:
the layer-plane strength against the von Mises stress, and the interlayer (Z) strength against the
tension across the layers, which is the stress along the print direction. The safety factor is the
smaller of the two. Peak stresses on the clamped and loaded nodes themselves are singular (a point
load or a perfect clamp has infinite stress in theory), so the reported maximum leaves those nodes out.

Units are millimetres, newtons and MPa throughout.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

TIMEOUT_S = 150
MAX_NODES = 60000
# gmsh's 10-node tetrahedron numbers its last two edge nodes the other way round from CalculiX.
_GMSH_TO_CCX = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]
AXES = {"x": 0, "y": 1, "z": 2}
# The four faces of a C3D10 tetrahedron (CalculiX order), outward wound, each followed by the
# mid-side nodes of its edges 0-1, 1-2 and 2-0: the six-node triangle of that face.
_FACES6 = np.array([[0, 2, 1, 6, 5, 4], [0, 1, 3, 4, 8, 7], [1, 2, 3, 5, 9, 8], [0, 3, 2, 7, 9, 6]])
# Six-point Gauss rule on a triangle, exact to degree 4: area coordinates and weights summing to one.
_GA, _GB = 0.445948490915965, 0.091576213509771
_RULE = np.array([[_GA, _GA, 1 - 2 * _GA], [_GA, 1 - 2 * _GA, _GA], [1 - 2 * _GA, _GA, _GA], [_GB, _GB, 1 - 2 * _GB], [_GB, 1 - 2 * _GB, _GB], [1 - 2 * _GB, _GB, _GB]])
_WEIGHTS = np.array([0.223381589678011] * 3 + [0.109951743655322] * 3)
# The mesh check reruns the governing case with elements this many times smaller round its peak, out to
# PEAK_BALL element sizes; a peak that moves by more than MESH_TOLERANCE depends on the mesh.
REFINE = 1.6
PEAK_BALL = 4.0
MESH_TOLERANCE = 0.15
# The reactions must balance the loads to this share of the load.
BALANCE_TOLERANCE = 0.001
# A displacement past this many times the part's size: it is not held, and the watchdog stops CalculiX.
RUNAWAY = 10.0
# The weight of 1 g/cm³ under one g, in N/mm³.
WEIGHT_N_MM3 = 9.80665e-6
# Nonlinear CalculiX steps print the largest displacement change of each iteration.
_DISPLACEMENT_LINE = re.compile(r"largest (?:increment of disp|correction to disp)\s*=\s*([-+0-9.eEdD]+)")


class FemUnavailable(RuntimeError):
    pass


class FemFailed(RuntimeError):
    pass


class FemUnheld(FemFailed):
    """A loaded body of the part can still move; `motions` names each free motion in words."""

    def __init__(self, message: str, motions: list[str]):
        super().__init__(message)
        self.motions = motions


@dataclass
class Mesh:
    """Quadratic tetrahedra and their outer surface as six-node triangles, each with the CAD face it lies on."""

    nodes: np.ndarray
    tets: np.ndarray
    tris: np.ndarray
    face_ids: np.ndarray
    h: float

    @property
    def size(self) -> float:
        return float(np.ptp(self.nodes, axis=0).max())

    def areas(self, tris: np.ndarray) -> np.ndarray:
        corners = self.nodes[self.tris[tris, :3]]
        return 0.5 * np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1)


@dataclass
class Region:
    """What a region selects: the nodes a support holds, the surface triangles a load acts on, and where that is in words."""

    nodes: np.ndarray
    tris: np.ndarray
    where: str
    # Where a load on it lands, when that differs from what a hold on it holds.
    load_where: str | None = None


@dataclass
class Model:
    """The resolved problem on one mesh: held degrees of freedom and, per load case, the nodal loads."""

    mesh: Mesh
    held: np.ndarray
    held_where: list[str]
    loads: list[np.ndarray] = field(default_factory=list)
    # Per case: the size of the load (the equilibrium check's reference), the nodes under a surface load, each load in words,
    # and the percentage of its forces and pressures on held nodes (the weight there is expected and not counted).
    scales: list[float] = field(default_factory=list)
    loaded: list[np.ndarray] = field(default_factory=list)
    rows: list[list[dict]] = field(default_factory=list)
    held_shares: list[float] = field(default_factory=list)
    # Loose bodies the hold check left out, then every note worth telling.
    left_out: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def find_tools() -> tuple[str, str] | None:
    """(gmsh, ccx) executables, or None when either is missing."""

    found = []
    for name, env in (("gmsh", "PAI_GMSH"), ("ccx", "PAI_CCX")):
        override = os.environ.get(env, "").strip()
        if override.lower() == "off":
            return None
        path = override if override and Path(override).is_file() else shutil.which(name)
        if not path:
            from pai_agent.freecad_run import find_freecadcmd

            freecad = find_freecadcmd()
            if freecad:
                sibling = Path(freecad).resolve().parent / name
                path = str(sibling) if sibling.is_file() else None
        if not path:
            return None
        found.append(path)
    return found[0], found[1]


def mesh_size(size_mm: list[float], min_wall_mm: float | None) -> float:
    """Element size: about 30 elements along the longest side, at least two through the thinnest wall."""

    longest = max(size_mm)
    h = longest / 30.0
    if min_wall_mm:
        h = min(h, max(min_wall_mm / 1.6, 0.4))
    return round(min(max(h, 0.4), 8.0), 3)


def _geo(geometry: Path, h: float, refine: tuple[list[float], float, float] | None = None) -> str:
    head = [
        "Mesh.ElementOrder = 2;",
        "Mesh.SecondOrderLinear = 1;",
        f"Mesh.CharacteristicLengthMax = {h:g};",
        f"Mesh.CharacteristicLengthMin = {h / 5:g};",
        "Mesh.MshFileVersion = 2.2;",
        "Mesh.Optimize = 1;",
    ]
    if refine is not None:
        # Smaller elements inside a ball (the mesh check round a peak), blending back to h over two elements.
        (x, y, z), radius, inner = refine
        head += [
            "Field[1] = Ball;",
            f"Field[1].XCenter = {x:g};",
            f"Field[1].YCenter = {y:g};",
            f"Field[1].ZCenter = {z:g};",
            f"Field[1].Radius = {radius:g};",
            f"Field[1].Thickness = {2 * h:g};",
            f"Field[1].VIn = {inner:g};",
            f"Field[1].VOut = {h:g};",
            "Background Field = 1;",
        ]
    if geometry.suffix.lower() in {".step", ".stp"}:
        return "\n".join(
            [
                'SetFactory("OpenCASCADE");',
                f'Merge "{geometry.name}";',
                # Touching solids share their faces, so a part made of several bodies meshes as one.
                "solids() = Volume{:};",
                "If (#solids() > 1)",
                "  BooleanFragments{ Volume{solids()}; Delete; }{}",
                "EndIf",
                *head,
            ]
        )
    return "\n".join(
        [
            f'Merge "{geometry.name}";',
            "ClassifySurfaces{Pi/4, 1, 1, Pi};",
            "CreateGeometry;",
            "Surface Loop(1) = Surface{:};",
            "Volume(1) = {1};",
            *head,
        ]
    )


def _read_msh(path: Path) -> tuple[np.ndarray, np.ndarray, dict[tuple[int, ...], int]]:
    """Nodes, CalculiX-ordered C3D10 connectivity, and the CAD face of every surface triangle (sorted corners to face)."""

    lines = path.read_text().splitlines()
    nodes_at = lines.index("$Nodes")
    count = int(lines[nodes_at + 1])
    ids = np.empty(count, dtype=np.int64)
    xyz = np.empty((count, 3))
    for i in range(count):
        parts = lines[nodes_at + 2 + i].split()
        ids[i] = int(parts[0])
        xyz[i] = [float(parts[1]), float(parts[2]), float(parts[3])]
    index = {int(v): i for i, v in enumerate(ids)}
    elements_at = lines.index("$Elements")
    total = int(lines[elements_at + 1])
    tets = []
    faces = {}
    for i in range(total):
        parts = lines[elements_at + 2 + i].split()
        if parts[1] not in {"9", "11"}:
            continue
        tags = int(parts[2])
        if parts[1] == "11":
            tets.append([index[int(v)] for v in parts[3 + tags : 13 + tags]])
        else:
            # A six-node surface triangle: its second tag is the geometric surface, the CAD face it lies on.
            corners = tuple(sorted(index[int(v)] for v in parts[3 + tags : 6 + tags]))
            faces[corners] = int(parts[4]) if tags >= 2 else 0
    if not tets:
        raise FemFailed("gmsh made no volume mesh: the shape is not a closed solid.")
    return xyz, np.array(tets, dtype=np.int64)[:, _GMSH_TO_CCX], faces


def _boundary(tets: np.ndarray, faces: dict[tuple[int, ...], int]) -> tuple[np.ndarray, np.ndarray]:
    """Outer six-node triangles of the tetrahedra (corners outward wound) and the CAD face of each, 0 where unknown."""

    every = tets[:, _FACES6].reshape(-1, 6)
    keys = np.sort(every[:, :3], axis=1)
    _, first, counts = np.unique(keys, axis=0, return_index=True, return_counts=True)
    outer = every[first[counts == 1]]
    ids = np.array([faces.get(tuple(sorted(row)), 0) for row in outer[:, :3].tolist()], dtype=np.int64)
    return outer, ids


def mesh(geometry: Path, work: Path, h: float, gmsh: str, refine: tuple[list[float], float, float] | None = None) -> Mesh:
    """Quadratic tetrahedra of the solid and their surface; a coarser size when the mesh would pass MAX_NODES.

    refine is (centre, radius, element size) of a ball in the part's own frame meshed finer.
    """

    work.mkdir(parents=True, exist_ok=True)
    local = work / ("part" + geometry.suffix.lower())
    shutil.copyfile(geometry, local)
    for attempt in range(3):
        (work / "mesh.geo").write_text(_geo(local, h, refine), encoding="utf-8")
        try:
            done = subprocess.run([gmsh, "mesh.geo", "-3", "-o", "mesh.msh", "-v", "1", "-nt", "2"], cwd=work, capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            raise FemFailed(f"gmsh ran past {TIMEOUT_S} s meshing it at {h:g} mm.") from exc
        if done.returncode != 0 or not (work / "mesh.msh").is_file():
            raise FemFailed("gmsh failed: " + ((done.stderr or done.stdout).strip().splitlines() or ["no output"])[-1][:200])
        nodes, tets, faces = _read_msh(work / "mesh.msh")
        if len(nodes) <= MAX_NODES or attempt == 2:
            break
        h *= (len(nodes) / MAX_NODES) ** (1 / 3) * 1.1
    tris, face_ids = _boundary(tets, faces)
    return Mesh(nodes, tets, tris, face_ids, round(h, 3))


def _subset(mesh: Mesh, keep: np.ndarray) -> tuple[Mesh, np.ndarray]:
    """The mesh of the kept tetrahedra only, and the old-to-new node numbers (-1 for a node that went)."""

    tets = mesh.tets[keep]
    used = np.unique(tets)
    remap = -np.ones(len(mesh.nodes), dtype=np.int64)
    remap[used] = np.arange(len(used))
    inside = np.all(remap[mesh.tris] >= 0, axis=1)
    return Mesh(mesh.nodes[used], remap[tets], remap[mesh.tris[inside]], mesh.face_ids[inside], mesh.h), remap


def _bodies(tets: np.ndarray, count: int) -> np.ndarray:
    """A body label per node (the lowest node number of its piece): tetrahedra that share a node are one body."""

    label = np.arange(count)
    while True:
        low = np.repeat(label[tets].min(axis=1, keepdims=True), tets.shape[1], axis=1)
        lower = label.copy()
        np.minimum.at(lower, tets, low)
        lower = lower[lower]
        if np.array_equal(lower, label):
            return label
        label = lower


def _closest_points(corners: np.ndarray, point: np.ndarray) -> np.ndarray:
    """The point of each triangle (k, 3, 3) closest to `point`, by the Voronoi regions of its corners and edges."""

    a, b, c = corners[:, 0], corners[:, 1], corners[:, 2]
    ab, ac = b - a, c - a
    ap, bp, cp = point - a, point - b, point - c
    d1, d2 = np.einsum("kd,kd->k", ab, ap), np.einsum("kd,kd->k", ac, ap)
    d3, d4 = np.einsum("kd,kd->k", ab, bp), np.einsum("kd,kd->k", ac, bp)
    d5, d6 = np.einsum("kd,kd->k", ab, cp), np.einsum("kd,kd->k", ac, cp)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    with np.errstate(divide="ignore", invalid="ignore"):
        on_ab = a + ab * (d1 / (d1 - d3))[:, None]
        on_ac = a + ac * (d2 / (d2 - d6))[:, None]
        on_bc = b + (c - b) * ((d4 - d3) / ((d4 - d3) + (d5 - d6)))[:, None]
        total = va + vb + vc
        inside = a + ab * (vb / total)[:, None] + ac * (vc / total)[:, None]
    regions = [
        (d1 <= 0) & (d2 <= 0),
        (d3 >= 0) & (d4 <= d3),
        (vc <= 0) & (d1 >= 0) & (d3 <= 0),
        (d6 >= 0) & (d5 <= d6),
        (vb <= 0) & (d2 >= 0) & (d6 <= 0),
        (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0),
    ]
    choices = [a, b, on_ab, c, on_ac, on_bc]
    return np.select([r[:, None] for r in regions], choices, default=inside)


def _where(mesh: Mesh, tris: np.ndarray) -> str:
    """The CAD faces of the triangles, largest share first, and their area: 'face 8, 1772 mm²'."""

    if len(tris) == 0:
        return "no surface"
    area = mesh.areas(tris)
    shares = np.bincount(mesh.face_ids[tris], weights=area)
    faces = [int(f) for f in np.argsort(-shares) if shares[f] > 0 and f > 0]
    total = f"{area.sum():.0f} mm²"
    if not faces:
        return total
    named = [str(f) for f in faces[:6]] + ([f"{len(faces) - 6} more"] if len(faces) > 6 else [])
    listed = named[0] if len(named) == 1 else ", ".join(named[:-1]) + " and " + named[-1]
    return ("face " if len(faces) == 1 else "faces ") + listed + " (" + total + ")"


def _point(v: np.ndarray) -> str:
    # Adding 0.0 turns a rounded -0.0 into 0.0.
    return "(" + ", ".join(f"{round(float(c), 1) + 0.0:.1f}" for c in v) + ")"


def resolve(mesh: Mesh, region: dict, h: float) -> Region:
    """The nodes and surface triangles of a region: CAD faces by number, the faces on one side, a round patch, or a box."""

    if "face_id" in region:
        wanted = sorted({int(v) for v in np.atleast_1d(region["face_id"])})
        known = np.unique(mesh.face_ids[mesh.face_ids > 0])
        missing = [f for f in wanted if f not in set(known.tolist())]
        if missing:
            raise ValueError(f"The part has no outer face {missing[0]}: its faces are numbered 1 to {int(known.max()) if len(known) else 0}.")
        tris = np.nonzero(np.isin(mesh.face_ids, wanted))[0]
        return Region(np.unique(mesh.tris[tris]), tris, _where(mesh, tris))
    if "face" in region:
        side = str(region["face"]).lower()
        values = mesh.nodes[:, AXES[side[0]]]
        depth = float(region.get("depth_mm") or 0.1)
        slab = values <= values.min() + depth if side.endswith("min") else values >= values.max() - depth
        flat = slab[mesh.tris].all(axis=1)
        # The CAD faces lying wholly on that side; a face only partly there (a slope, a curve) stays out.
        partly = np.unique(mesh.face_ids[~flat])
        tris = np.nonzero(flat & (mesh.face_ids > 0) & ~np.isin(mesh.face_ids, partly))[0]
        if len(tris) == 0:
            tris = np.nonzero(flat)[0]
        if len(tris):
            return Region(np.unique(mesh.tris[tris]), tris, _where(mesh, tris))
        # No face lies there (a cylinder on its side): the nodes along that side hold, the triangles touching them carry a load.
        nodes = np.nonzero(slab)[0]
        touching = np.nonzero(slab[mesh.tris].any(axis=1))[0]
        return Region(nodes, touching, f"{len(nodes)} nodes along its {side} edge, where no face lies", _where(mesh, touching) + f" along its {side} edge")
    if "near" in region:
        point = np.array(region["near"], dtype=float)
        radius = float(region.get("radius_mm") or 3 * h)
        corners = mesh.nodes[mesh.tris[:, :3]]
        closest = _closest_points(corners, point)
        # A degenerate sliver has no closest point; it never counts as near.
        gap = np.nan_to_num(np.linalg.norm(closest - point, axis=1), nan=np.inf)
        nearest = int(np.argmin(gap))
        if gap[nearest] > radius:
            # The point sits off the part (a load centred in the air above it): take the patch round the nearest point of the surface.
            point = closest[nearest]
            gap = np.nan_to_num(np.linalg.norm(_closest_points(corners, point) - point, axis=1), nan=np.inf)
        tris = np.nonzero(gap <= radius)[0]
        return Region(np.unique(mesh.tris[tris]), tris, f"a {radius:.1f} mm patch round {_point(point)} on {_where(mesh, tris)}")
    if "box" in region:
        lo, hi = np.array(region["box"][:3], dtype=float), np.array(region["box"][3:], dtype=float)
        inside = np.all((mesh.nodes >= lo) & (mesh.nodes <= hi), axis=1)
        tris = np.nonzero(inside[mesh.tris].all(axis=1))[0]
        if len(tris) == 0:
            tris = np.nonzero(inside[mesh.tris].any(axis=1))[0]
        # A box holds everything inside it, the material within too.
        return Region(np.nonzero(inside)[0], tris, f"the box {_point(lo)} to {_point(hi)}: " + _where(mesh, tris))
    raise ValueError("A region needs face_id, face, near or box.")


def _tri6(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Six-node triangle shape functions at area coordinates (g, 3), and their derivatives along L2 and L3."""

    l1, l2, l3 = points.T
    zero = np.zeros_like(l1)
    shape = np.stack([l1 * (2 * l1 - 1), l2 * (2 * l2 - 1), l3 * (2 * l3 - 1), 4 * l1 * l2, 4 * l2 * l3, 4 * l3 * l1], axis=1)
    d2 = np.stack([1 - 4 * l1, 4 * l2 - 1, zero, 4 * (l1 - l2), 4 * l3, -4 * l3], axis=1)
    d3 = np.stack([1 - 4 * l1, zero, 4 * l3 - 1, -4 * l2, 4 * l2, 4 * (l1 - l3)], axis=1)
    return shape, d2, d3


def surface_integrals(mesh: Mesh, tris: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each triangle's six shape functions integrated over its area (k, 6) and over its outward area vector (k, 6, 3)."""

    x = mesh.nodes[mesh.tris[tris]]
    shape, d2, d3 = _tri6(_RULE)
    tangent2 = np.einsum("gi,kid->kgd", d2, x)
    tangent3 = np.einsum("gi,kid->kgd", d3, x)
    # Outward normal times the area at each Gauss point; the reference triangle has area 1/2.
    area = np.cross(tangent2, tangent3) * (_WEIGHTS / 2.0)[None, :, None]
    return np.einsum("gi,kg->ki", shape, np.linalg.norm(area, axis=2)), np.einsum("gi,kgd->kid", shape, area)


def force_load(mesh: Mesh, region: Region, force: list[float]) -> np.ndarray:
    """Nodal loads (n, 3) of a force spread evenly over the region's area: the traction F / A on each triangle's nodes."""

    weights, _vector = surface_integrals(mesh, region.tris)
    load = np.zeros((len(mesh.nodes), 3))
    np.add.at(load, mesh.tris[region.tris].ravel(), (weights.ravel() / weights.sum())[:, None] * np.asarray(force, dtype=float))
    return load


def pressure_load(mesh: Mesh, region: Region, pressure_mpa: float) -> np.ndarray:
    """Nodal loads (n, 3) of a pressure on the region, pushing into the part along its normals (negative pulls)."""

    _weights, vector = surface_integrals(mesh, region.tris)
    load = np.zeros((len(mesh.nodes), 3))
    np.add.at(load, mesh.tris[region.tris].ravel(), -pressure_mpa * vector.reshape(-1, 3))
    return load


def weight_load(mesh: Mesh, density_g_cm3: float, g: float) -> np.ndarray:
    """Nodal loads (n, 3) of the part's own weight at g times gravity, down -Z.

    The consistent loads of a straight ten-node tetrahedron: -1/20 of its weight on each corner and
    1/5 on each mid-side node (the integrals of its shape functions over its volume).
    """

    corners = mesh.nodes[mesh.tets[:, :4]]
    volume = np.abs(np.einsum("kd,kd->k", np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), corners[:, 3] - corners[:, 0])) / 6.0
    share = np.array([-1 / 20] * 4 + [1 / 5] * 6)
    load = np.zeros((len(mesh.nodes), 3))
    np.add.at(load[:, 2], mesh.tets.ravel(), (-(volume * density_g_cm3 * WEIGHT_N_MM3 * g)[:, None] * share).ravel())
    return load


def _along(vector: np.ndarray) -> str:
    unit = vector / np.linalg.norm(vector)
    axis = int(np.argmax(np.abs(unit)))
    # Within ten degrees of an axis it is that axis.
    if abs(unit[axis]) >= 0.985:
        return "along " + "XYZ"[axis]
    return "along (" + ", ".join(f"{float(c):.2f}" for c in unit) + ")"


def free_motions(points: np.ndarray, held: np.ndarray) -> list[str]:
    """The rigid motions that the held degrees of freedom of a body leave free, in words; empty when it is held.

    A small rigid motion moves a point x by a + w x (x - c). Each held degree of freedom, a node and a
    direction, is one row of that motion's component there: a matrix with six columns, (a, w). Rank six
    holds the body; the null space of the matrix is what the supports do not stop, read as slides
    (no turn) and turns, with the axis through the point that does not move.
    """

    centre = points.mean(axis=0)
    scale = max(float(np.ptp(points, axis=0).max()), 1e-9)
    x = (points - centre) / scale
    one, zero = np.ones(len(x)), np.zeros(len(x))
    # u_x = a_x + w_y z - w_z y, u_y = a_y + w_z x - w_x z, u_z = a_z + w_x y - w_y x.
    rows = [
        np.stack([one, zero, zero, zero, x[:, 2], -x[:, 1]], axis=1),
        np.stack([zero, one, zero, -x[:, 2], zero, x[:, 0]], axis=1),
        np.stack([zero, zero, one, x[:, 1], -x[:, 0], zero], axis=1),
    ]
    matrix = np.concatenate([rows[d][held[:, d]] for d in range(3)])
    if len(matrix) == 0:
        return ["move and turn freely, since nothing holds it"]
    values, vectors = np.linalg.eigh(matrix.T @ matrix)
    free = vectors[:, values <= 1e-12 * values.max()]
    if free.shape[1] == 0:
        return []
    _u, spin, combos = np.linalg.svd(free[3:])
    turning = int((spin > 1e-6).sum())
    slides = free[:3] @ combos[turning:].T
    turns = free @ combos[:turning].T
    words = []
    if slides.shape[1] == 3:
        words.append("move in any direction")
    elif slides.shape[1] == 2:
        normal = np.cross(slides[:, 0], slides[:, 1])
        axis = int(np.argmax(np.abs(normal)))
        plane = [a for a in "XYZ" if a != "XYZ"[axis]]
        words.append(f"slide along {plane[0]} and {plane[1]}" if abs(normal[axis]) / np.linalg.norm(normal) >= 0.985 else "slide in a plane " + _along(normal).replace("along", "across"))
    elif slides.shape[1] == 1:
        words.append("slide " + _along(slides[:, 0]))
    if turning == 0:
        return words
    # The point that stays put solves a + w x p = 0 for every free turn (least squares; exact for a single turn).
    spins = turns[3:].T
    cross = np.array([[[0, -w[2], w[1]], [w[2], 0, -w[0]], [-w[1], w[0], 0]] for w in spins]).reshape(-1, 3)
    still, *_ = np.linalg.lstsq(cross, -turns[:3].T.ravel(), rcond=None)
    through = "" if slides.shape[1] else " through " + _point(centre + scale * still) + " mm"
    if turning == 1:
        words.append("turn about an axis " + _along(spins[0]) + through)
    elif slides.shape[1]:
        words.append("turn freely")
    else:
        words.append("turn in any direction about " + _point(centre + scale * still) + " mm" if turning == 3 else "turn two ways about " + _point(centre + scale * still) + " mm")
    return words


def hold_check(mesh: Mesh, held: np.ndarray, loads: list[np.ndarray]) -> tuple[np.ndarray, list[str]]:
    """Which tetrahedra to keep: every connected body that carries a load must be held against all six rigid motions.

    A loaded body that can still move raises FemUnheld with the free motion; a loose body without a
    load is left out with a note, since it would only make the system singular.
    """

    labels = _bodies(mesh.tets, len(mesh.nodes))
    owner = labels[mesh.tets[:, 0]]
    bodies, counts = np.unique(owner, return_counts=True)
    bodies = bodies[np.argsort(-counts)]
    loaded = np.zeros(len(mesh.nodes), dtype=bool)
    for load in loads:
        loaded |= np.abs(load).sum(axis=1) > 0
    keep = np.ones(len(mesh.tets), dtype=bool)
    notes = []
    for index, body in enumerate(bodies):
        nodes = np.unique(mesh.tets[owner == body])
        motions = free_motions(mesh.nodes[nodes], held[nodes])
        if not motions:
            continue
        centre = _point(mesh.nodes[nodes].mean(axis=0))
        name = "The part" if len(bodies) == 1 else f"Body {index + 1} of {len(bodies)}, round {centre} mm,"
        if loaded[nodes].any():
            if held[nodes].any():
                fix = "Hold it on a face with some area (a whole face, or a near patch with radius_mm), not along a line or at a point."
            else:
                fix = "The held region lies off it: put the hold on the part." if len(bodies) == 1 else "Hold it too, or join it to the held body."
            raise FemUnheld(f"{name} is not held: it can {' and '.join(motions)}. {fix}", motions)
        keep[owner == body] = False
        notes.append(f"{name} is not held and carries no load, so it is left out.")
    return keep, notes


def _nset(name: str, nodes: np.ndarray) -> list[str]:
    return [f"*NSET, NSET={name}"] + [", ".join(str(int(n) + 1) for n in nodes[i : i + 12]) for i in range(0, len(nodes), 12)]


def _write_inp(path: Path, mesh: Mesh, modulus: float, poisson: float, held: np.ndarray, load: np.ndarray) -> None:
    """The CalculiX deck: held degrees of freedom as *BOUNDARY, the nodal loads on the free ones as *CLOAD, the reaction total printed."""

    out = ["*NODE, NSET=NALL"]
    out += [f"{i + 1}, {x:.6f}, {y:.6f}, {z:.6f}" for i, (x, y, z) in enumerate(mesh.nodes)]
    out.append("*ELEMENT, TYPE=C3D10, ELSET=EALL")
    out += [f"{e + 1}, " + ", ".join(str(int(n) + 1) for n in row) for e, row in enumerate(mesh.tets)]
    fixed = np.nonzero(held.any(axis=1))[0]
    out += _nset("FIX", fixed)
    boundary = ["FIX, 1, 3"]
    if not held[fixed].all():
        boundary = []
        for dof in range(3):
            if held[:, dof].any():
                out += _nset(f"FIX{dof + 1}", np.nonzero(held[:, dof])[0])
                boundary.append(f"FIX{dof + 1}, {dof + 1}, {dof + 1}")
    out += ["*MATERIAL, NAME=PRINTED", "*ELASTIC", f"{modulus:.4f}, {poisson:.4f}", "*SOLID SECTION, ELSET=EALL, MATERIAL=PRINTED"]
    out += ["*BOUNDARY", *boundary, "*STEP", "*STATIC", "*CLOAD"]
    # A load on a held degree of freedom goes straight into the support; CalculiX would drop it anyway.
    nodes, dofs = np.nonzero((np.abs(load) > 1e-12 * max(float(np.abs(load).max()), 1e-30)) & ~held)
    out += [f"{int(n) + 1}, {int(d) + 1}, {load[n, d]:.8g}" for n, d in zip(nodes, dofs)]
    out += ["*NODE PRINT, NSET=FIX, TOTALS=ONLY", "RF", "*NODE FILE", "U", "*EL FILE", "S", "*END STEP"]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _read_frd(path: Path, count: int) -> tuple[np.ndarray, np.ndarray]:
    """Nodal displacement (n, 3) and stress (n, 6: xx yy zz xy yz zx) from the CalculiX result file."""

    disp = np.zeros((count, 3))
    stress = np.zeros((count, 6))
    target = None
    for line in path.read_text(errors="ignore").splitlines():
        if line.startswith(" -4"):
            name = line[3:].split()[0]
            target = disp if name == "DISP" else stress if name == "STRESS" else None
            continue
        if line.startswith(" -3"):
            target = None
            continue
        if target is not None and line.startswith(" -1"):
            node = int(line[3:13]) - 1
            width = target.shape[1]
            values = [float(line[13 + 12 * i : 25 + 12 * i]) for i in range(width)]
            if 0 <= node < count:
                target[node] = values
    return disp, stress


def _read_reaction(path: Path) -> np.ndarray:
    """The total reaction force on the held nodes, from the `total force` lines CalculiX writes to the .dat file."""

    lines = path.read_text(errors="ignore").splitlines() if path.is_file() else []
    for at, line in enumerate(lines):
        if line.strip().startswith("total force"):
            for row in lines[at + 1 : at + 4]:
                values = row.split()
                if len(values) == 3:
                    return np.array([float(v.replace("D", "E")) for v in values])
    raise FemFailed("CalculiX printed no reaction forces for the held nodes.")


def run_ccx(ccx: str, work: Path, env: dict, size_mm: float, timeout_s: float = TIMEOUT_S) -> tuple[int, str]:
    """Runs CalculiX on job.inp and reads its output as it comes; returns the exit code and the output.

    The watchdog stops it at the first error line, as soon as a reported displacement passes RUNAWAY
    times the part's size (a nonlinear step that runs away because the part is not held), and at the
    time limit, instead of letting a lost run sit out the limit.
    """

    process = subprocess.Popen([ccx, "-i", "job"], cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", env=env)
    lines: queue.Queue = queue.Queue()

    def pump() -> None:
        assert process.stdout is not None
        for text in process.stdout:
            lines.put(text)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + timeout_s
    log = []
    try:
        while True:
            try:
                line = lines.get(timeout=max(deadline - time.monotonic(), 0.0))
            except queue.Empty:
                raise FemFailed(f"CalculiX ran past {timeout_s:.0f} s and was stopped.") from None
            if line is None:
                break
            log.append(line)
            if "*ERROR" in line.upper():
                raise FemFailed("CalculiX stopped: " + line.strip()[:200])
            moved = _DISPLACEMENT_LINE.search(line)
            if moved and abs(float(moved.group(1).upper().replace("D", "E"))) > RUNAWAY * size_mm:
                raise FemFailed(
                    f"CalculiX stopped: the displacement ran away past {RUNAWAY:g} times the part's size ({size_mm:.0f} mm), "
                    "so the part is not held against some motion."
                )
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
    return process.returncode, "".join(log)


def von_mises(s: np.ndarray) -> np.ndarray:
    xx, yy, zz, xy, yz, zx = (s[:, i] for i in range(6))
    return np.sqrt(0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2) + 3.0 * (xy**2 + yz**2 + zx**2))


def normal_stress(s: np.ndarray, direction: np.ndarray) -> np.ndarray:
    """Stress along a unit direction: n . sigma . n, tension positive."""

    n = direction / max(np.linalg.norm(direction), 1e-12)
    xx, yy, zz, xy, yz, zx = (s[:, i] for i in range(6))
    return xx * n[0] ** 2 + yy * n[1] ** 2 + zz * n[2] ** 2 + 2 * (xy * n[0] * n[1] + yz * n[1] * n[2] + zx * n[2] * n[0])


def solve(mesh: Mesh, props: dict, held: np.ndarray, load: np.ndarray, work: Path, ccx: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One linear static solve: nodal displacement (n, 3), stress (n, 6), and the total reaction force on the held nodes."""

    work.mkdir(parents=True, exist_ok=True)
    for stale in work.glob("job.*"):
        stale.unlink()
    _write_inp(work / "job.inp", mesh, props["modulus_mpa"], props["poisson"], held, load)
    env = {**{k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "LANG"}}, "OMP_NUM_THREADS": "2", "CCX_NPROC_EQUATION_SOLVER": "2"}
    code, log = run_ccx(ccx, work, env, mesh.size)
    frd = work / "job.frd"
    if code != 0 or not frd.is_file() or frd.stat().st_size < 200:
        tail = [line for line in log.splitlines() if "ERROR" in line.upper()] or log.strip().splitlines() or ["no output"]
        raise FemFailed("CalculiX failed: " + tail[-1].strip()[:200])
    disp, stress = _read_frd(frd, len(mesh.nodes))
    moved = float(np.linalg.norm(disp, axis=1).max())
    if moved > RUNAWAY * mesh.size:
        raise FemFailed(
            f"The part moves {moved:.3g} mm under the load, more than {RUNAWAY:g} times its size ({mesh.size:.0f} mm): "
            "it is barely held (along a line or at a point) or the load is far too big, so its stresses would mean nothing."
        )
    return disp, stress, _read_reaction(work / "job.dat")


def colour_map(value: np.ndarray) -> np.ndarray:
    """0 (no stress) to 1 (at the allowable stress) as blue, cyan, green, yellow, red; above 1 stays red."""

    stops = np.array([[0.16, 0.33, 0.85], [0.10, 0.74, 0.85], [0.18, 0.80, 0.44], [0.98, 0.80, 0.18], [0.93, 0.20, 0.20]])
    t = np.clip(value, 0.0, 1.0) * (len(stops) - 1)
    i = np.minimum(t.astype(int), len(stops) - 2)
    f = (t - i)[:, None]
    return stops[i] * (1 - f) + stops[i + 1] * f


def write_glb(path: Path, nodes: np.ndarray, triangles: np.ndarray, colours: np.ndarray, name: str) -> None:
    """A vertex-coloured GLB of the stressed surface (flat-shaded: three vertices per triangle)."""

    positions = nodes[triangles].reshape(-1, 3).astype(np.float32)
    rgb = colours[triangles].reshape(-1, 3).astype(np.float32)
    a, b, c = positions[0::3], positions[1::3], positions[2::3]
    normal = np.cross(b - a, c - a)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    normals = np.repeat(normal, 3, axis=0).astype(np.float32)
    rgba = np.concatenate([rgb, np.ones((len(rgb), 1), dtype=np.float32)], axis=1)
    blobs = [positions.tobytes(), normals.tobytes(), rgba.tobytes()]
    offsets = np.cumsum([0] + [len(b) for b in blobs]).tolist()
    count = len(positions)
    gltf = {
        "asset": {"version": "2.0", "generator": "AnyBuild FEM"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2}, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0, "roughnessFactor": 0.7}, "doubleSided": True}],
        "buffers": [{"byteLength": offsets[-1]}],
        "bufferViews": [{"buffer": 0, "byteOffset": offsets[i], "byteLength": len(blobs[i]), "target": 34962} for i in range(3)],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3", "min": positions.min(axis=0).tolist(), "max": positions.max(axis=0).tolist()},
            {"bufferView": 1, "componentType": 5126, "count": count, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": count, "type": "VEC4"},
        ],
    }
    body = b"".join(blobs)
    body += b"\x00" * (-len(body) % 4)
    header = json.dumps(gltf, separators=(",", ":")).encode()
    header += b" " * (-len(header) % 4)
    chunks = struct.pack("<I4s", len(header), b"JSON") + header + struct.pack("<I4s", len(body), b"BIN\x00") + body
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)


def _vector(v: np.ndarray, digits: int = 2) -> list[float]:
    return [round(float(c), digits) + 0.0 for c in v]


def prepare(mesh: Mesh, fixed: list[dict], cases: list[dict], props: dict, h: float) -> Model:
    """Resolves the held regions and each case's loads on the mesh, then keeps only what is held (`hold_check`).

    A case is {name, loads: [{region, force_n} or {region, pressure_mpa}], gravity_g}, or the short
    {name, region, force_n} for one force; gravity_g adds the part's own weight at that many g.
    """

    held = np.zeros((len(mesh.nodes), 3), dtype=bool)
    held_where = []
    for spec in fixed:
        region = resolve(mesh, spec, h)
        held[region.nodes] = True
        held_where.append(region.where)
    model = Model(mesh, held, held_where)
    for case in cases:
        name = case.get("name") or f"case {len(model.loads) + 1}"
        total = np.zeros((len(mesh.nodes), 3))
        loaded, rows, scale, on_held = [], [], 0.0, np.zeros(3)
        items = case.get("loads")
        if items is None:
            items = [{"region": case["region"], "force_n": case["force_n"]}] if "region" in case else []
        for item in items:
            region = resolve(mesh, item["region"], h)
            where = region.load_where or region.where
            if len(region.tris) == 0:
                raise ValueError(f"Load case {name}: {where} has no surface to load.")
            if item.get("pressure_mpa") is not None:
                load = pressure_load(mesh, region, float(item["pressure_mpa"]))
                scale = max(scale, abs(float(item["pressure_mpa"])) * float(mesh.areas(region.tris).sum()))
                text = f"{float(item['pressure_mpa']):g} MPa on {where}"
            else:
                load = force_load(mesh, region, item["force_n"])
                scale = max(scale, float(np.linalg.norm(item["force_n"])))
                text = f"{float(np.linalg.norm(item['force_n'])):.1f} N on {where}"
            if np.abs(load[~held]).sum() <= 1e-9 * np.abs(load).sum():
                raise ValueError(f"Load case {name}: the loaded region is inside the clamp.")
            total += load
            on_held += np.where(held, load, 0.0).sum(axis=0)
            loaded.append(region.nodes)
            rows.append({"where": text, "force_n": _vector(load.sum(axis=0))})
        model.held_shares.append(round(float(np.linalg.norm(on_held)) / scale * 100, 2) if scale > 0 else 0.0)
        if case.get("gravity_g"):
            if not props.get("density_g_cm3"):
                raise ValueError(f"Load case {name}: its own weight needs the material's density.")
            load = weight_load(mesh, float(props["density_g_cm3"]) * float(props.get("fill") or 1.0), float(case["gravity_g"]))
            total += load
            scale = max(scale, float(np.linalg.norm(load.sum(axis=0))))
            rows.append({"where": f"its own weight at {float(case['gravity_g']):g} g", "force_n": _vector(load.sum(axis=0), 3)})
        if not rows:
            raise ValueError(f"Load case {name} has no load: give it a force_n, a pressure_mpa or gravity_g.")
        model.loads.append(total)
        model.loaded.append(np.unique(np.concatenate(loaded)) if loaded else np.zeros(0, dtype=np.int64))
        model.rows.append(rows)
        model.scales.append(scale)
    keep, model.left_out = hold_check(mesh, held, model.loads)
    # Only the kept bodies' nodes go to CalculiX: a node without an element would have no stiffness.
    model.mesh, remap = _subset(mesh, keep)
    alive = remap >= 0
    model.held = held[alive]
    model.loads = [load[alive] for load in model.loads]
    model.loaded = [remap[nodes][remap[nodes] >= 0] for nodes in model.loaded]
    model.notes = list(model.left_out)
    return model


def _peaks(stress: np.ndarray, direction: np.ndarray, away: np.ndarray) -> tuple[np.ndarray, float, float, int, int]:
    """Von Mises at every node, the largest von Mises and tension across the layers away from supports and loads, and their nodes."""

    vm = von_mises(stress)
    across = np.maximum(normal_stress(stress, direction), 0.0)
    pick = away if away.any() else np.ones(len(vm), dtype=bool)
    vm_at, across_at = int(np.argmax(np.where(pick, vm, -1.0))), int(np.argmax(np.where(pick, across, -1.0)))
    return vm, float(vm[vm_at]), float(across[across_at]), vm_at, across_at


def _away(model: Model, index: int) -> np.ndarray:
    away = ~model.held.any(axis=1)
    away[model.loaded[index]] = False
    return away


def _balance(model: Model, index: int, reaction: np.ndarray) -> dict:
    """The equilibrium check of one case: the supports' reactions against the loads the part carries."""

    load, held = model.loads[index], model.held
    applied = np.where(held, 0.0, load)
    # CalculiX's total runs over the held nodes; a held node's free directions add their own loads to it.
    pushed = reaction - applied[held.any(axis=1)].sum(axis=0)
    carried = applied.sum(axis=0)
    lost = np.where(held, load, 0.0).sum(axis=0)
    scale = max(model.scales[index], 1e-12)
    error = float(np.linalg.norm(pushed + carried)) / scale
    return {
        "reaction_n": _vector(pushed, 3),
        "load_n": _vector(carried, 3),
        "error_pct": round(error * 100, 4),
        "ok": error <= BALANCE_TOLERANCE,
        "on_held_n": _vector(lost, 3),
        "on_held_pct": model.held_shares[index],
    }


def _mesh_check(
    geometry: Path, transform, props: dict, fixed: list[dict], case: dict, direction: np.ndarray, work: Path, fine: Mesh, governs: str, peak: float, at: np.ndarray, gmsh: str, ccx: str
) -> dict:
    """The governing case once more with REFINE times smaller elements round its peak, and how far the peak moves.

    Refining only round the peak keeps the check about as cheap as the first solve and tests exactly the
    number that sets the safety factor; a coarser mesh everywhere would instead put a thin wall's
    two elements down to one and flag a peak that is in fact settled.
    """

    inner = round(fine.h / REFINE, 3)
    # gmsh meshes the part in its own frame.
    centre = np.asarray(at, dtype=float)
    if transform is not None:
        centre = np.array(transform[0], dtype=float).T @ (centre - np.array(transform[1], dtype=float))
    try:
        finer = _placed(mesh(geometry, work, fine.h, gmsh, (centre.tolist(), PEAK_BALL * fine.h, inner)), transform)
        if finer.h != fine.h:
            raise FemFailed(f"the finer mesh would pass {MAX_NODES} nodes")
        model = prepare(finer, fixed, [case], props, fine.h)
        _disp, stress, _reaction = solve(model.mesh, props, model.held, model.loads[0], work / "case", ccx)
    except (FemFailed, ValueError) as exc:
        return {"ok": None, "element_size_mm": inner, "text": f"Mesh check not run: {exc}"}
    _vm, vm_max, across_max, _vm_at, _across_at = _peaks(stress, direction, _away(model, 0))
    other = across_max if governs == "layers" else vm_max
    change = other / peak - 1.0 if peak > 0 else 0.0
    ok = abs(change) <= MESH_TOLERANCE
    quantity = "tension across the layers" if governs == "layers" else "von Mises stress"
    text = f"Mesh check: the {quantity} peaks at {peak:.1f} MPa on the {fine.h:.2g} mm mesh and at {other:.1f} MPa with {inner:.2g} mm elements round the peak ({change * 100:+.0f} %)."
    if not ok and change > 0:
        text += (
            " The peak depends on the mesh: it sits at a sharp corner or right at a load or support, where the number keeps growing as the elements get smaller. "
            "Round that corner, spread the load, or judge the stress a little away from it."
        )
    elif not ok:
        text += " The peak depends on the mesh: smaller elements give less there, so the first number overstates it."
    return {"ok": ok, "element_size_mm": inner, "peak_mpa": round(peak, 2), "finer_peak_mpa": round(other, 2), "change_pct": round(change * 100, 1), "text": text}


def _placed(raw: Mesh, transform: tuple[list[list[float]], list[float]] | None) -> Mesh:
    if transform is not None:
        matrix, offset = np.array(transform[0], dtype=float), np.array(transform[1], dtype=float)
        raw.nodes = raw.nodes @ matrix.T + offset
    return raw


def analyse(
    geometry: Path,
    transform: tuple[list[list[float]], list[float]] | None,
    props: dict,
    fixed_region: dict | list[dict],
    cases: list[dict],
    build_direction: list[float],
    work: Path,
    h: float,
    glb_path: Path | None = None,
    name: str = "part",
    mesh_check: bool = True,
) -> dict:
    """Meshes the part once, solves every load case, judges each against the printed strengths, and checks itself.

    transform is (rotation, offset) from the part's own frame into the assembly frame; regions and
    forces are in the assembly frame. fixed_region is the held region (or a list of them). Each case:
    {name, region, force_n: [fx, fy, fz]}, or {name, loads: [{region, force_n} or {region, pressure_mpa}],
    gravity_g} for several loads at once (four motors pulling) and the part's own weight.
    Returns per-case results, the governing case, the self-checks (held, equilibrium, mesh) with their
    notes, and writes the stress-coloured GLB of the governing case.
    """

    tools = find_tools()
    if tools is None:
        raise FemUnavailable("gmsh and CalculiX (ccx) are missing: FreeCAD's FEM tools are not on this machine.")
    gmsh, ccx = tools
    fixed = fixed_region if isinstance(fixed_region, list) else [fixed_region]
    fine = _placed(mesh(geometry, work, h, gmsh), transform)
    model = prepare(fine, fixed, cases, props, fine.h)
    direction = np.array(build_direction, dtype=float)
    results = []
    worst = None
    for index, case in enumerate(cases):
        disp, stress, reaction = solve(model.mesh, props, model.held, model.loads[index], work / f"case{index}", ccx)
        balance = _balance(model, index, reaction)
        case_name = case.get("name") or f"case {index + 1}"
        if not balance["ok"]:
            raise FemFailed(
                f"Load case {case_name}: the reactions {balance['reaction_n']} N do not balance the loads {balance['load_n']} N "
                f"(off by {balance['error_pct']:.2f} %), so the solve cannot be trusted."
            )
        vm, vm_max, across_max, hot, across_at = _peaks(stress, direction, _away(model, index))
        sf_plane = props["strength_mpa"] / vm_max if vm_max > 0 else 99.0
        sf_layers = props["z_strength_mpa"] / across_max if across_max > 0 else 99.0
        row = {
            "name": case_name,
            "force_n": _vector(model.loads[index].sum(axis=0)),
            "loaded_nodes": int(len(model.loaded[index])),
            "max_von_mises_mpa": round(vm_max, 2),
            "max_across_layers_mpa": round(across_max, 2),
            "max_deflection_mm": round(float(np.linalg.norm(disp, axis=1).max()), 3),
            "safety": round(min(sf_plane, sf_layers, 99.0), 2),
            "safety_in_plane": round(min(sf_plane, 99.0), 2),
            "safety_across_layers": round(min(sf_layers, 99.0), 2),
            "governs": "layers" if sf_layers < sf_plane else "in-plane",
            "hot_spot_mm": [round(float(v), 1) for v in model.mesh.nodes[hot]],
            "loads": model.rows[index],
            "equilibrium": balance,
        }
        results.append(row)
        if balance["on_held_pct"] > 1.0:
            model.notes.append(
                f"{case_name}: {balance['on_held_pct']:.0f} % of the load lands on held nodes and goes straight into the support, "
                "so the part carries only the rest; move the load off the held region if that is not meant."
            )
        if worst is None or row["safety"] < worst[0]["safety"]:
            layers = row["governs"] == "layers"
            worst = (row, vm, index, across_max if layers else vm_max, model.mesh.nodes[across_at if layers else hot])
    assert worst is not None
    row, vm, governing, peak, at = worst
    if mesh_check:
        checked = _mesh_check(geometry, transform, props, fixed, cases[governing], direction, work / "finer", model.mesh, row["governs"], peak, at, gmsh, ccx)
    else:
        checked = {"ok": None, "text": "Mesh check not run."}
    if checked["ok"] is False:
        model.notes.append(checked["text"])
    if glb_path is not None:
        allowable = props["strength_mpa"]
        write_glb(glb_path, model.mesh.nodes, model.mesh.tris[:, :3], colour_map(vm / max(allowable, 1e-9)), name)
    worst_balance = max(results, key=lambda r: r["equilibrium"]["error_pct"])["equilibrium"]
    checks = {
        "held": {"ok": True, "where": " and ".join(model.held_where), "left_out": model.left_out},
        "equilibrium": {"ok": True, "error_pct": worst_balance["error_pct"], "text": f"Reactions balance the loads to {worst_balance['error_pct']:.3f} % in every case."},
        "mesh": checked,
    }
    return {
        "nodes": int(len(model.mesh.nodes)),
        "elements": int(len(model.mesh.tets)),
        "element_size_mm": model.mesh.h,
        "fixed_nodes": int(model.held.any(axis=1).sum()),
        "held": checks["held"]["where"],
        "cases": results,
        "governing": row["name"],
        "safety": row["safety"],
        "max_von_mises_mpa": row["max_von_mises_mpa"],
        "max_deflection_mm": max(r["max_deflection_mm"] for r in results),
        "solver": "CalculiX " + Path(ccx).name + ", gmsh C3D10",
        "bbox_mm": [round(float(v), 2) for v in [*model.mesh.nodes.min(axis=0), *model.mesh.nodes.max(axis=0)]],
        "scale_mpa": round(props["strength_mpa"], 2),
        "build_direction": [round(float(v), 3) for v in direction / max(np.linalg.norm(direction), 1e-12)],
        "checks": checks,
        "notes": model.notes,
    }
