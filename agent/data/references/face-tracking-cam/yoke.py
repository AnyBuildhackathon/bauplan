import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 50.0)
H = P.get("height_mm", 60.0)
T = P.get("thickness_mm", 3.0)
DEPTH = 20.0
Z0 = 32.0
AXIS_Z = 80.0

# U bracket on the pan servo horn: a plate and two uprights that carry the tilt axis.
plate = Part.makeBox(W, DEPTH, T, V(-W / 2.0, -DEPTH / 2.0, Z0))
left = Part.makeBox(T, DEPTH, H, V(-W / 2.0, -DEPTH / 2.0, Z0 + T))
right = Part.makeBox(T, DEPTH, H, V(W / 2.0 - T, -DEPTH / 2.0, Z0 + T))
yoke = plate.fuse(left).fuse(right)
# Horn pocket under the plate centre, the tilt bearing hole on the left and the servo horn hole on the right.
yoke = yoke.cut(Part.makeCylinder(3.5, T + 2, V(0, 0, Z0 - 1)))
yoke = yoke.cut(Part.makeCylinder(3.2, T + 2, V(-W / 2.0 - 1, 0, AXIS_Z), V(1, 0, 0)))
yoke = yoke.cut(Part.makeCylinder(3.5, T + 2, V(W / 2.0 - T - 1, 0, AXIS_Z), V(1, 0, 0)))
shape = yoke
