import FreeCAD
import Part

V = FreeCAD.Vector

R = P.get("radius_mm", 45.0)
W = P.get("width_mm", 20.0)
X = P.get("track_mm", 140.0) / 2.0

# Two wheels on the stepper shafts (axle along X at Z=R), each with a 5 mm D-bore hub and three windows.
wheels = None
for x0 in (X - W / 2.0, -X - W / 2.0):
    wheel = Part.makeCylinder(R, W, V(x0, 0, R), V(1, 0, 0))
    wheel = wheel.cut(Part.makeCylinder(2.6, W + 2, V(x0 - 1, 0, R), V(1, 0, 0)))
    for y, z in ((0.0, R + 24.0), (20.8, R - 12.0), (-20.8, R - 12.0)):
        wheel = wheel.cut(Part.makeCylinder(9.0, W + 2, V(x0 - 1, y, z), V(1, 0, 0)))
    wheels = wheel if wheels is None else wheels.fuse(wheel)
shape = wheels
