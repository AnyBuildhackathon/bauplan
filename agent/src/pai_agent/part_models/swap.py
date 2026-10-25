"""Puts the chosen parts' 3D models into a built drone or product GLB, in place of the simple solids.

The drone GLB (FreeCAD or CadQuery, see drone_assembly.py) has one node per scene target, in metres
with y up, its mesh in node-local coordinates around the node's origin. Each motor, propeller,
battery, flight controller and camera node whose part has a model gets the model's triangles
instead, placed the way the simple solid sat: motors on their pad with the leads toward the hub,
props on the bell with the mirror image for the other spin, the pack under the plate with its plug
at the back, the board on its standoffs, the camera facing the nose. A product's bought part, drawn
as a box at its size and position (assembly.py), gets its model turned to fit that box.

Each swapped node keeps its name and origin, so highlighting, exploding and spinning still work,
and says in `extras` which part it shows and whether the model is official, a measured look-alike
or approximate. A part without a model keeps the simple solid.
"""

from __future__ import annotations

import itertools
import json
import math
import struct
from pathlib import Path

from ..paths import REPO_ROOT
from . import model_for
from .web import web_model

WEB_DIR = REPO_ROOT / "web" / "public"

# The node names of the drone's bought parts, and the catalog category behind each.
DRONE_NODES = {"battery": "battery", "flight_controller": "flight_controller", "camera": "camera"}
CORNER_SPIN = {"front_left": -1, "front_right": 1, "rear_left": 1, "rear_right": -1}


def _read(path: Path) -> tuple[dict, bytearray]:
    data = Path(path).read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    document = json.loads(data[20 : 20 + length])
    offset = 20 + length
    binary_length = struct.unpack_from("<I", data, offset)[0]
    return document, bytearray(data[offset + 8 : offset + 8 + binary_length])


def _write(path: Path, document: dict, blob: bytearray) -> None:
    while len(blob) % 4:
        blob.append(0)
    document["buffers"] = [{"byteLength": len(blob)}]
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    total = 12 + 8 + len(payload) + 8 + len(blob)
    Path(path).write_bytes(
        struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(payload), 0x4E4F534A) + payload + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    )


_FORMATS = {5126: ("f", 4, None), 5122: ("h", 2, 32767.0), 5123: ("H", 2, 65535.0), 5120: ("b", 1, 127.0), 5121: ("B", 1, 255.0), 5125: ("I", 4, None)}


def _accessor(document: dict, blob: bytes, index: int) -> list:
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    code, size, norm = _FORMATS[accessor["componentType"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    stride = view.get("byteStride", size * width)
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    out = []
    for i in range(accessor["count"]):
        values = struct.unpack_from("<" + code * width, blob, start + i * stride)
        if accessor.get("normalized") and norm:
            values = tuple(max(-1.0, v / norm) for v in values)
        out.append(values if width > 1 else values[0])
    return out


def model_meshes(glb: Path) -> list[dict]:
    """A part model's pieces: positions and normals in its own frame (mm, z up), indices, material."""

    document, blob = _read(glb)
    pieces = []
    for node in document.get("nodes", []):
        if "mesh" not in node:
            continue
        scale = node.get("scale", [1.0, 1.0, 1.0])
        shift = node.get("translation", [0.0, 0.0, 0.0])
        for primitive in document["meshes"][node["mesh"]]["primitives"]:
            positions = [tuple(p[i] * scale[i] + shift[i] for i in range(3)) for p in _accessor(document, blob, primitive["attributes"]["POSITION"])]
            normals = _accessor(document, blob, primitive["attributes"]["NORMAL"]) if "NORMAL" in primitive["attributes"] else [(0.0, 0.0, 1.0)] * len(positions)
            indices = _accessor(document, blob, primitive["indices"]) if "indices" in primitive else list(range(len(positions)))
            material = document["materials"][primitive["material"]] if "material" in primitive else {"name": "pai:#9a9ca0"}
            pieces.append({"name": node.get("name", ""), "positions": positions, "normals": normals, "indices": indices, "material": material})
    return pieces


def _bounds(points) -> tuple[list[float], list[float]]:
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    return low, high


class Placement:
    """Model frame (mm, z up) to a node's local frame: optional mirror in y, a 3 x 3 turn, then a shift."""

    def __init__(self, matrix=None, shift=(0.0, 0.0, 0.0), mirror: bool = False):
        self.matrix = matrix or [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        self.shift = list(shift)
        self.mirror = mirror

    @staticmethod
    def turn_z(degrees: float) -> list[list[float]]:
        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
        return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]

    def direction(self, v):
        x, y, z = v
        if self.mirror:
            y = -y
        m = self.matrix
        return (m[0][0] * x + m[0][1] * y + m[0][2] * z, m[1][0] * x + m[1][1] * y + m[1][2] * z, m[2][0] * x + m[2][1] * y + m[2][2] * z)

    def point(self, p):
        x, y, z = self.direction(p)
        return (x + self.shift[0], y + self.shift[1], z + self.shift[2])


def _cylinder(x: float, y: float, z0: float, height: float, radius: float, colour: str, sides: int = 16) -> dict:
    """A closed cylinder as a mesh piece (mm, z up), for standoffs under a swapped board."""

    positions, normals, indices = [], [], []
    for k in range(sides):
        a = 2 * math.pi * k / sides
        c, s = math.cos(a), math.sin(a)
        positions += [(x + radius * c, y + radius * s, z0), (x + radius * c, y + radius * s, z0 + height)]
        normals += [(c, s, 0.0), (c, s, 0.0)]
    for k in range(sides):
        a, b = 2 * k, 2 * ((k + 1) % sides)
        indices += [a, b, b + 1, a, b + 1, a + 1]
    for z, nz in ((z0, -1.0), (z0 + height, 1.0)):
        centre = len(positions)
        positions.append((x, y, z))
        normals.append((0.0, 0.0, nz))
        ring = []
        for k in range(sides):
            a = 2 * math.pi * k / sides
            ring.append(len(positions))
            positions.append((x + radius * math.cos(a), y + radius * math.sin(a), z))
            normals.append((0.0, 0.0, nz))
        for k in range(sides):
            i, j = ring[k], ring[(k + 1) % sides]
            indices += [centre, i, j] if nz > 0 else [centre, j, i]
    material = {"name": "pai:" + colour, "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.25, 0.1, 1.0], "metallicFactor": 0.9, "roughnessFactor": 0.35}}
    return {"name": "standoff", "positions": positions, "normals": normals, "indices": indices, "material": material}


def _standoffs(pieces: list[dict], height: float) -> list[dict]:
    """Anodised standoffs from the frame up to the board, under each plated mounting hole."""

    if height <= 0:
        return []
    out = []
    for piece in pieces:
        if piece["name"].startswith("hole_"):
            points = piece["positions"]
            x = sum(p[0] for p in points) / len(points)
            y = sum(p[1] for p in points) / len(points)
            radius = max(math.hypot(p[0] - x, p[1] - y) for p in points)
            out.append(_cylinder(x, y, -height, height, min(radius + 0.4, 2.0), "#ff6a1c"))
    return out


def _to_gltf(p):
    return (p[0] / 1000.0, p[2] / 1000.0, -p[1] / 1000.0)


def _from_gltf(p):
    return (p[0] * 1000.0, -p[2] * 1000.0, p[1] * 1000.0)


def _append(document: dict, blob: bytearray, data: bytes, target: int) -> int:
    while len(blob) % 4:
        blob.append(0)
    document["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target})
    blob.extend(data)
    return len(document["bufferViews"]) - 1


def _primitives(document: dict, blob: bytearray, pieces: list[dict], place: Placement, gltf_axes: bool) -> list[dict]:
    """The pieces as new glTF primitives, placed, in metres y up (drone) or as they are (mm, z up)."""

    materials = document.setdefault("materials", [])
    by_name = {m.get("name"): i for i, m in enumerate(materials)}
    out = []
    for piece in pieces:
        points = [place.point(p) for p in piece["positions"]]
        normals = [place.direction(n) for n in piece["normals"]]
        if gltf_axes:
            points = [_to_gltf(p) for p in points]
            normals = [(n[0], n[2], -n[1]) for n in normals]
        indices = list(piece["indices"])
        if place.mirror:
            # A mirror image turns the triangles inside out; swap two corners of each back.
            for t in range(0, len(indices) - 2, 3):
                indices[t + 1], indices[t + 2] = indices[t + 2], indices[t + 1]
        low, high = _bounds(points)
        position_view = _append(document, blob, struct.pack("<%df" % (3 * len(points)), *[c for p in points for c in p]), 34962)
        normal_view = _append(document, blob, struct.pack("<%df" % (3 * len(normals)), *[c for n in normals for c in n]), 34962)
        index_view = _append(document, blob, struct.pack("<%dI" % len(indices), *indices), 34963)
        accessors = document["accessors"]
        accessors.append({"bufferView": position_view, "componentType": 5126, "count": len(points), "type": "VEC3", "min": low, "max": high})
        accessors.append({"bufferView": normal_view, "componentType": 5126, "count": len(normals), "type": "VEC3"})
        accessors.append({"bufferView": index_view, "componentType": 5125, "count": len(indices), "type": "SCALAR"})
        name = piece["material"].get("name")
        if name not in by_name:
            materials.append(dict(piece["material"]))
            by_name[name] = len(materials) - 1
        out.append({"attributes": {"POSITION": len(accessors) - 3, "NORMAL": len(accessors) - 2}, "indices": len(accessors) - 1, "material": by_name[name]})
    return out


def _old_bounds(document: dict, mesh_index: int, blob: bytes, gltf_axes: bool):
    points = []
    for primitive in document["meshes"][mesh_index]["primitives"]:
        accessor = document["accessors"][primitive["attributes"]["POSITION"]]
        if "min" in accessor and "max" in accessor:
            corners = list(itertools.product(*zip(accessor["min"], accessor["max"])))
        else:
            corners = _accessor(document, blob, primitive["attributes"]["POSITION"])
        points.extend(_from_gltf(c) if gltf_axes else c for c in corners)
    return _bounds(points) if points else None


def part_model(part: dict | None) -> tuple[Path, dict] | None:
    """The GLB and manifest-style info of a chosen part: the library's model, else one for a web find."""

    if not part or not part.get("id"):
        return None
    entry = model_for(str(part["id"]))
    if entry is not None:
        return WEB_DIR / entry["glb"], entry
    return web_model(part)


def _info(entry: dict) -> dict:
    return {
        "part_id": entry["id"],
        "part_name": entry.get("name") or entry["id"],
        "model_kind": entry["kind"],
        "model_missing": entry.get("missing", []),
        "model_source": entry.get("model_url") or entry.get("source_url"),
    }


def _node_frames(document: dict) -> dict:
    """Each named node's absolute origin in the drone's mm frame, parents included."""

    parent = {}
    for index, node in enumerate(document["nodes"]):
        for child in node.get("children", []):
            parent[child] = index
    frames = {}
    for index, node in enumerate(document["nodes"]):
        x = y = z = 0.0
        walk = index
        while walk is not None:
            tx, ty, tz = document["nodes"][walk].get("translation", [0.0, 0.0, 0.0])
            x, y, z = x + tx, y + ty, z + tz
            walk = parent.get(walk)
        frames[node.get("name")] = (index, _from_gltf((x, y, z)))
    return frames


def _bell_top(selected: dict) -> float | None:
    """How high the chosen motor's bell stands above its pad, from its model (mm)."""

    motor = part_model(selected.get("motor"))
    if motor is None:
        return None
    bell = [p for piece in model_meshes(motor[0]) if piece["name"].startswith("bell") for p in piece["positions"]]
    return max(p[2] for p in bell) if bell else None


def _drone_place(name: str, origins: dict, old, selected: dict, bell_top: float | None):
    """For one drone node: its part's model entry, GLB, pieces and placement, or None to keep the solid.

    origins maps node names to absolute origins (mm, z up); old is the simple solid's bounds in the
    node's own frame.
    """

    origin = origins[name]
    if name.startswith("motor_"):
        category = "motor"
        place = Placement(Placement.turn_z(math.degrees(math.atan2(origin[1], origin[0]))))
    elif name.startswith("propeller_"):
        category = "propeller"
        corner = name[len("propeller_") :]
        if bell_top is None:
            return None
        motor_origin = origins.get("motor_" + corner, origin)
        # The hub sits on the bell's top, whatever height the simple prop had.
        place = Placement(shift=(0.0, 0.0, motor_origin[2] + bell_top - origin[2]), mirror=CORNER_SPIN.get(corner, 1) < 0)
    elif name in DRONE_NODES:
        category = DRONE_NODES[name]
        place = None
    else:
        return None
    found = part_model(selected.get(category))
    if found is None:
        return None
    glb, entry = found
    pieces = model_meshes(glb)
    if not pieces:
        return None
    low, high = _bounds([p for piece in pieces for p in piece["positions"]])
    centre_old = [(old[0][i] + old[1][i]) / 2 for i in range(3)]
    if category == "battery":
        # Length along the drone's nose axis with the plug at the back, the top against the plate.
        body = [p for piece in pieces if piece["name"].startswith("body") for p in piece["positions"]] or [p for piece in pieces for p in piece["positions"]]
        b_low, b_high = _bounds(body)
        cx, cy = (b_low[0] + b_high[0]) / 2, (b_low[1] + b_high[1]) / 2
        place = Placement(Placement.turn_z(90.0), (centre_old[0] + cy, centre_old[1] - cx, old[1][2] - b_high[2]))
    elif category == "flight_controller":
        # The board on the standoffs (the node's origin is their top), turned 45 degrees like the
        # frame's stack holes, with a standoff under each of the board's own holes.
        place = Placement(Placement.turn_z(45.0), (centre_old[0], centre_old[1], 0.0))
        pieces = pieces + _standoffs(pieces, -old[0][2] if old[0][2] < 0 else 0.0)
    elif category == "camera":
        cx, cy = (low[0] + high[0]) / 2, (low[1] + high[1]) / 2
        place = Placement(Placement.turn_z(90.0), (centre_old[0] + cy, centre_old[1] - cx, centre_old[2] - (high[2] - low[2]) / 2))
    return entry, glb, pieces, place


def into_drone_glb(path: Path, selected: dict) -> list[dict]:
    """Swaps the bought parts' meshes in a built drone GLB for their models; returns what was swapped."""

    document, blob = _read(path)
    frames = _node_frames(document)
    origins = {name: origin for name, (_, origin) in frames.items()}
    bell_top = _bell_top(selected)
    swapped: list[dict] = []
    for name, (index, origin) in frames.items():
        node = document["nodes"][index]
        if "mesh" not in node or not name:
            continue
        old = _old_bounds(document, node["mesh"], blob, True)
        if old is None:
            continue
        found = _drone_place(name, origins, old, selected, bell_top)
        if found is None:
            continue
        entry, _glb, pieces, place = found
        document["meshes"][node["mesh"]]["primitives"] = _primitives(document, blob, pieces, place, True)
        node.setdefault("extras", {}).update(_info(entry))
        swapped.append({"node": name, **_info(entry)})
    _write(path, document, blob)
    return swapped


def drone_step_solids(nodes: list[dict], selected: dict) -> dict[str, list[tuple[object, object]]]:
    """For drone_assembly's STEP: each node's model solids (finish, CadQuery shape) in node-local mm.

    Only library parts are rebuilt as solids (official STEPs and the look-alike generators); a part
    found on the web keeps its simple solid in the STEP while the GLB shows its model.
    """

    import cadquery as cq

    from .solids import model_solids

    origins = {n["node"]: tuple(n["origin"]) for n in nodes}
    bell_top = _bell_top(selected)
    out: dict[str, list] = {}
    for n in nodes:
        solids = [solid for _, solid in n["solids"]]
        box = cq.Compound.makeCompound([s.val() if hasattr(s, "val") else s for s in solids]).BoundingBox()
        old = ([box.xmin, box.ymin, box.zmin], [box.xmax, box.ymax, box.zmax])
        found = _drone_place(n["node"], origins, old, selected, bell_top)
        if found is None:
            continue
        entry, _glb, _pieces, place = found
        shapes = model_solids(entry)
        if not shapes:
            continue
        # Every drone placement is a turn about z and a shift.
        degrees = math.degrees(math.atan2(place.matrix[1][0], place.matrix[0][0]))
        placed = []
        for fin, shape in shapes:
            if place.mirror:
                shape = shape.mirror("XZ")
            placed.append((fin, shape.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), degrees).translate(cq.Vector(*place.shift))))
        out[n["node"]] = placed
    return out


def _fit_turn(model_size: list[float], box_size: list[float]) -> list[list[float]]:
    """The quarter-turn of the model whose axes best match the box's (both sizes in mm)."""

    best = None
    for perm in itertools.permutations(range(3)):
        error = sum(abs(model_size[perm[i]] - box_size[i]) / max(box_size[i], 1.0) for i in range(3))
        if best is None or error < best[0]:
            best = (error, perm)
    perm = best[1]
    matrix = [[0.0] * 3 for _ in range(3)]
    for i, j in enumerate(perm):
        matrix[i][j] = 1.0
    # Keep it a rotation, not a mirror image.
    det = (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )
    if det < 0:
        matrix[2] = [-v for v in matrix[2]]
    return matrix


def into_product_glb(path: Path, bodies: list[dict], picked: dict, parts: list[dict], rotation) -> list[dict]:
    """Swaps each bought part's box in a product GLB (mm, z up) for its model, fitted to the box."""

    document, blob = _read(path)
    by_name = {node.get("name"): node for node in document.get("nodes", [])}
    spec = {part["id"]: part for part in parts}
    swapped: list[dict] = []
    for body in bodies:
        if body.get("kind") != "bought" or not body.get("stl"):
            continue
        part = spec.get(body["part_id"]) or {}
        found = part_model(picked.get(body["part_id"]))
        node = by_name.get(body["name"])
        if found is None or node is None or "mesh" not in node:
            continue
        glb, entry = found
        pieces = model_meshes(glb)
        # Fit the part's body (not its leads, horn or cable) to the box the spec gave it.
        case = [p for piece in pieces if piece["name"].startswith("body") for p in piece["positions"]] or [p for piece in pieces for p in piece["positions"]]
        low, high = _bounds(case)
        size = [high[i] - low[i] for i in range(3)]
        box = list(part.get("size_mm") or picked[body["part_id"]].get("size_mm") or size)
        fit = _fit_turn(size, [float(v) for v in box])
        turn = rotation(part.get("rotation_deg"))
        matrix = [[sum(turn[i][k] * fit[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        centre = [(low[i] + high[i]) / 2 for i in range(3)]
        moved = Placement(matrix).direction(centre)
        target = body["com_mm"]
        place = Placement(matrix, (target[0] - moved[0], target[1] - moved[1], target[2] - moved[2]))
        document["meshes"][node["mesh"]]["primitives"] = _primitives(document, blob, pieces, place, False)
        node.setdefault("extras", {}).update(_info(entry))
        swapped.append({"node": body["name"], **_info(entry)})
    _write(path, document, blob)
    return swapped
