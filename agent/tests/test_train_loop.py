"""The train loop: the missions fly a reference controller or a gain set, training on the missions beats the defaults, the firmware writes exactly the validated gains, and a failed validation goes back to parts, then to the user."""

import asyncio
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from pai_agent.context import Ctx
from pai_agent.drone_geometry import geometry
from pai_agent.mission_sim import AirframeError, Controller, _Flight, airframe, gain_set, run
from pai_agent.mission_train import evaluate, export_gains, reference_gains, roll_pitch_inertia, train
from pai_agent.paths import DATA_DIR
from pai_agent.state import BuildState
from pai_agent.tools.registry import call_tool
from pai_agent.tools.stress import ControllerGains

BASE = ["generic-1103-15000kv", "gemfan-2020-4", "betafpv-matrix-1s-5in1-v2", "twiglet-2in-carbon", "caddx-ant", "toothpick-canopy-holder", "m14-bolts"]
# The missions this build passes on the reference controller; the chase fails on any catalog camera (test_missions).
LIMITS = {"speed_run": 60.0, "turn": 120.0, "hold": 15.0}


class Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _catalog() -> dict:
    return {p["id"]: p for p in json.loads((DATA_DIR / "parts.json").read_text())["parts"]}


def _state(battery: str = "tattu-rline-1s-550") -> BuildState:
    parts = _catalog()
    state = BuildState(session_id="t", directory=Path(tempfile.mkdtemp()))
    for pid in BASE + [battery]:
        state.selected[parts[pid]["category"]] = dict(parts[pid])
    return state


def _frame(state: BuildState | None = None) -> dict:
    state = state or _state()
    return airframe(geometry(state), state.selected)


def test_gains_map_to_the_attitude_loop_through_the_builds_inertia():
    frame = _frame()
    flight = _Flight(frame)
    gains = asdict(ControllerGains())
    k_r, k_w = Controller(gains).rates(flight.inertia, frame["tau"])
    assert k_r[0] == pytest.approx(gains["kp_att"] / flight.inertia[0, 0])
    assert k_w[1] == pytest.approx(gains["kd_att"] / flight.inertia[1, 1])
    # Yaw has no trained gain and keeps the reference loop; so does everything without gains.
    ref_r, ref_w = Controller().rates(flight.inertia, frame["tau"])
    assert k_r[2] == ref_r[2] and np.all(ref_r == ref_r[0]) and ref_w[0] == pytest.approx(1.6 * 28.0)
    assert gain_set({**gains, "kd_att": None}) is None
    with pytest.raises(AirframeError):
        Controller({"kp_z": 1.0})
    # The reference gains in the trainer's units give back the reference bandwidth.
    ref = reference_gains(frame)
    assert ref["kp_att"] / roll_pitch_inertia(frame) == pytest.approx(28.0**2)
    exported = export_gains(ref, roll_pitch_inertia(frame))
    assert set(exported) >= {"kp_z", "ki_z", "kd_z", "kp_xy", "kd_xy", "kp_att", "kd_att", "roll", "pitch"}


def test_a_mission_says_which_controller_flew_it():
    frame = _frame()
    assert run(frame, "turn")["controller"] == "reference"
    assert run(frame, "turn", asdict(ControllerGains()))["controller"] == "trained"


def test_trained_gains_beat_the_default_gains_on_the_missions():
    frame = _frame()
    defaults = asdict(ControllerGains())
    default_score, _terms = evaluate(frame, defaults, LIMITS)
    result = train(frame, LIMITS, population=4, generations=2, time_limit_s=1e9)
    assert result["score"] > default_score + 10
    assert result["score"] >= result["start_score"]
    # The full missions agree: the default gains drift metres off in the gusts and lose speed, the trained ones pass.
    trained = {m: run(frame, m, result["gains"]) for m in ("speed_run", "hold")}
    untrained = {m: run(frame, m, defaults) for m in ("speed_run", "hold")}
    assert trained["hold"]["hold_error_cm"] <= LIMITS["hold"] < untrained["hold"]["hold_error_cm"]
    assert trained["speed_run"]["top_speed_kmh"] > untrained["speed_run"]["top_speed_kmh"]


def _ctx(state: BuildState) -> Ctx:
    return Ctx(Bus(), state, auto_steps=False)


def test_firmware_writes_exactly_the_validated_gains():
    from pai_agent.tools.mission import airframe_of, build_key

    state = _state()
    _metrics, geo, frame = airframe_of(state)
    gains = export_gains(reference_gains(frame), roll_pitch_inertia(frame))
    gains["roll"] = {"p": 61, "i": 99}
    state.validated = {"build": build_key(frame), "mass_g": geo["total_mass_g"], "gains": gains, "missions": {"chase": {"value": 2.4, "unit": "s"}}, "stress": [49, 50], "score": 80.0}
    ctx = _ctx(state)
    result = asyncio.run(call_tool(ctx, "firmware", {}))
    assert result["gains_source"] == "validated" and result["gains_validated"] is True
    assert result["gains"]["roll"]["p"] == 61 and result["gains"]["roll"]["i"] == 99
    content = next(e for e in ctx.bus.events if e["type"] == "firmware")["content"]
    assert "set p_roll = 61" in content and "set i_roll = 99" in content
    assert "mission-validated" in content and "stress test 49/50" in content and f"kd_att {gains['kd_att']:g}" in content
    # Another pack is another build: its gains were never validated, and the file says so.
    parts = _catalog()
    state.selected["battery"] = dict(parts["betafpv-lava-1s-680"])
    again = asyncio.run(call_tool(_ctx(state), "firmware", {}))
    assert again["gains_source"] == "defaults" and again["gains_validated"] is False


def _flown(state: BuildState) -> None:
    """The hardware check: every mission of the fly hunter, on the reference controller."""

    ctx = _ctx(state)
    result = asyncio.run(call_tool(ctx, "simulate_mission", {"missions": [{"mission": m} for m in LIMITS]}))
    assert result["result"] == "pass" and result["controller"] == "reference"


def _quick_training(monkeypatch) -> None:
    """Training itself is tested above; here it hands back the reference gains at once, and the stress test flies 5 worlds."""

    import pai_agent.tools.stress as stress
    import pai_agent.tools.train_loop as loop

    def fake(frame, limits, **_kw):
        gains = export_gains(reference_gains(frame), roll_pitch_inertia(frame))
        return {"gains": gains, "score": 80.0, "start_score": 80.0, "terms": {"hover": {"value": 5.0, "ratio": 1.5}}, "rollouts": 1, "generations": 1, "curve": [[1, 80.0]], "stopped_early": False, "seconds": 0.0}

    monkeypatch.setattr(loop, "train", fake)
    worlds = stress.sample_worlds(5)
    monkeypatch.setattr(stress, "sample_worlds", lambda *a, **k: worlds)


def test_the_loop_validates_on_the_missions_and_the_stress_test(monkeypatch):
    _quick_training(monkeypatch)
    state = _state()
    _flown(state)
    ctx = _ctx(state)
    result = asyncio.run(call_tool(ctx, "train_controller", {}))
    assert result["result"] == "pass", result
    trained = [e for e in ctx.bus.events if e["type"] == "mission"]
    assert [e["controller"] for e in trained] == ["trained"] * 3
    assert all(e["reference"] and e["reference"]["result"] == "pass" for e in trained)
    assert {r["mission"] for r in result["missions"]} == set(LIMITS)
    stress = [e for e in ctx.bus.events if e["type"] == "stress"]
    assert stress[-1]["status"] == "done" and stress[-1]["source"] == "backend" and stress[-1]["gains"]["kp_xy"] == result["gains"]["kp_xy"]
    training = [e for e in ctx.bus.events if e["type"] == "training"]
    assert training[-1]["status"] == "done" and training[-1]["source"] == "backend" and training[-1]["gains"] == result["gains"]
    assert state.validated and state.validated["gains"] == result["gains"]
    # The requirement rows judge the trained run.
    assert state.missions["hold"]["controller"] == "trained"


def test_a_failed_validation_goes_back_to_parts_then_to_the_user(monkeypatch):
    import pai_agent.tools.train_loop as loop

    _quick_training(monkeypatch)
    # No build survives more than every world: the trained result fails on the stress test.
    monkeypatch.setattr(loop, "STRESS_PASS", 1.01)
    state = _state()
    _flown(state)
    first = asyncio.run(call_tool(_ctx(state), "train_controller", {}))
    assert first["result"] == "fail" and first["next_action"] == "parts" and first["loop"] == 1
    assert "back to parts" in first["next"] and state.validated is None
    second = asyncio.run(call_tool(_ctx(state), "train_controller", {}))
    assert second["result"] == "fail" and second["next_action"] == "ask" and "ask_user" in second["next"]


def test_a_failed_hardware_check_trains_nothing(monkeypatch):
    import pai_agent.tools.train_loop as loop

    monkeypatch.setattr(loop, "train", lambda *a, **k: pytest.fail("trained on a failed hardware check"))
    state = _state("tattu-funfly-4s-1300")
    ctx = _ctx(state)
    asyncio.run(call_tool(ctx, "simulate_mission", {"missions": [{"mission": "speed_run", "limit": 200}]}))
    result = asyncio.run(call_tool(ctx, "train_controller", {}))
    assert result["result"] == "fail" and result["stage"] == "hardware"
    assert not any(e["type"] == "training" for e in ctx.bus.events)


def test_the_mock_loop_goes_back_to_parts_and_asks_after_two_fails(monkeypatch):
    import pai_agent.tools.registry as registry
    from pai_agent.mock_story import _train_loop

    calls = []

    async def failing(ctx, args):
        calls.append(args)
        action = "parts" if len(calls) == 1 else "ask"
        row = {"mission": "chase", "unit": "s", "limit": 4.0, "reference": {"value": 2.4, "result": "pass"}, "trained": {"value": None, "result": "fail"}}
        return {"ok": True, "result": "fail", "next_action": action, "why": "Caught 2 of 5 flies.", "missions": [row], "stress": {"survived": 50, "total": 50}}

    monkeypatch.setitem(registry.TOOLS, "train_controller", failing)
    state = _state("betafpv-lava-1s-680")
    _flown(state)
    ctx = _ctx(state)
    asyncio.run(_train_loop(ctx, list(LIMITS)))
    names = [e["name"] for e in ctx.bus.events if e["type"] == "tool" and e["status"] != "running"]
    assert names.count("train_controller") == 2
    # Back to parts between the two: a lighter pack, the numbers, the hardware check again.
    between = names[names.index("train_controller") + 1 : len(names) - 1 - names[::-1].index("train_controller")]
    assert {"parts_search", "physics_calc", "simulate_mission"} <= set(between)
    assert state.selected["battery"]["id"] != "betafpv-lava-1s-680"
    assert names[-1] == "ask_user"


def test_mock_racing_drone_runs_the_loop_offline(monkeypatch, request):
    import shutil

    from pai_agent.mock_story import run_mock
    from pai_agent.paths import SESSIONS_DIR

    text = "Build me a racing drone"
    monkeypatch.setattr("pai_agent.tools.cad.ensure_gui", lambda: False)
    monkeypatch.setattr("pai_agent.tools.cad.find_freecadcmd", lambda: None)
    monkeypatch.setattr("pai_agent.freecad_run.find_freecadcmd", lambda: None)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(dir=SESSIONS_DIR))
    request.addfinalizer(lambda: shutil.rmtree(directory, True))
    state = BuildState(session_id=directory.name, directory=directory)
    state.requests.append(text)
    ctx = _ctx(state)
    asyncio.run(run_mock(ctx, text))
    missions = [e for e in ctx.bus.events if e["type"] == "mission"]
    assert [(m["mission"], m["controller"]) for m in missions] == [("speed_run", "reference"), ("turn", "reference"), ("speed_run", "trained"), ("turn", "trained")]
    assert all(m["result"] == "pass" for m in missions) and all(m["reference"] for m in missions[2:])
    done = [e for e in ctx.bus.events if e["type"] == "training" and e["status"] == "done"]
    assert len(done) == 1 and done[0]["source"] == "backend" and done[0]["rollouts_total"] == 18
    assert [e for e in ctx.bus.events if e["type"] == "stress"][-1]["source"] == "backend"
    firmware = [e for e in ctx.bus.events if e["type"] == "firmware"][-1]
    assert firmware["gains_source"] == "validated" and "set p_roll = " + str(state.validated["gains"]["roll"]["p"]) in firmware["content"]
    assert state.versions and state.finished
