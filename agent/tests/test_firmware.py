"""Firmware tool: the Betaflight file only uses known CLI commands and the wiring follows the parts.

Run with: cd agent && uv run --with pytest pytest tests/test_firmware.py
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools.firmware import DEFAULT_GAINS, firmware

CATALOG = {part["id"]: part for part in json.loads((Path(__file__).resolve().parents[1] / "data" / "parts.json").read_text())["parts"]}
V1 = ("generic-1103-15000kv", "gemfan-2020-4", "tattu-rline-1s-550", "betafpv-matrix-1s-5in1-v2", "twiglet-2in-carbon", "caddx-ant")

_SETTINGS = {
    "yaw_motors_reversed",
    "motor_pwm_protocol",
    "dshot_bidir",
    "motor_poles",
    "vbat_max_cell_voltage",
    "vbat_warning_cell_voltage",
    "vbat_min_cell_voltage",
    "rx_spi_protocol",
    "serialrx_provider",
    "rates_type",
} | {f"{term}_{axis}" for term in "pidf" for axis in ("roll", "pitch", "yaw")} | {
    f"{axis}_{key}" for axis in ("roll", "pitch", "yaw") for key in ("rc_rate", "srate", "expo")
}
_COMMANDS = (
    r"batch (start|end)",
    r"board_name \w+",
    r"manufacturer_id \w+",
    r"mixer QUADX",
    r"feature \w+",
    r"serial( \d+){6}",
    r"aux( \d+){7}",
    r"profile \d",
    r"rateprofile \d",
    r"save",
)


def _ctx(tmp_path: Path, ids=V1, product: str | None = None) -> Ctx:
    state = BuildState("test", tmp_path)
    for part_id in ids:
        part = part_id if isinstance(part_id, dict) else CATALOG[part_id]
        state.selected[part["category"]] = part
    if product:
        state.product = product
    return Ctx(EventBus(), state, auto_steps=False)


def _run(ctx: Ctx, args: dict | None = None) -> tuple[dict, dict]:
    result = asyncio.run(firmware(ctx, args or {}))
    return result, ctx.bus.events[-1]


def test_betaflight_file_uses_known_cli_lines(tmp_path):
    ctx = _ctx(tmp_path)
    result, event = _run(ctx)
    assert result["ok"] and event["type"] == "firmware" and event["kind"] == "betaflight"
    for line in event["content"].splitlines():
        if not line or line.startswith("#"):
            continue
        setting = re.fullmatch(r"set (\w+) = \S+", line)
        assert (setting and setting[1] in _SETTINGS) or any(re.fullmatch(c, line) for c in _COMMANDS), line
    assert event["content"].rstrip().endswith("save")
    assert "board_name" not in event["content"]
    assert "set serialrx_provider = CRSF" in event["content"]
    assert (tmp_path / event["filename"]).read_text() == event["content"]


def test_wiring_matches_the_parts(tmp_path):
    ctx = _ctx(tmp_path)
    _, event = _run(ctx)
    motors = [row for row in event["wiring"] if row["pin"] in {"M1", "M2", "M3", "M4"}]
    assert len(motors) == CATALOG["generic-1103-15000kv"]["bom_qty"]
    assert all(row["component"].startswith(CATALOG["generic-1103-15000kv"]["name"]) for row in motors)
    battery = [row for row in event["wiring"] if row["component"] == CATALOG["tattu-rline-1s-550"]["name"]]
    assert {row["pin"]: row["wire"] for row in battery} == {"VBAT+": "red", "GND": "black"}
    assert not [row for row in event["wiring"] if row["component"] == "Check"]
    camera = {row["pin"]: row["wire"] for row in event["wiring"] if row["component"] == CATALOG["caddx-ant"]["name"]}
    assert camera == {"CAM video": "yellow", "5V": "red", "GND": "black"}


def test_too_many_cells_is_flagged(tmp_path):
    ids = ("generic-1103-15000kv", "gemfan-2020-4", "tattu-funfly-4s-1300", "betafpv-matrix-1s-5in1-v2", "twiglet-2in-carbon")
    _, event = _run(_ctx(tmp_path, ids))
    assert "# WARNING:" in event["content"]
    assert any(row["component"] == "Check" for row in event["wiring"])


def test_defaults_without_training(tmp_path):
    _, event = _run(_ctx(tmp_path))
    assert event["gains_source"] == "defaults"
    assert event["gains"] == DEFAULT_GAINS


BROWSER_DONE = {
    "type": "training",
    "source": "browser",
    "status": "done",
    "gains": {"kp_z": 9.1, "kd_att": 0.002, "roll": {"p": 61.4, "i": 999}, "pitch": {"p": 52, "i": 90}},
}
ISAAC_DONE = {"type": "omniverse", "mode": "train", "source": "live", "status": "done", "gains": {"roll": {"p": 70, "d": 44}, "yaw": {"p": 33}}}


def test_browser_gains_from_the_final_training_event(tmp_path):
    ctx = _ctx(tmp_path)
    asyncio.run(ctx.emit(BROWSER_DONE))
    asyncio.run(ctx.emit({"type": "training", "source": "browser", "status": "running", "gains": {"roll": {"p": 10}}}))
    _, event = _run(ctx)
    assert event["gains_source"] == "browser"
    assert event["gains"]["roll"] == {"p": 61, "i": 250, "d": 40, "f": 120}
    assert event["gains"]["pitch"] == {"p": 52, "i": 90, "d": 46, "f": 125}
    assert event["gains"]["yaw"] == DEFAULT_GAINS["yaw"]
    assert "set p_roll = 61" in event["content"]
    assert "# PID gains: the browser-tuned controller" in event["content"]


def test_isaac_gains_win_over_browser_gains(tmp_path):
    ctx = _ctx(tmp_path)
    asyncio.run(ctx.emit(ISAAC_DONE))
    asyncio.run(ctx.emit(BROWSER_DONE))
    _, event = _run(ctx)
    assert event["gains_source"] == "isaac"
    assert event["gains"]["roll"] == {"p": 70, "i": 80, "d": 44, "f": 120}
    assert event["gains"]["yaw"]["p"] == 33
    assert "Isaac Lab" in event["explanation"]


def test_recorded_or_gainless_isaac_results_fall_back(tmp_path):
    ctx = _ctx(tmp_path)
    asyncio.run(ctx.emit({**ISAAC_DONE, "source": "recorded", "status": "recorded"}))
    asyncio.run(ctx.emit({"type": "omniverse", "mode": "train", "source": "live", "status": "done", "metrics": {"final_reward": 1}}))
    asyncio.run(ctx.emit({**ISAAC_DONE, "mode": "test"}))
    _, event = _run(ctx)
    assert event["gains_source"] == "defaults"
    asyncio.run(ctx.emit(BROWSER_DONE))
    _, event = _run(ctx)
    assert event["gains_source"] == "browser"


def test_training_after_the_firmware_rebuilds_it(tmp_path):
    from pai_agent.tools.firmware import refresh_after_training

    ctx = _ctx(tmp_path)
    _, first = _run(ctx)
    assert first["gains_source"] == "defaults"
    asyncio.run(ctx.emit(BROWSER_DONE))
    asyncio.run(refresh_after_training(ctx))
    latest = [event for event in ctx.bus.events if event["type"] == "firmware"]
    assert len(latest) == 2 and latest[-1]["gains_source"] == "browser"
    asyncio.run(refresh_after_training(ctx))
    assert len([event for event in ctx.bus.events if event["type"] == "firmware"]) == 2


def test_explanation_comes_from_the_call(tmp_path):
    _, event = _run(_ctx(tmp_path), {"explanation": "Paste it, then check the motor directions."})
    assert event["explanation"] == "Paste it, then check the motor directions."


def test_arduino_sketch_for_a_servo_product(tmp_path):
    servo = {"id": "mg90s", "name": "MG90S servo", "category": "servo", "voltage_v": 4.8}
    driver = {"id": "pca9685", "name": "PCA9685 driver", "category": "driver"}
    result, event = _run(_ctx(tmp_path, (servo, driver), product="gripper"))
    assert result["ok"] and event["kind"] == "arduino" and event["filename"].endswith(".ino")
    assert "void setup()" in event["content"] and "void loop()" in event["content"]
    assert "driver.writeMicroseconds" in event["content"]
    assert {row["pin"] for row in event["wiring"] if row["component"] == "MG90S servo"} == {"signal", "V+", "GND"}
    _, direct = _run(_ctx(tmp_path, (servo,), product="gripper"))
    assert "#include <Servo.h>" in direct["content"]
    assert all(row["connects_to"] == "Arduino Uno D9" for row in direct["wiring"])


def test_no_parts_is_an_error(tmp_path):
    result = asyncio.run(firmware(_ctx(tmp_path, ()), {}))
    assert result["ok"] is False
