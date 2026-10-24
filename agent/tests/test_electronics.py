"""Electronics plan: wiring diagram and power budget for the drone, the plant waterer and a USB-C desk lamp.

Run with: cd agent && uv run --with pytest pytest tests/test_electronics.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools.electronics import electronics_plan

DATA = Path(__file__).resolve().parents[1] / "data"
DRONE = {part["id"]: part for part in json.loads((DATA / "parts.json").read_text())["parts"]}
GENERIC = {part["id"]: part for part in json.loads((DATA / "catalogs" / "generic.json").read_text())["parts"]}
V1 = ("generic-1103-15000kv", "gemfan-2020-4", "tattu-rline-1s-550", "betafpv-matrix-1s-5in1-v2", "twiglet-2in-carbon", "caddx-ant")


def _drone(tmp_path: Path, ids=V1) -> Ctx:
    state = BuildState("test", tmp_path)
    for part_id in ids:
        state.selected[DRONE[part_id]["category"]] = DRONE[part_id]
    return Ctx(EventBus(), state, auto_steps=False)


def _product(tmp_path: Path, name: str, parts: list[tuple[str, str, str | dict, int]], runtime: dict | None = None) -> Ctx:
    """parts: (spec part id, category, catalog id or estimate dict, qty)."""

    state = BuildState("test", tmp_path)
    state.product = "product"
    state.spec = {"name": name, "parts": [{"id": pid, "name": pid, "kind": "bought", "category": cat, "qty": qty} for pid, cat, _, qty in parts]}
    for pid, cat, source, _qty in parts:
        state.picked[pid] = dict(GENERIC[source]) if isinstance(source, str) else {"category": cat, **source}
    if runtime:
        state.checks["runtime"] = {"args": runtime}
    return Ctx(EventBus(), state, auto_steps=False)


def _run(ctx: Ctx) -> tuple[dict, dict]:
    result = asyncio.run(electronics_plan(ctx, {}))
    return result, ctx.bus.events[-1]


def _ids(event: dict) -> set[str]:
    return {block["id"] for block in event["blocks"]}


def _wired(event: dict) -> None:
    ids = _ids(event)
    for wire in event["wires"]:
        assert wire["from"] in ids and wire["to"] in ids, wire


def test_drone_diagram_budget_and_runtime(tmp_path):
    result, event = _run(_drone(tmp_path))
    assert result["ok"] and event["type"] == "electronics" and event["ok"], event["warnings"]
    assert {"battery", "fc", "motor_m1", "motor_m2", "motor_m3", "motor_m4", "camera"} <= _ids(event)
    _wired(event)
    phases = [w for w in event["wires"] if w["kind"] == "phase"]
    assert len(phases) == 4 and all(w["voltage_v"] == 3.7 for w in phases)
    budget = event["budget"]
    # 75C x 550 mAh is the pack's limit; a whoop hovers for a few minutes on it.
    assert budget["supply_limit_a"] == 41.25
    assert 0 < budget["average_w"] < budget["peak_w"] and budget["headroom"] >= 1
    assert 0.03 < budget["runtime_h"] < 0.2
    # The pins are the firmware tool's wiring table.
    assert any(row["pin"] == "M1" for row in event["wiring"])


def test_drone_4s_battery_on_1s_controller_warns(tmp_path):
    ids = tuple("tattu-funfly-4s-1300" if i == "tattu-rline-1s-550" else i for i in V1)
    result, event = _run(_drone(tmp_path, ids))
    assert result["result"] == "fail" and not event["ok"]
    texts = " ".join(w["text"] for w in event["warnings"] if w["severity"] == "fail")
    assert "14.8 V" in texts and "Matrix" in texts and "1S" in texts
    assert "rated for 1S" in texts
    assert any(w["color"] == "high" for w in event["wires"])


PLANT = [
    ("pump", "pump", "pump-5v-mini", 1),
    ("sensor", "sensor", "sensor-soil-capacitive", 1),
    ("mcu", "controller", "esp32-devkit", 1),
    ("battery", "battery", "battery-18650", 1),
    ("holder", "battery", "battery-holder-18650", 1),
    ("tubing", "tubing", "tube-silicone-8mm", 1),
    ("driver", "driver", "mosfet-module", 1),
]
PLANT_RUNTIME = json.loads((DATA / "references" / "plant-waterer" / "reference.json").read_text())["checks"][3]["args"]


def test_plant_waterer_runs_a_month_through_the_boost(tmp_path):
    result, event = _run(_product(tmp_path, "Plant waterer", PLANT, PLANT_RUNTIME))
    assert result["ok"] and event["ok"], event["warnings"]
    assert {"battery", "holder", "mcu", "driver", "pump", "sensor"} == _ids(event)
    _wired(event)
    roles = {b["id"]: b["role"] for b in event["blocks"]}
    assert roles["holder"] == "regulator" and roles["mcu"] == "controller" and roles["driver"] == "driver"
    # The soil sensor runs from the ESP32's 3.3 V pin and reads on an ADC pin.
    assert any(w["from"] == "mcu" and w["to"] == "sensor" and w["voltage_v"] == 3.3 for w in event["wires"])
    assert any(w["from"] == "sensor" and w["to"] == "mcu" and w["kind"] == "signal" and w["to_pin"] == "GPIO34" for w in event["wires"])
    assert any(w["from"] == "driver" and w["to"] == "pump" and w["voltage_v"] == 5.0 for w in event["wires"])
    # The duty cycles from the stored runtime check: a month and more on one 18650.
    assert event["budget"]["runtime_h"] > 30 * 24
    assert any("asleep" in row["name"] for row in event["budget"]["loads"])
    assert event["gaps"]


def test_plant_waterer_pump_on_a_bare_pin_warns(tmp_path):
    parts = [p for p in PLANT if p[0] != "driver"]
    _result, event = _run(_product(tmp_path, "Plant waterer", parts, PLANT_RUNTIME))
    assert not event["ok"]
    assert any("controller pin" in w["text"] and w["part"] == GENERIC["pump-5v-mini"]["name"] for w in event["warnings"])


RESISTOR = {"name": "Resistor 5.6 ohm 2 W", "mass_g": 1.0, "unit_price_eur": 0.3}
LAMP = [
    ("led", "light", "led-1w-white", 1),
    ("resistor", "resistor", RESISTOR, 1),
    ("switch", "switch", "switch-rocker", 1),
    ("power", "power", "usb-c-cable", 1),
    ("feet", "hardware", "rubber-feet-10mm", 4),
]


def test_desk_lamp_led_through_its_resistor(tmp_path):
    result, event = _run(_product(tmp_path, "USB-C desk lamp", LAMP))
    assert result["ok"] and event["ok"], event["warnings"]
    assert ["power", "switch", "resistor", "led"] == [b["id"] for b in sorted(event["blocks"], key=lambda b: b["col"])]
    _wired(event)
    led_wire = next(w for w in event["wires"] if w["to"] == "led")
    assert led_wire["voltage_v"] == 3.2 and abs(led_wire["current_a"] - 0.312) < 0.01
    assert "runtime_h" not in event["budget"] and event["budget"]["headroom"] > 1


def test_desk_lamp_without_resistor_or_with_a_small_one_warns(tmp_path):
    _result, event = _run(_product(tmp_path, "USB-C desk lamp", [p for p in LAMP if p[0] != "resistor"]))
    assert not event["ok"] and any("series resistor" in w["text"] for w in event["warnings"])
    small = [("resistor", "resistor", {**RESISTOR, "name": "Resistor 5.6 ohm 0.25 W"}, 1) if p[0] == "resistor" else p for p in LAMP]
    _result, event = _run(_product(tmp_path, "USB-C desk lamp", small))
    assert not event["ok"] and any("rated for 0.25 W" in w["text"] for w in event["warnings"])


def test_no_electronics_is_a_clear_failure(tmp_path):
    result = asyncio.run(electronics_plan(_product(tmp_path, "Phone stand", [("feet", "hardware", "rubber-feet-10mm", 4)]), {}))
    assert result["ok"] is False and "power supply" in result["error"]
