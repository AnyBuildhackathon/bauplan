import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 78.0)
D = P.get("depth_mm", 52.0)
H = P.get("height_mm", 40.0)
WALL = P.get("wall_mm", 2.0)
Z0 = 38.0
HIP_X = 22.0

# Open-top body box that carries the two hip servos, the Nano and its shield.
outer = Part.makeBox(W, D, H, V(-W / 2.0, -D / 2.0, Z0))
inner = Part.makeBox(W - 2 * WALL, D - 2 * WALL, H, V(-W / 2.0 + WALL, -D / 2.0 + WALL, Z0 + WALL))
body = outer.cut(inner)
# Hip servo pockets: an SG90 stands upright in each, its horn turns the leg below the floor.
for x in (-HIP_X, HIP_X):
    body = body.fuse(Part.makeBox(16.0, 26.5, 18.0, V(x - 8.0, -13.25, Z0 + WALL)))
    body = body.cut(Part.makeBox(12.6, 23.0, 18.0, V(x - 6.3, -11.5, Z0 + WALL)))
    body = body.cut(Part.makeCylinder(4.0, WALL + 2, V(x, -5.5, Z0 - 1)))
# Switch hole in the back wall.
body = body.cut(Part.makeBox(13.0, WALL + 2, 9.0, V(-6.5, D / 2.0 - WALL - 1, Z0 + 20.0)))
shape = body
