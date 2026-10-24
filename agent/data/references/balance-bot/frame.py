import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 120.0)
D = P.get("depth_mm", 50.0)
H = P.get("height_mm", 180.0)
T = P.get("wall_mm", 5.0)
DECK_Z = P.get("deck_z_mm", 110.0)
Z0 = 45.0 - 21.2

# Front and back walls standing on the motor mount, with the electronics deck between them.
frame = None
for y in (D / 2.0, -D / 2.0 - T):
    wall = Part.makeBox(W, T, H, V(-W / 2.0, y, Z0))
    wall = wall.cut(Part.makeBox(W - 40.0, T + 2, H - 90.0, V(-W / 2.0 + 20.0, y - 1, Z0 + 60.0)))
    frame = wall if frame is None else frame.fuse(wall)
frame = frame.fuse(Part.makeBox(W, D, 4.0, V(-W / 2.0, -D / 2.0, DECK_Z)))
shape = frame
