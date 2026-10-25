"""The drone as one dimensioned description, from the chosen parts and the frame parameters.

Everything that draws, weighs or flies the drone reads this: the CAD assembly sizes its motors,
propellers, battery and flight controller from it (`tools/cad.py`), the mission simulator takes
its masses and their positions for the inertia (`mission_sim.py`), and the dashboard scales the
model's parts to it (the `geometry` event). Part ids travel with every entry, so the 3D view,
the simulation and the bill of materials can be checked against each other.

Frame: millimetres, z up, the nose is +y, corners as in `freecad/frame_build.py` (front left at
135 degrees). A field a part does not carry falls back to the reference build's value and is
listed in `assumed`, so a part found on the web with fewer fields still builds and flies.
"""

from __future__ import annotations

import math

from pai_agent.scene import PART_CATEGORIES

# The reference toothpick (1103 15000KV, Gemfan 2020, Matrix 1S AIO, R-Line 550): the fallbacks.
DEFAULT_ARM_MM = 42.5
DEFAULT_THICKNESS_MM = 2.0
DEFAULT_MOTOR = {"diameter_mm": 14.0, "height_mm": 13.5, "shaft_mm": 1.5, "mount_diameter_mm": 6.6, "size": "1103"}
DEFAULT_PROP = {"diameter_mm": 51.0, "blades": 4}
DEFAULT_BATTERY_MM = (59.0, 18.0, 8.0)
DEFAULT_FC_MOUNT_MM = 26.0
DEFAULT_CAMERA_MM = 14.0
# Shared with freecad/frame_build.py: the stack's standoffs, the board, the pack under the plate.
STANDOFF_MM = 3.5
PCB_MM = 1.2
BATTERY_TOP_MM = -1.0
SHAFT_PROUD_MM = 3.3
HUB_HALF_MM = 14.5
ARM_WIDTH_MM = 8.2
PROP_GAP_MM = 4.0

CORNERS = (
    ("front_left", 135.0, -1),
    ("front_right", 45.0, 1),
    ("rear_left", 225.0, 1),
    ("rear_right", 315.0, -1),
)


def _num(part: dict | None, key: str, default: float | None = None) -> float | None:
    try:
        value = float((part or {})[key])
    except (KeyError, TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def stator_mm(size: str | None, bell_mm: float) -> tuple[float, float]:
    """Stator diameter and height from the motor code (1103: 11 by 3 mm, 2207: 22 by 7 mm)."""

    code = "".join(ch for ch in str(size or "") if ch.isdigit())
    if len(code) == 4:
        diameter, height = float(code[:2]), float(code[2:])
        if 0 < diameter < bell_mm and height > 0:
            return diameter, height
    return round(bell_mm * 0.78, 1), round(bell_mm * 0.22, 1)


def _part_mass(state, category: str) -> float:
    """The category's whole mass in the build, every unit of it, as physics_calc counts it."""

    part = state.selected.get(category) or {}
    qty = int(part.get("bom_qty") or 1)
    if category == "frame" and state.frame_mass_g is not None:
        return float(state.frame_mass_g) * qty
    return float(part.get("mass_g") or 0.0) * qty


def geometry(state, params: dict | None = None) -> dict:
    """The drone's parts with their sizes, masses and positions, as the CAD, the sim and the view use them.

    `params` are frame parameters about to be built; by default the last built frame's.
    """

    selected = state.selected
    params = state.cad_params if params is None else params
    params = params or {}
    assumed: list[str] = []

    def pick(part, key, default, label):
        value = _num(part, key)
        if value is None:
            assumed.append(label)
            return float(default)
        return value

    arm = float(params.get("arm_length_mm") or frame_arm_mm(selected))
    thickness = float(params.get("thickness_mm") or DEFAULT_THICKNESS_MM)
    motor_part = selected.get("motor")
    bell = pick(motor_part, "diameter_mm", DEFAULT_MOTOR["diameter_mm"], "motor diameter")
    height = pick(motor_part, "height_mm", DEFAULT_MOTOR["height_mm"], "motor height")
    size = str((motor_part or {}).get("size") or "")
    stator_d, stator_h = stator_mm(size, bell)
    prop_part = selected.get("propeller")
    prop_d = pick(prop_part, "diameter_mm", DEFAULT_PROP["diameter_mm"], "propeller diameter")
    blades = int(_num(prop_part, "blades", DEFAULT_PROP["blades"]) or DEFAULT_PROP["blades"])
    battery_part = selected.get("battery")
    pack = [pick(battery_part, key, default, "battery " + key[:-3]) for key, default in zip(("length_mm", "width_mm", "height_mm"), DEFAULT_BATTERY_MM)]
    fc_part = selected.get("flight_controller")
    mount = pick(fc_part, "mount_mm", DEFAULT_FC_MOUNT_MM, "flight controller mount")
    board = round(mount + 4.0, 1)
    camera_mm = _num(selected.get("camera"), "size_mm", DEFAULT_CAMERA_MM) or DEFAULT_CAMERA_MM

    motor_body = max(height - SHAFT_PROUD_MM, 4.0)
    prop_z = thickness + motor_body + 2.3
    corners = []
    for name, angle, spin in CORNERS:
        a = math.radians(angle)
        corners.append({"name": name, "x_mm": round(arm * math.cos(a), 3), "y_mm": round(arm * math.sin(a), 3), "spin": spin})

    # Every mass with where it sits, so the total matches physics_calc and the inertia follows.
    masses: list[dict] = []

    def add(kind: str, part_id, mass_g: float, pos, shape: str, size_mm) -> None:
        if mass_g > 0:
            masses.append({"kind": kind, "id": part_id, "mass_g": round(mass_g, 4), "pos_mm": [round(v, 3) for v in pos], "shape": shape, "size_mm": [round(v, 3) for v in size_mm]})

    motor_mass = _part_mass(state, "motor") / 4 if motor_part else 0.0
    prop_mass = _part_mass(state, "propeller") / 4 if prop_part else 0.0
    for corner in corners:
        cx, cy = corner["x_mm"], corner["y_mm"]
        add("motor_" + corner["name"], (motor_part or {}).get("id"), motor_mass, (cx, cy, thickness + motor_body / 2), "cylinder", (bell, motor_body))
        # A prop's mass sits along its blades: a disc of radius R * sqrt(2/3) has the same spin inertia as four rods.
        add("propeller_" + corner["name"], (prop_part or {}).get("id"), prop_mass, (cx, cy, prop_z), "disc", (prop_d * math.sqrt(2.0 / 3.0), 0.8))
    if battery_part:
        add("battery", battery_part.get("id"), _part_mass(state, "battery"), (0.0, 0.0, BATTERY_TOP_MM - pack[2] / 2), "box", (pack[1], pack[0], pack[2]))
    if fc_part:
        add("flight_controller", fc_part.get("id"), _part_mass(state, "flight_controller"), (0.0, 0.0, thickness + STANDOFF_MM + PCB_MM / 2), "box", (board, board, PCB_MM + 1.5))
    frame_part = selected.get("frame")
    if frame_part:
        frame_mass = _part_mass(state, "frame")
        hub_area = (2 * HUB_HALF_MM) ** 2
        arm_out = max(arm - HUB_HALF_MM, 1.0)
        arms_area = 4 * arm_out * ARM_WIDTH_MM
        hub_share = hub_area / (hub_area + arms_area)
        add("frame_hub", frame_part.get("id"), frame_mass * hub_share, (0.0, 0.0, thickness / 2), "box", (2 * HUB_HALF_MM, 2 * HUB_HALF_MM, thickness))
        mid = HUB_HALF_MM + arm_out / 2
        for corner in corners:
            a = math.atan2(corner["y_mm"], corner["x_mm"])
            add("frame_arm_" + corner["name"], frame_part.get("id"), frame_mass * (1 - hub_share) / 4, (mid * math.cos(a), mid * math.sin(a), thickness / 2), "box", (ARM_WIDTH_MM, arm_out, thickness))
    if selected.get("camera"):
        add("camera", selected["camera"].get("id"), _part_mass(state, "camera"), (0.0, HUB_HALF_MM, thickness + 8.0), "box", (camera_mm, camera_mm, camera_mm))
    if selected.get("canopy"):
        add("canopy", selected["canopy"].get("id"), _part_mass(state, "canopy"), (0.0, 0.0, thickness + 7.0), "box", (board, board, 6.0))
    hardware = selected.get("hardware")
    if hardware:
        each = _part_mass(state, "hardware") / 4
        for corner in corners:
            add("hardware_" + corner["name"], hardware.get("id"), each, (corner["x_mm"], corner["y_mm"], thickness / 2), "box", (3.0, 3.0, 2.0))
    # Any other category the catalog adds later still counts, at the centre.
    for category in PART_CATEGORIES:
        if category in {"motor", "propeller", "battery", "flight_controller", "frame", "camera", "canopy", "hardware"}:
            continue
        part = selected.get(category)
        if part:
            add(category, part.get("id"), _part_mass(state, category), (0.0, 0.0, thickness), "box", (10.0, 10.0, 5.0))
    total = sum(m["mass_g"] for m in masses)
    com = [sum(m["mass_g"] * m["pos_mm"][i] for m in masses) / total if total else 0.0 for i in range(3)]
    clearance = arm * math.sqrt(2.0) - prop_d
    return {
        "arm_length_mm": round(arm, 3),
        "thickness_mm": round(thickness, 3),
        "motor_spacing_mm": round(_num(motor_part, "mount_diameter_mm", DEFAULT_MOTOR["mount_diameter_mm"]) or 6.6, 2),
        "motor": {
            "id": (motor_part or {}).get("id"),
            "bell_diameter_mm": bell,
            "height_mm": height,
            "stator_diameter_mm": stator_d,
            "stator_height_mm": stator_h,
            "shaft_mm": _num(motor_part, "shaft_mm", DEFAULT_MOTOR["shaft_mm"]),
            "size": size or None,
        },
        "propeller": {"id": (prop_part or {}).get("id"), "diameter_mm": prop_d, "pitch_in": _num(prop_part, "pitch_in"), "blades": blades, "z_mm": round(prop_z, 3)},
        "battery": {"id": (battery_part or {}).get("id"), "size_mm": pack},
        "flight_controller": {"id": (fc_part or {}).get("id"), "mount_mm": mount, "board_mm": board},
        "camera_mm": camera_mm,
        "corners": corners,
        "prop_clearance_mm": round(clearance, 1),
        "props_clear": clearance >= PROP_GAP_MM,
        "masses": masses,
        "total_mass_g": round(total, 2),
        "com_mm": [round(v, 3) for v in com],
        "assumed": assumed,
    }


def min_arm_mm(prop_diameter_mm: float) -> float:
    """The shortest arm at which neighbouring props keep the gap: they stand arm * sqrt(2) apart."""

    return (prop_diameter_mm + PROP_GAP_MM) / math.sqrt(2.0)


def frame_arm_mm(selected: dict) -> float:
    """Centre to motor shaft before a CAD frame exists: the chosen frame's arm, else half its
    wheelbase (motor to motor across the diagonal), else the shortest arm the props clear."""

    frame = selected.get("frame")
    arm = _num(frame, "arm_length_mm")
    if arm is None and _num(frame, "wheelbase_mm"):
        arm = float(frame["wheelbase_mm"]) / 2.0
    if arm is None and _num(selected.get("propeller"), "diameter_mm"):
        arm = min_arm_mm(float(selected["propeller"]["diameter_mm"]))
    return arm or DEFAULT_ARM_MM


def view(geo: dict) -> dict:
    """What the dashboard needs to size the model's parts, without the mass list."""

    return {
        "type": "geometry",
        "arm_length_mm": geo["arm_length_mm"],
        "thickness_mm": geo["thickness_mm"],
        "motor": geo["motor"],
        "propeller": geo["propeller"],
        "battery": geo["battery"],
        "flight_controller": geo["flight_controller"],
        "prop_clearance_mm": geo["prop_clearance_mm"],
        "total_mass_g": geo["total_mass_g"],
        "assumed": geo["assumed"],
    }


async def publish_geometry(ctx) -> None:
    """Sends the `geometry` event when the drone's parts or frame changed since the last one."""

    state = ctx.state
    if state.product != "drone" or not state.selected:
        return
    shown = view(geometry(state))
    if shown == state.geometry_shown:
        return
    state.geometry_shown = shown
    await ctx.emit(shown)
