import math
import FreeCAD
import Part

V = FreeCAD.Vector

D = P.get("diameter_mm", 150.0)
T = P.get("thickness_mm", 5.0)
S = P.get("socket_mm", 16.0)
SOCKET_DEPTH = P.get("socket_depth_mm", 4.0)
FOOT_D = P.get("foot_recess_diameter_mm", 8.0)
FOOT_DEPTH = P.get("foot_recess_depth_mm", 1.0)
FOOT_R = P.get("foot_radius_mm", 60.0)

base = Part.makeCylinder(D / 2.0, T, V(0, 0, 0))

# Blind socket in the top face for the neck
base = base.cut(Part.makeCylinder(S / 2.0, SOCKET_DEPTH, V(0, 0, T - SOCKET_DEPTH)))

# Four rubber-foot recesses on the underside
for i in range(4):
    a = math.radians(45 + 90 * i)
    x = FOOT_R * math.cos(a)
    y = FOOT_R * math.sin(a)
    base = base.cut(Part.makeCylinder(FOOT_D / 2.0, FOOT_DEPTH, V(x, y, 0)))

shape = base
