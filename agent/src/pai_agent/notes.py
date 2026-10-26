"""Studio notes: what the person points at in the studio, sent along with a chat message (U6).

A note is a small structured attachment the dashboard puts as a chip into Mechanic's message box, so
Mechanic knows exactly what is meant instead of guessing from the words:

- `selection`: a part the person clicked, the face and the point; the backend adds the script that
  builds it and its lines (the FreeCAD harness records them per part, `part_harness.py`) and the point
  in that script's own frame.
- `measure`: two points and the distance between them, with the rise and the angle of the faces.
- `markup`: a picture of the view the person drew on, uploaded first (`POST /api/notes/markup`, stored
  as `markup-<n>.png` in the session) with what the view showed: tab, camera, explode, section, colours.
- `spot`: one value of a surface check (`analysis`) at one place, as the colour layer's click read it.
- `param`: a CAD parameter with its value, range and the value Mechanic designed.

Every note names the CAD build it was taken on (the `?build=` of the model), so a note on an older
build or version is never read as the design that stands now; whether it still is the current one is
decided when Mechanic reads it, which can be after a run that was busy. `accept` checks what the browser
sent and adds what only the backend knows, `describe` writes the lines Mechanic reads after the person's
words, `images` the markings as image blocks to go with them, and offline `read_back` says each note back.
"""

from __future__ import annotations

import base64
import binascii
import math
import re
import struct
from pathlib import Path

KINDS = ("selection", "measure", "markup", "spot", "param")
MAX_NOTES = 8
MAX_MARKUPS = 40
MAX_MARKUP_BYTES = 4 * 1024 * 1024
MAX_MARKUP_SIDE = 4096
# Lines of a selected part's script that go with the note, so Mechanic sees how it is built.
SNIPPET_LINES = 60

CHECKS = {"overhang": ("Overhang", "°"), "thickness": ("Wall thickness", " mm"), "clearance": ("Clearance", " mm")}
AXES = ("x", "y", "z")
TABS = {"modell": "Model", "cad": "CAD"}
_MARKUP = re.compile(r"markup-\d{1,4}\.png")
_PNG = b"\x89PNG\r\n\x1a\n"
_DATA_URL = re.compile(r"^data:([\w/+.-]+);base64,(.*)$", re.DOTALL)


# --- checking what the browser sent -------------------------------------------------------


def _text(raw: object, what: str, limit: int = 120, required: bool = False) -> str | None:
    if raw is None or raw == "":
        if required:
            raise ValueError(what + " is required.")
        return None
    if not isinstance(raw, str):
        raise ValueError(what + " must be text.")
    return raw.strip()[:limit] or None


def _number(raw: object, what: str, required: bool = False) -> float | None:
    if raw is None:
        if required:
            raise ValueError(what + " is required.")
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        raise ValueError(what + " must be a number.")
    return float(raw)


def _vector(raw: object, what: str, required: bool = False) -> list[float] | None:
    if raw is None:
        if required:
            raise ValueError(what + " is required.")
        return None
    if not isinstance(raw, list) or len(raw) != 3:
        raise ValueError(what + " must be three numbers [x, y, z].")
    return [round(float(_number(v, what, True)), 3) for v in raw]  # type: ignore[arg-type]


def _direction(raw: object, what: str) -> list[float] | None:
    vector = _vector(raw, what)
    if vector is None:
        return None
    length = math.sqrt(sum(v * v for v in vector))
    return [round(v / length, 3) for v in vector] if length > 1e-9 else None


def _whole(raw: object, what: str) -> int | None:
    number = _number(raw, what)
    if number is None:
        return None
    if number != int(number) or number < 0:
        raise ValueError(what + " must be a whole number.")
    return int(number)


def _end(raw: object, what: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(what + " must be a point {point_mm, node, part}.")
    return {
        "point_mm": _vector(raw.get("point_mm"), what + ".point_mm", True),
        "node": _text(raw.get("node"), what + ".node"),
        "part": _text(raw.get("part"), what + ".part"),
        "normal": _direction(raw.get("normal"), what + ".normal"),
    }


def _view(raw: object) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("view must be an object.")
    view: dict = {}
    if raw.get("tab") in TABS:
        view["tab"] = raw["tab"]
    camera = _direction(raw.get("camera"), "view.camera")
    if camera:
        view["camera"] = camera
    view["ortho"] = bool(raw.get("ortho"))
    explode = _number(raw.get("explode"), "view.explode")
    if explode:
        view["explode"] = round(min(1.0, max(0.0, explode)), 2)
    section = raw.get("section")
    if isinstance(section, dict) and section.get("axis") in AXES:
        view["section"] = {
            "axis": section["axis"],
            "at_mm": round(float(_number(section.get("at_mm"), "view.section.at_mm", True)), 1),  # type: ignore[arg-type]
            "keep": "above" if section.get("keep") == "above" else "below",
        }
    surface = raw.get("surface")
    if isinstance(surface, dict) and surface.get("check") in CHECKS:
        view["surface"] = {"check": surface["check"], "limit": _number(surface.get("limit"), "view.surface.limit")}
    hidden = raw.get("hidden")
    if isinstance(hidden, list):
        view["hidden"] = [name for name in (_text(item, "view.hidden") for item in hidden[:20]) if name]
    view["labels"] = bool(raw.get("labels"))
    return view


def _check(raw: object, directory: Path) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Every note must be an object with a kind.")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError("A note's kind must be one of " + ", ".join(KINDS) + ".")
    note: dict = {"kind": kind, "build": _whole(raw.get("build"), "build")}
    if kind == "selection":
        note.update(
            node=_text(raw.get("node"), "node", required=True),
            part=_text(raw.get("part"), "part"),
            part_id=_text(raw.get("part_id"), "part_id"),
            # A part picked without a click (the assembly tree) has no point.
            point_mm=_vector(raw.get("point_mm"), "point_mm"),
            normal=_direction(raw.get("normal"), "normal"),
            # Clicked where the section view cut the part: a point inside it, on the cut.
            cut=bool(raw.get("cut")) or None,
        )
    elif kind == "measure":
        note.update(a=_end(raw.get("a"), "a"), b=_end(raw.get("b"), "b"))
    elif kind == "markup":
        image = _text(raw.get("image"), "image", required=True)
        if not image or not _MARKUP.fullmatch(image) or not (directory / image).is_file():
            raise ValueError("image must name a marking uploaded to this session (POST /api/notes/markup).")
        note.update(image=image, view=_view(raw.get("view")), version=_whole(raw.get("version"), "version"))
    elif kind == "spot":
        if raw.get("check") not in CHECKS:
            raise ValueError("check must be one of " + ", ".join(CHECKS) + ".")
        note.update(
            check=raw["check"],
            value=_number(raw.get("value"), "value", True),
            part=_text(raw.get("part"), "part", required=True),
            part_id=_text(raw.get("part_id"), "part_id"),
            at_mm=_vector(raw.get("at_mm"), "at_mm", True),
            limit=_number(raw.get("limit"), "limit"),
            critical=bool(raw.get("critical")),
        )
    else:
        note.update(
            name=_text(raw.get("name"), "name", 80, required=True),
            label=_text(raw.get("label"), "label"),
            value=_number(raw.get("value"), "value", True),
            unit=_text(raw.get("unit"), "unit", 8) or "",
            min=_number(raw.get("min"), "min"),
            max=_number(raw.get("max"), "max"),
            default=_number(raw.get("default"), "default"),
        )
    return note


def accept(raw: object, state) -> list[dict]:
    """Checks the notes of one message and adds what the backend knows. Raises ValueError for the person."""

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("notes must be a list.")
    if len(raw) > MAX_NOTES:
        raise ValueError("At most " + str(MAX_NOTES) + " notes go with one message.")
    return [_enrich(_check(item, Path(state.directory)), state) for item in raw]


# --- what only the backend knows ------------------------------------------------------------


def _norm(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def _script_name(part_id: str) -> str:
    # The file cad_part writes next to the part (`part-<slug>.py`).
    from pai_agent.tools.cad_part import _slug

    return "part-" + _slug(part_id) + ".py"


def _transpose_apply(matrix: list[list[float]], point: list[float]) -> list[float]:
    return [sum(matrix[row][col] * point[row] for row in range(3)) for col in range(3)]


def _body(state, node: str | None, part_id: str | None) -> dict | None:
    """The printed body a model node shows: its spec part, its row from the harness, its script and its placement."""

    key = _norm(node)
    if state.product == "generic" and state.spec:
        bodies = (state.assembly or {}).get("bodies") or []
        body = next((b for b in bodies if _norm(b.get("name")) == key), None)
        if body is None and part_id:
            matches = [b for b in bodies if b.get("part_id") == part_id]
            body = matches[0] if len(matches) == 1 else None
        if body is None:
            return None
        found = {"part_id": body.get("part_id"), "body": body.get("name"), "kind": body.get("kind"), "holder": body.get("holder")}
        # A bought part a script draws itself (its `reference`, a servo in its pocket) has that script's lines too.
        info = state.built.get(found["part_id"]) if body.get("kind") in ("printed", "bought") else None
        if info is None:
            return found
        rows = info.get("parts") or []
        row = rows[0] if len(rows) == 1 else next((r for r in rows if _norm(r.get("name")) == key), None)
        spec_part = next((p for p in state.spec.get("parts", []) if p.get("id") == found["part_id"]), None)
        found.update(script=_script_name(found["part_id"]), source=info.get("script"), row=row)
        if spec_part is not None and info.get("bbox_mm"):
            from pai_agent.assembly import rotation

            box = info["bbox_mm"]
            center = [(box[i] + box[i + 3]) / 2.0 for i in range(3)]
            found["place"] = (rotation(spec_part.get("rotation_deg")), list(spec_part.get("position_mm") or center), center)
        return found
    part = state.part
    if part and Path(state.stl_path or "").name.startswith("part-"):
        rows = part.get("parts") or []
        row = next((r for r in rows if _norm(r.get("name")) == key), None)
        if row is None:
            return None
        script = Path(state.stl_path).with_suffix(".py").name
        return {"part_id": None, "body": row.get("name"), "kind": "bought" if row.get("reference") else "printed", "script": script, "source": part.get("script"), "row": row}
    return None


def _enrich(note: dict, state) -> dict:
    kind = note["kind"]
    if kind == "selection":
        found = _body(state, note["node"], note.get("part_id"))
        if found:
            note["part_id"] = found.get("part_id") or note.get("part_id")
            note["body"] = found.get("body")
            note["part_kind"] = found.get("kind")
            note["holder"] = found.get("holder")
            row = found.get("row") or {}
            if found.get("script") and row.get("lines"):
                note["script"] = found["script"]
                note["lines"] = row["lines"]
            if found.get("place") and note.get("point_mm"):
                matrix, target, center = found["place"]
                moved = [note["point_mm"][i] - target[i] for i in range(3)]
                local = [round(v + center[i], 1) for i, v in enumerate(_transpose_apply(matrix, moved))]
                if any(abs(local[i] - note["point_mm"][i]) > 0.05 for i in range(3)):
                    note["local_mm"] = local
    elif kind == "measure":
        a, b = note["a"]["point_mm"], note["b"]["point_mm"]
        delta = [b[i] - a[i] for i in range(3)]
        distance = math.sqrt(sum(v * v for v in delta))
        # One rounding, the one the dashboard's chip shows.
        note["distance_mm"] = round(distance, 1)
        note["delta_mm"] = [round(abs(v), 2) for v in delta]
        note["rise_deg"] = round(math.degrees(math.asin(min(1.0, abs(delta[2]) / distance))), 1) if distance > 1e-9 else 0.0
        na, nb = note["a"].get("normal"), note["b"].get("normal")
        if na and nb:
            dot = max(-1.0, min(1.0, sum(na[i] * nb[i] for i in range(3))))
            note["faces_deg"] = round(math.degrees(math.acos(dot)), 1)
    elif kind == "markup":
        note["url"] = "/files/" + state.session_id + "/" + note["image"]
    elif kind == "spot":
        label, unit = CHECKS[note["check"]]
        note["label"] = label
        note["unit"] = unit.strip()
        limits = (state.surface or {}).get("limits") or {}
        if limits.get(note["check"]) is not None:
            note["mechanic_limit"] = limits[note["check"]]
    elif kind == "param":
        designed, user_set = _designed(state, note["name"])
        if note.get("default") is None:
            note["default"] = designed
        if user_set:
            note["user_set"] = True
    note["built_as"] = _build_of(state, note.get("build"))
    return note


def _declared(script: str | None, key: str) -> float | None:
    """A parameter's default as the script's PARAMS declares it, read without running the script."""

    from pai_agent.part_params import ParamsError, declaration

    try:
        found = declaration(script or "")
    except ParamsError:
        return None
    value = (found[0].get(key) or {}).get("value") if found else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _designed(state, name: str) -> tuple[float | None, bool]:
    """The value Mechanic designed a parameter with, and whether the value now is one the person set with its slider
    (`BuildState.user_params`, which wins over Mechanic's values until he is asked for a new one)."""

    from pai_agent.tools.cad_part import LIBRARY, _slug

    if state.product == "generic" and state.spec and "." in name:
        part_id, _, key = name.partition(".")
        spec_part = next((p for p in state.spec.get("parts", []) if p.get("id") == part_id), None)
        value = ((spec_part or {}).get("params") or {}).get(key)
        designed = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else _declared((state.built.get(part_id) or {}).get("script"), key)
        return designed, key in (state.user_params.get(part_id) or {})
    part = state.part
    if not part:
        return None, False
    known = LIBRARY.get(part.get("template") or "", {}).get("params", {}).get(name)
    designed = float(known[0]) if known else _declared(part.get("script"), name)
    return designed, name in (state.user_params.get(_slug(part["name"])) or {})


def _build_of(state, build: int | None) -> dict | None:
    """Which build a note was taken on, against the one on the bench: current or not, and their versions."""

    if build is None:
        return None
    version = next((v["n"] for v in reversed(state.versions) if v.get("build") == build), None)
    now = next((v["n"] for v in reversed(state.versions) if v.get("build") == state.cad_builds), None)
    return {"build": build, "current": build == state.cad_builds, "version": version, "now": state.cad_builds, "now_version": now}


# --- markings ---------------------------------------------------------------------------------


def decode_png(raw: str) -> bytes:
    """A data URL or plain base64 of a PNG, as bytes. Raises ValueError with a message for the person."""

    text = (raw or "").strip()
    match = _DATA_URL.match(text)
    if match:
        text = match.group(2)
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("The marking is not valid base64 image data.") from exc
    if len(data) > MAX_MARKUP_BYTES:
        raise ValueError("The marking is larger than 4 MB.")
    if not data.startswith(_PNG) or len(data) < 24 or data[12:16] != b"IHDR":
        raise ValueError("The marking must be a PNG picture.")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= MAX_MARKUP_SIDE and 0 < height <= MAX_MARKUP_SIDE):
        raise ValueError("The marking must be at most " + str(MAX_MARKUP_SIDE) + " pixels on a side.")
    return data


def store_markup(state, data: bytes) -> str:
    """Writes the marking as markup-<n>.png into the session and returns its name."""

    directory = Path(state.directory)
    taken = [int(p.stem.split("-")[1]) for p in directory.glob("markup-*.png") if _MARKUP.fullmatch(p.name)]
    if len(taken) >= MAX_MARKUPS:
        raise ValueError("This chat has " + str(MAX_MARKUPS) + " markings already. Start over for more.")
    name = "markup-" + str(max(taken, default=0) + 1) + ".png"
    (directory / name).write_bytes(data)
    return name


# --- what Mechanic reads -----------------------------------------------------------------------


def _mm(value: float) -> str:
    text = f"{value:.1f}"
    return "0.0" if text == "-0.0" else text


def _point(point: list[float]) -> str:
    return "(" + ", ".join(_mm(v) for v in point) + ") mm"


def _name(node: str) -> str:
    # The model's loader writes spaces in node names as underscores.
    return node.replace("_", " ")


def _ranges(lines: list[list[int]]) -> str:
    return ", ".join(str(a) if a == b else str(a) + "-" + str(b) for a, b in lines)


def _facing(normal: list[float] | None, drone: bool) -> str:
    """A face's direction in words, when it points mostly along one axis."""

    if not normal:
        return ""
    axis = max(range(3), key=lambda i: abs(normal[i]))
    if abs(normal[axis]) < 0.9:
        return "pointing along (" + ", ".join(f"{v:.2f}" for v in normal) + ")"
    sign = normal[axis] > 0
    words = (
        ("right", "left"),
        (("to the nose", "to the tail") if drone else ("to the back", "to the front")),
        ("up", "down"),
    )[axis]
    return "pointing " + (words[0] if sign else words[1])


def _seen_from(camera: list[float], drone: bool) -> str:
    """Where the camera stood, as a drawing names it: front, back, left, right, above, below."""

    x, y, z = camera
    front = y > 0.35 if drone else y < -0.35
    back = y < -0.35 if drone else y > 0.35
    parts = [name for on, name in ((front, "the front"), (back, "the back"), (x > 0.35, "the right"), (x < -0.35, "the left"), (z > 0.35, "above"), (z < -0.35, "below")) if on]
    return "seen from " + (" and ".join([", ".join(parts[:-1]), parts[-1]]) if len(parts) > 1 else parts[0] if parts else "the side")


def _when(state, note: dict) -> str:
    """Whether the note is about the design on the bench now or an older one, as it stands when Mechanic reads it."""

    built = _build_of(state, note.get("build"))
    if not built:
        return ""
    if built["current"]:
        return " On the current model" + (" (version " + str(built["version"]) + ")" if built["version"] else "") + "."
    then = "build " + str(built["build"]) + (" (version " + str(built["version"]) + ")" if built["version"] else "")
    now = "build " + str(built["now"]) + (", version " + str(built["now_version"]) if built["now_version"] else "")
    return " Taken on " + then + ", an older model than the one on the bench now (" + now + "): check what changed before you act on it."


def _line(state, note: dict, index: int, drone: bool) -> str:
    kind = note["kind"]
    if kind == "selection":
        name = note.get("part") or note.get("body") or _name(note["node"])
        what = name + (" (" + str(note["part_kind"]) + " part " + note["part_id"] + ")" if note.get("part_kind") and note.get("part_id") else "")
        if note.get("body") and _norm(note["body"]) != _norm(name):
            what += ", body " + note["body"]
        if note.get("holder"):
            what += ", held in part " + note["holder"]
        text = "Selection: " + what + "."
        if note.get("point_mm"):
            facing = _facing(note.get("normal"), drone)
            where = "inside it, on the face the section view cut," if note.get("cut") else "the face " + facing if facing else "it"
            text += " The person clicked " + where + " at " + _point(note["point_mm"])
            if note.get("local_mm"):
                text += ", " + _point(note["local_mm"]) + " in its script's own frame"
            text += "."
        if note.get("script") and note.get("lines"):
            text += " Its script " + note["script"] + " builds it in lines " + _ranges(note["lines"]) + " (below)."
        return text + _when(state, note)
    if kind == "measure":
        a, b = note["a"], note["b"]
        ends = [(end.get("part") or end.get("node") or "the model") + " at " + _point(end["point_mm"]) for end in (a, b)]
        dx, dy, dz = note["delta_mm"]
        text = f"Measurement: {_mm(note['distance_mm'])} mm from {ends[0]} to {ends[1]}: dx {_mm(dx)}, dy {_mm(dy)}, dz {_mm(dz)} mm, {note['rise_deg']:g}° from the horizontal"
        if note.get("faces_deg") is not None:
            text += f"; the two faces stand at {note['faces_deg']:g}° to each other"
        return text + "." + _when(state, note)
    if kind == "markup":
        view = note.get("view") or {}
        bits = ["drawn on the " + TABS.get(view.get("tab", "modell"), "Model") + " tab"]
        if view.get("camera"):
            bits.append(_seen_from(view["camera"], drone))
        bits.append("orthographic" if view.get("ortho") else "perspective")
        if view.get("explode"):
            bits.append(f"exploded {round(view['explode'] * 100)} %")
        if view.get("section"):
            cut = view["section"]
            gone = "above" if cut["keep"] == "below" else "below"
            bits.append(f"cut through {cut['axis'].upper()} at {_mm(cut['at_mm'])} mm, the part {gone} it taken away so the cut faces show (darker)")
        if view.get("surface"):
            label, unit = CHECKS[view["surface"]["check"]]
            limit = view["surface"].get("limit")
            bits.append("coloured by " + label.lower() + (f" at {limit:g}{unit}" if limit is not None else ""))
        if view.get("hidden"):
            bits.append("hidden: " + ", ".join(view["hidden"]))
        text = f"Marking {index}, the picture number {index} after this text ({note['image']}): " + ", ".join(bits) + ". The person's strokes on it point at what they mean."
        if note.get("version"):
            text += " It shows version " + str(note["version"]) + " as the Versions tab picked it, not necessarily the current design."
        return text + _when(state, note)
    if kind == "spot":
        unit = CHECKS[note["check"]][1]
        text = f"Surface spot: {note['label'].lower()} {note['value']:.2f}{unit} on {_name(note['part'])} at {_point(note['at_mm'])}"
        if note.get("limit") is not None:
            text += f", {'past' if note['critical'] else 'within'} the {note['limit']:g}{unit} limit the colour layer showed"
            if note.get("mechanic_limit") is not None and abs(note["mechanic_limit"] - note["limit"]) > 1e-6:
                text += f" (your own limit is {note['mechanic_limit']:g}{unit})"
        return text + "." + _when(state, note)
    unit = (" " + note["unit"]) if note.get("unit") else ""
    text = f"Parameter: {note.get('label') or note['name']} ({note['name']}) is {note['value']:g}{unit}"
    if note.get("user_set"):
        text += ", a value the person set with its slider"
    if note.get("default") is not None and abs(note["default"] - note["value"]) > 1e-9:
        text += f"; you designed it at {note['default']:g}{unit}"
    if note.get("min") is not None and note.get("max") is not None:
        text += f"; its slider runs {note['min']:g} to {note['max']:g}{unit}"
    return text + "." + _when(state, note)


def _snippet(note: dict, source: str) -> str:
    rows = source.splitlines()
    out, used = [], 0
    for first, last in note["lines"]:
        if out:
            out.append("...")
        for number in range(first, last + 1):
            if used >= SNIPPET_LINES:
                out.append("... (more lines in " + note["script"] + ")")
                return "\n".join(out)
            if 0 < number <= len(rows):
                out.append(f"{number:>4}  {rows[number - 1]}")
                used += 1
    return "\n".join(out)


def describe(state, text: str, notes: list[dict]) -> str:
    """The person's words, then one numbered line per note and the script lines of each selected part."""

    drone = state.product == "drone"
    head = text.strip() or "(No words: only the notes below.)"
    lines = []
    markings = 0
    for number, note in enumerate(notes, 1):
        if note["kind"] == "markup":
            markings += 1
        lines.append(str(number) + ". " + _line(state, note, markings, drone))
    out = head + "\n\nStudio notes the person attached (positions in mm in the build's frame, Z up, as in cad_view):\n" + "\n".join(lines)
    sources = {}
    for note in notes:
        if note["kind"] != "selection" or not note.get("lines"):
            continue
        found = _body(state, note["node"], note.get("part_id"))
        source = (found or {}).get("source")
        if source and (note["script"], str(note["lines"])) not in sources:
            sources[(note["script"], str(note["lines"]))] = "\n\n" + note["script"] + ", the lines that build " + (note.get("part") or note["node"]) + ":\n```python\n" + _snippet(note, source) + "\n```"
    return out + "".join(sources.values())


def images(state, notes: list[dict]) -> list[dict]:
    """Each marking as an image block, in the order `describe` numbers them; they follow its text."""

    blocks: list[dict] = []
    for note in notes:
        if note["kind"] != "markup":
            continue
        path = Path(state.directory) / note["image"]
        if path.is_file():
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(path.read_bytes()).decode("ascii")}})
    return blocks


def public(notes: list[dict]) -> list[dict]:
    """The notes as the chat event carries them."""

    return [{key: value for key, value in note.items() if value is not None and value != {}} for note in notes]


# --- offline -------------------------------------------------------------------------------------


def _short(state, note: dict, drone: bool) -> str:
    kind = note["kind"]
    if kind == "selection":
        text = note.get("part") or note.get("body") or _name(note["node"])
        if note.get("script") and note.get("lines"):
            text += ", " + note["script"] + " lines " + _ranges(note["lines"])
        if note.get("point_mm") and note.get("cut"):
            text += ", inside on the section's cut at " + _point(note["point_mm"])
        elif note.get("point_mm"):
            facing = _facing(note.get("normal"), drone)
            text += (", the face " + facing + " at " if facing else " at ") + _point(note["point_mm"])
    elif kind == "measure":
        ends = [(end.get("part") or "the model") for end in (note["a"], note["b"])]
        text = f"{_mm(note['distance_mm'])} mm from {ends[0]} to {ends[1]}, {note['rise_deg']:g}° up"
    elif kind == "markup":
        view = note.get("view") or {}
        text = "your marking on the " + TABS.get(view.get("tab", "modell"), "Model") + " view"
        if view.get("section"):
            text += f", cut through {view['section']['axis'].upper()} at {_mm(view['section']['at_mm'])} mm"
    elif kind == "spot":
        text = f"{note['label'].lower()} {note['value']:.2f}{CHECKS[note['check']][1]} on {_name(note['part'])} at {_point(note['at_mm'])}"
    else:
        unit = (" " + note["unit"]) if note.get("unit") else ""
        text = f"{note.get('label') or note['name']} at {note['value']:g}{unit}"
    built = _build_of(state, note.get("build"))
    if built and not built["current"]:
        text += " (on an older build)"
    return text


def read_back(state, notes: list[dict]) -> str:
    """What Mechanic says offline: each note back in one line, so the person sees what he would get."""

    drone = state.product == "drone"
    shorts = [_short(state, note, drone) for note in notes]
    lines = "\n".join("- " + short[:1].upper() + short[1:] for short in shorts)
    return "I read your notes:\n\n" + lines + "\n\nOffline I can only read them back. With Claude connected I change the design right there."
