import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 16.0)
T = P.get("thickness_mm", 13.0)
REACH = P.get("reach_mm", 200.0)
Z0 = 275.0
Y_POST = 20.0
TAIL = 12.0

# Horizontal arm on top of the post, reaching forwards (-Y) to the head.
arm = Part.makeBox(W, REACH + Y_POST + TAIL, T, V(-W / 2.0, -REACH, Z0))
arm = arm.makeFillet(3.0, [e for e in arm.Edges if abs(e.Vertexes[0].Point.y - e.Vertexes[-1].Point.y) > 1.0])
# Wire groove along the underside.
arm = arm.cut(Part.makeBox(4.0, REACH + Y_POST, 2.5, V(-2.0, -REACH, Z0 - 1)))
shape = arm
