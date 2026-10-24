import FreeCAD
import Part

V = FreeCAD.Vector

SPAN = P.get("span_mm", 170.0)
BAR_W = P.get("bar_width_mm", 10.0)
BAR_T = P.get("bar_thickness_mm", 8.0)
POST_H = 38.0
Y0 = -80.0 - BAR_W

# Perch bar in front of the tray on two posts, so birds sit in the camera's view.
bar = Part.makeBox(SPAN + 2 * 8.0, BAR_W, BAR_T, V(-SPAN / 2.0 - 8.0, Y0, POST_H - BAR_T))
left = Part.makeBox(8.0, BAR_W, POST_H, V(-SPAN / 2.0 - 8.0, Y0, 0))
right = Part.makeBox(8.0, BAR_W, POST_H, V(SPAN / 2.0, Y0, 0))
# A tab on each post reaches over the tray lip and holds the perch against the tray.
tabs = [Part.makeBox(8.0, BAR_W + 4.0, 3.0, V(x, Y0, 18.0)) for x in (-SPAN / 2.0 - 8.0, SPAN / 2.0)]
shape = bar.fuse(left).fuse(right).fuse(tabs[0]).fuse(tabs[1])
