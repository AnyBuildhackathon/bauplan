import FreeCAD
import Part

V = FreeCAD.Vector

D = P.get("diameter_mm", 100.0)
H = P.get("height_mm", 30.0)
WALL = P.get("wall_mm", 2.4)
FLOOR = P.get("floor_mm", 5.0)

# Round hollow base with a thick floor to keep the centre of mass low,
# a pocket in the top for the pan servo and a slot for the USB-C cable.
outer = Part.makeCylinder(D / 2.0, H, V(0, 0, 0))
inner = Part.makeCylinder(D / 2.0 - WALL, H - FLOOR - WALL, V(0, 0, FLOOR))
base = outer.cut(inner)
# SG90 body 22.5 x 12.2 mm, its shaft at the centre: the body sits 6 mm towards -X.
base = base.cut(Part.makeBox(23.0, 12.8, WALL + 2, V(-6.0 - 11.5, -6.4, H - WALL - 1)))
# Two screw tabs of the servo rest on the top plate; holes for M2 screws.
for x in (-6.0 - 14.0, -6.0 + 14.0):
    base = base.cut(Part.makeCylinder(1.0, WALL + 2, V(x, 0, H - WALL - 1)))
base = base.cut(Part.makeBox(12.0, WALL + 2, 7.0, V(-6.0, D / 2.0 - WALL - 1, FLOOR + 2)))
shape = base
