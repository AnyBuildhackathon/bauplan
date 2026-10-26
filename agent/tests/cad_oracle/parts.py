"""The reference parts: how each one is built and what its exported files must measure.

Every part names the AnyBuild code that builds it and gives its closed-form values: volume, surface
area, centre of mass and bounding box of the printed solid, its solids, its genus (one per through
hole) and the overlap between its bodies, which is 0 for parts meant to print and fit separately.
A value a formula would only restate in a more error-prone way is left out and taken from
recorded.json instead (`python tests/cad_oracle/run.py --record` writes it); README.md says how to
add a part. Lengths are mm, Z is up.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field

from . import build
from .build import Builder

PI = math.pi
SQRT3 = math.sqrt(3.0)


@dataclass
class Expect:
    """Closed-form values; one left at None is compared with its recorded value instead."""

    volume_mm3: float | None = None
    area_mm2: float | None = None
    com_mm: list[float] | None = None
    bbox_mm: list[float] | None = None
    solids: int | None = None
    genus: int | None = None
    overlap_mm3: float | None = None
    mass_g: float | None = None
    # Per body, by name: the same quantities for one body.
    bodies: dict[str, Expect] = field(default_factory=dict)
    # Pairs of bodies that must be mirror images of each other across the plane x = 0.
    mirrored: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Reference:
    name: str
    covers: str
    # What the machine needs: "freecad", "solidcraft" or None (CadQuery is always there).
    needs: str | None
    build: Builder
    expect: Expect
    # Checks that fail because of a defect found and not fixed yet: check name to what is wrong and where it went.
    known: dict[str, str] = field(default_factory=dict)
    # A build of many seconds starts first, so the suite does not wait for it at the end.
    slow: bool = False


def _sum(*pieces: tuple[float, tuple[float, float, float]]) -> tuple[float, list[float]]:
    """Volume and centre of mass of pieces (volume, centre); a cut has a negative volume."""

    volume = sum(v for v, _c in pieces)
    return volume, [sum(v * c[i] for v, c in pieces) / volume for i in range(3)]


def _box(dx, dy, dz, x0, y0, z0):
    return dx * dy * dz, (x0 + dx / 2.0, y0 + dy / 2.0, z0 + dz / 2.0)


def _cylinder(r, h, x, y, z0):
    return PI * r * r * h, (x, y, z0 + h / 2.0)


def _params(**values) -> str:
    """A PARAMS declaration like the one the contract asks Mechanic for; ranges are wide enough to build."""

    lines = ["PARAMS = {"]
    for name, value in values.items():
        lines.append(
            f'    "{name}": {{"value": {value!r}, "min": {value / 2.0!r}, "max": {value * 2.0!r}, "step": 0.1, "unit": "mm", '
            f'"label": "{name.removesuffix("_mm").replace("_", " ").capitalize()}", "group": "Part"}},'
        )
    return "\n".join(lines + ["}"]) + "\n"


# --- Parts Mechanic writes ----------------------------------------------------------------------------------------

PLATE = _params(length_mm=60.0, width_mm=40.0, thickness_mm=5.0, hole_mm=3.4, inset_mm=8.0) + """
L, W, T = P["length_mm"], P["width_mm"], P["thickness_mm"]
r, e = P["hole_mm"] / 2.0, P["inset_mm"]
plate = Part.makeBox(L, W, T, Vector(-L / 2.0, -W / 2.0, 0))
for x in (-L / 2.0 + e, L / 2.0 - e):
    for y in (-W / 2.0 + e, W / 2.0 - e):
        plate = plate.cut(Part.makeCylinder(r, T + 2.0, Vector(x, y, -1.0)))
shape = plate
"""


def _plate() -> Expect:
    L, W, T, r = 60.0, 40.0, 5.0, 1.7
    return Expect(
        volume_mm3=L * W * T - 4 * PI * r * r * T,
        area_mm2=2 * (L * W - 4 * PI * r * r) + 2 * (L + W) * T + 4 * 2 * PI * r * T,
        com_mm=[0.0, 0.0, T / 2.0],
        bbox_mm=[-L / 2, -W / 2, 0.0, L / 2, W / 2, T],
        solids=1,
        genus=4,
        overlap_mm3=0.0,
        mass_g=(L * W * T - 4 * PI * r * r * T) * 1.24 / 1000.0,
    )


COUNTERBORE = _params(size_mm=50.0, thickness_mm=8.0, pitch_mm=34.0, hole_mm=3.4, bore_mm=6.5, depth_mm=3.3) + """
S, T, c = P["size_mm"], P["thickness_mm"], P["depth_mm"]
plate = Part.makeBox(S, S, T, Vector(-S / 2.0, -S / 2.0, 0))
for x in (-P["pitch_mm"] / 2.0, P["pitch_mm"] / 2.0):
    for y in (-P["pitch_mm"] / 2.0, P["pitch_mm"] / 2.0):
        plate = plate.cut(Part.makeCylinder(P["hole_mm"] / 2.0, T + 2.0, Vector(x, y, -1.0)))
        plate = plate.cut(Part.makeCylinder(P["bore_mm"] / 2.0, c + 1.0, Vector(x, y, T - c)))
shape = plate
"""


def _counterbore() -> Expect:
    S, T, c, r1, r2 = 50.0, 8.0, 3.3, 1.7, 3.25
    volume, com = _sum(
        (S * S * T, (0, 0, T / 2)),
        (-4 * PI * r1 * r1 * (T - c), (0, 0, (T - c) / 2)),
        (-4 * PI * r2 * r2 * c, (0, 0, T - c / 2)),
    )
    area = (S * S - 4 * PI * r2 * r2) + (S * S - 4 * PI * r1 * r1) + 4 * S * T
    area += 4 * (2 * PI * r1 * (T - c) + 2 * PI * r2 * c + PI * (r2 * r2 - r1 * r1))
    return Expect(volume, area, [0.0, 0.0, com[2]], [-S / 2, -S / 2, 0.0, S / 2, S / 2, T], 1, 4, 0.0)


BRACKET = _params(base_mm=50.0, width_mm=30.0, thickness_mm=4.0, height_mm=36.0, hole_mm=4.5) + """
B, W, T, H = P["base_mm"], P["width_mm"], P["thickness_mm"], P["height_mm"]
r = P["hole_mm"] / 2.0
bracket = Part.makeBox(B, W, T, Vector(0, -W / 2.0, 0)).fuse(Part.makeBox(T, W, H, Vector(0, -W / 2.0, T)))
for y in (-8.0, 8.0):
    bracket = bracket.cut(Part.makeCylinder(r, T + 2.0, Vector(30.0, y, -1.0)))
    bracket = bracket.cut(Part.makeCylinder(r, T + 2.0, Vector(-1.0, y, 28.0), Vector(1, 0, 0)))
shape = bracket.removeSplitter()
"""


def _bracket() -> Expect:
    B, W, T, H, r = 50.0, 30.0, 4.0, 36.0, 2.25
    hole = PI * r * r * T
    volume, com = _sum(
        _box(B, W, T, 0, -W / 2, 0),
        _box(T, W, H, 0, -W / 2, T),
        (-2 * hole, (30.0, 0.0, T / 2)),
        (-2 * hole, (T / 2, 0.0, 28.0)),
    )
    # Two boxes that share the upright's foot (T x W), four through holes T long.
    area = 2 * (B * W + B * T + W * T) + 2 * (T * W + T * H + W * H) - 2 * T * W + 4 * (2 * PI * r * T - 2 * PI * r * r)
    return Expect(volume, area, com, [0.0, -W / 2, 0.0, B, W / 2, T + H], 1, 4, 0.0)


GUSSET = _params(leg_mm=30.0, rise_mm=20.0, thickness_mm=4.0, hole_mm=4.0) + """
A, B, T = P["leg_mm"], P["rise_mm"], P["thickness_mm"]
outline = Part.makePolygon([Vector(0, 0, 0), Vector(A, 0, 0), Vector(0, 0, B), Vector(0, 0, 0)])
gusset = Part.Face(outline).extrude(Vector(0, T, 0))
shape = gusset.cut(Part.makeCylinder(P["hole_mm"] / 2.0, T + 2.0, Vector(8.0, -1.0, 5.0), Vector(0, 1, 0)))
"""


def _gusset() -> Expect:
    a, b, t, r = 30.0, 20.0, 4.0, 2.0
    face = a * b / 2.0
    volume, com = _sum((face * t, (a / 3, t / 2, b / 3)), (-PI * r * r * t, (8.0, t / 2, 5.0)))
    area = 2 * (face - PI * r * r) + t * (a + b + math.hypot(a, b)) + 2 * PI * r * t
    return Expect(volume, area, com, [0.0, 0.0, 0.0, a, t, b], 1, 1, 0.0)


SHAFT = _params(d1_mm=10.0, l1_mm=30.0, d2_mm=6.0, l2_mm=20.0, tip_mm=4.0, chamfer_mm=1.0, bore_mm=3.0, bore_depth_mm=10.0) + """
R1, R2, R3 = P["d1_mm"] / 2.0, P["d2_mm"] / 2.0, P["tip_mm"] / 2.0
H1, H2, C = P["l1_mm"], P["l2_mm"], P["chamfer_mm"]
shaft = Part.makeCylinder(R1, H1).fuse(Part.makeCylinder(R2, H2, Vector(0, 0, H1)))
shaft = shaft.fuse(Part.makeCone(R2, R3, C, Vector(0, 0, H1 + H2)))
shaft = shaft.cut(Part.makeCylinder(P["bore_mm"] / 2.0, P["bore_depth_mm"] + 1.0, Vector(0, 0, -1.0)))
shape = shaft.removeSplitter()
"""


def _shaft() -> Expect:
    R1, H1, R2, H2, R3, C, RB, DB = 5.0, 30.0, 3.0, 20.0, 2.0, 1.0, 1.5, 10.0
    frustum = PI * C / 3 * (R2 * R2 + R2 * R3 + R3 * R3)
    rise = C * (R2 * R2 + 2 * R2 * R3 + 3 * R3 * R3) / (4 * (R2 * R2 + R2 * R3 + R3 * R3))
    volume, com = _sum(
        _cylinder(R1, H1, 0, 0, 0), _cylinder(R2, H2, 0, 0, H1), (frustum, (0, 0, H1 + H2 + rise)), (-PI * RB * RB * DB, (0, 0, DB / 2))
    )
    area = PI * (R1 * R1 - RB * RB) + 2 * PI * RB * DB + PI * RB * RB + 2 * PI * R1 * H1 + PI * (R1 * R1 - R2 * R2)
    area += 2 * PI * R2 * H2 + PI * (R2 + R3) * math.hypot(R2 - R3, C) + PI * R3 * R3
    return Expect(volume, area, [0.0, 0.0, com[2]], [-R1, -R1, 0.0, R1, R1, H1 + H2 + C], 1, 0, 0.0)


BUSHING = _params(flange_mm=20.0, flange_h_mm=3.0, outer_mm=12.0, length_mm=15.0, bore_mm=8.0) + """
RF, HF, RO, HB, RI = P["flange_mm"] / 2.0, P["flange_h_mm"], P["outer_mm"] / 2.0, P["length_mm"], P["bore_mm"] / 2.0
bush = Part.makeCylinder(RF, HF).fuse(Part.makeCylinder(RO, HB, Vector(0, 0, HF)))
shape = bush.cut(Part.makeCylinder(RI, HF + HB + 2.0, Vector(0, 0, -1.0))).removeSplitter()
"""


def _bushing() -> Expect:
    RF, HF, RO, HB, RI = 10.0, 3.0, 6.0, 15.0, 4.0
    volume, com = _sum((PI * (RF * RF - RI * RI) * HF, (0, 0, HF / 2)), (PI * (RO * RO - RI * RI) * HB, (0, 0, HF + HB / 2)))
    area = PI * (RF * RF - RI * RI) + 2 * PI * RF * HF + PI * (RF * RF - RO * RO) + 2 * PI * RO * HB + PI * (RO * RO - RI * RI)
    area += 2 * PI * RI * (HF + HB)
    return Expect(volume, area, [0.0, 0.0, com[2]], [-RF, -RF, 0.0, RF, RF, HF + HB], 1, 1, 0.0)


def involute_profile(module: float, teeth: int, pressure_deg: float = 20.0, flank: int = 6) -> list[tuple[float, float]]:
    """A spur gear's outline, counter-clockwise: involute flanks from the base circle (radial below it), tip and root arcs."""

    pitch = module * teeth / 2.0
    base = pitch * math.cos(math.radians(pressure_deg))
    tip, root = pitch + module, pitch - 1.25 * module

    def inv(radius: float) -> float:
        phi = math.acos(min(1.0, base / radius))
        return math.tan(phi) - phi

    # Half the tooth's angle at a radius: a quarter pitch at the pitch circle, along the involute elsewhere.
    def half(radius: float) -> float:
        return PI / (2 * teeth) + inv(pitch) - inv(max(radius, base))

    foot = max(base, root)
    radii = [foot + (tip - foot) * i / (flank - 1) for i in range(flank)]
    radial = root < base
    gap = 2 * PI / teeth - 2 * half(foot)
    points = []
    for tooth in range(teeth):
        centre = 2 * PI * tooth / teeth
        flank_up = ([(root, centre - half(foot))] if radial else []) + [(r, centre - half(r)) for r in radii]
        tip_arc = [(tip, centre - half(tip) + 2 * half(tip) * k / 3) for k in (1, 2)]
        flank_down = [(r, centre + half(r)) for r in reversed(radii)] + ([(root, centre + half(foot))] if radial else [])
        root_arc = [(root, centre + half(foot) + gap * k / 3) for k in (1, 2)]
        for radius, angle in flank_up + tip_arc + flank_down + root_arc:
            points.append((round(radius * math.cos(angle), 6), round(radius * math.sin(angle), 6)))
    return points


GEAR_PROFILE = involute_profile(2.0, 18)
GEAR = _params(thickness_mm=6.0, bore_mm=6.0) + f"""
PROFILE = {json.dumps(GEAR_PROFILE)}
T = P["thickness_mm"]
outline = Part.makePolygon([Vector(x, y, 0) for x, y in PROFILE] + [Vector(PROFILE[0][0], PROFILE[0][1], 0)])
gear = Part.Face(outline).extrude(Vector(0, 0, T))
shape = gear.cut(Part.makeCylinder(P["bore_mm"] / 2.0, T + 2.0, Vector(0, 0, -1.0)))
"""


def _gear() -> Expect:
    t, r = 6.0, 3.0
    pts = GEAR_PROFILE + GEAR_PROFILE[:1]
    cross = [(x0 * y1 - x1 * y0, x0, y0, x1, y1) for (x0, y0), (x1, y1) in itertools.pairwise(pts)]
    face = sum(c[0] for c in cross) / 2.0
    cx = sum(c[0] * (c[1] + c[3]) for c in cross) / (6 * face)
    cy = sum(c[0] * (c[2] + c[4]) for c in cross) / (6 * face)
    rim = sum(math.dist(a, b) for a, b in itertools.pairwise(pts))
    section = face - PI * r * r
    xs, ys = [p[0] for p in GEAR_PROFILE], [p[1] for p in GEAR_PROFILE]
    return Expect(
        volume_mm3=section * t,
        area_mm2=2 * section + rim * t + 2 * PI * r * t,
        com_mm=[cx * face / section, cy * face / section, t / 2],
        bbox_mm=[min(xs), min(ys), 0.0, max(xs), max(ys), t],
        solids=1,
        genus=1,
        overlap_mm3=0.0,
    )


FILLET = _params(length_mm=40.0, width_mm=30.0, height_mm=10.0, radius_mm=5.0) + """
L, W, H = P["length_mm"], P["width_mm"], P["height_mm"]
box = Part.makeBox(L, W, H, Vector(-L / 2.0, -W / 2.0, 0))
upright = [edge for edge in box.Edges if abs(edge.Vertexes[0].Point.z - edge.Vertexes[1].Point.z) > 0.001]
shape = box.makeFillet(P["radius_mm"], upright)
"""


def _fillet() -> Expect:
    L, W, H, R = 40.0, 30.0, 10.0, 5.0
    face = L * W - (4 - PI) * R * R
    rim = 2 * (L - 2 * R) + 2 * (W - 2 * R) + 2 * PI * R
    return Expect(face * H, 2 * face + rim * H, [0.0, 0.0, H / 2], [-L / 2, -W / 2, 0.0, L / 2, W / 2, H], 1, 0, 0.0)


TORUS = _params(ring_mm=24.0, cord_mm=4.0) + """
shape = Part.makeTorus(P["ring_mm"] / 2.0, P["cord_mm"] / 2.0)
materials = {"Part": "TPU"}
"""


def _torus() -> Expect:
    R, r = 12.0, 2.0
    volume = 2 * PI * PI * R * r * r
    return Expect(volume, 4 * PI * PI * R * r, [0.0, 0.0, 0.0], [-R - r, -R - r, -r, R + r, R + r, r], 1, 1, 0.0, volume * 1.21 / 1000.0)


# The sensor box: a shell with four posts for M3 heat-set inserts, and its lid with four M3 screws (pai_agent.fasteners).
POSTS = [[x, y] for x in (-23.0, 23.0) for y in (-13.0, 13.0)]
ENCLOSURE = _params(length_mm=60.0, width_mm=40.0, height_mm=25.0, wall_mm=2.0, post_mm=8.0) + """
L, W, H, w = P["length_mm"], P["width_mm"], P["height_mm"], P["wall_mm"]
box = Part.makeBox(L, W, H, Vector(-L / 2.0, -W / 2.0, 0))
box = box.cut(Part.makeBox(L - 2 * w, W - 2 * w, H, Vector(-L / 2.0 + w, -W / 2.0 + w, w)))
for x in (-23.0, 23.0):
    for y in (-13.0, 13.0):
        box = box.fuse(Part.makeCylinder(P["post_mm"] / 2.0, H - w, Vector(x, y, w)))
shape = box.removeSplitter()
"""
INSERTS = {"name": "Lid insert", "kind": "insert", "size": "M3 short", "at": [[x, y, 25.0] for x, y in POSTS]}
LID = _params(length_mm=60.0, width_mm=40.0, thickness_mm=3.0) + """
L, W, T = P["length_mm"], P["width_mm"], P["thickness_mm"]
shape = Part.makeBox(L, W, T, Vector(-L / 2.0, -W / 2.0, 25.0))
"""
SCREWS = {"name": "Lid screw", "kind": "screw", "standard": "ISO 4762", "size": "M3x8", "at": [[x, y, 28.0] for x, y in POSTS], "fit": "medium"}

# The standard parts' sizes, from the bd_warehouse tables they are built from (pai_agent/fasteners/data).
ISO_4762_M3 = {"dk": 5.68, "k": 3.0, "s": 2.5, "t": 1.3, "d": 3.0, "pitch": 0.5}
ISO_4032_M3 = {"s": 5.5, "m": 2.4, "d": 3.0}
ISO_7089_M3 = {"d1": 3.2, "d2": 7.0, "h": 0.55}
RUTHEX_M3X4 = {"s": 4.6, "m": 4.0, "d": 3.0, "drill": 0.159 * 25.4}  # drill #21
ISO_273_MEDIUM_M3 = 3.4


def socket_screw(length: float, at=(0.0, 0.0, 0.0)) -> Expect:
    """ISO 4762 without its thread, as pai_agent.fasteners models it: a head with a 0.06 dk chamfer on top and a hex
    socket, a shank with a tip chamfer of min(0.6 pitch, 0.2 d), seated at `at` with the shank pointing down."""

    p = ISO_4762_M3
    rk, k, s, t, r = p["dk"] / 2, p["k"], p["s"], p["t"], p["d"] / 2
    c, tip, hex_area = 0.06 * p["dk"], min(0.6 * p["pitch"], 0.2 * p["d"]), SQRT3 / 2 * s * s
    x, y, z = at
    volume, com = _sum(
        _cylinder(rk, k, x, y, z),
        (-PI * c * c * (rk - c / 3), (x, y, z + k - c / 3)),
        (-hex_area * t, (x, y, z + k - t / 2)),
        _cylinder(r, length, x, y, z - length),
        (-PI * tip * tip * (r - tip / 3), (x, y, z - length + tip / 3)),
    )
    area = PI * (rk - c) ** 2 - hex_area + PI * (2 * rk - c) * c * math.sqrt(2) + 2 * PI * rk * (k - c) + PI * (rk * rk - r * r)
    area += 2 * SQRT3 * s * t + hex_area + 2 * PI * r * (length - tip) + PI * (2 * r - tip) * tip * math.sqrt(2) + PI * (r - tip) ** 2
    return Expect(volume, area, com, [x - rk, y - rk, z - length, x + rk, y + rk, z + k], 1, 0, mass_g=volume * 7.85 / 1000.0)


def heat_set_insert(at=(0.0, 0.0, 0.0)) -> Expect:
    p = RUTHEX_M3X4
    R, r, m = p["s"] / 2, p["d"] / 2, p["m"]
    x, y, z = at
    volume = PI * (R * R - r * r) * m
    area = 2 * PI * (R * R - r * r) + 2 * PI * (R + r) * m
    return Expect(volume, area, [x, y, z - m / 2], [x - R, y - R, z - m, x + R, y + R, z], 1, 1, mass_g=volume * 8.5 / 1000.0)


def _enclosure() -> Expect:
    L, W, H, w, rp, rh, depth = 60.0, 40.0, 25.0, 2.0, 4.0, RUTHEX_M3X4["drill"] / 2, RUTHEX_M3X4["m"] + 1.0
    volume, com = _sum(
        _box(L, W, H, -L / 2, -W / 2, 0),
        (-(L - 2 * w) * (W - 2 * w) * (H - w), (0, 0, w + (H - w) / 2)),
        (4 * PI * rp * rp * (H - w), (0, 0, w + (H - w) / 2)),
        (-4 * PI * rh * rh * depth, (0, 0, H - depth / 2)),
    )
    shell = L * W + 2 * (L + W) * H + (L * W - (L - 2 * w) * (W - 2 * w)) + 2 * (L + W - 4 * w) * (H - w) + (L - 2 * w) * (W - 2 * w)
    # Each post adds its wall and replaces the floor under it by its top; each insert hole adds its wall.
    area = shell + 4 * 2 * PI * rp * (H - w) + 4 * 2 * PI * rh * depth
    inserts = {"Lid insert " + str(i + 1): heat_set_insert((x, y, 25.0)) for i, (x, y) in enumerate(POSTS)}
    return Expect(volume, area, [0.0, 0.0, com[2]], [-L / 2, -W / 2, 0.0, L / 2, W / 2, H], 1, 0, 0.0, volume * 1.27 / 1000.0, inserts)


def _lid() -> Expect:
    L, W, T, z0, r = 60.0, 40.0, 3.0, 25.0, ISO_273_MEDIUM_M3 / 2
    volume = L * W * T - 4 * PI * r * r * T
    area = 2 * (L * W - 4 * PI * r * r) + 2 * (L + W) * T + 4 * 2 * PI * r * T
    screws = {"Lid screw " + str(i + 1): socket_screw(8.0, (x, y, 28.0)) for i, (x, y) in enumerate(POSTS)}
    return Expect(volume, area, [0.0, 0.0, z0 + T / 2], [-L / 2, -W / 2, z0, L / 2, W / 2, z0 + T], 1, 4, 0.0, volume * 1.27 / 1000.0, screws)


# --- The FreeCAD library ----------------------------------------------------------------------------------------------


def _template(name: str) -> str:
    from pai_agent.tools.cad_part import library_script

    return library_script(name)


def _gripper_gear(cx: float, phase: float, z0: float, t: float) -> Expect:
    """The template's gear: a cylinder of R - m with 16 teeth of 2.2 m x 1.6 m set in 0.2 m, and a 3.2 mm bore."""

    m, teeth = 1.5, 16
    r0, w = m * teeth / 2 - m, 0.8 * m
    inner, outer = r0 - 0.2 * m, r0 + 2.0 * m

    def strip(y: float) -> float:
        return y * math.sqrt(r0 * r0 - y * y) / 2 + r0 * r0 / 2 * math.asin(y / r0) - inner * y

    # The part of each tooth inside the cylinder, and the length of each tooth side outside it.
    inside = strip(w) - strip(-w)
    side = outer - math.sqrt(r0 * r0 - w * w)
    section = PI * r0 * r0 + teeth * (2.2 * m * 2 * w - inside) - PI * 1.6 * 1.6
    rim = 2 * PI * r0 - teeth * r0 * 2 * math.asin(w / r0) + teeth * (2 * side + 2 * w) + 2 * PI * 1.6
    corners = []
    for i in range(teeth):
        a = phase + 2 * PI * i / teeth
        for v in (-w, w):
            corners.append((cx + outer * math.cos(a) - v * math.sin(a), outer * math.sin(a) + v * math.cos(a)))
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    volume = section * t
    return Expect(volume, 2 * section + rim * t, [cx, 0.0, z0 + t / 2], [min(xs), min(ys), z0, max(xs), max(ys), z0 + t], 1, 1, mass_g=volume * 1.24 / 1000.0)


def _gripper() -> Expect:
    """The template at its defaults: finger 70, jaw 76, thickness 6, pad 3; the servo 40.7 x 19.7 x 42.9 hangs under the palm."""

    L, OPEN, T, PAD, SL, SW, SH, SHAFT = 70.0, 76.0, 6.0, 3.0, 40.7, 19.7, 42.9, 10.0
    R, PLATE, FW = 12.0, 4.0, 9.0
    Z0 = PLATE + 0.6
    ZF = Z0 + T
    width, depth = OPEN + 2 * (PAD + FW) + 12, SL + 16
    y0 = -depth + 14
    small, large = PI * 1.7 * 1.7 * PLATE, PI * 3.2 * 3.2 * PLATE
    corners = [(sx * (width / 2 - 6), y) for sx in (-1, 1) for y in (-depth + 20, 8.0)]
    flange_holes = [(fx, 2 + fz) for fx in (-12.5, 12.5) for fz in (-12.5, 12.5)]
    palm_volume, palm_com = _sum(
        _box(width, depth, PLATE, -width / 2, y0, 0),
        (-large, (-R, 0, PLATE / 2)),
        (-small, (R, 0, PLATE / 2)),
        *[(-small, (x, y, PLATE / 2)) for x, y in corners],
        _box(36, PLATE, 36, -18, y0 - PLATE, -16),
        *[(-small, (x, y0 - PLATE / 2, z)) for x, z in flange_holes],
    )
    # The plate's back face meets the flange's front over 36 x 4; ten holes go through 4 mm.
    palm_area = 2 * (width * depth + width * PLATE + depth * PLATE) + 2 * (36 * PLATE + 36 * 36 + PLATE * 36) - 2 * 36 * PLATE
    palm_area += sum(2 * PI * r * PLATE - 2 * PI * r * r for r in [3.2] + [1.7] * 9)
    pad_volume = PAD * 0.45 * L * T
    pads = {
        name: Expect(
            pad_volume, 2 * (PAD * 0.45 * L + PAD * T + 0.45 * L * T), [x0 + PAD / 2, 0.775 * L, ZF + T / 2],
            [x0, 0.55 * L, ZF, x0 + PAD, L, ZF + T], 1, 0, mass_g=pad_volume * 1.21 / 1000.0,
        )
        for name, x0 in (("Pad L", -OPEN / 2 - PAD), ("Pad R", OPEN / 2))
    }
    servo_volume, servo_com = _sum(_box(SW, SL, SH, -R - SW / 2, -SHAFT, -SH), _cylinder(2.4, PLATE + 0.6, -R, 0, 0))
    servo_area = 2 * (SW * SL + SW * SH + SL * SH) + 2 * PI * 2.4 * (PLATE + 0.6)
    return Expect(
        solids=7,
        # The palm's ten holes, each gear's bore and each finger's pivot hole.
        genus=10 + 2 + 2,
        overlap_mm3=0.0,
        bodies={
            "Palm": Expect(palm_volume, palm_area, palm_com, [-width / 2, y0 - PLATE, -16.0, width / 2, 14.0, 20.0], 1, 10, mass_g=palm_volume * 1.24 / 1000.0),
            "Gear L": _gripper_gear(-R, 0.0, Z0, T),
            "Gear R": _gripper_gear(R, PI / 16, Z0, T),
            **pads,
            "Servo": Expect(servo_volume, servo_area, servo_com, [-R - SW / 2, -SHAFT, -SH, -R + SW / 2, SL - SHAFT, PLATE + 0.6], 1, 0),
        },
        mirrored=[("Finger L", "Finger R"), ("Pad L", "Pad R")],
    )


def _reference_script(product: str, part: str) -> tuple[str, dict, str]:
    """A reference build's script, the parameters and material its reference.json builds it with."""

    from pai_agent.references import REFERENCES_DIR

    folder = REFERENCES_DIR / product
    spec = json.loads((folder / "reference.json").read_text(encoding="utf-8"))
    row = next(p for p in spec["spec"]["parts"] if p["id"] == part)
    return (folder / spec["scripts"][part]["file"]).read_text(encoding="utf-8"), row.get("params") or {}, row.get("material") or "PLA"


STAND_BASE, STAND_BASE_PARAMS, STAND_MATERIAL = _reference_script("phone-stand", "base")
STAND_REST, STAND_REST_PARAMS, _ = _reference_script("phone-stand", "back-rest")


def _phone_stand_base() -> Expect:
    """An L-section (plate 110 x 5, lip 5 x 12 on its front) 80 wide, with a cable slot 14 wide and 11 deep through the front."""

    W, D, T, LIP, FRONT = 80.0, 110.0, 5.0, 12.0, -25.0
    # The section in the y-z plane and the slot's share of it, as (area, y, z) pieces.
    section = [(D * T, FRONT + D / 2, T / 2), (5.0 * LIP, FRONT + 2.5, T + LIP / 2)]
    slot = [(5.0 * (T + LIP), FRONT + 2.5, (T + LIP) / 2), (6.0 * T, FRONT + 8.0, T / 2)]
    volume, com = _sum(*[(a * W, (0.0, y, z)) for a, y, z in section], *[(-a * 14.0, (0.0, y, z)) for a, y, z in slot])
    rim = (T + LIP) + 5.0 + LIP + (D - 5.0) + T + D
    slot_area = sum(a for a, _y, _z in slot)
    # The slot takes 14 mm of the front, the lip, its step, 6 mm of plate top and 11 mm of bottom, and adds its walls.
    area = 2 * sum(a for a, _y, _z in section) + rim * W - (T + LIP + 5.0 + LIP + 6.0 + 11.0) * 14.0 + 2 * slot_area + 14.0 * T
    return Expect(volume, area, [0.0, com[1], com[2]], [-W / 2, FRONT, 0.0, W / 2, FRONT + D, T + LIP], 1, 0, 0.0, volume * 1.27 / 1000.0)


# --- Standard parts, the CadQuery fallbacks and SolidCraft ------------------------------------------------------------------


def _nut() -> Expect:
    """ISO 4032 M3 as the module builds it: a hex prism whose corners are cut by a 30 degree cone at both faces, bored through."""

    s, m, d = ISO_4032_M3["s"], ISO_4032_M3["m"], ISO_4032_M3["d"]
    e = s / math.cos(math.radians(30))
    a, c = s / 2, (e - s) / 2 * math.tan(math.radians(30))

    def section(rho: float) -> float:
        return PI * rho * rho - 6 * (rho * rho * math.acos(min(1.0, a / rho)) - a * math.sqrt(max(0.0, rho * rho - a * a)))

    # Simpson's rule over the chamfer, where the cone's radius runs from s/2 to e/2.
    n = 2000
    weights = [1 if i in (0, n) else 4 if i % 2 else 2 for i in range(n + 1)]
    chamfer = c / (3 * n) * sum(wt * section(a + (e / 2 - a) * i / n) for i, wt in enumerate(weights))
    volume = 2 * chamfer + (m - 2 * c) * SQRT3 / 2 * s * s - PI * d * d / 4 * m
    return Expect(volume_mm3=volume, com_mm=[0.0, 0.0, m / 2], bbox_mm=[-e / 2, -s / 2, 0.0, e / 2, s / 2, m], solids=1, genus=1, mass_g=volume * 7.85 / 1000.0)


def _washer() -> Expect:
    d1, d2, h = ISO_7089_M3["d1"], ISO_7089_M3["d2"], ISO_7089_M3["h"]
    volume = PI / 4 * (d2 * d2 - d1 * d1) * h
    area = 2 * PI / 4 * (d2 * d2 - d1 * d1) + PI * (d1 + d2) * h
    return Expect(volume, area, [0.0, 0.0, h / 2], [-d2 / 2, -d2 / 2, 0.0, d2 / 2, d2 / 2, h], 1, 1, mass_g=volume * 7.85 / 1000.0)


def _block() -> Expect:
    """run_block's 40 x 30 x 12 block with the clearance hole of an M3x10 seated on top: down to 1 mm past the shank."""

    L, W, H, r = 40.0, 30.0, 12.0, ISO_273_MEDIUM_M3 / 2
    depth = 10.0 + 1.0
    volume, com = _sum(_box(L, W, H, -L / 2, -W / 2, 0), (-PI * r * r * depth, (0, 0, H - depth / 2)))
    area = 2 * (L * W + L * H + W * H) + 2 * PI * r * depth
    return Expect(
        volume, area, [0.0, 0.0, com[2]], [-L / 2, -W / 2, 0.0, L / 2, W / 2, H], 1, 0, 0.0, volume * 1.24 / 1000.0,
        {"Block screw": socket_screw(10.0, (0.0, 0.0, H))},
    )


def _frame_defaults() -> dict:
    from pai_agent.tools.cad import DEFAULT_PARAMS

    return dict(DEFAULT_PARAMS)


def _drone_frame(params: dict) -> Expect:
    """The whoop frame: arms on the X corners ending in 6 mm pads, a hub hole, four stack holes and per pad a shaft hole
    and three motor holes, so 21 through holes; it is symmetric about its centre."""

    arm, t = params["arm_length_mm"], params["thickness_mm"]
    reach = arm * math.cos(math.radians(45)) + 6.0
    return Expect(com_mm=[0.0, 0.0, t / 2], bbox_mm=[-reach, -reach, 0.0, reach, reach, t], solids=1, genus=21, overlap_mm3=0.0)


def _hero_frame(params: dict) -> Expect:
    """frame_build's unibody plate: arms on the X corners ending in 6.2 mm pads, a lightening window under the flight
    controller and per arm a slot, a shaft hole and three motor holes, four standoff holes: 25 through holes."""

    reach = params["arm_length_mm"] * math.cos(math.radians(45)) + 6.2
    return Expect(bbox_mm=[-reach, -reach, 0.0, reach, reach, params["thickness_mm"]], solids=1, genus=25)


def _solidcraft_plate() -> dict:
    holes = [[x, y] for x in (-22.0, 22.0) for y in (-12.0, 12.0)]
    return {
        "commands": [
            {"command": "file.new", "params": {"name": "Plate with holes"}},
            {"command": "solid.box", "params": {"corner": [-30, -20, 0], "length": 60, "width": 40, "height": 5, "body_name": "Plate"}},
            *[
                {"command": "solid.cylinder", "params": {"base": [x, y, -1], "diameter": 3.4, "height": 7, "operation": "cut", "targets": ["Plate"]}}
                for x, y in holes
            ],
        ]
    }


def _solidcraft_library(name: str) -> dict:
    from pai_agent.tools.solidcraft_part import library_script

    return library_script(name)


def _solidcraft_gripper() -> Expect:
    """The library's two-finger gripper: boxes and cylinders, each finger the mirror image of the other."""

    def box(dx, dy, dz, x0, y0, z0) -> Expect:
        volume, com = _box(dx, dy, dz, x0, y0, z0)
        return Expect(volume, 2 * (dx * dy + dx * dz + dy * dz), list(com), [x0, y0, z0, x0 + dx, y0 + dy, z0 + dz], 1, 0)

    def cylinder(r, h, x, z0) -> Expect:
        volume, com = _cylinder(r, h, x, 0.0, z0)
        return Expect(volume, 2 * PI * r * r + 2 * PI * r * h, list(com), [x - r, -r, z0, x + r, r, z0 + h], 1, 0)

    fx = 50 / 2 + 3 + 8 / 2
    bodies = {
        "Palm plate": box(76, 26, 4, -38, -12, -4),
        "Wrist flange": box(76, 6, 18, -38, 14, -4),
        "Axle L": cylinder(2, 11, -8, -4),
        "Axle R": cylinder(2, 11, 8, -4),
        "Gear L": cylinder(8, 6, -8, 0),
        "Gear R": cylinder(8, 6, 8, 0),
        "Root bar L": box(fx + 4 - 12, 8, 5, -fx - 4, -4, 0),
        "Root bar R": box(fx + 4 - 12, 8, 5, 12, -4, 0),
        "Finger bar L": box(8, 64, 5, -fx - 4, -60, 0),
        "Finger bar R": box(8, 64, 5, fx - 4, -60, 0),
        "Pad L": box(3, 18, 5, -28, -60, 0),
        "Pad R": box(3, 18, 5, 25, -60, 0),
    }
    pairs = [(a, a[:-1] + "R") for a in bodies if a.endswith(" L")]
    return Expect(solids=12, genus=0, overlap_mm3=0.0, bodies=bodies, mirrored=pairs)


REFERENCES = [
    Reference("plate-holes", "A part script as Mechanic writes it: a plate with four M3 clearance holes", "freecad", build.freecad(PLATE, "plate-holes"), _plate()),
    Reference("plate-counterbore", "Plate with four counterbored holes, cylinders cut at two depths", "freecad", build.freecad(COUNTERBORE, "plate-counterbore"), _counterbore()),
    Reference("l-bracket", "L-bracket from two fused boxes, two vertical and two horizontal holes", "freecad", build.freecad(BRACKET, "l-bracket"), _bracket()),
    Reference("gusset", "Triangular gusset from an extruded polygon face, with a hole across it", "freecad", build.freecad(GUSSET, "gusset"), _gusset()),
    Reference("stepped-shaft", "Stepped shaft: two cylinders, a cone chamfer and a blind centre bore", "freecad", build.freecad(SHAFT, "stepped-shaft"), _shaft()),
    Reference("flanged-bushing", "Flanged bushing with a through bore", "freecad", build.freecad(BUSHING, "flanged-bushing"), _bushing()),
    Reference("spur-gear", "Involute spur gear, module 2, 18 teeth: a 324-point polygon extruded, with a bore", "freecad", build.freecad(GEAR, "spur-gear"), _gear()),
    Reference("fillet-block", "Block with its four upright edges filleted (makeFillet)", "freecad", build.freecad(FILLET, "fillet-block"), _fillet()),
    Reference("o-ring", "Torus in TPU: doubly curved faces and a part material of its own", "freecad", build.freecad(TORUS, "o-ring"), _torus()),
    Reference(
        "enclosure-inserts", "Sensor box shell with four posts and M3 heat-set inserts (U4) cut by the harness", "freecad",
        build.freecad(ENCLOSURE, "enclosure-inserts", material="PETG", fasteners=[INSERTS]), _enclosure(),
    ),
    Reference(
        "lid-screws", "Its lid with four ISO 4762 M3x8 screws (U4) in ISO 273 medium clearance holes", "freecad",
        build.freecad(LID, "lid-screws", material="PETG", fasteners=[SCREWS]), _lid(),
    ),
    Reference(
        "gripper-template", "The FreeCAD library's gripper template: palm, gears, fingers, pads and the reference servo", "freecad",
        build.freecad(_template("gripper"), "gripper-template", template="gripper"), _gripper(),
        known={
            "STEP overlap_mm3": "the gears' rectangular teeth, 2.4 mm wide in 2.3 mm gaps at the pitch circle, cut 6.8 mm3 into each other's flanks where they mesh; "
            "agent/freecad/library/gripper.py is locked; see What it caught in README.md",
        },
    ),
    Reference(
        "phone-stand-base", "Reference build script: the phone stand's base plate with lip and cable slot", "freecad",
        build.freecad(STAND_BASE, "phone-stand-base", params=STAND_BASE_PARAMS, material=STAND_MATERIAL), _phone_stand_base(),
    ),
    Reference(
        "phone-stand-back-rest", "Reference build script: the leaning back rest with two gussets, cut at the base top", "freecad",
        build.freecad(STAND_REST, "phone-stand-back-rest", params=STAND_REST_PARAMS, material=STAND_MATERIAL), Expect(solids=1, overlap_mm3=0.0),
    ),
    Reference(
        "screw-iso4762-m3x10", "Standard part (U4): ISO 4762 M3x10 socket head screw", None,
        build.standard_part({"kind": "screw", "standard": "ISO 4762", "size": "M3x10", "at": [0, 0, 0]}, "screw"), socket_screw(10.0),
    ),
    Reference("nut-iso4032-m3", "Standard part (U4): ISO 4032 M3 hex nut, chamfered both sides", None, build.standard_part({"kind": "nut", "size": "M3", "at": [0, 0, 0], "hole": "none"}, "nut"), _nut()),
    Reference("washer-iso7089-m3", "Standard part (U4): ISO 7089 M3 washer", None, build.standard_part({"kind": "washer", "size": "M3", "at": [0, 0, 0]}, "washer"), _washer()),
    Reference("insert-m3x4", "Standard part (U4): ruthex M3x4 heat-set insert", None, build.standard_part({"kind": "insert", "size": "M3 short", "at": [0, 0, 0]}, "insert"), heat_set_insert()),
    Reference(
        "fallback-block", "CadQuery stand-in without FreeCAD (run_block) with a screw's clearance hole", None,
        build.block([40.0, 30.0, 12.0], "fallback-block", fasteners=[{"name": "Block screw", "kind": "screw", "size": "M3x10", "at": [0, 0, 12]}]), _block(),
    ),
    Reference("drone-frame", "The drone's carbon frame plate from the CadQuery fallback, at cad_frame's defaults", None, build.drone_frame(_frame_defaults()), _drone_frame(_frame_defaults())),
    Reference(
        "hero-frame", "The drone's carbon frame plate as headless FreeCAD builds it with the whole drone, at cad_frame's defaults", "freecad",
        build.hero_frame(_frame_defaults()), _hero_frame(_frame_defaults()), slow=True,
    ),
    Reference("solidcraft-plate", "The plate with holes again, as a SolidCraft script: the same numbers from another kernel", "solidcraft", build.solidcraft(_solidcraft_plate(), "solidcraft-plate"), _plate()),
    Reference(
        "solidcraft-four-bar", "SolidCraft library: SolidCraft's Chebyshev four-bar, 13 bodies on four hinges, its pins drawn through the links they join",
        "solidcraft", build.solidcraft(_solidcraft_library("four_bar"), "solidcraft-four-bar"), Expect(solids=13),
    ),
    Reference(
        "solidcraft-gripper", "SolidCraft library: the two-finger gripper on meshing gears", "solidcraft",
        build.solidcraft(_solidcraft_library("two_finger_gripper"), "solidcraft-gripper"), _solidcraft_gripper(),
        known={
            "STEP overlap_mm3": "1184 mm3 shared: each finger's root bar overlaps its gear and its finger bar, the axles run through the palm plate "
            "and through gears without a bore, so measure (and the URDF masses) count 4.5 % of the volume twice, a finger 10 %; see What it caught in README.md",
        },
    ),
]
