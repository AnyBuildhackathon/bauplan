import FreeCAD
import Part

V = FreeCAD.Vector

R = P.get("radius_mm", 100.0)
T = P.get("thickness_mm", 4.0)
AXLE_Z = P.get("axle_z_mm", 42.0)
Z0 = AXLE_Z - 18.5 - T

# Round bottom plate under the two 37 mm gear motors, with a clamp saddle per motor and slots for the wheels.
plate = Part.makeCylinder(R, T, V(0, 0, Z0))
for x in (-56.0, 56.0):
    saddle = Part.makeBox(30.0, 45.0, 22.0, V(x - 15.0, -22.5, Z0 + T))
    saddle = saddle.cut(Part.makeCylinder(18.6, 32.0, V(x - 16.0, 0, AXLE_Z), V(1, 0, 0)))
    plate = plate.fuse(saddle)
# Cable hole in the middle and four holes for the standoffs of the mid plate.
plate = plate.cut(Part.makeCylinder(10.0, T + 2, V(0, -45.0, Z0 - 1)))
for x, y in ((70.0, 45.0), (-70.0, 45.0), (70.0, -45.0), (-70.0, -45.0)):
    plate = plate.cut(Part.makeCylinder(1.7, T + 2, V(x, y, Z0 - 1)))
shape = plate
