import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 220.0)
D = P.get("depth_mm", 160.0)
LIP = P.get("lip_mm", 18.0)
WALL = P.get("wall_mm", 2.4)
FLOOR = 3.0

# Open seed tray that stands on a garden table or a window ledge, with drain holes in the floor.
outer = Part.makeBox(W, D, LIP, V(-W / 2.0, -D / 2.0, 0))
inner = Part.makeBox(W - 2 * WALL, D - 2 * WALL, LIP, V(-W / 2.0 + WALL, -D / 2.0 + WALL, FLOOR))
tray = outer.cut(inner)
for x in (-70.0, -35.0, 0.0, 35.0, 70.0):
    for y in (-50.0, -25.0):
        tray = tray.cut(Part.makeCylinder(2.0, FLOOR + 2, V(x, y, -1)))
shape = tray
