import math
import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 16.0)
L = P.get("length_mm", 105.0)
T = P.get("thickness_mm", 6.0)

Z0 = 124.0
Y_START = -45.0

bar = Part.makeBox(W, L, T, V(-W / 2.0, Y_START - L, Z0))

# screw holes at the tank end
for y in (-50.0, -60.0):
    bar = bar.cut(Part.makeCylinder(1.5, T + 2, V(0, y, Z0 - 1)))

# sensor blade slot at Y=-145 (5 mm in Y), limited to leave 2 mm side rails
slot_x = W - 4.0
slot = Part.makeBox(slot_x, 5.0, T + 2, V(-slot_x / 2.0, -145.0 - 2.5, Z0 - 1))
bar = bar.cut(slot)

shape = bar
