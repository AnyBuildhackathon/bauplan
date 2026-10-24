"""Firmware and wiring for the built product.

Deterministic templates filled from the chosen parts: a Betaflight CLI script for the
drone, an Arduino sketch for a servo product. Claude only writes the explanation.
"""

from __future__ import annotations

from pai_agent.context import Ctx

# Betaflight targets for the flight controllers in the catalog. An unknown board gets no
# board_name line and a serial receiver, so the config stays generic.
_BOARDS = {
    "betafpv-f4-1s-12a-aio-v3": {
        "board_name": "BETAFPVF411",
        "manufacturer_id": "BEFH",
        "receiver": "ExpressLRS 2.4 GHz on board (SPI)",
        "battery_plug": "BT2.0",
    },
}

# Quad X, props in: Betaflight numbers the motors from rear right, counter-clockwise seen from below.
_MOTORS = (
    ("M1", "motor_rear_right", "rear right", "CW"),
    ("M2", "motor_front_right", "front right", "CCW"),
    ("M3", "motor_rear_left", "rear left", "CCW"),
    ("M4", "motor_front_left", "front left", "CW"),
)

# Starting gains for a 1S whoop on Betaflight 4.4 (Betaflight units). Training replaces them.
DEFAULT_GAINS = {
    "roll": {"p": 45, "i": 80, "d": 40, "f": 120},
    "pitch": {"p": 47, "i": 84, "d": 46, "f": 125},
    "yaw": {"p": 45, "i": 80, "d": 0, "f": 120},
}
_GAIN_LIMITS = {"p": 250, "i": 250, "d": 250, "f": 1000}

# Actual rates: center sensitivity 70 deg/s, max 670 deg/s, no expo.
_RATES = {"rc_rate": 7, "srate": 67, "expo": 0}

_SERVO_PINS = (9, 10, 11, 6, 5, 3)


def _gains_from(source) -> dict | None:
    """Reads {roll: {p, i, d, f}, pitch: ..., yaw: ...} in Betaflight units, or flat p_roll keys."""

    if not isinstance(source, dict):
        return None
    found: dict[str, dict] = {}
    for axis in DEFAULT_GAINS:
        terms = source.get(axis)
        for term in _GAIN_LIMITS:
            value = terms.get(term) if isinstance(terms, dict) else source.get(term + "_" + axis)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                found.setdefault(axis, {})[term] = value
    return found or None


def trained_gains(ctx: Ctx, args: dict) -> tuple[dict, str]:
    """Gains and where they came from: the tool call, the session, the last training event, or defaults."""

    candidates = [
        ("tool call", args.get("gains")),
        ("training", getattr(ctx.state, "controller_gains", None)),
    ]
    for event in reversed(ctx.bus.events):
        if event.get("type") == "training" and event.get("gains"):
            candidates.append(("training", event["gains"]))
            break
    for source, raw in candidates:
        found = _gains_from(raw)
        if found:
            merged = {}
            for axis, defaults in DEFAULT_GAINS.items():
                merged[axis] = {}
                for term, default in defaults.items():
                    value = found.get(axis, {}).get(term, default)
                    merged[axis][term] = int(round(min(max(float(value), 0.0), _GAIN_LIMITS[term])))
            return merged, source
    return {axis: dict(terms) for axis, terms in DEFAULT_GAINS.items()}, "defaults"


def _part(ctx: Ctx, category: str) -> dict | None:
    return ctx.state.selected.get(category)


def _version_label(ctx: Ctx) -> str:
    return "v" + str(len(ctx.state.versions) + 1)


def _drone_warnings(fc: dict | None, motor: dict | None, battery: dict | None) -> list[str]:
    warnings = []
    cells = int((battery or {}).get("cells") or 0)
    if fc and cells and fc.get("cells_max") and cells > int(fc["cells_max"]):
        warnings.append(
            f"{battery['name']} is {cells}S, the {fc['name']} takes at most {fc['cells_max']}S."
        )
    if motor and cells and motor.get("cells_max") and cells > int(motor["cells_max"]):
        warnings.append(
            f"{battery['name']} is {cells}S, the {motor['name']} is rated for {motor['cells_max']}S."
        )
    return warnings


def drone_wiring(ctx: Ctx) -> list[dict]:
    fc = _part(ctx, "flight_controller")
    motor = _part(ctx, "motor")
    battery = _part(ctx, "battery")
    board = _BOARDS.get((fc or {}).get("id", ""), {})
    fc_name = fc["name"] if fc else "Flight controller"
    rows = []
    if motor:
        for pad, _target, position, spin in _MOTORS:
            rows.append(
                {
                    "component": f"{motor['name']} ({position})",
                    "connects_to": f"{fc_name} motor plug {pad}",
                    "pin": pad,
                    "wire": "3 phase wires, black",
                    "note": f"Spins {spin}, props in.",
                }
            )
    if battery:
        cells = int(battery.get("cells") or 1)
        plug = board.get("battery_plug", "battery lead") if cells == 1 else "XT30" if cells == 2 else "XT60"
        rows.append(
            {
                "component": battery["name"],
                "connects_to": f"{fc_name} {plug}",
                "pin": "VBAT+",
                "wire": "red",
                "note": f"{cells}S, {battery.get('voltage_v', '')} V",
            }
        )
        rows.append(
            {
                "component": battery["name"],
                "connects_to": f"{fc_name} {plug}",
                "pin": "GND",
                "wire": "black",
                "note": "",
            }
        )
    if fc:
        rows.append(
            {
                "component": "Receiver",
                "connects_to": fc_name,
                "pin": "SPI RX",
                "wire": "on board",
                "note": board.get("receiver", "Wire a serial receiver to UART1."),
            }
        )
        rows.append(
            {
                "component": "Computer",
                "connects_to": fc_name,
                "pin": "USB",
                "wire": "USB cable",
                "note": "Paste the firmware file into the Betaflight CLI.",
            }
        )
    for warning in _drone_warnings(fc, motor, battery):
        rows.append({"component": "Check", "connects_to": "", "pin": "", "wire": "", "note": warning})
    return rows


def betaflight_cli(ctx: Ctx, gains: dict, gains_source: str) -> str:
    fc = _part(ctx, "flight_controller")
    motor = _part(ctx, "motor")
    battery = _part(ctx, "battery")
    propeller = _part(ctx, "propeller")
    board = _BOARDS.get((fc or {}).get("id", ""), {})
    cells = int((battery or {}).get("cells") or 1)
    lihv = float((battery or {}).get("voltage_v") or 3.7) / max(cells, 1) >= 3.8
    lines = [
        "# AnyBuild firmware: Betaflight CLI configuration",
        "# Product: drone " + _version_label(ctx),
        "# Flight controller: " + (fc["name"] if fc else "unknown"),
        "# Motors: " + (motor["name"] if motor else "unknown"),
        "# Propellers: " + (propeller["name"] if propeller else "unknown"),
        "# Battery: " + (battery["name"] if battery else "unknown"),
        "# PID gains: " + ("trained controller" if gains_source == "training" else gains_source),
        "# Paste into the Betaflight Configurator CLI tab and press Enter. The board saves and reboots.",
        "# A motor that spins the wrong way: swap any two of its phase wires, or reverse it in the Motors tab.",
    ]
    for warning in _drone_warnings(fc, motor, battery):
        lines.append("# WARNING: " + warning)
    lines += ["", "batch start", ""]
    if board:
        lines += ["board_name " + board["board_name"], "manufacturer_id " + board["manufacturer_id"], ""]
    lines += ["# Motor order (Quad X, props in)"]
    for pad, _target, position, spin in _MOTORS:
        lines.append(f"#   {pad} {position} {spin}")
    lines += [
        "mixer QUADX",
        "set yaw_motors_reversed = OFF",
        "set motor_pwm_protocol = DSHOT300",
        "set dshot_bidir = ON",
        "set motor_poles = 12",
        "",
        "# Battery",
        f"set vbat_max_cell_voltage = {435 if lihv else 420}",
        "set vbat_warning_cell_voltage = 350",
        "set vbat_min_cell_voltage = 330",
        "",
        "# Receiver and arming switch on AUX1",
    ]
    if board.get("receiver", "").endswith("(SPI)"):
        lines += ["feature RX_SPI", "set rx_spi_protocol = EXPRESSLRS"]
    else:
        lines += ["feature RX_SERIAL", "serial 0 64 115200 57600 0 115200", "set serialrx_provider = CRSF"]
    lines += ["aux 0 0 0 1700 2100 0 0", "", "profile 0", ""]
    for axis, terms in gains.items():
        lines.append(f"set p_{axis} = {terms['p']}")
        lines.append(f"set i_{axis} = {terms['i']}")
        lines.append(f"set d_{axis} = {terms['d']}")
        lines.append(f"set f_{axis} = {terms['f']}")
    lines += ["", "rateprofile 0", "", "set rates_type = ACTUAL"]
    for axis in ("roll", "pitch", "yaw"):
        lines.append(f"set {axis}_rc_rate = {_RATES['rc_rate']}")
        lines.append(f"set {axis}_srate = {_RATES['srate']}")
        lines.append(f"set {axis}_expo = {_RATES['expo']}")
    lines += ["", "batch end", "", "save", ""]
    return "\n".join(lines)


def arduino_wiring(ctx: Ctx) -> list[dict]:
    servos = [part for part in ctx.state.selected.values() if part.get("category") == "servo"]
    driver = next((p for p in ctx.state.selected.values() if p.get("category") == "driver"), None)
    rows = []
    if driver:
        name = driver["name"]
        for pin, label, wire in (("A4", "SDA", "blue"), ("A5", "SCL", "yellow"), ("5V", "VCC", "red"), ("GND", "GND", "black")):
            rows.append({"component": name, "connects_to": "Arduino Uno " + pin, "pin": label, "wire": wire, "note": ""})
        rows.append(
            {
                "component": "5-6 V supply",
                "connects_to": name + " V+ terminal",
                "pin": "V+ / GND",
                "wire": "red / black",
                "note": "Servo power, not from the Arduino 5V pin.",
            }
        )
    for index, servo in enumerate(servos):
        target = f"{driver['name']} channel {index}" if driver else f"Arduino Uno D{_SERVO_PINS[index % len(_SERVO_PINS)]}"
        rows.append({"component": servo["name"], "connects_to": target, "pin": "signal", "wire": "orange", "note": ""})
        rows.append({"component": servo["name"], "connects_to": target, "pin": "V+", "wire": "red", "note": f"{servo.get('voltage_v', 5)} V"})
        rows.append({"component": servo["name"], "connects_to": target, "pin": "GND", "wire": "brown", "note": ""})
    return rows


def arduino_sketch(ctx: Ctx, product: str) -> str:
    servos = [part for part in ctx.state.selected.values() if part.get("category") == "servo"]
    driver = next((p for p in ctx.state.selected.values() if p.get("category") == "driver"), None)
    head = [
        "// AnyBuild firmware: Arduino sketch",
        f"// Product: {product} {_version_label(ctx)}",
    ]
    head += [f"// Servo {i}: {servo['name']}" for i, servo in enumerate(servos)]
    head.append("// Open and close the gripper over the serial monitor: send 'o' or 'c' at 115200 baud.")
    count = max(len(servos), 1)
    if driver:
        body = [
            "#include <Wire.h>",
            "#include <Adafruit_PWMServoDriver.h>",
            "",
            "Adafruit_PWMServoDriver driver = Adafruit_PWMServoDriver(0x40);",
            f"const int SERVO_COUNT = {count};",
            "const int PULSE_OPEN_US = 1000;",
            "const int PULSE_CLOSED_US = 2000;",
            "",
            "void writeAll(int pulseUs) {",
            "  for (int channel = 0; channel < SERVO_COUNT; channel++) {",
            "    driver.writeMicroseconds(channel, pulseUs);",
            "  }",
            "}",
            "",
            "void setup() {",
            "  Serial.begin(115200);",
            "  driver.begin();",
            "  driver.setOscillatorFrequency(27000000);",
            "  driver.setPWMFreq(50);",
            "  delay(10);",
            "  writeAll(PULSE_OPEN_US);",
            "}",
        ]
    else:
        pins = ", ".join(str(_SERVO_PINS[i % len(_SERVO_PINS)]) for i in range(count))
        body = [
            "#include <Servo.h>",
            "",
            f"const int SERVO_COUNT = {count};",
            f"const int SERVO_PINS[SERVO_COUNT] = {{{pins}}};",
            "const int PULSE_OPEN_US = 1000;",
            "const int PULSE_CLOSED_US = 2000;",
            "Servo servos[SERVO_COUNT];",
            "",
            "void writeAll(int pulseUs) {",
            "  for (int i = 0; i < SERVO_COUNT; i++) {",
            "    servos[i].writeMicroseconds(pulseUs);",
            "  }",
            "}",
            "",
            "void setup() {",
            "  Serial.begin(115200);",
            "  for (int i = 0; i < SERVO_COUNT; i++) {",
            "    servos[i].attach(SERVO_PINS[i]);",
            "  }",
            "  writeAll(PULSE_OPEN_US);",
            "}",
        ]
    loop = [
        "",
        "void loop() {",
        "  if (Serial.available() > 0) {",
        "    char command = Serial.read();",
        "    if (command == 'o') writeAll(PULSE_OPEN_US);",
        "    if (command == 'c') writeAll(PULSE_CLOSED_US);",
        "  }",
        "}",
        "",
    ]
    return "\n".join(head + [""] + body + loop)


def _default_explanation(kind: str, ctx: Ctx, gains_source: str, wiring: list[dict]) -> str:
    if kind == "betaflight":
        fc = _part(ctx, "flight_controller")
        source = "the trained controller" if gains_source == "training" else "Betaflight starting values for a 1S whoop"
        return (
            f"Betaflight CLI for the {fc['name'] if fc else 'flight controller'}: Quad X motor order, DShot300, "
            f"actual rates 70/670 deg/s, PID gains from {source}. "
            f"{len(wiring)} wiring rows come straight from the bill of materials."
        )
    return f"Arduino sketch that opens and closes the servos over serial. {len(wiring)} wiring rows from the parts."


async def firmware(ctx: Ctx, args: dict) -> dict:
    product = str(getattr(ctx.state, "product", "") or "drone")
    kind = str(args.get("kind") or "")
    if kind not in {"betaflight", "arduino"}:
        kind = "betaflight" if "flight_controller" in ctx.state.selected else "arduino"
    if not ctx.state.selected:
        message = "No parts chosen yet."
        return {"ok": False, "error": message, "detail": message}
    gains, gains_source = trained_gains(ctx, args)
    if kind == "betaflight":
        if "flight_controller" not in ctx.state.selected:
            message = "Betaflight needs a flight controller in the parts."
            return {"ok": False, "error": message, "detail": message}
        content = betaflight_cli(ctx, gains, gains_source)
        wiring = drone_wiring(ctx)
        filename = f"anybuild-{product}-{_version_label(ctx)}-betaflight.txt"
    else:
        content = arduino_sketch(ctx, product)
        wiring = arduino_wiring(ctx)
        filename = f"anybuild_{product}_{_version_label(ctx)}.ino".replace("-", "_")
        gains_source = "none"
    path = ctx.state.directory / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    explanation = str(args.get("explanation") or "").strip() or _default_explanation(kind, ctx, gains_source, wiring)
    event = {
        "type": "firmware",
        "kind": kind,
        "product": product,
        "filename": filename,
        "url": f"/files/{ctx.state.session_id}/{filename}",
        "content": content,
        "gains": gains if kind == "betaflight" else None,
        "gains_source": gains_source,
        "explanation": explanation,
        "wiring": wiring,
    }
    await ctx.emit(event)
    detail = filename + ", " + str(len(wiring)) + " wiring rows"
    return {
        "ok": True,
        "detail": detail,
        "kind": kind,
        "filename": filename,
        "gains_source": gains_source,
        "wiring": wiring,
    }
