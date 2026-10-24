# Battery tray of the RC car: a tray for a 2S 1500 mAh pack (70 x 35 x 18 mm) with a
# strap slot, standing on four posts from the deck top so its floor is at tray_z_mm.
L = P.get("length_mm", 76.0)
W = P.get("width_mm", 41.0)
WALL = P.get("wall_mm", 2.0)
H = P.get("rim_mm", 8.0)
DECK = P.get("deck_top_mm", 40.0)
Z = P.get("tray_z_mm", 70.0)

tray = Part.makeBox(W, L, WALL + H, Vector(-W / 2.0, -L / 2.0, Z - WALL))
tray = tray.cut(Part.makeBox(W - 2 * WALL, L - 2 * WALL, H + 1.0, Vector(-W / 2.0 + WALL, -L / 2.0 + WALL, Z)))
tray = tray.cut(Part.makeBox(W + 2.0, 20.0, 3.0, Vector(-W / 2.0 - 1.0, -10.0, Z + H - 3.0)))
if Z - WALL > DECK + 0.5:
    for x in (-W / 2.0 + 4.0, W / 2.0 - 4.0):
        for y in (-L / 2.0 + 4.0, L / 2.0 - 4.0):
            tray = tray.fuse(Part.makeCylinder(3.0, Z - WALL - DECK, Vector(x, y, DECK)))
shape = tray.removeSplitter()
