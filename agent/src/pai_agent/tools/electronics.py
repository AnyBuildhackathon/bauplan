"""Wiring diagram and power budget for the electronics of the built product.

Derived from the chosen parts: the supply (a battery or USB), inline parts (socket, switch,
LED resistor), a regulator, the controller, drivers and the loads (motors, pumps, servos,
fans, LEDs, sensors, camera). Every wire carries its voltage and current, every part is
checked against its voltage and current rating, and analysis_more.power_budget gives the
average and peak draw and the runtime on a battery. The drone takes its pins from the
firmware tool's wiring table.

Ratings the catalog does not list get a stated default here (see GAPS), never a silent guess.
"""

from __future__ import annotations

import re

from pai_agent import analysis_more
from pai_agent.context import Ctx
from pai_agent.tools.firmware import _MOTORS, _drone_warnings, drone_wiring

LOADS = ("motor", "pump", "servo", "fan", "light", "camera", "sensor")
# A microcontroller pin drives at most this much before it needs a driver (ESP32 and RP2040 are safe at 20 mA).
GPIO_MAX_A = 0.02
# Defaults for ratings the catalog does not list.
REGULATOR_MAX_A = 1.0
USB_MAX_A = 1.5
FC_POWER_W = 1.5
CAMERA_POWER_W = 0.6
LIPO_MAX_CELL_V = 4.35
GAPS = {
    "regulator": "Regulator output limit assumed " + str(REGULATOR_MAX_A) + " A (no max_current_a in the catalog).",
    "usb": "USB supply limit assumed " + str(USB_MAX_A) + " A, the USB-C default without Power Delivery.",
    "c_rating": "Battery discharge limit assumed from its chemistry (no c_rating in the catalog).",
    "fc_power": "Flight controller with video transmitter assumed " + str(FC_POWER_W) + " W.",
    "camera_power": "Camera assumed " + str(CAMERA_POWER_W) + " W.",
    "driver": "Driver without a current rating in the catalog; its load current is not checked.",
}

# Pins per controller family: power input, 3.3 V output, then free GPIO and ADC pins in order.
_PINS = {
    "esp32": {"power": "VIN", "v33": "3V3", "gpio": ["GPIO25", "GPIO26", "GPIO27", "GPIO14"], "adc": ["GPIO34", "GPIO35"]},
    "pico": {"power": "VSYS", "v33": "3V3 OUT", "gpio": ["GP15", "GP14", "GP13", "GP12"], "adc": ["GP26 ADC0", "GP27 ADC1"]},
    "arduino": {"power": "5V", "v33": "3V3", "gpio": ["D3", "D5", "D6", "D9"], "adc": ["A0", "A1"]},
}
_DEFAULT_PINS = {"power": "5V", "v33": None, "gpio": ["IO1", "IO2", "IO3", "IO4"], "adc": ["AIN0", "AIN1"]}


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _text(item: dict) -> str:
    return " ".join(str(item.get(k) or "") for k in ("id", "name", "note"))


def _parts(ctx: Ctx) -> list[dict]:
    """[{key, name, category, qty, item}] for the drone's selected parts or the product's picked parts."""

    state = ctx.state
    rows = []
    if state.spec and state.picked:
        for part in state.spec.get("parts", []):
            item = state.picked.get(part["id"])
            if item is None or part.get("kind") != "bought":
                continue
            category = str(item.get("category") or part.get("category") or "")
            rows.append({"key": part["id"], "name": item["name"], "category": category, "qty": int(part.get("qty") or 1), "item": item})
    else:
        for category, item in state.selected.items():
            rows.append({"key": category, "name": item["name"], "category": category, "qty": int(item.get("bom_qty") or 1), "item": item})
    return rows


def _c_rating(item: dict) -> tuple[float, bool]:
    """Discharge rating in C and whether it is a default."""

    if _num(item.get("c_rating")):
        return float(item["c_rating"]), False
    found = re.search(r"\b(\d{1,3})\s?C\b", str(item.get("note") or "") + " " + str(item.get("name") or ""))
    if found:
        return float(found[1]), False
    text = _text(item).lower()
    if "18650" in text or "li-ion" in text:
        return 2.0, True
    if "aa" in text.split("-") or "alkaline" in text:
        return 0.5, True
    return 20.0, True


def _supply_of(rows: list[dict]) -> dict | None:
    """The part that feeds everything: a battery with capacity, else a power part with a current rating, else a cable or adapter."""

    batteries = [r for r in rows if r["category"] == "battery" and _num(r["item"].get("capacity_mah"))]
    if batteries:
        return batteries[0]
    power = [r for r in rows if r["category"] == "power" and _num(r["item"].get("voltage_v"))]
    for test in (lambda r: _num(r["item"].get("max_current_a")), lambda r: re.search(r"cable|adapter|psu|supply", r["name"], re.I)):
        found = [r for r in power if test(r)]
        if found:
            return found[0]
    return power[0] if power else None


def _wire_color_key(volts: float | None, kind: str) -> str:
    if kind == "signal":
        return "signal"
    if kind == "phase":
        return "phase"
    if volts is None:
        return "power"
    if volts <= 3.6:
        return "3v3"
    if volts <= 4.4:
        return "1s"
    if volts <= 5.5:
        return "5v"
    return "high"


class _Plan:
    def __init__(self) -> None:
        self.blocks: list[dict] = []
        self.wires: list[dict] = []
        self.warnings: list[dict] = []
        self.gaps: list[str] = []
        self.loads: list[dict] = []

    def block(self, block_id: str, name: str, role: str, col: int, voltage_v=None, rating: str = "", qty: int = 1) -> str:
        row = sum(1 for b in self.blocks if b["col"] == col)
        self.blocks.append({"id": block_id, "name": name, "role": role, "col": col, "row": row, "voltage_v": voltage_v, "rating": rating, "qty": qty})
        return block_id

    def wire(self, source: str, target: str, kind: str, volts, current_a=None, source_pin: str = "", target_pin: str = "", label: str = "") -> None:
        if not label:
            label = (f"{volts:g} V" if volts is not None and kind != "signal" else "") + (f" {current_a:.2f} A" if current_a else "")
        self.wires.append(
            {
                "id": "w" + str(len(self.wires) + 1),
                "from": source,
                "to": target,
                "from_pin": source_pin,
                "to_pin": target_pin,
                "kind": kind,
                "voltage_v": volts,
                "current_a": None if current_a is None else round(current_a, 3),
                "color": _wire_color_key(volts, kind),
                "label": label.strip(),
            }
        )

    def warn(self, part: str, text: str, severity: str = "fail") -> None:
        self.warnings.append({"part": part, "text": text, "severity": severity})

    def gap(self, key: str) -> None:
        if GAPS[key] not in self.gaps:
            self.gaps.append(GAPS[key])

    def check_voltage(self, name: str, rated, volts: float, has_resistor: bool = False) -> None:
        rated = _num(rated)
        if rated is None or has_resistor:
            return
        if volts > rated * 1.1:
            self.warn(name, f"{name} gets {volts:g} V, it is rated for {rated:g} V.")
        elif volts < rated * 0.75:
            self.warn(name, f"{name} gets only {volts:g} V of its {rated:g} V; it runs weak.", "warn")


def _drone(ctx: Ctx, rows: list[dict], plan: _Plan) -> dict | None:
    by = {r["category"]: r for r in rows}
    battery, fc, motor, camera = by.get("battery"), by.get("flight_controller"), by.get("motor"), by.get("camera")
    if not battery:
        return None
    item = battery["item"]
    cells = int(item.get("cells") or 1)
    volts = float(item.get("voltage_v") or 3.7 * cells)
    c_rating, assumed = _c_rating(item)
    if assumed:
        plan.gap("c_rating")
    limit_a = c_rating * float(item.get("capacity_mah") or 0) / 1000.0
    plan.block("battery", battery["name"], "supply", 0, volts, f"{cells}S {item.get('capacity_mah', '?')} mAh, {c_rating:g}C = {limit_a:.0f} A")
    mass_g = _num(ctx.state.metrics.get("weight_g")) or sum(float(r["item"].get("mass_g") or 0) * r["qty"] for r in rows)
    motor_count = motor["qty"] if motor else 0
    hover_w = full_w = 0.0
    if motor:
        efficiency = float(motor["item"].get("efficiency_g_per_w") or 2.0)
        thrust_g = float(motor["item"].get("thrust_g") or 0)
        full_w = thrust_g / efficiency
        # The same hover model as physics_calc: power scales with thrust to the 1.5.
        hover_w = full_w * min(mass_g / max(motor_count, 1) / thrust_g, 1.0) ** 1.5 if thrust_g else 0.0
    if fc:
        fc_item = fc["item"]
        esc = re.search(r"(\d+(?:\.\d+)?)\s?A ESC", fc_item.get("note") or "") or re.search(r"-(\d+)a-", fc_item.get("id") or "")
        esc_a = float(esc[1]) if esc else None
        max_v = float(fc_item.get("cells_max") or cells) * LIPO_MAX_CELL_V
        rating = f"{fc_item.get('cells_max', '?')}S max ({max_v:.2f} V)" + (f", ESC {esc_a:g} A per motor" if esc_a else "")
        plan.block("fc", fc["name"], "controller", 1, volts, rating)
        peak_total_a = (full_w * motor_count + FC_POWER_W + (CAMERA_POWER_W if camera else 0)) / volts
        plan.wire("battery", "fc", "power", volts, peak_total_a, "+", "VBAT")
        if volts > max_v:
            plan.warn(fc["name"], f"{battery['name']} gives {volts:g} V ({cells}S), the {fc['name']} takes at most {max_v:.2f} V ({fc_item.get('cells_max')}S). It burns out.")
        plan.loads.append({"name": fc["name"], "power_w": FC_POWER_W, "voltage_v": volts, "duty": 1.0})
        plan.gap("fc_power")
        if motor:
            motor_v_max = float(motor["item"].get("cells_max") or cells) * LIPO_MAX_CELL_V
            for pad, _target, position, spin in _MOTORS[:motor_count]:
                block_id = "motor_" + pad.lower()
                plan.block(block_id, f"{pad} {position}", "load", 2, volts, f"{motor['name']}, {spin}")
                plan.wire("fc", block_id, "phase", volts, full_w / volts, "ESC " + pad, "3 phase")
                if esc_a and full_w / volts > esc_a:
                    plan.warn(motor["name"], f"{motor['name']} pulls {full_w / volts:.1f} A at full throttle, the ESC gives {esc_a:g} A.")
            if volts > motor_v_max:
                plan.warn(motor["name"], f"{motor['name']} is rated for {motor['item'].get('cells_max')}S ({motor_v_max:.2f} V), the battery gives {volts:g} V.")
            plan.loads.append(
                {"name": f"{motor_count} x {motor['name']} (hover)", "power_w": hover_w * motor_count, "voltage_v": volts, "duty": 1.0, "peak_factor": full_w / hover_w if hover_w else 1.0}
            )
        if camera:
            plan.block("camera", camera["name"], "load", 2, 5.0, "5 V")
            plan.wire("fc", "camera", "power", 5.0, CAMERA_POWER_W / 5.0, "5V", "VCC")
            plan.wire("camera", "fc", "signal", None, None, "video", "CAM", "video")
            plan.loads.append({"name": camera["name"], "power_w": CAMERA_POWER_W, "voltage_v": 5.0, "duty": 1.0})
            plan.gap("camera_power")
    # The firmware check lines are the same cell checks; they only add what this plan has not said.
    said = " ".join(w["text"] for w in plan.warnings)
    for text in _drone_warnings(fc["item"] if fc else None, motor["item"] if motor else None, item):
        if battery["name"] not in said:
            plan.warn("battery", text)
    return {"kind": "battery", "name": battery["name"], "voltage_v": volts, "capacity_mah": item.get("capacity_mah"), "c_rating": c_rating}


def _product(rows: list[dict], plan: _Plan) -> dict | None:
    supply = _supply_of(rows)
    if supply is None:
        return None
    item = supply["item"]
    volts = float(item["voltage_v"])
    is_battery = _num(item.get("capacity_mah")) is not None
    budget_supply = {"kind": "battery" if is_battery else "supply", "name": supply["name"], "voltage_v": volts}
    if is_battery:
        # A battery rated in amps instead of C still needs its capacity for the runtime.
        budget_supply["capacity_mah"] = float(item["capacity_mah"])
    if _num(item.get("max_current_a")):
        budget_supply["max_current_a"] = float(item["max_current_a"])
    elif is_battery:
        c_rating, assumed = _c_rating(item)
        if assumed:
            plan.gap("c_rating")
        budget_supply.update(c_rating=c_rating, capacity_mah=float(item["capacity_mah"]))
    else:
        found = re.search(r"(\d+(?:\.\d+)?)\s?A\b", supply["name"] + " " + str(item.get("note") or ""))
        budget_supply["max_current_a"] = float(found[1]) if found else USB_MAX_A
        if not found:
            plan.gap("usb")
    limit = budget_supply.get("max_current_a") or budget_supply["c_rating"] * budget_supply["capacity_mah"] / 1000.0
    rating = f"{volts:g} V, {limit:.2f} A" + (f", {item['capacity_mah']:g} mAh" if is_battery else "")
    col = 0
    tail = plan.block(supply["key"], supply["name"], "supply", col, volts, rating)

    def chain(row: dict, role: str, out_v: float, pin: str, rating_text: str = "") -> None:
        nonlocal tail, col, volts
        col += 1
        plan.block(row["key"], row["name"], role, col, out_v, rating_text)
        plan.wire(tail, row["key"], "power", volts, None, "+", pin)
        tail, volts = row["key"], out_v

    # Inline: sockets and connectors, the switch, then a regulator that sets the rail.
    for row in rows:
        if row is not supply and row["category"] == "power":
            chain(row, "connector", volts, "VBUS", f"{volts:g} V in")
    for row in rows:
        if row["category"] == "switch":
            chain(row, "switch", volts, "IN", "on/off")
    regulator = next((r for r in rows if r["category"] in ("battery", "regulator") and r is not supply and not _num(r["item"].get("capacity_mah"))), None)
    if regulator:
        out_v = float(regulator["item"].get("voltage_v") or volts)
        reg_limit = _num(regulator["item"].get("max_current_a")) or REGULATOR_MAX_A
        if not _num(regulator["item"].get("max_current_a")):
            plan.gap("regulator")
        chain(regulator, "regulator", out_v, "IN", f"{volts:g} V to {out_v:g} V, {reg_limit:g} A")
    rail_v, rail_source = volts, tail

    controller = next((r for r in rows if r["category"] in ("controller", "flight_controller")), None)
    drivers = [r for r in rows if r["category"] == "driver"]
    loads = [r for r in rows if r["category"] in LOADS]
    resistor = next((r for r in rows if r["category"] == "resistor"), None)
    pins = dict(_DEFAULT_PINS)
    gpio_n = adc_n = 0
    load_col = col + 1
    if controller:
        family = next((key for key in _PINS if key in _text(controller["item"]).lower()), None)
        pins = _PINS.get(family or "", _DEFAULT_PINS)
        c_item = controller["item"]
        plan.block(controller["key"], controller["name"], "controller", col + 1, rail_v, f"{c_item.get('voltage_v', rail_v):g} V in")
        power_w = float(c_item.get("power_w") or 0.25)
        plan.wire(rail_source, controller["key"], "power", rail_v, power_w * float(c_item.get("peak_factor") or 1) / rail_v, "+", pins["power"])
        plan.check_voltage(controller["name"], c_item.get("voltage_v"), rail_v)
        plan.loads.append({"part_id": controller["key"], "name": controller["name"], "power_w": power_w, "voltage_v": rail_v, "duty": 1.0, "peak_factor": float(c_item.get("peak_factor") or 1), "sleep_power_w": _num(c_item.get("sleep_power_w"))})
        load_col = col + 2
    if drivers:
        for driver in drivers:
            plan.block(driver["key"], driver["name"], "driver", load_col, rail_v, f"{driver['item']['max_current_a']:g} A" if _num(driver["item"].get("max_current_a")) else "")
            if controller:
                pin = pins["gpio"][gpio_n % len(pins["gpio"])]
                gpio_n += 1
                plan.wire(controller["key"], driver["key"], "signal", None, None, pin, "IN", pin)
        load_col += 1
    driven: dict[str, list[float]] = {d["key"]: [] for d in drivers}
    for index, row in enumerate(sorted(loads, key=lambda r: r["category"] == "sensor")):
        item = row["item"]
        rated = _num(item.get("voltage_v"))
        power_w = float(item.get("power_w") or 0.0) * row["qty"]
        peak_factor = float(item.get("peak_factor") or 1.0)
        qty = f"{row['qty']} x " if row["qty"] > 1 else ""
        bare_led = row["category"] == "light" and rated is not None and rated < rail_v * 0.9
        if bare_led and resistor:
            plan.block(resistor["key"], resistor["name"], "inline", load_col, None, "LED series resistor")
        plan.block(row["key"], qty + row["name"], "sensor" if row["category"] == "sensor" else "load", load_col + (1 if bare_led and resistor else 0), rated, f"{rated:g} V, {item.get('power_w', '?')} W" if rated else "")
        feed_v = rail_v
        if row["category"] == "sensor" and controller and rated and rated <= 3.6 and pins.get("v33"):
            feed_v = 3.3
            plan.wire(controller["key"], row["key"], "power", 3.3, power_w / 3.3, pins["v33"], "VCC")
            plan.wire(row["key"], controller["key"], "signal", None, None, "AOUT", pins["adc"][adc_n % len(pins["adc"])], pins["adc"][adc_n % len(pins["adc"])])
            adc_n += 1
        elif row["category"] == "sensor":
            plan.wire(rail_source, row["key"], "power", rail_v, power_w / rail_v, "+", "VCC")
            if controller:
                plan.wire(row["key"], controller["key"], "signal", None, None, "OUT", pins["adc"][adc_n % len(pins["adc"])], pins["adc"][adc_n % len(pins["adc"])])
                adc_n += 1
        elif row["category"] in ("motor", "pump") and drivers:
            driver = drivers[min(index, len(drivers) - 1)]
            current = power_w * peak_factor / rail_v
            driven[driver["key"]].append(current)
            plan.wire(driver["key"], row["key"], "power", rail_v, current, "OUT", "+")
        elif bare_led:
            current = float(item.get("power_w") or 0.0) / rated
            if resistor:
                ohms = (rail_v - rated) / current if current else 0
                heat_w = (rail_v - rated) * current
                found = re.search(r"(\d+(?:\.\d+)?)\s?W\b", resistor["name"])
                res_rating = float(found[1]) if found else None
                plan.blocks[-2]["rating"] = f"needs {ohms:.1f} ohm, burns {heat_w:.2f} W"
                plan.wire(rail_source, resistor["key"], "power", rail_v, current, "+", "R")
                plan.wire(resistor["key"], row["key"], "power", rated, current, "R", "LED+", f"{rated:g} V {current:.2f} A")
                if res_rating and heat_w > res_rating:
                    plan.warn(resistor["name"], f"{resistor['name']} burns {heat_w:.2f} W, it is rated for {res_rating:g} W.")
                plan.loads.append({"part_id": row["key"], "name": row["name"] + " and resistor", "power_w": rail_v * current * row["qty"], "voltage_v": rail_v, "duty": 1.0})
                continue
            plan.wire(rail_source, row["key"], "power", rail_v, current, "+", "LED+")
            plan.warn(row["name"], f"{row['name']} is a {rated:g} V LED on the {rail_v:g} V rail with no series resistor or constant-current driver. It burns out.")
            plan.loads.append({"part_id": row["key"], "name": row["name"], "power_w": rail_v * current * row["qty"], "voltage_v": rail_v, "duty": 1.0})
            continue
        else:
            current = power_w * peak_factor / rail_v
            plan.wire(rail_source, row["key"], "power", rail_v, current, "+", "V+")
            if controller and row["category"] in ("servo", "light"):
                pin = pins["gpio"][gpio_n % len(pins["gpio"])]
                gpio_n += 1
                plan.wire(controller["key"], row["key"], "signal", None, None, pin, "SIG" if row["category"] == "servo" else "DIN", pin)
            elif controller and row["category"] in ("motor", "pump"):
                pin = pins["gpio"][gpio_n % len(pins["gpio"])]
                gpio_n += 1
                if current > GPIO_MAX_A:
                    plan.warn(row["name"], f"{row['name']} pulls {current:.2f} A; a controller pin gives {GPIO_MAX_A * 1000:.0f} mA. Add a MOSFET or motor driver.")
        plan.check_voltage(row["name"], rated, feed_v)
        plan.loads.append({"part_id": row["key"], "name": qty + row["name"], "power_w": power_w, "voltage_v": feed_v, "duty": 1.0, "peak_factor": peak_factor})
    for driver in drivers:
        rating = _num(driver["item"].get("max_current_a"))
        total = sum(driven[driver["key"]])
        if rating is None and total:
            plan.gap("driver")
        elif rating is not None and total > rating:
            plan.warn(driver["name"], f"{driver['name']} switches {total:.2f} A, it is rated for {rating:g} A.")
    if regulator:
        rail_peak = sum(load["power_w"] * load.get("peak_factor", 1.0) / rail_v for load in plan.loads)
        reg_limit = _num(regulator["item"].get("max_current_a")) or REGULATOR_MAX_A
        if rail_peak > reg_limit:
            plan.warn(regulator["name"], f"The {rail_v:g} V rail peaks at {rail_peak:.2f} A, {regulator['name']} gives {reg_limit:g} A.")
    return budget_supply


def _apply_duties(ctx: Ctx, plan: _Plan) -> None:
    """Duty cycles from the stored runtime or power check: the share of time each load is on, plus extra named loads."""

    stored = (ctx.state.checks.get("runtime") or ctx.state.checks.get("power") or {}).get("args") or {}
    known = {load.get("part_id") for load in plan.loads}
    rows = []
    for given in stored.get("loads") or []:
        if not isinstance(given, dict):
            continue
        duty = _num(given.get("duty"))
        for load in plan.loads:
            if given.get("part_id") and load.get("part_id") == given["part_id"] and duty is not None:
                load["duty"] = min(max(duty, 0.0), 1.0)
        if not given.get("part_id") or given["part_id"] not in known:
            power = _num(given.get("power_w"))
            if power:
                rows.append({"name": str(given.get("name") or "other load"), "power_w": power, "voltage_v": None, "duty": duty if duty is not None else 1.0})
    for load in list(plan.loads):
        sleep = load.pop("sleep_power_w", None)
        if sleep and load["duty"] < 1.0:
            plan.loads.append({"name": load["name"] + " asleep", "power_w": sleep, "voltage_v": load["voltage_v"], "duty": 1.0 - load["duty"]})
    plan.loads += rows


def _budget(supply: dict, plan: _Plan) -> dict:
    loads = [{k: v for k, v in load.items() if k in ("name", "power_w", "voltage_v", "duty", "peak_factor")} for load in plan.loads if load["power_w"] > 0]
    result = analysis_more.power_budget(supply, loads)
    for row in result["loads"]:
        row["average_w"] = round(row["power_w"] * row["duty"], 4)
        row["current_a"] = round(row["peak_w"] / row["voltage_v"], 3)
    if result["headroom"] < 1.0:
        plan.warn(supply["name"], f"{supply['name']} gives {result['supply_limit_a']:.2f} A, the build peaks at {result['peak_a']:.2f} A.")
    result["supply"] = supply["name"]
    return result


def plan_electronics(ctx: Ctx) -> dict | None:
    """The plan for the current parts, or None when nothing electrical is chosen."""

    rows = _parts(ctx)
    plan = _Plan()
    drone = "flight_controller" in ctx.state.selected and not ctx.state.spec
    supply = _drone(ctx, rows, plan) if drone else _product(rows, plan)
    if supply is None:
        return None
    if not drone:
        _apply_duties(ctx, plan)
    budget = _budget(supply, plan)
    # The inline wires on the supply side carry everything the build draws.
    for wire in plan.wires:
        if wire["kind"] == "power" and wire["current_a"] is None:
            wire["current_a"] = budget["peak_a"]
            wire["label"] = f"{wire['voltage_v']:g} V {budget['peak_a']:.2f} A"
    fails = [w for w in plan.warnings if w["severity"] == "fail"]
    runtime = budget.get("runtime_h")
    runtime_text = "" if runtime is None else (f", runs {runtime * 60:.1f} min" if runtime < 1 else f", runs {runtime:.0f} h" if runtime < 48 else f", runs {runtime / 24:.0f} days")
    summary = (
        f"{len(plan.blocks)} parts, {len(plan.wires)} wires. Peak {budget['peak_a']:.2f} A of {budget['supply_limit_a']:.2f} A from {supply['name']}"
        + f" (headroom {budget['headroom']:.1f}x), average {budget['average_w']:.2f} W{runtime_text}."
        + (f" {len(fails)} part{'s' if len(fails) != 1 else ''} over {'their' if len(fails) != 1 else 'its'} rating." if fails else " Every part within its rating.")
    )
    return {
        "type": "electronics",
        "product": str(ctx.state.product or "drone"),
        "ok": not fails,
        "summary": summary,
        "blocks": plan.blocks,
        "wires": plan.wires,
        "budget": budget,
        "warnings": plan.warnings,
        "gaps": plan.gaps,
        "wiring": drone_wiring(ctx) if drone else [],
    }


async def electronics_plan(ctx: Ctx, args: dict) -> dict:
    event = plan_electronics(ctx)
    if event is None:
        message = "No electrical parts chosen yet: pick a battery or power supply and the parts it feeds."
        return {"ok": False, "error": message, "detail": message}
    note = str(args.get("explanation") or "").strip()
    if note:
        event["explanation"] = note
    await ctx.emit(event)
    return {
        "ok": True,
        "detail": ("pass: " if event["ok"] else "fail: ") + event["summary"],
        "result": "pass" if event["ok"] else "fail",
        "summary": event["summary"],
        "warnings": [w["text"] for w in event["warnings"]],
        "gaps": event["gaps"],
        "budget": {k: event["budget"].get(k) for k in ("supply", "supply_voltage_v", "supply_limit_a", "average_w", "peak_w", "peak_a", "headroom", "runtime_h")},
    }
