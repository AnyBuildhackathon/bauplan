"""MuJoCo grip test for the two-finger gripper, with the fingers the CAD template builds.

The template (agent/freecad/library/gripper.py) hangs each finger on a gear: the servo turns
the left gear, the right one meshes with it, and both fingers swing shut on the gear axes.
Swinging, the pads tilt, so they meet the object with their tips, not their middles. Here
each finger is a hinge on its gear axis, the two are coupled like the gears, the servo's
holding torque drives the left one, and the pads and finger bars are boxes with the
template's dimensions.

The object is a cube as wide as the brief says. The pad tips close on it at half its
height, or higher on a cube taller than the pads are long, so that it stays clear of the
finger bars above the pads. The hand lifts it 15 cm, holds, and shakes it up and down (about 0.4 g extra), the
way a robot arm moves a part. A real arm starts and stops harder than this shake, so last
the object is pulled down with its weight once more: the hand has to hold twice its weight.
Friction alone keeps the object in the hand. It passes when the object stays within 10 mm
of where the hand holds it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_DT = 0.001
_SQUEEZE = 0.4
_LIFT = (0.4, 1.4)
_SHAKE = (2.0, 2.8)
_SHAKEN = 3.2
_PULL = (3.2, 3.5)
_DURATION = 4.0
_LIFT_M = 0.15
_SHAKE_M = 0.015
_SHAKE_HZ = 2.5
_SLIP_LIMIT_M = 0.010
_SAMPLE_EVERY = 20

# The template's fixed sizes in mm: gear pitch radius (module 1.5, 16 teeth) and finger width.
GEAR_RADIUS_MM = 12.0
FINGER_WIDTH_MM = 9.0
# The pads cover the outer 45 % of each finger, the knee sits at 35 %.
_PAD_FROM = 0.55
_KNEE = 0.35


@dataclass(frozen=True)
class Fingers:
    """The template's finger parameters in mm, with its defaults."""

    length_mm: float = 70.0
    opening_mm: float = 76.0
    thickness_mm: float = 6.0
    pad_mm: float = 3.0

    @classmethod
    def from_params(cls, params: dict) -> Fingers:
        return cls(
            float(params.get("finger_length_mm", cls.length_mm)),
            float(params.get("jaw_opening_mm", cls.opening_mm)),
            float(params.get("finger_thickness_mm", cls.thickness_mm)),
            float(params.get("pad_thickness_mm", cls.pad_mm)),
        )


@dataclass(frozen=True)
class Contact:
    """Where a pad meets the object, measured from its gear axis."""

    angle_rad: float  # how far each finger swings shut from the open CAD pose
    lever_mm: float  # along the finger to the pad tip: the arm of the squeeze
    offset_mm: float  # across to the object's face: the arm of the friction


def contact(fingers: Fingers, width_mm: float) -> Contact | None:
    """The pad tip on an object `width_mm` wide; None when it does not fit between the open pads."""

    if not 0 < width_mm < fingers.opening_mm:
        return None
    face = fingers.opening_mm / 2 - GEAR_RADIUS_MM
    offset = width_mm / 2 - GEAR_RADIUS_MM
    angle = math.acos(offset / math.hypot(face, fingers.length_mm)) - math.atan2(fingers.length_mm, face)
    return Contact(angle, face * math.sin(angle) + fingers.length_mm * math.cos(angle), offset)


def squeeze_n(torque_nm: float, tip: Contact) -> float:
    """Each finger gets half the servo torque and presses with it on the pad tip."""

    return torque_nm / 2 / (tip.lever_mm / 1000.0)


def hold_n(torque_nm: float, friction: float, tip: Contact) -> float:
    """The weight friction carries before the object slides.

    About the gear axis, torque / 2 + offset * F = lever * N for each finger, where F is the
    friction the object's weight drags the pad down with. The pad tip sits outside the axis,
    so that drag swings the fingers further shut, like ice tongs. Sliding starts at
    F = mu * N on both pads: hold = mu * torque / (lever - mu * offset). Close to a wedge
    the flex of the printed fingers decides, so it counts at most four times what the
    squeeze alone holds.
    """

    arm = max(tip.lever_mm - friction * tip.offset_mm, tip.lever_mm / 4) / 1000.0
    return friction * torque_nm / arm


def _bar(a: tuple[float, float], b: tuple[float, float], width: float, thickness: float, friction: float) -> str:
    """A box from a to b in the finger's plane, mm from the gear axis with y down the finger."""

    length = math.hypot(b[0] - a[0], b[1] - a[1])
    return (
        f'<geom type="box" size="{length / 2000:.6f} {thickness / 2000:.6f} {width / 2000:.6f}" '
        f'pos="{(a[0] + b[0]) / 2000:.6f} 0 {-(a[1] + b[1]) / 2000:.6f}" euler="0 {math.atan2(b[1] - a[1], b[0] - a[0]):.6f} 0" '
        f'density="1240" friction="{friction} 0.005 0.0001" contype="2" conaffinity="0"/>'
    )


def _finger(side: int, fingers: Fingers, friction: float) -> str:
    name = "l" if side < 0 else "r"
    length, thickness, pad = fingers.length_mm, fingers.thickness_mm, fingers.pad_mm
    face = fingers.opening_mm / 2 - GEAR_RADIUS_MM
    bar_x = side * (face + pad + FINGER_WIDTH_MM / 2)
    pad_x = side * (face + pad / 2)
    geoms = (
        _bar((0.0, 0.0), (bar_x, _KNEE * length), FINGER_WIDTH_MM, thickness, friction),
        _bar((bar_x, _KNEE * length), (bar_x, length), FINGER_WIDTH_MM, thickness, friction),
        _bar((pad_x, _PAD_FROM * length), (pad_x, length), pad, thickness, friction),
    )
    # Both joints count positive when the finger swings shut.
    return (
        f'<body name="finger_{name}" pos="{side * GEAR_RADIUS_MM / 1000:.6f} 0 0" gravcomp="1">'
        f'<joint name="finger_{name}" type="hinge" axis="0 {side} 0" range="0 1.4" damping="0.01" armature="0.001"/>'
        + "".join(geoms)
        + "</body>"
    )


def grasp_height_mm(fingers: Fingers, width_mm: float, tip: Contact) -> float:
    """How high on the cube the pad tips close: half way up, or so its top stays below the pads."""

    pads = (1 - _PAD_FROM) * fingers.length_mm * math.cos(tip.angle_rad)
    return max(width_mm / 2, width_mm - pads)


def _model(mass_kg: float, width_mm: float, friction: float, fingers: Fingers, tip: Contact) -> str:
    half = width_mm / 2000
    hand_z = (grasp_height_mm(fingers, width_mm, tip) + tip.lever_mm) / 1000
    return f"""
<mujoco model="grip">
  <compiler angle="radian"/>
  <option timestep="{_DT}" gravity="0 0 -9.80665" cone="elliptic" impratio="10" noslip_iterations="4"/>
  <worldbody>
    <geom name="floor" type="plane" size="1 1 0.1" friction="0.5 0.005 0.0001"/>
    <body name="object" pos="0 0 {half:.6f}">
      <freejoint/>
      <geom name="object" type="box" size="{half:.6f} {half:.6f} {half:.6f}" mass="{mass_kg}" friction="{friction} 0.005 0.0001" conaffinity="3"/>
    </body>
    <body name="hand" pos="0 0 {hand_z:.6f}" gravcomp="1">
      <joint name="lift" type="slide" axis="0 0 1" damping="40"/>
      <geom type="box" size="{fingers.opening_mm / 2000 + 0.02:.6f} 0.025 0.004" pos="0 0 0.006" mass="0.3" contype="0" conaffinity="0"/>
      {_finger(-1, fingers, friction)}
      {_finger(1, fingers, friction)}
    </body>
  </worldbody>
  <equality>
    <joint joint1="finger_r" joint2="finger_l" polycoef="0 1 0 0 0" solref="0.002 1"/>
  </equality>
  <actuator>
    <motor name="servo" joint="finger_l" ctrlrange="0 100"/>
    <position name="lift" joint="lift" kp="20000" ctrlrange="-1 1"/>
  </actuator>
</mujoco>
"""


def _hand_z(t: float, shake_m: float = _SHAKE_M) -> float:
    if t < _LIFT[0]:
        return 0.0
    if t < _LIFT[1]:
        u = (t - _LIFT[0]) / (_LIFT[1] - _LIFT[0])
        return _LIFT_M * (1 - math.cos(math.pi * u)) / 2
    if _SHAKE[0] <= t < _SHAKE[1]:
        return _LIFT_M + shake_m * math.sin(2 * math.pi * _SHAKE_HZ * (t - _SHAKE[0]))
    return _LIFT_M


class Rig:
    """The gripper on its lift with the object between the open pads."""

    def __init__(self, payload_g: float, width_mm: float, friction: float, fingers: Fingers, tip: Contact):
        import mujoco

        self._mj = mujoco
        self.model = mujoco.MjModel.from_xml_string(_model(payload_g / 1000.0, width_mm, friction, fingers, tip))
        self.data = mujoco.MjData(self.model)
        mujoco.mj_forward(self.model, self.data)
        self.weight_n = payload_g / 1000.0 * 9.80665
        self._object = self.model.body("object").id
        self._hand = self.model.body("hand").id
        self._fingers = {self.model.body(name).id for name in ("finger_l", "finger_r")}
        self._hand_z0 = float(self.data.xpos[self._hand][2])
        self._object_z0 = float(self.data.xpos[self._object][2])

    def step(self, torque_nm: float, hand_z: float, pull_n: float = 0.0) -> None:
        self.data.ctrl[0] = torque_nm
        self.data.ctrl[1] = hand_z
        self.data.xfrc_applied[self._object][2] = -pull_n
        self._mj.mj_step(self.model, self.data)

    def lifted(self) -> float:
        return float(self.data.xpos[self._hand][2]) - self._hand_z0

    def rise(self) -> float:
        return float(self.data.xpos[self._object][2]) - self._object_z0

    def squeeze_n(self) -> float:
        """The mean normal force of the two fingers on the object right now."""

        import numpy as np

        force = np.zeros(6)
        total = 0.0
        for i in range(self.data.ncon):
            pair = self.data.contact[i]
            bodies = {int(self.model.geom_bodyid[pair.geom1]), int(self.model.geom_bodyid[pair.geom2])}
            if self._object in bodies and bodies & self._fingers:
                self._mj.mj_contactForce(self.model, self.data, i, force)
                total += float(force[0])
        return total / 2


def run_grip(payload_g: float, width_mm: float, torque_nm: float, friction: float, fingers: Fingers = Fingers(), proof: float = 2.0) -> dict:
    """The grip test with the servo's holding torque on the left gear; the last pull loads `proof` times the weight.

    `failed_at` names the first phase the object did not hold in: fit (wider than the open
    jaws, not simulated), lift (it slid out), shake or pull (it slipped over 10 mm).
    """

    tip = contact(fingers, width_mm)
    if tip is None:
        return {"result": "fail", "failed_at": "fit", "slip_mm": 0.0, "final_slip_mm": 0.0, "dropped": False, "squeeze_n": 0.0, "trajectory": [], "hand": []}
    rig = Rig(payload_g, width_mm, friction, fingers, tip)
    trajectory: list[list[float]] = []
    hand: list[list[float]] = []
    max_slip = 0.0
    pull_slip = 0.0
    squeeze = 0.0
    dropped = False
    for step in range(int(_DURATION / _DT)):
        t = step * _DT
        pull = (proof - 1) * rig.weight_n * min(1.0, max(0.0, (t - _PULL[0]) / (_PULL[1] - _PULL[0])))
        rig.step(min(1.0, t / 0.2) * torque_nm, _hand_z(t), pull)
        lag = rig.lifted() - rig.rise()
        if step == int(_SQUEEZE / _DT):
            squeeze = rig.squeeze_n()
        if step == int(_SHAKEN / _DT):
            dropped = lag > 0.05
        if t >= _SHAKEN:
            pull_slip = max(pull_slip, lag)
        elif t >= _LIFT[0]:
            max_slip = max(max_slip, lag)
        if step % _SAMPLE_EVERY == 0:
            trajectory.append([round(t, 3), 0.0, 0.0, round(rig.rise(), 4)])
            hand.append([round(t, 3), round(rig.lifted(), 4)])
    final_slip = rig.lifted() - rig.rise()
    finite = all(math.isfinite(v) for row in trajectory for v in row)
    if not finite or dropped:
        failed_at = "lift"
    elif max_slip > _SLIP_LIMIT_M:
        failed_at = "shake"
    elif pull_slip > _SLIP_LIMIT_M:
        failed_at = "pull"
    else:
        failed_at = None
    return {
        "result": "fail" if failed_at else "pass",
        "failed_at": failed_at,
        "slip_mm": round(max(0.0, max_slip) * 1000, 1),
        "final_slip_mm": round(max(0.0, final_slip) * 1000, 1),
        "dropped": dropped or not finite,
        "squeeze_n": round(squeeze, 2),
        "trajectory": trajectory,
        "hand": hand,
    }


if __name__ == "__main__":
    import sys

    print({k: v for k, v in run_grip(*map(float, sys.argv[1:5])).items() if k not in ("trajectory", "hand")})
