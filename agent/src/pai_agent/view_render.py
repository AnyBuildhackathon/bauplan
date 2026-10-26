"""Renders a build's GLB to a PNG with VTK, offscreen: the picture `cad_view` shows Mechanic.

`python -m pai_agent.view_render job.json` reads a job written by `tools/view.py` (the GLB
layers, the views, the section, the colouring), writes one PNG of WIDTH x HEIGHT and prints a
JSON line with what it drew: the parts, where each one's number sits, the grid size and the
overhang area per printed part. It runs in its own process: VTK's macOS window has to live on
a main thread, a broken OpenGL driver must not take the server down, and a stuck render ends
at the tool's timeout.

The reading half needs only numpy and also runs in the server: `read_glb` and `mesh_nodes`
give `tools/view.py` the node tree (names, which part sits inside which) to resolve the parts
to hide or show before anything renders. Every mesh ends up in one frame, millimetres with
Z up: a GLB in glTF's own axes (the drone: metres, Y up) is turned into FreeCAD's, generated
parts and assemblies are already in it.

The look follows the CAD tab: each part in its `pai:#rrggbb` colour (else the calm CAD grey),
dark crease edges at 30 degrees and silhouettes, a parallel projection so alignment and sizes
read true, and a grid on the lowest point for scale. A section takes away the half facing the
camera and closes each cut solid with a face in a darker shade of its colour, so walls, holes
and pockets show. Each part gets a number on the spot where most of it is visible; the JSON
line says which number is which part.
"""

from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

WIDTH, HEIGHT = 1024, 768
CAD_GREY = "#c9ccd3"
INK = (0.17, 0.18, 0.2)
MUTED = (0.38, 0.4, 0.45)
OVERHANG = (0.88, 0.19, 0.19)
ON_BED = (0.11, 0.49, 0.84)
NEUTRAL = (0.84, 0.85, 0.87)
PAPER = (0.925, 0.933, 0.945)
CONTEXT_OPACITY = 0.3
CREASE_DEG = 30.0
# A bed face lies within this of the part's lowest point along its print direction.
BED_MM = 0.05
# A part needs this many visible pixels to get a number.
MIN_PIXELS = 40

_DTYPES = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_JSON, _BIN = 0x4E4F534A, 0x004E4942


# ---------------------------------------------------------------- reading GLB


def read_glb(path: Path) -> tuple[dict, bytes]:
    """The glTF document and its binary chunk."""

    data = Path(path).read_bytes()
    if data[:4] != b"glTF":
        raise ValueError(Path(path).name + " is not a GLB file.")
    document, blob, offset = None, b"", 12
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        if kind == _JSON:
            document = json.loads(data[offset + 8 : offset + 8 + length])
        elif kind == _BIN:
            blob = data[offset + 8 : offset + 8 + length]
        offset += 8 + length
    if document is None:
        raise ValueError(Path(path).name + " has no glTF document.")
    return document, blob


def _local(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    x, y, z, w = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    turn = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    matrix = np.eye(4)
    matrix[:3, :3] = turn * np.array(node.get("scale", [1.0, 1.0, 1.0]), dtype=float)
    matrix[:3, 3] = node.get("translation", [0.0, 0.0, 0.0])
    return matrix


def mesh_nodes(document: dict) -> list[dict]:
    """Every node with a mesh, in scene order: index, name, the names of the nodes it sits in, its world matrix."""

    nodes = document.get("nodes", [])
    children = {child for node in nodes for child in node.get("children", [])}
    scenes = document.get("scenes") or []
    roots = scenes[document.get("scene", 0)].get("nodes", []) if scenes else [i for i in range(len(nodes)) if i not in children]
    out: list[dict] = []

    def walk(index: int, parent: np.ndarray, path: list[str]) -> None:
        node = nodes[index]
        world = parent @ _local(node)
        name = str(node.get("name") or "node " + str(index))
        if "mesh" in node:
            out.append({"index": index, "name": name, "within": list(path), "world": world, "mesh": node["mesh"]})
        for child in node.get("children", []):
            walk(child, world, [*path, name])

    for root in roots:
        walk(root, np.eye(4), [])
    return out


def _accessor(document: dict, blob: bytes, index: int) -> np.ndarray:
    accessor = document["accessors"][index]
    dtype = np.dtype(_DTYPES[accessor["componentType"]]).newbyteorder("<")
    width = _WIDTHS[accessor["type"]]
    count = int(accessor["count"])
    out = np.zeros((count, width))
    if "bufferView" in accessor:
        view = document["bufferViews"][accessor["bufferView"]]
        if view.get("buffer", 0) != 0:
            raise ValueError("external glTF buffers are not supported")
        start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
        stride = int(view.get("byteStride") or dtype.itemsize * width)
        out = np.ndarray((count, width), dtype=dtype, buffer=blob, offset=start, strides=(stride, dtype.itemsize)).astype(float)
    sparse = accessor.get("sparse")
    if sparse:
        at = _packed(document, blob, sparse["indices"], np.dtype(_DTYPES[sparse["indices"]["componentType"]]).newbyteorder("<"), int(sparse["count"]), 1)
        out[at[:, 0].astype(np.int64)] = _packed(document, blob, sparse["values"], dtype, int(sparse["count"]), width)
    if accessor.get("normalized") and dtype.kind in "iu":
        out = np.maximum(out / float(np.iinfo(dtype).max), -1.0)
    return out


def _packed(document: dict, blob: bytes, ref: dict, dtype: np.dtype, count: int, width: int) -> np.ndarray:
    view = document["bufferViews"][ref["bufferView"]]
    start = int(view.get("byteOffset", 0)) + int(ref.get("byteOffset", 0))
    return np.frombuffer(blob, dtype=dtype, count=count * width, offset=start).reshape(count, width).astype(float)


def _triangles(primitive: dict, document: dict, blob: bytes, count: int) -> np.ndarray | None:
    mode = primitive.get("mode", 4)
    order = _accessor(document, blob, primitive["indices"])[:, 0].astype(np.int64) if "indices" in primitive else np.arange(count)
    if mode == 4:
        return order[: len(order) // 3 * 3].reshape(-1, 3)
    if mode == 5:
        return np.array([(order[i], order[i + 1], order[i + 2]) if i % 2 == 0 else (order[i + 1], order[i], order[i + 2]) for i in range(len(order) - 2)], dtype=np.int64).reshape(-1, 3)
    if mode == 6:
        return np.array([(order[0], order[i], order[i + 1]) for i in range(1, len(order) - 1)], dtype=np.int64).reshape(-1, 3)
    return None


def colour_of(material: dict | None) -> tuple[tuple[float, float, float], float]:
    """RGB and opacity as the CAD tab shows a material: `pai:#rrggbb` or `pai:#rrggbbaa`, everything else in the CAD grey."""

    name = str((material or {}).get("name") or "")
    code = name[4:].split(" ")[0].lstrip("#") if name.startswith("pai:") else ""
    try:
        if len(code) not in (6, 8):
            raise ValueError(code)
        rgb = tuple(int(code[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
        return rgb, int(code[6:8], 16) / 255.0 if len(code) == 8 else 1.0  # type: ignore[return-value]
    except ValueError:
        return tuple(int(CAD_GREY[i : i + 2], 16) / 255.0 for i in (1, 3, 5)), 1.0  # type: ignore[return-value]


def to_millimetres(points: np.ndarray, axes: str) -> np.ndarray:
    """glTF's own axes (metres, Y up, the drone's nose at -Z) into FreeCAD's (mm, Z up, the nose at +Y); zup_mm stays."""

    if axes == "gltf":
        return np.column_stack([points[:, 0], -points[:, 2], points[:, 1]]) * 1000.0
    return points


def read_meshes(path: Path, axes: str, indices: set[int] | None = None) -> list[dict]:
    """The triangle primitives of the chosen mesh nodes (every node without indices), placed in mm with Z up."""

    document, blob = read_glb(path)
    materials = document.get("materials", [])
    out = []
    for node in mesh_nodes(document):
        if indices is not None and node["index"] not in indices:
            continue
        for primitive in document["meshes"][node["mesh"]].get("primitives", []):
            attributes = primitive.get("attributes", {})
            if "POSITION" not in attributes:
                continue
            try:
                local = _accessor(document, blob, attributes["POSITION"])[:, :3]
                faces = _triangles(primitive, document, blob, len(local))
                colours = np.clip(_accessor(document, blob, attributes["COLOR_0"])[:, :3], 0.0, 1.0) if "COLOR_0" in attributes else None
            except (KeyError, ValueError, IndexError, TypeError):
                continue
            if faces is None or not len(faces) or int(faces.max()) >= len(local):
                continue
            world = local @ node["world"][:3, :3].T + node["world"][:3, 3]
            index = primitive.get("material")
            rgb, alpha = colour_of(materials[index] if isinstance(index, int) and index < len(materials) else None)
            out.append({"node": node["index"], "name": node["name"], "points": to_millimetres(world, axes), "faces": faces, "rgb": rgb, "alpha": alpha, "colours": colours})
    return out


# ---------------------------------------------------------------- geometry


def view_frame(front: list[float]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """For each named view: the direction from the model to the camera, and the picture's up."""

    f = np.array(front, dtype=float)
    f /= np.linalg.norm(f)
    z = np.array([0.0, 0.0, 1.0])
    # Someone standing in front of it, looking at it: their right hand side.
    right = np.cross(-f, z)
    return {
        "front": (f, z),
        "back": (-f, z),
        "right": (right, z),
        "left": (-right, z),
        "top": (z, -f),
        "bottom": (-z, f),
        "iso": ((f + right + z) / math.sqrt(3.0), z),
        "iso_below": ((f + right - z) / math.sqrt(3.0), z),
    }


def camera_for(view: str, direction: list[float] | None, front: list[float]) -> tuple[np.ndarray, np.ndarray]:
    if direction is None:
        return view_frame(front)[view]
    d = np.array(direction, dtype=float)
    d /= np.linalg.norm(d)
    up = np.array([0.0, 0.0, 1.0])
    if abs(float(d[2])) > 0.98:
        # Straight down or up: the front stays at the bottom of the picture.
        up = -np.array(front, dtype=float) if d[2] > 0 else np.array(front, dtype=float)
    return d, up


def grid_step(span_mm: float) -> float:
    """A round grid size (1, 2 or 5 times a power of ten) with about eight squares across."""

    raw = max(span_mm, 1e-3) / 8.0
    power = 10.0 ** math.floor(math.log10(raw))
    return next(step * power for step in (1.0, 2.0, 5.0, 10.0) if step * power >= raw * 0.999)


def overhang(points: np.ndarray, faces: np.ndarray, direction: np.ndarray, limit_deg: float, floor: float) -> tuple[np.ndarray, float]:
    """Per triangle 0 (prints as it is), 1 (hangs over more than limit_deg from vertical) or 2 (on the bed), and the hanging area in mm².

    The rule is print_prep's: a face hangs over when it faces down more steeply than the limit, faces on the bed excluded.
    """

    a, b, c = points[faces[:, 0]], points[faces[:, 1]], points[faces[:, 2]]
    cross = np.cross(b - a, c - a)
    area = np.linalg.norm(cross, axis=1) / 2.0
    facing = (cross @ direction) / np.maximum(np.linalg.norm(cross, axis=1), 1e-12)
    on_bed = np.stack([a @ direction, b @ direction, c @ direction], axis=1).max(axis=1) < floor + BED_MM
    hanging = (facing < -math.sin(math.radians(limit_deg))) & ~on_bed & (area > 0)
    kind = np.zeros(len(faces), dtype=np.int8)
    kind[hanging] = 1
    kind[on_bed & (facing < -0.99)] = 2
    return kind, float(area[hanging].sum())


def interior(mask: np.ndarray) -> tuple[int, int] | None:
    """The pixel deepest inside a mask (4-neighbour erosion until one step before it vanishes), nearest the middle of what is left."""

    rows, cols = np.nonzero(mask)
    if not len(rows):
        return None
    r0, c0 = rows.min(), cols.min()
    current = np.pad(mask[r0 : rows.max() + 1, c0 : cols.max() + 1], 1)
    while True:
        eroded = current.copy()
        eroded[1:, :] &= current[:-1, :]
        eroded[:-1, :] &= current[1:, :]
        eroded[:, 1:] &= current[:, :-1]
        eroded[:, :-1] &= current[:, 1:]
        if not eroded.any():
            break
        current = eroded
    rows, cols = np.nonzero(current)
    k = int(np.argmin((rows - rows.mean()) ** 2 + (cols - cols.mean()) ** 2))
    return int(rows[k] + r0 - 1), int(cols[k] + c0 - 1)


def section_plane(section: dict, bounds: np.ndarray, d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The cut plane's origin and the normal of the half that stays: the half facing the camera goes, side on the + side goes."""

    axis = "xyz".index(section["axis"])
    at = float(section["at_mm"])
    if not bounds[axis] < at < bounds[axis + 3]:
        raise ValueError(f"section {section['axis']} = {at:g} mm misses the model, which spans {section['axis']} {bounds[axis]:.1f} to {bounds[axis + 3]:.1f} mm.")
    normal = np.zeros(3)
    normal[axis] = 1.0
    origin = (bounds[:3] + bounds[3:]) / 2.0
    origin[axis] = at
    return origin, (-normal if float(d @ normal) >= -1e-6 else normal)


# ---------------------------------------------------------------- VTK


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


def _colours(rgb: np.ndarray):
    from vtkmodules.util.numpy_support import numpy_to_vtk

    array = numpy_to_vtk(np.ascontiguousarray(np.clip(rgb * 255.0 + 0.5, 0, 255), dtype=np.uint8), deep=True)
    array.SetName("Colors")
    return array


def _clean(poly):
    from vtkmodules.vtkFiltersCore import vtkCleanPolyData

    clean = vtkCleanPolyData()
    clean.SetInputData(poly)
    clean.ToleranceIsAbsoluteOn()
    clean.SetAbsoluteTolerance(1e-4)
    clean.ConvertPolysToLinesOff()
    clean.ConvertLinesToPointsOff()
    clean.Update()
    return clean.GetOutput()


def _closed(poly) -> bool:
    from vtkmodules.vtkFiltersCore import vtkFeatureEdges

    edges = vtkFeatureEdges()
    edges.SetInputData(poly)
    edges.BoundaryEdgesOn()
    edges.NonManifoldEdgesOn()
    edges.FeatureEdgesOff()
    edges.ManifoldEdgesOff()
    edges.Update()
    return edges.GetOutput().GetNumberOfCells() == 0


def _cut(poly, plane: tuple[np.ndarray, np.ndarray], rgb):
    """The half that stays; a closed solid gets its cut face in a darker shade of its colour. Returns (poly, coloured)."""

    from vtkmodules.vtkCommonDataModel import vtkPlane, vtkPlaneCollection
    from vtkmodules.vtkFiltersCore import vtkClipPolyData
    from vtkmodules.vtkFiltersGeneral import vtkClipClosedSurface

    vtk_plane = vtkPlane()
    vtk_plane.SetOrigin(*plane[0])
    vtk_plane.SetNormal(*plane[1])
    if _closed(poly):
        planes = vtkPlaneCollection()
        planes.AddItem(vtk_plane)
        clip = vtkClipClosedSurface()
        clip.SetInputData(poly)
        clip.SetClippingPlanes(planes)
        clip.GenerateFacesOn()
        clip.SetScalarModeToColors()
        clip.SetBaseColor(*rgb)
        clip.SetClipColor(*(0.55 * v for v in rgb))
        clip.Update()
        return clip.GetOutput(), True
    clip = vtkClipPolyData()
    clip.SetInputData(poly)
    clip.SetClipFunction(vtk_plane)
    clip.Update()
    return clip.GetOutput(), False


def _lines(source, colour, opacity: float, width: float):
    """Lines drawn on top of the faces, from a polydata or a filter."""

    from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper

    mapper = vtkPolyDataMapper()
    if hasattr(source, "GetOutputPort"):
        mapper.SetInputConnection(source.GetOutputPort())
    else:
        mapper.SetInputData(source)
    mapper.ScalarVisibilityOff()
    mapper.SetResolveCoincidentTopologyToPolygonOffset()
    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*colour)
    actor.GetProperty().SetOpacity(opacity)
    actor.GetProperty().SetLineWidth(width)
    actor.GetProperty().LightingOff()
    return actor


def _prepare(mesh: dict, colour: str, printed: dict, floors: dict, limit: float, plane, overhang_mm2: dict) -> dict | None:
    """One mesh ready for any view: its shaded surface, its crease edges and the mesh its silhouette follows.

    None when a section leaves nothing of it.
    """

    from vtkmodules.vtkFiltersCore import vtkFeatureEdges, vtkPolyDataNormals

    rgb, alpha, coloured = mesh["rgb"], mesh["alpha"], False
    poly = _polydata(mesh["points"], mesh["faces"])
    if mesh["colours"] is not None:
        # A result mesh brings its colour per corner (the FEM stress); its lines come from a merged copy.
        poly.GetPointData().SetScalars(_colours(mesh["colours"]))
        lines_of = _clean(_polydata(mesh["points"], mesh["faces"]))
        alpha, coloured = 1.0, True
    else:
        if colour == "overhang" and mesh["name"] in printed:
            kind, area = overhang(mesh["points"], mesh["faces"], printed[mesh["name"]], limit, floors[mesh["name"]])
            overhang_mm2[mesh["name"]] = overhang_mm2.get(mesh["name"], 0.0) + area
            poly.GetCellData().SetScalars(_colours(np.array([NEUTRAL, OVERHANG, ON_BED])[kind]))
            coloured = True
        elif colour != "parts" or mesh["role"] == "context":
            # Everything the colouring does not judge stays as see-through context.
            rgb, alpha = NEUTRAL, min(alpha, CONTEXT_OPACITY)
        poly = _clean(poly)
        if plane is not None:
            poly, capped = _cut(poly, plane, rgb)
            coloured = coloured or capped
            if poly.GetNumberOfCells() == 0:
                return None
        lines_of = poly
    normals = vtkPolyDataNormals()
    normals.SetInputData(poly)
    normals.SetFeatureAngle(CREASE_DEG)
    normals.SplittingOn()
    normals.Update()
    crease = None
    if alpha >= 0.99:
        edges = vtkFeatureEdges()
        edges.SetInputData(lines_of)
        edges.BoundaryEdgesOn()
        edges.FeatureEdgesOn()
        edges.SetFeatureAngle(CREASE_DEG)
        edges.NonManifoldEdgesOff()
        edges.ManifoldEdgesOff()
        edges.ColoringOff()
        edges.Update()
        crease = edges.GetOutput()
    return {"name": mesh["name"], "surface": normals.GetOutput(), "crease": crease, "lines_of": lines_of, "rgb": rgb, "alpha": alpha, "coloured": coloured}


def _part_actors(item: dict, camera) -> tuple[object, list]:
    """A prepared mesh in one view: the shaded surface, its crease edges and its silhouette for this camera."""

    from vtkmodules.vtkFiltersHybrid import vtkPolyDataSilhouette
    from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper

    mapper = vtkPolyDataMapper()
    mapper.SetInputData(item["surface"])
    mapper.SetScalarVisibility(item["coloured"])
    mapper.SetColorModeToDirectScalars()
    mapper.SetResolveCoincidentTopologyToPolygonOffset()
    # Faces step back a little more than usual, so the edges on them never break up into dashes.
    mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(1.5, 3.0)
    surface = vtkActor()
    surface.SetMapper(mapper)
    prop = surface.GetProperty()
    prop.SetColor(*item["rgb"])
    prop.SetOpacity(item["alpha"])
    prop.SetAmbient(0.25)
    prop.SetDiffuse(0.75)
    prop.SetSpecular(0.06)
    prop.SetSpecularPower(20)
    solid = item["alpha"] >= 0.99
    lines = [_lines(item["crease"], INK, 0.55, 1.2)] if item["crease"] is not None else []
    outline = vtkPolyDataSilhouette()
    outline.SetInputData(item["lines_of"])
    outline.SetCamera(camera)
    outline.SetDirectionToCameraVector()
    outline.BorderEdgesOn()
    outline.SetEnableFeatureAngle(0)
    lines.append(_lines(outline, INK, 0.75 if solid else 0.35, 1.4))
    return surface, lines


def _grid(bounds: np.ndarray, step: float):
    """Light lines on the lowest point of the model, a square beyond its footprint all round."""

    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
    from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper

    x0, y0 = math.floor(bounds[0] / step - 1) * step, math.floor(bounds[1] / step - 1) * step
    x1, y1 = math.ceil(bounds[3] / step + 1) * step, math.ceil(bounds[4] / step + 1) * step
    z = bounds[2] - 0.002 * step
    points, cells = vtkPoints(), vtkCellArray()
    for x in np.arange(x0, x1 + step / 2, step):
        cells.InsertNextCell(2, [points.InsertNextPoint(x, y0, z), points.InsertNextPoint(x, y1, z)])
    for y in np.arange(y0, y1 + step / 2, step):
        cells.InsertNextCell(2, [points.InsertNextPoint(x0, y, z), points.InsertNextPoint(x1, y, z)])
    poly = vtkPolyData()
    poly.SetPoints(points)
    poly.SetLines(cells)
    mapper = vtkPolyDataMapper()
    mapper.SetInputData(poly)
    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(0.6, 0.63, 0.68)
    actor.GetProperty().SetOpacity(0.6)
    actor.GetProperty().LightingOff()
    return actor


def _text(text: str, size: int, x: float, y: float, colour=INK, bold: bool = False, anchor: str = "left", marker: bool = False):
    from vtkmodules.vtkRenderingCore import vtkTextActor

    actor = vtkTextActor()
    actor.SetInput(text)
    prop = actor.GetTextProperty()
    prop.SetFontFamilyToArial()
    prop.SetFontSize(size)
    prop.SetColor(*colour)
    prop.SetBold(bold)
    prop.SetJustification({"left": 0, "center": 1, "right": 2}[anchor])
    if marker:
        prop.SetVerticalJustificationToCentered()
        prop.SetBackgroundColor(1.0, 1.0, 1.0)
        prop.SetBackgroundOpacity(0.92)
        prop.SetFrame(1)
        prop.SetFrameColor(*INK)
        prop.SetFrameWidth(1)
    actor.SetDisplayPosition(round(x), round(y))
    return actor


def _fit(renderer, d: np.ndarray, up: np.ndarray, points: np.ndarray, bounds: np.ndarray, aspect: float) -> None:
    """Parallel projection along d, the model filling the view with a margin."""

    up = up - (up @ d) * d
    up /= np.linalg.norm(up)
    right = np.cross(-d, up)
    across, high = points @ right, points @ up
    centre = (bounds[:3] + bounds[3:]) / 2.0
    focal = (across.min() + across.max()) / 2.0 * right + (high.min() + high.max()) / 2.0 * up + (centre @ d) * d
    radius = 0.5 * float(np.linalg.norm(bounds[3:] - bounds[:3])) or 1.0
    camera = renderer.GetActiveCamera()
    camera.ParallelProjectionOn()
    camera.SetFocalPoint(*focal)
    camera.SetPosition(*(focal + d * radius * 4.0))
    camera.SetViewUp(*up)
    camera.SetParallelScale(max(float(np.ptp(high)) / 2.0, float(np.ptp(across)) / 2.0 / aspect, 1e-3) * 1.1)
    camera.SetClippingRange(radius * 2.0, radius * 6.0)


def _grab(window) -> np.ndarray:
    """The window's pixels as rows from the bottom, RGB."""

    from vtkmodules.util.numpy_support import vtk_to_numpy
    from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter

    grab = vtkWindowToImageFilter()
    grab.SetInput(window)
    grab.ReadFrontBufferOff()
    grab.Update()
    image = grab.GetOutput()
    width, height, _depth = image.GetDimensions()
    return vtk_to_numpy(image.GetPointData().GetScalars()).reshape(height, width, -1)[:, :, :3]


def _write_png(window, path: Path) -> None:
    """The picture as a 256-colour PNG: a flat render needs no more, and it is a tenth of the bytes in every history it rides in."""

    try:
        from PIL import Image
    except ImportError:
        from vtkmodules.vtkIOImage import vtkPNGWriter
        from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter

        grab = vtkWindowToImageFilter()
        grab.SetInput(window)
        grab.ReadFrontBufferOff()
        writer = vtkPNGWriter()
        writer.SetFileName(str(path))
        writer.SetInputConnection(grab.GetOutputPort())
        writer.Write()
        return
    image = Image.fromarray(np.ascontiguousarray(_grab(window)[::-1]), "RGB")
    image.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, "PNG", optimize=True)


def _number_spots(renderer, parts: list[tuple[str, list]], box: tuple[int, int, int, int]) -> dict[str, tuple[int, int]]:
    """Where each part's number goes, in display pixels: the spot deepest inside what is seen of it.

    A second window draws every part flat in a colour of its own through the same camera; a
    see-through part counts only where no solid part shows.
    """

    from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper, vtkRenderer, vtkRenderWindow

    window = vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(WIDTH, HEIGHT)
    window.SetMultiSamples(0)
    flat = vtkRenderer()
    flat.SetViewport(*renderer.GetViewport())
    flat.SetActiveCamera(renderer.GetActiveCamera())
    flat.SetBackground(0.0, 0.0, 1.0)
    window.AddRenderer(flat)
    x0, y0, x1, y1 = box
    passes = []
    for solid in (True, False):
        flat.RemoveAllViewProps()
        for n, (_name, actors) in enumerate(parts, 1):
            for actor in actors:
                if (actor.GetProperty().GetOpacity() >= 0.99) != solid:
                    continue
                mapper = vtkPolyDataMapper()
                mapper.SetInputData(actor.GetMapper().GetInput())
                mapper.ScalarVisibilityOff()
                copy = vtkActor()
                copy.SetMapper(mapper)
                copy.GetProperty().LightingOff()
                copy.GetProperty().SetColor((n % 256) / 255.0, (n // 256) / 255.0, 0.0)
                flat.AddActor(copy)
        window.Render()
        tile = _grab(window)[y0:y1, x0:x1].astype(np.int32)
        passes.append(np.where(tile[:, :, 2] == 0, tile[:, :, 0] + 256 * tile[:, :, 1], 0))
    window.Finalize()
    ids = np.where(passes[0] > 0, passes[0], passes[1])
    spots = {}
    for n, (name, _actors) in enumerate(parts, 1):
        mask = ids == n
        spot = interior(mask) if int(mask.sum()) >= MIN_PIXELS else None
        if spot is not None:
            spots[name] = (x0 + spot[1], y0 + spot[0])
    return spots


def render(job: dict) -> dict:
    """Draws the job into one PNG of WIDTH x HEIGHT and returns what it drew."""

    from vtkmodules import vtkRenderingFreeType, vtkRenderingOpenGL2  # noqa: F401  text and the OpenGL backend
    from vtkmodules.vtkRenderingCore import vtkLightKit, vtkRenderer, vtkRenderWindow

    colour = job.get("color", "parts")
    views = list(job["views"])
    direction = job.get("direction")
    front = job["front"]
    limit = float(job.get("overhang_deg", 45.0))
    printed = {name: np.array(d, dtype=float) / np.linalg.norm(d) for name, d in (job.get("printed") or {}).items()}
    meshes = []
    for layer in job["layers"]:
        nodes = set(layer["nodes"]) if layer.get("nodes") is not None else None
        for mesh in read_meshes(Path(layer["glb"]), layer.get("axes", "zup_mm"), nodes):
            meshes.append({**mesh, "role": layer.get("role", "model")})
    if not meshes:
        raise ValueError("Nothing to draw: no visible part has triangles.")
    every = np.concatenate([m["points"][m["faces"].ravel()] for m in meshes])
    bounds = np.concatenate([every.min(axis=0), every.max(axis=0)])
    step = grid_step(float(max(bounds[3] - bounds[0], bounds[4] - bounds[1])))
    plane = section_plane(job["section"], bounds, camera_for(views[0], direction, front)[0]) if job.get("section") else None
    names = list(dict.fromkeys(m["name"] for m in meshes))
    floors = {name: min(float((m["points"] @ printed[name]).min()) for m in meshes if m["name"] == name) for name in names if name in printed}
    overhang_mm2: dict[str, float] = {}
    prepared = [item for item in (_prepare(mesh, colour, printed, floors, limit, plane, overhang_mm2) for mesh in meshes) if item is not None]

    window = vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(WIDTH, HEIGHT)
    window.SetMultiSamples(0)
    window.SetAlphaBitPlanes(1)
    backdrop = vtkRenderer()
    backdrop.SetBackground(0.72, 0.74, 0.78)
    window.AddRenderer(backdrop)
    sheet = len(views) > 1
    tiles = [(0, 384, 512, 768), (512, 384, 1024, 768), (0, 0, 512, 384), (512, 0, 1024, 384)] if sheet else [(0, 0, WIDTH, HEIGHT)]
    size = 12 if sheet else 14
    spots: dict[str, tuple[int, int]] = {}
    for n, view in enumerate(views):
        x0, y0, x1, y1 = tiles[n]
        renderer = vtkRenderer()
        inset = 1 if sheet else 0
        renderer.SetViewport((x0 + inset * (x0 > 0)) / WIDTH, (y0 + inset * (y0 > 0)) / HEIGHT, (x1 - inset * (x1 < WIDTH)) / WIDTH, (y1 - inset * (y1 < HEIGHT)) / HEIGHT)
        renderer.SetBackground(*PAPER)
        renderer.UseDepthPeelingOn()
        renderer.SetMaximumNumberOfPeels(6)
        renderer.UseFXAAOn()
        lights = vtkLightKit()
        # A strong head light: a face turned to the camera shows its colour, also from below.
        lights.SetKeyLightIntensity(0.7)
        lights.SetKeyToHeadRatio(1.0)
        lights.AddLightsToRenderer(renderer)
        window.AddRenderer(renderer)
        d, up = camera_for(view, direction if n == 0 else None, front)
        _fit(renderer, d, up, every, bounds, (x1 - x0) / (y1 - y0))
        surfaces: dict[str, list] = {name: [] for name in names}
        for item in prepared:
            surface, lines = _part_actors(item, renderer.GetActiveCamera())
            renderer.AddActor(surface)
            for line in lines:
                renderer.AddActor(line)
            surfaces[item["name"]].append(surface)
        if d[2] > -0.05:
            renderer.AddActor(_grid(bounds, step))
        title = view.replace("_", " ").upper()
        if n == 0 and direction is not None:
            title = "VIEW FROM (" + ", ".join(f"{float(v):g}" for v in direction) + ")"
        if n == 0 and plane is not None:
            title += "   SECTION " + job["section"]["axis"].upper() + " = " + f"{float(job['section']['at_mm']):g} mm"
        renderer.AddViewProp(_text(title, size + 1, x0 + 10, y1 - size - 12, bold=True))
        renderer.AddViewProp(_text("grid " + f"{step:g}" + " mm", size - 1, x1 - 10, y0 + 8, colour=MUTED, anchor="right"))
        legend = None
        if colour == "overhang":
            legend = f"red: hangs over more than {limit:g}° (needs support)   blue: on the bed"
        elif colour == "stress":
            legend = job.get("legend")
        if n == 0 and legend:
            renderer.AddViewProp(_text(legend, size - 1, x0 + 10, y0 + 8, colour=MUTED))
        if n == 0:
            spots = _number_spots(renderer, [(name, surfaces[name]) for name in names], (x0, y0, x1, y1))
            for number, name in enumerate(names, 1):
                if name in spots and job.get("numbers", True):
                    renderer.AddViewProp(_text(str(number), size, spots[name][0], spots[name][1], bold=True, anchor="center", marker=True))
    window.Render()
    _write_png(window, Path(job["out"]))
    window.Finalize()
    colours = {}
    for mesh in meshes:
        if mesh["name"] not in colours:
            code = "#" + "".join(f"{round(v * 255):02x}" for v in mesh["rgb"])
            colours[mesh["name"]] = code + (f"{round(mesh['alpha'] * 255):02x}" if mesh["alpha"] < 0.99 else "")
    out = {
        "ok": True,
        "width": WIDTH,
        "height": HEIGHT,
        "parts": [{"number": n, "name": name, "seen": name in spots, "color": colours[name]} for n, name in enumerate(names, 1)],
        "grid_mm": step,
        "bounds_mm": [round(float(v), 2) for v in bounds],
        "overhang_mm2": {name: round(area, 1) for name, area in overhang_mm2.items()},
    }
    if plane is not None:
        out["removed"] = "+" if float(plane[1]["xyz".index(job["section"]["axis"])]) < 0 else "-"
    return out


def main(argv: list[str]) -> int:
    job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    try:
        result = render(job)
    except Exception as exc:  # noqa: BLE001 - the tool reads the reason from the JSON line
        result = {"ok": False, "error": str(exc) or type(exc).__name__}
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
