"""Step-by-step build guide from the bill of materials.

Claude writes the steps; this module checks them against the scene parts and the
chosen parts, then publishes one `build_guide` event that the web renders as an
exploded 3D walkthrough. The mock story passes `mock_steps` through the same tool.
"""

from __future__ import annotations

from pai_agent.context import Ctx
from pai_agent.scene import PART_CATEGORIES, PART_TARGETS
from pai_agent.versions import bench_version

MAX_STEPS = 20
MAX_MINUTES = 240

SCHEMA = {
    "name": "build_guide",
    "description": (
        "Writes the step-by-step build guide for the drone's bill of materials. Call it after bom_build, drone only. "
        "Each step names the scene parts to highlight (parts), the tools needed and the minutes it takes. "
        "bom_parts names bill-of-materials categories the step uses that have no scene part of their own, such as camera, canopy or hardware. "
        "Together the steps must cover every scene part. Write title and instructions in English."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_STEPS,
                "items": {
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer", "minimum": 1},
                        "title": {"type": "string"},
                        "instructions": {"type": "string"},
                        "parts": {"type": "array", "items": {"type": "string", "enum": list(PART_TARGETS)}, "minItems": 1},
                        "bom_parts": {"type": "array", "items": {"type": "string", "enum": list(PART_CATEGORIES)}},
                        "tools": {"type": "array", "items": {"type": "string"}},
                        "minutes": {"type": "number", "exclusiveMinimum": 0, "maximum": MAX_MINUTES},
                    },
                    "required": ["n", "title", "instructions", "parts", "tools", "minutes"],
                },
            }
        },
        "required": ["steps"],
    },
}

MOTORS = ("motor_front_left", "motor_front_right", "motor_rear_left", "motor_rear_right")
PROPELLERS = ("propeller_front_left", "propeller_front_right", "propeller_rear_left", "propeller_rear_right")


def _category(target: str) -> str:
    """Scene part to bill-of-materials category: motor_front_left is a motor."""

    for category in ("motor", "propeller"):
        if target.startswith(category + "_"):
            return category
    return target


def _validate(steps: object) -> tuple[list[dict], str | None]:
    if not isinstance(steps, list) or not steps:
        return [], "steps must be a non-empty list"
    if len(steps) > MAX_STEPS:
        return [], f"at most {MAX_STEPS} steps"
    clean: list[dict] = []
    for index, step in enumerate(steps, start=1):
        where = f"step {index}: "
        if not isinstance(step, dict):
            return [], where + "must be an object"
        if step.get("n") != index:
            return [], where + f"n must be {index}, steps are numbered 1, 2, 3 in order"
        title = str(step.get("title") or "").strip()
        instructions = str(step.get("instructions") or "").strip()
        if not title or not instructions:
            return [], where + "title and instructions are required"
        parts = step.get("parts")
        if not isinstance(parts, list) or not parts:
            return [], where + "parts must name at least one scene part"
        unknown = [str(p) for p in parts if p not in PART_TARGETS]
        if unknown:
            return [], where + "unknown parts " + ", ".join(unknown) + "; use " + ", ".join(PART_TARGETS)
        bom_parts = step.get("bom_parts", [])
        if not isinstance(bom_parts, list) or any(c not in PART_CATEGORIES for c in bom_parts):
            return [], where + "bom_parts must name categories from " + ", ".join(PART_CATEGORIES)
        tools = step.get("tools", [])
        if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
            return [], where + "tools must be a list of strings"
        try:
            minutes = float(step.get("minutes"))
        except (TypeError, ValueError):
            return [], where + "minutes must be a number"
        if not 0 < minutes <= MAX_MINUTES:
            return [], where + f"minutes must be above 0 and at most {MAX_MINUTES}"
        clean.append(
            {
                "n": index,
                "title": title,
                "instructions": instructions,
                "parts": list(dict.fromkeys(parts)),
                "bom_parts": list(dict.fromkeys(bom_parts)),
                "tools": [t.strip() for t in tools if t.strip()],
                "minutes": round(minutes, 1),
            }
        )
    covered = {part for step in clean for part in step["parts"]}
    missing = [part for part in PART_TARGETS if part not in covered]
    if missing:
        return [], "no step installs " + ", ".join(missing)
    return clean, None


async def build_guide(ctx: Ctx, args: dict) -> dict:
    if ctx.state.product != "drone":
        message = "The build guide is only available for the drone."
        return {"ok": False, "error": message, "detail": message}
    if not ctx.state.bom:
        message = "No bill of materials yet; call bom_build first."
        return {"ok": False, "error": message, "detail": message}
    steps, error = _validate(args.get("steps"))
    if error:
        return {"ok": False, "error": error, "detail": error}
    for step in steps:
        # The part names come from the build, not from the model's text.
        names = []
        for category in [_category(target) for target in step["parts"]] + step.pop("bom_parts"):
            part = ctx.state.selected.get(category)
            if part and part["name"] not in names:
                names.append(part["name"])
        step["items"] = names
    total = round(sum(step["minutes"] for step in steps), 1)
    guide = {
        "version": bench_version(ctx.state),
        "steps": steps,
        "total_minutes": total,
    }
    await ctx.emit({"type": "build_guide", **guide})
    detail = f"Build guide: {len(steps)} steps, about {total:g} min"
    return {"ok": True, "detail": detail, **guide}


def mock_steps(ctx: Ctx) -> list[dict]:
    """The guide the mock story writes, filled with the parts this build chose."""

    selected = ctx.state.selected
    frame = selected["frame"]
    motor = selected["motor"]["name"]
    propeller = selected["propeller"]["name"]
    battery = selected["battery"]["name"]
    controller = selected["flight_controller"]["name"]
    camera = selected.get("camera")
    canopy = selected.get("canopy")
    bolts = selected.get("hardware")
    arm = ctx.state.cad_params.get("arm_length_mm") or 42.5
    screws = bolts["name"] if bolts else "M1.4 × 3 mm screws"
    hardware = ["hardware"] if bolts else []
    if "printed" in frame["id"]:
        first = {
            "title": "Print and clean the frame",
            "instructions": f"Print frame.stl in PLA (arms {arm:g} mm from the centre to the motor shaft). "
            "Remove the supports and clear the four motor screw holes and the hub holes.",
            "tools": ["3D printer", "Flush cutters", "1.5 mm drill bit"],
            "minutes": 10,
        }
    else:
        first = {
            "title": "Prepare the frame",
            "instructions": f"Unpack the {frame['name']} and check it against frame.step (arms {arm:g} mm from the centre to the motor shaft). "
            "Sand the cut edges lightly so they cannot chafe the motor wires.",
            "tools": ["Fine sandpaper", "Calipers"],
            "minutes": 5,
        }
    steps = [
        {**first, "parts": ["frame"]},
        {
            "title": "Mount the front motors",
            "instructions": f"Screw a {motor} onto each front arm with {screws}, wires pointing to the hub. "
            "Use screws that do not touch the windings.",
            "parts": ["frame", "motor_front_left", "motor_front_right"],
            "bom_parts": hardware,
            "tools": ["1.5 mm hex driver"],
            "minutes": 6,
        },
        {
            "title": "Mount the rear motors",
            "instructions": f"Repeat on the rear arms with the other two {motor}. All four wires point to the hub.",
            "parts": ["frame", "motor_rear_left", "motor_rear_right"],
            "bom_parts": hardware,
            "tools": ["1.5 mm hex driver"],
            "minutes": 6,
        },
        {
            "title": "Seat the flight controller",
            "instructions": f"Put the soft-mount grommets on the stack mount and press the {controller} onto them, arrow facing forward.",
            "parts": ["frame", "flight_controller"],
            "tools": ["Tweezers", "Rubber grommets"],
            "minutes": 5,
        },
        {
            "title": "Solder the motor wires",
            "instructions": "Shorten each motor's three wires to reach its ESC pads and solder them. "
            "Front left and rear right spin one way, front right and rear left the other; swap two wires to reverse a motor.",
            "parts": ["flight_controller", *MOTORS],
            "tools": ["Soldering iron", "Solder", "Wire cutters"],
            "minutes": 15,
        },
    ]
    if camera:
        holder = f" and seat it in the {canopy['name']}" if canopy else ""
        steps.append(
            {
                "title": "Fit the camera",
                "instructions": f"Solder the {camera['name']}'s three wires to the camera pads (5V, GND, video){holder}, lens facing forward.",
                "parts": ["frame", "flight_controller"],
                "bom_parts": ["camera", *(["canopy"] if canopy else [])],
                "tools": ["Soldering iron", "Solder"],
                "minutes": 8,
            }
        )
    holder = f"Slide the {battery} into the battery holder on the canopy" if canopy else f"Strap the {battery} on top of the flight controller"
    steps += [
        {
            "title": "Fit the battery",
            "instructions": f"{holder}, centred so the drone balances on the hub. Do not plug it in yet.",
            "parts": ["battery", "flight_controller"],
            "bom_parts": ["canopy"] if canopy else [],
            "tools": [] if canopy else ["Battery strap"],
            "minutes": 3,
        },
        {
            "title": "Test the motors without propellers",
            "instructions": "Connect USB, open Betaflight, check that the controller reads level, "
            "then plug in the battery and spin each motor slowly in the motor tab to check its direction.",
            "parts": ["flight_controller", "battery", *MOTORS],
            "tools": ["Laptop with Betaflight", "USB cable"],
            "minutes": 8,
        },
        {
            "title": "Fit the propellers",
            "instructions": f"Unplug the battery. Press a {propeller} onto each motor shaft, "
            "matching each propeller's direction to its motor, then check that no blade touches the frame or a neighbour.",
            "parts": list(PROPELLERS),
            "tools": ["Propeller tool"],
            "minutes": 4,
        },
    ]
    return [{"n": n, **step} for n, step in enumerate(steps, start=1)]
