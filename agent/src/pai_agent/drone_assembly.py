"""The whole drone in CadQuery, for machines without FreeCAD: parametric parts sized from the geometry.

FreeCAD builds the detailed drone (`freecad/frame_build.py`). Without it, this builds the same
assembly from simple solids: the frame plate with its arms on the X corners, each motor as base,
stator (from the motor code) and bell, each propeller as hub and blades of its real diameter,
the pack at its catalog size under the plate, the flight controller board on its mount, the
camera at the nose. Every part comes from `drone_geometry.geometry`, the same description the
mission simulator weighs, so the model, the STEP and the simulation show one product.

The GLB follows frame_build's conventions: metres, y up, the nose is -z, one node per scene target
(`scene.PART_TARGETS`), propellers as children of their motors so they spin about their shafts,
the battery's node at its top centre with its size in `extras`.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from pai_agent.drone_geometry import BATTERY_TOP_MM, PCB_MM, STANDOFF_MM, SHAFT_PROUD_MM

_CARBON_G_PER_MM3 = 1.55 / 1000.0
_ARM_WIDTH_MM = 6.0
_HUB_RADIUS_MM = 20.0
_PAD_RADIUS_MM = 6.0
_TOLERANCE = 0.05

# name: base colour (linear-ish sRGB), metallic, roughness, alpha
_MATERIALS = {
    "carbon": ((0.06, 0.06, 0.07), 0.0, 0.45, 1.0),
    "bell": ((0.09, 0.09, 0.1), 0.6, 0.35, 1.0),
    "steel": ((0.62, 0.63, 0.66), 0.9, 0.3, 1.0),
    "copper": ((0.72, 0.4, 0.18), 0.8, 0.35, 1.0),
    "prop": ((0.2, 0.22, 0.26), 0.0, 0.4, 0.82),
    "battery": ((0.2, 0.21, 0.24), 0.0, 0.5, 1.0),
    "label": ((0.91, 0.76, 0.1), 0.0, 0.45, 1.0),
    "pcb": ((0.05, 0.08, 0.06), 0.0, 0.5, 1.0),
    "chip": ((0.03, 0.03, 0.03), 0.0, 0.4, 1.0),
    "anodized": ((0.75, 0.2, 0.2), 0.7, 0.35, 1.0),
    "camera": ((0.1, 0.1, 0.11), 0.2, 0.4, 1.0),
    "glass": ((0.12, 0.16, 0.25), 0.3, 0.05, 1.0),
}


def build_frame(arm_length_mm: float, thickness_mm: float, motor_spacing_mm: float):
    """The carbon plate: a round hub, four arms on the X corners, motor pads with bolt holes."""

    import cadquery as cq

    angles = (45, 135, 225, 315)

    def arm():
        return cq.Workplane("XY").box(arm_length_mm, _ARM_WIDTH_MM, thickness_mm, centered=(False, True, False))

    frame = arm().rotate((0, 0, 0), (0, 0, 1), angles[0])
    for angle in angles[1:]:
        frame = frame.union(arm().rotate((0, 0, 0), (0, 0, 1), angle))
    frame = frame.union(cq.Workplane("XY").circle(_HUB_RADIUS_MM).extrude(thickness_mm))
    for angle in angles:
        radians = math.radians(angle)
        frame = frame.union(
            cq.Workplane("XY").center(arm_length_mm * math.cos(radians), arm_length_mm * math.sin(radians)).circle(_PAD_RADIUS_MM).extrude(thickness_mm)
        )
    holes: list[tuple[float, float, float]] = [(0.0, 0.0, 2.2)]
    for sign_x in (-1, 1):
        for sign_y in (-1, 1):
            holes.append((13.0 * sign_x, 13.0 * sign_y, 1.1))
    for angle in angles:
        radians = math.radians(angle)
        cx, cy = arm_length_mm * math.cos(radians), arm_length_mm * math.sin(radians)
        holes.append((cx, cy, 1.0))
        for index in range(3):
            hole = math.radians(angle + 30 + index * 120)
            holes.append((cx + motor_spacing_mm / 2.0 * math.cos(hole), cy + motor_spacing_mm / 2.0 * math.sin(hole), 0.8))
    cutters = None
    for x_mm, y_mm, radius in holes:
        cutter = cq.Workplane("XY").center(x_mm, y_mm).circle(radius).extrude(thickness_mm + 2).translate((0, 0, -1))
        cutters = cutter if cutters is None else cutters.union(cutter)
    return frame.cut(cutters)


def _cyl(radius: float, height: float, x: float = 0.0, y: float = 0.0, z: float = 0.0):
    import cadquery as cq

    return cq.Workplane("XY").circle(radius).extrude(height).translate((x, y, z))


def _ring(outer: float, inner: float, height: float, z: float = 0.0):
    import cadquery as cq

    return cq.Workplane("XY").circle(outer).circle(inner).extrude(height).translate((0, 0, z))


def _box(w: float, l: float, h: float, x: float = 0.0, y: float = 0.0, z: float = 0.0):
    import cadquery as cq

    return cq.Workplane("XY").box(w, l, h, centered=(True, True, False)).translate((x, y, z))


def _motor(geo: dict) -> list[tuple[str, object]]:
    """One motor at its own origin (the pad's top): base, stator from the code, bell, shaft."""

    m = geo["motor"]
    bell_r = m["bell_diameter_mm"] / 2.0
    body = max(m["height_mm"] - SHAFT_PROUD_MM, 4.0)
    stator_r = min(m["stator_diameter_mm"] / 2.0, bell_r - 0.9)
    shaft = float(m.get("shaft_mm") or 1.5)
    base = _cyl(bell_r * 0.85, 1.0)
    stator = _ring(stator_r, max(stator_r * 0.45, shaft), m["stator_height_mm"], 1.6)
    bell = _ring(bell_r, bell_r - 0.65, body - 1.9, 1.1).union(_cyl(bell_r, 0.8, 0, 0, body - 0.8))
    spindle = _cyl(shaft / 2.0, m["height_mm"] - 0.6, 0, 0, 0.6)
    return [("steel", base), ("copper", stator), ("bell", bell), ("steel", spindle)]


def _propeller(geo: dict, spin: int) -> list[tuple[str, object]]:
    """A propeller at its own origin (the blade plane): hub and blades at the real diameter."""

    import cadquery as cq

    prop = geo["propeller"]
    radius = prop["diameter_mm"] / 2.0
    blades = max(2, int(prop.get("blades") or 2))
    hub = _cyl(max(2.4, radius * 0.12), 3.0, 0, 0, -1.5)
    chord = max(3.0, radius * 0.32 * 3.0 / blades)
    shape = hub
    for index in range(blades):
        blade = cq.Workplane("XY").box(radius - 1.0, chord, 0.8, centered=(False, True, True)).translate((1.0, 0, 0))
        blade = blade.rotate((0, 0, 0), (1, 0, 0), -spin * 12.0).rotate((0, 0, 0), (0, 0, 1), index * 360.0 / blades)
        shape = shape.union(blade)
    return [("prop", shape)]


def _battery(geo: dict) -> list[tuple[str, object]]:
    """The pack at its catalog size, origin at its top centre."""

    length, width, height = geo["battery"]["size_mm"]
    pack = _box(width, length, height, 0, 0, -height)
    band = _box(width + 0.4, length * 0.46, height + 0.4, 0, length * 0.08, -height - 0.2)
    return [("battery", pack), ("label", band)]


def _flight_controller(geo: dict) -> list[tuple[str, object]]:
    """The board on its mount, turned 45 degrees like the AIO, origin at the standoffs' top."""

    fc = geo["flight_controller"]
    board = fc["board_mm"]
    r = fc["mount_mm"] / 2.0 * math.sqrt(2.0)
    pcb = _box(board, board, PCB_MM).rotate((0, 0, 0), (0, 0, 1), 45)
    standoffs = None
    for x, y in ((0.0, r), (r, 0.0), (0.0, -r), (-r, 0.0)):
        post = _cyl(1.5, STANDOFF_MM, x, y, -STANDOFF_MM)
        standoffs = post if standoffs is None else standoffs.union(post)
    chip = _box(board * 0.24, board * 0.24, 0.9, 0, 0, PCB_MM)
    return [("pcb", pcb), ("anodized", standoffs), ("chip", chip)]


def _camera(size: float) -> list[tuple[str, object]]:
    body = _box(size, size * 0.9, size)
    lens = _cyl(size * 0.32, size * 0.35, 0, 0, 0).rotate((0, 0, 0), (1, 0, 0), -90).translate((0, size * 0.45, size / 2))
    return [("camera", body), ("glass", lens)]


def assembly_parts(geo: dict, frame) -> list[dict]:
    """Every node with its origin (mm, z up) and its solids in node-local mm (the frame's origin is the drone's)."""

    t = geo["thickness_mm"]
    nodes = [{"node": "frame", "origin": (0.0, 0.0, 0.0), "solids": [("carbon", frame)]}]
    body = max(geo["motor"]["height_mm"] - SHAFT_PROUD_MM, 4.0)
    for corner in geo["corners"]:
        origin = (corner["x_mm"], corner["y_mm"], t)
        nodes.append({"node": "motor_" + corner["name"], "origin": origin, "solids": _motor(geo)})
        nodes.append({"node": "propeller_" + corner["name"], "origin": (origin[0], origin[1], t + body + 2.3), "solids": _propeller(geo, corner["spin"]), "parent": "motor_" + corner["name"]})
    nodes.append({"node": "battery", "origin": (0.0, 0.0, BATTERY_TOP_MM), "solids": _battery(geo), "extras": {"size_mm": geo["battery"]["size_mm"]}})
    nodes.append({"node": "flight_controller", "origin": (0.0, 0.0, t + STANDOFF_MM), "solids": _flight_controller(geo)})
    nodes.append({"node": "camera", "origin": (0.0, 15.5, t + 3.0), "solids": _camera(float(geo.get("camera_mm") or 14.0))})
    return nodes


def _to_gltf(x: float, y: float, z: float) -> tuple[float, float, float]:
    return (x / 1000.0, z / 1000.0, -y / 1000.0)


def _mesh(shape) -> tuple[list[float], list[float]]:
    """Flat-shaded triangles of a CadQuery solid, in glTF metres, one normal per face."""

    vertices, triangles = shape.val().tessellate(_TOLERANCE, 0.3)
    positions: list[float] = []
    normals: list[float] = []
    points = [_to_gltf(v.x, v.y, v.z) for v in vertices]
    for a, b, c in triangles:
        pa, pb, pc = points[a], points[b], points[c]
        ux, uy, uz = (pb[i] - pa[i] for i in range(3))
        vx, vy, vz = (pc[i] - pa[i] for i in range(3))
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        for p in (pa, pb, pc):
            positions.extend(p)
            normals.extend((nx / length, ny / length, nz / length))
    return positions, normals


def write_glb(nodes: list[dict], geo: dict, path: Path) -> None:
    blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []
    gltf_nodes: list[dict] = []
    materials = []
    material_index: dict[str, int] = {}

    def add_view(data: bytes) -> int:
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": 34962})
        blob.extend(data)
        return len(views) - 1

    origins = {n["node"]: n["origin"] for n in nodes}
    index_of: dict[str, int] = {}
    for n in nodes:
        primitives = []
        ox, oy, oz = n["origin"]
        for material, solid in n["solids"]:
            positions, normals = _mesh(solid)
            if not positions:
                continue
            if material not in material_index:
                rgb, metal, rough, alpha = _MATERIALS[material]
                entry = {"name": material, "pbrMetallicRoughness": {"baseColorFactor": [*rgb, alpha], "metallicFactor": metal, "roughnessFactor": rough}}
                if alpha < 1.0:
                    entry["alphaMode"] = "BLEND"
                    entry["doubleSided"] = True
                materials.append(entry)
                material_index[material] = len(materials) - 1
            count = len(positions) // 3
            xs, ys, zs = positions[0::3], positions[1::3], positions[2::3]
            pos_view = add_view(struct.pack("<%df" % len(positions), *positions))
            accessors.append({"bufferView": pos_view, "componentType": 5126, "count": count, "type": "VEC3", "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]})
            nrm_view = add_view(struct.pack("<%df" % len(normals), *normals))
            accessors.append({"bufferView": nrm_view, "componentType": 5126, "count": count, "type": "VEC3"})
            primitives.append({"attributes": {"POSITION": len(accessors) - 2, "NORMAL": len(accessors) - 1}, "material": material_index[material]})
        if not primitives:
            continue
        meshes.append({"name": n["node"], "primitives": primitives})
        parent = n.get("parent")
        px, py, pz = origins[parent] if parent else (0.0, 0.0, 0.0)
        entry = {"name": n["node"], "mesh": len(meshes) - 1, "translation": list(_to_gltf(ox - px, oy - py, oz - pz))}
        if n.get("extras"):
            entry["extras"] = n["extras"]
        gltf_nodes.append(entry)
        index_of[n["node"]] = len(gltf_nodes) - 1
    for n in nodes:
        parent = n.get("parent")
        if parent in index_of and n["node"] in index_of:
            gltf_nodes[index_of[parent]].setdefault("children", []).append(index_of[n["node"]])
    children = {i for node in gltf_nodes for i in node.get("children", [])}
    gltf_nodes.append(
        {
            "name": "drone",
            "children": [i for i in range(len(gltf_nodes)) if i not in children],
            "extras": {
                "arm_length_mm": geo["arm_length_mm"],
                "prop_mm": geo["propeller"]["diameter_mm"],
                "battery_mm": geo["battery"]["size_mm"],
                "motor_diameter_mm": geo["motor"]["bell_diameter_mm"],
                "motor_height_mm": geo["motor"]["height_mm"],
                "fc_mount_mm": geo["flight_controller"]["mount_mm"],
            },
        }
    )
    document = {
        "asset": {"version": "2.0", "generator": "AnyBuild drone (CadQuery)"},
        "scene": 0,
        "scenes": [{"nodes": [len(gltf_nodes) - 1]}],
        "nodes": gltf_nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    while len(blob) % 4:
        blob.append(0)
    total = 12 + 8 + len(payload) + 8 + len(blob)
    data = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(payload), 0x4E4F534A) + payload + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    path.write_bytes(data)


def build(directory: Path, params: dict, geo: dict, selected: dict | None = None) -> float:
    """Writes frame.stl, frame.step, the assembly drone.step and the assembly frame.glb; returns the frame mass.

    With the chosen parts (`selected`), the STEP shows each bought part's own model where it has one.
    """

    import cadquery as cq
    from cadquery import exporters

    directory.mkdir(parents=True, exist_ok=True)
    frame = build_frame(params["arm_length_mm"], params["thickness_mm"], params["motor_spacing_mm"])
    exporters.export(frame, str(directory / "frame.stl"))
    exporters.export(frame, str(directory / "frame.step"))
    nodes = assembly_parts(geo, frame)
    # The STEP carries each bought part's own model where the library has one (part_models).
    try:
        from pai_agent.part_models.swap import drone_step_solids

        models = drone_step_solids(nodes, selected) if selected else {}
    except Exception:  # the simple solids stay
        models = {}
    assembly = cq.Assembly(name="drone")
    for n in nodes:
        solids = n["solids"]
        if n["node"] in models:
            # Keep the frame-side standoffs under a swapped flight controller.
            solids = [s for s in solids if s[0] == "anodized"] + models[n["node"]]
        for k, (material, solid) in enumerate(solids):
            if isinstance(material, str):
                color = cq.Color(*_MATERIALS[material][0])
            else:
                color = cq.Color(*(int(material.color[i : i + 2], 16) / 255.0 for i in (1, 3, 5)), material.alpha)
            assembly.add(solid.translate(n["origin"]), name=n["node"] + "_" + str(k), color=color)
    if hasattr(assembly, "export"):
        assembly.export(str(directory / "drone.step"))
    else:
        assembly.save(str(directory / "drone.step"))
    write_glb(nodes, geo, directory / "frame.glb")
    return float(frame.val().Volume()) * _CARBON_G_PER_MM3
