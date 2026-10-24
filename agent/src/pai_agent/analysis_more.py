"""More engineering checks for any product: power, heat and roll-over. Pure functions, numbers in, numbers out.

Power budget: every load draws power_w (or current_a at its voltage_v) times its duty on
average and peak_factor times that at its peak. Loads at another voltage than the supply
go through a regulator at 85 % efficiency. The supply's current limit is max_current_a,
or c_rating x capacity for a battery; headroom is that limit over the peak supply current.

Thermal: the heat leaves the closed box through the wall and then the outer air, in series:
G_box = 1 / (t / (k A) + 1 / (h A)), h = 5 W/m2K natural convection, A the outer area.
Vents add air exchange G_vent = rho cp v A_vent with a natural draft of v = 0.1 m/s, a fan
G_fan = rho cp Q with its airflow Q. The air inside rises dT = P / (G_box + G_vent + G_fan)
above ambient and must stay under the material limit and the component limit.

Roll-over: a vehicle on flat ground tips sideways once the lateral acceleration reaches
the static stability factor SSF = T / (2 h) in g, T the track and h the centre of mass
height. A turn at speed v on radius r needs v^2 / (r g). The side slope it stands on is
atan(T / 2h), the forward slope atan(L / 2h), L the wheelbase.
"""

from __future__ import annotations

import math

from pai_agent import analysis

REGULATOR_EFFICIENCY = 0.85
CONVECTION_W_M2K = 5.0
VENT_DRAFT_MPS = 0.1
AIR_RHO_CP = 1.2 * 1005.0
# Thermal conductivity in W/mK and the softening limit of the material in C.
WALL = {
    "PLA": (0.13, 55.0),
    "PETG": (0.20, 75.0),
    "ABS": (0.17, 95.0),
    "ASA": (0.17, 95.0),
    "NYLON": (0.25, 120.0),
    "TPU": (0.20, 60.0),
    "ALUMINIUM": (160.0, 300.0),
}
COMPONENT_LIMIT_C = 70.0


def power_budget(supply: dict, loads: list[dict]) -> dict:
    """supply {kind, voltage_v, max_current_a or c_rating with capacity_mah}; loads [{name, power_w or current_a, voltage_v, duty, peak_factor}]."""

    supply_v = float(supply["voltage_v"])
    if supply.get("max_current_a") is not None:
        limit = float(supply["max_current_a"])
    elif supply.get("c_rating") is not None and supply.get("capacity_mah") is not None:
        limit = float(supply["c_rating"]) * float(supply["capacity_mah"]) / 1000.0
    else:
        raise ValueError(str(supply.get("name")) + " has no max_current_a (or c_rating and capacity_mah). Pick a supply or battery with a current rating.")
    if supply_v <= 0 or limit <= 0:
        raise ValueError("The supply needs a positive voltage_v and current limit.")
    rails: dict[float, dict] = {}
    rows = []
    average_w = peak_w = 0.0
    for load in loads:
        volts = float(load.get("voltage_v") or supply_v)
        power = float(load["power_w"]) if load.get("power_w") is not None else float(load["current_a"]) * volts
        duty = min(max(float(load.get("duty", 1.0)), 0.0), 1.0)
        peak = power * max(float(load.get("peak_factor", 1.0)), 1.0)
        # A load at another voltage costs the regulator's losses on the supply side.
        factor = 1.0 if abs(volts - supply_v) <= 0.05 * supply_v else 1.0 / REGULATOR_EFFICIENCY
        average_w += power * duty * factor
        peak_w += peak * factor
        rail = rails.setdefault(volts, {"voltage_v": volts, "average_a": 0.0, "peak_a": 0.0})
        rail["average_a"] += power * duty / volts
        rail["peak_a"] += peak / volts
        rows.append({"name": load["name"], "voltage_v": volts, "power_w": round(power, 3), "duty": duty, "peak_w": round(peak, 3)})
    if peak_w <= 0:
        raise ValueError("The loads draw no power; give each load power_w or current_a.")
    peak_a = peak_w / supply_v
    result = {
        "supply_voltage_v": supply_v,
        "supply_limit_a": round(limit, 3),
        "average_a": round(average_w / supply_v, 3),
        "peak_a": round(peak_a, 3),
        "average_w": round(average_w, 3),
        "peak_w": round(peak_w, 3),
        "headroom": round(limit / peak_a, 2),
        "rails": [{k: round(v, 3) for k, v in rail.items()} for rail in sorted(rails.values(), key=lambda r: -r["peak_a"])],
        "weakest_rail_v": max(rails.values(), key=lambda r: r["peak_a"])["voltage_v"],
        "loads": rows,
    }
    if str(supply.get("kind") or "").lower() == "battery" or supply.get("capacity_mah") is not None:
        run = analysis.runtime(supply, [{"name": "all loads", "power_w": average_w, "duty": 1.0}])
        result["runtime_h"] = run["runtime_h"]
    return result


def thermal(power_w: float, bbox_mm: list[float], wall_mm: float, material: str, vents_mm2: float = 0.0, fan_m3h: float = 0.0, ambient_c: float = 25.0, component_limit_c: float = COMPONENT_LIMIT_C) -> dict:
    material = material.upper().replace("ALUMINUM", "ALUMINIUM")
    if material not in WALL:
        raise ValueError("Unknown wall material " + material + ".")
    if power_w < 0 or wall_mm <= 0 or min(bbox_mm) <= 0:
        raise ValueError("power_w must not be negative, wall_mm and the box sides positive.")
    conductivity, material_limit = WALL[material]
    a, b, c = (v / 1000.0 for v in bbox_mm)
    area = 2.0 * (a * b + a * c + b * c)
    box = 1.0 / (wall_mm / 1000.0 / (conductivity * area) + 1.0 / (CONVECTION_W_M2K * area))
    vent = AIR_RHO_CP * VENT_DRAFT_MPS * max(vents_mm2, 0.0) / 1e6
    fan = AIR_RHO_CP * max(fan_m3h, 0.0) / 3600.0
    rise = power_w / (box + vent + fan)
    inside = ambient_c + rise
    limit = min(material_limit, component_limit_c)
    return {
        "internal_c": round(inside, 1),
        "rise_c": round(rise, 1),
        "ambient_c": ambient_c,
        "material_limit_c": material_limit,
        "component_limit_c": component_limit_c,
        "limit_c": limit,
        "margin_c": round(limit - inside, 1),
        "area_m2": round(area, 4),
        "conductance_w_k": {"box": round(box, 3), "vents": round(vent, 3), "fan": round(fan, 3)},
        "material": material,
    }


def rollover(track_mm: float, wheelbase_mm: float, com_height_mm: float, speed_mps: float = 0.0, turn_radius_m: float = 0.0) -> dict:
    if min(track_mm, wheelbase_mm, com_height_mm) <= 0:
        raise ValueError("track_mm, wheelbase_mm and the centre of mass height must be positive.")
    ssf = track_mm / (2.0 * com_height_mm)
    turn_g = speed_mps**2 / (turn_radius_m * analysis.GRAVITY) if turn_radius_m > 0 else 0.0
    return {
        "ssf": round(ssf, 3),
        "max_lateral_g": round(ssf, 2),
        "turn_g": round(turn_g, 2),
        "side_slope_deg": round(math.degrees(math.atan(ssf)), 1),
        "forward_slope_deg": round(math.degrees(math.atan(wheelbase_mm / (2.0 * com_height_mm))), 1),
        "rolls_in_turn": turn_g >= ssf,
        "track_mm": round(track_mm, 1),
        "wheelbase_mm": round(wheelbase_mm, 1),
        "com_height_mm": round(com_height_mm, 1),
    }
