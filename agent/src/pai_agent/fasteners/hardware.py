"""AnyBuild's standard parts: checked entries in, CadQuery parts, harness inputs and bill-of-materials lines out.

One entry describes one standard part at one or more seats of a printed part:

    {"name": "Lid screw", "kind": "screw", "standard": "ISO 4762", "size": "M3x10",
     "at": [[20, 15, 30], [-20, 15, 30]], "direction": "-Z", "hole": "clearance", "fit": "medium"}

`at` is the seat in the frame the part's script builds in (mm): the point on the axis where the
underside of a screw head, a nut or a washer rests, or the top of an insert, a countersunk screw or a
set screw; a sunk part ends flush with `at` instead (or as many mm below it as `sunk` says).
`direction` points from there into the material. `normalize` turns the entries into one item
per seat, checked against the tables, and `build` makes each with SOMA's module in CadQuery: the part,
the tool that cuts its hole, and its keep-out, the space no printed material may fill (the whole part,
except where a thread or an insert's knurls bite into the plastic on purpose).

The FreeCAD harness gets them as STEP files (`write_inputs`): it cuts every hole into the printed bodies
of the part and measures the material left in each keep-out. `misfits` says what sits in material and
what to change (the build fails on it), `apply_fit` adds a warning for a part that touches no printed
body. `write_meshes` writes their STLs for the 3D view and the assembly, `price` finds a price per
piece through the catalog search, and `bom_lines` groups them for the bill of materials.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

PACKAGE = Path(__file__).resolve().parent
KINDS = ("screw", "nut", "washer", "insert")
# The holes each kind can get; the first is the default.
HOLES = {"screw": ("clearance", "tap", "none"), "nut": ("trap", "none"), "washer": ("none",), "insert": ("insert", "none")}
DEFAULT_STANDARD = {"screw": "ISO 4762", "nut": "ISO 4032", "washer": "ISO 7089"}
DEFAULT_BRAND = "ruthex"
FITS = ("fine", "medium", "coarse")
MAX_ITEMS = 48
# Per side, the room a nut gets in its trap (the module's default).
TRAP_CLEARANCE_MM = 0.2
# g/cm3: screws, nuts and washers are steel (STEEL in cad_script), inserts brass.
DENSITY = {"steel": 7.85, "brass": 8.5}
# The module's steel and brass colours as hex, for the 3D view.
COLORS = {"steel": "#73757d", "brass": "#cca152"}
# A keep-out may share faces with its hole or the surface it rests on; anything above this is material in the way.
OVERLAP_MM3 = 0.01
_KIND_WORDS = {"screw": ("screw", "bolt"), "nut": ("nut",), "washer": ("washer",), "insert": ("insert",)}
# Without a catalog item of its own kind and thread, a line is estimated from the nearest kind that has one.
_PRICED_LIKE = {"screw": ("screw",), "nut": ("nut", "screw"), "washer": ("washer", "nut", "screw"), "insert": ("insert",)}
_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}

# The `fasteners` field of a printed spec part and of cad_part.
SCHEMA = {
    "type": "array",
    "description": (
        "Standard parts this printed part holds: screws, nuts, washers and heat-set inserts. After the script, the harness cuts each one's hole "
        "into the part and adds the part itself, and the build fails when one sits in material; the bill of materials lists them by standard, size and length. "
        "at is the seat in mm in the frame the part is built in, or a list of seats: where the underside of a screw head, a nut or a washer rests, "
        "or the top of an insert, a countersunk screw or a set screw; a sunk part ends flush with at instead. direction points from there into the material (default -Z). "
        "A screw that joins two printed parts belongs to the one its head rests on; give the other the insert, nut or tap hole on the same axis."
    ),
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Optional; several seats are numbered, e.g. 'Lid screw 1'."},
            "kind": {"type": "string", "enum": list(KINDS)},
            "standard": {
                "type": "string",
                "description": "Screws: ISO 4762 (socket head, default), ISO 7380 (button head), ISO 10642 (countersunk), ISO 4017, ISO 4014, DIN 931 (hex head), "
                "ISO 4026 (set screw). Nuts: ISO 4032 (default), ISO 4033 (high), ISO 4035 (thin), DIN 557 (square). Washers: ISO 7089 (default), ISO 7091, ISO 7093 (large).",
            },
            "size": {"type": "string", "description": "M3x10 for a screw (a standard length), M3 for a nut or a washer, M3x4 or 'M3 short' for an insert."},
            "at": {"type": "array", "description": "The seat [x, y, z] in mm, or a list of seats."},
            "direction": {"description": "From the seat into the material: -Z (default), +X, ... or [x, y, z]."},
            "hole": {
                "type": "string",
                "enum": ["clearance", "tap", "trap", "insert", "none"],
                "description": "screw: clearance (default) or tap (a thread in the plastic); nut: trap (default); insert: insert (default); none: the script cuts it.",
            },
            "fit": {"type": "string", "enum": list(FITS), "description": "Clearance hole after ISO 273, default medium."},
            "sunk": {"description": "true sinks a screw head into a counterbore, a nut into a trap open to the surface or an insert flush; a number sinks it that many mm deeper."},
            "brand": {"type": "string", "enum": ["ruthex", "CNCKitchen", "McMaster-Carr", "Hilitchi", "AE-SamZhihui"], "description": "Insert maker, default ruthex."},
            "variant": {"type": "string", "description": "Insert variant of the same length, e.g. Voron."},
            "depth_mm": {"type": "number", "description": "Depth of a screw's hole from at, when the rest of the screw threads into the part."},
            "oversize_mm": {"type": "number", "description": "Added to the hole diameters, for printers whose holes come out small."},
        },
        "required": ["kind", "size", "at"],
    },
}


@functools.cache
def _soma():
    """The vendored module; it imports CadQuery, so only code that checks or builds parts loads it."""

    from pai_agent.fasteners import fasteners

    return fasteners


@functools.cache
def version() -> str:
    """Changes when the module, this file or a table changes, so cached builds with standard parts rebuild."""

    digest = hashlib.sha256()
    for path in sorted([PACKAGE / "fasteners.py", PACKAGE / "hardware.py", *(PACKAGE / "data").glob("*.csv")]):
        digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()[:16]


def _fmt(value: float) -> str:
    return f"{value:g}"


def _round(value: float) -> float:
    # + 0.0 turns -0.0 into 0.0, so equal entries serialise equally.
    return round(float(value), 4) + 0.0


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _vector(raw: object, what: str) -> list[float]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        raise ValueError(what + " must be [x, y, z] in mm.")
    values = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 2000:
            raise ValueError(what + " must be [x, y, z] in mm, each within 2000 mm.")
        values.append(_round(value))
    return values


def _points(raw: object) -> list[list[float]]:
    """One seat [x, y, z] or a list of seats."""

    if raw is None:
        raise ValueError("at is missing: the seat [x, y, z] in mm, or a list of seats.")
    if isinstance(raw, (list, tuple)) and raw and all(isinstance(point, (list, tuple)) for point in raw):
        if len(raw) > MAX_ITEMS:
            raise ValueError("at lists more than " + str(MAX_ITEMS) + " seats.")
        return [_vector(point, "at") for point in raw]
    return [_vector(raw, "at")]


def _direction(raw: object) -> list[float]:
    if raw is None:
        return [0.0, 0.0, -1.0]
    if isinstance(raw, str):
        match = re.fullmatch(r"\s*([+-]?)\s*([xyzXYZ])\s*", raw)
        if not match:
            raise ValueError('direction must be an axis such as "-Z" or "+X", or [x, y, z].')
        sign = -1.0 if match.group(1) == "-" else 1.0
        return [_round(sign * v) for v in _AXES[match.group(2).lower()]]
    vector = _vector(raw, "direction")
    length = math.sqrt(sum(v * v for v in vector))
    if length < 1e-9:
        raise ValueError("direction must not be [0, 0, 0].")
    return [_round(v / length) for v in vector]


def _number(raw: object, what: str, low: float, high: float) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or not low <= raw <= high:
        raise ValueError(what + " must be a number from " + _fmt(low) + " to " + _fmt(high) + ".")
    return _round(raw)


def _sunk(raw: object) -> float | None:
    """None: not sunk; otherwise how far below the seat the part's outer side sits (0 is flush)."""

    if raw is None or raw is False:
        return None
    if raw is True:
        return 0.0
    return _number(raw, "sunk (true, false or a depth in mm)", 0.0, 50.0)


def _plain(message: str) -> str:
    """The module's messages, minus the advice on its own Python arguments that tool callers do not have."""

    return message.replace(". Non-standard length: check_length=False", "")


def _brand(raw: object) -> str:
    soma = _soma()
    key = re.sub(r"[\s_.-]", "", str(raw or DEFAULT_BRAND).lower())
    if key not in soma.INSERT_BRANDS:
        raise ValueError("brand must be one of " + ", ".join(sorted(set(soma.INSERT_BRANDS.values()))) + ".")
    return soma.INSERT_BRANDS[key]


def _kind_of(entry: dict) -> str:
    """The kind a standard names (a screw, nut or washer standard), or insert for an insert brand."""

    soma = _soma()
    key = re.sub(r"[\s_.-]", "", str(entry.get("standard") or "").lower())
    key = soma.ALIASES.get(key, key)
    for kind, table in (("screw", soma.SCREWS), ("nut", soma.NUTS), ("washer", soma.WASHERS)):
        if key in table:
            return kind
    return "insert" if entry.get("brand") else ""


def _short_insert(brand: str, size: str) -> str:
    """ "M3 short" -> "M3x4" for ruthex: the shortest insert the maker has for that thread."""

    soma = _soma()
    match = re.fullmatch(r"\s*M\s*(\d+(?:[.,]\d+)?)\s*(?:short|kurz)\s*", size, re.IGNORECASE)
    if not match:
        return size
    d = float(match.group(1).replace(",", "."))
    rows = [row for row in soma._inserts(brand) if abs(row[0] - d) < 1e-9]
    if not rows:
        return "M" + _fmt(d)
    return "M" + _fmt(d) + "x" + _fmt(min(row[3]["m"] for row in rows))


def _part(item: dict):
    """The module's part for one item at its seat; raises ValueError with what is wrong."""

    soma = _soma()
    place = {"at": tuple(item["at"]), "direction": tuple(item["direction"]), "angle": item["angle_deg"]}
    sunk = False if item["sunk"] is None else item["sunk"]
    if item["kind"] == "screw":
        return soma.Screw(item["standard"], item["size"], item["length_mm"], sunk=sunk, **place)
    if item["kind"] == "nut":
        return soma.Nut(item["standard"], item["size"], sunk=sunk, **place)
    if item["kind"] == "washer":
        return soma.Washer(item["standard"], item["size"], **place)
    return soma.HeatSetInsert(item["size"], item["length_mm"], brand=item["brand"], variant=item["variant"], sunk=sunk, **place)


def _entry(entry: dict, owner: str, counts: dict[str, int]) -> list[dict]:
    kind = str(entry.get("kind") or "").strip().lower() or _kind_of(entry)
    if kind not in KINDS:
        raise ValueError("kind must be screw, nut, washer or insert.")
    points = _points(entry.get("at"))
    size = str(entry.get("size") or "").strip()
    if not size:
        raise ValueError("size is missing, e.g. \"M3x10\" for a screw, \"M3\" for a nut or washer, \"M3x4\" for an insert.")
    item = {
        "kind": kind,
        "standard": None,
        "brand": None,
        "variant": None,
        "size": size,
        "length_mm": _number(entry.get("length_mm"), "length_mm", 0.5, 500.0),
        "at": points[0],
        "direction": _direction(entry.get("direction")),
        "hole": None,
        "fit": None,
        "sunk": _sunk(entry.get("sunk")),
        "depth_mm": _number(entry.get("depth_mm"), "depth_mm", 0.1, 500.0),
        "oversize_mm": _number(entry.get("oversize_mm"), "oversize_mm", 0.0, 1.0) or 0.0,
        "angle_deg": _number(entry.get("angle_deg"), "angle_deg", -360.0, 360.0) or 0.0,
    }
    if kind == "insert":
        item["brand"] = _brand(entry.get("brand"))
        item["variant"] = str(entry["variant"]).strip() if entry.get("variant") else None
        item["size"] = _short_insert(item["brand"], size)
    else:
        item["standard"] = str(entry.get("standard") or DEFAULT_STANDARD[kind])
    if kind in {"nut", "washer"} and item["length_mm"] is not None:
        raise ValueError("a " + kind + " has no length; give only its thread, e.g. \"M3\".")
    part = _part(item)
    head = getattr(part, "head", None)
    hole = str(entry.get("hole") or ("tap" if head == "set" else HOLES[kind][0])).strip().lower()
    if hole not in HOLES[kind]:
        raise ValueError("hole for a " + kind + " must be " + " or ".join(HOLES[kind]) + ", not " + repr(hole) + ".")
    if kind == "screw":
        if head == "set" and hole == "clearance":
            raise ValueError("a set screw sits in its thread: hole must be tap or none.")
        if head == "countersunk" and hole == "tap":
            raise ValueError("a countersunk screw needs the clearance hole, which cuts its countersink.")
        if item["sunk"] is not None and hole != "clearance":
            raise ValueError("a sunk screw needs the clearance hole, which cuts its counterbore.")
        if hole == "clearance":
            item["fit"] = str(entry.get("fit") or "medium").strip().lower()
            if item["fit"] not in FITS:
                raise ValueError("fit must be fine, medium or coarse (ISO 273), not " + repr(item["fit"]) + ".")
    elif item["depth_mm"] is not None:
        raise ValueError("depth_mm is the depth of a screw's hole; a " + kind + " has its own.")
    if kind == "washer" and item["sunk"] is not None:
        raise ValueError("a washer lies on the surface; sunk is not supported.")
    item["hole"] = hole
    # The module's own spelling: "ISO 4762", "M3" with the length apart, the maker's name.
    item["size"] = "M" + _fmt(part.d)
    if kind in {"screw", "insert"}:
        item["length_mm"] = _round(part.length)
    if kind == "insert":
        item["variant"] = part.variant
    else:
        item["standard"] = part.standard
    base = str(entry.get("name") or "").strip()[:60]
    items = []
    for index, point in enumerate(points, 1):
        if base:
            name = base if len(points) == 1 else base + " " + str(index)
        else:
            counts[kind] = counts.get(kind, 0) + 1
            name = (owner + " " + kind + " " + str(counts[kind])).strip()
        placed = {"name": name, **item, "at": point}
        if index > 1:
            _part(placed)
        items.append(placed)
    return items


def normalize(raw: object, owner: str = "") -> tuple[list[dict], list[str]]:
    """One item per seat from a part's `fasteners`, checked against the tables, or every problem found.

    owner (the part's name) starts the names of entries that have none: "Lid screw 1".
    Normalizing the result again gives the same items.
    """

    if raw is None or raw == []:
        return [], []
    if not isinstance(raw, list):
        return [], ["fasteners must be a list of standard parts, e.g. [{\"kind\": \"screw\", \"standard\": \"ISO 4762\", \"size\": \"M3x10\", \"at\": [0, 0, 5]}]."]
    items: list[dict] = []
    problems: list[str] = []
    counts: dict[str, int] = {}
    for index, entry in enumerate(raw):
        where = "fasteners[" + str(index) + "]"
        if not isinstance(entry, dict):
            problems.append(where + " must be an object.")
            continue
        try:
            items += _entry(entry, owner, counts)
        except ValueError as exc:
            problems.append(where + ": " + _plain(str(exc)))
    names = [item["name"] for item in items]
    twice = sorted({name for name in names if names.count(name) > 1})
    if twice:
        problems.append("Each fastener needs its own name; used twice: " + ", ".join(twice) + ".")
    if len(items) > MAX_ITEMS:
        problems.append("Keep it to " + str(MAX_ITEMS) + " standard parts per printed part, not " + str(len(items)) + ".")
    return ([] if problems else items), problems


def designation(item: dict) -> str:
    """ "ISO 4762 M3x10", "ISO 4032 M3", "Heat-set insert ruthex M3x4"."""

    length = "x" + _fmt(item["length_mm"]) if item["kind"] in {"screw", "insert"} else ""
    if item["kind"] == "insert":
        return "Heat-set insert " + item["brand"] + " " + item["size"] + length + (" " + item["variant"] if item["variant"] else "")
    return item["standard"] + " " + item["size"] + length


def _title(item: dict) -> str:
    soma = _soma()
    if item["kind"] == "insert":
        return "heat-set insert"
    table = {"screw": soma.SCREWS, "nut": soma.NUTS, "washer": soma.WASHERS}[item["kind"]]
    title = next(entry["title"] for entry in table.values() if entry["name"] == item["standard"])
    return title[0].lower() + title[1:]


def line_name(item: dict, part_number: str | None = None) -> str:
    """How the bill of materials names it: "ISO 4762 M3x10 socket head cap screw"."""

    if item["kind"] == "insert":
        return designation(item) + (" (" + part_number + ")" if part_number else "")
    return designation(item) + " " + _title(item)


def _numbers(item: dict, part) -> dict:
    """The sizes the script and the result see, in mm."""

    kind, hole, oversize = item["kind"], item["hole"], item["oversize_mm"]
    numbers: dict = {"d": part.d}
    if kind == "screw":
        numbers.update(length=part.length, head_d=part.head_diameter, head_h=part.head_height, key=part.key)
        if hole == "clearance":
            numbers["hole_d"] = part.clearance(item["fit"]) + oversize
        elif hole == "tap":
            numbers["hole_d"] = part.tap_drill + oversize
    elif kind == "nut":
        numbers.update(key=part.key, height=part.height)
        if hole == "trap":
            numbers["hole_d"] = part.key + 2 * TRAP_CLEARANCE_MM + oversize
    elif kind == "washer":
        numbers.update(inner_d=part.inner, outer_d=part.outer_diameter, thickness=part.thickness)
    else:
        numbers.update(outer_d=part.diameter, length=part.length, hole_d=part.hole_diameter + oversize)
    return {key: _round(value) for key, value in numbers.items()}


def _gap(item: dict, numbers: dict) -> float | None:
    """Radial gap to the hole wall in mm: play when positive, a thread or knurls biting in when negative."""

    if "hole_d" not in numbers:
        return None
    if item["kind"] == "nut":
        return _round(TRAP_CLEARANCE_MM + item["oversize_mm"] / 2)
    if item["kind"] == "insert":
        return _round((numbers["hole_d"] - numbers["outer_d"]) / 2)
    return _round((numbers["hole_d"] - numbers["d"]) / 2)


def _point(values) -> str:
    return "(" + ", ".join(_fmt(round(float(v), 3) + 0.0) for v in values) + ")"


def _advice(item: dict, numbers: dict) -> str:
    """What the script writer changes when the part sits in material; the same for every piece of one kind."""

    if item["kind"] == "screw":
        if item["hole"] == "none":
            return "cut the hole (" + _fmt(numbers["d"]) + " mm shank) and leave room for the head at the seat."
        return "the head needs a flat face at the seat with room around it, and the shank no material."
    if item["kind"] == "insert":
        return "cut a hole of at least " + _fmt(numbers["hole_d"]) + " mm, " + _fmt(numbers["length"]) + " mm deep from the top."
    return "the seat needs a flat face with room around it."


def describe(items: list[dict]) -> str:
    """The standard parts of a part, for the CAD agent that writes its script."""

    if not items:
        return ""
    lines = [
        "Standard parts in this part (mm, the frame you build in). After your script runs, the harness adds each one and cuts its hole into your printed bodies: do not model them.",
        "At its point the underside of a screw head, a nut or a washer rests, and an insert, a countersunk or set screw or a sunk part ends flush.",
        "Give each one material to sit in: a flat face under every screw head, nut and washer, at least 2 mm of wall around every hole,",
        "and around an insert a boss at least 3 mm wider than its hole and 1 mm deeper than the insert.",
        "H[name] holds each: shape, hole (the cutting tool, or None), seat and direction (Vectors) and its sizes (d, hole_d, length, head_d, head_h, key, outer_d ...).",
    ]
    for item in items:
        part = _part(item)
        numbers = _numbers(item, part)
        text = line_name(item) + " at " + _point(item["at"]) + ", into the material along " + _point(item["direction"])
        if item["sunk"] is not None:
            text += ", sunk " + (_fmt(item["sunk"]) + " mm below that" if item["sunk"] else "flush")
        if item["hole"] == "clearance":
            text += ", clearance hole " + _fmt(numbers["hole_d"]) + " mm (" + item["fit"] + ")"
        elif item["hole"] == "tap":
            text += ", tap hole " + _fmt(numbers["hole_d"]) + " mm"
        elif item["hole"] == "trap":
            text += ", nut trap " + _fmt(numbers["hole_d"]) + " mm across flats"
        elif item["hole"] == "insert":
            text += ", insert hole " + _fmt(numbers["hole_d"]) + " mm, " + _fmt(numbers["length"] + 1) + " mm deep"
        elif item["kind"] == "washer":
            text += ", " + _fmt(numbers["outer_d"]) + " x " + _fmt(numbers["thickness"]) + " mm on the surface"
        else:
            text += ", no hole cut for it: cut its hole yourself"
        if item["kind"] == "screw" and part.head != "set":
            text += ", head " + _fmt(numbers["head_d"]) + " x " + _fmt(numbers["head_h"]) + " mm"
        lines.append("- " + json.dumps(item["name"]) + ": " + text + ".")
    return "\n".join(lines) + "\n\n"


@dataclass
class Made:
    """One standard part built in CadQuery: the part, its hole tool and its keep-out, all in place."""

    item: dict
    shape: object
    hole: object | None
    keep: object | None
    numbers: dict
    material: str
    part_number: str | None
    seat: list[float]
    tip: list[float] | None
    advice: str


def _zone(part, numbers: dict, free_mm: float):
    """A cylinder over the head and the shank down to free_mm below at: the screw must be free in there.

    Measured from at, the surface, as the module measures a hole's depth: a sunk head sits below it.
    """

    import cadquery as cq

    axis = cq.Vector(*part.direction)
    base = cq.Vector(*part.surface) + axis * free_mm
    height = free_mm + numbers["head_h"] + 1.0
    return cq.Solid.makeCylinder(numbers["head_d"] / 2 + 1.0, height, base, -axis)


def _make(item: dict) -> Made:
    import cadquery as cq

    part = _part(item)
    shape = part.shape
    numbers = _numbers(item, part)
    kind, hole = item["kind"], item["hole"]
    tool = None
    keep = shape
    if kind == "screw":
        if hole == "clearance":
            tool = part.clearance_hole(fit=item["fit"], depth=item["depth_mm"], oversize=item["oversize_mm"])
        elif hole == "tap":
            tool = part.tap_hole(depth=item["depth_mm"], oversize=item["oversize_mm"])
        if part.head == "set" and hole == "tap":
            # A set screw sits in its thread all along: nothing of it has to stay free.
            keep = None
        elif hole == "tap" or (hole == "clearance" and item["depth_mm"] is not None):
            # Below the hole's depth the thread bites into the plastic on purpose; the head and the free shank may not.
            keep = shape.intersect(_zone(part, numbers, item["depth_mm"] if hole == "clearance" else 0.0))
    elif kind == "nut" and hole == "trap":
        tool = part.trap(clearance=TRAP_CLEARANCE_MM + item["oversize_mm"] / 2)
    elif kind == "insert":
        if hole == "insert":
            tool = part.hole(oversize=item["oversize_mm"])
        # The knurls melt into the wall on purpose; the hole itself must be there at the maker's diameter.
        axis = cq.Vector(*part.direction)
        keep = cq.Solid.makeCylinder(part.hole_diameter / 2 - 0.01, part.length, cq.Vector(*part.point(part.length)), -axis)
    return Made(
        item=item,
        shape=shape,
        hole=tool,
        keep=keep,
        numbers=numbers,
        material="brass" if kind == "insert" else "steel",
        part_number=getattr(part, "part_number", None) if kind == "insert" else None,
        seat=[_round(v) for v in part.seat],
        tip=[_round(v) for v in part.tip] if kind == "screw" else None,
        advice=_advice(item, numbers),
    )


def build(items: list[dict]) -> list[Made]:
    """Every item as CadQuery shapes, in the frame the part's script builds in."""

    return [_make(item) for item in items]


def write_inputs(made: list[Made], work: Path) -> None:
    """hardware.json and one STEP per shape for the FreeCAD harness, which cuts the holes and measures the fit."""

    rows = []
    for index, one in enumerate(made):
        files = {"shape": "hw-" + str(index) + ".step", "keep": None, "hole": None}
        one.shape.exportStep(str(work / files["shape"]))
        for key, shape in (("keep", one.keep), ("hole", one.hole)):
            if shape is not None:
                files[key] = "hw-" + str(index) + "-" + key + ".step"
                shape.exportStep(str(work / files[key]))
        rows.append(
            {
                "name": one.item["name"],
                "kind": one.item["kind"],
                "files": files,
                "seat": one.seat,
                "direction": one.item["direction"],
                "tip": one.tip,
                "numbers": one.numbers,
            }
        )
    (work / "hardware.json").write_text(json.dumps({"overlap_mm3": OVERLAP_MM3, "items": rows}), encoding="utf-8")


def _bounds(shape) -> list[float]:
    """The exact bounding box: CadQuery's BoundingBox of a meshed shape is its triangulation's, a few um too big."""

    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    return [_round(v) for v in box.Get()]


def row_of(one: Made, stl_name: str) -> dict:
    """The record a built part keeps for one standard part: what it is, its hole, its mesh and its mass."""

    center = one.shape.Center()
    volume = float(one.shape.Volume())
    item = one.item
    return {
        "name": item["name"],
        "key": "hw-" + _slug(designation(item)),
        "kind": item["kind"],
        "role": "hardware",
        "designation": designation(item),
        "line": line_name(item, one.part_number),
        "standard": item["standard"],
        "brand": item["brand"],
        "part_number": one.part_number,
        "size": item["size"],
        "length_mm": item["length_mm"],
        "hole": item["hole"],
        "fit": item["fit"],
        "hole_d_mm": one.numbers.get("hole_d"),
        "radial_gap_mm": _gap(item, one.numbers),
        "seat_mm": one.seat,
        # From the seat into the material: the explode view takes it out the other way.
        "direction": [_round(v) for v in item["direction"]],
        "stl": stl_name,
        "bbox_mm": _bounds(one.shape),
        "com_mm": [_round(v) for v in (center.x, center.y, center.z)],
        "volume_mm3": round(volume, 2),
        "material": one.material,
        "mass_g": round(volume / 1000.0 * DENSITY[one.material], 3),
        "color": COLORS[one.material],
    }


def mesh_name(stem: str, index: int) -> str:
    """part-lid.hw0.stl: no part's slug holds a dot, so the name never meets a printed part's file."""

    return stem + ".hw" + str(index) + ".stl"


def step_name(stem: str) -> str:
    """part-lid.hardware.step: every standard part of one printed part, in place."""

    return stem + ".hardware.step"


def is_mesh(name: str) -> bool:
    """A standard part's STL (mesh_name): bought, so never for the slicer."""

    return re.search(r"\.hw\d+\.stl$", name) is not None


def clear_files(out_dir: Path, stem: str) -> None:
    """Removes a printed part's standard-part files from an earlier build, which may have had more of them."""

    for old in [*out_dir.glob(stem + ".hw*.stl"), out_dir / step_name(stem)]:
        if old.is_file() and (is_mesh(old.name) or old.name == step_name(stem)):
            old.unlink()


def write_meshes(made: list[Made], out_dir: Path, stem: str) -> list[dict]:
    """One STL per standard part (mesh_name) and all of them in place as one STEP (step_name); returns their rows."""

    import cadquery as cq
    from cadquery import exporters

    clear_files(out_dir, stem)
    rows = []
    for index, one in enumerate(made):
        stl = out_dir / mesh_name(stem, index)
        exporters.export(one.shape, str(stl), tolerance=0.02, angularTolerance=0.2)
        rows.append(row_of(one, stl.name))
    if made:
        cq.Compound.makeCompound([one.shape for one in made]).exportStep(str(out_dir / step_name(stem)))
    return rows


def check_cadquery(made: list[Made], bodies: dict[str, object]) -> tuple[list[dict], list[str]]:
    """The harness's fit check for a part built in CadQuery (name to body): one row per standard part, and the problems."""

    rows = []
    for one in made:
        inside, overlap = [], 0.0
        for name, body in bodies.items():
            volume = float(body.intersect(one.keep).Volume()) if one.keep is not None else 0.0
            if volume > OVERLAP_MM3:
                inside.append(name)
                overlap += volume
        touches = any(body.distance(one.shape) < 0.05 for body in bodies.values())
        rows.append({"name": one.item["name"], "overlap_mm3": round(overlap, 2), "inside": inside, "touches": touches})
    return rows, misfits(made, rows)


def misfits(made: list[Made], fit: list[dict]) -> list[str]:
    """The standard parts the fit check found in material, one line per kind and the bodies it sits in, with what to change."""

    found = {entry["name"]: entry for entry in fit}
    groups: dict[tuple, list[tuple[str, float]]] = {}
    for one in made:
        entry = found.get(one.item["name"]) or {}
        if entry.get("inside"):
            key = (designation(one.item), tuple(entry["inside"]), one.advice)
            groups.setdefault(key, []).append((one.item["name"], float(entry["overlap_mm3"])))
    lines = []
    for (name, inside, advice), pieces in groups.items():
        most = max(volume for _piece, volume in pieces)
        lines.append(
            name + " " + ", ".join(repr(piece) for piece, _volume in pieces) + (" sits " if len(pieces) == 1 else " sit up to ")
            + f"{most:.1f}" + " mm3 inside " + ", ".join(repr(body) for body in inside) + ": " + advice
        )
    return lines


def apply_fit(rows: list[dict], fit: list[dict], problems: list[str]) -> tuple[list[dict], list[str]]:
    """Adds the fit check to the rows (overlap_mm3, touches) and returns the warnings: problems, then parts that touch nothing."""

    found = {entry["name"]: entry for entry in fit}
    warnings = list(problems)
    for row in rows:
        entry = found.get(row["name"], {})
        row["overlap_mm3"] = float(entry.get("overlap_mm3") or 0.0)
        row["touches"] = bool(entry.get("touches"))
        if not row["touches"]:
            warnings.append(row["designation"] + " " + repr(row["name"]) + " touches no printed body of this part: it floats at its seat " + _point(row["seat_mm"]) + ".")
    return rows, warnings


def _text(item: dict) -> str:
    return " ".join([str(item.get("id", "")), str(item.get("name", "")), *[str(a) for a in item.get("aliases", [])]]).lower()


def _thread_in(text: str, size: str) -> bool:
    """ "m3" in "m3 screw and nut set", but not in "m30" or "m3.5"."""

    return re.search(r"(?<![a-z0-9.])" + re.escape(size.lower()) + r"(?![0-9.,])", text) is not None


def _per_piece(item: dict) -> float:
    return float(item["unit_price_eur"]) / max(1, int(item["pack_qty"]))


def _thread_mm(text: str) -> float | None:
    match = re.search(r"(?<![a-z0-9.])m(\d+(?:\.\d+)?)(?![0-9.,])", text)
    return float(match.group(1)) if match else None


def price(row: dict) -> dict:
    """A price per piece for one standard part, through the catalog search part_pick uses.

    A catalog item of the same kind and thread sold in packs (`pack_qty`) gives its sample price per
    piece. Without one the price is estimated from the nearest such item of the closest kind, and the
    line says which item it came from. With a live key bom_build then searches the shops for the line.
    """

    from pai_agent.tools.product import _search, catalog_items

    def priced(item: dict, source: str) -> dict:
        return {
            "unit_price_eur": round(_per_piece(item), 3),
            "shop": str(item.get("shop") or ""),
            "url": str(item.get("url") or ""),
            "price_source": source,
            "pack_qty": int(item["pack_qty"]),
            "priced_from": item["id"],
        }

    words = _KIND_WORDS[row["kind"]]
    query = row["size"] + " " + words[0] + " " + row["line"]
    for item in _search(query, "hardware"):
        text = _text(item)
        if item.get("pack_qty") and _thread_in(text, row["size"]) and any(word in text for word in words):
            # Catalog prices are samples to verify, as for a part_pick.
            return {**row, **priced(item, "sample")}
    size = float(row["size"][1:])
    packs = [item for item in catalog_items() if item.get("category") == "hardware" and item.get("pack_qty")]
    for kind in _PRICED_LIKE[row["kind"]]:
        like = [item for item in packs if any(word in _text(item) for word in _KIND_WORDS[kind])]
        if like:
            nearest = min(like, key=lambda item: abs((_thread_mm(_text(item)) or size) - size))
            quote = priced(nearest, "estimated")
            # The shop page of the item it was priced from shows another part; a search for this one is the honest link.
            quote.update(shop="Amazon DE", url="https://www.amazon.de/s?k=" + quote_plus(row["line"]))
            return {**row, **quote}
    return {**row, "unit_price_eur": 0.0, "shop": "", "url": "https://www.amazon.de/s?k=" + quote_plus(row["line"]), "price_source": "estimated", "priced_from": None}


def tree_nodes(prefix: str, rows: list[dict], nodes: dict[str, list[str]] | None = None) -> list[dict]:
    """CAD-tree children for a part's standard parts, one per designation: "ISO 4762 M3x10 ×4 (hardware)".

    Each lists in `nodes` the GLB nodes its pieces are: the rows' own names in the part's GLB, or for
    the assembly the names its bodies got there (nodes, by bill-of-materials key).
    """

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["key"], []).append(row)
    out = []
    for key, same in groups.items():
        n = len(same)
        names = (nodes or {}).get(key) if nodes is not None else [row["name"] for row in same]
        out.append({"id": prefix + "/" + key, "label": same[0]["designation"] + (" ×" + str(n) if n > 1 else "") + " (hardware)", "nodes": names or [], "children": []})
    return out


def bom_lines(holders: list[tuple[dict, list[dict]]]) -> list[dict]:
    """One bill-of-materials line per kind of standard part, from (spec part, its hardware rows) pairs."""

    lines: dict[str, dict] = {}
    for part, rows in holders:
        for row in rows:
            line = lines.get(row["key"])
            if line is None:
                line = lines[row["key"]] = {
                    "name": row["line"],
                    "qty": 0,
                    "unit_price_eur": float(row.get("unit_price_eur") or 0.0),
                    "weight_g": round(float(row["mass_g"]), 2),
                    "shop": row.get("shop") or "",
                    "url": row.get("url") or "",
                    "price_source": row.get("price_source") or "estimated",
                    "category": row["key"],
                    "role": "hardware",
                    "standard": row["standard"],
                    "size": row["size"],
                    "length_mm": row["length_mm"],
                    **({"brand": row["brand"], "part_number": row["part_number"]} if row["kind"] == "insert" else {}),
                    **({"pack_qty": row["pack_qty"]} if row.get("pack_qty") else {}),
                    "parts": [],
                }
            line["qty"] += int(part.get("qty") or 1)
            if part["id"] not in line["parts"]:
                line["parts"].append(part["id"])
    return list(lines.values())
