"""Mission tests fly the drone built from its parts: deterministic numbers, a heavier or weaker build measurably worse, every mission a requirement check, and one geometry for the model, the sim and the bill of materials."""

import asyncio
import json
import shutil
import struct
import tempfile
from pathlib import Path

import pytest

from pai_agent.context import Ctx
from pai_agent.drone_geometry import geometry
from pai_agent.mission_sim import airframe, run
from pai_agent.paths import DATA_DIR
from pai_agent.state import BuildState
from pai_agent.tools.physics import compute
from pai_agent.tools.registry import call_tool

BASE = ["generic-1103-15000kv", "gemfan-2020-4", "betafpv-matrix-1s-5in1-v2", "twiglet-2in-carbon", "caddx-ant", "toothpick-canopy-holder", "m14-bolts"]
FLY = "a fly hunter drone, incredibly fast, small and light, under 100 euros"


class Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _catalog() -> dict:
    return {p["id"]: p for p in json.loads((DATA_DIR / "parts.json").read_text())["parts"]}


def _state(battery: str, *requests: str) -> BuildState:
    parts = _catalog()
    state = BuildState(session_id="t", directory=Path(tempfile.mkdtemp()))
    for pid in BASE + [battery]:
        state.selected[parts[pid]["category"]] = dict(parts[pid])
    state.requests.extend(requests)
    return state


def _frame(battery: str) -> dict:
    state = _state(battery)
    return airframe(geometry(state), state.selected)


@pytest.fixture(scope="module")
def flights() -> dict:
    """Every mission for the 1S R-Line build and the 4S FunFly build, flown once for the module."""

    out = {}
    for battery in ("tattu-rline-1s-550", "tattu-funfly-4s-1300"):
        frame = _frame(battery)
        out[battery] = {mission: run(frame, mission) for mission in ("speed_run", "turn", "hold", "chase")}
    return out


def test_geometry_weighs_what_physics_and_the_bom_count():
    for battery in ("tattu-rline-1s-550", "betafpv-lava-1s-680", "tattu-funfly-4s-1300"):
        state = _state(battery)
        geo = geometry(state)
        assert geo["total_mass_g"] == pytest.approx(compute(state)["weight_g"], abs=0.1)
        # Every part on the bill of materials is in the model: the ids match the selection.
        assert {m["id"] for m in geo["masses"]} == {part["id"] for part in state.selected.values()}
        assert geo["battery"]["size_mm"] == [state.selected["battery"][k] for k in ("length_mm", "width_mm", "height_mm")]
        assert geo["propeller"]["diameter_mm"] == 51 and geo["motor"]["stator_diameter_mm"] == 11 and geo["motor"]["stator_height_mm"] == 3
        assert geo["assumed"] == []


def test_mujoco_inertia_comes_from_the_parts():
    light, heavy = _frame("tattu-rline-1s-550"), _frame("tattu-funfly-4s-1300")
    from pai_agent.mission_sim import _Flight

    a, b = _Flight(light), _Flight(heavy)
    assert a.mass == pytest.approx(light["geo"]["total_mass_g"] / 1000, rel=1e-3)
    assert b.mass == pytest.approx(heavy["geo"]["total_mass_g"] / 1000, rel=1e-3)
    # The 150 g pack sits under the plate: more roll inertia, a lower centre of mass.
    assert b.inertia[0, 0] > 2 * a.inertia[0, 0]
    assert heavy["geo"]["com_mm"][2] < light["geo"]["com_mm"][2]


def test_missions_are_deterministic():
    frame = _frame("tattu-rline-1s-550")
    for mission in ("speed_run", "turn", "hold", "chase"):
        first, second = run(frame, mission), run(frame, mission)
        assert first == second, mission


def test_reference_build_numbers(flights):
    light = flights["tattu-rline-1s-550"]
    assert light["speed_run"]["top_speed_kmh"] == pytest.approx(83.0, abs=0.5)
    assert light["speed_run"]["time_to_top_s"] < 2.5
    assert light["turn"]["turn_rate_dps"] == pytest.approx(154.6, abs=3)
    assert light["hold"]["hold_error_cm"] == pytest.approx(11.3, abs=1)
    assert not any(outcome["crashed"] for outcome in light.values())
    # The pack sags under the speed run's 30 A and drains: 8 s flat out takes about 50 mAh of 550.
    run_pack = light["speed_run"]
    assert run_pack["pack_v_start"] > run_pack["pack_v_min"] + 0.2 and 40 < run_pack["pack_used_mah"] < 60


def test_the_chase_sees_flies_only_through_its_camera(flights):
    """The Caddx Ant's 165 degrees on 720 pixels show a 6 mm fly over 2 pixels within 0.94 m, each fix 68 ms late:
    the fly starts 2.3 m away and the reference pursuit catches at most one of five, so no median capture."""

    chase = flights["tattu-rline-1s-550"]["chase"]
    assert chase["detect_range_m"] == pytest.approx(0.94, abs=0.01)
    assert chase["sensing_delay_ms"] == pytest.approx(68, abs=1)
    assert chase["captured"] <= 1 and chase["capture_s"] is None
    assert chase["first_fix_s"] is not None and chase["tracks_lost"] > 0
    # With a near-perfect camera (no delay, 500 frames a second, all-round view, far sight) the same build catches flies again.
    frame = _frame("tattu-rline-1s-550")
    frame["camera"] = dict(frame["camera"], ifov=frame["camera"]["ifov"] / 100, delay_s=0.0, fov_h=3.12, fov_v=3.12, fps=500.0)
    assert run(frame, "chase")["captured"] >= 3


def test_a_heavier_build_loses_speed_and_the_chase(flights):
    light, heavy = flights["tattu-rline-1s-550"], flights["tattu-funfly-4s-1300"]
    assert heavy["speed_run"]["top_speed_kmh"] < 0.7 * light["speed_run"]["top_speed_kmh"]
    assert heavy["speed_run"]["time_to_top_s"] > 2 * light["speed_run"]["time_to_top_s"]
    # At thrust-to-weight 1.1 it cannot lean into a 90 degree turn at 29 km/h.
    assert heavy["turn"]["turn_rate_dps"] < light["turn"]["turn_rate_dps"] / 2
    # Neither camera-guided chase catches its flies; the heavy build never gets near one.
    assert heavy["chase"]["captured"] <= light["chase"]["captured"]
    assert heavy["chase"]["miss_distance_cm"] > 3 * light["chase"]["miss_distance_cm"]
    assert heavy["chase"]["capture_s"] is None


def test_a_weaker_motor_loses_speed_and_turn():
    state = _state("tattu-rline-1s-550")
    weak = dict(state.selected["motor"], thrust_g=22.0, kv=11000)
    state.selected["motor"] = weak
    frame = airframe(geometry(state), state.selected)
    reference = _frame("tattu-rline-1s-550")
    assert run(frame, "speed_run")["top_speed_kmh"] < run(reference, "speed_run")["top_speed_kmh"] - 10
    assert run(frame, "turn")["turn_rate_dps"] < run(reference, "turn")["turn_rate_dps"]


def test_a_part_with_fewer_fields_still_flies():
    state = _state("tattu-rline-1s-550")
    state.selected["propeller"] = {"id": "web-prop", "name": "Found prop", "category": "propeller", "bom_qty": 4, "mass_g": 1.0, "diameter_mm": 65}
    state.selected["battery"] = {"id": "web-pack", "name": "Found pack", "category": "battery", "bom_qty": 1, "mass_g": 20, "voltage_v": 3.8, "capacity_mah": 750, "cells": 1}
    geo = geometry(state)
    assert "battery length" in geo["assumed"] and geo["propeller"]["diameter_mm"] == 65
    assert run(airframe(geo, state.selected), "speed_run")["top_speed_kmh"] > 0


def test_simulate_mission_makes_requirement_checks():
    state = _state("tattu-rline-1s-550", FLY + ", catches a fly in 3 s")
    state.product = "drone"
    ctx = Ctx(Bus(), state, auto_steps=False)
    args = {"missions": [{"mission": "speed_run"}, {"mission": "chase", "limit": 3, "quote": "catches a fly in 3 s"}]}
    result = asyncio.run(call_tool(ctx, "simulate_mission", args))
    assert result["ok"] is not False and result["result"] == "fail"
    rows = {e["id"]: e for e in ctx.bus.events if e.get("type") == "requirement"}
    assert rows["top_speed"]["source"] == "proposed" and rows["top_speed"]["speaker"] == "Mechanic"
    assert rows["top_speed"]["text"] == "Top speed at least 60 km/h" and rows["top_speed"]["met"] is True
    assert rows["chase_time"]["source"] == "user" and rows["chase_time"]["source_quote"] == "catches a fly in 3 s"
    # The camera cannot see the fly far enough: the chase fails and says why.
    assert rows["chase_time"]["met"] is False
    chase = next(m for m in result["missions"] if m["mission"] == "chase")
    assert "0.9 m" in chase["why"] and "68 ms" in chase["why"]
    missions = [e for e in ctx.bus.events if e.get("type") == "mission"]
    assert [m["mission"] for m in missions] == ["speed_run", "chase"]
    assert missions[1]["target"] and missions[1]["poses"] and missions[0]["parts"]["battery"] == "tattu-rline-1s-550"
    assert missions[0]["metrics"]["pack_used_mah"] > 0 and missions[1]["metrics"]["detect_range_m"] > 0
    assert any(e.get("type") == "geometry" for e in ctx.bus.events)

    # A limit the build cannot reach fails, and the result says what limits it.
    harder = asyncio.run(call_tool(ctx, "simulate_mission", {"missions": [{"mission": "speed_run", "limit": 100}]}))
    assert harder["result"] == "fail" and "pitch speed" in harder["missions"][0]["why"]
    rows = {e["id"]: e for e in ctx.bus.events if e.get("type") == "requirement"}
    assert rows["top_speed"]["met"] is False and rows["top_speed"]["changed_from"] == "Top speed at least 60 km/h"


def test_simulate_mission_needs_the_parts():
    state = BuildState(session_id="t", directory=Path(tempfile.mkdtemp()))
    ctx = Ctx(Bus(), state, auto_steps=False)
    result = asyncio.run(call_tool(ctx, "simulate_mission", {"missions": ["hold"]}))
    assert result["ok"] is False and "Parts missing" in result["error"]
    bad = asyncio.run(call_tool(ctx, "simulate_mission", {"missions": ["loop"]}))
    assert bad["ok"] is False and "Unknown mission" in bad["error"]


def test_brief_takes_mission_limits_and_a_revision_keeps_them():
    state = BuildState(session_id="t", directory=Path(tempfile.mkdtemp()))
    state.requests.append("a racer that reaches 90 km/h under 150 euros")
    ctx = Ctx(Bus(), state, auto_steps=False)
    brief = {"product": "drone", "requirements": [{"id": "top_speed", "limit": 90, "quote": "reaches 90 km/h"}, {"id": "budget", "limit": 150, "quote": "under 150 euros"}]}
    asyncio.run(call_tool(ctx, "product_brief", brief))
    assert {r["id"] for r in state.requirements} == {"top_speed", "budget", "hover", "printable"}
    state.selected = _state("tattu-rline-1s-550").selected
    asyncio.run(call_tool(ctx, "product_brief", {"product": "drone", "requirements": [{"id": "budget", "limit": 120, "quote": "under 150 euros"}]}))
    assert next(r for r in state.requirements if r["id"] == "top_speed")["source"] == "user"


def _glb_json(path: Path) -> dict:
    data = path.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20 : 20 + length])


def test_cadquery_builds_the_whole_drone_from_its_parts(tmp_path):
    from pai_agent import drone_assembly

    state = _state("betafpv-lava-1s-680")
    state.selected["propeller"] = dict(state.selected["propeller"], diameter_mm=40.0, blades=3)
    params = {"arm_length_mm": 42.5, "thickness_mm": 2.0, "motor_spacing_mm": 6.6}
    geo = geometry(state, params)
    mass = drone_assembly.build(tmp_path, params, geo)
    assert mass > 1 and (tmp_path / "drone.step").stat().st_size > 1000 and (tmp_path / "frame.step").is_file()
    doc = _glb_json(tmp_path / "frame.glb")
    nodes = {n["name"]: n for n in doc["nodes"]}
    for name in ("frame", "battery", "flight_controller", "motor_front_left", "propeller_rear_right"):
        assert name in nodes, name
    assert nodes["battery"]["extras"]["size_mm"] == [80, 15, 6.5]
    assert nodes["drone"]["extras"]["prop_mm"] == 40.0 and nodes["drone"]["extras"]["motor_diameter_mm"] == 14
    # Props hang under their motors, so they spin about the shaft; the motor sits on the X corner.
    assert nodes["motor_front_left"]["children"] and nodes["motor_front_left"]["translation"][0] < 0 and nodes["motor_front_left"]["translation"][2] < 0
    # The propeller mesh spans its real diameter.
    prop_mesh = doc["meshes"][nodes["propeller_front_left"]["mesh"]]
    accessor = doc["accessors"][prop_mesh["primitives"][0]["attributes"]["POSITION"]]
    span = max(accessor["max"][0] - accessor["min"][0], accessor["max"][2] - accessor["min"][2])
    assert span == pytest.approx(0.040, abs=0.004)


def test_mock_fly_hunter_flies_its_missions(monkeypatch, request):
    from pai_agent.mock_story import missions_from_text, run_mock

    assert missions_from_text(FLY) == ["speed_run", "turn", "chase"]
    assert missions_from_text("Build a micro drone under 120 euros with at least 8 minutes of flight time, under 50 g.") == []
    monkeypatch.setattr("pai_agent.tools.cad.ensure_gui", lambda: False)
    monkeypatch.setattr("pai_agent.tools.cad.find_freecadcmd", lambda: None)
    monkeypatch.setattr("pai_agent.freecad_run.find_freecadcmd", lambda: None)
    from pai_agent.paths import SESSIONS_DIR

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(dir=SESSIONS_DIR))
    request.addfinalizer(lambda: shutil.rmtree(directory, True))
    state = BuildState(session_id=directory.name, directory=directory)
    state.requests.append(FLY)
    ctx = Ctx(Bus(), state, auto_steps=False)
    asyncio.run(run_mock(ctx, FLY))
    missions = [e for e in ctx.bus.events if e.get("type") == "mission"]
    assert [m["mission"] for m in missions] == ["speed_run", "turn", "chase"]
    assert [m["result"] for m in missions] == ["pass", "pass", "fail"]
    assert "camera" in missions[2]["why"]
    # The camera loses the chase on the reference controller: the hardware check fails, so nothing is trained.
    assert all(m["controller"] == "reference" for m in missions)
    rows = {r["id"]: r for r in state.requirements}
    assert {"top_speed", "turn_rate", "chase_time"} <= set(rows) and rows["top_speed"]["source"] == "proposed"
    assert not any(e.get("type") == "training" for e in ctx.bus.events) and state.validated is None
    assert state.versions and state.finished
