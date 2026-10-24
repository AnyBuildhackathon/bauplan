import FreeCAD
import Part
import math

V = FreeCAD.Vector

L = P.get("length_mm", 135.0)
W = P.get("width_mm", 28.0)
T = P.get("thickness_mm", 24.0)
ELBOW_Y = 116.0 * math.cos(math.radians(30.0))
ELBOW_Z = 90.0 + 116.0 * math.sin(math.radians(30.0))

# Horizontal hollow forearm from the elbow forwards to the wrist servos.
arm = Part.makeBox(W, L + 12.0, T, V(-W / 2.0, ELBOW_Y - 12.0, ELBOW_Z - T / 2.0))
arm = arm.cut(Part.makeBox(W - 6.0, L - 40.0, T - 6.0, V(-W / 2.0 + 3.0, ELBOW_Y + 20.0, ELBOW_Z - T / 2.0 + 3.0)))
arm = arm.cut(Part.makeCylinder(4.0, W + 2, V(-W / 2.0 - 1, ELBOW_Y, ELBOW_Z), V(1, 0, 0)))
shape = arm
