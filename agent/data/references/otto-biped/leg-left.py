import FreeCAD
import Part

V = FreeCAD.Vector

SIDE = -1.0
FOOT_W = P.get("foot_width_mm", 32.0)
FOOT_L = P.get("foot_length_mm", 56.0)
FOOT_T = P.get("foot_mm", 4.0)
LEG_H = P.get("leg_height_mm", 30.0)
X = SIDE * P.get("stance_mm", 22.0)

# Foot plate on the table, turned by the ankle servo inside the leg.
foot = Part.makeBox(FOOT_W, FOOT_L, FOOT_T, V(X - FOOT_W / 2.0, -FOOT_L / 2.0, 0))
# Leg block above it with a pocket for the ankle SG90, lying along Y.
leg = Part.makeBox(22.0, 30.0, LEG_H, V(X - 11.0, -15.0, FOOT_T))
leg = leg.cut(Part.makeBox(12.6, 23.0, LEG_H - 6.0, V(X - 6.3, -11.5, FOOT_T + 3.0)))
# Hip horn boss on top that the hip servo turns.
leg = leg.fuse(Part.makeCylinder(6.0, 38.0 - FOOT_T - LEG_H, V(X, -5.5, FOOT_T + LEG_H)))
shape = foot.fuse(leg)
