import math
import FreeCAD
import Part

V = FreeCAD.Vector

R = P.get("radius_mm", 20.0)
L = P.get("length_mm", 140.0)
PITCH = P.get("pitch_mm", 15.0)
X0 = -50.0
Z = 35.0

# Shaft with a stepped flight: thin blades turned 30 degrees apart along the axis,
# an approximation of a helix that prints without supports when stood on end.
auger = Part.makeCylinder(5.0, L, V(X0, 0, Z), V(1, 0, 0))
blade_step = PITCH / 12.0 * 4.0
x = X0 + 14.0
angle = 0.0
while x < X0 + L - 4.0:
    blade = Part.makeBox(3.0, 2 * R, 6.0, V(x, -R, Z - 3.0))
    blade.rotate(V(x, 0, Z), V(1, 0, 0), angle)
    auger = auger.fuse(blade)
    x += blade_step
    angle += 30.0
# Coupler for the 5 mm D-shaft of the 28BYJ-48 at the motor end.
coupler = Part.makeCylinder(7.0, 12.0, V(X0, 0, Z), V(1, 0, 0))
coupler = coupler.cut(Part.makeCylinder(2.6, 9.0, V(X0 - 1, 0, Z), V(1, 0, 0)))
auger = auger.cut(Part.makeCylinder(2.6, 9.0, V(X0 - 1, 0, Z), V(1, 0, 0)))
shape = auger.fuse(coupler)
