import FreeCAD
import Part

V = FreeCAD.Vector

R = P.get("radius_mm", 32.0)
PLATE = P.get("plate_mm", 5.0)
CHEEK = P.get("cheek_mm", 4.0)
SHOULDER_Z = P.get("shoulder_z_mm", 64.0)
Z0 = 28.0

# Turntable on the base servo with two cheeks that carry the shoulder and elbow servos.
turret = Part.makeCylinder(R, PLATE, V(0, 0, Z0))
for x in (-17.0, 17.0 - CHEEK):
    cheek = Part.makeBox(CHEEK, 34.0, SHOULDER_Z + 8.0 - Z0 - PLATE, V(x, -17.0, Z0 + PLATE))
    cheek = cheek.cut(Part.makeCylinder(3.0, CHEEK + 2, V(x - 1, 0, SHOULDER_Z), V(1, 0, 0)))
    turret = turret.fuse(cheek)
shape = turret
