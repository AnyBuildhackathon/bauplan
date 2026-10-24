import FreeCAD
import Part

V = FreeCAD.Vector

L = P.get("length_mm", 120.0)
D = P.get("depth_mm", 50.0)
T = P.get("plate_mm", 5.0)
AXLE_Z = 45.0

# Floor plate under the two Nema17 motors with an end flange per motor that its four M3 screws hold.
mount = Part.makeBox(L, D, T, V(-L / 2.0, -D / 2.0, AXLE_Z - 21.2 - T))
for x in (L / 2.0 - 4.0, -L / 2.0):
    flange = Part.makeBox(4.0, D, 46.0, V(x, -D / 2.0, AXLE_Z - 21.2 - T))
    flange = flange.cut(Part.makeCylinder(11.5, 6.0, V(x - 1, 0, AXLE_Z), V(1, 0, 0)))
    mount = mount.fuse(flange)
shape = mount
