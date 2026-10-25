"""Training on the missions, on the backend: an evolution strategy over the seven controller gains.

The trainer flies the same MuJoCo model as the missions (`mission_sim`), so a gain set that
scores well here is judged again on exactly those missions. Each candidate flies:

- hover: from 0.6 m off the spot and tilted 21 degrees, back onto a point within 3 s and held there;
- every mission the build was judged on (speed run, hard turn, position hold, chase), against
  its requirement limit. The speed run and the turn are cut short (3.5 s, 3 s) and the chase is
  three flies of 5 s, not five of 8 s, so a candidate flies in about two seconds; the validation
  after training flies the full missions.

Each term is the requirement's ratio (value over limit, or limit over value for a maximum; hover
against 10 cm RMS), capped at 1.5, 0 for a crash or a missed number; the score is their mean
scaled to 0 to 100. The first two candidates are the reference controller's gains
(`reference_seeds`), so the best never scores below them.

The gains come out in the browser trainer's format (web/src/sim/drone.ts `exportGains`): the seven
cascaded gains, attitude in N m/rad and N m s/rad, plus Betaflight roll and pitch P and I scaled by
the trained rate damping. The search runs in the trainer's units (attitude per unit inertia).

`stress_world` flies one world of the stress test on this model, for the backend stress test.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

import numpy as np

from pai_agent.mission_sim import (
    DT,
    GAIN_KEYS,
    MISSIONS,
    START_Z,
    TARGET_SPEED,
    Controller,
    _chase_one,
    _Flight,
    _fly_path,
    hold,
    speed_run,
    turn,
)

# Trainer units: height and position as exported; attitude per unit inertia (1/s^2, 1/s).
PARAMS = (
    ("kp_z", 0.5, 40.0),
    ("ki_z", 0.05, 20.0),
    ("kd_z", 0.2, 15.0),
    ("kp_xy", 0.1, 60.0),
    ("kd_xy", 0.1, 20.0),
    ("kp_att", 5.0, 3000.0),
    ("kd_att", 0.5, 150.0),
)
POPULATION = 8
GENERATIONS = 5
TIME_LIMIT_S = 120.0
SEED = 11
ELITE = 0.25
SIGMA = 0.12

HOVER_S = 3.0
HOVER_SETTLE_S = 1.5
HOVER_LIMIT_CM = 10.0
HOVER_START = (0.35, -0.25, -0.45)
HOVER_TILT = (0.3, -0.2)
TRAIN_SPEED_S = 3.5
TRAIN_TURN_S = 3.0
TRAIN_FLIES = 3
TRAIN_CHASE_S = 5.0
CAP = 1.5

# Betaflight 4.4 rate-loop defaults for a 1S whoop, and the rate damping they stand for (drone.ts).
BETAFLIGHT_DEFAULT = {"roll": {"p": 45, "i": 80}, "pitch": {"p": 47, "i": 84}}
REFERENCE_KD_ATT = 12.0


def roll_pitch_inertia(frame: dict) -> float:
    """The build's mean roll and pitch inertia, kg m^2: what turns attitude gains into the trainer's units."""

    inertia = _Flight(frame).inertia
    return float((inertia[0, 0] + inertia[1, 1]) / 2)


def reference_gains(frame: dict) -> dict[str, float]:
    """The reference controller as seven gains: its hold loop's height and position, its attitude bandwidth."""

    omega = min(28.0, 0.8 / frame["tau"])
    inertia = roll_pitch_inertia(frame)
    return {"kp_z": 6.0, "ki_z": 2.0, "kd_z": 4.5, "kp_xy": 5.0, "kd_xy": 3.6, "kp_att": omega * omega * inertia, "kd_att": 1.6 * omega * inertia}


def reference_seeds(frame: dict) -> list[dict[str, float]]:
    """Where the search starts: the reference's hold loop, and its chase loop as one cascade.

    The reference chases on a velocity gain of 10 and holds on 3.6; seven gains have one velocity
    gain, so both are tried, the chase one at the hold loop's damping (kp over kd squared kept).
    """

    hold = reference_gains(frame)
    k = 10.0 / hold["kd_xy"]
    return [hold, dict(hold, kd_xy=10.0, kp_xy=hold["kp_xy"] * k * k)]


def _sig(value: float) -> float:
    return float(f"{value:.4g}")


def export_gains(gains: dict, inertia: float) -> dict:
    """The browser trainer's gain format: seven cascaded gains plus Betaflight roll and pitch P and I."""

    k = min(2.0, max(0.5, gains["kd_att"] / inertia / REFERENCE_KD_ATT))
    out: dict = {key: _sig(float(gains[key])) for key in GAIN_KEYS}
    for axis, terms in BETAFLIGHT_DEFAULT.items():
        out[axis] = {"p": round(terms["p"] * k), "i": round(terms["i"] * k)}
    return out


def _to_unit(gains: dict, inertia: float) -> np.ndarray:
    values = []
    for key, lo, hi in PARAMS:
        value = gains[key] / inertia if key in {"kp_att", "kd_att"} else gains[key]
        values.append((math.log(min(max(value, lo), hi)) - math.log(lo)) / (math.log(hi) - math.log(lo)))
    return np.array(values)


def _from_unit(x: np.ndarray, inertia: float) -> dict[str, float]:
    gains = {}
    for (key, lo, hi), u in zip(PARAMS, np.clip(x, 0.0, 1.0)):
        value = math.exp(math.log(lo) + float(u) * (math.log(hi) - math.log(lo)))
        gains[key] = value * inertia if key in {"kp_att", "kd_att"} else value
    return gains


def _tilted(roll: float, pitch: float) -> tuple[float, float, float, float]:
    cr, sr, cp, sp = math.cos(roll / 2), math.sin(roll / 2), math.cos(pitch / 2), math.sin(pitch / 2)
    return (cr * cp, sr * cp, cr * sp, -sr * sp)


def hover(frame: dict, gains: dict | None = None, duration: float = HOVER_S) -> dict:
    """Back onto a point from 0.6 m off and tilted, then held: RMS error after the settle, peak tilt."""

    ctl = Controller(gains)
    flight = _Flight(frame, controller=ctl)
    target = np.array([0.0, 0.0, START_Z])
    flight.data.qpos[0:3] = target + np.array(HOVER_START)
    flight.data.qpos[3:7] = _tilted(*HOVER_TILT)
    flight.mujoco.mj_forward(flight.model, flight.data)
    err2, count, tilt = 0.0, 0, 0.0
    crashed = False
    for _ in range(round(duration / DT)):
        flight.step(ctl.hold(target, flight.pos, flight.vel))
        if flight.crashed():
            crashed = True
            break
        if flight.t >= HOVER_SETTLE_S:
            err2 += float(np.sum((flight.pos - target) ** 2))
            count += 1
            tilt = max(tilt, math.acos(min(1.0, max(-1.0, float(flight.rotation()[2, 2])))))
    rms = math.sqrt(err2 / count) * 100.0 if count else 999.0
    return {"crashed": crashed, "rms_error_cm": round(rms if not crashed else 999.0, 1), "max_tilt_deg": round(math.degrees(tilt), 1)}


def _ratio(value: float | None, limit: float, kind: str) -> float:
    if value is None or value <= 0 or limit <= 0:
        return 0.0
    return min(CAP, value / limit if kind == "min" else limit / value)


def _chase_train(frame: dict, gains: dict) -> dict:
    times = []
    crashed = False
    for seed in range(TRAIN_FLIES):
        one = _chase_one(frame, _fly_path(seed, TRAIN_CHASE_S, TARGET_SPEED), record=False, seed=seed, gains=gains)
        crashed = crashed or one["crashed"]
        times.append(one["capture_s"] if one["capture_s"] is not None else math.inf)
    median = sorted(times)[len(times) // 2]
    return {"crashed": crashed, "capture_s": None if math.isinf(median) else median}


def _fly(frame: dict, mission: str, gains: dict) -> dict:
    if mission == "speed_run":
        return speed_run(frame, duration=TRAIN_SPEED_S, gains=gains)
    if mission == "turn":
        return turn(frame, duration=TRAIN_TURN_S, gains=gains)
    if mission == "hold":
        return hold(frame, gains=gains)
    return _chase_train(frame, gains)


def evaluate(frame: dict, gains: dict, limits: dict[str, float]) -> tuple[float, dict]:
    """The training score of one gain set, 0 to 100, and each term's number."""

    terms: dict[str, dict] = {}
    first = hover(frame, gains)
    terms["hover"] = {"value": first["rms_error_cm"], "ratio": 0.0 if first["crashed"] else _ratio(first["rms_error_cm"], HOVER_LIMIT_CM, "max")}
    # A controller that cannot hover is not flown through the missions.
    if terms["hover"]["ratio"] > 0:
        for mission, limit in limits.items():
            spec = MISSIONS[mission]
            outcome = _fly(frame, mission, gains)
            value = outcome.get(spec["key"])
            ratio = 0.0 if outcome.get("crashed") else _ratio(None if value is None else float(value), limit, spec["kind"])
            terms[mission] = {"value": value, "ratio": ratio}
    total = sum(t["ratio"] for t in terms.values())
    score = 100.0 * total / (CAP * (1 + len(limits)))
    return score, terms


def train(
    frame: dict,
    limits: dict[str, float],
    *,
    population: int = POPULATION,
    generations: int = GENERATIONS,
    time_limit_s: float = TIME_LIMIT_S,
    seed: int = SEED,
    start: dict | None = None,
    on_generation: Callable[[dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Cross-entropy search over the seven gains, seeded at `start` and the reference seeds.

    Stops after `generations`, or when `time_limit_s` runs out (or `should_stop` says so) after a
    finished candidate; the best gain set flown so far is the result.
    """

    inertia = roll_pitch_inertia(frame)
    seeds = ([start] if start else []) + reference_seeds(frame)
    rng = np.random.default_rng(seed)
    mean = _to_unit(seeds[0], inertia)
    sigma = np.full(len(PARAMS), SIGMA)
    began = time.monotonic()
    best: dict | None = None
    curve: list[list[float]] = []
    rollouts = 0
    seed_score = None
    stopped = False
    for generation in range(generations):
        xs = [np.clip(mean + sigma * rng.standard_normal(len(PARAMS)), 0.0, 1.0) for _ in range(population)]
        if generation == 0:
            xs[: len(seeds)] = [_to_unit(g, inertia) for g in seeds]
        scored = []
        for index, x in enumerate(xs):
            gains = seeds[index] if generation == 0 and index < len(seeds) else _from_unit(x, inertia)
            score, terms = evaluate(frame, gains, limits)
            rollouts += 1
            if seed_score is None:
                seed_score = score
            scored.append((score, x, gains, terms))
            if best is None or score > best["score"]:
                best = {"score": score, "gains": gains, "terms": terms, "generation": generation + 1}
            if time.monotonic() - began > time_limit_s or (should_stop and should_stop()):
                stopped = True
                break
        scored.sort(key=lambda item: -item[0])
        elite = np.array([item[1] for item in scored[: max(2, round(len(scored) * ELITE))]])
        mean = 0.3 * mean + 0.7 * elite.mean(axis=0)
        sigma = np.maximum(0.03, 0.3 * sigma + 0.7 * elite.std(axis=0))
        curve.append([rollouts, round(best["score"], 2)])
        if on_generation:
            on_generation({"generation": generation + 1, "rollouts": rollouts, "best_score": round(best["score"], 2), "mean_score": round(sum(s[0] for s in scored) / len(scored), 2), "best_gains": best["gains"], "curve": list(curve)})
        if stopped:
            break
    assert best is not None
    return {
        "gains": export_gains(best["gains"], inertia),
        "score": round(best["score"], 2),
        "terms": best["terms"],
        # The score of the first seed: the reference hold loop unless `start` was given.
        "start_score": round(seed_score, 2),
        "rollouts": rollouts,
        "generations": len(curve),
        "curve": curve,
        "stopped_early": stopped,
        "seconds": round(time.monotonic() - began, 1),
        "inertia": inertia,
    }


# -- one stress world on the mission model ---------------------------------------------------

STRESS_S = 5.0
_DRIFT_FROM_S = 1.0


def _gust(world) -> Callable[[float], np.ndarray]:
    """The world's gust as moving air: a raised cosine of its speed, from its direction, with its downdraft share."""

    direction = math.radians(world.gust_dir_deg)
    side = math.sqrt(max(0.0, 1.0 - world.downdraft_share**2))

    def wind(t: float) -> np.ndarray:
        k = (t - world.gust_start_s) / world.gust_len_s
        speed = world.gust_mps * (1 - math.cos(2 * math.pi * k)) / 2 if 0 < k < 1 else 0.0
        return np.array([speed * side * math.cos(direction), speed * side * math.sin(direction), -speed * world.downdraft_share])

    return wind


class _WeakerMotors:
    """The build's power train with every motor's thrust limit scaled, for a world with weaker motors."""

    def __init__(self, plant, scale: float) -> None:
        self._plant = plant
        self._scale = scale

    def thrust_max(self, v_pack, axial):
        return self._plant.thrust_max(v_pack, axial) * self._scale

    def __getattr__(self, name: str):
        return getattr(self._plant, name)


def nominal_body(frame: dict) -> tuple[float, np.ndarray]:
    """The nominal build's mass and inertia, what the controller assumes in every stress world."""

    flight = _Flight(frame)
    return flight.mass, flight.inertia


def stress_world(frame: dict, gains: dict, world, nominal: tuple[float, np.ndarray] | None = None) -> dict:
    """One randomized world: the drone holds its spot 1 m up for 5 s through the world's gust.

    The plant takes the world's mass and motor strength; the controller only knows the nominal
    build (`nominal_body`) and reads position and velocity with the world's sensor noise.
    Returns the readouts the browser's stress worlds report (drift_m, low_z_m, tail_z_m, crashed).
    """

    mass, inertia = nominal or nominal_body(frame)
    geo = dict(frame["geo"])
    geo["masses"] = [dict(m, mass_g=m["mass_g"] * world.mass_scale) for m in frame["geo"]["masses"]]
    world_frame = dict(frame, geo=geo, t0=frame["t0"] * world.motor_scale, plant=_WeakerMotors(frame["plant"], world.motor_scale))
    ctl = Controller(gains)
    flight = _Flight(world_frame, wind=_gust(world), controller=ctl)
    flight.mass = mass
    flight.inertia = inertia
    flight.k_r, flight.k_w = ctl.rates(inertia, frame["tau"])
    target = np.array([0.0, 0.0, 1.0])
    flight.data.qpos[0:3] = target
    flight.mujoco.mj_forward(flight.model, flight.data)
    steps = round(STRESS_S / DT)
    noise = np.random.default_rng(world.i).normal(0.0, 1.0, (steps, 6)) * world.noise_m * np.array([1, 1, 1, 5, 5, 5])
    drift, low, tail = 0.0, math.inf, math.inf
    trajectory = []
    every = round(0.05 / DT)
    crashed = False
    for step in range(steps):
        true = flight.pos
        flight.step(ctl.hold(target, true + noise[step, :3], flight.vel + noise[step, 3:]))
        true = flight.pos
        if step % every == 0:
            trajectory.append([round(flight.t, 2), *(round(float(v), 3) for v in true)])
        if flight.crashed() or float(np.linalg.norm(true - target)) > 3.0:
            crashed = True
            break
        if flight.t >= _DRIFT_FROM_S:
            drift = max(drift, math.hypot(float(true[0]), float(true[1])))
        if flight.t >= world.gust_start_s:
            low = min(low, float(true[2]))
        if flight.t >= STRESS_S - 0.5:
            tail = min(tail, float(true[2]))
    metrics = {
        "crashed": crashed,
        "drift_m": round(drift, 3),
        "low_z_m": round(low if math.isfinite(low) else 0.0, 3),
        "tail_z_m": round(tail if math.isfinite(tail) else 0.0, 3),
    }
    return {"metrics": metrics, "trajectory": trajectory}
