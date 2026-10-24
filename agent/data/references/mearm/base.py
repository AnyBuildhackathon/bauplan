import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 110.0)
D = P.get("depth_mm", 110.0)
H = P.get("height_mm", 28.0)
WALL = P.get("wall_mm", 2.0)

# Closed base box with the AA pack and the Nano inside; the base servo stands in the top plate.
outer = Part.makeBox(W, D, H, V(-W / 2.0, -D / 2.0, 0))
inner = Part.makeBox(W - 2 * WALL, D - 2 * WALL, H - 2 * WALL, V(-W / 2.0 + WALL, -D / 2.0 + WALL, WALL))
base = outer.cut(inner)
# Pocket for the base SG90 in the top plate, its horn turns the turret.
base = base.cut(Part.makeBox(12.6, 23.0, WALL + 2, V(-6.3, -17.0, H - WALL - 1)))
# USB hole for the Nano in the back wall.
base = base.cut(Part.makeBox(12.0, WALL + 2, 8.0, V(-6.0, D / 2.0 - WALL - 1, 8.0)))
shape = base
