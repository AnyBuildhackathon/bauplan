"""circuit_design: SparkBench wires the chosen parts, checks them and runs the firmware in its simulator.

Run with: cd agent && uv run --with pytest pytest tests/test_circuit.py
The tests that run SparkBench need its checkout (bash agent/scripts/setup_sparkbench.sh, once, with the network)
and are skipped without it. No test needs the network or a key.
"""

from __future__ import annotations

import asyncio
import json
import resource
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from pai_agent import cache, sparkbench
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools import circuit, registry

DATA = Path(__file__).resolve().parents[1] / "data"
GRIPPER = {part["id"]: part for part in json.loads((DATA / "catalogs" / "gripper.json").read_text())["parts"]}
GENERIC = {part["id"]: part for part in json.loads((DATA / "catalogs" / "generic.json").read_text())["parts"]}
DRONE = {part["id"]: part for part in json.loads((DATA / "parts.json").read_text())["parts"]}
BUTTON = {"name": "12 mm push button", "mass_g": 1.0, "unit_price_eur": 0.3}
installed = pytest.mark.skipif(sparkbench.missing() is not None, reason=f"SparkBench is not installed: {sparkbench.missing()}")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Every test has its own result cache, and the files carry a fixed date."""

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(circuit, "_today", lambda: "2026-10-26")


def _gripper(directory: Path, controller: str | None = "esp32-devkit", driver: bool = True) -> Ctx:
    state = BuildState("test", directory)
    state.product = "gripper"
    for part_id in ["towerpro-mg996r", "pads-tpu-printed", "m3-hardware-set"] + (["pca9685-driver"] if driver else []):
        state.selected[GRIPPER[part_id]["category"]] = GRIPPER[part_id]
    if controller:
        state.selected["controller"] = GENERIC[controller]
    return Ctx(EventBus(), state, auto_steps=True)


def _product(directory: Path, name: str, parts: list[tuple]) -> Ctx:
    """parts: (spec part id, its name, category, catalog id or a part of our own, qty); None is not picked yet."""

    state = BuildState("test", directory)
    state.product = "generic"
    state.spec = {"name": name, "parts": [{"id": pid, "name": label, "kind": "bought", "category": cat, "qty": qty} for pid, label, cat, _, qty in parts]}
    for pid, _label, cat, source, _qty in parts:
        if source is not None:
            state.picked[pid] = dict(GENERIC[source]) if isinstance(source, str) else {"category": cat, **source}
    return Ctx(EventBus(), state, auto_steps=True)


def _lamp(directory: Path, *extra: tuple) -> Ctx:
    """A desk lamp with an ESP32: a WS2812 ring, a push button and USB-C power."""

    return _product(
        directory,
        "Desk lamp",
        [
            ("controller", "Controller", "controller", "esp32-devkit", 1),
            ("ring", "Lamp ring", "light", "led-ws2812-ring-12", 1),
            ("button", "Lamp button", "switch", BUTTON, 1),
            ("power", "USB-C power", "power", "usb-c-cable", 1),
            *extra,
        ],
    )


def _run(ctx: Ctx, **args) -> tuple[dict, dict | None]:
    """The tool through the registry, as Claude calls it; the result and the circuit event, if any."""

    result = asyncio.run(registry.call_tool(ctx, "circuit_design", args))
    events = [event for event in ctx.bus.events if event["type"] == "circuit"]
    return result, events[-1] if events else None


def _errors(event: dict) -> list[str]:
    return [check["title"] for check in event["checks"] if check["severity"] == "error"]


def _files(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("TowerPro SG90 micro servo", "servo"),
        ("SG90 360 continuous rotation servo", None),
        ("TowerPro MG996R servo", None),
        ("WS2812B LED ring, 12 LEDs", "neopixel"),
        ("5 mm red LED", "led"),
        ("1 W white LED on 20 mm star", None),
        ("KY-016 RGB LED module", None),
        ("HC-SR04 ultrasonic distance sensor", "hcsr04"),
        ("HC-SR505 Mini PIR motion sensor", "pir"),
        ("Capacitive soil moisture sensor v1.2", "soil"),
        ("GY-521 MPU-6050 accelerometer and gyroscope", "mpu6050"),
        ("0.96 inch OLED display I2C", "oled"),
        ("1.3 inch SH1106 OLED display", None),
        ("12 mm push button", "button"),
        ("CR2032 button cell", None),
        ("1-channel 5 V relay module", "relay"),
        ("4 channel relay module", None),
        ("Passive piezo buzzer", "buzzer"),
        ("PCA9685 16-channel servo driver", None),
    ],
)
def test_built_in_parts_become_sparkbench_features(name, kind):
    assert (circuit._feature(circuit._words(name)) or {}).get("kind") == kind


def test_feature_details_come_from_the_name():
    assert circuit._feature(circuit._words("5 mm green LED")) == {"kind": "led", "props": {"color": "green"}}
    assert circuit._feature(circuit._words("WS2812B LED strip, 30 LEDs")) == {"kind": "neopixel", "props": {"pixels": 30}}


def test_plan_sorts_the_parts_into_board_features_library_and_gaps(tmp_path):
    ctx = _lamp(
        tmp_path,
        ("light", "Reading light", "light", "led-1w-white", 1),
        ("resistor", "LED resistor", "resistor", {"name": "LED series resistor 5.6 ohm 2 W"}, 1),
        ("rocker", "Rocker switch", "switch", "switch-rocker", 1),
        ("cells", "Battery", "battery", "battery-18650", 1),
        ("feet", "Rubber feet", "hardware", None, 4),
        ("sensor", "Light sensor", "sensor", None, 1),
    )
    plan = circuit._plan(ctx, "")
    assert (plan["board"], plan["proposed"], plan["controller"]) == ("esp32", False, "controller")
    kinds = {part["key"]: (part.get("feature") or {}).get("kind") for part in plan["parts"]}
    # The 1 W LED has no feature: the bridge looks it up in SparkBench's library.
    assert kinds == {"ring": "neopixel", "button": "button", "light": None}
    assert plan["notes"] == ["USB-C power powers the board over USB."]
    gaps = "\n".join(plan["gaps"])
    for label in ("LED resistor:", "Rocker switch:", "Battery:", "Light sensor: not picked yet"):
        assert label in gaps
    assert "Rubber feet" not in gaps


@pytest.mark.parametrize(("controller", "board"), [("esp32-devkit", "esp32"), ("esp32-nodemcu-bb", "esp32"), ("pico-w", "pico")])
def test_the_controller_sets_the_board(tmp_path, controller, board):
    plan = circuit._plan(_gripper(tmp_path, controller), "")
    assert plan["board"] == board and not plan["proposed"]


@pytest.mark.parametrize(
    ("controller", "why"),
    [
        ("esp32-s3-devkit", "newer ESP32 with other pins"),
        ("m5stack-timer-camera-u082x", "camera board"),
        ("arduino-nano", "is neither"),
        ("rpi4b-1gb-bb", "is neither"),
    ],
)
def test_a_controller_sparkbench_cannot_simulate_stops_the_tool(tmp_path, controller, why):
    result, event = _run(_gripper(tmp_path, controller), board="esp32")
    assert result["ok"] is False and why in result["error"] and event is None


def test_the_drone_keeps_its_betaflight_firmware(tmp_path):
    state = BuildState("test", tmp_path)
    for part_id in ("generic-1103-15000kv", "gemfan-2020-4", "tattu-rline-1s-550", "betafpv-matrix-1s-5in1-v2", "twiglet-2in-carbon", "caddx-ant"):
        state.selected[DRONE[part_id]["category"]] = DRONE[part_id]
    result, _ = _run(Ctx(EventBus(), state, auto_steps=False))
    assert result["ok"] is False and "Betaflight" in result["error"]


def test_without_a_controller_the_board_must_be_proposed(tmp_path):
    ctx = _gripper(tmp_path, controller=None)
    result, _ = _run(ctx)
    assert result["ok"] is False and "pass board" in result["error"]
    plan = circuit._plan(ctx, "pico")
    assert plan["board"] == "pico" and plan["proposed"] and "proposed by Mechanic" in plan["notes"][0]


def test_a_board_that_contradicts_the_parts_is_refused(tmp_path):
    result, _ = _run(_gripper(tmp_path), board="pico")
    assert result["ok"] is False and "already have the ESP32 DevKit C board" in result["error"]
    result, _ = _run(_gripper(tmp_path), board="arduino")
    assert result["ok"] is False and result["error"] == "board is esp32 or pico."


def test_without_sparkbench_the_tool_says_how_to_install_it_and_the_run_goes_on(tmp_path, monkeypatch):
    monkeypatch.setenv("SPARKBENCH_DIR", str(tmp_path / "nowhere"))
    ctx = _gripper(tmp_path / "session")
    result, event = _run(ctx)
    assert result["ok"] is False and "agent/scripts/setup_sparkbench.sh" in result["error"] and "nowhere" in result["error"]
    assert "Go on without the circuit" in result["next"] and event is None
    final = [e for e in ctx.bus.events if e["type"] == "tool"][-1]
    assert (final["name"], final["status"]) == ("circuit_design", "error")
    monkeypatch.setattr(sparkbench, "node", lambda: None)
    assert sparkbench.missing() == "Node.js is not installed"


def test_registered_with_its_schema_and_step():
    assert registry.TOOLS["circuit_design"] is circuit.circuit_design
    assert circuit.SCHEMA in registry.SCHEMAS
    assert registry._STEP["circuit_design"] == "simulation"


@installed
def test_gripper_circuit(tmp_path):
    session = tmp_path / "session"
    ctx = _gripper(session)
    result, event = _run(ctx)
    assert result["ok"] and result["result"] == "pass", result
    assert (event["board"], event["board_name"], event["board_proposed"], event["ok"]) == ("esp32", "ESP32 DevKit V1", False, True)
    assert _errors(event) == []
    assert (event["sim"]["status"], event["sim"]["error"], event["sim"]["simulated_s"]) == ("stopped", None, 5)
    assert event["tests"] and all(test["pass"] for test in event["tests"])
    board = next(part for part in event["parts"] if part["ref"] == "U1")
    assert (board["type"], board["anybuild"]) == ("esp32-devkit", "controller")
    driver = next(part for part in event["parts"] if part["mpn"] == "PCA9685")
    assert driver["anybuild"] == "driver"
    assert (driver["pins"]["SDA"], driver["pins"]["SCL"], driver["pins"]["VCC"], driver["pins"]["OE"]) == ("GPIO21_SDA", "GPIO22_SCL", "+3V3", None)
    assert {"name": "GPIO21_SDA", "pins": ["U1.D21", driver["ref"] + ".SDA"]} in event["nets"]
    assert {"from": driver["ref"] + ".SDA", "to": "U1.D21", "color": "#1e88e5"} in event["wires"]
    # SparkBench's PCA9685 has no channel pins: the servo is a gap with its channel, not a wire to a board pin.
    assert not any(part["mpn"] == "MG996R" for part in event["parts"])
    assert any(gap.startswith("TowerPro MG996R servo: plugs into PCA9685 channel 0") for gap in event["gaps"])
    assert event["files"]["kicad_sch"] == "/files/test/circuit-v1.kicad_sch"
    for kind, url in event["files"].items():
        assert (session / url.rsplit("/", 1)[1]).is_file(), kind
    assert (session / "circuit-v1.kicad_sch").read_text().startswith("(kicad_sch")
    with zipfile.ZipFile(session / "circuit-v1-firmware.zip") as archive:
        assert {"main.py", "pca9685.py"} <= set(archive.namelist())
    with zipfile.ZipFile(session / "circuit-v1-kicad.zip") as archive:
        assert {"robot-gripper/robot-gripper.kicad_pro", "robot-gripper/robot-gripper.kicad_sch", "robot-gripper/fp-lib-table"} <= set(archive.namelist())
    assert event["source"] == "sparkbench@6dd9237"
    # The event goes out over SSE as JSON.
    assert json.loads(json.dumps(event)) == event
    steps = [(e["id"], e["status"]) for e in ctx.bus.events if e["type"] == "step"]
    assert steps == [("simulation", "running"), ("simulation", "done")]


@installed
def test_a_servo_without_a_driver_gets_a_board_pin_and_its_own_supply(tmp_path):
    result, event = _run(_gripper(tmp_path, driver=False))
    assert result["ok"] and _errors(event) == []
    servo = next(part for part in event["parts"] if part["mpn"] == "MG996R")
    assert servo["anybuild"] == "servo" and servo["pins"]["SIG"].startswith("GPIO") and servo["pins"]["V+"] == "VEXT"
    supply = next(part for part in event["parts"] if part["type"] == "dc-supply")
    assert supply["pins"] == {"+": "VEXT", "-": "GND"} and supply["anybuild"] is None


@installed
def test_a_gripper_without_controller_builds_on_the_proposed_board(tmp_path):
    result, event = _run(_gripper(tmp_path, controller=None), board="esp32")
    assert result["ok"] and result["board"] == "ESP32 DevKit V1 (proposed by Mechanic)"
    assert event["board_proposed"] and "No controller among the parts: the ESP32 DevKit V1 is proposed by Mechanic." in event["notes"]
    assert next(part for part in event["parts"] if part["ref"] == "U1")["anybuild"] is None


@installed
def test_lamp_circuit(tmp_path):
    session = tmp_path / "session"
    result, event = _run(_lamp(session))
    assert result["ok"] and result["result"] == "pass", result
    assert _errors(event) == [] and event["gaps"] == []
    assert (event["sim"]["status"], event["sim"]["error"]) == ("stopped", None)
    assert "button pressed" in event["sim"]["serial_tail"]
    assert all(test["pass"] for test in event["tests"])
    ring = next(part for part in event["parts"] if part["type"] == "neopixel-ring")
    button = next(part for part in event["parts"] if part["type"] == "pushbutton")
    assert (ring["anybuild"], ring["label"], ring["pins"]["VCC"]) == ("ring", "Lamp ring", "+5V")
    assert (button["anybuild"], button["label"]) == ("button", "Lamp button") and button["pins"]["1"].startswith("GPIO")
    assert "USB-C power powers the board over USB." in event["notes"]
    assert (session / "circuit-v1.kicad_sch").is_file() and (session / "circuit-v1-main.py").read_text().startswith("# Desk lamp")


@installed
def test_a_part_sparkbench_cannot_model_is_listed_in_gaps(tmp_path):
    ctx = _lamp(tmp_path, ("light", "Reading light", "light", "led-1w-white", 1), ("lidar", "Lidar", "sensor", "rplidar-c1-mybotshop", 1))
    result, event = _run(ctx)
    assert result["ok"]
    for label in ("Reading light", "Lidar"):
        assert f"{label}: SparkBench has no model for it, so it is not in the circuit." in event["gaps"]
    assert {part["anybuild"] for part in event["parts"]} == {"controller", "ring", "button"}
    assert result["gaps"] == event["gaps"]


@installed
def test_a_pico_build(tmp_path):
    ctx = _product(
        tmp_path,
        "Pan head",
        [("mcu", "Controller", "controller", "pico-w", 1), ("servo", "Pan servo", "servo", "servo-sg90", 1), ("led", "Status LED", "light", {"name": "5 mm green LED"}, 1)],
    )
    result, event = _run(ctx)
    assert result["ok"] and event["board"] == "pico" and _errors(event) == []
    servo = next(part for part in event["parts"] if part["type"] == "servo")
    led = next(part for part in event["parts"] if part["type"] == "led")
    assert servo["pins"]["PWM"].startswith("GP") and led["label"] == "Status LED"


@installed
def test_sparkbench_rejecting_the_parts_answers_in_its_words(tmp_path):
    ctx = _product(
        tmp_path,
        "Sensor wall",
        [
            ("mcu", "Controller", "controller", "pico-w", 1),
            ("sonars", "Sonars", "sensor", "sensor-hcsr04", 8),
            ("buttons", "Buttons", "switch", BUTTON, 8),
            ("leds", "LEDs", "light", {"name": "5 mm red LED"}, 8),
        ],
    )
    result, event = _run(ctx)
    assert result["ok"] is False and "has run out of free GPIO pins" in result["error"] and event is None


@installed
def test_the_same_parts_give_the_same_circuit_and_files(tmp_path, monkeypatch):
    monkeypatch.setenv("PAI_CACHE", "0")
    for build in (_gripper, _lamp):
        first, second = build(tmp_path / build.__name__ / "a"), build(tmp_path / build.__name__ / "b")
        (one_result, one), (two_result, two) = _run(first), _run(second)
        assert not one_result["cached"] and not two_result["cached"]
        assert one == two
        assert _files(tmp_path / build.__name__ / "a") == _files(tmp_path / build.__name__ / "b")


@installed
def test_an_identical_request_comes_from_the_cache(tmp_path):
    again = _lamp(tmp_path / "b")
    (first, one), (second, two) = _run(_lamp(tmp_path / "a")), _run(again)
    assert (first["cached"], second["cached"]) == (False, True)
    assert one == two and _files(tmp_path / "a") == _files(tmp_path / "b")
    assert [e for e in again.bus.events if e["type"] == "tool"][-1]["cached"] is True


@installed
def test_one_call_takes_under_5_s(tmp_path, monkeypatch):
    monkeypatch.setenv("PAI_CACHE", "0")
    ctx = _gripper(tmp_path)
    before, started = resource.getrusage(resource.RUSAGE_CHILDREN), time.perf_counter()
    result, _ = _run(ctx)
    after, wall = resource.getrusage(resource.RUSAGE_CHILDREN), time.perf_counter() - started
    cpu = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
    assert result["ok"]
    # CPU time of the SparkBench process: on a machine busy with other test runs the wall clock measures them too.
    assert 0 < cpu < 5, f"{cpu:.2f} s CPU, {wall:.2f} s wall"


@installed
def test_a_stuck_bridge_is_stopped_with_its_child_process(tmp_path, monkeypatch):
    stuck = tmp_path / "stuck.mts"
    stuck.write_text("await new Promise((done) => setTimeout(done, 60_000));\n")
    monkeypatch.setattr(sparkbench, "BRIDGE", stuck)
    monkeypatch.setattr(sparkbench, "TIMEOUT_S", 1.0)
    started = time.perf_counter()
    with pytest.raises(sparkbench.SparkBenchFailed, match="ran longer than 1 s"):
        asyncio.run(sparkbench._run(tmp_path, tmp_path / "request.json"))
    assert time.perf_counter() - started < 30
    # tsx runs the script in a child process; it goes too.
    assert subprocess.run(["pgrep", "-f", str(stuck)], capture_output=True, text=True).stdout == ""


@installed
def test_a_crashing_bridge_fails_the_tool_and_the_run_goes_on(tmp_path, monkeypatch):
    broken = tmp_path / "broken.mts"
    broken.write_text("throw new Error('the bridge broke');\n")
    monkeypatch.setattr(sparkbench, "BRIDGE", broken)
    result, event = _run(_lamp(tmp_path / "session"))
    assert result["ok"] is False and "exit code 1" in result["error"] and "the bridge broke" in result["error"]
    assert "Go on without the circuit" in result["next"] and event is None
