import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 70.0)
H = P.get("height_mm", 110.0)
T = P.get("thickness_mm", 2.4)
Y0 = 22.5
Z0 = 4.0

# Back lid with four M2.5 holes, a USB-C hole for charging the cell and a keyhole to hang it on a screw.
lid = Part.makeBox(W, T, H, V(-W / 2.0, Y0, Z0))
for x in (-W / 2.0 + 5.4, W / 2.0 - 5.4):
    for z in (Z0 + 5.4, Z0 + H - 5.4):
        lid = lid.cut(Part.makeCylinder(1.4, T + 2, V(x, Y0 - 1, z), V(0, 1, 0)))
lid = lid.cut(Part.makeBox(11.0, T + 2, 5.0, V(-5.5, Y0 - 1, Z0 + 10.0)))
lid = lid.cut(Part.makeCylinder(4.0, T + 2, V(0, Y0 - 1, Z0 + H - 25.0), V(0, 1, 0)))
lid = lid.cut(Part.makeBox(3.5, T + 2, 10.0, V(-1.75, Y0 - 1, Z0 + H - 35.0)))
shape = lid
