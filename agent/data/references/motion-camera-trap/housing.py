import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 70.0)
D = P.get("depth_mm", 45.0)
H = P.get("height_mm", 110.0)
WALL = P.get("wall_mm", 2.4)
LENS = P.get("lens_hole_mm", 12.0)
Z0 = 4.0

# Upright box open at the back, the camera lying across the top looking out of the front (-Y),
# the PIR lens below it and the 18650 holder standing in the lower half.
outer = Part.makeBox(W, D, H, V(-W / 2.0, -D / 2.0, Z0))
inner = Part.makeBox(W - 2 * WALL, D - WALL + 1, H - 2 * WALL, V(-W / 2.0 + WALL, -D / 2.0 + WALL, Z0 + WALL))
box = outer.cut(inner)
box = box.cut(Part.makeCylinder(LENS / 2.0, WALL + 2, V(0, -D / 2.0 - 1, 98.0), V(0, 1, 0)))
box = box.cut(Part.makeCylinder(5.3, WALL + 2, V(0, -D / 2.0 - 1, 72.0), V(0, 1, 0)))
# Rain lip over the lens.
box = box.fuse(Part.makeBox(W, 10.0, 2.0, V(-W / 2.0, -D / 2.0 - 10.0, 108.0)))
# Four bosses for the back lid screws.
for x in (-W / 2.0 + WALL, W / 2.0 - WALL - 6.0):
    for z in (Z0 + WALL, Z0 + H - WALL - 6.0):
        boss = Part.makeBox(6.0, 8.0, 6.0, V(x, D / 2.0 - 8.0, z))
        box = box.fuse(boss.cut(Part.makeCylinder(1.25, 9.0, V(x + 3.0, D / 2.0 - 8.5, z + 3.0), V(0, 1, 0))))
shape = box
