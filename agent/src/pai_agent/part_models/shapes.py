"""Small CadQuery helpers and the surface finishes the look-alike parts share.

All sizes are millimetres; z = 0 is the bottom of a part and the part is centred on its footprint.
"""

from __future__ import annotations

import math

import cadquery as cq

from .glb import Finish

FINISH = {
    "aluminium": Finish("#c4c7cc", 0.9, 0.35),
    "anodised_black": Finish("#1d1f22", 0.7, 0.4),
    "steel": Finish("#b9bcc0", 1.0, 0.28),
    "dark_steel": Finish("#55585d", 1.0, 0.35),
    "brass": Finish("#c9a45c", 1.0, 0.3),
    "gold": Finish("#d8b04a", 1.0, 0.25),
    "copper": Finish("#b8693a", 0.9, 0.35),
    "tin": Finish("#d9dadb", 1.0, 0.3),
    "chip": Finish("#1a1a1c", 0.0, 0.45),
    "black_plastic": Finish("#202124", 0.0, 0.55),
    "white_plastic": Finish("#ecebe6", 0.0, 0.5),
    "beige_plastic": Finish("#e5dcc3", 0.0, 0.55),
    "carbon": Finish("#26282b", 0.2, 0.3),
    "rubber": Finish("#1b1b1b", 0.0, 0.9),
    "glass": Finish("#9fb3c8", 0.2, 0.05, 0.45),
    "lens": Finish("#1c2633", 0.6, 0.08),
    "wire_red": Finish("#c8241f", 0.0, 0.5),
    "wire_black": Finish("#1e1e1e", 0.0, 0.5),
    "wire_yellow": Finish("#e1b923", 0.0, 0.5),
    "wire_brown": Finish("#6b3e23", 0.0, 0.5),
    "wire_orange": Finish("#e57a1f", 0.0, 0.5),
    "wire_blue": Finish("#2a5bd7", 0.0, 0.5),
    "wire_green": Finish("#2f9e44", 0.0, 0.5),
    "wire_white": Finish("#e9e9e9", 0.0, 0.5),
    "pcb_green": Finish("#1f6f3d", 0.0, 0.45),
    "pcb_blue": Finish("#1d4fa3", 0.0, 0.45),
    "pcb_black": Finish("#18191b", 0.0, 0.45),
    "pcb_red": Finish("#b3262b", 0.0, 0.45),
    "pcb_purple": Finish("#4a2a7a", 0.0, 0.45),
    "pcb_white": Finish("#e8e8e4", 0.0, 0.45),
    "ceramic": Finish("#d8cfb8", 0.0, 0.5),
    "led_white": Finish("#f4f4ee", 0.0, 0.25),
    "led_yellow": Finish("#f5d64a", 0.0, 0.3),
    "fresnel": Finish("#f2f2ee", 0.0, 0.35, 0.9),
}


def finish(name_or_hex: str, metallic: float = 0.0, roughness: float = 0.5) -> Finish:
    """A named finish, or a plain colour given as #rrggbb."""

    if name_or_hex in FINISH:
        return FINISH[name_or_hex]
    return Finish(name_or_hex, metallic, roughness)


def box(x: float, y: float, z: float, at=(0.0, 0.0, 0.0), fillet: float = 0.0) -> cq.Workplane:
    """A box x by y by z with its bottom centre at `at`, edges optionally rounded."""

    shape = cq.Workplane("XY").box(x, y, z, centered=(True, True, False))
    if fillet > 0:
        try:
            shape = shape.edges().fillet(min(fillet, min(x, y, z) * 0.45))
        except Exception:
            pass
    return shape.translate(at)


def rounded_plate(x: float, y: float, t: float, r: float, at=(0.0, 0.0, 0.0)) -> cq.Workplane:
    """A flat plate with rounded corners in the XY plane, bottom at at[2]."""

    shape = cq.Workplane("XY").rect(x, y)
    if r > 0:
        shape = cq.Workplane("XY").sketch().rect(x, y).vertices().fillet(min(r, x / 2 - 0.01, y / 2 - 0.01)).finalize()
    return shape.extrude(t).translate(at)


def cyl(r: float, h: float, at=(0.0, 0.0, 0.0), axis: str = "Z") -> cq.Workplane:
    """A cylinder of radius r and length h starting at `at` along +axis."""

    plane = {"Z": "XY", "X": "YZ", "Y": "XZ"}[axis]
    shape = cq.Workplane(plane).circle(r).extrude(h if axis != "Y" else -h)
    return shape.translate(at)


def tube(r_out: float, r_in: float, h: float, at=(0.0, 0.0, 0.0), axis: str = "Z") -> cq.Workplane:
    plane = {"Z": "XY", "X": "YZ", "Y": "XZ"}[axis]
    shape = cq.Workplane(plane).circle(r_out).circle(r_in).extrude(h if axis != "Y" else -h)
    return shape.translate(at)


def polar(n: int, radius: float, start_deg: float = 0.0) -> list[tuple[float, float]]:
    """n points evenly spaced on a circle."""

    return [
        (radius * math.cos(math.radians(start_deg + 360.0 * i / n)), radius * math.sin(math.radians(start_deg + 360.0 * i / n)))
        for i in range(n)
    ]


def wire_path(points: list[tuple[float, float, float]], r: float) -> cq.Workplane:
    """A round wire along a polyline, as joined cylinders with ball joints (robust, no sweeps)."""

    solids = None
    for (x0, y0, z0), (x1, y1, z1) in zip(points, points[1:]):
        dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 1e-6:
            continue
        segment = cq.Solid.makeCylinder(r, length, cq.Vector(x0, y0, z0), cq.Vector(dx, dy, dz))
        solids = segment if solids is None else solids.fuse(segment)
    for x, y, z in points[1:-1]:
        solids = solids.fuse(cq.Solid.makeSphere(r, cq.Vector(x, y, z), angleDegrees1=-90, angleDegrees2=90))
    return cq.Workplane("XY").add(solids)


def shape_of(work) -> cq.Shape:
    """The CadQuery shape inside a Workplane (or the shape itself)."""

    if isinstance(work, cq.Shape):
        return work
    values = [v for v in work.vals() if isinstance(v, cq.Shape)]
    if len(values) == 1:
        return values[0]
    return cq.Compound.makeCompound(values)


def union(*works) -> cq.Workplane:
    result = None
    for work in works:
        if work is None:
            continue
        result = work if result is None else result.union(work)
    return result
