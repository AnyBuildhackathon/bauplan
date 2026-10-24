import FreeCAD
import Part

V = FreeCAD.Vector

R = P.get("radius_mm", 28.0)
DISC = P.get("disc_mm", 6.0)
CHEEK = P.get("cheek_mm", 6.0)
AXIS_Z = P.get("shoulder_z_mm", 90.0)
Z0 = 46.0

# Turntable on the base servo horn with two cheeks that carry the shoulder STS3215.
part = Part.makeCylinder(R, DISC, V(0, 0, Z0))
for x in (-25.0, 25.0 - CHEEK):
    cheek = Part.makeBox(CHEEK, 40.0, AXIS_Z + 14.0 - Z0 - DISC, V(x, -20.0, Z0 + DISC))
    cheek = cheek.cut(Part.makeCylinder(4.0, CHEEK + 2, V(x - 1, 0, AXIS_Z), V(1, 0, 0)))
    part = part.fuse(cheek)
shape = part
