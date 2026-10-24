import FreeCAD
import Part

V = FreeCAD.Vector

R = P.get("radius_mm", 100.0)
T = P.get("thickness_mm", 4.0)
Z_MID = P.get("mid_z_mm", 86.0)
Z = P.get("z_mm", 132.0)

# Top plate carrying the lidar, on four 8 mm standoffs from the mid plate, with a rim so the lidar sees 360 degrees above it.
plate = Part.makeCylinder(R, T, V(0, 0, Z))
for x, y in ((60.0, 60.0), (-60.0, 60.0), (60.0, -60.0), (-60.0, -60.0)):
    plate = plate.fuse(Part.makeCylinder(4.0, Z - Z_MID, V(x, y, Z_MID)))
# Lidar seat: a 4 mm ring the 55.6 mm scanner drops into.
seat = Part.makeCylinder(31.0, 3.0, V(0, -10.0, Z + T)).cut(Part.makeCylinder(28.2, 3.0, V(0, -10.0, Z + T)))
plate = plate.fuse(seat)
shape = plate
