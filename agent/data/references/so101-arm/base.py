import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 110.0)
D = P.get("depth_mm", 110.0)
PLATE = P.get("plate_mm", 6.0)
H = P.get("housing_height_mm", 40.0)

# Foot plate with a clamp tab at the back that a desk clamp holds down.
base = Part.makeBox(W, D, PLATE, V(-W / 2.0, -D / 2.0, 0))
base = base.fuse(Part.makeBox(50.0, 30.0, PLATE, V(-25.0, -D / 2.0 - 30.0, 0)))
# Housing for the base STS3215, standing in the middle of the plate.
housing = Part.makeBox(56.0, 46.0, H, V(-28.0, -23.0, PLATE))
housing = housing.cut(Part.makeBox(46.0, 36.0, H, V(-23.0, -18.0, PLATE + 3.0)))
base = base.fuse(housing)
# Two M6 holes for the clamp in the tab.
for x in (-12.0, 12.0):
    base = base.cut(Part.makeCylinder(3.2, PLATE + 2, V(x, -D / 2.0 - 15.0, -1)))
shape = base
