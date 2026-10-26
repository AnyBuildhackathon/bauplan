"""`cad_view`: Mechanic looks at his own model.

It renders the build as it stands, from the GLB the Model tab shows: a product's assembly, the
drone, or the last generated part. `view_render.py` draws it with VTK offscreen in its own
process, and the picture goes back to Claude next to the JSON, which says which number marks
which part, the grid size and what was hidden or cut. So Mechanic catches a part that floats,
sits crooked or inside another, a hole in the wrong place or a missing part before anyone else
sees it.

On the Messages API the picture is an image block in the tool result (`api_content`), on the
Claude Code subscription MCP image content through the in-process server (`mcp_content`); the
JSON text never carries it. The newest picture also stays in the session as `cad-view.png`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from pai_agent.context import Ctx
from pai_agent.paths import REPO_ROOT
from pai_agent.view_render import HEIGHT, WIDTH, mesh_nodes, read_glb

VIEWS = ("sheet", "iso", "iso_below", "front", "back", "left", "right", "top", "bottom")
SHEET = ("iso", "front", "right", "top")
COLORS = ("parts", "overhang", "stress")
TIMEOUT_S = 90
# The tool result key that holds the base64 PNG for the model; it never goes into the JSON text.
IMAGE = "_png"
FILE = "cad-view.png"

SCHEMA = {
    "name": "cad_view",
    "description": (
        "Look at your model: renders the build as it stands (a product's assembly, the drone, or the last generated part) from the 3D model "
        "the Model tab shows and returns the picture, a number on every part (parts says which is which) and a grid for scale. "
        "Use it after building and assembling to catch what the numbers miss: a part that floats, sits crooked or inside another, "
        "a hole or pocket in the wrong place, a missing part. "
        "view: sheet (the default: iso, front, right and top in one picture), iso, iso_below, front, back, left, right, top or bottom, "
        "as in a drawing (right is the side on your right when you face the front); direction [x, y, z] looks from that direction instead. "
        "Coordinates: mm, Z up; -Y is a product's front, +Y the drone's nose. "
        "only shows just these parts, hide leaves them out (part names or ids; a part takes what sits on it along, as a motor its propeller). "
        "section {axis, at_mm} cuts the model there and takes away the half facing the camera; cut faces show in a darker shade of their part, "
        "so walls, holes and pockets read. color overhang paints red what hangs over more than 45 degrees when printed (in print_prep's pose, "
        "else as modelled; overhangs face down, so it looks from iso_below unless you pick a view); color stress shows each fem_check result, "
        "the other parts see-through."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "view": {"type": "string", "enum": list(VIEWS)},
            "direction": {"type": "array", "items": {"type": "number"}, "description": "Look from this direction: [x, y, z] in the build's frame."},
            "only": {"type": "array", "items": {"type": "string"}, "description": "Part names or ids to show alone."},
            "hide": {"type": "array", "items": {"type": "string"}, "description": "Part names or ids to leave out."},
            "section": {
                "type": "object",
                "properties": {"axis": {"type": "string", "enum": ["x", "y", "z"]}, "at_mm": {"type": "number"}},
                "required": ["axis", "at_mm"],
            },
            "color": {"type": "string", "enum": list(COLORS)},
            "numbers": {"type": "boolean", "description": "false leaves the part numbers off."},
        },
    },
}

# Plain names for part colours, so Mechanic can say "the orange back rest".
_COLOUR_NAMES = {
    "white": (240, 241, 244),
    "light grey": (201, 204, 211),
    "grey": (140, 145, 155),
    "dark grey": (72, 75, 82),
    "black": (30, 31, 35),
    "red": (214, 50, 50),
    "orange": (255, 138, 61),
    "yellow": (242, 201, 76),
    "green": (64, 180, 96),
    "teal": (46, 211, 174),
    "blue": (59, 91, 219),
    "light blue": (110, 170, 240),
    "purple": (139, 124, 246),
    "pink": (236, 120, 180),
    "brown": (140, 92, 54),
}


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message[:160]}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def colour_name(hex_code: str) -> str:
    code = hex_code.lstrip("#")
    rgb = np.array([int(code[i : i + 2], 16) for i in (0, 2, 4)], dtype=float)
    name = min(_COLOUR_NAMES, key=lambda key: float(np.sum((rgb - np.array(_COLOUR_NAMES[key])) ** 2)))
    return name + (" see-through" if len(code) == 8 and int(code[6:8], 16) < 250 else "")


def api_content(result: dict) -> str | list[dict]:
    """A tool result as Messages API tool_result content: its JSON, and the picture as an image block when it has one."""

    text = json.dumps({k: v for k, v in result.items() if k != IMAGE}, ensure_ascii=False, default=str)
    if not result.get(IMAGE):
        return text
    return [{"type": "text", "text": text}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": result[IMAGE]}}]


def mcp_content(result: dict) -> list[dict]:
    """The same as MCP tool content for the subscription's in-process server: the JSON text, then the picture."""

    content = [{"type": "text", "text": json.dumps({k: v for k, v in result.items() if k != IMAGE}, ensure_ascii=False, default=str)}]
    if result.get(IMAGE):
        content.append({"type": "image", "data": result[IMAGE], "mimeType": "image/png"})
    return content


def drop_old_images(messages: list[dict], keep: int = 2) -> None:
    """Keeps the newest `keep` pictures in a Messages history and turns older ones into a line of text.

    Every round sends the whole history again, so old pictures would cost tokens on every round and
    a long session would run into the API's image limit.
    """

    seen = 0
    for message in reversed(messages):
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, list):
            continue
        for block in reversed(content):
            if not isinstance(block, dict) or block.get("type") != "tool_result" or not isinstance(block.get("content"), list):
                continue
            parts = block["content"]
            if not any(isinstance(p, dict) and p.get("type") == "image" for p in parts):
                continue
            seen += 1
            if seen > keep:
                block["content"] = [p for p in parts if not (isinstance(p, dict) and p.get("type") == "image")] + [
                    {"type": "text", "text": "(An older picture was shown here; call cad_view to look again.)"}
                ]


async def _source(ctx: Ctx) -> dict:
    """The GLB of the build as it stands and how to read it; raises ValueError when there is no model yet."""

    state = ctx.state
    directory = Path(state.directory)
    glb = directory / "frame.glb"
    if state.product == "drone" and (glb.is_file() or not state.part):
        if not glb.is_file():
            raise ValueError("No model of the drone yet: run cad_frame first.")
        document = read_glb(glb)[0]
        # FreeCAD's and CadQuery's drone GLBs hang off a "drone" node in glTF's axes; a bare frame STL turned GLB is in mm.
        gltf = any(node.get("name") == "drone" for node in document.get("nodes", []))
        return {"glb": glb, "axes": "gltf" if gltf else "zup_mm", "front": [0.0, 1.0, 0.0], "label": "the drone", "document": document, "frame": "mm, Z up, the nose is +Y"}
    if state.product == "generic" and state.spec:
        from pai_agent.tools.product import ensure_assembly

        assembly = await ensure_assembly(ctx)
        glb = directory / assembly["glb"]
        if not glb.is_file():
            raise ValueError("The assembly's 3D model is missing: run assemble again.")
        return {"glb": glb, "axes": "zup_mm", "front": [0.0, -1.0, 0.0], "label": "the " + state.spec["name"], "document": read_glb(glb)[0], "frame": "mm, Z up, -Y is the front"}
    if state.part and state.stl_path:
        glb = (REPO_ROOT / state.stl_path).with_suffix(".glb")
        if glb.is_file():
            return {"glb": glb, "axes": "zup_mm", "front": [0.0, -1.0, 0.0], "label": state.part["name"], "document": read_glb(glb)[0], "frame": "mm, Z up, -Y is the front"}
    raise ValueError("No model yet: build it first (product_spec and cad_part, cad_frame for the drone, or cad_part for one part).")


def _aliases(state) -> dict[str, list[str]]:
    """Other names each GLB node answers to: a product part's spec id, its kind; a standard part also its printed part's id."""

    if state.product != "generic" or not state.spec or not state.assembly:
        return {}
    kinds = {part["id"]: part["kind"] for part in state.spec["parts"]}
    out: dict[str, list[str]] = {}
    for body in state.assembly.get("bodies", []):
        # A screw or insert (kind hardware) goes along with the printed part that holds it.
        out.setdefault(body["name"], []).extend([body["part_id"], kinds.get(body["part_id"], body["kind"]), body.get("holder", "")])
    return out


def _matches(query: str, keys: list[str]) -> bool:
    wanted = _norm(query)
    return bool(wanted) and any(_norm(key) == wanted for key in keys if key)


def _select(nodes: list[dict], aliases: dict[str, list[str]], only: list[str], hide: list[str]) -> tuple[list[dict], list[str]]:
    """The nodes to draw and the names that matched nothing. A name selects a node or what it sits in;
    without an exact match it may start a name ("motor" for all four), or be its plural ("motors")."""

    def keys(node: dict) -> list[str]:
        return [node["name"], *node["within"], *aliases.get(node["name"], [])]

    def resolve(query: str) -> set[int]:
        exact = {node["index"] for node in nodes if _matches(query, keys(node))}
        if exact:
            return exact
        stem = _norm(query)
        for prefix in (stem, stem[:-1] if stem.endswith("s") else ""):
            if prefix:
                found = {node["index"] for node in nodes if any(_norm(key).startswith(prefix) for key in keys(node))}
                if found:
                    return found
        return set()

    unknown = []
    shown = {node["index"] for node in nodes}
    if only:
        shown = set()
        for query in only:
            found = resolve(query)
            shown |= found
            if not found:
                unknown.append(query)
    for query in hide:
        found = resolve(query)
        shown -= found
        if not found:
            unknown.append(query)
    return [node for node in nodes if node["index"] in shown], unknown


def _print_poses(state, names: list[str]) -> tuple[dict[str, list[float]], dict[str, str]]:
    """The print direction of each printed part's nodes in the build's frame, and the pose it comes from."""

    from pai_agent.assembly import rotation
    from pai_agent.tools.fem import _build_axis

    plan = {row.get("id"): str(row.get("orientation")) for row in (state.print_plan or {}).get("parts", [])}
    up = [0.0, 0.0, 1.0]
    directions: dict[str, list[float]] = {}
    poses: dict[str, str] = {}
    if state.product == "generic" and state.spec and state.assembly:
        printed = {part["id"]: part for part in state.spec["parts"] if part["kind"] == "printed"}
        for body in state.assembly.get("bodies", []):
            part = printed.get(body["part_id"])
            info = state.built.get(body["part_id"]) if part else None
            if part is None or info is None or body["kind"] != "printed" or body["name"] not in names:
                continue
            box = info["bbox_mm"]
            orientation = plan.get(part["id"], "as_modeled")
            axis = np.array(rotation(part.get("rotation_deg"))) @ _build_axis([box[i + 3] - box[i] for i in range(3)], orientation)
            directions[body["name"]] = [float(v) for v in axis]
            poses[body["name"]] = orientation if part["id"] in plan else "as modelled"
    else:
        # print_prep plans the drone's frame and a single part as the one STL it reads, turned by that STL's size.
        key = "frame" if state.product == "drone" else "body"
        bodies = ["frame"] if state.product == "drone" else [row["name"] for row in (state.part or {}).get("parts", []) if not row.get("reference")]
        orientation = plan.get(key, "as_modeled")
        axis = up
        stl = REPO_ROOT / state.stl_path if state.stl_path else None
        if orientation != "as_modeled" and stl is not None and stl.is_file():
            from pai_agent.tools.print_prep import read_stl

            axis = [float(v) for v in _build_axis(np.ptp(read_stl(stl).reshape(-1, 3), axis=0).tolist(), orientation)]
        for name in bodies:
            if name in names:
                directions[name], poses[name] = axis, orientation if key in plan else "as modelled"
    return directions, poses


def _stress_layers(state, directory: Path, nodes: list[dict]) -> tuple[list[dict], set[str], str]:
    """The FEM results to show (their coloured GLBs), the parts they stand in for, and the legend."""

    rows = [row for key, row in state.checks.items() if key.startswith("fem:")]
    layers, replaced, strengths = [], set(), []
    names = {node["name"] for node in nodes}
    for row in rows:
        glb = directory / ("fem-" + row["part_id"] + ".glb")
        if not glb.is_file():
            continue
        if state.product == "generic" and state.assembly:
            bodies = {body["name"] for body in state.assembly.get("bodies", []) if body["part_id"] == row["part_id"]}
        else:
            bodies = {"frame"} if row["part_id"] == "frame" else set()
        if not bodies & names and row.get("part_name") not in names:
            continue
        replaced |= bodies
        layers.append({"glb": str(glb), "axes": "zup_mm", "role": "result"})
        strengths.append(f"{row['part_name']} {float(row['strength_mpa']):g} MPa")
    legend = "von Mises stress: blue none, green half, red at the printed strength (" + ", ".join(strengths) + ")"
    return layers, replaced, legend


def _run(job: dict) -> dict:
    """view_render in its own process; returns its JSON line."""

    with tempfile.TemporaryDirectory(prefix="pai-view-") as work:
        path = Path(work) / "job.json"
        path.write_text(json.dumps(job), encoding="utf-8")
        completed = subprocess.run([sys.executable, "-m", "pai_agent.view_render", str(path)], capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    if not lines:
        tail = (completed.stderr or completed.stdout or "no output").strip().splitlines()
        raise RuntimeError("the renderer stopped: " + (tail[-1] if tail else "no output")[:300])
    return json.loads(lines[-1])


def _numbers(value: object, size: int) -> list[float] | None:
    if not isinstance(value, list) or len(value) != size:
        return None
    try:
        out = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    return out if all(math.isfinite(v) for v in out) else None


def _names(value: object) -> list[str] | None:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    return [v for v in value if v.strip()]


async def cad_view(ctx: Ctx, args: dict) -> dict:
    colour = str(args.get("color") or "parts")
    if colour not in COLORS:
        return _fail("color must be one of " + ", ".join(COLORS) + ".")
    view = str(args.get("view") or ("iso_below" if colour == "overhang" else "sheet"))
    if view not in VIEWS:
        return _fail("view must be one of " + ", ".join(VIEWS) + ".")
    direction = None
    if args.get("direction") is not None:
        direction = _numbers(args["direction"], 3)
        if direction is None or math.hypot(*direction) < 1e-9:
            return _fail("direction must be three numbers [x, y, z], not all zero: the side you look from.")
    only, hide = _names(args.get("only")), _names(args.get("hide"))
    if only is None or hide is None:
        return _fail("only and hide must be lists of part names or ids.")
    section = args.get("section")
    if section is not None:
        if not isinstance(section, dict) or section.get("axis") not in ("x", "y", "z") or _numbers([section.get("at_mm")], 1) is None:
            return _fail("section must be {axis: x, y or z, at_mm: a number}.")
        if colour != "parts":
            return _fail("A section shows the parts' own colours; leave out color or section.")
        section = {"axis": section["axis"], "at_mm": float(section["at_mm"])}
    try:
        source = await _source(ctx)
    except ValueError as exc:
        return _fail(str(exc))
    state = ctx.state
    directory = Path(state.directory)
    nodes = mesh_nodes(source["document"])
    chosen, unknown = _select(nodes, _aliases(state), only, hide)
    if unknown:
        listed = ", ".join(dict.fromkeys(node["name"] for node in nodes))
        return _fail("No part is called " + ", ".join(repr(name) for name in unknown) + ". The parts: " + listed + ".")
    if not chosen:
        return _fail("Nothing left to show: only and hide leave out every part.")
    names = [node["name"] for node in chosen]
    views = list(SHEET) if view == "sheet" and direction is None else [view if view != "sheet" else "iso"]
    job: dict = {
        "views": views,
        "direction": direction,
        "front": source["front"],
        "section": section,
        "color": colour,
        "numbers": args.get("numbers") is not False,
        "layers": [{"glb": str(source["glb"]), "axes": source["axes"], "nodes": [node["index"] for node in chosen], "role": "context" if colour == "stress" else "model"}],
    }
    poses: dict[str, str] = {}
    if colour == "overhang":
        from pai_agent.tools.print_prep import OVERHANG_DEG

        job["printed"], poses = _print_poses(state, names)
        job["overhang_deg"] = OVERHANG_DEG
        if not job["printed"]:
            return _fail("None of the parts shown is printed, so nothing has an overhang to show.")
    elif colour == "stress":
        layers, replaced, job["legend"] = _stress_layers(state, directory, chosen)
        if not layers:
            return _fail("No FEM result for the parts shown: run fem_check first.")
        job["layers"][0]["nodes"] = [node["index"] for node in chosen if node["name"] not in replaced]
        job["layers"] += layers
    with tempfile.TemporaryDirectory(prefix="pai-view-out-") as work:
        job["out"] = str(Path(work) / FILE)
        try:
            drawn = await asyncio.to_thread(_run, job)
        except subprocess.TimeoutExpired:
            return _fail("The view took longer than " + str(TIMEOUT_S) + " s to render.")
        except (OSError, RuntimeError, ValueError) as exc:
            return _fail("The view could not be rendered: " + str(exc))
        if not drawn.get("ok"):
            return _fail("The view could not be rendered: " + str(drawn.get("error")))
        png = Path(job["out"]).read_bytes()
        shutil.copyfile(job["out"], directory / FILE)
    aliases = _aliases(state)
    parts = []
    for row in drawn["parts"]:
        entry = {"number": row["number"], "name": row["name"]}
        if row["name"] in aliases:
            entry["id"], entry["kind"] = aliases[row["name"]][:2]
        if colour == "parts" and row.get("color"):
            entry["color"] = colour_name(row["color"])
        if not row["seen"]:
            entry["seen"] = False
        parts.append(entry)
    hidden = [name for name in dict.fromkeys(node["name"] for node in nodes) if name not in names]
    titles = {"iso": "iso", "iso_below": "iso from below"}
    shown = "view from " + str([round(v, 3) for v in direction]) if direction is not None else ", ".join(titles.get(v, v) for v in views)
    detail = shown.capitalize() + " of " + source["label"] + ": " + str(len(parts)) + " part" + ("s" if len(parts) != 1 else "")
    result: dict = {
        "ok": True,
        "detail": detail,
        "views": views if direction is None else ["direction"],
        "frame": source["frame"] + "; views as in a drawing, right is the side on your right when you face the front",
        "picture": f"{WIDTH} x {HEIGHT} PNG, " + ("a 2 x 2 sheet: iso top left, front top right, right bottom left, top bottom right" if len(views) > 1 else "one view"),
        "parts": parts,
        "size_mm": [round(drawn["bounds_mm"][i + 3] - drawn["bounds_mm"][i], 1) for i in range(3)],
        "grid_mm": drawn["grid_mm"],
    }
    if hidden:
        result["hidden"] = hidden
    if section:
        removed = section["axis"] + (" > " if drawn.get("removed", "+") == "+" else " < ") + f"{section['at_mm']:g} mm"
        result["section"] = {**section, "removed": removed, "cut_faces": "a darker shade of each part's colour"}
    if colour == "overhang":
        result["overhang_cm2"] = {name: round(area / 100.0, 2) for name, area in drawn["overhang_mm2"].items()}
        result["print_pose"] = poses
        detail += ", overhang"
    if colour == "stress":
        result["legend"] = job["legend"]
    if any(not part.get("seen", True) for part in parts):
        result["note"] = "Parts with seen false are hidden behind others in this view: hide what is in front or look from another side."
    result["detail"] = detail
    result[IMAGE] = base64.b64encode(png).decode("ascii")
    return result
