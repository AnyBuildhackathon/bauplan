import math
import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 140.0)
D = P.get("depth_mm", 140.0)
H = P.get("height_mm", 30.0)
WALL = P.get("wall_mm", 2.5)
FLOOR = P.get("floor_mm", 3.0)
PLATE = 3.0
RECESS = 1.0
RW = 110.0

# Outer block
body = Part.makeBox(W, D, H, V(-W / 2.0, -D / 2.0, 0))

# Hollow interior (between floor and top plate)
iw = W - 2 * WALL
idp = D - 2 * WALL
ih = H - FLOOR - PLATE
cavity = Part.makeBox(iw, idp, ih, V(-iw / 2.0, -idp / 2.0, FLOOR))
body = body.cut(cavity)

# Tank recess in top plate, 1 mm deep
recess = Part.makeBox(RW, RW, RECESS + 0.5, V(-RW / 2.0, -RW / 2.0, H - RECESS))
body = body.cut(recess)

# Cable hole through plate at X=40, Y=40
hole = Part.makeCylinder(4.0, PLATE + 2, V(40, 40, H - PLATE - 1))
body = body.cut(hole)

# Tube hole in front wall (-Y) at X=-40, Z=15
tube = Part.makeCylinder(4.0, WALL + 4, V(-40, -D / 2.0 - 1, 15), V(0, 1, 0))
body = body.cut(tube)

# Cable slot 6 x 3 mm at the top front edge (centred X=0), through the front wall
slot = Part.makeBox(6, WALL + 2, 3, V(-3, -D / 2.0 - 1, H - 3))
body = body.cut(slot)

shape = body
