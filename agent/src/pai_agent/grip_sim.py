"""MuJoCo grip test for the two-finger gripper.

Two pads squeeze the object with the finger force the servo can hold. The hand then
lifts it 15 cm, holds, and shakes it up and down (about 0.4 g extra), the way a robot
arm moves a part. Friction alone keeps the object in the hand. It passes when the
object stays within 10 mm of where the hand holds it.
"""

from __future__ import annotations

import math

_DT = 0.001
_SQUEEZE = 0.4
_LIFT = (0.4, 1.4)
_SHAKE = (2.0, 2.8)
_DURATION = 3.2
_LIFT_M = 0.15
_SHAKE_M = 0.015
_SHAKE_HZ = 2.5
_SLIP_LIMIT_M = 0.010


def _hand_z(t: float) -> float:
    if t < _LIFT[0]:
        return 0.0
    if t < _LIFT[1]:
        u = (t - _LIFT[0]) / (_LIFT[1] - _LIFT[0])
        return _LIFT_M * (1 - math.cos(math.pi * u)) / 2
    if _SHAKE[0] <= t < _SHAKE[1]:
        return _LIFT_M + _SHAKE_M * math.sin(2 * math.pi * _SHAKE_HZ * (t - _SHAKE[0]))
    return _LIFT_M


def _model(mass_kg: float, width_m: float, friction: float) -> str:
    half_w = width_m / 2
    return f"""
<mujoco model="grip">
  <option timestep="{_DT}" gravity="0 0 -9.80665" cone="elliptic" impratio="10" noslip_iterations="4"/>
  <worldbody>
    <geom name="floor" type="plane" size="1 1 0.1" friction="0.5 0.005 0.0001"/>
    <body name="object" pos="0 0 0.06">
      <freejoint/>
      <geom name="object" type="box" size="{half_w} 0.025 0.06" mass="{mass_kg}" friction="{friction} 0.005 0.0001"/>
    </body>
    <body name="hand" pos="0 0 0.08" gravcomp="1">
      <joint name="lift" type="slide" axis="0 0 1" damping="40"/>
      <geom type="box" size="{half_w + 0.03} 0.03 0.004" pos="0 0 0.05" mass="0.3" contype="0" conaffinity="0" rgba="0.8 0.8 0.85 1"/>
      <body name="pad_l" pos="{-half_w - 0.004} 0 0" gravcomp="1">
        <joint name="pad_l" type="slide" axis="1 0 0" range="-0.03 0.03" damping="2"/>
        <geom type="box" size="0.003 0.015 0.02" mass="0.01" friction="{friction} 0.005 0.0001"/>
      </body>
      <body name="pad_r" pos="{half_w + 0.004} 0 0" gravcomp="1">
        <joint name="pad_r" type="slide" axis="1 0 0" range="-0.03 0.03" damping="2"/>
        <geom type="box" size="0.003 0.015 0.02" mass="0.01" friction="{friction} 0.005 0.0001"/>
      </body>
    </body>
  </worldbody>
  <actuator>
    <motor joint="pad_l" gear="1" ctrlrange="0 1000"/>
    <motor joint="pad_r" gear="-1" ctrlrange="0 1000"/>
    <position joint="lift" kp="20000" ctrlrange="-1 1"/>
  </actuator>
</mujoco>
"""


def run_grip(payload_g: float, width_mm: float, pad_force_n: float, friction: float) -> dict:
    import mujoco

    model = mujoco.MjModel.from_xml_string(_model(payload_g / 1000.0, width_mm / 1000.0, friction))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    obj = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "object")
    base_hand = 0.08
    hand_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "hand")
    obj_z0 = float(data.xpos[obj][2])
    trajectory: list[list[float]] = []
    hand: list[list[float]] = []
    max_slip = 0.0
    steps = int(_DURATION / _DT)
    for step in range(steps):
        t = step * _DT
        squeeze = min(1.0, t / 0.2) * pad_force_n
        data.ctrl[0] = squeeze
        data.ctrl[1] = squeeze
        data.ctrl[2] = _hand_z(t)
        mujoco.mj_step(model, data)
        lifted = float(data.xpos[hand_id][2]) - base_hand
        obj_rise = float(data.xpos[obj][2]) - obj_z0
        if t >= _LIFT[0]:
            max_slip = max(max_slip, lifted - obj_rise)
        if step % 20 == 0:
            trajectory.append([round(t, 3), 0.0, 0.0, round(obj_rise, 4)])
            hand.append([round(t, 3), round(lifted, 4)])
    final_slip = (float(data.xpos[hand_id][2]) - base_hand) - (float(data.xpos[obj][2]) - obj_z0)
    finite = all(math.isfinite(v) for row in trajectory for v in row)
    dropped = final_slip > 0.05
    passed = finite and not dropped and max_slip <= _SLIP_LIMIT_M
    return {
        "result": "pass" if passed else "fail",
        "slip_mm": round(max(0.0, max_slip) * 1000, 1),
        "final_slip_mm": round(max(0.0, final_slip) * 1000, 1),
        "dropped": dropped,
        "trajectory": trajectory,
        "hand": hand,
    }


if __name__ == "__main__":
    import sys

    print({k: v for k, v in run_grip(*map(float, sys.argv[1:5])).items() if k not in ("trajectory", "hand")})
