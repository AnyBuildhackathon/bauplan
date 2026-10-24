import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 84.0)
L = P.get("length_mm", 150.0)
T = P.get("thickness_mm", 3.0)
LIP = P.get("lip_mm", 6.0)
Z0 = 47.0
STEM = 6.0
SPAN = 56.0

# Stem block on the clamp top, then the phone tray with side lips and end hooks.
stem = Part.makeBox(20.0, SPAN, STEM, V(-10.0, -SPAN / 2.0, Z0))
tray = Part.makeBox(W, L, T, V(-W / 2.0, -L / 2.0, Z0 + STEM))
for x in (-W / 2.0, W / 2.0 - 3.0):
    tray = tray.fuse(Part.makeBox(3.0, L, LIP + T, V(x, -L / 2.0, Z0 + STEM)))
for y in (-L / 2.0, L / 2.0 - 3.0):
    tray = tray.fuse(Part.makeBox(40.0, 3.0, LIP + T, V(-20.0, y, Z0 + STEM)))
cradle = stem.fuse(tray)
# Counterbored holes for the two M3 screws into the clamp inserts.
for y in (-SPAN / 2.0 + 5.0, SPAN / 2.0 - 5.0):
    cradle = cradle.cut(Part.makeCylinder(1.7, STEM + T + 2, V(0, y, Z0 - 1)))
    cradle = cradle.cut(Part.makeCylinder(3.0, 3.0, V(0, y, Z0 + STEM + T - 3.0)))
# Lighten the tray with one window beside the stem; the stem still carries the screws.
for x in (-W / 2.0 + 10.0, 10.0):
    cradle = cradle.cut(Part.makeBox(W / 2.0 - 20.0, 110.0, T + 2, V(x, -55.0, Z0 + STEM - 1)))
shape = cradle
