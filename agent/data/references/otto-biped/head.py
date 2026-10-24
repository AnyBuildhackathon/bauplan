import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 78.0)
D = P.get("depth_mm", 52.0)
H = P.get("height_mm", 38.0)
WALL = P.get("wall_mm", 2.0)
EYE = P.get("eye_mm", 16.5)
Z0 = 78.0

# Open-bottom head that sits on the body; the HC-SR04 looks out through the two eyes.
outer = Part.makeBox(W, D, H, V(-W / 2.0, -D / 2.0, Z0))
inner = Part.makeBox(W - 2 * WALL, D - 2 * WALL, H - WALL, V(-W / 2.0 + WALL, -D / 2.0 + WALL, Z0))
head = outer.cut(inner)
# Eyes 26 mm apart, the spacing of the HC-SR04 transducers.
for x in (-13.0, 13.0):
    head = head.cut(Part.makeCylinder(EYE / 2.0, WALL + 2, V(x, -D / 2.0 - 1, Z0 + 20.0), V(0, 1, 0)))
# Rim that locates the head on the body.
rim = Part.makeBox(W - 2 * WALL - 0.6, D - 2 * WALL - 0.6, 4.0, V(-W / 2.0 + WALL + 0.3, -D / 2.0 + WALL + 0.3, Z0 - 4.0))
rim = rim.cut(Part.makeBox(W - 4 * WALL, D - 4 * WALL, 4.0, V(-W / 2.0 + 2 * WALL, -D / 2.0 + 2 * WALL, Z0 - 4.0)))
shape = head.fuse(rim)
