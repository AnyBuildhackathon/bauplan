import FreeCAD
import Part
import math

V = FreeCAD.Vector

L = P.get("length_mm", 80.0)
W = P.get("width_mm", 14.0)
T = P.get("thickness_mm", 6.0)
UPPER = 80.0
ANGLE = 45.0
SHOULDER_Z = 64.0
ELBOW_Y = UPPER * math.cos(math.radians(ANGLE))
ELBOW_Z = SHOULDER_Z + UPPER * math.sin(math.radians(ANGLE))

# Horizontal forearm from the elbow forwards to the claw.
arm = Part.makeBox(W, L + 10.0, T, V(-W / 2.0, ELBOW_Y - 5.0, ELBOW_Z - T / 2.0))
arm = arm.cut(Part.makeCylinder(2.0, T + 2, V(0, ELBOW_Y, ELBOW_Z - T / 2.0 - 1)))
shape = arm
