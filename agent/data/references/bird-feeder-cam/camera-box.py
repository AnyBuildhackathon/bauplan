import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 110.0)
D = P.get("depth_mm", 70.0)
H = P.get("height_mm", 60.0)
WALL = P.get("wall_mm", 2.4)
VENTS = P.get("vents_mm2", 360.0)
Y0 = 10.0
Z0 = 3.0

# Closed box at the back of the tray for the Pi 4 and the AI camera, looking at the seed through a window.
outer = Part.makeBox(W, D, H, V(-W / 2.0, Y0, Z0))
inner = Part.makeBox(W - 2 * WALL, D - 2 * WALL, H - WALL, V(-W / 2.0 + WALL, Y0 + WALL, Z0 + WALL))
box = outer.cut(inner)
# Lens window in the front wall at the camera's height.
box = box.cut(Part.makeCylinder(9.0, WALL + 2, V(0, Y0 - 1, 45.0), V(0, 1, 0)))
# Vent slots high in both side walls, under the roof overhang: VENTS mm2 in total.
slot_h = 3.0
slots = max(1, int(round(VENTS / 2.0 / (40.0 * slot_h))))
for i in range(slots):
    z = Z0 + H - 10.0 - i * (slot_h + 3.0)
    for x in (-W / 2.0 - 1, W / 2.0 - WALL - 1):
        box = box.cut(Part.makeBox(WALL + 2, 40.0, slot_h, V(x, Y0 + D / 2.0 - 20.0, z)))
# USB-C cable hole in the back wall.
box = box.cut(Part.makeBox(14.0, WALL + 2, 8.0, V(30.0, Y0 + D - WALL - 1, Z0 + 8.0)))
shape = box
