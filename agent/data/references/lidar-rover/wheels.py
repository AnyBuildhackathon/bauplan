import math

import FreeCAD
import Part

V = FreeCAD.Vector

R = P.get("radius_mm", 42.0)
W = P.get("width_mm", 20.0)
X = P.get("track_mm", 236.0) / 2.0

# Two wheels on the gear motor shafts (axle along X at Z=R), each with a 6 mm hub bore, a tyre groove and five windows.
wheels = None
for x0 in (X - W / 2.0, -X - W / 2.0):
    wheel = Part.makeCylinder(R, W, V(x0, 0, R), V(1, 0, 0))
    wheel = wheel.cut(Part.makeCylinder(3.1, W + 2, V(x0 - 1, 0, R), V(1, 0, 0)))
    groove = Part.makeCylinder(R + 1, 8.0, V(x0 + W / 2.0 - 4.0, 0, R), V(1, 0, 0))
    groove = groove.cut(Part.makeCylinder(R - 2.0, 8.0, V(x0 + W / 2.0 - 4.0, 0, R), V(1, 0, 0)))
    wheel = wheel.cut(groove)
    for i in range(5):
        a = math.radians(i * 72.0)
        y, z = 24.0 * math.cos(a), R + 24.0 * math.sin(a)
        wheel = wheel.cut(Part.makeCylinder(7.5, W + 2, V(x0 - 1, y, z), V(1, 0, 0)))
    wheels = wheel if wheels is None else wheels.fuse(wheel)
shape = wheels
