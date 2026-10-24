import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 110.0)
D = P.get("depth_mm", 90.0)
T = P.get("thickness_mm", 4.0)

# Foot plate under the housing for a shelf, a sill or a fence post, with four screw holes.
plate = Part.makeBox(W, D, T, V(-W / 2.0, -D / 2.0, 0))
for x in (-W / 2.0 + 8.0, W / 2.0 - 8.0):
    for y in (-D / 2.0 + 8.0, D / 2.0 - 8.0):
        plate = plate.cut(Part.makeCylinder(2.2, T + 2, V(x, y, -1)))
shape = plate
