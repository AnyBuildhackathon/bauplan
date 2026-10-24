import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 150.0)
D = P.get("depth_mm", 175.0)
T = P.get("thickness_mm", 10.0)
Y_BACK = 40.0
POST = 18.0
POST_Y = 20.0
SOCKET = 7.0
SKIN = 3.5

# Plate from y = 40 forwards, so the lamp head hangs over it.
base = Part.makeBox(W, D, T, V(-W / 2.0, Y_BACK - D, 0))
base = base.makeFillet(6.0, [e for e in base.Edges if abs(e.Vertexes[0].Point.z - e.Vertexes[-1].Point.z) > 1.0])
# Hollow underside in front of the socket, leaving a 3.5 mm top skin and a 5 mm rim.
base = base.cut(Part.makeBox(W - 10.0, D - 55.0, T - SKIN, V(-W / 2.0 + 5.0, Y_BACK - D + 5.0, -1)))
# Square socket for the post.
base = base.cut(Part.makeBox(POST + 0.4, POST + 0.4, SOCKET + 1, V(-(POST + 0.4) / 2.0, POST_Y - (POST + 0.4) / 2.0, T - SOCKET)))
# Cut-out for the 15 x 10 mm rocker switch near the front.
base = base.cut(Part.makeBox(13.0, 9.0, T + 2, V(-6.5, Y_BACK - D + 15.0, -1)))
# USB-C breakout pocket from below, with the socket opening in the back face.
base = base.cut(Part.makeBox(23.0, 23.0, 5.0, V(-11.5, Y_BACK - 25.0, -1)))
base = base.cut(Part.makeBox(10.0, 4.0, 4.0, V(-5.0, Y_BACK - 3.0, 0.5)))

shape = base
