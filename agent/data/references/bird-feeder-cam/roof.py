import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 130.0)
D = P.get("depth_mm", 90.0)
T = P.get("thickness_mm", 3.0)
Z0 = 63.0

# Lid with an overhang that keeps rain off the box, the vents and the lens window.
roof = Part.makeBox(W, D, T, V(-W / 2.0, 0.0, Z0))
# Rim that locates the lid on the box walls.
rim = Part.makeBox(110.0 - 5.0, 70.0 - 5.0, 3.0, V(-52.5, 12.5, Z0 - 3.0))
rim = rim.cut(Part.makeBox(110.0 - 9.0, 70.0 - 9.0, 5.0, V(-50.5, 14.5, Z0 - 4.0)))
shape = roof.fuse(rim)
