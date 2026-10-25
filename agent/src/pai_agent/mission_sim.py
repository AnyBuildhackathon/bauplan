"""Mission tests in MuJoCo: the drone built from its chosen parts flies a speed run, a hard turn,
a position hold in wind and a chase of a dodging target.

The airframe (`airframe`) comes from the parts, nothing is a fixed constant of one build:

- Mass and inertia: every part is a MuJoCo geom with its catalog mass at its place in the
  assembly (`drone_geometry.geometry`): motors on the arm tips, propellers as discs on the
  motors, the pack under the plate, the board on its standoffs, the frame as a hub and four
  arms. MuJoCo sums them into the body's mass, centre of mass and full inertia matrix, so the
  sim weighs exactly what physics_calc and the bill of materials list.
- Thrust: the power train in `plant.py`. Each motor's static thrust is its maker's 100 % load-table
  row, and with the air coming through the disc it follows the measured thrust and power
  coefficients of the nearest documented propeller (UIUC database) while the motor, a DC motor
  fitted to the same row, spins up as the prop unloads. The pack's voltage sags with the current
  actually drawn (internal resistance from its C rating and capacity) and drains over the mission,
  and the full-throttle thrust follows the sagging voltage. Near the floor the thrust gains the
  Cheeseman-Bennett ground effect.
- Motor response: a first-order lag of 15 ms for a 51 mm propeller, growing in proportion to the
  diameter, 10 to 120 ms. That puts a 5.1 inch prop at 39 ms, the time constant measured on a
  thrust stand for the Agilicious 5-inch racer (Foehn et al., Science Robotics 2022: 39.1 ms).
- Yaw: each propeller's drag torque is 0.012 m per newton of thrust per 51 mm of diameter;
  props spin as in `freecad/frame_build.py`.
- Drag: the body's flat-plate drag, 0.5 rho Cd A v^2 with Cd 1.0 sideways and 1.2 through the
  disc plane, A from the parts' own outlines (pack, board, motors, arms, camera); plus rotor
  drag (blade flapping, the H force): each rotor pushes back against the in-plane air speed with
  its thrust times the air speed over its tip speed. Air density 1.225 kg/m^3.
- Chase sensing: the drone sees each fly only through its camera (`plant.camera_spec`): the
  camera's field of view, uptilt, 720 x 480 pixels and frame rate; a 6 mm fly is detected while it
  covers 2 pixels and is inside the view. Each fix arrives late by the camera's latency, one frame
  and the detector's pass, with half a pixel of noise in bearing and in apparent size (so in
  range), into a constant-velocity Kalman filter that predicts across the delay. A track coasts
  0.5 s without a fix; then the drone stops and turns on the spot to search. It starts with the
  fly's first position pointed out to it, no velocity.
- Not modelled: prop wash between rotors, the vortex ring state, motor heating, the drone's own
  sensor noise (it knows its own position and attitude exactly).

The reference flight controller is the same for every build: a geometric attitude controller whose
bandwidth follows the motor lag (0.8 / lag, at most 28 rad/s: half the 1.6 / lag where a PD loop
on a lagging motor goes unstable, a gain margin of 2), mixing with attitude priority, thrust tilt
limited to 70 degrees, and per-mission outer loops on position or velocity. Flown with it, a build
only differs by its parts, so a heavier or weaker build measurably loses speed, turns slower or
misses the chase: the hardware check.

A mission can instead fly a gain set (`gains`), the seven gains the trainer and the firmware use
(`GAIN_KEYS`, see `Controller`), so the trained controller is judged on the same missions.

All missions are deterministic: fixed start, fixed seed for the target's dodges and the wind.
"""

from __future__ import annotations

import math
import random

import numpy as np

from pai_agent.plant import Plant, camera_spec, ground_effect

GRAVITY = 9.80665
RHO = 1.225
DT = 0.002
SAMPLE_S = 0.02
START_Z = 1.5
TILT_MAX = math.radians(70.0)

MISSIONS = {
    "speed_run": {"label": "Speed run", "requirement": "top_speed", "key": "top_speed_kmh", "unit": "km/h", "kind": "min"},
    "turn": {"label": "Hard turn", "requirement": "turn_rate", "key": "turn_rate_dps", "unit": "°/s", "kind": "min"},
    "hold": {"label": "Position hold", "requirement": "hold_error", "key": "hold_error_cm", "unit": "cm", "kind": "max"},
    "chase": {"label": "Chase", "requirement": "chase_time", "key": "capture_s", "unit": "s", "kind": "max"},
}

TURN_SPEED = 8.0
TARGET_SPEED = 2.5
CAPTURE_M = 0.12
CLOSING_MS = 3.0
CHASE_S = 8.0
CHASE_FLIES = 5


# The trained controller's gains, as web/src/sim/drone.ts exports them and stress.ControllerGains reads them.
GAIN_KEYS = ("kp_z", "ki_z", "kd_z", "kp_xy", "kd_xy", "kp_att", "kd_att")


class AirframeError(ValueError):
    pass


def motor_lag_s(diameter_mm: float) -> float:
    """The motor's first-order time constant for this propeller diameter."""

    return min(0.12, max(0.01, 0.015 * diameter_mm / 51.0))


def _num(part: dict | None, key: str) -> float | None:
    try:
        value = float((part or {})[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def airframe(geo: dict, selected: dict) -> dict:
    """The flying model of the build: geoms with masses, per-motor thrust, lag, drag areas."""

    motor = selected.get("motor") or {}
    prop = selected.get("propeller") or {}
    battery = selected.get("battery") or {}
    thrust_g = _num(motor, "thrust_g")
    if thrust_g is None:
        raise AirframeError("The motor has no thrust figure (thrust_g).")
    qty = int(motor.get("bom_qty") or 4)
    if qty != 4:
        raise AirframeError("Mission tests fly quadcopters; the motor count is " + str(qty) + ".")
    if not geo["masses"]:
        raise AirframeError("No parts chosen yet.")
    diameter = float(geo["propeller"]["diameter_mm"])
    plant = Plant(motor, dict(prop, diameter_mm=diameter), battery, qty)
    fresh = plant.full_throttle(1.0)
    scale = diameter / 51.0
    pack = geo["battery"]["size_mm"]
    bell = geo["motor"]["bell_diameter_mm"]
    motor_h = geo["motor"]["height_mm"]
    board = geo["flight_controller"]["board_mm"]
    arm = geo["arm_length_mm"]
    t = geo["thickness_mm"]
    mm2 = 1e-6
    # Sideways: the pack's mean side, the board edge-on, two motors' worth of bells, the arms in
    # section and the camera; through the disc plane: the pack, the board, bells and arms from above.
    side = (pack[2] * (pack[0] + pack[1]) / 2 + board * 6.0 + 2 * bell * motor_h + 2 * arm * t * 1.4 + 14.0 * 14.0) * mm2
    top = (pack[0] * pack[1] + board * board + 4 * math.pi * bell * bell / 4 + 4 * arm * 8.2) * mm2
    com = geo["com_mm"]
    rotors = []
    for corner in geo["corners"]:
        rotors.append(
            {
                "name": corner["name"],
                "r": np.array([corner["x_mm"] - com[0], corner["y_mm"] - com[1], geo["propeller"]["z_mm"] - com[2]]) / 1000.0,
                "spin": corner["spin"],
            }
        )
    return {
        "geo": geo,
        "rotors": rotors,
        # Full-throttle static thrust per motor on the fresh pack, sagged under that load.
        "t0": fresh["thrust_n"],
        "plant": plant,
        "camera": camera_spec(selected.get("camera")),
        "rotor_radius": diameter / 2000.0,
        # The airspeed through the disc where full throttle makes no thrust any more.
        "pitch_speed": plant.zero_thrust_speed(1.0),
        "tip_speed": plant.tip_speed(1.0),
        "tau": motor_lag_s(diameter),
        "kq": 0.012 * scale,
        "cda_side": 1.0 * side,
        "cda_top": 1.2 * top,
        "parts": {k: (selected.get(k) or {}).get("id") for k in ("motor", "propeller", "battery", "flight_controller", "frame")},
    }


def _model_xml(geo: dict) -> str:
    com = geo["com_mm"]
    geoms = []
    for index, m in enumerate(geo["masses"]):
        x, y, z = ((m["pos_mm"][i] - com[i]) / 1000.0 for i in range(3))
        size = [v / 1000.0 for v in m["size_mm"]]
        if m["shape"] in {"cylinder", "disc"}:
            spec = f'type="cylinder" size="{max(size[0] / 2, 1e-4):.5f} {max(size[1] / 2, 1e-4):.5f}"'
        else:
            spec = f'type="box" size="{max(size[0] / 2, 1e-4):.5f} {max(size[1] / 2, 1e-4):.5f} {max(size[2] / 2, 1e-4):.5f}"'
        geoms.append(f'<geom name="g{index}" {spec} pos="{x:.5f} {y:.5f} {z:.5f}" mass="{m["mass_g"] / 1000.0:.6f}" contype="0" conaffinity="0"/>')
    return f"""
<mujoco model="mission">
  <compiler inertiafromgeom="true"/>
  <option timestep="{DT}" gravity="0 0 -{GRAVITY}" integrator="RK4"/>
  <worldbody>
    <body name="drone" pos="0 0 {START_Z}">
      <freejoint name="root"/>
      {"".join(geoms)}
    </body>
  </worldbody>
</mujoco>
"""


def _vee(m: np.ndarray) -> np.ndarray:
    return np.array([m[2, 1], m[0, 2], m[1, 0]])


def _cross(a, b) -> np.ndarray:
    """a x b for two 3-vectors, as np.cross computes it, without its per-call overhead."""

    return np.array([a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]])


def gain_set(raw: dict | None) -> dict[str, float] | None:
    """The seven gains from a training result, as floats; None when any is missing, negative or not a number."""

    if not isinstance(raw, dict):
        return None
    out = {}
    for key in GAIN_KEYS:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            return None
        out[key] = float(value)
    return out


class Controller:
    """The flight controller of one flight: the reference (no gains) or a gain set.

    The gains are in the training module's exported units: height and position in 1/s^2, 1/s^3
    and 1/s, attitude in N m/rad and N m s/rad, divided here by the build's own roll and pitch
    inertia. Yaw keeps the reference loop, as no trained gain covers it. With gains every outer
    loop is one cascaded PID, a = kp (p_ref - p) + ki (integral) + kd (v_ref - v); a mission that
    commands a velocity (the dash, the turn, the chase) goes through kd alone, the velocity loop
    of that cascade.
    """

    def __init__(self, gains: dict | None = None) -> None:
        if gains is None:
            self.gains = None
        else:
            self.gains = gain_set(gains)
            if self.gains is None:
                raise AirframeError("A gain set needs " + ", ".join(GAIN_KEYS) + " as numbers of at least 0.")
        self.name = "reference" if self.gains is None else "trained"
        self.z_int = 0.0
        self.p_int = np.zeros(3)
        self.v_int = np.zeros(2)

    def rates(self, inertia: np.ndarray, tau: float) -> tuple[np.ndarray, np.ndarray]:
        """Attitude stiffness and damping per body axis, in 1/s^2 and 1/s."""

        # tau * k_r < k_w keeps the loop stable on a lagging motor (omega < 1.6 / tau); half of that.
        omega = min(28.0, 0.8 / tau)
        k_r = np.full(3, omega * omega)
        k_w = np.full(3, 1.6 * omega)
        if self.gains:
            axes = np.diag(inertia)[:2]
            k_r[:2] = self.gains["kp_att"] / axes
            k_w[:2] = self.gains["kd_att"] / axes
        return k_r, k_w

    def altitude(self, z: float, pos: np.ndarray, vel: np.ndarray) -> float:
        error = z - float(pos[2])
        if self.gains is None:
            self.z_int = float(np.clip(self.z_int + error * DT, -2.0, 2.0))
            return 6.0 * error - 4.5 * float(vel[2]) + 2.0 * self.z_int
        g = self.gains
        # Clamped so the integral cannot wind up past half the weight, as in the browser trainer.
        cap = 0.5 * GRAVITY / max(g["ki_z"], 1e-6)
        self.z_int = float(np.clip(self.z_int + error * DT, -cap, cap))
        return g["kp_z"] * error - g["kd_z"] * float(vel[2]) + g["ki_z"] * self.z_int

    def hold(self, target: np.ndarray, pos: np.ndarray, vel: np.ndarray) -> np.ndarray:
        """Hold a point: the reference PID on all three axes, else position PD and the height PID."""

        error = target - pos
        if self.gains is None:
            self.p_int = np.clip(self.p_int + error * DT, -2.0, 2.0)
            return 5.0 * error + 3.6 * (np.zeros(3) - vel) + 2.0 * self.p_int
        g = self.gains
        xy = g["kp_xy"] * error[:2] - g["kd_xy"] * vel[:2]
        return np.array([xy[0], xy[1], self.altitude(float(target[2]), pos, vel)])

    def lateral(self, error: float, v: float) -> float:
        """Hold a line sideways (the speed run's y)."""

        if self.gains is None:
            return 3.0 * error - 2.0 * v
        return self.gains["kp_xy"] * error - self.gains["kd_xy"] * v

    def dash(self, v_target: float, v: float) -> float:
        """Accelerate along a line toward a speed it never reaches (the speed run)."""

        return (3.0 if self.gains is None else self.gains["kd_xy"]) * (v_target - v)

    def track(self, v_target: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Fly a horizontal velocity (the turn before and after it pulls)."""

        if self.gains is None:
            self.v_int = np.clip(self.v_int + (v_target - v) * DT, -3.0, 3.0)
            return 4.0 * (v_target - v) + 1.5 * self.v_int
        return self.gains["kd_xy"] * (v_target - v)

    def pursue(self, v_target: np.ndarray, vel: np.ndarray) -> np.ndarray:
        """Fly a 3D velocity (the chase's guidance)."""

        if self.gains is None:
            return 10.0 * (v_target - vel)
        g = self.gains
        return np.array([g["kd_xy"], g["kd_xy"], g["kd_z"]]) * (v_target - vel)


class _Flight:
    """One MuJoCo flight: the plant (thrust, lag, drag) and the flight controller."""

    def __init__(self, frame: dict, wind=None, controller: Controller | None = None) -> None:
        import mujoco

        self.mujoco = mujoco
        self.frame = frame
        self.model = mujoco.MjModel.from_xml_string(_model_xml(frame["geo"]))
        self.data = mujoco.MjData(self.model)
        self.body = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "drone")
        self.mass = float(self.model.body_mass[self.body])
        rot = np.zeros(9)
        mujoco.mju_quat2Mat(rot, self.model.body_iquat[self.body])
        rot = rot.reshape(3, 3)
        self.inertia = rot @ np.diag(self.model.body_inertia[self.body]) @ rot.T
        self.offset = np.array(self.model.body_ipos[self.body])
        self.wind = wind or (lambda t: np.zeros(3))
        rotors = frame["rotors"]
        self.r = np.array([rotor["r"] - self.offset for rotor in rotors])
        self.spin = np.array([rotor["spin"] for rotor in rotors], dtype=float)
        mix = np.vstack([np.ones(4), self.r[:, 1], -self.r[:, 0], -self.spin * frame["kq"]])
        self.unmix = np.linalg.inv(mix)
        self.thrust = np.full(4, self.mass * GRAVITY / 4)
        self.controller = controller or Controller()
        self.k_r, self.k_w = self.controller.rates(self.inertia, frame["tau"])
        self.t = 0.0
        self.peak_rate = 0.0
        self.saturated = 0.0
        self.thrust_left = 1.0
        # The pack starts fresh and sags with what the motors draw.
        self.plant = frame["plant"]
        self.soc = 1.0
        self.v_pack = self.plant.full_throttle(1.0)["v_pack"]
        self.v_start = self.plant.pack.ocv(1.0)
        self.v_min = self.v_start
        self.axial = np.zeros(4)
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[0:3] = (0.0, 0.0, START_Z)
        self.data.qpos[3:7] = (1.0, 0.0, 0.0, 0.0)
        mujoco.mj_forward(self.model, self.data)

    # -- state ------------------------------------------------------------------------------

    @property
    def pos(self) -> np.ndarray:
        return np.array(self.data.qpos[0:3])

    @property
    def vel(self) -> np.ndarray:
        return np.array(self.data.qvel[0:3])

    def rotation(self) -> np.ndarray:
        return np.array(self.data.xmat[self.body]).reshape(3, 3)

    def set_velocity(self, v) -> None:
        self.data.qvel[0:3] = v
        self.mujoco.mj_forward(self.model, self.data)

    def pose(self) -> list[float]:
        q = self.data.qpos
        return [round(self.t, 3), *(round(float(v), 4) for v in q[0:3]), *(round(float(v), 4) for v in q[3:7])]

    # -- one step -----------------------------------------------------------------------------

    def _limits(self, rot: np.ndarray, v_rel_b: np.ndarray, w_b: np.ndarray) -> np.ndarray:
        # Positive axial: the disc moving along its thrust axis into the air, as when climbing or
        # tilted forward at speed, so the air comes through it faster.
        self.axial = v_rel_b[2] + np.cross(w_b, self.r)[:, 2]
        return self.plant.thrust_max(self.v_pack, self.axial)

    def _drain(self) -> None:
        watts = float(self.plant.power(self.thrust, self.axial).sum())
        self.v_pack, current = self.plant.pack.terminal(self.soc, watts)
        self.soc = self.plant.pack.drain(self.soc, current, DT)
        self.v_min = min(self.v_min, self.v_pack)

    def pack_numbers(self) -> dict:
        used = (1.0 - self.soc) * self.plant.pack.capacity_ah * 1000.0
        return {"pack_v_start": round(self.v_start, 2), "pack_v_min": round(self.v_min, 2), "pack_used_mah": round(used, 1)}

    def step(self, accel: np.ndarray, heading: np.ndarray | None = None) -> None:
        frame = self.frame
        rot = self.rotation()
        w_b = np.array(self.data.qvel[3:6])
        v_rel = self.vel - self.wind(self.t)
        v_rel_b = rot.T @ v_rel
        t_max = self._limits(rot, v_rel_b, w_b)
        self.thrust_left = float(t_max.mean()) / frame["t0"]

        # Outer loop: the commanded acceleration, vertical first, then as much tilt as thrust allows.
        avail = 0.95 * float(t_max.sum()) / self.mass
        az = float(np.clip(accel[2], -0.8 * GRAVITY, max(avail - GRAVITY, -0.8 * GRAVITY)))
        up = GRAVITY + az
        horizontal = np.array(accel[:2], dtype=float)
        h_max = min(math.sqrt(max(avail * avail - up * up, 0.0)), up * math.tan(TILT_MAX))
        norm = float(np.linalg.norm(horizontal))
        if norm > h_max:
            horizontal *= h_max / norm
            self.saturated += DT
        force = self.mass * np.array([horizontal[0], horizontal[1], up])

        # Attitude: point the thrust along the force, nose kept to world +y or to `heading`.
        b3 = force / max(float(np.linalg.norm(force)), 1e-9)
        b2 = _cross(b3, (1.0, 0.0, 0.0)) if heading is None else heading - (heading @ b3) * b3
        b2 /= max(float(np.linalg.norm(b2)), 1e-9)
        b1 = _cross(b2, b3)
        target = np.column_stack([b1, b2, b3])
        e_r = 0.5 * _vee(target.T @ rot - rot.T @ target)
        alpha = -self.k_r * e_r - self.k_w * w_b
        torque = self.inertia @ alpha + _cross(w_b, self.inertia @ w_b)
        collective = max(float(force @ rot[:, 2]), 0.0)

        # Mixing with attitude priority: shift the four commands together before clipping.
        cmd = self.unmix @ np.array([collective, torque[0], torque[1], torque[2]])
        over = float(np.max(cmd - t_max))
        if over > 0:
            cmd -= over
        under = float(-np.min(cmd))
        if under > 0:
            cmd += under
        cmd = np.clip(cmd, 0.0, t_max)
        self.thrust += (cmd - self.thrust) * (DT / frame["tau"])
        self.thrust = np.minimum(self.thrust, t_max)
        self._drain()

        # Plant: rotor thrust (with ground effect) and H force, body drag, yaw drag torque.
        heights = float(self.data.qpos[2]) + (rot @ self.r.T)[2]
        lift = self.thrust * ground_effect(heights, frame["rotor_radius"])
        f_b = np.zeros(3)
        tau_b = np.zeros(3)
        for i in range(4):
            v_i = v_rel_b + np.cross(w_b, self.r[i])
            in_plane = np.array([v_i[0], v_i[1], 0.0])
            f_i = np.array([0.0, 0.0, lift[i]]) - self.thrust[i] * in_plane / frame["tip_speed"]
            f_b += f_i
            tau_b += np.cross(self.r[i], f_i)
            tau_b[2] -= self.spin[i] * frame["kq"] * self.thrust[i]
        speed = float(np.linalg.norm(v_rel_b))
        f_b -= 0.5 * RHO * speed * np.array([frame["cda_side"] * v_rel_b[0], frame["cda_side"] * v_rel_b[1], frame["cda_top"] * v_rel_b[2]])
        self.data.xfrc_applied[self.body, 0:3] = rot @ f_b
        self.data.xfrc_applied[self.body, 3:6] = rot @ tau_b
        self.mujoco.mj_step(self.model, self.data)
        self.t += DT
        self.peak_rate = max(self.peak_rate, float(np.linalg.norm(w_b)))

    def crashed(self) -> bool:
        z = float(self.data.qpos[2])
        return z < 0.05 or not math.isfinite(z) or abs(z) > 500


# -- outer loops ---------------------------------------------------------------------------------


def _sample(flight: _Flight, poses: list, every: int, step: int) -> None:
    if step % every == 0:
        poses.append(flight.pose())


def _trajectory(poses: list) -> list[list[float]]:
    return [p[0:4] for p in poses]


def speed_run(frame: dict, duration: float = 8.0, gains: dict | None = None) -> dict:
    """Full throttle along +x from a hover, height held: the top speed and the time to reach it."""

    ctl = Controller(gains)
    flight = _Flight(frame, controller=ctl)
    poses: list = []
    speeds: list[tuple[float, float]] = []
    every = round(SAMPLE_S / DT)
    crashed = False
    for step in range(round(duration / DT)):
        pos, v = flight.pos, flight.vel
        accel = np.array([ctl.dash(120.0, v[0]), ctl.lateral(0.0 - pos[1], v[1]), ctl.altitude(START_Z, pos, v)])
        flight.step(accel)
        _sample(flight, poses, every, step)
        if step % every == 0:
            speeds.append((round(flight.t, 3), round(float(math.hypot(flight.vel[0], flight.vel[1])), 3)))
        if flight.crashed():
            crashed = True
            break
    top = max((s for _, s in speeds), default=0.0)
    reach = next((t for t, s in speeds if s >= 0.95 * top), duration) if top > 0 else duration
    tail = [s for t, s in speeds if t >= flight.t - 0.5]
    return {
        "crashed": crashed,
        "top_speed_ms": round(top, 2),
        "top_speed_kmh": round(top * 3.6, 1),
        "time_to_top_s": round(reach, 2),
        "still_accelerating": bool(tail) and tail[-1] - tail[0] > 0.01 * top,
        # How much of the static thrust the props still make at top speed: low means the pitch speed is the wall.
        "thrust_left_pct": round(flight.thrust_left * 100.0, 0),
        "distance_m": round(float(flight.pos[0]), 1),
        **flight.pack_numbers(),
        "series": [[t, s] for t, s in speeds],
        "poses": poses,
    }


def turn(frame: dict, speed: float = TURN_SPEED, duration: float = 4.0, gains: dict | None = None) -> dict:
    """At `speed` along +x, from 1 s a hard 90 degree turn to +y: turn rate and overshoot.

    The turn pulls all the sideways acceleration the build has while holding its speed and
    height, so the turn rate is the build's lateral grip over its speed; at 90 degrees it
    straightens out on +y and the overshoot is how far its course swings past.
    """

    ctl = Controller(gains)
    flight = _Flight(frame, controller=ctl)
    flight.set_velocity([speed, 0.0, 0.0])
    poses: list = []
    every = round(SAMPLE_S / DT)
    start = 1.0
    headings: list[tuple[float, float]] = []
    crashed = False
    turned = False
    for step in range(round(duration / DT)):
        v = flight.vel[:2]
        heading = math.degrees(math.atan2(v[1], v[0]))
        turned = turned or heading >= 90.0
        if flight.t < start or turned:
            target = np.array([speed, 0.0]) if flight.t < start else np.array([0.0, speed])
            horizontal = ctl.track(target, v)
        else:
            along = v / max(float(np.linalg.norm(v)), 1e-6)
            left = np.array([-along[1], along[0]])
            # Ask for far more than any build has: the thrust limit decides how hard it turns.
            horizontal = 80.0 * left + 4.0 * (speed - float(np.linalg.norm(v))) * along
        flight.step(np.array([horizontal[0], horizontal[1], ctl.altitude(START_Z, flight.pos, flight.vel)]))
        _sample(flight, poses, every, step)
        if step % every == 0:
            headings.append((round(flight.t, 3), round(math.degrees(math.atan2(flight.vel[1], flight.vel[0])), 2)))
        if flight.crashed():
            crashed = True
            break
    after = [(t, h) for t, h in headings if t >= start]
    done = next((t for t, h in after if h >= 90.0), None)
    turn_time = (done - start) if done is not None else None
    peak = max((h for _, h in after), default=0.0)
    return {
        "crashed": crashed,
        "entry_speed_kmh": round(speed * 3.6, 1),
        "turn_time_s": round(turn_time, 2) if turn_time else None,
        "turn_rate_dps": round(90.0 / turn_time, 1) if turn_time else 0.0,
        "overshoot_pct": round(max(peak - 90.0, 0.0) / 90.0 * 100.0, 1),
        "peak_body_rate_dps": round(math.degrees(flight.peak_rate), 0),
        **flight.pack_numbers(),
        "series": [[t, h] for t, h in headings],
        "poses": poses,
    }


def _hold_wind(t: float) -> np.ndarray:
    """A 3 m/s side wind from 0.5 s with two gust frequencies, a cross gust and a 2 m/s downdraft at 2.5 s."""

    if t < 0.5:
        return np.zeros(3)
    ramp = min(1.0, (t - 0.5) / 0.4)
    x = ramp * (3.0 + 2.0 * math.sin(2 * math.pi * 0.7 * t) + 1.0 * math.sin(2 * math.pi * 1.9 * t + 1.0))
    y = ramp * 1.2 * math.sin(2 * math.pi * 1.3 * t)
    z = -2.0 if 2.5 <= t < 3.0 else 0.0
    return np.array([x, y, z])


def hold(frame: dict, duration: float = 6.0, gains: dict | None = None) -> dict:
    """Hold a point at 1.5 m through gusting side wind and a downdraft: the worst and RMS error."""

    ctl = Controller(gains)
    flight = _Flight(frame, wind=_hold_wind, controller=ctl)
    target = np.array([0.0, 0.0, START_Z])
    poses: list = []
    errors: list[tuple[float, float]] = []
    wind: list[list[float]] = []
    every = round(SAMPLE_S / DT)
    crashed = False
    for step in range(round(duration / DT)):
        flight.step(ctl.hold(target, flight.pos, flight.vel))
        _sample(flight, poses, every, step)
        if step % every == 0:
            errors.append((round(flight.t, 3), round(float(np.linalg.norm(flight.pos - target)) * 100.0, 2)))
            w = _hold_wind(flight.t)
            wind.append([round(flight.t, 3), *(round(float(v), 2) for v in w)])
        if flight.crashed():
            crashed = True
            break
    windy = [e for t, e in errors if t >= 0.5]
    worst = max(windy, default=0.0)
    rms = math.sqrt(sum(e * e for e in windy) / len(windy)) if windy else 0.0
    return {
        "crashed": crashed,
        "hold_error_cm": round(worst if not crashed else 999.0, 1),
        "rms_error_cm": round(rms, 1),
        "wind_ms": 3.0,
        # The thrust gained from the floor at the hold's height: the hold flies too high for it to matter.
        "ground_effect_pct": round(float(ground_effect(START_Z, frame["rotor_radius"]) - 1.0) * 100.0, 3),
        **flight.pack_numbers(),
        "series": [[t, e] for t, e in errors],
        "wind": wind,
        "poses": poses,
    }


def _fly_path(seed: int, duration: float, speed: float) -> list[np.ndarray]:
    """A fly at `speed` that darts off by 45 to 120 degrees every 0.5 to 0.9 s, in a 12 by 12 by 3 m room."""

    rng = random.Random(seed)
    pos = np.array([2.0, 1.2, 1.6])
    heading = math.radians(30.0)
    climb = 0.0
    path = []
    next_turn = 0.5
    t = 0.0

    def unit() -> np.ndarray:
        direction = np.array([math.cos(heading), math.sin(heading), climb])
        return direction / np.linalg.norm(direction)

    while t <= duration + 1e-9:
        if t >= next_turn:
            heading += math.radians(rng.choice((-1, 1)) * rng.uniform(45.0, 120.0))
            climb = rng.uniform(-0.35, 0.35)
            next_turn = t + rng.uniform(0.5, 0.9)
        ahead = pos + unit() * speed * DT
        # The fly turns back at the walls, the floor and the ceiling.
        if abs(ahead[0]) > 6.0:
            heading = math.pi - heading
        if abs(ahead[1]) > 6.0:
            heading = -heading
        if not 0.6 <= ahead[2] <= 3.0:
            climb = -climb
        pos = pos + unit() * speed * DT
        path.append(pos.copy())
        t += DT
    return path


class _Tracker:
    """A constant-velocity Kalman filter on the camera's delayed, noisy fixes of the fly."""

    ACCEL = 30.0  # m/s^2: a fly at 2.5 m/s darts off by up to 120 degrees in about a tenth of a second

    def __init__(self, position: np.ndarray, sigma: float) -> None:
        self.x = np.concatenate([position, np.zeros(3)])
        self.P = np.diag([sigma * sigma] * 3 + [TARGET_SPEED * TARGET_SPEED] * 3)
        self.t = 0.0
        self.last_fix: float | None = None

    def _propagate(self, dt: float) -> None:
        if dt <= 0:
            return
        f = np.eye(6)
        f[0:3, 3:6] = np.eye(3) * dt
        q = self.ACCEL * self.ACCEL
        block = np.array([[dt**4 / 4, dt**3 / 2], [dt**3 / 2, dt * dt]]) * q
        self.x = f @ self.x
        self.P = f @ self.P @ f.T + np.kron(block, np.eye(3))

    def update(self, z: np.ndarray, cov: np.ndarray, t_capture: float) -> None:
        self._propagate(t_capture - self.t)
        self.t = max(self.t, t_capture)
        h = np.hstack([np.eye(3), np.zeros((3, 3))])
        s = h @ self.P @ h.T + cov
        gain = self.P @ h.T @ np.linalg.inv(s)
        self.x = self.x + gain @ (z - h @ self.x)
        self.P = (np.eye(6) - gain @ h) @ self.P
        self.last_fix = t_capture

    def at(self, t: float) -> tuple[np.ndarray, np.ndarray]:
        """Position and velocity predicted across the delay to now."""

        return self.x[0:3] + self.x[3:6] * (t - self.t), self.x[3:6].copy()


TRACK_COAST_S = 0.5
CUE_S = 1.0
SEARCH_YAW = 3.0
YAW_RATE = 10.0


def _look(flight: _Flight, camera: dict, fly: np.ndarray) -> tuple[bool, float, float, float]:
    """(seen, azimuth, elevation, pixels): where the fly is in the camera's picture and how big."""

    rot = flight.rotation()
    tilt = camera["tilt"]
    forward = rot @ np.array([0.0, math.cos(tilt), math.sin(tilt)])
    up = rot @ np.array([0.0, -math.sin(tilt), math.cos(tilt)])
    right = rot @ np.array([1.0, 0.0, 0.0])
    rel = fly - flight.pos
    ahead = float(rel @ forward)
    distance = float(np.linalg.norm(rel))
    pixels = 0.006 / max(distance, 1e-6) / camera["ifov"]
    if ahead <= 0:
        return False, 0.0, 0.0, pixels
    az = math.atan2(float(rel @ right), ahead)
    el = math.atan2(float(rel @ up), ahead)
    seen = abs(az) <= camera["fov_h"] / 2 and abs(el) <= camera["fov_v"] / 2 and pixels >= 2.0
    return seen, az, el, pixels


def _fix(flight: _Flight, camera: dict, az: float, el: float, pixels: float, rng: random.Random) -> tuple[np.ndarray, np.ndarray]:
    """The fly's position from one detection: half a pixel of noise in bearing and in apparent size."""

    rot = flight.rotation()
    tilt = camera["tilt"]
    forward = rot @ np.array([0.0, math.cos(tilt), math.sin(tilt)])
    up = rot @ np.array([0.0, -math.sin(tilt), math.cos(tilt)])
    right = rot @ np.array([1.0, 0.0, 0.0])
    ifov = camera["ifov"]
    az += rng.gauss(0.0, 0.5 * ifov)
    el += rng.gauss(0.0, 0.5 * ifov)
    seen_px = max(pixels + rng.gauss(0.0, 0.5), 1.0)
    distance = 0.006 / (seen_px * ifov)
    ray = forward + math.tan(az) * right + math.tan(el) * up
    ray /= float(np.linalg.norm(ray))
    sigma_r = distance * 0.5 / seen_px
    sigma_side = distance * 0.5 * ifov
    cov = sigma_r * sigma_r * np.outer(ray, ray) + sigma_side * sigma_side * (np.eye(3) - np.outer(ray, ray))
    return flight.pos + ray * distance, cov


def _chase_one(frame: dict, fly: list[np.ndarray], record: bool, seed: int = 0, gains: dict | None = None) -> dict:
    ctl = Controller(gains)
    flight = _Flight(frame, controller=ctl)
    camera = frame["camera"]
    rng = random.Random(1000 + seed)
    tracker = _Tracker(fly[0], 0.5)
    pending: list[tuple[float, np.ndarray, np.ndarray, float]] = []
    period = 1.0 / camera["fps"]
    next_frame = 0.0
    # The nose (and the camera) starts towards the fly.
    psi = math.atan2(float(fly[0][1] - flight.pos[1]), float(fly[0][0] - flight.pos[0]))
    poses: list = []
    target: list[list[float]] = []
    distances: list[list[float]] = []
    every = round(SAMPLE_S / DT)
    closest = float("inf")
    captured_at = None
    crashed = False
    first_fix = None
    lost_at = None
    reacquire = 0.0
    lost_count = 0
    seen_time = 0.0
    for step in range(len(fly) - 1):
        p_t = fly[step]
        distance = float(np.linalg.norm(p_t - flight.pos))
        closest = min(closest, distance)
        done = distance <= CAPTURE_M
        if record and (step % every == 0 or done):
            poses.append(flight.pose())
            target.append([round(flight.t, 3), *(round(float(v), 4) for v in p_t)])
            distances.append([round(flight.t, 3), round(distance * 100.0, 1)])
        if done:
            captured_at = flight.t
            break
        # The camera: one picture per frame, the fix reaches the estimator after the delay.
        if flight.t >= next_frame - 1e-9:
            next_frame += period
            seen, az, el, pixels = _look(flight, camera, p_t)
            if seen:
                z, cov = _fix(flight, camera, az, el, pixels, rng)
                pending.append((flight.t + camera["delay_s"], z, cov, flight.t))
                seen_time += period
                if first_fix is None:
                    first_fix = flight.t
                if lost_at is not None:
                    reacquire += flight.t - lost_at
                    lost_at = None
            elif first_fix is not None and lost_at is None:
                lost_at = flight.t
                lost_count += 1
        while pending and pending[0][0] <= flight.t + 1e-9:
            _ready, z, cov, taken = pending.pop(0)
            tracker.update(z, cov, taken)
        tracking = (tracker.last_fix is not None and flight.t - tracker.last_fix <= TRACK_COAST_S + camera["delay_s"]) or (tracker.last_fix is None and flight.t <= CUE_S)
        if tracking:
            # Lead pursuit on the estimate: match the fly's velocity, aim where it will be when the
            # drone gets there (at most 1 s ahead), and close at 4 m/s per metre of gap, never slower than 3 m/s.
            p_hat, v_hat = tracker.at(flight.t)
            gap = float(np.linalg.norm(p_hat - flight.pos))
            closing = max(CLOSING_MS, float(np.linalg.norm(flight.vel)))
            aim = p_hat + v_hat * min(gap / closing, 1.0)
            lead = aim - flight.pos
            reach = float(np.linalg.norm(lead))
            v_des = v_hat + lead / max(reach, 1e-6) * min(max(4.0 * reach, CLOSING_MS), 30.0)
            want = math.atan2(float(p_hat[1] - flight.pos[1]), float(p_hat[0] - flight.pos[0]))
        else:
            # Lost: stop and turn on the spot until the fly is in the picture again.
            v_des = np.zeros(3)
            want = psi + SEARCH_YAW * DT
        turn_by = (want - psi + math.pi) % (2 * math.pi) - math.pi
        psi += float(np.clip(turn_by, -YAW_RATE * DT, YAW_RATE * DT))
        flight.step(ctl.pursue(v_des, flight.vel), heading=np.array([math.cos(psi), math.sin(psi), 0.0]))
        if flight.crashed():
            crashed = True
            break
    if lost_at is not None:
        reacquire += flight.t - lost_at
    return {
        "capture_s": None if captured_at is None else round(captured_at, 2),
        "closest_cm": round(closest * 100.0, 1),
        "crashed": crashed,
        "first_fix_s": None if first_fix is None else round(first_fix, 2),
        "reacquire_s": round(reacquire, 2),
        "tracks_lost": lost_count,
        "seen_pct": round(seen_time / max(flight.t, 1e-6) * 100.0, 0),
        "pack": flight.pack_numbers(),
        "poses": poses,
        "target": target,
        "series": distances,
    }


def chase(frame: dict, flies: int = CHASE_FLIES, duration: float = CHASE_S, speed: float = TARGET_SPEED, gains: dict | None = None) -> dict:
    """Chase five flies, each dodging its own way; capture is within 12 cm. The median capture time counts.

    One fly alone is a coin toss: a dodge at the right moment saves it. Over five, a build that
    accelerates and turns harder catches more of them, sooner, so the median separates builds.
    A missed fly counts as never caught.
    """

    tries = []
    for seed in range(flies):
        tries.append(_chase_one(frame, _fly_path(seed, duration, speed), record=False, seed=seed, gains=gains))
    times = sorted(t["capture_s"] if t["capture_s"] is not None else math.inf for t in tries)
    median = times[len(times) // 2]
    caught = sum(1 for t in tries if t["capture_s"] is not None)
    # Replay the fly closest to the median: the typical chase, not the luckiest one.
    order = sorted(range(flies), key=lambda i: (tries[i]["capture_s"] if tries[i]["capture_s"] is not None else math.inf, tries[i]["closest_cm"]))
    shown = order[len(order) // 2]
    replay = _chase_one(frame, _fly_path(shown, duration, speed), record=True, seed=shown, gains=gains)
    missed = [t["closest_cm"] for t in tries if t["capture_s"] is None]
    return {
        "crashed": any(t["crashed"] for t in tries),
        "captured": caught,
        "flies": flies,
        "capture_s": None if math.isinf(median) else round(median, 2),
        "capture_times_s": [t["capture_s"] for t in tries],
        "miss_distance_cm": min(missed) if missed else 0.0,
        "target_speed_kmh": round(speed * 3.6, 1),
        "capture_radius_cm": round(CAPTURE_M * 100.0, 0),
        "shown_fly": shown + 1,
        # What the camera allows: the range a 6 mm fly still covers 2 pixels, the delay of each fix,
        # and the time spent looking for a fly the camera had lost, per fly.
        "detect_range_m": round(frame["camera"]["detect_range_m"], 2),
        "sensing_delay_ms": round(frame["camera"]["delay_s"] * 1000.0, 0),
        "first_fix_s": _median([t["first_fix_s"] for t in tries]),
        "reacquire_s": round(sum(t["reacquire_s"] for t in tries) / flies, 2),
        "tracks_lost": sum(t["tracks_lost"] for t in tries),
        **replay["pack"],
        "series": replay["series"],
        "target": replay["target"],
        "poses": replay["poses"],
    }


def _median(values: list) -> float | None:
    known = sorted(v for v in values if v is not None)
    return known[len(known) // 2] if known else None


RUNNERS = {"speed_run": speed_run, "turn": turn, "hold": hold, "chase": chase}


def run(frame: dict, mission: str, gains: dict | None = None) -> dict:
    """One mission, flown with the reference controller, or with `gains` (the trained controller)."""

    if mission not in RUNNERS:
        raise AirframeError("mission must be one of " + ", ".join(RUNNERS) + ".")
    out = RUNNERS[mission](frame, gains=gains)
    out["mission"] = mission
    out["controller"] = "reference" if gains is None else "trained"
    out["mass_g"] = round(frame["geo"]["total_mass_g"], 1)
    return out


def value_of(outcome: dict) -> float | None:
    """The number a mission's requirement is judged on: None when it never got one (no capture)."""

    key = MISSIONS[outcome["mission"]]["key"]
    value = outcome.get(key)
    return None if value is None else float(value)


def passes(outcome: dict, limit: float) -> bool:
    if outcome.get("crashed"):
        return False
    value = value_of(outcome)
    if value is None:
        return False
    return value >= limit if MISSIONS[outcome["mission"]]["kind"] == "min" else value <= limit
