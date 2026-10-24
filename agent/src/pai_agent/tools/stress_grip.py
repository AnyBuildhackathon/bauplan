"""Stress test for the gripper: the grip test from grip_sim in 50 randomized worlds.

Each world draws its own payload mass (+-15 %), servo strength (-25..0 %), pad
friction (-40..+10 %, dusty, oily or worn pads), how hard the arm shakes (1-2x
the nominal 1.5 cm; the 2.5 Hz stays, so the shake still ends on a full cycle), and noise on the squeeze force (slow servo
jitter up to 15 %). A world is survived when the object never lags the hand by more than
10 mm, the same line as the single grip test.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from pai_agent.grip_sim import _DT, _DURATION, _LIFT, _LIFT_M, _SHAKE, _SHAKE_HZ, _SHAKE_M, _SLIP_LIMIT_M, _model

_SAMPLE_EVERY = 20
_JITTER_S = 0.05


@dataclass(frozen=True)
class GripWorld:
    i: int
    mass_scale: float
    servo_scale: float
    friction_scale: float
    shake_scale: float
    noise: float


def sample_grip_worlds(n: int, seed: int) -> list[GripWorld]:
    rng = random.Random(seed)
    return [
        GripWorld(
            i=i + 1,
            mass_scale=rng.uniform(0.85, 1.15),
            servo_scale=rng.uniform(0.75, 1.0),
            friction_scale=rng.uniform(0.6, 1.1),
            shake_scale=rng.uniform(1.0, 2.0),
            noise=rng.uniform(0.0, 0.15),
        )
        for i in range(n)
    ]


def _hand_z(t: float, world: GripWorld) -> float:
    if t < _LIFT[0]:
        return 0.0
    if t < _LIFT[1]:
        u = (t - _LIFT[0]) / (_LIFT[1] - _LIFT[0])
        return _LIFT_M * (1 - math.cos(math.pi * u)) / 2
    if _SHAKE[0] <= t < _SHAKE[1]:
        return _LIFT_M + _SHAKE_M * world.shake_scale * math.sin(2 * math.pi * _SHAKE_HZ * (t - _SHAKE[0]))
    return _LIFT_M


def run_grip_world(payload_g: float, width_mm: float, force_n: float, friction: float, world: GripWorld) -> dict:
    import mujoco

    model = mujoco.MjModel.from_xml_string(
        _model(payload_g * world.mass_scale / 1000.0, width_mm / 1000.0, friction * world.friction_scale)
    )
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    obj = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "object")
    hand_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "hand")
    base_hand = float(data.xpos[hand_id][2])
    obj_z0 = float(data.xpos[obj][2])
    rng = random.Random(world.i * 7919)
    squeeze_n = force_n * world.servo_scale
    trajectory: list[list[float]] = []
    hand: list[list[float]] = []
    max_slip = 0.0
    jitter = 0.0
    # Servo jitter is slow: first-order filtered noise with a 50 ms time constant.
    blend = _DT / _JITTER_S
    for step in range(int(_DURATION / _DT)):
        t = step * _DT
        jitter += blend * (rng.gauss(0, world.noise) * math.sqrt(2 / blend) - jitter)
        squeeze = min(1.0, t / 0.2) * squeeze_n * max(0.0, 1 + jitter)
        data.ctrl[0] = squeeze
        data.ctrl[1] = squeeze
        data.ctrl[2] = _hand_z(t, world)
        mujoco.mj_step(model, data)
        lifted = float(data.xpos[hand_id][2]) - base_hand
        rise = float(data.xpos[obj][2]) - obj_z0
        if t >= _LIFT[0]:
            max_slip = max(max_slip, lifted - rise)
        if step % _SAMPLE_EVERY == 0:
            trajectory.append([round(t, 3), 0.0, 0.0, round(rise, 4)])
            hand.append([round(t, 3), round(lifted, 4)])
    final_slip = (float(data.xpos[hand_id][2]) - base_hand) - (float(data.xpos[obj][2]) - obj_z0)
    finite = all(math.isfinite(v) for row in trajectory for v in row)
    if not finite or final_slip > 0.05:
        reason = "dropped"
    elif max_slip > _SLIP_LIMIT_M:
        reason = "slipped"
    else:
        reason = ""
    margin = 1 - max(0.0, max_slip) / _SLIP_LIMIT_M if finite else -1.0
    return {
        "pass": not reason,
        "reason": reason,
        "slip_mm": round(max(0.0, max_slip) * 1000, 1),
        "margin": round(max(-1.0, margin), 3),
        "trajectory": trajectory,
        "hand": hand,
    }


def grip_row(world: GripWorld, outcome: dict) -> dict:
    return {
        "i": world.i,
        "pass": outcome["pass"],
        "reason": outcome["reason"],
        "mass_pct": round((world.mass_scale - 1) * 100, 1),
        "motor_pct": round((world.servo_scale - 1) * 100, 1),
        "friction_pct": round((world.friction_scale - 1) * 100, 1),
        "shake_x": round(world.shake_scale, 2),
        "noise_pct": round(world.noise * 100, 1),
        "slip_mm": outcome["slip_mm"],
        "margin": outcome["margin"],
    }


# How hard each randomized factor pushed a world, 0 (mild) to 1 (the worst draw).
_SEVERITY = {
    "friction": lambda r: (10 - r["friction_pct"]) / 50.0,
    "motor": lambda r: -r["motor_pct"] / 25.0,
    "mass": lambda r: (r["mass_pct"] + 15) / 30.0,
    "shake": lambda r: r["shake_x"] - 1.0,
    "noise": lambda r: r["noise_pct"] / 15.0,
}


def grip_weakest(rows: list[dict]) -> tuple[str | None, str]:
    lost = [r for r in rows if not r["pass"]]
    if not rows:
        return None, "No worlds were run."
    if not lost:
        closest = min(rows, key=lambda r: r["margin"])
        return None, (
            f"It held on in all {len(rows)} worlds; the closest call was pads {abs(closest['friction_pct']):.0f} % "
            f"{'slicker' if closest['friction_pct'] < 0 else 'grippier'} with a {closest['shake_x']:.1f}x shake, "
            f"where the object slipped {closest['slip_mm']:.1f} mm."
        )
    kept = [r for r in rows if r["pass"]] or rows

    def mean(group: list[dict], key: str) -> float:
        return sum(_SEVERITY[key](r) for r in group) / len(group)

    key = max(_SEVERITY, key=lambda k: mean(lost, k) - mean(kept, k))
    worst = min(lost, key=lambda r: r["margin"])
    if key == "friction":
        sentence = (
            f"Pad friction is the weak point: with pads {abs(worst['friction_pct']):.0f} % slicker the object slides "
            f"{worst['slip_mm']:.0f} mm, so softer, grippier pads or more squeeze would fix it."
        )
    elif key == "motor":
        sentence = (
            f"Servo strength is the weak point: a servo {abs(worst['motor_pct']):.0f} % weaker than its datasheet "
            f"cannot squeeze hard enough to hold through the shake."
        )
    elif key == "mass":
        sentence = f"Payload is the weak point: {worst['mass_pct']:+.0f} % heavier objects slip out of the same squeeze."
    elif key == "shake":
        sentence = (
            f"Arm jerk is the weak point: a {worst['shake_x']:.1f}x harder shake throws the object "
            f"{worst['slip_mm']:.0f} mm out of the pads."
        )
    else:
        sentence = f"Servo jitter is the weak point: at {worst['noise_pct']:.0f} % force noise the grip loosens for a moment and the object slips."
    return key, sentence
