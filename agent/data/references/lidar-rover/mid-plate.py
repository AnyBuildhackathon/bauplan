import FreeCAD
import Part

V = FreeCAD.Vector

R = P.get("radius_mm", 100.0)
T = P.get("thickness_mm", 4.0)
Z_BOTTOM = P.get("bottom_z_mm", 23.5)
Z = P.get("z_mm", 82.0)

# Mid plate for the Raspberry Pi and the 5 V step-down, on four 8 mm standoffs from the bottom plate.
plate = Part.makeCylinder(R, T, V(0, 0, Z))
for x, y in ((70.0, 45.0), (-70.0, 45.0), (70.0, -45.0), (-70.0, -45.0)):
    plate = plate.fuse(Part.makeCylinder(4.0, Z - Z_BOTTOM, V(x, y, Z_BOTTOM)))
plate = plate.cut(Part.makeCylinder(12.0, T + 2, V(0, 60.0, Z - 1)))
shape = plate
