# Back rest of a desk phone stand: a plate leaning back at angle_deg from the table,
# braced by two triangular gussets. It stands on the base plate (its top at BASE_T)
# with its front face crossing the base top at Y0.
import math

PARAMS = {
    "width_mm": {"value": 70.0, "min": 50.0, "max": 120.0, "step": 1.0, "unit": "mm", "label": "Width", "group": "Back rest"},
    "support_length_mm": {"value": 95.0, "min": 60.0, "max": 160.0, "step": 1.0, "unit": "mm", "label": "Length", "group": "Back rest"},
    "thickness_mm": {"value": 5.0, "min": 3.0, "max": 10.0, "step": 0.5, "unit": "mm", "label": "Thickness", "group": "Back rest"},
    "angle_deg": {"value": 65.0, "min": 45.0, "max": 80.0, "step": 1.0, "unit": "deg", "label": "Lean angle", "group": "Back rest"},
}
W = P["width_mm"]
L = P["support_length_mm"]
T = P["thickness_mm"]
A = P["angle_deg"]
BASE_T = 5.0
Y0 = -10.0

lean = 90.0 - A
s, c = math.sin(math.radians(lean)), math.cos(math.radians(lean))
plate = Part.makeBox(W, T, L, Vector(-W / 2.0, 0, 0))
plate.rotate(Vector(0, 0, 0), Vector(1, 0, 0), -lean)
plate.translate(Vector(0, Y0, BASE_T))

reach = 0.7 * L
for x in (-W / 2.0 + 6.0, W / 2.0 - 12.0):
    y1 = Y0 + T * c
    y2 = y1 + reach * s
    z2 = BASE_T - T * s + reach * c
    outline = Part.makePolygon([Vector(x, y1, BASE_T), Vector(x, y2, BASE_T), Vector(x, y2, z2), Vector(x, y1, BASE_T)])
    plate = plate.fuse(Part.Face(outline).extrude(Vector(6.0, 0, 0)))

# Everything below the base top belongs to the base.
plate = plate.cut(Part.makeBox(W + 20.0, 400.0, 50.0, Vector(-W / 2.0 - 10.0, -200.0, BASE_T - 50.0)))
shape = plate.removeSplitter()
