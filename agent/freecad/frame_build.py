"""Headless FreeCAD frame. Run by freecadcmd, not by the agent interpreter."""

import json
import os
import sys

DENSITY = 1.24 / 1000.0


def main() -> None:
    params_path = os.environ.get("PAI_FREECAD_PARAMS") or sys.argv[-2]
    out_dir = os.environ.get("PAI_FREECAD_OUT") or sys.argv[-1]
    params = json.loads(open(params_path, encoding="utf-8").read())
    os.makedirs(out_dir, exist_ok=True)
    try:
        mass_g = build(params, out_dir)
    except Exception as exc:
        _write(out_dir, {"ok": False, "error": str(exc)})
        raise
    _write(out_dir, {"ok": True, "mass_g": round(mass_g, 2)})


def build(params: dict, out_dir: str) -> float:
    import FreeCAD as App
    import Mesh
    import Part

    arm = float(params["arm_length_mm"])
    thick = float(params["thickness_mm"])
    bolt = float(params["motor_spacing_mm"]) / 2.0
    hub = Part.makeCylinder(20, thick)
    shape = hub
    for index in range(4):
        import math

        box = Part.makeBox(arm + 6, 6, thick)
        box.translate(App.Vector(0, -3, 0))
        box.rotate(App.Vector(0, 0, 0), App.Vector(0, 0, 1), index * 90)
        shape = shape.fuse(box)
        radians = math.radians(index * 90)
        cx = arm * math.cos(radians)
        cy = arm * math.sin(radians)
        pad = Part.makeCylinder(6, thick, App.Vector(cx, cy, 0))
        shape = shape.fuse(pad)
    holes = [(0, 0, 2.2)]
    for sign_x in (-1, 1):
        for sign_y in (-1, 1):
            holes.append((13 * sign_x, 13 * sign_y, 1.1))
    for index in range(4):
        import math

        radians = math.radians(index * 90)
        cx = arm * math.cos(radians)
        cy = arm * math.sin(radians)
        holes.append((cx, cy, 1.0))
        for hole_index in range(3):
            angle = math.radians(index * 90 + hole_index * 120)
            holes.append((cx + bolt * math.cos(angle), cy + bolt * math.sin(angle), 0.8))
    for x_mm, y_mm, radius in holes:
        cutter = Part.makeCylinder(radius, thick + 2, App.Vector(x_mm, y_mm, -1))
        shape = shape.cut(cutter)

    doc = App.newDocument("whoop")
    feature = doc.addObject("Part::Feature", "Rahmen")
    feature.Shape = shape
    doc.recompute()
    doc.saveAs(os.path.join(out_dir, "frame.FCStd"))
    Part.export([feature], os.path.join(out_dir, "frame.step"))
    Mesh.export([feature], os.path.join(out_dir, "frame.stl"))
    glb_path = os.path.join(out_dir, "frame.glb")
    try:
        import Import

        Import.export([feature], glb_path)
    except Exception:
        pass
    return float(feature.Shape.Volume) * DENSITY


def _write(out_dir: str, payload: dict) -> None:
    with open(os.path.join(out_dir, "freecad_result.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


if os.environ.get("PAI_FREECAD_OUT"):
    main()
