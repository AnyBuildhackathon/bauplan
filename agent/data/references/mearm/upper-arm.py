import FreeCAD
import Part

V = FreeCAD.Vector

L = P.get("length_mm", 80.0)
W = P.get("width_mm", 14.0)
T = P.get("thickness_mm", 6.0)
ANGLE = P.get("angle_deg", 45.0)
SHOULDER_Z = 64.0

# Upper arm from the shoulder, raised ANGLE degrees forwards (+Y).
arm = Part.makeBox(W, L + 10.0, T, V(-W / 2.0, -5.0, SHOULDER_Z - T / 2.0))
arm = arm.cut(Part.makeCylinder(2.0, T + 2, V(0, 0, SHOULDER_Z - T / 2.0 - 1)))
arm = arm.cut(Part.makeCylinder(2.0, T + 2, V(0, L, SHOULDER_Z - T / 2.0 - 1)))
arm.rotate(V(0, 0, SHOULDER_Z), V(1, 0, 0), ANGLE)
shape = arm
