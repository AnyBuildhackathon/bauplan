"""Runs one generated part script inside freecadcmd and exports what it built.

The backend writes part_script.py and params.json into a fresh temp directory and
starts `freecadcmd part_harness.py` there with PAI_PART_DIR pointing at it. The
script sees Part, App (FreeCAD), Vector, math and P (the parameters, mm) and has
to leave a solid in `shape`, or several named solids in `parts`. Optional:
`colors` (name to hex), `materials` (name to material) and `reference` (names
that are shown but not printed, such as a bought servo). Templates that can be
simulated also set `joints`, `tool`, `collision` and `grip_surfaces` (plain
numbers, lists and dicts, read by pai_agent/mjcf_export.py).

A script that declares its parameters in PARAMS (pai_agent/part_params.py) also gets
contract.json, PARAMS as the backend read it. Its P then holds every declared value
and the fixed inputs: reading any other name fails, instead of quietly taking a
default, and PARAMS must still be as declared once the script has run.

Standard parts (pai_agent/fasteners) arrive as hardware.json and STEP files; the
script sees them as H (name to shape, hole tool, seat, direction and sizes).
After the script, every hole is cut into the printed bodies and each part's
keep-out is measured: `hardware` in result.json says how much material is left
in it, in which bodies, and whether the part touches one. The backend judges that.

Writes one STL per part, part.step (all printed parts), part.stl (all printed
parts) and result.json with volume and bounding box per part, plus those
simulation fields under `sim`. Each part also gets `lines`, the script lines
that build it, which a selection note from the studio cites. Never raises:
every failure lands in result.json as `error` plus the traceback tail, so the
agent can read it and fix the script.
"""

import json
import os
import traceback

OUT = os.environ.get("PAI_PART_DIR", "")
ALLOWED_MODULES = {"FreeCAD", "Part", "math"}
SIM_KEYS = ("joints", "tool", "collision", "grip_surfaces")
SAFE_BUILTINS = (
    "abs all any bool dict enumerate float int isinstance len list max min "
    "pow range reversed round set sorted str sum tuple zip ValueError Exception print"
).split()


def _write(payload):
    with open(os.path.join(OUT, "result.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


class UndeclaredParameter(KeyError):
    def __str__(self):
        return str(self.args[0])


class Declared(dict):
    """P of a script that declares PARAMS: a name it does not declare is an error, not a silent default."""

    def __missing__(self, key):
        raise UndeclaredParameter(str(key) + " is not declared in PARAMS; declare every parameter the script reads from P.")

    def get(self, key, default=None):
        return self[key]


def _load_contract():
    """PARAMS as the backend read it from the script, or None for a script without PARAMS."""

    path = os.path.join(OUT, "contract.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["params"]


def _plain(value):
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        return None


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name.split(".")[0] not in ALLOWED_MODULES or level:
        raise ImportError("Only FreeCAD, Part and math can be imported in a part script, not " + name)
    return __import__(name, globals, locals, fromlist, level)


def _bbox(shape):
    box = shape.BoundBox
    return [round(v, 3) for v in (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)]


def _load_hardware(Part):
    """(overlap limit in mm3, items) for the standard parts the backend built, with their shapes read."""

    path = os.path.join(OUT, "hardware.json")
    if not os.path.isfile(path):
        return 0.0, []
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    for item in data["items"]:
        item["shapes"] = {key: Part.read(os.path.join(OUT, name)) for key, name in item["files"].items() if name}
    return float(data["overlap_mm3"]), data["items"]


def _for_script(item, App):
    """What the script sees of one standard part; copies, so moving them cannot move the harness's own."""

    shapes = item["shapes"]
    seen = {
        "shape": shapes["shape"].copy(),
        "hole": shapes["hole"].copy() if "hole" in shapes else None,
        "seat": App.Vector(*item["seat"]),
        "direction": App.Vector(*item["direction"]),
    }
    if item["tip"]:
        seen["tip"] = App.Vector(*item["tip"])
    seen.update(item["numbers"])
    return seen


def _meet(a, b, gap=0.0):
    box = a.BoundBox
    box.enlarge(gap)
    return box.intersect(b.BoundBox)


def _fit_hardware(parts, bodies, items, limit):
    """Cuts every standard part's hole into the printed bodies (names in parts), then measures the material left in each keep-out.

    Returns one row per standard part: the overlap, the bodies it sits in and whether it touches one."""

    for item in items:
        hole = item["shapes"].get("hole")
        for name in bodies:
            if hole is not None and _meet(parts[name], hole):
                parts[name] = parts[name].cut(hole)
    rows = []
    for item in items:
        keep, shape = item["shapes"].get("keep"), item["shapes"]["shape"]
        inside, overlap, touches = [], 0.0, False
        for name in bodies:
            body = parts[name]
            if keep is not None and _meet(body, keep):
                volume = float(body.common(keep).Volume)
                if volume > limit:
                    inside.append(name)
                    overlap += volume
            if not touches and _meet(body, shape, 0.1):
                touches = body.distToShape(shape)[0] < 0.05
        rows.append({"name": item["name"], "overlap_mm3": round(overlap, 2), "inside": inside, "touches": touches})
    return rows


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


def _part_lines(source, names, shapes):
    """The script lines that build each part: {name: [[first, last], ...]}, read from the syntax tree.

    A part's lines are the entry that puts it into `parts` (or the `shape` it is), the statements before
    it that make or change the shapes that entry uses (`shapes`: the names holding a shape, or a list of
    them, after the run), back to where each was made from nothing, and the functions it calls. A part
    added under a computed name gets the statement that adds it. Comments right above a block count.
    """

    import ast

    body = ast.parse(source).body
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    funcs = {node.name: node for node in body if isinstance(node, defs[:2])}

    def walk(node):
        # Inside one statement, without the bodies of the functions and classes it defines.
        stack = [node]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(child for child in ast.iter_child_nodes(item) if not isinstance(child, (*defs, ast.Lambda)))

    def span(node):
        return [node.lineno, node.end_lineno or node.lineno]

    def reads(node):
        return {item.id for item in walk(node) if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)}

    def writes(stmt):
        out = set()
        for item in walk(stmt):
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
                out.add(item.id)
            elif isinstance(item, ast.Expr) and isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Attribute) and isinstance(item.value.func.value, ast.Name):
                # `servo.translate(...)` changes the shape in place.
                out.add(item.value.func.value.id)
        return out

    def fresh(stmt, name):
        return isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets) and name not in reads(stmt.value)

    def called(node, seen):
        # The script's own functions a node calls, and the ones those call, each once.
        out = []
        for item in walk(node):
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id in funcs and item.func.id not in seen:
                seen.add(item.func.id)
                out += [span(funcs[item.func.id])] + called(funcs[item.func.id], seen)
        return out

    def same_part(value, key):
        # `parts["Palm"] = parts["Palm"].cut(slot)` builds on the entry before it.
        return any(
            isinstance(item, ast.Subscript) and isinstance(item.value, ast.Name) and item.value.id == "parts" and isinstance(item.slice, ast.Constant) and item.slice.value == key
            for item in walk(value)
        )

    # Every place a part name gets its value, in order: (index of the top-level statement, the lines, the value).
    found, computed = {}, []
    for index, stmt in enumerate(body):
        if isinstance(stmt, defs):
            continue
        for item in walk(stmt):
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "parts":
                        if not isinstance(item.value, ast.Dict):
                            computed.append(span(stmt))
                            continue
                        for key, value in zip(item.value.keys, item.value.values):
                            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                                found.setdefault(key.value, []).append((index, [key.lineno, value.end_lineno or value.lineno], value))
                            elif key is not None:
                                computed.append(span(stmt))
                    elif isinstance(target, ast.Name) and target.id == "shape":
                        found.setdefault("Part", []).append((index, span(item), item.value))
                    elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == "parts":
                        if isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                            found.setdefault(target.slice.value, []).append((index, span(stmt), item.value))
                        else:
                            computed.append(span(stmt))
            elif isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and item.func.attr == "update" and isinstance(item.func.value, ast.Name) and item.func.value.id == "parts":
                for kw in item.keywords:
                    if kw.arg:
                        found.setdefault(kw.arg, []).append((index, span(stmt), kw.value))
                for arg in item.args:
                    pairs = zip(arg.keys, arg.values) if isinstance(arg, ast.Dict) else []
                    for key, value in pairs:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            found.setdefault(key.value, []).append((index, span(stmt), value))
                    if not isinstance(arg, ast.Dict):
                        computed.append(span(stmt))

    lines = source.splitlines()
    out = {}
    for name in names:
        entries = found.get(name)
        if not entries:
            if computed:
                out[name] = [list(r) for r in computed]
            continue
        ranges, seen, done = [], set(), set()
        todo = []
        for index, entry, value in reversed(entries):
            ranges += [entry] + called(value, seen)
            todo += [(needed, index) for needed in reads(value) & shapes]
            if not same_part(value, name):
                break
        while todo:
            needed, index = todo.pop()
            if needed in done:
                continue
            done.add(needed)
            for before in range(index - 1, -1, -1):
                stmt = body[before]
                if isinstance(stmt, defs) or needed not in writes(stmt):
                    continue
                ranges += [span(stmt)] + called(stmt, seen)
                # What this statement used, as it stood there.
                todo += [(other, before) for other in (reads(stmt) & shapes) - done]
                if fresh(stmt, needed):
                    break
        merged = []
        for first, last in sorted(ranges):
            # A comment right above a block belongs to it.
            while first > 1 and lines[first - 2].strip().startswith("#"):
                first -= 1
            # Blocks with only blank lines between them read as one range.
            if merged and all(not text.strip() for text in lines[merged[-1][1] : first - 1]):
                merged[-1][1] = max(merged[-1][1], last)
            else:
                merged.append([first, last])
        out[name] = merged
    return out


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
    limit, hardware = _load_hardware(Part)
    contract = _load_contract()
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
        "P": dict(params) if contract is None else Declared(params),
        "H": {item["name"]: _for_script(item, App) for item in hardware},
    }
    exec(compile(source, "part_script.py", "exec"), scope)
    if contract is not None and _plain(scope.get("PARAMS")) != contract:
        raise ValueError("PARAMS changed while the script ran: declare it once at the top as plain data and leave it as it is.")

    parts = scope.get("parts")
    if parts is None and scope.get("shape") is not None:
        parts = {"Part": scope["shape"]}
    if not isinstance(parts, dict) or not parts:
        raise ValueError("The script must set `shape` to a solid or `parts` to a dict of name -> solid.")
    reference = set(scope.get("reference") or [])
    colors = dict(scope.get("colors") or {})
    materials = dict(scope.get("materials") or {})
    taken = sorted(set(parts) & {item["name"] for item in hardware})
    if taken:
        raise ValueError("`parts` uses the name of a standard part in H (" + ", ".join(repr(name) for name in taken) + "); name it differently.")
    # Anything that is not a shape fails below with its own message.
    bodies = [name for name, shape in parts.items() if name not in reference and isinstance(shape, Part.Shape) and not shape.isNull()]
    fitted = _fit_hardware(parts, bodies, hardware, limit) if hardware else []
    try:
        held = {key for key, value in scope.items() if isinstance(value, Part.Shape) or (isinstance(value, (list, tuple)) and value and all(isinstance(v, Part.Shape) for v in value))}
        lines = _part_lines(source, [str(name) for name in parts], held)
    except Exception:  # The lines are a pointer for notes; a script they cannot read still builds.
        lines = {}

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
                "lines": lines.get(str(name)),
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
    sim = {}
    for key in SIM_KEYS:
        if scope.get(key) is None:
            continue
        try:
            sim[key] = json.loads(json.dumps(scope[key]))
        except (TypeError, ValueError) as exc:
            raise ValueError("`" + key + "` must hold only numbers, strings, lists and dicts.") from exc
    extra = {"hardware": fitted} if hardware else {}
    _write({"ok": True, "parts": rows, "bbox_mm": _bbox(compound), "volume_mm3": round(float(compound.Volume), 2), **({"sim": sim} if sim else {}), **extra})


if OUT:
    try:
        main()
    except Exception as exc:  # The agent reads this and retries with a fixed script.
        tail = traceback.format_exc().strip().splitlines()[-6:]
        # The script's own line, also when the error is raised deeper down, in P or in FreeCAD.
        lines = [frame.lineno for frame in traceback.extract_tb(exc.__traceback__) if frame.filename == "part_script.py"]
        where = " (part_script.py line " + str(lines[-1]) + ")" if lines else ""
        _write({"ok": False, "error": type(exc).__name__ + ": " + str(exc) + where, "traceback": "\n".join(tail)})
