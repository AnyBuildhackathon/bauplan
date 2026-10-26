# Base plate of a desk phone stand: a flat plate with a front lip the phone stands
# behind, and a cable slot through the lip. Units are mm, Z is up, -Y is the front.
# depth_mm runs from the front edge backwards, so a deeper base resists tipping back.
PARAMS = {
    "width_mm": {"value": 80.0, "min": 60.0, "max": 140.0, "step": 1.0, "unit": "mm", "label": "Width", "group": "Base plate"},
    "depth_mm": {"value": 60.0, "min": 40.0, "max": 160.0, "step": 1.0, "unit": "mm", "label": "Depth", "group": "Base plate"},
    "thickness_mm": {"value": 5.0, "min": 3.0, "max": 10.0, "step": 0.5, "unit": "mm", "label": "Thickness", "group": "Base plate"},
    "lip_height_mm": {"value": 12.0, "min": 6.0, "max": 25.0, "step": 0.5, "unit": "mm", "label": "Lip height", "group": "Front lip"},
}
W = P["width_mm"]
D = P["depth_mm"]
T = P["thickness_mm"]
LIP = P["lip_height_mm"]
FRONT = -25.0

plate = Part.makeBox(W, D, T, Vector(-W / 2.0, FRONT, 0))
lip = Part.makeBox(W, 5.0, T + LIP, Vector(-W / 2.0, FRONT, 0))
base = plate.fuse(lip)
# Charging cable slot through the lip and the plate front.
base = base.cut(Part.makeBox(14.0, 12.0, T + LIP + 2.0, Vector(-7.0, FRONT - 1.0, -1.0)))
shape = base.removeSplitter()
