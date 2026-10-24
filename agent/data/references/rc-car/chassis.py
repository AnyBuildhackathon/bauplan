# Chassis plate of a 2WD RC car: a flat plate between the rear wheels with two
# outrigger arms that carry the N20 motor clamps at track_mm between the wheel
# centres. The rear axle sits at y = +wheelbase / 2, the ball caster at the front.
W_PLATE = P.get("plate_width_mm", 70.0)
WB = P.get("wheelbase_mm", 110.0)
TRACK = P.get("track_mm", 100.0)
T = P.get("thickness_mm", 4.0)
Z = P.get("deck_z_mm", 36.0)

L = WB + 40.0
plate = Part.makeBox(W_PLATE, L, T, Vector(-W_PLATE / 2.0, -L / 2.0, Z))
# Outrigger arm across the rear axle out to the motor clamps, the wheels outside them.
arm_w = max(TRACK - 30.0, W_PLATE)
plate = plate.fuse(Part.makeBox(arm_w, 16.0, T, Vector(-arm_w / 2.0, WB / 2.0 - 8.0, Z)))
for side in (-1.0, 1.0):
    x = side * (arm_w / 2.0 - 7.0)
    clamp = Part.makeBox(14.0, 14.0, 8.0, Vector(x - 7.0, WB / 2.0 - 7.0, Z - 8.0))
    plate = plate.fuse(clamp.cut(Part.makeBox(12.2, 15.0, 10.2, Vector(x - 6.1, WB / 2.0 - 7.5, Z - 9.0))))
# Caster mount holes at the front.
for x in (-9.5, 9.5):
    plate = plate.cut(Part.makeCylinder(1.6, T + 2.0, Vector(x, -WB / 2.0, Z - 1.0)))
shape = plate.removeSplitter()
