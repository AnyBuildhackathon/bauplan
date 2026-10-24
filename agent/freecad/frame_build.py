"""The AnyBuild reference drone, a 1S 2-inch toothpick micro quad, built parametrically in FreeCAD.

It is the build from Mediocre Nerd's "Build a Micro FPV Drone for $59" video: a Twiglet 2"
carbon frame, 1103 motors, Gemfan 2020 four-blade props, a Caddx Ant camera in a canopy, the
BetaFPV Matrix 1S AIO, a 1S pack in a battery holder under the frame, M1.4 motor bolts.

Runs inside FreeCAD, never in the agent interpreter: headless as `freecadcmd frame_build.py`
(PAI_FREECAD_PARAMS and PAI_FREECAD_OUT set), or stage by stage in the open FreeCAD window,
where freecad_run.build_in_gui loads this file with runpy and calls `run_stage`.

The carbon X-frame is a unibody plate (arm_length_mm, thickness_mm, motor_spacing_mm) with
rounded arms, motor pads and lightening slots; only it is weighed, at carbon-plate density.
Around it sit the bought parts at catalog size: motors with stator, windings, magnets and
screws, four-blade props, the AIO on standoffs with its wiring, the canopy with the camera
and the antenna tube, the battery holder, the strapped pack and the antennas.

Outputs: frame.FCStd (the whole assembly), frame.step and frame.stl (the X-frame),
drone.step (the assembly) and frame.glb, the assembly with one node per scene target from
docs/events.md (plus canopy, camera, battery_strap and antenna), PBR materials and the
battery size in the battery node's extras.
FreeCAD is Z-up in mm with the nose at +Y; the GLB is Y-up in metres with the nose at -Z.
"""

import json
import math
import os
import struct
import sys

DENSITY = 1.55 / 1000.0  # carbon fibre plate, g per mm3

CORNERS = (
    # name, angle of the arm, prop spin seen from above (+1 counter-clockwise)
    ("front_left", 135.0, -1),
    ("front_right", 45.0, 1),
    ("rear_left", 225.0, 1),
    ("rear_right", 315.0, -1),
)

# glTF look, CAD-tab colour, base colour, metallic, roughness, alpha, clearcoat
MATERIALS = {
    "carbon": ("#c9ccd3", "#0d0e10", 0.0, 0.4, 1.0, 0.6),
    "anodized": ("#ff9a5a", "#ff6a1c", 1.0, 0.3, 1.0, 0.0),
    "bell": ("#7d838e", "#1b1c20", 0.85, 0.34, 1.0, 0.0),
    "copper": ("#c98a5a", "#c27a46", 1.0, 0.32, 1.0, 0.0),
    "steel": ("#aeb4bd", "#a3a9b1", 1.0, 0.24, 1.0, 0.0),
    "magnet": ("#5c616b", "#45484f", 0.7, 0.42, 1.0, 0.0),
    "screw": ("#4a4e56", "#1d1e22", 0.9, 0.34, 1.0, 0.0),
    "prop": ("#c9d6df", "#b8c7d2", 0.0, 0.12, 0.42, 0.0),
    "pcb": ("#4b5563", "#111318", 0.0, 0.5, 1.0, 0.2),
    "chip": ("#2f343c", "#0b0c0e", 0.0, 0.32, 1.0, 0.0),
    "gold": ("#d9b25c", "#d9ac52", 1.0, 0.22, 1.0, 0.0),
    "plastic": ("#e7e5df", "#ecebe5", 0.0, 0.55, 1.0, 0.0),
    "battery": ("#6b7280", "#202227", 0.0, 0.34, 1.0, 0.5),
    "strap": ("#3f434a", "#141518", 0.0, 0.85, 1.0, 0.0),
    "wire_red": ("#d65a5a", "#c62828", 0.0, 0.45, 1.0, 0.0),
    "wire_black": ("#3f434a", "#18191c", 0.0, 0.45, 1.0, 0.0),
    "wire_yellow": ("#f2c94c", "#e8a317", 0.0, 0.45, 1.0, 0.0),
    "sleeve": ("#3f434a", "#121316", 0.0, 0.55, 1.0, 0.0),
    "tpu": ("#9aa0aa", "#141518", 0.0, 0.72, 1.0, 0.0),
    "glass": ("#3b4a63", "#0c1424", 0.3, 0.05, 1.0, 1.0),
}

DEFAULTS = {
    "arm_length_mm": 42.5,
    "thickness_mm": 2.0,
    "motor_spacing_mm": 6.6,
    "prop_mm": 51.0,
    "prop_pitch_in": 2.0,
    "motor_height_mm": 13.5,
    "motor_size": "1103",
    "motor_diameter_mm": 14.0,
    "shaft_mm": 1.5,
    "motor_kv": 15000,
    "battery_mm": [59.0, 18.0, 8.0],
    "battery_label": "#e8c21a",
    "camera_mm": 14.0,
    "prop_blades": 4,
}

BAY = 14.5  # half width of the plate ring around the flight controller
BAY_HOLE = 9.0  # the lightening window under the flight controller
ARM_ROOT = 4.8  # half width of an arm at the body
ARM_TIP = 3.4  # half width of an arm at the motor pad
FC_HOLE = 13.0  # standoffs at +-13 mm, the 26 mm AIO mount
STANDOFF_H = 3.5
PCB_T = 1.2
CANOPY_WALL = 1.3
LIP_H = 2.6  # the battery holder's side lips
HOLDER_W = 19.0  # widest 1S pack the holder takes
CAMERA_TILT = 22.0  # degrees up from level


def resolve(params: dict) -> dict:
    p = dict(DEFAULTS)
    p.update({k: v for k, v in params.items() if v is not None})
    p["arm_length_mm"] = float(p["arm_length_mm"])
    p["thickness_mm"] = float(p["thickness_mm"])
    p["motor_spacing_mm"] = float(p["motor_spacing_mm"])
    p["prop_mm"] = float(p["prop_mm"])
    p["battery_mm"] = [float(v) for v in p["battery_mm"]]
    p["prop_blades"] = int(p["prop_blades"])
    size = str(p.get("motor_size") or "1103")
    p["stator_h_mm"] = float(size[2:4]) if len(size) == 4 and size.isdigit() else 3.0
    p["motor_body_mm"] = float(p["motor_height_mm"]) - 3.3  # the shaft stands about 3.3 mm proud
    t = p["thickness_mm"]
    p["prop_z"] = t + p["motor_body_mm"] + 2.3  # blade plane: hub on the bell cap
    p["canopy_z"] = t + STANDOFF_H + PCB_T + 1.3  # on the standoff nuts
    p["battery_top"] = -1.0  # under the motor screw heads
    return p


# --- small geometry helpers ------------------------------------------------------------


def _v(x, y, z=0.0):
    import FreeCAD as App

    return App.Vector(x, y, z)


def _face(points):
    import Part

    pts = [_v(*p) for p in points]
    return Part.Face(Part.makePolygon(pts + [pts[0]]))


def _disk(x, y, r):
    import Part

    return Part.Face(Part.Wire(Part.makeCircle(r, _v(x, y, 0))))


def _rounded_rect(cx, cy, w, h, r):
    """A rounded rectangle face in the XY plane."""

    import Part

    inner = _face([(cx - w / 2 + r, cy - h / 2 + r), (cx + w / 2 - r, cy - h / 2 + r), (cx + w / 2 - r, cy + h / 2 - r), (cx - w / 2 + r, cy + h / 2 - r)])
    return Part.Face(inner.makeOffset2D(r, 0).Wires[0])


def _stadium(p0, p1, width):
    """A slot from p0 to p1 with round ends, in the XY plane."""

    import Part

    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    half = width / 2.0
    body = _face(
        [
            (p0[0] + nx * half, p0[1] + ny * half),
            (p1[0] + nx * half, p1[1] + ny * half),
            (p1[0] - nx * half, p1[1] - ny * half),
            (p0[0] - nx * half, p0[1] - ny * half),
        ]
    )
    return _union_faces([body, _disk(p0[0], p0[1], half), _disk(p1[0], p1[1], half)])


def _union_faces(faces):
    """Union of planar XY faces as one face: fused as thin prisms, then the floor is read back."""

    solid = _fused([face.extrude(_v(0, 0, 1)) for face in faces])
    floor = [f for f in solid.Faces if f.BoundBox.ZMax < 1e-6]
    return floor[0]


def _round(face, concave, convex):
    """Fillets in plan view: closing rounds the inside corners, opening the outside ones."""

    shape = face
    if concave:
        shape = shape.makeOffset2D(concave, 0).makeOffset2D(-concave, 0)
    if convex:
        shape = shape.makeOffset2D(-convex, 0).makeOffset2D(convex, 0)
    return shape


def _cyl(r, h, x=0.0, y=0.0, z=0.0, d=(0, 0, 1)):
    import Part

    return Part.makeCylinder(r, h, _v(x, y, z), _v(*d))


def _ring(r_out, r_in, h, x=0.0, y=0.0, z=0.0):
    return _cyl(r_out, h, x, y, z).cut(_cyl(r_in, h + 0.2, x, y, z - 0.1))


def _rod(a, b, r):
    """A cylinder between two points."""

    import Part

    va, vb = _v(*a), _v(*b)
    return Part.makeCylinder(r, (vb - va).Length, va, vb - va)


def _fused(shapes):
    shape = shapes[0]
    if len(shapes) > 1:
        shape = shape.fuse(shapes[1:])
    return shape.removeSplitter()


def _try_fillet(shape, radius, edges):
    try:
        out = shape.makeFillet(radius, edges)
        if out.isValid() and out.Volume > 0:
            return out
    except Exception:
        pass
    return shape


def _motor_centers(p):
    arm = p["arm_length_mm"]
    out = []
    for name, angle, spin in CORNERS:
        a = math.radians(angle)
        out.append((name, angle, spin, arm * math.cos(a), arm * math.sin(a)))
    return out


# --- the carbon frame --------------------------------------------------------------------


def frame_plate(p):
    """The 2D unibody plate, extruded to thickness_mm, with its cutouts."""

    t = p["thickness_mm"]
    bolt = p["motor_spacing_mm"] / 2.0
    # An open bay: a rounded square ring with bosses for the standoffs.
    faces = [_rounded_rect(0, 0, 2 * BAY, 2 * BAY, 2.5)]
    for sx in (-1, 1):
        for sy in (-1, 1):
            faces.append(_disk(sx * FC_HOLE, sy * FC_HOLE, 3.0))
    for _name, angle, _spin, cx, cy in _motor_centers(p):
        a = math.radians(angle)
        ux, uy = math.cos(a), math.sin(a)
        nx, ny = -uy, ux
        start = 15.0
        faces.append(
            _face(
                [
                    (start * ux + ARM_ROOT * nx, start * uy + ARM_ROOT * ny),
                    (cx + ARM_TIP * nx, cy + ARM_TIP * ny),
                    (cx - ARM_TIP * nx, cy - ARM_TIP * ny),
                    (start * ux - ARM_ROOT * nx, start * uy - ARM_ROOT * ny),
                ]
            )
        )
        faces.append(_disk(cx, cy, 6.2))
    outline = _union_faces(faces)
    outline = _round(outline, 2.4, 0.6)

    holes = [_rounded_rect(0, 0, BAY_HOLE, BAY_HOLE, 3.0)]
    for _name, angle, _spin, cx, cy in _motor_centers(p):
        a = math.radians(angle)
        ux, uy = math.cos(a), math.sin(a)
        holes.append(_stadium((19.5 * ux, 19.5 * uy), ((p["arm_length_mm"] - 8.6) * ux, (p["arm_length_mm"] - 8.6) * uy), 1.8))
        holes.append(_disk(cx, cy, 1.6))
        for k in range(3):
            b = a + math.radians(30 + k * 120)
            holes.append(_disk(cx + bolt * math.cos(b), cy + bolt * math.sin(b), 0.8))
    for sx in (-1, 1):
        for sy in (-1, 1):
            holes.append(_disk(sx * FC_HOLE, sy * FC_HOLE, 1.05))
    solid = outline.extrude(_v(0, 0, t))
    cutter = _fused([h.extrude(_v(0, 0, t + 2)).translate(_v(0, 0, -1)) for h in holes])
    plate = solid.cut(cutter)
    top = [e for e in plate.Edges if abs(e.BoundBox.ZMin - t) < 1e-6 and abs(e.BoundBox.ZMax - t) < 1e-6]
    return _try_fillet(plate, 0.45, top)


def canopy(p):
    """The TPU hood over the flight controller: a lofted shell on the standoff nuts, open at
    the sides so the board and its wiring show, a window for the camera and a tube for the antenna."""

    import Part

    z0 = p["canopy_z"]
    top = z0 + 7.4
    outer = Part.makeLoft([_rounded_rect(0, 0.5, 29.6, 31.0, 6.0).Wires[0].translated(_v(0, 0, z0)), _rounded_rect(0, 2.0, 15.0, 19.0, 5.0).Wires[0].translated(_v(0, 0, top))], True, False)
    w = CANOPY_WALL
    inner = Part.makeLoft(
        [
            _rounded_rect(0, 0.5, 29.6 - 2 * w, 31.0 - 2 * w, 5.0).Wires[0].translated(_v(0, 0, z0 - 0.1)),
            _rounded_rect(0, 2.0, 15.0 - 2 * w, 19.0 - 2 * w, 4.0).Wires[0].translated(_v(0, 0, top - w)),
        ],
        True,
        False,
    )
    shell = outer.cut(inner)
    edges = [e for e in shell.Edges if abs(e.BoundBox.ZMin - top) < 1e-6 and abs(e.BoundBox.ZMax - top) < 1e-6 and e.BoundBox.XLength > 12]
    shell = _try_fillet(shell, 1.6, edges)
    # Side windows between the corner feet, so the board and its wiring show.
    window = Part.makeBox(40.0, 18.0, 6.0, _v(-20.0, -8.0, z0 - 1.4))
    window = _try_fillet(window, 2.2, [e for e in window.Edges if e.BoundBox.XLength > 30])
    shell = shell.cut(window)
    # The camera looks out of the nose.
    lens = _camera_frame(p)
    hole = _rounded_rect(0, 0, 10.0, 10.0, 2.6).extrude(_v(0, 0, 14))
    hole.translate(_v(0, 0, -2))
    hole.rotate(_v(0, 0, 0), _v(1, 0, 0), -90 + CAMERA_TILT)
    hole.translate(lens)
    shell = shell.cut(hole)
    # The antenna tube on the tail.
    base, tip = _antenna_line(p, 0.0), _antenna_line(p, 5.5)
    tube = _rod(_antenna_line(p, -2.5), tip, 1.4).cut(_rod(_antenna_line(p, -3.0), _antenna_line(p, 6.0), 0.75))
    return _fused([shell, tube])


def _camera_frame(p):
    """Where the camera's front face sits: on the nose, under the canopy roof."""

    return _v(0, 13.6, p["canopy_z"] + 4.0)


def _antenna_line(p, length):
    """A point on the antenna axis: out of the canopy tail, raked back and up."""

    rake = math.radians(38)
    base = (0.0, -13.8, p["canopy_z"] + 5.0)
    return (base[0], base[1] - length * math.cos(rake), base[2] + length * math.sin(rake))


# --- bought parts -------------------------------------------------------------------------


def motor(p, cx, cy):
    """An outrunner on its pad, sized from its code (1103: 11 mm stator, 3 mm tall): base spider,
    wound stator, magnet ring, black bell with spoked cap, shaft, screws and leads."""

    import Part

    t = p["thickness_mm"]
    bolt = p["motor_spacing_mm"] / 2.0
    r = p["motor_diameter_mm"] / 2.0
    k = r / 7.0  # the radial layout was drawn for a 14 mm bell
    stator_h = p["stator_h_mm"]
    cap_z1 = t + p["motor_body_mm"]
    bell_z1 = cap_z1 - 1.9
    parts = []
    base = _cyl(6.3 * k, 1.0, cx, cy, t)
    for n in range(3):
        window = Part.makeCylinder(5.2 * k, 1.4, _v(cx, cy, t - 0.2), _v(0, 0, 1), 74).cut(_cyl(2.7 * k, 1.6, cx, cy, t - 0.3))
        window.rotate(_v(cx, cy, 0), _v(0, 0, 1), n * 120 + 23)
        base = base.cut(window)
    base = base.fuse(_cyl(2.4 * k, 2.6, cx, cy, t))
    parts.append(("steel", base))

    z0 = t + 1.6
    stator = _ring(3.4 * k, 1.6 * k, stator_h, cx, cy, z0)
    coils = []
    teeth = []
    for n in range(12):
        b = n * 30.0
        tooth = Part.makeBox(2.4 * k, 1.0 * k, stator_h, _v(3.2 * k, -0.5 * k, z0))
        cap = Part.makeBox(0.5 * k, 2.4 * k, stator_h, _v(5.1 * k, -1.2 * k, z0))
        coil = Part.makeBox(1.5 * k, 1.9 * k, stator_h + 0.9, _v(3.5 * k, -0.95 * k, z0 - 0.45))
        coil = _try_fillet(coil, 0.42 * k, coil.Edges)
        for shape in (tooth, cap, coil):
            shape.rotate(_v(0, 0, 0), _v(0, 0, 1), b)
            shape.translate(_v(cx, cy, 0))
        teeth += [tooth, cap]
        coils.append(coil)
    parts.append(("steel", _fused([stator] + teeth)))
    parts.append(("copper", _fused(coils)))

    bell_z0 = t + 1.1
    bell = _ring(r, r - 0.65, bell_z1 - bell_z0, cx, cy, bell_z0)
    bell = _try_fillet(bell, 0.25, [e for e in bell.Edges if abs(e.BoundBox.ZMin - bell_z0) < 1e-6 and abs(e.BoundBox.ZMax - bell_z0) < 1e-6])
    parts.append(("bell", bell))
    parts.append(("magnet", _ring(r - 0.65, r - 1.25, bell_z1 - t - 3.0, cx, cy, t + 1.8)))
    cap = _cyl(r, cap_z1 - bell_z1, cx, cy, bell_z1)
    for n in range(5):
        window = Part.makeCylinder(r - 1.4, 3.0, _v(cx, cy, bell_z1 - 1), _v(0, 0, 1), 44)
        window = window.cut(_cyl(2.4 * k, 3.2, cx, cy, bell_z1 - 1.1))
        window.rotate(_v(cx, cy, 0), _v(0, 0, 1), n * 72 + 14)
        cap = cap.cut(window)
    cap = cap.fuse(_cyl(2.2 * k, cap_z1 - bell_z1 + 0.5, cx, cy, bell_z1))
    top_edges = [e for e in cap.Edges if abs(e.BoundBox.ZMin - cap_z1) < 1e-6 and e.BoundBox.XLength > 2 * r - 1]
    cap = _try_fillet(cap, 0.9, top_edges)
    parts.append(("bell", cap))
    parts.append(("steel", _cyl(p["shaft_mm"] / 2.0, p["motor_height_mm"] - 0.6, cx, cy, t + 0.6)))

    screws = []
    for k in range(3):
        b = math.radians(_corner_angle(cx, cy) + 30 + k * 120)
        sx, sy = cx + bolt * math.cos(b), cy + bolt * math.sin(b)
        head = _cyl(1.15, 0.7, sx, sy, -0.7)
        head = head.cut(Part.makeBox(1.4, 0.35, 0.6, _v(sx - 0.7, sy - 0.175, -0.85)))
        screws.append(head)
    parts.append(("screw", _fused(screws)))

    # Three motor leads along the arm into the bay.
    a = math.radians(_corner_angle(cx, cy))
    ux, uy = math.cos(a), math.sin(a)
    nx, ny = -uy, ux
    wires = {"wire_black": [], "wire_red": [], "wire_yellow": []}
    board = t + STANDOFF_H + PCB_T + 0.2
    for key, off in zip(wires, (-0.75, 0.0, 0.75)):
        start = (cx - 4.6 * ux + off * nx, cy - 4.6 * uy + off * ny, t + 0.36)
        bend = (16.0 * ux + off * nx, 16.0 * uy + off * ny, t + 0.36)
        end = (10.0 * ux + off * nx, 10.0 * uy + off * ny, board)
        wires[key] += [_rod(start, bend, 0.34), _rod(bend, end, 0.34), Part.makeSphere(0.34, _v(*bend))]
    for key, rods in wires.items():
        parts.append((key, _fused(rods)))
    return parts


def _corner_angle(cx, cy):
    return math.degrees(math.atan2(cy, cx))


def propeller(p, cx, cy, spin, phase):
    """Twisted, swept blades lofted through elliptic sections, on a domed hub."""

    import Part

    radius = p["prop_mm"] / 2.0
    pitch = float(p["prop_pitch_in"]) * 25.4
    z = p["prop_z"]
    # (radius share, chord mm, thickness mm); a loft through these stays valid for 30-60 mm props.
    count = p["prop_blades"]
    wide = 3.0 / count  # four blades share the disc, each a little narrower
    stations = tuple((s, c * (0.55 + 0.45 * wide), th) for s, c, th in ((0.1, 3.2, 0.9), (0.25, 5.2, 0.8), (0.45, 8.2, 0.7), (0.65, 8.6, 0.6), (0.825, 7.4, 0.5), (0.97, 4.2, 0.42)))
    blades = []
    for k in range(count):
        wires = []
        for share, chord, thick in stations:
            r = share * radius
            # Real whoop props stay fairly flat; clamp the geometric pitch angle.
            phi = max(min(math.atan(pitch / (2 * math.pi * max(r, 4.0))), math.radians(26)), math.radians(12))
            # Twisted elliptic sections: the chord leans into the spin by phi, swept back to the tip.
            lead = _v(0, spin * math.cos(phi), math.sin(phi))
            up = _v(0, -spin * math.sin(phi), math.cos(phi))
            sweep = 0.35 * (r / radius) ** 2 * chord
            center = _v(r, 0, 0) - lead * sweep
            ellipse = Part.Ellipse(center + lead * (chord / 2), center + up * (thick / 2), center)
            wires.append(Part.Wire(ellipse.toShape()))
        blade = Part.makeLoft(wires, True, False)
        blade.rotate(_v(0, 0, 0), _v(0, 0, 1), phase + k * 360.0 / count)
        blades.append(blade)
    hub = _cyl(2.7, 3.2, 0, 0, -1.6)
    dome = Part.makeSphere(2.7, _v(0, 0, 1.6), _v(0, 0, 1), 0, 90)
    hub = hub.fuse(dome).cut(_cyl(0.75, 3.0, 0, 0, -2.0))
    # OCCT cannot fuse the lofted blades onto the hub; a compound renders the same.
    prop = Part.makeCompound([hub] + blades)
    prop.translate(_v(cx, cy, z))
    return [("prop", prop)]


def flight_controller(p):
    """The AIO board on four anodized standoffs, with MCU, gyro, FETs, plugs and nuts."""

    import Part

    t = p["thickness_mm"]
    z0 = t + STANDOFF_H
    parts = []
    standoffs, nuts, screws = [], [], []
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * FC_HOLE, sy * FC_HOLE
            hexa = Part.Face(Part.makePolygon([_v(x + 1.7 * math.cos(math.radians(60 * i)), y + 1.7 * math.sin(math.radians(60 * i)), t) for i in range(7)]))
            standoffs.append(hexa.extrude(_v(0, 0, STANDOFF_H)).cut(_cyl(0.8, STANDOFF_H + 1, x, y, t - 0.5)))
            nut = Part.Face(Part.makePolygon([_v(x + 1.5 * math.cos(math.radians(60 * i + 30)), y + 1.5 * math.sin(math.radians(60 * i + 30)), z0 + PCB_T) for i in range(7)]))
            nuts.append(nut.extrude(_v(0, 0, 1.3)).cut(_cyl(0.8, 2, x, y, z0)))
            head = _cyl(1.6, 0.8, x, y, -0.8)
            screws.append(head.cut(Part.makeBox(0.5, 0.5, 0.6, _v(x - 0.25, y - 0.25, -0.9))))
    parts.append(("anodized", _fused(standoffs)))
    parts.append(("anodized", _fused(nuts)))
    parts.append(("screw", _fused(screws)))

    board = _rounded_rect(0, 0, 28.0, 28.0, 3.0)
    for sx in (-1, 1):
        for sy in (-1, 1):
            board = board.cut(_disk(sx * FC_HOLE, sy * FC_HOLE, 0.85))
    parts.append(("pcb", board.extrude(_v(0, 0, PCB_T)).translate(_v(0, 0, z0))))
    top = z0 + PCB_T
    chips = [Part.makeBox(7.0, 7.0, 0.9, _v(-3.5, -3.5, top))]
    chips.append(Part.makeBox(3.0, 3.0, 0.8, _v(5.0, 2.0, top)))
    chips.append(Part.makeBox(4.0, 4.0, 0.8, _v(-9.0, 4.0, top)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            for k in range(2):
                chips.append(Part.makeBox(2.6, 2.0, 0.7, _v(sx * 7.4 - 1.3 + k * 0.0, sy * (5.2 + k * 2.5) - 1.0, top)))
    parts.append(("chip", _fused(chips)))
    pads = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            pads.append(_ring(1.5, 0.85, 0.06, sx * FC_HOLE, sy * FC_HOLE, top))
            for k in range(3):
                off = (k - 1) * 1.25
                a = math.atan2(sy, sx)
                ux, uy = math.cos(a), math.sin(a)
                pads.append(Part.makeBox(0.9, 0.9, 0.08, _v(10.0 * ux - uy * off - 0.45, 10.0 * uy + ux * off - 0.45, top)))
    parts.append(("gold", _fused(pads)))
    plugs = [Part.makeBox(6.0, 3.6, 2.6, _v(-3.0, -14.2, top))]
    plugs.append(Part.makeBox(8.8, 3.2, 3.2, _v(-4.4, 11.2, z0 - 3.2)))
    parts.append(("plastic", plugs[0]))
    parts.append(("steel", plugs[1]))
    # The battery pigtail: from the rear pads, back past the tail and down to the pack's plug.
    length = p["battery_mm"][0]
    plug = _battery_plug(p)
    for key, x in (("wire_red", -0.8), ("wire_black", 0.8)):
        pad = (x, -11.0, top + 0.3)
        back = (x, -length / 2 - 2.0, top - 1.0)
        down = (x, plug[1] + 2.4, plug[2])
        parts.append((key, _fused([_rod(pad, back, 0.5), _rod(back, down, 0.5), Part.makeSphere(0.5, _v(*back))])))
    return parts


def _battery_plug(p):
    length, _width, height = p["battery_mm"]
    return (0.0, -length / 2 - 5.5, p["battery_top"] - height / 2)


def battery_holder(p):
    """The TPU cradle under the frame: a tray between frame and pack, lips along the pack.

    It is sized for the frame, not the pack: the lips take packs up to HOLDER_W wide, the strap
    holds narrower ones.
    """

    import Part

    top = p["battery_top"]
    span = 2 * BAY + 4.0
    tray = _rounded_rect(0, 0, HOLDER_W + 2.4, span, 2.0).extrude(_v(0, 0, -top)).translate(_v(0, 0, top))
    tray = tray.cut(_rounded_rect(0, 0, HOLDER_W - 5.0, span - 12.0, 2.0).extrude(_v(0, 0, 4)).translate(_v(0, 0, top - 1)))
    lips = []
    for sx in (-1, 1):
        x0 = HOLDER_W / 2 + 0.2 if sx > 0 else -HOLDER_W / 2 - 1.2
        lip = Part.makeBox(1.0, span - 8.0, LIP_H, _v(x0, -(span - 8.0) / 2, top - LIP_H + 0.01))
        lips.append(_try_fillet(lip, 0.35, lip.Edges))
    return _fused([tray] + lips)


def battery(p):
    """The pack under the frame: rounded cell, label band, lead and plug. Origin: its top centre."""

    import Part

    length, width, height = p["battery_mm"]
    z0 = p["battery_top"] - height
    pack = Part.makeBox(width, length, height, _v(-width / 2, -length / 2, z0))
    pack = _try_fillet(pack, min(width, height) * 0.22, pack.Edges)
    band_l = length * 0.46
    # The shrink-wrap label stands a little proud of the cell, so it never z-fights in a browser.
    band = Part.makeBox(width + 0.5, band_l, height + 0.5, _v(-width / 2 - 0.25, -band_l / 2 + length * 0.08, z0 - 0.25))
    band = _try_fillet(band, min(width, height) * 0.22, band.Edges)
    plug = _battery_plug(p)
    lead_y = -length / 2
    leads = []
    for key, x in (("wire_red", -0.8), ("wire_black", 0.8)):
        leads.append((key, _rod((x, lead_y + 1.0, plug[2]), (x, plug[1] - 1.6, plug[2]), 0.5)))
    body = Part.makeBox(4.4, 4.0, 3.0, _v(plug[0] - 2.2, plug[1] - 2.0, plug[2] - 1.5))
    body = _try_fillet(body, 0.45, body.Edges)
    return [("battery", pack), ("label", band), ("plastic", body)] + leads


def battery_strap(p):
    """The strap pulled tight around the frame and the pack: the convex hull of both, in section."""

    import Part

    length, width, height = p["battery_mm"]
    t = p["thickness_mm"]
    bottom = p["battery_top"] - height
    hull = [(-BAY - 0.1, t), (BAY + 0.1, t), (BAY + 0.1, 0.0), (width / 2, bottom), (-width / 2, bottom), (-BAY - 0.1, 0.0)]
    face = Part.Face(Part.makePolygon([_v(x, 0, z) for x, z in hull] + [_v(hull[0][0], 0, hull[0][1])]))
    ring = face.makeOffset2D(0.6, 0).cut(face)
    strap = ring.extrude(_v(0, 7.0, 0)).translate(_v(0, -3.5, 0))
    buckle = Part.makeBox(6.0, 8.0, 0.9, _v(-3.0, -4.0, bottom - 1.5))
    buckle = _try_fillet(buckle, 0.4, buckle.Edges)
    return [("strap", strap), ("anodized", buckle)]


def camera(p):
    """A nano FPV camera in the nose, tilted up: body, lens barrel, glass, and its cable."""

    import Part

    face = _camera_frame(p)
    side = float(p["camera_mm"])
    body = Part.makeBox(side, 10.0, side, _v(-side / 2, -10.0, -side / 2))
    body = _try_fillet(body, 1.0, body.Edges)
    barrel = _cyl(4.0, 4.2, 0, 0, 0, (0, 1, 0)).fuse(_cyl(4.6, 1.2, 0, 0, 0, (0, 1, 0)))
    ring = _ring(4.05, 3.1, 0.4, 0, 0, 0)
    ring.rotate(_v(0, 0, 0), _v(1, 0, 0), -90)
    ring.translate(_v(0, 4.0, 0))
    glass = Part.makeSphere(3.1, _v(0, 2.4, 0), _v(0, 1, 0), 60, 90)
    parts = [("chip", body), ("screw", barrel.fuse(ring)), ("glass", glass)]
    out = []
    for material, shape in parts:
        shape.rotate(_v(0, 0, 0), _v(1, 0, 0), CAMERA_TILT)
        shape.translate(face)
        out.append((material, shape))
    cable = _rod((0.0, face.y - 7.5, face.z - 2.0), (0.0, 6.0, p["thickness_mm"] + STANDOFF_H + PCB_T + 0.4), 0.9)
    out.append(("wire_black", cable))
    return out


def antenna(p):
    """The receiver's coax whip in the canopy tube, white dipole sleeve at the end."""

    t = p["thickness_mm"]
    coax = _rod(_antenna_line(p, -2.0), _antenna_line(p, 13.0), 0.55)
    sleeve = _rod(_antenna_line(p, 13.0), _antenna_line(p, 26.0), 0.8)
    start = _antenna_line(p, -2.0)
    feed = _rod((0.0, -9.0, t + STANDOFF_H + PCB_T + 0.4), start, 0.5)
    return [("wire_black", _fused([coax, feed])), ("sleeve", sleeve)]


# --- the assembly as stages ---------------------------------------------------------------

STAGES = ("Frame", "Motors", "Propellers", "Flight controller", "Canopy and camera", "Battery and strap", "Antenna")


def run_stage(doc, params, index):
    """Adds one stage's bodies to doc. Each body records its scene node and material."""

    p = resolve(params)
    label = STAGES[index]
    added = []
    if label == "Frame":
        added.append(("Frame", "frame", "carbon", frame_plate(p)))
        added.append(("Holder", "frame", "tpu", battery_holder(p)))
    elif label == "Canopy and camera":
        added.append(("Canopy", "canopy", "tpu", canopy(p)))
        for k, (material, shape) in enumerate(camera(p)):
            added.append(("Camera_" + str(k), "camera", material, shape))
    elif label == "Motors":
        for name, _angle, _spin, cx, cy in _motor_centers(p):
            for k, (material, shape) in enumerate(motor(p, cx, cy)):
                added.append(("Motor_" + name + "_" + str(k), "motor_" + name, material, shape))
    elif label == "Propellers":
        for i, (name, _angle, spin, cx, cy) in enumerate(_motor_centers(p)):
            for material, shape in propeller(p, cx, cy, spin, 15 + i * 25):
                added.append(("Propeller_" + name, "propeller_" + name, material, shape))
    elif label == "Flight controller":
        for k, (material, shape) in enumerate(flight_controller(p)):
            added.append(("FC_" + str(k), "flight_controller", material, shape))
    elif label == "Battery and strap":
        for k, (material, shape) in enumerate(battery(p)):
            added.append(("Battery_" + str(k), "battery", material, shape))
        for k, (material, shape) in enumerate(battery_strap(p)):
            added.append(("Strap_" + str(k), "battery_strap", material, shape))
    elif label == "Antenna":
        for k, (material, shape) in enumerate(antenna(p)):
            added.append(("Antenna_" + str(k), "antenna", material, shape))
    for name, node, material, shape in added:
        feature = doc.addObject("Part::Feature", name)
        feature.Shape = shape
        feature.Label2 = node + "|" + material
        _paint(feature, p, material)
    doc.recompute()
    return label


def _paint(feature, p, material):
    import FreeCAD as App

    if not App.GuiUp:
        return
    color = _material_color(p, material)[1]
    rgb = tuple(int(color[i : i + 2], 16) / 255.0 for i in (1, 3, 5))
    try:
        feature.ViewObject.ShapeColor = rgb
        if material == "prop":
            feature.ViewObject.Transparency = 55
    except Exception:
        pass  # colour is cosmetic; never fail a build over it


def _material_color(p, material):
    if material == "label":
        label = p["battery_label"]
        return (label, label, 0.0, 0.42, 1.0, 0.0)
    return MATERIALS[material]


def export(doc, params, out_dir):
    """Writes the FCStd, STEP and STL of the frame, the assembly STEP and the GLB; returns the frame mass."""

    import MeshPart
    import Part

    p = resolve(params)
    os.makedirs(out_dir, exist_ok=True)
    frame = doc.getObject("Frame")
    doc.saveAs(os.path.join(out_dir, "frame.FCStd"))
    Part.export([frame], os.path.join(out_dir, "frame.step"))
    MeshPart.meshFromShape(Shape=frame.Shape, LinearDeflection=0.03, AngularDeflection=0.3, Relative=False).write(os.path.join(out_dir, "frame.stl"))
    bodies = [o for o in doc.Objects if o.TypeId == "Part::Feature" and "|" in (o.Label2 or "")]
    Part.export(bodies, os.path.join(out_dir, "drone.step"))
    write_glb(p, [(o.Label2.split("|")[0], o.Label2.split("|")[1], o.Shape) for o in bodies], os.path.join(out_dir, "frame.glb"))
    return float(frame.Shape.Volume) * DENSITY


# --- GLB writer -----------------------------------------------------------------------------


def _node_origins(p):
    """Each node's origin in FreeCAD mm, so motors and props can spin about their shafts."""

    origins = {"frame": (0.0, 0.0, 0.0), "flight_controller": (0.0, 0.0, p["thickness_mm"] + STANDOFF_H), "battery_strap": (0.0, 0.0, 0.0)}
    origins["battery"] = (0.0, 0.0, p["battery_top"])
    origins["canopy"] = (0.0, 0.0, p["canopy_z"])
    origins["camera"] = tuple(_camera_frame(p))
    origins["antenna"] = _antenna_line(p, 0.0)
    for name, _angle, _spin, cx, cy in _motor_centers(p):
        origins["motor_" + name] = (cx, cy, p["thickness_mm"])
        origins["propeller_" + name] = (cx, cy, p["prop_z"])
    return origins


def _parent(node):
    if node.startswith("propeller_"):
        return "motor_" + node[len("propeller_") :]
    return None


def _to_gltf(x, y, z):
    return (x / 1000.0, z / 1000.0, -y / 1000.0)


def _tessellate(shape, origin, tolerance):
    """Per-face meshes, so curved faces shade smooth and edges stay crisp.

    Vertex normals average the face's own triangles; one probe of the true surface normal
    per face fixes the winding.
    """

    import MeshPart

    positions, normals, indices = [], [], []
    ox, oy, oz = origin
    for face in shape.Faces:
        curved = face.Surface.__class__.__name__ not in ("Plane", "Cylinder")
        try:
            mesh = MeshPart.meshFromShape(
                Shape=face,
                LinearDeflection=tolerance * (1.5 if curved else 1.0),
                AngularDeflection=0.45 if curved else 0.4,
                Relative=False,
            )
            points, triangles = mesh.Topology
        except Exception:
            continue
        if not triangles:
            continue
        sums = [[0.0, 0.0, 0.0] for _ in points]
        total = [0.0, 0.0, 0.0]
        for a, b, c in triangles:
            n = (points[b] - points[a]).cross(points[c] - points[a])
            for i in (a, b, c):
                sums[i][0] += n.x
                sums[i][1] += n.y
                sums[i][2] += n.z
            total[0] += n.x
            total[1] += n.y
            total[2] += n.z
        flip = False
        try:
            u0, u1, v0, v1 = face.ParameterRange
            probe = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
            flip = probe.x * total[0] + probe.y * total[1] + probe.z * total[2] < 0
        except Exception:
            pass
        sign = -1.0 if flip else 1.0
        base = len(positions) // 3
        for point, (nx, ny, nz) in zip(points, sums):
            positions.extend(_to_gltf(point.x - ox, point.y - oy, point.z - oz))
            length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            normals.extend((sign * nx / length, sign * nz / length, -sign * ny / length))
        for a, b, c in triangles:
            indices.extend((base + a, base + c, base + b) if flip else (base + a, base + b, base + c))
    return positions, normals, indices


def write_glb(p, bodies, path, tolerance=0.06):
    origins = _node_origins(p)
    order = ["frame", "canopy", "camera", "flight_controller", "battery", "battery_strap", "antenna"]
    for name, _angle, _spin, _cx, _cy in _motor_centers(p):
        order += ["motor_" + name, "propeller_" + name]
    groups = {}
    for node, material, shape in bodies:
        groups.setdefault(node, {}).setdefault(material, []).append(shape)

    materials, material_index = [], {}
    clearcoat = False
    for node in order:
        for material in groups.get(node, {}):
            if material in material_index:
                continue
            cad, base, metal, rough, alpha, coat = _material_color(p, material)
            rgb = [_linear(int(base[i : i + 2], 16) / 255.0) for i in (1, 3, 5)]
            entry = {
                "name": "pai:" + cad + " " + material,
                "pbrMetallicRoughness": {"baseColorFactor": rgb + [alpha], "metallicFactor": metal, "roughnessFactor": rough},
            }
            if alpha < 1.0:
                entry["alphaMode"] = "BLEND"
            if coat:
                entry["extensions"] = {"KHR_materials_clearcoat": {"clearcoatFactor": coat, "clearcoatRoughnessFactor": 0.12}}
                clearcoat = True
            material_index[material] = len(materials)
            materials.append(entry)

    blob = bytearray()
    views, accessors, meshes, nodes = [], [], [], []

    def add_view(data, target):
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target})
        blob.extend(data)
        return len(views) - 1

    node_index = {}
    for node in order:
        if node not in groups:
            continue
        origin = origins[node]
        primitives = []
        for material, shapes in groups[node].items():
            shape = shapes[0] if len(shapes) == 1 else _compound(shapes)
            positions, normals, indices = _tessellate(shape, origin, tolerance)
            if not indices:
                continue
            count = len(positions) // 3
            xs, ys, zs = positions[0::3], positions[1::3], positions[2::3]
            pos_view = add_view(struct.pack("<%df" % len(positions), *positions), 34962)
            accessors.append({"bufferView": pos_view, "componentType": 5126, "count": count, "type": "VEC3", "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]})
            pos_acc = len(accessors) - 1
            nrm_view = add_view(struct.pack("<%df" % len(normals), *normals), 34962)
            accessors.append({"bufferView": nrm_view, "componentType": 5126, "count": count, "type": "VEC3"})
            nrm_acc = len(accessors) - 1
            wide = count > 65535
            idx_view = add_view(struct.pack(("<%dI" if wide else "<%dH") % len(indices), *indices), 34963)
            accessors.append({"bufferView": idx_view, "componentType": 5125 if wide else 5123, "count": len(indices), "type": "SCALAR"})
            primitives.append({"attributes": {"POSITION": pos_acc, "NORMAL": nrm_acc}, "indices": len(accessors) - 1, "material": material_index[material]})
        if not primitives:
            continue
        meshes.append({"name": node, "primitives": primitives})
        parent = _parent(node)
        px, py, pz = origins[parent] if parent else (0.0, 0.0, 0.0)
        entry = {"name": node, "mesh": len(meshes) - 1, "translation": list(_to_gltf(origin[0] - px, origin[1] - py, origin[2] - pz))}
        if node == "battery":
            entry["extras"] = {"size_mm": p["battery_mm"]}
        nodes.append(entry)
        node_index[node] = len(nodes) - 1
    for node, index in node_index.items():
        parent = _parent(node)
        if parent in node_index:
            nodes[node_index[parent]].setdefault("children", []).append(index)
    children = set(i for n in nodes for i in n.get("children", []))
    nodes.append(
        {
            "name": "drone",
            "children": [i for i in range(len(nodes)) if i not in children],
            "extras": {"arm_length_mm": p["arm_length_mm"], "prop_mm": p["prop_mm"], "battery_mm": p["battery_mm"], "motor_kv": p["motor_kv"]},
        }
    )
    gltf = {
        "asset": {"version": "2.0", "generator": "AnyBuild hero drone (FreeCAD)"},
        "scene": 0,
        "scenes": [{"nodes": [len(nodes) - 1]}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    if clearcoat:
        gltf["extensionsUsed"] = ["KHR_materials_clearcoat"]
    payload = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(payload) % 4:
        payload += b" "
    while len(blob) % 4:
        blob.append(0)
    total = 12 + 8 + len(payload) + 8 + len(blob)
    with open(path, "wb") as handle:
        handle.write(struct.pack("<III", 0x46546C67, 2, total))
        handle.write(struct.pack("<II", len(payload), 0x4E4F534A))
        handle.write(payload)
        handle.write(struct.pack("<II", len(blob), 0x004E4942))
        handle.write(bytes(blob))


def _compound(shapes):
    import Part

    return Part.makeCompound(shapes)


def _linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# --- headless entry -----------------------------------------------------------------------


def main() -> None:
    import FreeCAD as App

    params_path = os.environ.get("PAI_FREECAD_PARAMS") or sys.argv[-2]
    out_dir = os.environ.get("PAI_FREECAD_OUT") or sys.argv[-1]
    params = json.loads(open(params_path, encoding="utf-8").read())
    os.makedirs(out_dir, exist_ok=True)
    try:
        doc = App.newDocument("AnyBuild")
        for index in range(len(STAGES)):
            run_stage(doc, params, index)
        mass_g = export(doc, params, out_dir)
    except Exception as exc:
        _write(out_dir, {"ok": False, "error": str(exc)})
        raise
    _write(out_dir, {"ok": True, "mass_g": round(mass_g, 2)})


def _write(out_dir: str, payload: dict) -> None:
    with open(os.path.join(out_dir, "freecad_result.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


if os.environ.get("PAI_FREECAD_OUT"):
    main()
