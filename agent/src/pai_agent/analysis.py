"""Generic engineering checks for any product. Pure functions, numbers in, numbers out.

Tip-over: the assembly stands on the convex hull of its lowest points. Tilting it
about one hull edge lifts the centre of mass until it is straight above that edge,
so the tip angle is atan(d / h), d the distance from the centre of mass to the edge
in plan view and h its height. The force that tips it, pushed horizontally at height
H, is m g d / H.

Deflection: Euler-Bernoulli beam with a rectangular section, I = b t^3 / 12.
Cantilever: delta = F L^3 / (3 E I), M = F L. Simply supported, load in the middle:
delta = F L^3 / (48 E I), M = F L / 4. Bending stress sigma = M (t / 2) / I.
Printed plastics get a knock-down for layer lines: 85 % of the modulus, 60 % of the strength.

Torque: an actuator gives a usable share of its stall torque (servo 70 %, stepper 80 %,
DC motor 50 %); the safety factor is usable torque over required torque.

Runtime: 80 % of the battery energy over the average power of all loads.
"""

from __future__ import annotations

import math

GRAVITY = 9.80665
# Young's modulus and tensile strength in MPa.
MATERIALS = {
    "PLA": (3500.0, 50.0),
    "PETG": (2100.0, 50.0),
    "ABS": (2000.0, 40.0),
    "ASA": (2000.0, 45.0),
    "NYLON": (1700.0, 50.0),
    "TPU": (30.0, 30.0),
    "ALUMINIUM": (69000.0, 240.0),
    "STEEL": (200000.0, 250.0),
}
PRINTED_E = 0.85
PRINTED_STRENGTH = 0.6
MIN_STRESS_SAFETY = 2.0
USABLE_TORQUE = {"servo": 0.7, "stepper": 0.8, "motor": 0.5}
USABLE_ENERGY = 0.8


def tip_over(footprint_mm: list[list[float]], com_mm: list[float], floor_mm: float, mass_g: float, push_height_mm: float) -> dict:
    """Smallest tip angle over the footprint edges, the direction it tips and the force that tips it."""

    height = com_mm[2] - floor_mm
    if len(footprint_mm) < 3 or height <= 0:
        return {"angle_deg": 0.0, "force_n": 0.0, "margin_mm": 0.0, "direction": [0.0, 1.0], "inside": False}
    best = None
    count = len(footprint_mm)
    for index in range(count):
        ax, ay = footprint_mm[index]
        bx, by = footprint_mm[(index + 1) % count]
        ex, ey = bx - ax, by - ay
        length = math.hypot(ex, ey)
        if length < 1e-6:
            continue
        # Counter-clockwise hull: the outward normal points right of the edge.
        nx, ny = ey / length, -ex / length
        distance = (ax - com_mm[0]) * nx + (ay - com_mm[1]) * ny
        if best is None or distance < best[0]:
            best = (distance, [nx, ny])
    assert best is not None
    distance, direction = best
    lever = max(push_height_mm - floor_mm, 1.0)
    angle = math.degrees(math.atan2(distance, height))
    force = mass_g / 1000.0 * GRAVITY * max(distance, 0.0) / lever
    return {
        "angle_deg": round(angle, 1),
        "force_n": round(force, 2),
        "margin_mm": round(distance, 1),
        "com_height_mm": round(height, 1),
        "push_height_mm": round(lever, 1),
        "direction": [round(direction[0], 3), round(direction[1], 3)],
        "inside": distance > 0,
    }


def deflection(material: str, span_mm: float, width_mm: float, thickness_mm: float, load_n: float, support: str) -> dict:
    material = material.upper().replace("ALUMINUM", "ALUMINIUM")
    if material not in MATERIALS:
        raise ValueError("Unknown material " + material + ".")
    if min(span_mm, width_mm, thickness_mm) <= 0 or load_n < 0:
        raise ValueError("span_mm, width_mm and thickness_mm must be positive and load_n not negative.")
    modulus, strength = MATERIALS[material]
    if material not in {"ALUMINIUM", "STEEL"}:
        modulus *= PRINTED_E
        strength *= PRINTED_STRENGTH
    inertia = width_mm * thickness_mm**3 / 12.0
    if support == "simple":
        delta = load_n * span_mm**3 / (48.0 * modulus * inertia)
        moment = load_n * span_mm / 4.0
    else:
        delta = load_n * span_mm**3 / (3.0 * modulus * inertia)
        moment = load_n * span_mm
    stress = moment * (thickness_mm / 2.0) / inertia
    safety = strength / stress if stress > 0 else 99.0
    return {
        "deflection_mm": round(delta, 3),
        "stress_mpa": round(stress, 2),
        "stress_safety": round(min(safety, 99.0), 2),
        "modulus_mpa": round(modulus, 0),
        "strength_mpa": round(strength, 1),
        "support": "simple" if support == "simple" else "cantilever",
    }


def actuator_torque_nm(item: dict) -> tuple[float, float, str]:
    """Stall torque in N m, the usable share and the actuator family from a catalog item."""

    stall = item.get("stall_torque_nm")
    if stall is None and item.get("stall_torque_kgcm") is not None:
        stall = float(item["stall_torque_kgcm"]) * GRAVITY / 100.0
    if stall is None:
        raise ValueError(str(item.get("name")) + " has no stall_torque_nm. Pick a motor or servo with a torque rating.")
    category = str(item.get("category") or "motor").lower()
    family = "servo" if category == "servo" else "stepper" if "stepper" in str(item.get("id", "")) + category else "motor"
    return float(stall), USABLE_TORQUE[family], family


def torque(item: dict, required_nm: float) -> dict:
    if required_nm <= 0:
        raise ValueError("The required torque must be positive.")
    stall, share, family = actuator_torque_nm(item)
    usable = stall * share
    return {
        "stall_torque_nm": round(stall, 4),
        "usable_torque_nm": round(usable, 4),
        "required_torque_nm": round(required_nm, 4),
        "safety": round(usable / required_nm, 2),
        "family": family,
    }


def runtime(battery: dict, loads: list[dict]) -> dict:
    """loads: {name, power_w, duty}; duty is the share of time the load is on (0 to 1)."""

    if battery.get("capacity_wh") is not None:
        energy = float(battery["capacity_wh"])
    elif battery.get("capacity_mah") is not None and battery.get("voltage_v") is not None:
        energy = float(battery["capacity_mah"]) / 1000.0 * float(battery["voltage_v"])
    else:
        raise ValueError(str(battery.get("name")) + " has no capacity_mah and voltage_v. Pick a battery from the catalog.")
    average = 0.0
    rows = []
    for load in loads:
        power = float(load["power_w"])
        duty = min(max(float(load.get("duty", 1.0)), 0.0), 1.0)
        average += power * duty
        rows.append({"name": load["name"], "power_w": round(power, 4), "duty": round(duty, 5), "average_w": round(power * duty, 5)})
    if average <= 0:
        raise ValueError("The loads draw no power; give each load power_w and duty.")
    hours = energy * USABLE_ENERGY / average
    return {"energy_wh": round(energy, 2), "average_w": round(average, 5), "runtime_h": round(hours, 2), "loads": rows}
