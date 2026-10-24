"""Mass, thrust-to-weight, endurance, and price for the selected parts.

Flight time is an estimate, not a stopwatch. Peak watts come from the
motor's published bench point (thrust grams divided by g/W). Hover splits
the craft weight across the motors. Electrical power then scales with
thrust to the 1.5, which is the induced-power exponent. The pack contributes
80 percent of its capacity at the battery's nominal voltage. Below a
thrust-to-weight of 1.05 the craft cannot hover, so the estimate is 0.
A heavier pack never invents extra thrust: the bench figure stays the
1S number printed for that motor.
"""

from __future__ import annotations

from pai_agent.context import Ctx, de
from pai_agent.scene import PART_CATEGORIES
from pai_agent.state import BuildState

_HOVER_TWR = 1.05
_USABLE = 0.8


class PhysicsError(Exception):
    pass


def compute(state: BuildState) -> dict:
    missing = [category for category in PART_CATEGORIES if category not in state.selected]
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

    for category in PART_CATEGORIES:
        part = state.selected[category]
        qty = int(part["bom_qty"])
        mass = float(part["mass_g"])
        if category == "frame" and state.frame_mass_g is not None:
            mass = float(state.frame_mass_g)
        weight += mass * qty
        price += float(part["unit_price_eur"]) * qty
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

    twr = thrust / weight
    minutes = _flight_minutes(weight, motor, battery, twr)
    metrics = {
        "weight_g": round(weight, 1),
        "thrust_g": round(thrust, 1),
        "thrust_to_weight": round(twr, 2),
        "flight_time_min": round(minutes, 1),
        "price_eur": round(price, 2),
        "warnings": warnings,
    }
    state.metrics = metrics
    return metrics


def _flight_minutes(weight_g: float, motor: dict, battery: dict, twr: float) -> float:
    if twr < _HOVER_TWR:
        return 0.0
    qty = int(motor["bom_qty"])
    peak_thrust = float(motor["thrust_g"])
    efficiency = float(motor["efficiency_g_per_w"])
    if peak_thrust <= 0 or efficiency <= 0 or qty <= 0:
        return 0.0
    hover_each = weight_g / qty
    if hover_each > peak_thrust:
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
    return {"ok": True, "detail": detail, **metrics}
