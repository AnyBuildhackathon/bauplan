"""Safety check: the drone class and battery note, the gripper pinch point, the 230 V lamp mains warning.

Run with: cd agent && uv run --with pytest pytest tests/test_safety.py
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.mock_lamp import run_lamp_mock, wants_lamp
from pai_agent.state import BuildState
from pai_agent.tools.gripper import CATEGORIES, gripper_catalog
from pai_agent.tools.safety import safety_check

CATALOG = {part["id"]: part for part in json.loads((Path(__file__).resolve().parents[1] / "data" / "parts.json").read_text())["parts"]}
V1 = ("generic-1103-15000kv", "gemfan-2020-4", "tattu-rline-1s-550", "betafpv-matrix-1s-5in1-v2", "twiglet-2in-carbon", "caddx-ant")


def _ctx(tmp_path: Path) -> Ctx:
    return Ctx(EventBus(), BuildState("test", tmp_path), auto_steps=False)


def _drone(tmp_path: Path, weight_g: float) -> Ctx:
    ctx = _ctx(tmp_path)
    for part_id in V1:
        ctx.state.selected[CATALOG[part_id]["category"]] = CATALOG[part_id]
    ctx.state.metrics = {"weight_g": weight_g}
    return ctx


def _safety_events(ctx: Ctx) -> list[dict]:
    return [e for e in ctx.bus.events if e["type"] == "safety"]


def test_drone_is_c0_with_battery_note(tmp_path):
    ctx = _drone(tmp_path, 38.4)
    result = asyncio.run(safety_check(ctx, {}))
    by_id = {f["id"]: f for f in result["findings"]}
    assert by_id["drone-class"]["severity"] == "info"
    assert "C0" in by_id["drone-class"]["title"]
    assert "2019/945" in by_id["drone-class"]["rule"]
    battery = by_id["lithium-battery"]
    assert battery["severity"] == "warning"
    assert "2.0 Wh" in battery["title"]
    assert "UN3481" in battery["reason"] and "IATA" in battery["rule"]
    # The warning outranks the info, so Mechanic leads with the battery.
    assert result["top"]["id"] == "lithium-battery"
    event = _safety_events(ctx)[-1]
    assert event["findings"] == result["findings"]
    assert "not legal advice" in event["disclaimer"]


def test_heavy_drone_leaves_c0(tmp_path):
    result = asyncio.run(safety_check(_drone(tmp_path, 420), {}))
    finding = next(f for f in result["findings"] if f["id"] == "drone-class")
    assert finding["severity"] == "warning" and "C1" in finding["title"] and "remote ID" in finding["reason"]


def test_gripper_pinch_point_has_fix(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.state.product = "gripper"
    parts = gripper_catalog()["parts"]
    for category in CATEGORIES:
        ctx.state.selected[category] = next(p for p in parts if p["category"] == category)
    result = asyncio.run(safety_check(ctx, {}))
    pinch = result["top"]
    assert pinch["id"] == "pinch-point"
    assert "ISO 13857" in pinch["rule"]
    assert "cover" in pinch["fix"] and "firmware" in pinch["fix"]


def test_lamp_mock_flags_mains_and_applies_the_fix(tmp_path):
    prompt = "Design a 230 V desk lamp with an E14 bulb on a 200 mm arm"
    assert wants_lamp(prompt)
    ctx = _ctx(tmp_path)
    asyncio.run(run_lamp_mock(ctx, prompt))
    first, second = _safety_events(ctx)
    mains = first["findings"][0]
    assert mains["id"] == "mains-voltage" and mains["severity"] == "danger"
    assert "2014/35/EU" in mains["rule"] and "USB-C" in mains["fix"]
    # The default answer switches to USB-C 5 V and the check runs again without the mains finding.
    assert all(f["id"] != "mains-voltage" for f in second["findings"])
    assert any(e["type"] == "chat" and "mains warning is gone" in e["text"] for e in ctx.bus.events)


def test_claude_findings_merge_and_sort(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.state.product = "generic"
    result = asyncio.run(
        safety_check(
            ctx,
            {
                "context": "A toy for kids",
                "findings": [
                    {"severity": "danger", "title": "Sharp edge on the lid", "reason": "Printed corners", "rule": "EN 71-1 sharp edges", "fix": "Round the corners 2 mm"},
                    {"severity": "loud", "title": "Odd severity", "reason": "", "rule": "", "fix": ""},
                    {"title": ""},
                ],
            },
        )
    )
    findings = result["findings"]
    assert [f["severity"] for f in findings] == ["danger", "warning", "info"]
    assert findings[0]["source"] == "claude" and findings[1]["id"] == "small-parts"


def test_no_mains_warning_without_mains(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.state.product = "generic"
    result = asyncio.run(safety_check(ctx, {"context": "A USB-C desk lamp on 5 V"}))
    assert all(f["id"] != "mains-voltage" for f in result["findings"])
