import FreeCAD
import Part
import math

V = FreeCAD.Vector

THIGH = P.get("thigh_mm", 50.0)
SHIN = P.get("shin_mm", 50.0)
ANGLE = P.get("knee_angle_deg", 30.0)
X = P.get("hip_x_mm", 47.0)
Y = 60.0
HIP_Z = 6.0 + (THIGH + SHIN) * math.cos(math.radians(ANGLE))

# Two legs, left and right: the thigh swings back from the hip, the shin forward to the foot pad.
legs = None
for x in (-X, X):
    boss = Part.makeCylinder(9.0, 7.0, V(x - 3.5 if x > 0 else x + 3.5, Y, HIP_Z), V(-1 if x > 0 else 1, 0, 0))
    thigh = Part.makeBox(10.0, 14.0, THIGH + 7.0, V(x - 5.0, Y - 7.0, HIP_Z - THIGH))
    thigh.rotate(V(x, Y, HIP_Z), V(1, 0, 0), -ANGLE)
    knee_y = Y - THIGH * math.sin(math.radians(ANGLE))
    knee_z = HIP_Z - THIGH * math.cos(math.radians(ANGLE))
    shin = Part.makeBox(8.0, 12.0, SHIN + 6.0, V(x - 4.0, knee_y - 6.0, knee_z - SHIN))
    shin.rotate(V(x, knee_y, knee_z), V(1, 0, 0), ANGLE)
    foot = Part.makeBox(14.0, 14.0, 6.0, V(x - 7.0, Y - 7.0, 0))
    leg = boss.fuse(thigh).fuse(shin).fuse(foot)
    legs = leg if legs is None else legs.fuse(leg)
shape = legs
