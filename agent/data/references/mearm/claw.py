import FreeCAD
import Part
import math

V = FreeCAD.Vector

OPEN = P.get("opening_mm", 30.0)
FINGER = P.get("finger_mm", 32.0)
Y0 = 80.0 * math.cos(math.radians(45.0)) + 80.0 + 5.0
Z = 64.0 + 80.0 * math.sin(math.radians(45.0))

# Claw housing for the gripper SG90 and two fingers OPEN apart reaching forwards.
claw = Part.makeBox(OPEN + 12.0, 16.0, 14.0, V(-(OPEN + 12.0) / 2.0, Y0, Z - 7.0))
claw = claw.cut(Part.makeBox(12.6, 12.0, 15.0, V(-6.3, Y0 + 2.0, Z - 8.0)))
for x in (-OPEN / 2.0 - 4.0, OPEN / 2.0):
    claw = claw.fuse(Part.makeBox(4.0, FINGER, 10.0, V(x, Y0 + 16.0, Z - 5.0)))
shape = claw
