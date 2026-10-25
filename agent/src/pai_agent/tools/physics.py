"""Mass, thrust-to-weight, endurance, price and flight performance for the selected parts.

Flight time is an estimate, not a stopwatch. Peak watts come from the
motor's published bench point (thrust grams divided by g/W). Hover splits
the craft weight across the motors. Electrical power then comes from the
motor's published load table, or, for a motor with only its 100 % row, scales
with thrust to the 1.5, which is the induced-power exponent. The pack contributes
80 percent of its capacity at the battery's nominal voltage. Below a
thrust-to-weight of 1.05 the craft cannot hover, so the estimate is 0.
A heavier pack never invents extra thrust: the bench figure stays the
1S number printed for that motor.

The flight performance (top speed, acceleration, climb rate, turn rate, roll, flight time at
full speed and full throttle, the inertia of the parts as placed) comes from `pai_agent.flight`,
from the same parts' published specs; every one of those numbers is an estimate with its
assumptions listed. Motor, propeller, battery, flight controller and frame are required; the
camera, canopy, hardware and video transmitter count for mass and price when chosen.
"""

from __future__ import annotations

from pai_agent import printers, web_parts
from pai_agent.context import Ctx, de
from pai_agent.flight import arm_length as arm_length_mm, bench, motor_power_w, performance
from pai_agent.scene import PART_CATEGORIES
from pai_agent.state import BuildState
from pai_agent.tools.parts_search import unit_price_eur

_HOVER_TWR = 1.05
_USABLE = 0.8
REQUIRED = ("motor", "propeller", "battery", "flight_controller", "frame")
# The performance numbers physics_calc shows next to the four core metrics.
PERFORMANCE_KEYS = (
    "top_speed_mps", "top_speed_kmh", "accel_mps2", "climb_rate_mps", "turn_rate_dps", "turn_radius_m",
    "flip_time_s", "flight_time_full_speed_min", "flight_time_full_throttle_min", "time_to_90pct_s",
)


class PhysicsError(Exception):
    pass


def compute(state: BuildState) -> dict:
    missing = [category for category in REQUIRED if category not in state.selected]
    if missing:
        raise PhysicsError("Parts missing: " + ", ".join(missing))

    weight = 0.0
    price = 0.0
    thrust = 0.0
    warnings: list[str] = []
    motor = state.selected["motor"]
    propeller = state.selected["propeller"]
    battery = state.selected["battery"]
    controller = state.selected["flight_controller"]

    for category in [c for c in PART_CATEGORIES if c in state.selected]:
        part = state.selected[category]
        qty = int(part["bom_qty"])
        mass = float(part["mass_g"])
        if category == "frame" and state.frame_mass_g is not None:
            mass = float(state.frame_mass_g)
        weight += mass * qty
        printed = printers.printed_frame(state) if category == "frame" else None
        # With the user's printer the frame is printed: it costs its filament, not the shop price.
        price += (printed["price_eur"] if printed else unit_price_eur(part)) * qty
        if category == "motor":
            thrust += float(part["thrust_g"]) * qty

    if weight <= 0 or thrust <= 0:
        raise PhysicsError("Mass or thrust is 0.")

    bench_prop = motor.get("bench_prop_id")
    if bench_prop and bench_prop != propeller["id"]:
        warnings.append(
            "The thrust figure is for "
            + str(bench_prop)
            + ", not for the chosen propeller."
        )
    if int(battery["cells"]) > int(motor["cells_max"]):
        warnings.append(
            "The battery is "
            + str(battery["cells"])
            + "S, the motors are rated to "
            + str(motor["cells_max"])
            + "S. The calculation uses the datasheet thrust, not a higher voltage."
        )
    if int(battery["cells"]) > int(controller.get("cells_max", 99)):
        warnings.append(
            "The controller is rated to "
            + str(controller["cells_max"])
            + "S, the battery is "
            + str(battery["cells"])
            + "S."
        )
    if state.frame_mass_g is None and state.selected["frame"].get("mass_is_estimate"):
        warnings.append("The frame mass is the estimate until cad_frame weighs the STL.")

    flight = performance(state, weight)
    # Below the motor's test voltage the thrust is scaled down; never up.
    thrust = min(thrust, flight["thrust_g"])
    twr = thrust / weight
    minutes = _flight_minutes(weight, motor, battery, twr)
    warnings += flight.get("warnings", [])
    metrics = {
        "weight_g": round(weight, 1),
        "thrust_g": round(thrust, 1),
        "thrust_to_weight": round(twr, 2),
        "flight_time_min": round(minutes, 1),
        "price_eur": round(price, 2),
        "warnings": warnings,
        **{key: flight.get(key) for key in PERFORMANCE_KEYS},
        "performance": {key: value for key, value in flight.items() if key not in ("warnings",)},
        # The chosen parts' numbers that are estimates, not stated on their pages.
        "estimated_inputs": web_parts.estimated_inputs(state.selected),
    }
    state.metrics = metrics
    return metrics


def _flight_minutes(weight_g: float, motor: dict, battery: dict, twr: float) -> float:
    if twr < _HOVER_TWR:
        return 0.0
    qty = int(motor["bom_qty"])
    peak_thrust = float(motor["thrust_g"])
    if peak_thrust <= 0 or qty <= 0:
        return 0.0
    hover_each = weight_g / qty
    if hover_each > peak_thrust:
        return 0.0
    if bench(motor).get("load_table"):
        hover_watts, _source = motor_power_w(motor, hover_each)
    else:
        efficiency = float(motor["efficiency_g_per_w"])
        if efficiency <= 0:
            return 0.0
        peak_watts = peak_thrust / efficiency
        hover_watts = peak_watts * (hover_each / peak_thrust) ** 1.5
    volts = float(battery["voltage_v"])
    if volts <= 0:
        return 0.0
    amps = (hover_watts * qty) / volts
    if amps <= 0:
        return 0.0
    usable_ah = float(battery["capacity_mah"]) / 1000.0 * _USABLE
    return usable_ah / amps * 60.0


async def physics_calc(ctx: Ctx, args: dict) -> dict:
    del args
    try:
        metrics = compute(ctx.state)
    except PhysicsError as exc:
        return {"ok": False, "error": str(exc), "detail": str(exc)}
    await ctx.emit(
        {
            "type": "metrics",
            "weight_g": metrics["weight_g"],
            "thrust_to_weight": metrics["thrust_to_weight"],
            "flight_time_min": metrics["flight_time_min"],
            "price_eur": metrics["price_eur"],
            **{key: metrics[key] for key in PERFORMANCE_KEYS if metrics.get(key) is not None},
            "estimate": True,
            **({"estimated_inputs": metrics["estimated_inputs"]} if metrics["estimated_inputs"] else {}),
        }
    )
    detail = (
        de(metrics["weight_g"], 1)
        + " g, thrust-to-weight "
        + de(metrics["thrust_to_weight"], 2)
        + ", "
        + de(metrics["flight_time_min"], 1)
        + " min, "
        + de(metrics["price_eur"], 2)
        + " €"
    )
    if metrics.get("top_speed_kmh"):
        detail += ", top speed about " + de(metrics["top_speed_kmh"], 0) + " km/h"
    return {"ok": True, "detail": detail, **metrics}
