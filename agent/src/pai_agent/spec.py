"""Product spec for any physical product: validated before anything is built.

Claude writes the spec through the product_spec tool. validate_spec either returns a
normalized copy or raises SpecError with every problem listed, so Claude can fix the
spec and call the tool again. The build after it is deterministic: printed parts come
from cad_part scripts, bought parts from the catalogs, checks from pai_agent.analysis.
"""

from __future__ import annotations

import re

from pai_agent.cad_script import DENSITY_G_CM3

KINDS = ("printed", "bought", "external")
# A requirement names the check that judges it; the check decides pass or fail.
CHECKS = {
    "mass": ("max", ("g", "kg")),
    "cost": ("max", ("eur",)),
    "size": ("max", ("mm",)),
    "tip_over": ("min", ("deg", "n")),
    "deflection": ("max", ("mm",)),
    "torque": ("min", ("x",)),
    "runtime": ("min", ("min", "h", "days")),
    "stability": ("max", ("deg",)),
    "drop": ("max", ("g",)),
    "printable": (None, ()),
}
MAX_PRINTED = 6
MAX_PARTS = 16
MAX_SIZE_MM = 1500.0


class SpecError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return (value or "part")[:40]


def _number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _vector(raw: object, name: str, problems: list[str], positive: bool = False) -> list[float] | None:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        problems.append(name + " must be a list of three numbers in mm.")
        return None
    values = [_number(v) for v in raw]
    if any(v is None for v in values):
        problems.append(name + " must be a list of three numbers in mm.")
        return None
    if positive and any(v <= 0 for v in values):  # type: ignore[operator]
        problems.append(name + " must be positive in all three directions.")
        return None
    if any(abs(v) > MAX_SIZE_MM for v in values):  # type: ignore[arg-type]
        problems.append(name + " is over " + f"{MAX_SIZE_MM:g}" + " mm; units are millimetres.")
        return None
    return [round(float(v), 3) for v in values]  # type: ignore[arg-type]


def _params(raw: object, where: str, problems: list[str]) -> dict[str, float]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        problems.append(where + ".params must be an object of numbers, e.g. {\"width_mm\": 80}.")
        return {}
    out = {}
    for key, value in raw.items():
        number = _number(value.get("value") if isinstance(value, dict) else value)
        if number is None:
            problems.append(where + ".params." + str(key) + " must be a number.")
            continue
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", str(key)):
            problems.append(where + ".params key " + repr(key) + " must be snake_case like width_mm.")
            continue
        out[str(key)] = number
    return out


def _unit(raw: object) -> str:
    unit = str(raw or "").strip().lower().replace("€", "eur").replace("°", "deg").replace("×", "x")
    return {"degree": "deg", "degrees": "deg", "newton": "n", "minutes": "min", "hours": "h", "hour": "h", "day": "days", "euro": "eur"}.get(unit, unit)


def validate_spec(raw: dict) -> dict:
    problems: list[str] = []
    name = str(raw.get("name") or "").strip()
    function = str(raw.get("function") or "").strip()
    if not name:
        problems.append("name is required, e.g. \"Phone stand\".")
    if not function:
        problems.append("function is required: one or two sentences on what the product does.")

    assemblies = []
    seen_assemblies = set()
    for index, entry in enumerate(raw.get("assemblies") or []):
        if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
            problems.append("assemblies[" + str(index) + "] needs a name.")
            continue
        assembly_id = slug(entry.get("id") or entry["name"])
        if assembly_id in seen_assemblies:
            problems.append("assembly id " + assembly_id + " is used twice.")
            continue
        seen_assemblies.add(assembly_id)
        assemblies.append({"id": assembly_id, "name": str(entry["name"]).strip()})

    parts = []
    seen = set()
    raw_parts = raw.get("parts") or []
    if not isinstance(raw_parts, list) or not raw_parts:
        problems.append("parts must list every part: printed ones you design, bought ones you order, external loads such as the phone it holds.")
        raw_parts = []
    if len(raw_parts) > MAX_PARTS:
        problems.append("Keep the spec to " + str(MAX_PARTS) + " parts or fewer; merge small hardware into one line.")
    for index, entry in enumerate(raw_parts):
        where = "parts[" + str(index) + "]"
        if not isinstance(entry, dict):
            problems.append(where + " must be an object.")
            continue
        part_name = str(entry.get("name") or "").strip()
        if not part_name:
            problems.append(where + " needs a name.")
            continue
        part_id = slug(entry.get("id") or part_name)
        where = "part " + part_id
        if part_id in seen:
            problems.append(where + ": the id is used twice.")
            continue
        seen.add(part_id)
        kind = str(entry.get("kind") or "").strip().lower()
        if kind not in KINDS:
            problems.append(where + ": kind must be printed, bought or external.")
            continue
        qty = entry.get("qty", 1)
        if not isinstance(qty, (int, float)) or int(qty) != qty or not 1 <= qty <= 100:
            problems.append(where + ": qty must be a whole number from 1 to 100.")
            qty = 1
        assembly = slug(entry["assembly"]) if entry.get("assembly") else None
        if assembly and assembly not in seen_assemblies:
            problems.append(where + ": assembly " + assembly + " is not in assemblies.")
            assembly = None
        part = {
            "id": part_id,
            "name": part_name,
            "kind": kind,
            "qty": int(qty),
            "assembly": assembly,
            "description": str(entry.get("description") or "").strip(),
            "size_mm": _vector(entry.get("size_mm"), where + ".size_mm", problems, positive=True),
            "position_mm": _vector(entry.get("position_mm"), where + ".position_mm", problems),
            "rotation_deg": _vector(entry.get("rotation_deg"), where + ".rotation_deg", problems),
        }
        if kind == "printed":
            material = str(entry.get("material") or "PLA").strip().upper().replace("ALUMINUM", "ALUMINIUM")
            if material not in DENSITY_G_CM3:
                problems.append(where + ": material must be one of " + ", ".join(sorted(DENSITY_G_CM3)) + ".")
            if len(part["description"]) < 20:
                problems.append(where + ": description must say the shape, features and where it sits in the assembly (20 characters or more).")
            if part["size_mm"] is None:
                problems.append(where + ": size_mm [x, y, z] is required, the rough envelope the script is checked against.")
            part["material"] = material
            part["params"] = _params(entry.get("params"), where, problems)
        else:
            mass = _number(entry.get("mass_g"))
            if kind == "external" and (mass is None or mass <= 0):
                problems.append(where + ": an external load needs mass_g (the phone, the water, the plant pot).")
            if kind == "external" and part["position_mm"] is None:
                problems.append(where + ": an external load needs position_mm, the centre of its mass in the assembly.")
            if mass is not None and mass < 0:
                problems.append(where + ": mass_g cannot be negative.")
            part["mass_g"] = mass
            part["category"] = str(entry.get("category") or "").strip().lower()
            part["query"] = str(entry.get("query") or part_name).strip()
        parts.append(part)

    printed = [p for p in parts if p["kind"] == "printed"]
    if raw_parts and not printed:
        problems.append("At least one part must be printed: AnyBuild designs it in FreeCAD.")
    if len(printed) > MAX_PRINTED:
        problems.append("Keep it to " + str(MAX_PRINTED) + " printed parts or fewer, so the build stays short; merge small brackets into their neighbours.")

    requirements = []
    used = set()
    raw_requirements = raw.get("requirements") or []
    if not isinstance(raw_requirements, list) or not raw_requirements:
        problems.append("requirements must list what the product has to meet, each with the check that judges it.")
        raw_requirements = []
    for index, entry in enumerate(raw_requirements):
        where = "requirements[" + str(index) + "]"
        if not isinstance(entry, dict):
            problems.append(where + " must be an object.")
            continue
        text = str(entry.get("text") or "").strip()
        check = str(entry.get("check") or "").strip().lower()
        if not text:
            problems.append(where + " needs text, e.g. \"Weighs under 150 g\".")
            continue
        if check not in CHECKS:
            problems.append(where + ": check must be one of " + ", ".join(CHECKS) + ".")
            continue
        requirement_id = slug(entry.get("id") or check).replace("-", "_")
        if requirement_id in used:
            requirement_id = requirement_id + "_" + str(index + 1)
        used.add(requirement_id)
        direction, units = CHECKS[check]
        requirement = {"id": requirement_id, "text": text, "check": check, "quote": str(entry.get("quote") or "").strip()}
        if direction is not None:
            limit = _number(entry.get(direction))
            if limit is None or limit <= 0:
                problems.append(where + " (" + check + ") needs a positive " + direction + ".")
                continue
            unit = _unit(entry.get("unit")) or units[0]
            if unit not in units:
                problems.append(where + " (" + check + "): unit must be " + " or ".join(units) + ".")
                continue
            if check == "mass" and unit == "kg":
                limit, unit = limit * 1000.0, "g"
            requirement[direction] = limit
            requirement["unit"] = unit
        target = entry.get("part_id")
        if target:
            target = slug(target)
            if target not in seen:
                problems.append(where + ": part_id " + target + " is not a part.")
            requirement["part_id"] = target
        requirements.append(requirement)
    if raw_requirements and not any(r["check"] in {"mass", "cost"} for r in requirements):
        problems.append("Add at least a mass or a cost requirement, so the totals have a limit.")

    if problems:
        raise SpecError(problems)
    return {
        "id": slug(name),
        "name": name,
        "function": function,
        "quote": str(raw.get("quote") or "").strip(),
        "assemblies": assemblies,
        "parts": parts,
        "requirements": requirements,
    }


def part_of(spec: dict, part_id: str) -> dict | None:
    return next((part for part in spec.get("parts", []) if part["id"] == part_id), None)


def find_part(spec: dict, key: str, kind: str | None = None) -> dict | None:
    """A spec part by id, by its name, or by the one id that contains or is contained in the key ("fan-bracket" finds "bracket")."""

    wanted = slug(key)
    parts = [p for p in spec.get("parts", []) if kind is None or p["kind"] == kind]
    for part in parts:
        if part["id"] == wanted or slug(part["name"]) == wanted:
            return part
    near = [p for p in parts if p["id"] in wanted or wanted in p["id"] or slug(p["name"]) in wanted]
    return near[0] if len(near) == 1 else None
