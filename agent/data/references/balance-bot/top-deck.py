import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 120.0)
D = P.get("depth_mm", 60.0)
T = P.get("thickness_mm", 4.0)
Z = 45.0 - 21.2 + 180.0

# Top deck on the walls that carries the 3S pack high up, which slows the fall the robot has to catch.
deck = Part.makeBox(W, D, T, V(-W / 2.0, -D / 2.0, Z))
for x in (-50.0, 50.0):
    deck = deck.fuse(Part.makeBox(4.0, D, 10.0, V(x - 2.0, -D / 2.0, Z + T)))
shape = deck
