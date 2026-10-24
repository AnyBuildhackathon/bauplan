import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 80.0)
L = P.get("length_mm", 150.0)
H = P.get("height_mm", 36.0)
WALL = P.get("wall_mm", 2.5)
Z0 = P.get("belly_z_mm", 72.0)

# Hollow body shell for the eight hip servos, the ESP32, the PCA9685 and the 2S pack.
body = Part.makeBox(W, L, H, V(-W / 2.0, -L / 2.0, Z0))
body = body.cut(Part.makeBox(W - 2 * WALL, L - 2 * WALL, H - WALL, V(-W / 2.0 + WALL, -L / 2.0 + WALL, Z0 + WALL)))
# Hip servo windows in the side walls, one per leg, where the hip horns come out.
for x in (-W / 2.0 - 1, W / 2.0 - WALL - 1):
    for y in (-60.0, 60.0):
        body = body.cut(Part.makeBox(WALL + 2, 24.0, 14.0, V(x, y - 12.0, Z0 + 13.0)))
shape = body
