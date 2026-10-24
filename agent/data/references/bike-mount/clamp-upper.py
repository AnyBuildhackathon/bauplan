import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 20.0)
BAR = P.get("bar_mm", 32.4)
SPAN = P.get("span_mm", 56.0)
ZC = 25.0
TOP = P.get("top_mm", 47.0)
HOLE = 3.4
HEAD = 6.0

# Upper half of the bar clamp with a flat top the cradle bolts to.
upper = Part.makeBox(W, SPAN, TOP - ZC, V(-W / 2.0, -SPAN / 2.0, ZC))
upper = upper.cut(Part.makeCylinder(BAR / 2.0, W + 2, V(-W / 2.0 - 1, 0, ZC), V(1, 0, 0)))
for y in (-SPAN / 2.0 + 5.0, SPAN / 2.0 - 5.0):
    upper = upper.cut(Part.makeCylinder(HOLE / 2.0, TOP - ZC + 2, V(0, y, ZC - 1)))
    upper = upper.cut(Part.makeCylinder(HEAD / 2.0, 4.0, V(0, y, TOP - 3.0)))
shape = upper
