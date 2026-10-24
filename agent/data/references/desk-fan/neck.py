import FreeCAD
import Part

V = FreeCAD.Vector

OD = P.get("outer_diameter_mm", 16.0)
ID = P.get("inner_diameter_mm", 8.0)
H = P.get("height_mm", 91.0)
Z0 = 5.0

outer = Part.makeCylinder(OD / 2.0, H, V(0, 0, Z0))
bore = Part.makeCylinder(ID / 2.0, H + 2, V(0, 0, Z0 - 1))
tube = outer.cut(bore)

shape = tube
