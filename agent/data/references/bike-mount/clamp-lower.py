import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 20.0)
BAR = P.get("bar_mm", 32.4)
SPAN = P.get("span_mm", 56.0)
ZC = 25.0
HOLE = 3.4
INSERT = 4.2

# Lower half of the bar clamp: a block under the bar (axis along X at Z=25) with a half bore.
lower = Part.makeBox(W, SPAN, ZC, V(-W / 2.0, -SPAN / 2.0, 0))
bore = Part.makeCylinder(BAR / 2.0, W + 2, V(-W / 2.0 - 1, 0, ZC), V(1, 0, 0))
lower = lower.cut(bore)
# Heat-set insert holes in both ears, from the top split face.
for y in (-SPAN / 2.0 + 5.0, SPAN / 2.0 - 5.0):
    lower = lower.cut(Part.makeCylinder(INSERT / 2.0, 8.0, V(0, y, ZC - 8.0)))
    lower = lower.cut(Part.makeCylinder(HOLE / 2.0, ZC, V(0, y, 0)))
# Light tab at the front: a 6 mm lug with an M5 cross hole for a light bracket.
lug = Part.makeBox(6.0, 18.0, 16.0, V(-3.0, -SPAN / 2.0 - 16.0, 0))
lug = lug.cut(Part.makeCylinder(2.7, 8.0, V(-4.0, -SPAN / 2.0 - 9.0, 8.0), V(1, 0, 0)))
shape = lower.fuse(lug)
