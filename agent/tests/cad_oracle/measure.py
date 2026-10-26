"""Measures exported CAD files on their own, without the code that wrote them.

A STEP file is read back with OpenCASCADE (OCP, the kernel under CadQuery) and measured on its exact
geometry; an STL with numpy, after welding its corners; a GLB from its binary chunk. Each gives plain
numbers: volume, surface area, centre of mass and bounding box in mm, and what makes the file usable:
a STEP's declared length unit, its solids and whether their shells close, an STL's open, overused and
flipped edges and its topology (one through hole adds one to the genus).
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ISO 10303-21 length units (the prefix of SI_UNIT(prefix, .METRE.)) and their size in mm.
_SI_PREFIX_MM = {"$": 1000.0, ".MILLI.": 1.0, ".CENTI.": 10.0, ".DECI.": 100.0, ".KILO.": 1e6, ".MICRO.": 1e-3}
_CONVERSION_MM = {"INCH": 25.4, "FOOT": 304.8}


@dataclass
class Solid:
    volume_mm3: float
    area_mm2: float
    # Area of the faces that are not planes: only there can an STL deviate from the solid.
    curved_area_mm2: float
    com_mm: list[float]
    bbox_mm: list[float]


@dataclass
class Step:
    unit_mm: float | None
    valid: bool
    solids: list[Solid]
    free_edges: int
    bad_edges: int
    volume_mm3: float
    area_mm2: float
    curved_area_mm2: float
    com_mm: list[float]
    bbox_mm: list[float]
    # Pairs of solids (by index) that share volume, with how much.
    overlaps: list[tuple[int, int, float]] = field(default_factory=list)


@dataclass
class Mesh:
    triangles: int
    degenerate: int
    # Edges with one triangle (a hole in the skin), with more than two, and walked the same way twice (a flipped triangle).
    open_edges: int
    overused_edges: int
    flipped_edges: int
    shells: int
    genus: float
    volume_mm3: float
    area_mm2: float
    com_mm: list[float]
    bbox_mm: list[float]
    problems: list[str] = field(default_factory=list)

    @property
    def watertight(self) -> bool:
        return not self.problems


def step_unit_mm(text: str) -> float | None:
    """The length unit the file declares, in mm; None when it declares none this reader knows."""

    for entity in text.split(";"):
        if "LENGTH_UNIT" not in entity:
            continue
        si = re.search(r"SI_UNIT\s*\(\s*(\$|\.[A-Z]+\.)\s*,\s*\.METRE\.\s*\)", entity)
        if si and "CONVERSION_BASED_UNIT" not in entity:
            return _SI_PREFIX_MM.get(si.group(1))
        named = re.search(r"CONVERSION_BASED_UNIT\s*\(\s*'([A-Z]+)'", entity.upper())
        if named:
            return _CONVERSION_MM.get(named.group(1))
    return None


def _solid(shape) -> Solid:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    volume = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, volume)
    area = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, area)
    curved = 0.0
    faces = TopExp_Explorer(shape, TopAbs_FACE)
    while faces.More():
        face = TopoDS.Face_s(faces.Current())
        if BRepAdaptor_Surface(face).GetType() != GeomAbs_Plane:
            one = GProp_GProps()
            BRepGProp.SurfaceProperties_s(face, one)
            curved += one.Mass()
        faces.Next()
    centre = volume.CentreOfMass()
    return Solid(volume.Mass(), area.Mass(), curved, [centre.X(), centre.Y(), centre.Z()], bbox(shape))


def bbox(shape) -> list[float]:
    """The exact bounding box, from the geometry rather than a triangulation or the shape's tolerance."""

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    return list(box.Get())


def _overlaps(shapes: list, boxes: list[list[float]]) -> list[tuple[int, int, float]]:
    """The volume every two solids share; solids that only touch share none."""

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    found = []
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            a, b = boxes[i], boxes[j]
            if any(min(a[k + 3], b[k + 3]) - max(a[k], b[k]) <= 1e-6 for k in range(3)):
                continue
            common = BRepAlgoAPI_Common(shapes[i], shapes[j])
            if not common.IsDone():
                found.append((i, j, float("nan")))
                continue
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(common.Shape(), props)
            if props.Mass() > 1e-6:
                found.append((i, j, props.Mass()))
    return found


def step(path: Path, overlaps: bool = False) -> Step:
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.ShapeAnalysis import ShapeAnalysis_Shell
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError(f"{path.name} is not a readable STEP file")
    reader.TransferRoots()
    shape = reader.OneShape()
    solids, shapes = [], []
    free = bad = 0
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        one = explorer.Current()
        shapes.append(one)
        solids.append(_solid(one))
        shells = ShapeAnalysis_Shell()
        shells.LoadShells(one)
        shells.CheckOrientedShells(one, True)
        free += shells.FreeEdges().NbChildren() if shells.HasFreeEdges() else 0
        bad += shells.BadEdges().NbChildren() if shells.HasBadEdges() else 0
        explorer.Next()
    volume = sum(s.volume_mm3 for s in solids)
    com = [sum(s.volume_mm3 * s.com_mm[i] for s in solids) / volume for i in range(3)] if volume else [0.0, 0.0, 0.0]
    return Step(
        unit_mm=step_unit_mm(path.read_text(encoding="utf-8", errors="ignore")),
        valid=bool(BRepCheck_Analyzer(shape).IsValid()),
        solids=solids,
        free_edges=free,
        bad_edges=bad,
        volume_mm3=volume,
        area_mm2=sum(s.area_mm2 for s in solids),
        curved_area_mm2=sum(s.curved_area_mm2 for s in solids),
        com_mm=com,
        bbox_mm=bbox(shape) if solids else [0.0] * 6,
        overlaps=_overlaps(shapes, [s.bbox_mm for s in solids]) if overlaps else [],
    )


def read_stl(path: Path) -> np.ndarray:
    """The triangles of a binary or ASCII STL, shape (n, 3, 3), in the file's own numbers."""

    data = path.read_bytes()
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + 50 * count:
            records = np.frombuffer(data, dtype=np.dtype([("normal", "<f4", 3), ("corners", "<f4", (3, 3)), ("attr", "<u2")]), count=count, offset=84)
            return records["corners"].astype(np.float64)
    text = data.decode("ascii", errors="strict")
    if not text.lstrip().startswith("solid"):
        raise ValueError(f"{path.name} is neither a binary STL of its length nor an ASCII STL")
    numbers = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
    if len(numbers) % 3:
        raise ValueError(f"{path.name}: a facet has no three corners")
    return np.array(numbers, dtype=np.float64).reshape(-1, 3, 3)


def mesh(path: Path) -> Mesh:
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    corners = read_stl(path)
    if not len(corners):
        raise ValueError(f"{path.name} has no triangles")
    # Corners welded where the file writes the same numbers: an STL has no shared vertices of its own.
    points, index = np.unique(corners.reshape(-1, 3), axis=0, return_inverse=True)
    faces = index.reshape(-1, 3)
    cross = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    doubled = np.linalg.norm(cross, axis=1)
    degenerate = int(np.count_nonzero((faces[:, 0] == faces[:, 1]) | (faces[:, 1] == faces[:, 2]) | (faces[:, 0] == faces[:, 2]) | (doubled <= 1e-12)))
    directed = faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
    _rows, walked = np.unique(directed, axis=0, return_counts=True)
    _edges, used = np.unique(np.sort(directed, axis=1), axis=0, return_counts=True)
    open_edges = int(np.count_nonzero(used == 1))
    overused = int(np.count_nonzero(used > 2))
    flipped = int(np.count_nonzero(walked > 1))
    graph = coo_matrix((np.ones(len(directed)), (directed[:, 0], directed[:, 1])), shape=(len(points), len(points)))
    shells = int(connected_components(graph, directed=False)[0])
    euler = len(points) - len(_edges) + len(faces)
    # Signed tetrahedra from a point near the part, so large coordinates cost no precision.
    origin = corners.reshape(-1, 3).mean(axis=0)
    a, b, c = corners[:, 0] - origin, corners[:, 1] - origin, corners[:, 2] - origin
    tetra = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    volume = float(tetra.sum())
    centre = (origin + (tetra[:, None] * (a + b + c)).sum(axis=0) / (4.0 * volume)) if volume else origin
    problems = []
    if degenerate:
        problems.append(f"{degenerate} degenerate triangles")
    if open_edges:
        problems.append(f"{open_edges} open edges")
    if overused:
        problems.append(f"{overused} edges shared by more than two triangles")
    if flipped:
        problems.append(f"{flipped} edges walked the same way twice (flipped triangles)")
    if volume <= 0:
        problems.append("the triangles face inwards (negative volume)")
    return Mesh(
        triangles=len(faces),
        degenerate=degenerate,
        open_edges=open_edges,
        overused_edges=overused,
        flipped_edges=flipped,
        shells=shells,
        genus=(2 * shells - euler) / 2.0,
        volume_mm3=volume,
        area_mm2=float(doubled.sum() / 2.0),
        com_mm=[float(v) for v in centre],
        bbox_mm=[float(v) for v in (*points.min(axis=0), *points.max(axis=0))],
        problems=problems,
    )


def glb_nodes(path: Path) -> dict[str, list[float]]:
    """Bounding box of every named node's positions in a GLB, decoded from the binary chunk (node transforms applied)."""

    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError(f"{path.name} is not a GLB")
    length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + length])
    binary_at = 20 + length
    binary = data[binary_at + 8 : binary_at + 8 + struct.unpack_from("<I", data, binary_at)[0]]
    out: dict[str, list[float]] = {}
    for number, node in enumerate(document.get("nodes", [])):
        if "mesh" not in node:
            continue
        matrix = np.array(node["matrix"], dtype=float).reshape(4, 4).T if "matrix" in node else np.eye(4)
        if "translation" in node:
            matrix[:3, 3] += node["translation"]
        boxes = []
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            accessor = document["accessors"][primitive["attributes"]["POSITION"]]
            view = document["bufferViews"][accessor["bufferView"]]
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            stride = view.get("byteStride", 12)
            raw = np.frombuffer(binary, dtype=np.uint8, count=stride * (accessor["count"] - 1) + 12, offset=start)
            rows = np.lib.stride_tricks.as_strided(raw, shape=(accessor["count"], 12), strides=(stride, 1)).copy()
            positions = rows.view("<f4").reshape(-1, 3).astype(float) @ matrix[:3, :3].T + matrix[:3, 3]
            boxes.append(np.concatenate([positions.min(axis=0), positions.max(axis=0)]))
        stacked = np.array(boxes)
        out[node.get("name", f"node {number}")] = [*stacked[:, :3].min(axis=0).tolist(), *stacked[:, 3:].max(axis=0).tolist()]
    return out
