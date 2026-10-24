import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 50.0)
D = P.get("depth_mm", 30.0)
H = P.get("height_mm", 36.0)
Y0 = 75.0
Z0 = 86.0

# Head on the front of the body: the HC-SR04 looks out through two 16 mm eyes.
head = Part.makeBox(W, D, H, V(-W / 2.0, Y0, Z0))
head = head.cut(Part.makeBox(W - 4.0, D - 4.0, H - 4.0, V(-W / 2.0 + 2.0, Y0, Z0 + 2.0)))
for x in (-13.0, 13.0):
    head = head.cut(Part.makeCylinder(8.0, 6.0, V(x, Y0 + D - 4.0, Z0 + H / 2.0), V(0, 1, 0)))
shape = head
