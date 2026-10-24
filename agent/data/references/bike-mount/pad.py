import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 22.0)
OUTER = P.get("outer_mm", 32.0)
INNER = P.get("inner_mm", 22.6)
ZC = 25.0

# TPU shim that adapts the 31.8 mm clamp to a 22.2 mm bar; leave it out on a 31.8 mm bar.
ring = Part.makeCylinder(OUTER / 2.0, W, V(-W / 2.0, 0, ZC), V(1, 0, 0))
ring = ring.cut(Part.makeCylinder(INNER / 2.0, W + 2, V(-W / 2.0 - 1, 0, ZC), V(1, 0, 0)))
# Split slot along the top so it wraps around the bar.
ring = ring.cut(Part.makeBox(W + 2, 3.0, OUTER, V(-W / 2.0 - 1, -1.5, ZC)))
shape = ring
