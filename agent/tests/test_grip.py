"""The grip test with the gripper template's real finger kinematics.

The fingers swing on their gears, so the pads meet the object with their tips, and the
object's weight drags the tips further shut. The old test pressed parallel pads with the
force at the pad centre and passed an MG996R on a 4 cm cube of 400 g at 2.43x safety; Robo
Use, running the gripper from its CAD in MuJoCo, saw that cube slide out. That case is the
regression, next to the rest of Robo Use's table.

Run with: cd agent && uv run --with pytest pytest tests/test_grip.py
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest

from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.grip_sim import Fingers, contact, run_grip
from pai_agent.state import BuildState
from pai_agent.tools.gripper import compute_grip, gripper_catalog, simulate_grip
from pai_agent.tools.stress_grip import run_grip_world, sample_grip_worlds

SERVOS = {"SG90": "towerpro-sg90", "MG90S": "towerpro-mg90s", "MG996R": "towerpro-mg996r"}


def _ctx(tmp_path: Path, servo: str, mass_g: float, width_mm: float = 40.0, params: dict | None = None) -> Ctx:
    ctx = Ctx(EventBus(), BuildState("test", tmp_path), auto_steps=False)
    ctx.state.product = "gripper"
    ctx.state.brief = {"object_mass_g": mass_g, "object_width_mm": width_mm, "max_weight_g": None, "budget_eur": None}
    parts = {part["id"]: part for part in gripper_catalog()["parts"]}
    for part_id in (SERVOS[servo], "pads-tpu-printed", "m3-hardware-set", "pca9685-driver"):
        ctx.state.selected[parts[part_id]["category"]] = dict(parts[part_id])
    if params is not None:
        ctx.state.part = {"params": params}
    return ctx


def test_pad_tips_meet_a_4_cm_cube_74_mm_from_the_gear_axis():
    tip = contact(Fingers(), 40.0)
    assert math.degrees(tip.angle_rad) == pytest.approx(14.2, abs=0.05)
    # The old calculation took the pad centre, 0.775 x 70 = 54.25 mm.
    assert tip.lever_mm == pytest.approx(74.24, abs=0.01)
    assert tip.offset_mm == pytest.approx(8.0)
    # A barely narrower object closes the fingers by a hair, and the tip sits a finger length away.
    almost = contact(Fingers(), 75.9)
    assert almost.angle_rad == pytest.approx(0.0, abs=0.01) and almost.lever_mm == pytest.approx(70.0, abs=0.3)
    assert contact(Fingers(), 76.0) is None


def test_report_case_mg996r_no_longer_holds_400_g_cube(tmp_path):
    ctx = _ctx(tmp_path, "MG996R", 400.0)
    metrics = compute_grip(ctx.state)
    # Before: 5.95 N per finger, safety 2.43, and the grip test passed with 4.1 mm slip.
    assert metrics["grip_force_n"] == pytest.approx(4.34, abs=0.01)
    assert metrics["safety_factor"] == pytest.approx(1.94, abs=0.01)
    assert metrics["max_payload_g"] == pytest.approx(388, abs=1)
    result = asyncio.run(simulate_grip(ctx, {}))
    # It rides through lift and shake, then slides out when pulled with twice its weight.
    assert result["result"] == "fail" and result["failed_at"] == "pull"
    assert not result["dropped"] and result["slip_mm"] < 10
    assert "slides out at 2x its weight" in result["summary"]
    sim = next(e for e in ctx.bus.events if e["type"] == "sim")
    assert sim["kind"] == "grip" and sim["result"] == "fail" and sim["force_n"] == metrics["grip_force_n"]


# Robo Use's run of the CAD gripper on the same cube: (servo, grams, reached the bowl).
ROBO_USE = [
    ("SG90", 25, True),
    ("SG90", 100, False),
    ("MG90S", 25, True),
    ("MG90S", 100, False),
    ("MG996R", 200, True),
    ("MG996R", 400, False),
    ("MG996R", 800, False),
]


@pytest.mark.parametrize(("servo", "grams", "holds"), ROBO_USE)
def test_grip_test_agrees_with_robo_use(tmp_path, servo, grams, holds):
    ctx = _ctx(tmp_path, servo, grams)
    metrics = compute_grip(ctx.state)
    assert (metrics["safety_factor"] >= 2.0) is holds
    result = asyncio.run(simulate_grip(ctx, {}))
    assert (result["result"] == "pass") is holds


def test_mujoco_squeeze_matches_the_kinematics(tmp_path):
    ctx = _ctx(tmp_path, "MG996R", 200.0)
    metrics = compute_grip(ctx.state)
    result = asyncio.run(simulate_grip(ctx, {}))
    assert result["result"] == "pass" and result["slip_mm"] < 2
    # Measured on the pads just before the lift, with no weight on them yet.
    assert result["squeeze_n"] == pytest.approx(metrics["grip_force_n"], rel=0.05)


def test_wider_object_than_the_jaws_fails_without_a_simulation(tmp_path):
    ctx = _ctx(tmp_path, "MG996R", 200.0, width_mm=80.0, params={"jaw_opening_mm": 76.0, "finger_length_mm": 70.0})
    metrics = compute_grip(ctx.state)
    assert metrics["safety_factor"] == 0 and any("jaws open only 76 mm" in w for w in metrics["warnings"])
    result = asyncio.run(simulate_grip(ctx, {}))
    assert result["result"] == "fail" and result["failed_at"] == "fit" and "jaws open only 76 mm" in result["summary"]
    # Before the part is built, and for a part without the template's opening, the jaws are planned 10 mm wider than the object.
    planned = compute_grip(_ctx(tmp_path, "MG996R", 200.0, width_mm=80.0).state)
    assert planned["opening_mm"] == 90.0 and planned["safety_factor"] > 2
    custom = compute_grip(_ctx(tmp_path, "MG996R", 200.0, width_mm=80.0, params={"finger_length_mm": 70.0}).state)
    assert custom["opening_mm"] == 90.0 and custom["safety_factor"] == planned["safety_factor"]


def test_longer_fingers_squeeze_less(tmp_path):
    short = compute_grip(_ctx(tmp_path, "MG996R", 200.0, params={"finger_length_mm": 60.0}).state)
    long = compute_grip(_ctx(tmp_path, "MG996R", 200.0, params={"finger_length_mm": 90.0}).state)
    assert long["grip_force_n"] < short["grip_force_n"]


def test_stress_worlds_run_the_same_fingers():
    torque = 9.4 * 9.80665 / 100 * 0.7
    worlds = sample_grip_worlds(3, seed=7)
    rows = [run_grip_world(200.0, 66.0, torque, 0.8, world, Fingers()) for world in worlds]
    assert all(row["pass"] for row in rows)
    assert rows[0]["trajectory"][-1][0] == pytest.approx(3.18, abs=0.03)
    weak = run_grip_world(400.0, 40.0, 1.8 * 9.80665 / 100 * 0.7, 0.8, worlds[0], Fingers())
    assert not weak["pass"] and weak["reason"] == "dropped"


def test_run_grip_reports_the_whole_timeline():
    outcome = run_grip(200.0, 66.0, 9.4 * 9.80665 / 100 * 0.7, 0.8)
    assert outcome["result"] == "pass" and outcome["failed_at"] is None
    assert outcome["trajectory"][-1][0] == pytest.approx(3.98, abs=0.03)
    assert outcome["hand"][-1][1] == pytest.approx(0.15, abs=0.002)
