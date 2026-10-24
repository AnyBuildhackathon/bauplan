# Parametric two-finger robot gripper. One servo turns the left gear; the right gear
# meshes with it, so both fingers close symmetrically on the object.
# Units are mm, Z is up, the fingers point along +Y.
import math

import FreeCAD
import Part

V = FreeCAD.Vector

L = P.get("finger_length_mm", 70.0)
OPEN = P.get("jaw_opening_mm", 76.0)
T = P.get("finger_thickness_mm", 6.0)
PAD = P.get("pad_thickness_mm", 3.0)
SL = P.get("servo_length_mm", 40.7)
SW = P.get("servo_width_mm", 19.7)
SH = P.get("servo_height_mm", 42.9)
SHAFT = P.get("servo_shaft_offset_mm", 10.0)

MODULE = 1.5
TEETH = 16
R = MODULE * TEETH / 2.0  # pitch radius; the gears sit 2R apart so they mesh
PLATE = 4.0
Z0 = PLATE + 0.6  # gears float just above the palm
ZF = Z0 + T  # fingers sit on their gears
FW = 9.0  # finger width


def gear(cx, phase):
    body = Part.makeCylinder(R - MODULE, T, V(cx, 0, Z0))
    for i in range(TEETH):
        a = 2 * math.pi * i / TEETH + phase
        tooth = Part.makeBox(2.2 * MODULE, 1.6 * MODULE, T, V(-0.2 * MODULE, -0.8 * MODULE, 0))
        tooth.rotate(V(0, 0, 0), V(0, 0, 1), math.degrees(a))
        tooth.translate(V(cx + (R - MODULE) * math.cos(a), (R - MODULE) * math.sin(a), Z0))
        body = body.fuse(tooth)
    return body.cut(Part.makeCylinder(1.6, T + 2, V(cx, 0, Z0 - 1)))


def bar(a, b, width, height, z):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    box = Part.makeBox(length, width, height, V(0, -width / 2.0, 0))
    box.rotate(V(0, 0, 0), V(0, 0, 1), math.degrees(math.atan2(dy, dx)))
    box.translate(V(a[0], a[1], z))
    caps = Part.makeCylinder(width / 2.0, height, V(a[0], a[1], z)).fuse(Part.makeCylinder(width / 2.0, height, V(b[0], b[1], z)))
    return box.fuse(caps)


def finger(side):
    pivot = (side * R, 0.0)
    xo = side * (OPEN / 2.0 + PAD + FW / 2.0)
    knee = (xo, L * 0.35)
    tip = (xo, L)
    shape = bar(pivot, knee, FW, T, ZF).fuse(bar(knee, tip, FW, T, ZF))
    return shape.cut(Part.makeCylinder(1.6, T + 2, V(pivot[0], pivot[1], ZF - 1)))


def pad(side):
    x_inner = side * (OPEN / 2.0)
    x0 = min(x_inner, x_inner + side * PAD)
    return Part.makeBox(PAD, L * 0.45, T, V(x0, L * 0.55, ZF))


# Palm: wide enough for both gears and the fingers swinging open.
width = OPEN + 2 * (PAD + FW) + 12
depth = SL + 16
palm = Part.makeBox(width, depth, PLATE, V(-width / 2.0, -depth + 14, 0))
for x in (-R, R):
    palm = palm.cut(Part.makeCylinder(1.7 if x > 0 else 3.2, PLATE + 2, V(x, 0, -1)))
for sx in (-1, 1):
    for y in (-depth + 20, 8):
        palm = palm.cut(Part.makeCylinder(1.7, PLATE + 2, V(sx * (width / 2.0 - 6), y, -1)))
# Wrist flange at the back, four M3 holes on a 25 mm square for the robot arm.
flange = Part.makeBox(36, PLATE, 36, V(-18, -depth + 14 - PLATE, -16))
for fx in (-12.5, 12.5):
    for fz in (-12.5, 12.5):
        flange = flange.cut(Part.makeCylinder(1.7, PLATE + 2, V(fx, -depth + 13 - PLATE, 2 + fz), V(0, 1, 0)))
palm = palm.fuse(flange)

# The servo hangs under the palm, output shaft on the left gear axis.
servo = Part.makeBox(SW, SL, SH, V(-R - SW / 2.0, -SHAFT, -SH))
servo = servo.fuse(Part.makeCylinder(2.4, PLATE + 0.6, V(-R, 0, 0)))

parts = {
    "Palm": palm,
    "Gear L": gear(-R, 0.0),
    "Gear R": gear(R, math.pi / TEETH),
    "Finger L": finger(-1),
    "Finger R": finger(1),
    "Pad L": pad(-1),
    "Pad R": pad(1),
    "Servo": servo,
}
colors = {
    "Palm": "#c9ccd3",
    "Gear L": "#ff8a3d",
    "Gear R": "#ff8a3d",
    "Finger L": "#e7e8ec",
    "Finger R": "#e7e8ec",
    "Pad L": "#2b2d33",
    "Pad R": "#2b2d33",
    "Servo": "#3b5bdb",
}
materials = {"Pad L": "TPU", "Pad R": "TPU"}
reference = ["Servo"]
