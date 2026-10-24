import FreeCAD
import Part
import math

V = FreeCAD.Vector

OPEN = P.get("opening_mm", 40.0)
FINGER = P.get("finger_mm", 70.0)
Y0 = 116.0 * math.cos(math.radians(30.0)) + 135.0 + 55.0
Z = 90.0 + 116.0 * math.sin(math.radians(30.0))

# Gripper palm on the wrist roll with a fixed jaw and the moving jaw that the gripper servo swings.
grip = Part.makeBox(OPEN + 20.0, 12.0, 30.0, V(-(OPEN + 20.0) / 2.0, Y0, Z - 15.0))
for x in (-OPEN / 2.0 - 10.0, OPEN / 2.0):
    grip = grip.fuse(Part.makeBox(10.0, FINGER, 20.0, V(x, Y0 + 12.0, Z - 10.0)))
shape = grip
