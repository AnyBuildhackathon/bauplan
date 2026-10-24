import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 64.0)
H = P.get("height_mm", 32.0)
WALL = P.get("wall_mm", 2.0)
Y = -185.0
Z_TOP = 275.0

# Open-bottom shade hanging under the end of the arm; the LED star sits under its roof.
outer = Part.makeBox(W, W, H, V(-W / 2.0, Y - W / 2.0, Z_TOP - H))
inner = Part.makeBox(W - 2 * WALL, W - 2 * WALL, H + 1 - WALL, V(-W / 2.0 + WALL, Y - W / 2.0 + WALL, Z_TOP - H - 1))
head = outer.cut(inner)
# Vent slots in the roof next to the arm.
for x in (-22.0, 16.0):
    head = head.cut(Part.makeBox(6.0, 30.0, 5.0, V(x, Y - 15.0, Z_TOP - 4.0)))
shape = head
