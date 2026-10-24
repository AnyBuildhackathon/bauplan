import FreeCAD
import Part

V = FreeCAD.Vector

L = P.get("length_mm", 116.0)
W = P.get("width_mm", 30.0)
T = P.get("thickness_mm", 24.0)
ANGLE = P.get("angle_deg", 30.0)
AXIS_Z = 90.0

# Hollow upper arm from the shoulder axis to the elbow servo, raised ANGLE degrees forwards (+Y).
arm = Part.makeBox(W, L + 24.0, T, V(-W / 2.0, -12.0, AXIS_Z - T / 2.0))
arm = arm.cut(Part.makeBox(W - 6.0, L - 40.0, T - 6.0, V(-W / 2.0 + 3.0, 20.0, AXIS_Z - T / 2.0 + 3.0)))
arm.rotate(V(0, 0, AXIS_Z), V(1, 0, 0), ANGLE)
shape = arm
