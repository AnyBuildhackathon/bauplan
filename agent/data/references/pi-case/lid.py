# Lid of the Raspberry Pi 5 case: a plate with a locating rim that drops into the
# shell. vents_mm2 is the open area cut over the SoC: zero is a closed lid, the
# area of a 40 mm fan opening takes the fan on four M3 holes on a 32 mm square.
import math

W = P.get("width_mm", 95.0)
D = P.get("depth_mm", 70.0)
T = P.get("thickness_mm", 2.5)
Z = P.get("shell_height_mm", 27.0)
WALL = P.get("wall_mm", 2.0)
VENTS = P.get("vents_mm2", 0.0)

lid = Part.makeBox(W, D, T, Vector(-W / 2.0, -D / 2.0, Z))
rim = Part.makeBox(W - 2 * WALL - 0.4, D - 2 * WALL - 0.4, 3.0, Vector(-W / 2.0 + WALL + 0.2, -D / 2.0 + WALL + 0.2, Z - 3.0))
rim = rim.cut(Part.makeBox(W - 2 * WALL - 4.4, D - 2 * WALL - 4.4, 3.0, Vector(-W / 2.0 + WALL + 2.2, -D / 2.0 + WALL + 2.2, Z - 3.0)))
lid = lid.fuse(rim)
if VENTS > 0:
    radius = math.sqrt(VENTS / math.pi)
    lid = lid.cut(Part.makeCylinder(radius, T + 2.0, Vector(-4.0, 0, Z - 1.0)))
    for x in (-16.0, 16.0):
        for y in (-16.0, 16.0):
            lid = lid.cut(Part.makeCylinder(1.6, T + 2.0, Vector(-4.0 + x, y, Z - 1.0)))
shape = lid.removeSplitter()
