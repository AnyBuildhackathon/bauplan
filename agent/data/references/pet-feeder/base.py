import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 160.0)
D = P.get("depth_mm", 140.0)
H = P.get("height_mm", 60.0)
WALL = P.get("wall_mm", 2.2)
TUBE_R = P.get("tube_bore_mm", 44.0) / 2.0
AXIS_Z = 35.0
SPOUT = 25.0

# Closed housing for the stepper, the driver and the ESP32.
outer = Part.makeBox(W, D, H, V(-W / 2.0, -D / 2.0, 0))
inner = Part.makeBox(W - 2 * WALL, D - 2 * WALL, H - 2 * WALL, V(-W / 2.0 + WALL, -D / 2.0 + WALL, WALL))
base = outer.cut(inner)
# Auger tube along X from inside the housing out through the +X wall as a spout.
x0 = -55.0
length = W / 2.0 - x0 + SPOUT
tube = Part.makeCylinder(TUBE_R + WALL, length, V(x0, 0, AXIS_Z), V(1, 0, 0))
# Short chute from the top plate down into the tube.
chute = Part.makeCylinder(20.0 + WALL, H - AXIS_Z, V(0, 0, AXIS_Z))
base = base.fuse(tube).fuse(chute)
base = base.cut(Part.makeCylinder(TUBE_R, length - WALL, V(x0 + WALL, 0, AXIS_Z), V(1, 0, 0)))
base = base.cut(Part.makeCylinder(20.0, H, V(0, 0, AXIS_Z)))
# Food falls out of the spout end through a slot underneath.
base = base.cut(Part.makeBox(SPOUT - 5.0, 30.0, TUBE_R + WALL, V(W / 2.0 + 3.0, -15.0, AXIS_Z - TUBE_R - WALL - 1)))
# Shaft hole for the stepper coupler and a USB cable hole in the back wall.
base = base.cut(Part.makeCylinder(5.0, WALL + 2, V(x0 - 1, 0, AXIS_Z), V(1, 0, 0)))
base = base.cut(Part.makeBox(12.0, WALL + 2, 8.0, V(-W / 2.0 + 20.0, D / 2.0 - WALL - 1, 10.0)))
shape = base
