"""Puts the printed parts, bought parts and external loads of a spec together.

Printed parts arrive as per-body STLs from cad_part, in assembly coordinates when their
scripts build them in place. position_mm means the same for every part: the centre of its
bounding box in the assembly, so a printed part with a position is moved there (and
rotated about its own centre), and one without it stays where its script built it.
Bought parts and external loads with a size and position become simple blocks, so
they show up in the model and count for the centre of mass. The result has the mass
properties the checks need: product and total mass, centre of mass, bounding box and
the footprint the assembly stands on.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

from pai_agent.mesh_export import read_stl_vertices, stls_to_glb

# Printed part cost per gram (filament, or a machining estimate for metal).
COST_EUR_PER_G = {"PLA": 0.025, "PETG": 0.025, "ABS": 0.025, "ASA": 0.03, "NYLON": 0.05, "TPU": 0.04, "ALUMINIUM": 0.08, "STEEL": 0.03}
BOUGHT_COLOR = "#3b5bdb"
# Loads are see-through, so the product behind them stays visible.
EXTERNAL_COLOR = "#9aa0aa59"
PRINTED_COLORS = ("#e7e8ec", "#ff8a3d", "#c9ccd3", "#2ed3ae", "#f2c94c", "#8b7cf6")
FOOT_TOLERANCE_MM = 1.0
TOUCH_GAP_MM = 1.5

Vec = tuple[float, float, float]


def rotation(deg: list[float] | None) -> list[list[float]]:
    """Rotation about X, then Y, then Z (degrees), as a 3x3 matrix."""

    rx, ry, rz = (math.radians(v) for v in (deg or [0.0, 0.0, 0.0]))
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return [
        [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
        [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
        [-sy, cy * sx, cy * cx],
    ]


def apply(matrix: list[list[float]], offset: Vec, point: Vec) -> Vec:
    x, y, z = point
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + offset[0],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + offset[1],
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + offset[2],
    )


def write_stl(path: Path, vertices: list[Vec]) -> None:
    """Binary STL from a flat vertex list, three per triangle."""

    count = len(vertices) // 3
    out = bytearray(b"AnyBuild assembly".ljust(80, b" "))
    out += struct.pack("<I", count)
    for index in range(count):
        a, b, c = vertices[3 * index : 3 * index + 3]
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        length = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) or 1.0
        out += struct.pack("<12fH", n[0] / length, n[1] / length, n[2] / length, *a, *b, *c, 0)
    path.write_bytes(bytes(out))


def box_triangles(size: list[float], center: Vec, matrix: list[list[float]]) -> list[Vec]:
    hx, hy, hz = (v / 2.0 for v in size)
    corners = [(sx * hx, sy * hy, sz * hz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    faces = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    placed = [apply(matrix, center, corner) for corner in corners]
    triangles: list[Vec] = []
    for a, b, c, d in faces:
        triangles += [placed[a], placed[b], placed[c], placed[a], placed[c], placed[d]]
    return triangles


def hull_2d(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Convex hull, counter-clockwise (monotone chain)."""

    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _bbox(vertices: list[Vec]) -> list[float]:
    xs, ys, zs = zip(*vertices)
    return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]


def _gap(a: list[float], b: list[float]) -> float:
    """Largest axis gap between two boxes; 0 or less means they touch or overlap."""

    return max(max(a[i] - b[i + 3], b[i] - a[i + 3]) for i in range(3))


def build(spec: dict, built: dict, picked: dict, directory: Path) -> dict:
    """Writes asm-*.stl per body, assembly.stl (printed bodies) and assembly.glb (everything)."""

    bodies: list[dict] = []
    warnings: list[str] = []
    printed_mass = 0.0
    printed_cost = 0.0
    color_index = 0
    for part in spec["parts"]:
        if part["kind"] != "printed":
            continue
        info = built.get(part["id"])
        if info is None:
            warnings.append(part["name"] + " is not built yet.")
            continue
        matrix = rotation(part.get("rotation_deg"))
        box = info["bbox_mm"]
        center = tuple((box[i] + box[i + 3]) / 2.0 for i in range(3))
        target = tuple(part["position_mm"]) if part.get("position_mm") else center
        # About its own centre, then onto its position: v -> R (v - c) + p.
        offset = tuple(target[i] - sum(matrix[i][j] * center[j] for j in range(3)) for i in range(3))
        for index, body in enumerate(info["parts"]):
            vertices = [apply(matrix, offset, v) for v in read_stl_vertices(directory / body["stl"])]
            if len(vertices) < 3:
                continue
            stl = directory / ("asm-" + part["id"] + "-" + str(index) + ".stl")
            write_stl(stl, vertices)
            reference = bool(body.get("reference"))
            com = apply(matrix, offset, tuple(body["com_mm"])) if body.get("com_mm") else None
            color = body.get("color")
            if not color:
                color = BOUGHT_COLOR if reference else PRINTED_COLORS[color_index % len(PRINTED_COLORS)]
            mass = 0.0 if reference else float(body["mass_g"]) * part["qty"]
            bodies.append(
                {
                    "part_id": part["id"],
                    "name": body["name"] if len(info["parts"]) > 1 else part["name"],
                    "kind": "bought" if reference else "printed",
                    "stl": stl.name,
                    "color": color,
                    "mass_g": mass,
                    "com_mm": list(com) if com else None,
                    "bbox_mm": _bbox(vertices),
                    "vertices": vertices,
                }
            )
            if not reference:
                printed_mass += mass
                printed_cost += mass * COST_EUR_PER_G.get(str(body.get("material") or info["material"]).upper(), 0.03)
        color_index += 1

    bought_mass = 0.0
    bought_cost = 0.0
    external_mass = 0.0
    unplaced: list[tuple[str, float]] = []
    for part in spec["parts"]:
        if part["kind"] == "printed":
            continue
        if part["kind"] == "bought":
            item = picked.get(part["id"])
            if item is None:
                warnings.append(part["name"] + " has no part picked yet.")
                continue
            mass = float(item.get("mass_g") or 0.0) * part["qty"]
            bought_mass += mass
            bought_cost += float(item.get("unit_price_eur") or 0.0) * part["qty"]
            size = part.get("size_mm") or item.get("size_mm")
        else:
            mass = float(part["mass_g"]) * part["qty"]
            external_mass += mass
            size = part.get("size_mm")
        position = part.get("position_mm")
        if position is None:
            unplaced.append((part["name"], mass))
            continue
        if not size:
            # A placed part without a size still counts for the centre of mass.
            bodies.append({"part_id": part["id"], "name": part["name"], "kind": part["kind"], "stl": None, "color": None, "mass_g": mass, "com_mm": list(position), "bbox_mm": None, "vertices": []})
            continue
        vertices = box_triangles(list(size), tuple(position), rotation(part.get("rotation_deg")))
        stl = directory / ("asm-" + part["id"] + ".stl")
        write_stl(stl, vertices)
        bodies.append(
            {
                "part_id": part["id"],
                "name": part["name"],
                "kind": part["kind"],
                "stl": stl.name,
                "color": BOUGHT_COLOR if part["kind"] == "bought" else EXTERNAL_COLOR,
                "mass_g": mass,
                "com_mm": list(position),
                "bbox_mm": _bbox(vertices),
                "vertices": vertices,
            }
        )

    shapes = [body for body in bodies if body["vertices"]]
    if not shapes:
        raise ValueError("Nothing to assemble yet: build the printed parts with cad_part first.")
    every = [v for body in shapes for v in body["vertices"]]
    bbox = _bbox(every)
    weighted = [(body["mass_g"], body["com_mm"]) for body in bodies if body["com_mm"] and body["mass_g"] > 0]
    total_known = sum(mass for mass, _ in weighted)
    if total_known > 0:
        com = [sum(mass * c[i] for mass, c in weighted) / total_known for i in range(3)]
    else:
        com = [(bbox[i] + bbox[i + 3]) / 2.0 for i in range(3)]
    for name, mass in unplaced:
        # Unplaced parts sit at the centre of mass found so far, so they add weight without moving it.
        if mass > 0:
            warnings.append(name + " has no position_mm, so its " + f"{mass:.0f}" + " g sit at the centre of mass.")
    total_mass = printed_mass + bought_mass + external_mass

    floor = bbox[2]
    feet = sorted({(round(v[0], 1), round(v[1], 1)) for v in every if v[2] <= floor + FOOT_TOLERANCE_MM})
    footprint = hull_2d(feet)

    for body in shapes:
        others = [o for o in shapes if o["part_id"] != body["part_id"]]
        if others and min(_gap(body["bbox_mm"], o["bbox_mm"]) for o in others) > TOUCH_GAP_MM:
            warnings.append(body["name"] + " floats: it touches no other part. Move it so the parts meet.")

    printed_stls = [directory / body["stl"] for body in shapes if body["kind"] == "printed"]
    assembly_stl = directory / "assembly.stl"
    write_stl(assembly_stl, [v for body in shapes if body["kind"] == "printed" for v in body["vertices"]])
    glb = directory / "assembly.glb"
    stls_to_glb([(body["name"], directory / body["stl"], body["color"]) for body in shapes], glb)
    return {
        "bodies": [{k: v for k, v in body.items() if k != "vertices"} for body in bodies],
        "printed_stls": [p.name for p in printed_stls],
        "stl": assembly_stl.name,
        "glb": glb.name,
        "bbox_mm": [round(v, 2) for v in bbox],
        "size_mm": [round(bbox[i + 3] - bbox[i], 1) for i in range(3)],
        "com_mm": [round(v, 2) for v in com],
        "footprint_mm": [[round(x, 1), round(y, 1)] for x, y in footprint],
        "printed_mass_g": round(printed_mass, 1),
        "bought_mass_g": round(bought_mass, 1),
        "external_mass_g": round(external_mass, 1),
        "product_mass_g": round(printed_mass + bought_mass, 1),
        "total_mass_g": round(total_mass, 1),
        "printed_cost_eur": round(printed_cost, 2),
        "bought_cost_eur": round(bought_cost, 2),
        "cost_eur": round(printed_cost + bought_cost, 2),
        "hull_points_mm": sorted({(round(v[0], 1), round(v[1], 1), round(v[2], 1)) for v in every}),
        "warnings": warnings,
    }
