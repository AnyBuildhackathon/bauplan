"""CadQuery shapes to a small GLB with one named node per piece and real colours, and back to numbers.

Every model is in millimetres with Z up, the same frame the CAD tab already shows (`zUp`).
Each piece is tessellated face by face, so normals are smooth inside a curved face and sharp
across an edge, the way a CAD part looks. A material is named `pai:#rrggbb` so the CAD view keeps
its colour instead of the neutral grey. `read_glb` gives each node's vertices back for the checks.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finish:
    """A surface: base colour as #rrggbb, metal or not, how rough, and optional see-through."""

    color: str
    metallic: float = 0.0
    roughness: float = 0.6
    alpha: float = 1.0


@dataclass
class Mesh:
    """A triangle mesh drawn directly from a formula, for surfaces OCC meshes far too finely."""

    positions: list[tuple[float, float, float]]
    normals: list[tuple[float, float, float]]
    indices: list[int]


def ring_mesh(rings: list[list[tuple[float, float, float]]]) -> Mesh:
    """A closed surface through rings of equal point count, capped at both ends, smooth normals."""

    count = len(rings[0])
    positions = [point for ring in rings for point in ring]
    indices: list[int] = []
    for j in range(len(rings) - 1):
        for k in range(count):
            a = j * count + k
            b = j * count + (k + 1) % count
            c = a + count
            d = b + count
            indices.extend((a, b, d, a, d, c))
    for ring_index, flip in ((0, True), (len(rings) - 1, False)):
        ring = rings[ring_index]
        centre = tuple(sum(p[i] for p in ring) / count for i in range(3))
        positions.append(centre)
        middle = len(positions) - 1
        start = ring_index * count
        for k in range(count):
            a, b = start + k, start + (k + 1) % count
            indices.extend((middle, b, a) if flip else (middle, a, b))
    sums = [[0.0, 0.0, 0.0] for _ in positions]
    for t in range(0, len(indices), 3):
        a, b, c = indices[t : t + 3]
        ax, ay, az = positions[a]
        bx, by, bz = positions[b]
        cx, cy, cz = positions[c]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        for index in (a, b, c):
            for axis in range(3):
                sums[index][axis] += n[axis]
    normals = []
    for total in sums:
        length = math.sqrt(sum(v * v for v in total)) or 1.0
        normals.append((total[0] / length, total[1] / length, total[2] / length))
    return Mesh(positions, normals, indices)


def _rgb(color: str) -> list[float]:
    value = color.lstrip("#")
    # glTF colours are linear; the hex values are the sRGB colour of the real part.
    channels = [int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return [round(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4, 4) for c in channels]


def tessellate(shape, tolerance: float, angular: float = 0.5) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], list[int]]:
    """Positions, smooth per-face normals and triangle indices of one CadQuery shape."""

    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    indices: list[int] = []
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location

    # One absolute-tolerance mesh of the whole shape (CadQuery's own call is relative and cached).
    BRepTools.Clean_s(shape.wrapped)
    BRepMesh_IncrementalMesh(shape.wrapped, tolerance, False, angular, False)
    for face in shape.Faces():
        location = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face.wrapped, location)
        if poly is None:
            continue
        transform = location.Transformation()
        reversed_face = face.wrapped.Orientation() == TopAbs_REVERSED
        vertices = []
        for i in range(1, poly.NbNodes() + 1):
            point = poly.Node(i).Transformed(transform)
            vertices.append(point)
        triangles = []
        for i in range(1, poly.NbTriangles() + 1):
            a, b, c = poly.Triangle(i).Get()
            triangles.append((a - 1, c - 1, b - 1) if reversed_face else (a - 1, b - 1, c - 1))
        if not triangles:
            continue
        vertices = [type("V", (), {"x": v.X(), "y": v.Y(), "z": v.Z()}) for v in vertices]
        base = len(positions)
        points = [(v.x, v.y, v.z) for v in vertices]
        sums = [[0.0, 0.0, 0.0] for _ in points]
        for a, b, c in triangles:
            ax, ay, az = points[a]
            bx, by, bz = points[b]
            cx, cy, cz = points[c]
            ux, uy, uz = bx - ax, by - ay, bz - az
            vx, vy, vz = cx - ax, cy - ay, cz - az
            n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
            for index in (a, b, c):
                sums[index][0] += n[0]
                sums[index][1] += n[1]
                sums[index][2] += n[2]
            indices.extend((base + a, base + b, base + c))
        for point, total in zip(points, sums):
            length = math.sqrt(total[0] ** 2 + total[1] ** 2 + total[2] ** 2) or 1.0
            positions.append(point)
            normals.append((total[0] / length, total[1] / length, total[2] / length))
    return positions, normals, indices


def write_glb(pieces: list[tuple[str, object, Finish]], path: Path, tolerance: float) -> dict:
    """Write pieces (name, CadQuery shape, finish) as one GLB; returns its bounding box and size."""

    blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []
    nodes: list[dict] = []
    materials: list[dict] = []
    material_index: dict[Finish, int] = {}
    low = [math.inf] * 3
    high = [-math.inf] * 3

    def add_view(data: bytes, target: int) -> int:
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target})
        blob.extend(data)
        return len(views) - 1

    for name, shape, finish in pieces:
        # A piece is a CadQuery shape, or an already built Mesh (a propeller blade).
        positions, normals, indices = (shape.positions, shape.normals, shape.indices) if isinstance(shape, Mesh) else tessellate(shape, tolerance)
        if not indices:
            continue
        if finish not in material_index:
            material = {
                "name": "pai:" + finish.color,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [*_rgb(finish.color), finish.alpha],
                    "metallicFactor": finish.metallic,
                    "roughnessFactor": finish.roughness,
                },
                "doubleSided": finish.alpha < 1.0,
            }
            if finish.alpha < 1.0:
                material["alphaMode"] = "BLEND"
            material_index[finish] = len(materials)
            materials.append(material)
        xs, ys, zs = zip(*positions)
        mins = [min(xs), min(ys), min(zs)]
        maxs = [max(xs), max(ys), max(zs)]
        for axis in range(3):
            low[axis] = min(low[axis], mins[axis])
            high[axis] = max(high[axis], maxs[axis])
        # KHR_mesh_quantization: 16-bit positions placed by the node's scale and translation,
        # 8-bit normals. About a third of the float size; three.js and Blender read it natively.
        centre = [(mins[i] + maxs[i]) / 2 for i in range(3)]
        step = [max((maxs[i] - mins[i]) / 2 / 32767.0, 1e-9) for i in range(3)]
        quantized = [tuple(int(round((p[i] - centre[i]) / step[i])) for i in range(3)) for p in positions]
        position_view = add_view(b"".join(struct.pack("<3hxx", *q) for q in quantized), 34962)
        views[position_view]["byteStride"] = 8
        normal_view = add_view(b"".join(struct.pack("<3bx", *(int(round(c * 127)) for c in n)) for n in normals), 34962)
        views[normal_view]["byteStride"] = 4
        wide = len(positions) > 65535
        index_view = add_view(struct.pack(f"<{len(indices)}{'I' if wide else 'H'}", *indices), 34963)
        qx, qy, qz = zip(*quantized)
        accessors.append({"bufferView": position_view, "componentType": 5122, "count": len(positions), "type": "VEC3", "min": [min(qx), min(qy), min(qz)], "max": [max(qx), max(qy), max(qz)]})
        accessors.append({"bufferView": normal_view, "componentType": 5120, "normalized": True, "count": len(normals), "type": "VEC3"})
        accessors.append({"bufferView": index_view, "componentType": 5125 if wide else 5123, "count": len(indices), "type": "SCALAR"})
        primitive = {
            "attributes": {"POSITION": len(accessors) - 3, "NORMAL": len(accessors) - 2},
            "indices": len(accessors) - 1,
            "material": material_index[finish],
        }
        meshes.append({"name": name, "primitives": [primitive]})
        nodes.append({"name": name, "mesh": len(meshes) - 1, "translation": centre, "scale": step})
    if not nodes:
        raise ValueError("No piece has triangles: " + str(path))
    document = {
        "asset": {"version": "2.0", "generator": "AnyBuild part models", "extras": {"units": "mm", "up": "+Z"}},
        "extensionsUsed": ["KHR_mesh_quantization"],
        "extensionsRequired": ["KHR_mesh_quantization"],
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views,
        "accessors": accessors,
    }
    while len(blob) % 4:
        blob.append(0)
    document["buffers"][0]["byteLength"] = len(blob)
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    chunks = _chunk(b"JSON", payload) + _chunk(b"BIN\x00", bytes(blob))
    data = b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"bbox_mm": [round(high[i] - low[i], 2) for i in range(3)], "bytes": len(data), "nodes": len(nodes)}


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + tag + data


def read_glb(path: Path) -> dict[str, list[tuple[float, float, float]]]:
    """Each node's name with its vertex positions in millimetres (node scale and translation applied)."""

    data = Path(path).read_bytes()
    if data[:4] != b"glTF":
        raise ValueError("Not a GLB file: " + str(path))
    length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + length])
    offset = 20 + length
    binary_length = struct.unpack_from("<I", data, offset)[0]
    binary = data[offset + 8 : offset + 8 + binary_length]
    formats = {5126: ("f", 4), 5122: ("h", 2), 5123: ("H", 2), 5120: ("b", 1), 5121: ("B", 1)}
    result: dict[str, list[tuple[float, float, float]]] = {}
    for index, node in enumerate(document.get("nodes", [])):
        if "mesh" not in node:
            continue
        shift = node.get("translation", [0.0, 0.0, 0.0])
        scale = node.get("scale", [1.0, 1.0, 1.0])
        points: list[tuple[float, float, float]] = []
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            accessor = document["accessors"][primitive["attributes"]["POSITION"]]
            view = document["bufferViews"][accessor["bufferView"]]
            code, size = formats[accessor["componentType"]]
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            stride = view.get("byteStride", 3 * size)
            for i in range(accessor["count"]):
                x, y, z = struct.unpack_from("<3" + code, binary, start + i * stride)
                points.append((x * scale[0] + shift[0], y * scale[1] + shift[1], z * scale[2] + shift[2]))
        name = node.get("name") or f"node{index}"
        result[name] = result.get(name, []) + points
    return result
