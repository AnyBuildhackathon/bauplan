import FreeCAD
import Part

V = FreeCAD.Vector

S = P.get("side_mm", 18.0)
H = P.get("height_mm", 272.0)
BORE = P.get("bore_mm", 11.0)
Y = 20.0
Z0 = 3.0

# Square post standing in the base socket, with a bore for the LED wires.
post = Part.makeBox(S, S, H, V(-S / 2.0, Y - S / 2.0, Z0))
post = post.cut(Part.makeCylinder(BORE / 2.0, H + 2, V(0, Y, Z0 - 1)))
shape = post
