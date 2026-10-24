import FreeCAD
import Part
import math

V = FreeCAD.Vector

LEN = P.get("length_mm", 55.0)
W = P.get("width_mm", 40.0)
H = P.get("height_mm", 36.0)
Y0 = 116.0 * math.cos(math.radians(30.0)) + 135.0
Z = 90.0 + 116.0 * math.sin(math.radians(30.0))

# Wrist housing for the wrist-flex and wrist-roll STS3215 at the forearm tip.
wrist = Part.makeBox(W, LEN, H, V(-W / 2.0, Y0, Z - H / 2.0))
wrist = wrist.cut(Part.makeBox(W - 6.0, LEN - 6.0, H - 6.0, V(-W / 2.0 + 3.0, Y0 + 3.0, Z - H / 2.0 + 3.0)))
shape = wrist
