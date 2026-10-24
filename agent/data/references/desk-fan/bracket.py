import math
import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 86.0)
H = P.get("height_mm", 86.0)
D = P.get("depth_mm", 28.0)
T = P.get("wall_mm", 3.0)
ZC = 140.0
SOCK_D = 16.0
SOCK_H = 4.0

z0 = ZC - H / 2.0  # 97

outer = Part.makeBox(W, D, H, V(-W / 2.0, -D / 2.0, z0))
inner_w = W - 2 * T
inner_h = H - 2 * T
pocket = Part.makeBox(inner_w, D + 2, inner_h, V(-inner_w / 2.0, -D / 2.0 - 1, z0 + T))
frame = outer.cut(pocket)

# Socket in the bottom face for the neck (bottom wall is 3 mm; the socket is 4 mm deep,
# so it cuts into the pocket slightly; keep a ring of wall around it by adding a boss).
boss_d = SOCK_D + 8.0
boss = Part.makeCylinder(boss_d / 2.0, SOCK_H + T, V(0, 0, z0))
# Limit boss to inside the frame depth
frame = frame.fuse(boss)
sock = Part.makeCylinder(SOCK_D / 2.0, SOCK_H, V(0, 0, z0 - 0.001))
frame = frame.cut(sock)

shape = frame
