"""Runs one generated part script inside freecadcmd and exports what it built.

The backend writes part_script.py and params.json into a fresh temp directory and
starts `freecadcmd part_harness.py` there with PAI_PART_DIR pointing at it. The
script sees Part, App (FreeCAD), Vector, math and P (the parameters, mm) and has
to leave a solid in `shape`, or several named solids in `parts`. Optional:
`colors` (name to hex), `materials` (name to material) and `reference` (names
that are shown but not printed, such as a bought servo).

Writes one STL per part, part.step (all printed parts), part.stl (all printed
parts) and result.json with volume and bounding box per part. Never raises:
every failure lands in result.json as `error` plus the traceback tail, so the
agent can read it and fix the script.
"""

import json
import os
import traceback

OUT = os.environ.get("PAI_PART_DIR", "")
ALLOWED_MODULES = {"FreeCAD", "Part", "math"}
SAFE_BUILTINS = (
    "abs all any bool dict enumerate float int isinstance len list max min "
    "pow range reversed round set sorted str sum tuple zip ValueError Exception print"
).split()


def _write(payload):
    with open(os.path.join(OUT, "result.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] not in ALLOWED_MODULES or level:
        raise ImportError("Only FreeCAD, Part and math can be imported in a part script, not " + name)
    return __import__(name, globals, locals, fromlist, level)


def _bbox(shape):
    box = shape.BoundBox
    return [round(v, 3) for v in (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)]


def _center(shape):
    """Volume centroid over the solids, the centre of mass for one uniform material."""

    total = 0.0
    sums = [0.0, 0.0, 0.0]
    for solid in shape.Solids:
        volume = float(solid.Volume)
        point = solid.CenterOfMass
        total += volume
        for axis, value in enumerate((point.x, point.y, point.z)):
            sums[axis] += value * volume
    return [round(value / total, 3) for value in sums] if total > 0 else None


def main():
    import builtins
    import math

    import FreeCAD as App
    import MeshPart
    import Part

    with open(os.path.join(OUT, "params.json"), encoding="utf-8") as handle:
        params = json.load(handle)
    with open(os.path.join(OUT, "part_script.py"), encoding="utf-8") as handle:
        source = handle.read()
    safe = {name: getattr(builtins, name) for name in SAFE_BUILTINS}
    safe["__import__"] = _guarded_import
    scope = {
        "__builtins__": safe,
        "__name__": "part_script",
        "App": App,
        "FreeCAD": App,
        "Part": Part,
        "Vector": App.Vector,
        "math": math,
        "P": dict(params),
    }
    exec(compile(source, "part_script.py", "exec"), scope)

    parts = scope.get("parts")
    if parts is None and scope.get("shape") is not None:
        parts = {"Part": scope["shape"]}
    if not isinstance(parts, dict) or not parts:
        raise ValueError("The script must set `shape` to a solid or `parts` to a dict of name -> solid.")
    reference = set(scope.get("reference") or [])
    colors = dict(scope.get("colors") or {})
    materials = dict(scope.get("materials") or {})

    rows = []
    printed = []
    for index, (name, shape) in enumerate(parts.items()):
        if not isinstance(shape, Part.Shape) or shape.isNull():
            raise ValueError("parts[" + repr(name) + "] is not a FreeCAD shape.")
        if not shape.Solids:
            raise ValueError("parts[" + repr(name) + "] has no solid. Extrude faces or use makeBox/makeCylinder.")
        if not shape.isValid():
            # Booleans sometimes leave tiny gaps; a repaired copy is usually a clean solid again.
            fixed = shape.copy()
            fixed.fix(1e-7, 1e-7, 1e-7)
            if fixed.isValid() and fixed.Solids:
                shape = fixed
        volume = float(shape.Volume)
        if volume <= 0:
            raise ValueError("parts[" + repr(name) + "] has zero volume.")
        stl_name = "part_" + str(index) + ".stl"
        scale = max(shape.BoundBox.DiagonalLength, 1.0)
        mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=max(0.02, scale / 800.0), AngularDeflection=0.35)
        mesh.write(os.path.join(OUT, stl_name))
        rows.append(
            {
                "name": str(name),
                "stl": stl_name,
                "volume_mm3": round(volume, 2),
                "bbox_mm": _bbox(shape),
                "valid": bool(shape.isValid()),
                "solids": len(shape.Solids),
                "com_mm": _center(shape),
                "reference": name in reference,
                "color": colors.get(name),
                "material": materials.get(name),
            }
        )
        if name not in reference:
            printed.append((shape, mesh))
    if not printed:
        raise ValueError("Every part is marked as reference, so nothing would be printed.")

    compound = Part.makeCompound([shape for shape, _mesh in printed])
    compound.exportStep(os.path.join(OUT, "part.step"))
    import Mesh

    merged = Mesh.Mesh()
    for _shape, mesh in printed:
        merged.addMesh(mesh)
    merged.write(os.path.join(OUT, "part.stl"))
    _write({"ok": True, "parts": rows, "bbox_mm": _bbox(compound), "volume_mm3": round(float(compound.Volume), 2)})


if OUT:
    try:
        main()
    except Exception as exc:  # The agent reads this and retries with a fixed script.
        tail = traceback.format_exc().strip().splitlines()[-6:]
        _write({"ok": False, "error": type(exc).__name__ + ": " + str(exc), "traceback": "\n".join(tail)})
