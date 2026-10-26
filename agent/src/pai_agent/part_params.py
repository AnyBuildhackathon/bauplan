"""The parameter contract of a part script, and the values the user set for each part.

A part script declares what a person may tune in PARAMS, a dict of plain data at its top:

    PARAMS = {
        "width_mm": {"value": 80.0, "min": 40.0, "max": 160.0, "step": 1.0, "unit": "mm", "label": "Width", "group": "Base"},
        "slots": {"type": "integer", "value": 2, "min": 0, "max": 6, "label": "Cable slots", "group": "Base"},
        "feet": {"value": True, "label": "Feet recesses", "group": "Base"},
        "mount": {"value": "screw", "options": ["screw", "clip"], "label": "Mount", "group": "Back"},
    }

A number has a range, a step and a unit; a whole number says `"type": "integer"`; a True/False value is a switch and
`options` make a choice. `declaration` reads PARAMS from the source without running it, so every problem comes back
before FreeCAD starts; `resolve` turns it, Mechanic's values and the user's into P, the values the script builds with;
`payload` is what the CAD tab shows. The harness (agent/freecad/part_harness.py) then checks that the script reads
only parameters it declares and leaves PARAMS as declared.

The user's values (`BuildState.user_params`, by part id) win over the script's defaults and over Mechanic's values,
also when Mechanic writes the part again; Mechanic replaces one only when the user asks for a new value.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field

TYPES = ("number", "integer", "switch", "choice")
NUMERIC = ("number", "integer")
MAX_PARAMS = 24
_NAME = re.compile(r"[a-z][a-z0-9_]{0,40}")
_KEYS = {
    "number": {"type", "value", "min", "max", "step", "unit", "label", "group"},
    "integer": {"type", "value", "min", "max", "step", "unit", "label", "group"},
    "switch": {"type", "value", "label", "group"},
    "choice": {"type", "value", "options", "label", "group"},
}
_UNITS = {"mm": "mm", "deg": "deg", "g": "g", "n": "N", "pct": "%", "s": "s"}


class ParamsError(ValueError):
    """The declaration or a value does not fit; `problems` lists each one, so all of them are fixed in one go."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(" | ".join(problems))
        self.problems = problems


@dataclass
class Resolved:
    """What one build uses: P, the declaration with Mechanic's numbers inside its ranges, and what became of the user's values."""

    values: dict
    entries: dict
    # The user's values this build uses, Mechanic's values they replaced, and the user's values that no longer fit (with why).
    user: dict = field(default_factory=dict)
    overridden: dict = field(default_factory=dict)
    dropped: dict = field(default_factory=dict)


def label_of(name: str) -> str:
    """'lip_height_mm' -> 'Lip height'."""

    words = re.sub(r"_(" + "|".join(_UNITS) + r")$", "", name).replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def _unit_of(name: str) -> str:
    suffix = name.rsplit("_", 1)[-1] if "_" in name else ""
    return _UNITS.get(suffix, "")


def _auto_step(span: float) -> float:
    # The CAD tab's own rule for a slider without a step.
    return 0.1 if span <= 10 else 0.5 if span <= 50 else 1.0


def _real(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _whole(value: object) -> bool:
    return _real(value) and float(value).is_integer()  # type: ignore[arg-type]


def _kind(spec: dict) -> str:
    if spec.get("type"):
        return str(spec["type"])
    if isinstance(spec.get("value"), bool):
        return "switch"
    return "choice" if "options" in spec else "number"


def _number(name: str, kind: str, spec: dict, problems: list[str]) -> dict | None:
    where = "PARAMS[" + repr(name) + "]"
    if "min" not in spec or "max" not in spec:
        problems.append(where + ": give min and max, the range in which the part still builds and makes sense.")
        return None
    keys = ("value", "min", "max") + (("step",) if "step" in spec else ())
    wrong = [key for key in keys if not (_whole(spec[key]) if kind == "integer" else _real(spec[key]))]
    if wrong:
        problems.append(where + ": " + ", ".join(wrong) + " must be " + ("whole numbers" if kind == "integer" else "numbers") + ".")
        return None
    cast = int if kind == "integer" else float
    value, low, high = cast(spec["value"]), cast(spec["min"]), cast(spec["max"])
    if not low < high:
        problems.append(where + ": min must be below max.")
        return None
    if not low <= value <= high:
        problems.append(where + ": value " + f"{value:g}" + " must lie between min and max.")
        return None
    step = cast(spec["step"]) if "step" in spec else (1 if kind == "integer" else _auto_step(high - low))
    if not 0 < step <= high - low:
        problems.append(where + ": step must be above 0 and at most max - min.")
        return None
    unit = spec.get("unit", _unit_of(name))
    if not isinstance(unit, str) or len(unit) > 12:
        problems.append(where + ": unit must be a short text such as mm, deg or %.")
        return None
    return {"value": value, "min": low, "max": high, "step": step, "unit": unit}


def _choice(name: str, spec: dict, problems: list[str]) -> dict | None:
    where = "PARAMS[" + repr(name) + "]"
    options = spec.get("options")
    if not isinstance(options, list) or not 2 <= len(options) <= 20:
        problems.append(where + ": options must list 2 to 20 choices.")
        return None
    texts = all(isinstance(o, str) and 0 < len(o) <= 40 for o in options)
    if not texts and not all(_real(o) for o in options):
        problems.append(where + ": options must be all short texts or all numbers.")
        return None
    if len(set(options)) != len(options):
        problems.append(where + ": options must differ from each other.")
        return None
    value = spec["value"]
    if isinstance(value, bool) or value not in options:
        problems.append(where + ": value must be one of its options.")
        return None
    return {"value": value, "options": list(options)}


def check(raw: object) -> dict[str, dict]:
    """The declaration in its order with every default filled in: type, value, label, group, and per type its range,
    step and unit or its options. Raises ParamsError listing every problem."""

    if not isinstance(raw, dict):
        raise ParamsError(["PARAMS must be a dict of parameter name to {value, ...}."])
    problems: list[str] = []
    if len(raw) > MAX_PARAMS:
        problems.append("PARAMS declares " + str(len(raw)) + " parameters; keep it to the " + str(MAX_PARAMS) + " a person would tune.")
    entries: dict[str, dict] = {}
    for name, spec in raw.items():
        where = "PARAMS[" + repr(name) + "]"
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            problems.append(where + ": the name must be snake_case like width_mm.")
            continue
        if not isinstance(spec, dict) or "value" not in spec:
            problems.append(where + " must be a dict with at least value.")
            continue
        kind = _kind(spec)
        if kind not in TYPES:
            problems.append(where + ": type must be number, integer, switch or choice.")
            continue
        extra = sorted(str(key) for key in set(spec) - _KEYS[kind])
        if extra:
            problems.append(where + ": a " + kind + " takes " + ", ".join(sorted(_KEYS[kind])) + "; not " + ", ".join(extra) + ".")
            continue
        label, group = spec.get("label", label_of(name)), spec.get("group")
        if not isinstance(label, str) or not 0 < len(label.strip()) <= 40:
            problems.append(where + ": label must be a short name, up to 40 characters.")
            continue
        if group is not None and (not isinstance(group, str) or len(group) > 40):
            problems.append(where + ": group must be a short name, up to 40 characters.")
            continue
        if kind == "switch":
            if not isinstance(spec["value"], bool):
                problems.append(where + ": a switch's value is True or False.")
                continue
            body: dict | None = {"value": spec["value"]}
        elif kind == "choice":
            body = _choice(name, spec, problems)
        else:
            body = _number(name, kind, spec, problems)
        if body is not None:
            entries[name] = {"type": kind, **body, "label": label.strip(), "group": (group or "").strip() or None}
    if problems:
        raise ParamsError(problems)
    return entries


def _writes(tree: ast.AST) -> list[ast.AST]:
    """Every place the script assigns, deletes or sets an item of PARAMS."""

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "PARAMS" and isinstance(node.ctx, (ast.Store, ast.Del)):
            found.append(node)
        elif isinstance(node, (ast.Subscript, ast.Attribute)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if isinstance(node.value, ast.Name) and node.value.id == "PARAMS":
                found.append(node)
    return found


def declaration(source: str) -> tuple[dict[str, dict], object] | None:
    """The script's PARAMS as (checked entries, the literal as written), or None when it declares none.

    PARAMS is read from the source, not run: one `PARAMS = {...}` of plain data at the top level, and every
    parameter it declares named somewhere in the script. Raises ParamsError listing every problem."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        # The sandbox check reports it with its line.
        return None
    writes = _writes(tree)
    if not writes:
        return None
    top = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "PARAMS"
    ]
    if len(top) != 1 or writes != [top[0].targets[0]]:
        raise ParamsError(["Assign PARAMS once, at the top level of the script, and leave it as it is."])
    try:
        raw = ast.literal_eval(top[0].value)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
        raise ParamsError(["PARAMS must be plain data: write every number, text, True/False and list out, without names or arithmetic."]) from exc
    entries = check(raw)
    inside = {id(node) for node in ast.walk(top[0].value)}
    named = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in inside}
    unused = [name for name in entries if name not in named]
    if unused:
        raise ParamsError(
            ["PARAMS declares " + name + ", but the script never reads P[" + repr(name) + "]; read it with its name written out, or remove it." for name in unused]
        )
    return entries, raw


def coerce(name: str, entry: dict, raw: object) -> object:
    """A value as the parameter's type: a float or an int, True or False, or one of its options. Raises ValueError."""

    kind = entry.get("type") or "number"
    if kind == "switch":
        if isinstance(raw, bool):
            return raw
        raise ValueError(name + " is a switch: true or false.")
    if kind == "choice":
        for option in entry["options"]:
            if not isinstance(raw, bool) and raw == option:
                return option
        raise ValueError(name + " must be one of " + ", ".join(str(option) for option in entry["options"]) + ".")
    number = raw
    if isinstance(raw, str):
        try:
            number = float(raw.strip())
        except ValueError:
            number = None
    if not _real(number):
        raise ValueError(name + " must be a number.")
    if kind == "integer":
        if not float(number).is_integer():  # type: ignore[arg-type]
            raise ValueError(name + " must be a whole number.")
        return int(number)  # type: ignore[arg-type]
    return float(number)  # type: ignore[arg-type]


def in_range(name: str, entry: dict, value: object) -> None:
    """Raises ValueError when a number lies outside the parameter's range."""

    if entry.get("type", "number") in NUMERIC and not entry["min"] - 1e-9 <= value <= entry["max"] + 1e-9:  # type: ignore[operator]
        raise ValueError(name + " must be between " + f"{entry['min']:g}" + " and " + f"{entry['max']:g}" + ".")


def resolve(entries: dict[str, dict], agent: dict, user: dict) -> Resolved:
    """P from the declaration: each default, replaced by Mechanic's value, replaced by the user's.

    Mechanic's values must have their parameter's type; a number beyond its range widens that range for this build,
    because Mechanic chose it on purpose. The user's values must fit as declared; one that does not (the part was
    written again with other parameters or ranges) is dropped with the reason. Raises ParamsError for Mechanic's values."""

    entries = {name: dict(entry) for name, entry in entries.items()}
    values = {name: entry["value"] for name, entry in entries.items()}
    problems = []
    for name, raw in agent.items():
        entry = entries.get(name)
        if entry is None:
            problems.append(name + " is not declared in PARAMS; declare every parameter of the request (declared: " + (", ".join(entries) or "none") + ").")
            continue
        try:
            value = coerce(name, entry, raw)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if entry["type"] in NUMERIC:
            entry["min"], entry["max"] = min(entry["min"], value), max(entry["max"], value)
        values[name] = value
    if problems:
        raise ParamsError(problems)
    resolved = Resolved(values=values, entries=entries)
    for name, raw in user.items():
        entry = entries.get(name)
        if entry is None:
            resolved.dropped[name] = "the part has no parameter " + name + " any more"
            continue
        try:
            value = coerce(name, entry, raw)
            in_range(name, entry, value)
        except ValueError as exc:
            resolved.dropped[name] = str(exc)
            continue
        if name in agent and values[name] != value:
            resolved.overridden[name] = values[name]
        values[name] = value
        resolved.user[name] = value
    return resolved


def payload(entries: dict[str, dict], values: dict) -> dict[str, dict]:
    """The CAD tab's params: per parameter its type, value, label and group, with range, step and unit or options."""

    out = {}
    for name, entry in entries.items():
        row = {"type": entry["type"], "value": values.get(name, entry["value"]), "label": entry["label"], "group": entry["group"]}
        if entry["type"] in NUMERIC:
            row.update(min=entry["min"], max=entry["max"], step=entry["step"], unit=entry["unit"])
        elif entry["type"] == "choice":
            row["options"] = list(entry["options"])
        out[name] = row
    return out


def remember(state, key: str, values: dict) -> dict:
    """Records values the user set for one part; returns what the part had before, for `restore`."""

    before = dict(state.user_params.get(key) or {})
    state.user_params[key] = {**before, **values}
    return before


def forget(state, key: str, names) -> dict:
    """Mechanic takes these parameters over (the user asked for new values); returns what the part had before."""

    before = dict(state.user_params.get(key) or {})
    kept = {name: value for name, value in before.items() if name not in set(names)}
    if kept:
        state.user_params[key] = kept
    else:
        state.user_params.pop(key, None)
    return before


def restore(state, key: str, before: dict) -> None:
    if before:
        state.user_params[key] = dict(before)
    else:
        state.user_params.pop(key, None)


def names(raw: object) -> list[str]:
    """The `replace_user_values` argument as a list of parameter names."""

    if isinstance(raw, str):
        raw = [raw]
    return [str(name) for name in raw] if isinstance(raw, (list, tuple)) else []


USER_NOTE = (
    "The user set these with the CAD sliders. They stay through every rebuild and every rewritten script; "
    "change one only when the user asks for a new value, with its name in replace_user_values."
)
# The tool argument of cad_part and cad_update that hands such values back to Mechanic.
REPLACE_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Names of values the user set with the CAD sliders (user_values) that your params replace. Only when the user asked for a new value.",
}
