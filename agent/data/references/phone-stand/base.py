# Base plate of a desk phone stand: a flat plate with a front lip the phone stands
# behind, and a cable slot through the lip. Units are mm, Z is up, -Y is the front.
# depth_mm runs from the front edge backwards, so a deeper base resists tipping back.
W = P.get("width_mm", 80.0)
D = P.get("depth_mm", 60.0)
T = P.get("thickness_mm", 5.0)
LIP = P.get("lip_height_mm", 12.0)
FRONT = -25.0

plate = Part.makeBox(W, D, T, Vector(-W / 2.0, FRONT, 0))
lip = Part.makeBox(W, 5.0, T + LIP, Vector(-W / 2.0, FRONT, 0))
base = plate.fuse(lip)
# Charging cable slot through the lip and the plate front.
base = base.cut(Part.makeBox(14.0, 12.0, T + LIP + 2.0, Vector(-7.0, FRONT - 1.0, -1.0)))
shape = base.removeSplitter()
