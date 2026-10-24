import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 120.0)
H = P.get("height_mm", 100.0)
WALL = P.get("wall_mm", 1.8)
OUTLET = P.get("outlet_mm", 40.0)
Z0 = 60.0

# Open-top square hopper on the base, with the outlet over the chute.
outer = Part.makeBox(W, W, H, V(-W / 2.0, -W / 2.0, Z0))
inner = Part.makeBox(W - 2 * WALL, W - 2 * WALL, H, V(-W / 2.0 + WALL, -W / 2.0 + WALL, Z0 + WALL))
hopper = outer.cut(inner)
hopper = hopper.cut(Part.makeCylinder(OUTLET / 2.0, WALL + 2, V(0, 0, Z0 - 1)))
shape = hopper
