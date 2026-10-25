"""Live part discovery: specs copied from a real page, units converted, implausible or missing numbers refused, never invented."""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from pai_agent import web_parts
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools.physics import compute
from pai_agent.tools.registry import call_tool

MOTOR = {
    "found": True,
    "name": "T-Motor F1404 3800KV",
    "url": "https://store.tmotor.com/product/f1404-motor.html",
    "shop": "T-Motor",
    "price": 19.9,
    "currency": "USD",
    "pack_qty": 1,
    "in_stock": True,
    "specs": {
        "mass_g": [9.6, "g"],
        "thrust_g": [418, "g"],
        "bench_voltage_v": [16.8, "V"],
        "bench_current_a": [13.2, "A"],
        "bench_power_w": [221.8, "W"],
        "kv": [3800, "KV"],
        "diameter_mm": [18.3, "mm"],
        "height_mm": [1.42, "cm"],
        "cells_max": [4, "S"],
        "mount_diameter_mm": [9, "mm"],
    },
    "estimated": [],
    "note": "100 % row on a T3x2x3 prop.",
}


class Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(web_parts, "CACHE_PATH", tmp_path / "web_parts.json")
    web_parts.clear()
    yield
    web_parts.clear()


def test_a_good_motor_answer_becomes_a_web_part():
    part, problems = web_parts.validate("motor", MOTOR, today="2026-10-25")
    assert problems == []
    assert part["provenance"] == "web" and part["source_url"] == MOTOR["url"] and part["checked"] == "2026-10-25"
    assert part["height_mm"] == 14.2  # 1.42 cm in the catalog's mm
    assert part["bench"] == {"voltage_v": 16.8, "thrust_g": 418.0, "power_w": 221.8, "current_a": 13.2}
    assert part["efficiency_g_per_w"] == round(418 / 221.8, 2)
    assert part["unit_price_eur"] == round(19.9 / 1.1193, 2)
    assert part["bom_qty"] == 4 and part["cells_max"] == 4


def test_a_missing_required_spec_refuses_the_part():
    answer = json.loads(json.dumps(MOTOR))
    del answer["specs"]["thrust_g"]
    part, problems = web_parts.validate("motor", answer)
    assert part is None
    assert any("thrust_g is not on the page" in p for p in problems)


def test_a_required_spec_may_not_be_an_estimate():
    answer = {**MOTOR, "estimated": ["thrust_g"]}
    part, problems = web_parts.validate("motor", answer)
    assert part is None and any("may not be an estimate" in p for p in problems)


def test_unknown_units_and_implausible_numbers_are_refused():
    answer = json.loads(json.dumps(MOTOR))
    answer["specs"]["mass_g"] = [9.6, "stone"]
    answer["specs"]["kv"] = [380000, "KV"]
    part, problems = web_parts.validate("motor", answer)
    assert part is None
    assert any("not a g unit" in p for p in problems)
    assert any("kv = 380000" in p for p in problems)


def test_cross_field_physics_catches_a_mistyped_table():
    answer = json.loads(json.dumps(MOTOR))
    answer["specs"]["bench_power_w"] = [22.18, "W"]  # one digit lost: 18.8 g/W and 22 W against 13.2 A x 16.8 V
    part, problems = web_parts.validate("motor", answer)
    assert part is None
    assert any("efficiency" in p for p in problems)
    assert any("does not match" in p for p in problems)


def test_battery_voltage_per_cell_and_energy_density():
    pack = {
        "found": True, "name": "Pack", "url": "https://shop.example.com/p/1", "price": 30, "currency": "EUR",
        "specs": {"cells": [4, "S"], "voltage_v": [14.8, "V"], "capacity_mah": [1.5, "Ah"], "mass_g": [180, "g"],
                  "length_mm": [72, "mm"], "width_mm": [35, "mm"], "height_mm": [34, "mm"], "c_rating": [100, "C"]},
    }
    part, problems = web_parts.validate("battery", pack)
    assert problems == [] and part["capacity_mah"] == 1500
    wrong = json.loads(json.dumps(pack))
    wrong["specs"]["voltage_v"] = [11.1, "V"]
    wrong["specs"]["mass_g"] = [12, "g"]
    _part, problems = web_parts.validate("battery", wrong)
    assert any("per cell" in p for p in problems)
    assert any("Energy density" in p for p in problems)


def test_a_unit_named_after_its_kind_is_accepted():
    answer = json.loads(json.dumps(MOTOR))
    answer["specs"]["cells_max"] = ["4", "count"]
    answer["specs"]["kv"] = [3800, "kv"]
    part, problems = web_parts.validate("motor", answer)
    assert problems == [] and part["cells_max"] == 4


def test_no_url_no_price_no_part():
    part, problems = web_parts.validate("motor", {**MOTOR, "url": "not a page", "price": 0})
    assert part is None
    assert "No product page URL." in problems and "No price." in problems


def test_not_found_says_why():
    part, problems = web_parts.validate("motor", {"found": False, "why": "no 0603 motor with a load table"})
    assert part is None and "0603" in problems[0]


def test_generic_part_takes_size_and_mass():
    servo = {
        "found": True, "name": "Servo", "url": "https://www.pololu.com/product/2818", "price": 8.4, "currency": "USD",
        "specs": {"mass_g": [9, "g"], "length_mm": [23.2, "mm"], "width_mm": [12.5, "mm"], "height_mm": [22, "mm"], "stall_torque_kgcm": [1.5, "kg cm"], "voltage_v": [6, "V"]},
    }
    part, problems = web_parts.validate("servo", servo)
    assert problems == []
    assert part["size_mm"] == [23.2, 12.5, 22.0] and part["stall_torque_kgcm"] == 1.5


def test_offline_discovery_refuses_without_a_key(monkeypatch):
    monkeypatch.setattr(web_parts, "enabled", lambda: False)
    result = asyncio.run(web_parts.discover("motor", "4S 1404 motor"))
    assert result["ok"] is False and "ANTHROPIC_API_KEY" in result["error"]


def _ctx() -> Ctx:
    state = BuildState(session_id="t", directory=Path(tempfile.mkdtemp()))
    return Ctx(Bus(), state, auto_steps=False)


def test_parts_search_web_find_is_selectable_and_flies(monkeypatch):
    monkeypatch.setattr(web_parts, "enabled", lambda: True)
    monkeypatch.setattr(web_parts, "_ask_claude", lambda request, deadline: "Here it is: " + json.dumps(MOTOR))
    ctx = _ctx()
    found = asyncio.run(call_tool(ctx, "parts_search", {"category": "motor", "web": True, "need": "4S 1404 motor, 400 g thrust"}))
    assert found["ok"] is True
    web_id = found["web_find"]["id"]
    assert found["parts"][0]["id"] == web_id and found["parts"][0]["provenance"] == "web"
    picked = asyncio.run(call_tool(ctx, "parts_search", {"category": "motor", "select_id": web_id, "reason": "4S 1404 class"}))
    assert picked["selected_id"] == web_id
    part_event = [e for e in ctx.bus.events if e.get("type") == "part"][-1]
    assert part_event["provenance"] == "web" and part_event["source_url"] == MOTOR["url"]
    for category, part_id in (("propeller", "gemfan-d63-3"), ("battery", "betafpv-lava-4s-550"), ("flight_controller", "betafpv-cube-2-4s-30a"), ("frame", "betafpv-pavo25-v2")):
        asyncio.run(call_tool(ctx, "parts_search", {"category": category, "select_id": part_id}))
    metrics = compute(ctx.state)
    assert metrics["thrust_g"] == pytest.approx(4 * 418)  # 15.2 V is within 10 % of the 16.8 V test voltage
    assert metrics["top_speed_mps"] > 0


def test_a_refused_web_answer_is_an_error_with_the_library(monkeypatch):
    monkeypatch.setattr(web_parts, "enabled", lambda: True)
    bad = {**MOTOR, "specs": {**MOTOR["specs"], "kv": [3, "KV"]}}
    monkeypatch.setattr(web_parts, "_ask_claude", lambda request, deadline: json.dumps(bad))
    result = asyncio.run(call_tool(_ctx(), "parts_search", {"category": "motor", "web": True, "need": "4S motor"}))
    assert result["ok"] is False
    assert "validation" in result["error"]
    assert result["library"]


def test_part_pick_web_find_for_any_product(monkeypatch):
    monkeypatch.setattr(web_parts, "enabled", lambda: True)
    servo = {
        "found": True, "name": "FEETECH FS90 micro servo", "url": "https://www.pololu.com/product/2818", "price": 8.4, "currency": "USD",
        "specs": {"mass_g": [9, "g"], "length_mm": [23.2, "mm"], "width_mm": [12.5, "mm"], "height_mm": [22, "mm"], "stall_torque_kgcm": [1.5, "kg cm"]},
    }
    monkeypatch.setattr(web_parts, "_ask_claude", lambda request, deadline: json.dumps(servo))
    ctx = _ctx()
    spec = {
        "name": "Pan head", "function": "Pans a camera.", "quote": "a pan head",
        "requirements": [{"text": "Under 100 g", "check": "mass", "max": 100}],
        "parts": [
            {"id": "base", "name": "Base", "kind": "printed", "material": "PLA", "description": "A 40 x 30 x 10 mm block with a servo pocket.", "size_mm": [40, 30, 10], "params": {"width_mm": 40}},
            {"id": "servo", "name": "Pan servo", "kind": "bought", "category": "servo", "query": "micro servo", "size_mm": [23, 12, 22], "position_mm": [0, 0, 21]},
        ],
    }
    assert asyncio.run(call_tool(ctx, "product_spec", spec))["ok"] is True
    found = asyncio.run(call_tool(ctx, "part_pick", {"part_id": "servo", "web": True, "query": "9 g micro servo, 1.5 kg cm"}))
    assert found["ok"] is True
    web_id = found["matches"][0]["id"]
    picked = asyncio.run(call_tool(ctx, "part_pick", {"part_id": "servo", "select_id": web_id}))
    assert picked["ok"] is True and ctx.state.picked["servo"]["provenance"] == "web"
