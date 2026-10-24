import FreeCAD
import Part

V = FreeCAD.Vector

CAM_W = P.get("camera_width_mm", 24.0)
CAM_H = P.get("camera_height_mm", 48.0)
WALL = P.get("wall_mm", 2.0)
AXIS_Z = 80.0
GAP = 22.0 - 3.0

# Cradle for the M5Stack Timer Camera standing upright, lens towards -Y,
# with axle stubs on the tilt axis that reach into the yoke uprights.
half = CAM_W / 2.0 + WALL + 2.0
z0 = AXIS_Z - CAM_H / 2.0 - WALL
back = Part.makeBox(2 * half, WALL + 1, CAM_H + 2 * WALL, V(-half, 5.5, z0))
left = Part.makeBox(half - CAM_W / 2.0, 15.0, CAM_H + 2 * WALL, V(-half, -8.0, z0))
right = Part.makeBox(half - CAM_W / 2.0, 15.0, CAM_H + 2 * WALL, V(CAM_W / 2.0, -8.0, z0))
ledge = Part.makeBox(2 * half, 17.0, WALL, V(-half, -10.0, z0))
head = back.fuse(left).fuse(right).fuse(ledge)
head = head.fuse(Part.makeCylinder(3.0, GAP - half + 3.0, V(-GAP - 3.0, 0, AXIS_Z), V(1, 0, 0)))
head = head.fuse(Part.makeCylinder(3.0, GAP - half + 3.0, V(half, 0, AXIS_Z), V(1, 0, 0)))
# Window for the USB-C port at the bottom of the camera.
head = head.cut(Part.makeBox(12.0, 10.0, WALL + 2, V(-6.0, -6.0, z0 - 1)))
shape = head
