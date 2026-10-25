"""Mission tests in MuJoCo: the drone built from its chosen parts flies a speed run, a hard turn,
a position hold in wind and a chase of a dodging target.

The airframe (`airframe`) comes from the parts, nothing is a fixed constant of one build:

- Mass and inertia: every part is a MuJoCo geom with its catalog mass at its place in the
  assembly (`drone_geometry.geometry`): motors on the arm tips, propellers as discs on the
  motors, the pack under the plate, the board on its standoffs, the frame as a hub and four
  arms. MuJoCo sums them into the body's mass, centre of mass and full inertia matrix, so the
  sim weighs exactly what physics_calc and the bill of materials list.
- Thrust: each motor's peak static thrust is its catalog `thrust_g` (the bench figure at its
  rated voltage; a higher-voltage pack never adds thrust, a pack under 90 % of the test voltage
  loses thrust with the voltage squared, `flight.thrust_per_motor_g`, as physics_calc counts it). Thrust falls linearly with the air
  speed through the disc, to zero at the propeller's pitch speed: pitch times loaded rpm, with
  loaded rpm = 75 % of kv times the pack's voltage (capped at 3.8 V per cell the motor is
  rated for). Without a pitch the propeller is taken as
  pitch = 0.8 diameter; without a kv, the pitch speed is 35 m/s.
- Motor response: a first-order lag of 15 ms for a 51 mm propeller, growing with the square of
  the diameter (bigger props spin up slower), 10 to 120 ms.
- Yaw: each propeller's drag torque is 0.012 m per newton of thrust per 51 mm of diameter;
  props spin as in `freecad/frame_build.py`.
- Drag: the body's flat-plate drag, 0.5 rho Cd A v^2 with Cd 1.0 sideways and 1.2 through the
  disc plane, A from the parts' own outlines (pack, board, motors, arms, camera); plus rotor
  drag (blade flapping, the H force): each rotor pushes back against the in-plane air speed with
  its thrust times the air speed over its tip speed. Air density 1.225 kg/m^3.
- Not modelled: battery sag over the flight, ground effect, prop wash between rotors, the
  vortex ring state, sensor noise and estimator delay. The pack is taken as fresh.

The flight controller is the same for every build: a geometric attitude controller whose
bandwidth follows the motor lag, mixing with attitude priority, thrust tilt limited to 70 degrees,
and per-mission outer loops on position or velocity. A build only differs by its parts, so a
heavier or weaker build measurably loses speed, turns slower or misses the chase.

All missions are deterministic: fixed start, fixed seed for the target's dodges and the wind.
"""

from __future__ import annotations

import math
import random

import numpy as np

from pai_agent.flight import thrust_per_motor_g

GRAVITY = 9.80665
RHO = 1.225
DT = 0.002
SAMPLE_S = 0.02
START_Z = 1.5
TILT_MAX = math.radians(70.0)
LOADED_RPM = 0.75

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


class AirframeError(ValueError):
    pass


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
    pitch_in = _num(prop, "pitch_in") or diameter * 0.8 / 25.4
    kv = _num(motor, "kv")
    volts = _num(battery, "voltage_v")
    cells_max = _num(motor, "cells_max")
    if volts and cells_max:
        # A pack above the motor's rating spins it no faster here, as physics_calc adds no thrust for it.
        volts = min(volts, cells_max * 3.8)
    if kv and volts:
        rpm = kv * volts * LOADED_RPM
        pitch_speed = pitch_in * 0.0254 * rpm / 60.0
        tip_speed = rpm / 60.0 * 2 * math.pi * diameter / 2000.0
    else:
        pitch_speed = 35.0
        tip_speed = 110.0
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
        # Below the load table's voltage the motor makes less thrust, as physics_calc computes it.
        "t0": thrust_per_motor_g(motor, float(battery["voltage_v"]))[0] / 1000.0 * GRAVITY if battery.get("voltage_v") else thrust_g / 1000.0 * GRAVITY,
        "pitch_speed": pitch_speed,
        "tip_speed": tip_speed,
        "tau": min(0.12, max(0.01, 0.015 * scale * scale)),
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


class _Flight:
    """One MuJoCo flight: the plant (thrust, lag, drag) and the flight controller."""

    def __init__(self, frame: dict, wind=None) -> None:
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
        omega = min(28.0, 0.4 / frame["tau"])
        self.k_r = omega * omega
        self.k_w = 1.6 * omega
        self.t = 0.0
        self.peak_rate = 0.0
        self.saturated = 0.0
        self.thrust_left = 1.0
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
        axial = v_rel_b[2] + np.cross(w_b, self.r)[:, 2]
        factor = np.clip(1.0 - axial / self.frame["pitch_speed"], 0.0, 1.2)
        return self.frame["t0"] * factor

    def step(self, accel: np.ndarray) -> None:
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

        # Attitude: point the thrust along the force, nose kept to world +y.
        b3 = force / max(float(np.linalg.norm(force)), 1e-9)
        b2 = np.cross(b3, np.array([1.0, 0.0, 0.0]))
        b2 /= max(float(np.linalg.norm(b2)), 1e-9)
        b1 = np.cross(b2, b3)
        target = np.column_stack([b1, b2, b3])
        e_r = 0.5 * _vee(target.T @ rot - rot.T @ target)
        alpha = -self.k_r * e_r - self.k_w * w_b
        torque = self.inertia @ alpha + np.cross(w_b, self.inertia @ w_b)
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

        # Plant: rotor thrust and H force, body drag, yaw drag torque.
        f_b = np.zeros(3)
        tau_b = np.zeros(3)
        for i in range(4):
            v_i = v_rel_b + np.cross(w_b, self.r[i])
            in_plane = np.array([v_i[0], v_i[1], 0.0])
            f_i = np.array([0.0, 0.0, self.thrust[i]]) - self.thrust[i] * in_plane / frame["tip_speed"]
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


class _Hold:
    """PID on position, the same gains for every build."""

    def __init__(self, kp: float = 5.0, kd: float = 3.6, ki: float = 2.0) -> None:
        self.kp, self.kd, self.ki = kp, kd, ki
        self.integral = np.zeros(3)

    def __call__(self, flight: _Flight, target: np.ndarray, v_target: np.ndarray | None = None) -> np.ndarray:
        error = target - flight.pos
        self.integral = np.clip(self.integral + error * DT, -2.0, 2.0)
        v_ref = np.zeros(3) if v_target is None else v_target
        return self.kp * error + self.kd * (v_ref - flight.vel) + self.ki * self.integral


def _altitude(flight: _Flight, z: float, integral: list[float]) -> float:
    error = z - float(flight.pos[2])
    integral[0] = float(np.clip(integral[0] + error * DT, -2.0, 2.0))
    return 6.0 * error - 4.5 * float(flight.vel[2]) + 2.0 * integral[0]


def _sample(flight: _Flight, poses: list, every: int, step: int) -> None:
    if step % every == 0:
        poses.append(flight.pose())


def _trajectory(poses: list) -> list[list[float]]:
    return [p[0:4] for p in poses]


def speed_run(frame: dict, duration: float = 8.0) -> dict:
    """Full throttle along +x from a hover, height held: the top speed and the time to reach it."""

    flight = _Flight(frame)
    poses: list = []
    speeds: list[tuple[float, float]] = []
    every = round(SAMPLE_S / DT)
    z_int = [0.0]
    crashed = False
    for step in range(round(duration / DT)):
        v = flight.vel
        accel = np.array([3.0 * (120.0 - v[0]), 3.0 * (0.0 - flight.pos[1]) - 2.0 * v[1], _altitude(flight, START_Z, z_int)])
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
        "series": [[t, s] for t, s in speeds],
        "poses": poses,
    }


def turn(frame: dict, speed: float = TURN_SPEED, duration: float = 4.0) -> dict:
    """At `speed` along +x, from 1 s a hard 90 degree turn to +y: turn rate and overshoot.

    The turn pulls all the sideways acceleration the build has while holding its speed and
    height, so the turn rate is the build's lateral grip over its speed; at 90 degrees it
    straightens out on +y and the overshoot is how far its course swings past.
    """

    flight = _Flight(frame)
    flight.set_velocity([speed, 0.0, 0.0])
    poses: list = []
    every = round(SAMPLE_S / DT)
    z_int = [0.0]
    v_int = np.zeros(2)
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
            v_int = np.clip(v_int + (target - v) * DT, -3.0, 3.0)
            horizontal = 4.0 * (target - v) + 1.5 * v_int
        else:
            along = v / max(float(np.linalg.norm(v)), 1e-6)
            left = np.array([-along[1], along[0]])
            # Ask for far more than any build has: the thrust limit decides how hard it turns.
            horizontal = 80.0 * left + 4.0 * (speed - float(np.linalg.norm(v))) * along
        flight.step(np.array([horizontal[0], horizontal[1], _altitude(flight, START_Z, z_int)]))
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


def hold(frame: dict, duration: float = 6.0) -> dict:
    """Hold a point at 1.5 m through gusting side wind and a downdraft: the worst and RMS error."""

    flight = _Flight(frame, wind=_hold_wind)
    control = _Hold()
    target = np.array([0.0, 0.0, START_Z])
    poses: list = []
    errors: list[tuple[float, float]] = []
    wind: list[list[float]] = []
    every = round(SAMPLE_S / DT)
    crashed = False
    for step in range(round(duration / DT)):
        flight.step(control(flight, target))
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


def _chase_one(frame: dict, fly: list[np.ndarray], record: bool) -> dict:
    flight = _Flight(frame)
    poses: list = []
    target: list[list[float]] = []
    distances: list[list[float]] = []
    every = round(SAMPLE_S / DT)
    closest = float("inf")
    captured_at = None
    crashed = False
    for step in range(len(fly) - 1):
        p_t = fly[step]
        v_t = (fly[step + 1] - p_t) / DT
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
        # Lead pursuit: match the fly's velocity, aim where it will be when the drone gets there
        # (at most 1 s ahead), and close at 4 m/s per metre of gap, never slower than 3 m/s.
        closing = max(CLOSING_MS, float(np.linalg.norm(flight.vel)))
        aim = p_t + v_t * min(distance / closing, 1.0)
        lead = aim - flight.pos
        reach = float(np.linalg.norm(lead))
        v_des = v_t + lead / max(reach, 1e-6) * min(max(4.0 * reach, CLOSING_MS), 30.0)
        flight.step(10.0 * (v_des - flight.vel))
        if flight.crashed():
            crashed = True
            break
    return {"capture_s": None if captured_at is None else round(captured_at, 2), "closest_cm": round(closest * 100.0, 1), "crashed": crashed, "poses": poses, "target": target, "series": distances}


def chase(frame: dict, flies: int = CHASE_FLIES, duration: float = CHASE_S, speed: float = TARGET_SPEED) -> dict:
    """Chase five flies, each dodging its own way; capture is within 12 cm. The median capture time counts.

    One fly alone is a coin toss: a dodge at the right moment saves it. Over five, a build that
    accelerates and turns harder catches more of them, sooner, so the median separates builds.
    A missed fly counts as never caught.
    """

    tries = []
    for seed in range(flies):
        tries.append(_chase_one(frame, _fly_path(seed, duration, speed), record=False))
    times = sorted(t["capture_s"] if t["capture_s"] is not None else math.inf for t in tries)
    median = times[len(times) // 2]
    caught = sum(1 for t in tries if t["capture_s"] is not None)
    # Replay the fly closest to the median: the typical chase, not the luckiest one.
    order = sorted(range(flies), key=lambda i: (tries[i]["capture_s"] if tries[i]["capture_s"] is not None else math.inf, tries[i]["closest_cm"]))
    shown = order[len(order) // 2]
    replay = _chase_one(frame, _fly_path(shown, duration, speed), record=True)
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
        "series": replay["series"],
        "target": replay["target"],
        "poses": replay["poses"],
    }


RUNNERS = {"speed_run": speed_run, "turn": turn, "hold": hold, "chase": chase}


def run(frame: dict, mission: str) -> dict:
    if mission not in RUNNERS:
        raise AirframeError("mission must be one of " + ", ".join(RUNNERS) + ".")
    out = RUNNERS[mission](frame)
    out["mission"] = mission
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
