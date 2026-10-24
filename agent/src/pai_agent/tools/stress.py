"""Stress test: the best controller flies in 50 randomized MuJoCo worlds.

Each world draws its own mass (+-15 %), motor strength (-25..0 %), a wind gust
of up to 6 m/s with a downdraft share, and sensor noise. The drone takes off,
holds 0.5 m over its start point, and the gust hits it. A world is survived
when it never touches down after take-off, never drifts more than 0.35 m off
its spot, and settles back at height for the last half second.

The controller is a cascaded PD: height and position loops command thrust and a
tilt, the attitude loop turns the tilt into torque. Its gains come from the
training module when that has produced a result (``state.trained_gains`` or the
``gains`` argument); otherwise the default gains below fly.

Worlds run through a ``Rollout``: ``MujocoRollout`` here in the backend. The
browser MuJoCo workers of the training module can take over later by running the
same seeded worlds (every world's parameters go out in the ``stress`` event).
"""

from __future__ import annotations

import asyncio
import math
import random
import re
from dataclasses import asdict, dataclass, fields
from typing import Protocol

from pai_agent.context import Ctx
from pai_agent.tools.physics import PhysicsError, compute

_GRAVITY = 9.80665
_RHO = 1.225
_DT = 0.002
_DURATION = 5.0
_TARGET_Z = 0.5
_SAMPLE_S = 0.05
_MAX_TILT = 0.45
_DRIFT_LIMIT_M = 0.35
_FLOOR_Z = 0.08
# Drag area of a 65 mm whoop: side-on (frame, ducts, props) and from above (prop discs).
_CDA_SIDE = 0.0035
_CDA_TOP = 0.012

WORLDS = 50
SEED = 7


@dataclass(frozen=True)
class ControllerGains:
    """Cascaded PD hover controller. Height and position in 1/s^2 and 1/s, attitude in N m."""

    kp_z: float = 16.0
    kd_z: float = 7.0
    kp_xy: float = 0.64
    kd_xy: float = 0.40
    kp_att: float = 0.0016
    kd_att: float = 0.00018


def gains_from(raw: dict | None) -> ControllerGains:
    """Known keys override the defaults; anything else is ignored."""

    if not isinstance(raw, dict):
        return ControllerGains()
    known = {f.name for f in fields(ControllerGains)}
    picked: dict[str, float] = {}
    for key, value in raw.items():
        if key in known:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and number > 0:
                picked[key] = number
    return ControllerGains(**picked)


@dataclass(frozen=True)
class World:
    i: int
    mass_scale: float
    motor_scale: float
    gust_mps: float
    gust_dir_deg: float
    gust_start_s: float
    gust_len_s: float
    downdraft_share: float
    noise_m: float


def sample_worlds(n: int = WORLDS, seed: int = SEED) -> list[World]:
    rng = random.Random(seed)
    worlds = []
    for i in range(n):
        worlds.append(
            World(
                i=i + 1,
                mass_scale=rng.uniform(0.85, 1.15),
                motor_scale=rng.uniform(0.75, 1.0),
                gust_mps=rng.uniform(0.0, 6.0),
                gust_dir_deg=rng.uniform(0.0, 360.0),
                gust_start_s=rng.uniform(1.6, 2.4),
                gust_len_s=rng.uniform(0.4, 1.0),
                downdraft_share=rng.uniform(0.2, 0.6),
                noise_m=rng.uniform(0.0, 0.02),
            )
        )
    return worlds


class Rollout(Protocol):
    """Flies one world. The browser workers of the training module can implement this too."""

    def run(self, mass_g: float, thrust_g: float, gains: ControllerGains, world: World) -> dict: ...


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _roll_pitch(quat) -> tuple[float, float]:
    w, x, y, z = quat
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(_clamp(2 * (w * y - z * x), -1.0, 1.0))
    return roll, pitch


def _rotate(quat, vector) -> tuple[float, float, float]:
    w, x, y, z = quat
    vx, vy, vz = vector
    tx = 2 * (y * vz - z * vy)
    ty = 2 * (z * vx - x * vz)
    tz = 2 * (x * vy - y * vx)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def _model_xml(mass_kg: float, inertia: float) -> str:
    return f"""
<mujoco model="whoop-stress">
  <option timestep="{_DT}" gravity="0 0 -{_GRAVITY}" integrator="RK4"/>
  <worldbody>
    <geom name="floor" type="plane" size="4 4 0.1" friction="0.9 0.05 0.01"/>
    <body name="drone" pos="0 0 0.03">
      <freejoint name="root"/>
      <inertial pos="0 0 0" mass="{mass_kg}" diaginertia="{inertia} {inertia} {inertia * 2}"/>
      <geom name="hull" type="box" size="0.02 0.02 0.005" mass="0"/>
    </body>
  </worldbody>
</mujoco>
"""


def _gust_speed(world: World, t: float) -> float:
    """A 1-cosine gust: ramps up, peaks halfway, and dies down."""

    k = (t - world.gust_start_s) / world.gust_len_s
    if k <= 0 or k >= 1:
        return 0.0
    return world.gust_mps * 0.5 * (1 - math.cos(2 * math.pi * k))


class MujocoRollout:
    def run(self, mass_g: float, thrust_g: float, gains: ControllerGains, world: World) -> dict:
        import mujoco

        mass_kg = mass_g / 1000.0 * world.mass_scale
        max_thrust_n = thrust_g * 0.001 * _GRAVITY * world.motor_scale
        inertia = max(2.0e-5, mass_kg * 0.028 * 0.028 / 8.0)
        model = mujoco.MjModel.from_xml_string(_model_xml(mass_kg, inertia))
        data = mujoco.MjData(model)
        mujoco.mj_resetData(model, data)
        data.qpos[0:3] = (0.0, 0.0, 0.03)
        data.qpos[3:7] = (1.0, 0.0, 0.0, 0.0)
        mujoco.mj_forward(model, data)
        body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "drone")
        rng = random.Random(world.i * 7919)
        heading = math.radians(world.gust_dir_deg)
        steps = int(_DURATION / _DT)
        every = int(_SAMPLE_S / _DT)
        noise = world.noise_m
        trajectory: list[list[float]] = []
        crashed = False
        drift = 0.0
        low_after_gust = 10.0

        for step in range(steps):
            t = step * _DT
            quat = (float(data.qpos[3]), float(data.qpos[4]), float(data.qpos[5]), float(data.qpos[6]))
            roll, pitch = _roll_pitch(quat)
            x, y, z = float(data.qpos[0]), float(data.qpos[1]), float(data.qpos[2])
            vx, vy, vz = float(data.qvel[0]), float(data.qvel[1]), float(data.qvel[2])
            wx, wy, wz = float(data.qvel[3]), float(data.qvel[4]), float(data.qvel[5])

            # What the flight controller sees: every reading carries noise.
            mx = x + rng.gauss(0, noise)
            my = y + rng.gauss(0, noise)
            mz = z + rng.gauss(0, noise)
            mvx = vx + rng.gauss(0, noise * 5)
            mvy = vy + rng.gauss(0, noise * 5)
            mvz = vz + rng.gauss(0, noise * 5)
            mroll = roll + rng.gauss(0, noise * 0.5)
            mpitch = pitch + rng.gauss(0, noise * 0.5)

            ax = gains.kp_xy * -mx - gains.kd_xy * mvx
            ay = gains.kp_xy * -my - gains.kd_xy * mvy
            pitch_cmd = _clamp(ax, -_MAX_TILT, _MAX_TILT)
            roll_cmd = _clamp(-ay, -_MAX_TILT, _MAX_TILT)
            az = gains.kp_z * (_TARGET_Z - mz) - gains.kd_z * mvz
            tilt = max(0.5, math.cos(mroll) * math.cos(mpitch))
            thrust = _clamp(mass_kg * (_GRAVITY + az) / tilt, 0.0, max_thrust_n)
            roll_tau = _clamp(gains.kp_att * (roll_cmd - mroll) - gains.kd_att * wx, -0.0008, 0.0008)
            pitch_tau = _clamp(gains.kp_att * (pitch_cmd - mpitch) - gains.kd_att * wy, -0.0008, 0.0008)
            yaw_tau = _clamp(-0.00008 * wz, -0.0003, 0.0003)
            force = list(_rotate(quat, (0.0, 0.0, thrust)))
            torque = _rotate(quat, (roll_tau, pitch_tau, yaw_tau))

            gust = _gust_speed(world, t)
            if gust > 0:
                side = gust * math.sqrt(1 - world.downdraft_share**2)
                rel = (side * math.cos(heading) - vx, side * math.sin(heading) - vy, -gust * world.downdraft_share - vz)
                speed_side = math.hypot(rel[0], rel[1])
                force[0] += 0.5 * _RHO * _CDA_SIDE * speed_side * rel[0]
                force[1] += 0.5 * _RHO * _CDA_SIDE * speed_side * rel[1]
                force[2] += 0.5 * _RHO * _CDA_TOP * abs(rel[2]) * rel[2]
            data.xfrc_applied[body] = (*force, *torque)
            mujoco.mj_step(model, data)

            z = float(data.qpos[2])
            if t >= 1.0:
                drift = max(drift, math.hypot(float(data.qpos[0]), float(data.qpos[1])))
                if z < _FLOOR_Z:
                    crashed = True
            if t >= world.gust_start_s:
                low_after_gust = min(low_after_gust, z)
            if step % every == 0:
                trajectory.append([round(t, 3), round(float(data.qpos[0]), 4), round(float(data.qpos[1]), 4), round(z, 4)])

        finite = all(math.isfinite(v) for point in trajectory for v in point)
        tail = [p[3] for p in trajectory if p[0] >= _DURATION - 0.5]
        settled = bool(tail) and min(tail) >= 0.35
        if not finite or crashed:
            reason = "crashed"
        elif drift > _DRIFT_LIMIT_M:
            reason = "drifted"
        elif not settled:
            reason = "sagged"
        else:
            reason = ""
        # 1 is a perfect hover; at 0 or below the world is lost.
        margin = min(1 - drift / _DRIFT_LIMIT_M, (low_after_gust - _FLOOR_Z) / (_TARGET_Z - _FLOOR_Z))
        return {
            "pass": not reason,
            "reason": reason,
            "drift_m": round(drift, 3),
            "low_z_m": round(low_after_gust, 3),
            "margin": round(margin if finite else -1.0, 3),
            "trajectory": trajectory,
        }


def world_row(world: World, outcome: dict) -> dict:
    return {
        "i": world.i,
        "pass": outcome["pass"],
        "reason": outcome["reason"],
        "mass_pct": round((world.mass_scale - 1) * 100, 1),
        "motor_pct": round((world.motor_scale - 1) * 100, 1),
        "gust_mps": round(world.gust_mps, 2),
        "downdraft_pct": round(world.downdraft_share * 100),
        "noise_cm": round(world.noise_m * 100, 2),
        "drift_m": outcome["drift_m"],
        "low_z_m": outcome["low_z_m"],
        "margin": outcome["margin"],
    }


# How hard each randomized factor pushed a world, 0 (mild) to 1 (the worst draw).
_SEVERITY = {
    "gust": lambda r: r["gust_mps"] / 6.0,
    "motor": lambda r: -r["motor_pct"] / 25.0,
    "mass": lambda r: (r["mass_pct"] + 15) / 30.0,
    "noise": lambda r: r["noise_cm"] / 2.0,
}


def weakest_point(rows: list[dict]) -> tuple[str | None, str]:
    """The factor that separates lost worlds from survived ones, as one plain sentence."""

    lost = [r for r in rows if not r["pass"]]
    if not rows:
        return None, "No worlds were flown."
    if not lost:
        closest = min(rows, key=lambda r: r["margin"])
        return None, (
            f"It survived all {len(rows)} worlds; the closest call was a {closest['gust_mps']:.1f} m/s gust "
            f"with motors {abs(closest['motor_pct']):.0f} % weak, where it drifted {closest['drift_m'] * 100:.0f} cm."
        )
    kept = [r for r in rows if r["pass"]] or rows

    def mean(group: list[dict], key: str) -> float:
        return sum(_SEVERITY[key](r) for r in group) / len(group)

    key = max(_SEVERITY, key=lambda k: mean(lost, k) - mean(kept, k))
    worst = min(lost, key=lambda r: r["margin"])
    if key == "gust":
        floor = min(r["gust_mps"] for r in lost)
        sentence = f"Gusts are the weak point: from {floor:.1f} m/s on, the wind pushes it more than {_DRIFT_LIMIT_M * 100:.0f} cm off its spot."
    elif key == "motor":
        sentence = (
            f"Thrust reserve is the weak point: with motors {abs(worst['motor_pct']):.0f} % weaker, "
            f"a {worst['gust_mps']:.1f} m/s gust is more than it can fight."
        )
    elif key == "mass":
        sentence = f"Weight is the weak point: {worst['mass_pct']:+.0f} % mass leaves too little thrust to catch the gust."
    else:
        sentence = f"Sensor noise is the weak point: at {worst['noise_cm']:.1f} cm of jitter the position hold starts to wander."
    return key, sentence


def trained_gains(state, override: dict | None) -> tuple[ControllerGains, str]:
    """The gains to stress: the tool argument, then the training result, else the defaults."""

    if isinstance(override, dict) and override:
        return gains_from(override), "trained"
    trained = getattr(state, "trained_gains", None)
    if isinstance(trained, dict) and trained:
        return gains_from(trained), "trained"
    return ControllerGains(), "default"


def _bounded_int(value, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


async def stress_test(ctx: Ctx, args: dict, rollout: Rollout | None = None) -> dict:
    try:
        metrics = compute(ctx.state)
    except PhysicsError as exc:
        message = "Build the drone first: " + str(exc)
        return {"ok": False, "error": message, "detail": message}

    total = _bounded_int(args.get("worlds"), WORLDS, 5, 200)
    seed = _bounded_int(args.get("seed"), SEED, 0, 1_000_000)
    gains, policy = trained_gains(ctx.state, args.get("gains"))
    runner = rollout or MujocoRollout()
    worlds = sample_worlds(total, seed)
    run = getattr(ctx.state, "stress_run", 0) + 1
    ctx.state.stress_run = run
    base = {
        "type": "stress",
        "run": run,
        "total": total,
        "seed": seed,
        "policy": policy,
        "gains": asdict(gains),
        "weight_g": metrics["weight_g"],
        "thrust_to_weight": metrics["thrust_to_weight"],
    }
    rows: list[dict] = []
    trajectories: dict[int, list] = {}
    await ctx.emit({**base, "status": "running", "done": 0, "survived": 0, "worlds": [], "worst": None, "weakest": None, "explanation": ""})
    chunk = 5
    for start in range(0, total, chunk):
        batch = worlds[start : start + chunk]
        outcomes = await asyncio.to_thread(
            lambda b=batch: [runner.run(metrics["weight_g"], metrics["thrust_g"], gains, w) for w in b]
        )
        for world, outcome in zip(batch, outcomes):
            rows.append(world_row(world, outcome))
            trajectories[world.i] = outcome["trajectory"]
        survived = sum(1 for r in rows if r["pass"])
        await ctx.emit({**base, "status": "running", "done": len(rows), "survived": survived, "worlds": rows, "worst": None, "weakest": None, "explanation": ""})
        await ctx.emit({"type": "tool", "name": "stress_test", "status": "running", "detail": f"World {len(rows)}/{total} · {survived} survived"})

    survived = sum(1 for r in rows if r["pass"])
    worst_row = min(rows, key=lambda r: r["margin"])
    weakest, explanation = weakest_point(rows)
    worst = {**worst_row, "trajectory": trajectories[worst_row["i"]]}
    await ctx.emit({**base, "status": "done", "done": total, "survived": survived, "worlds": rows, "worst": worst, "weakest": weakest, "explanation": explanation})
    ctx.state.last_stress = {"survived": survived, "total": total, "weakest": weakest, "explanation": explanation, "policy": policy}
    return {
        "ok": True,
        "detail": f"Survived {survived}/{total}",
        "survived": survived,
        "total": total,
        "policy": policy,
        "weakest": weakest,
        "explanation": explanation,
        "worst_world": {k: v for k, v in worst_row.items() if k != "margin"},
    }


STRESS_REQUEST = re.compile(r"\bstress|\brobust|\bstresstest|\bbelast", re.IGNORECASE)


async def run_stress_mock(ctx: Ctx) -> None:
    """'Stress test it' without a key: the same tool, with Bolzen's lines around it."""

    from pai_agent.tools.registry import call_tool

    if not ctx.state.selected:
        await call_tool(ctx, "mascot_say", {"state": "besorgt", "say": "There is nothing to stress yet. Build the drone first."})
        await ctx.chat("agent", "There is no drone to stress test yet. Let the kickoff build v1 first, then ask again.")
        return
    gains, policy = trained_gains(ctx.state, None)
    del gains
    source = "the trained controller" if policy == "trained" else "the default controller gains (no training result yet)"
    await call_tool(ctx, "mascot_say", {"state": "denkt", "say": "Fifty randomized worlds. Let's shake it."})
    await ctx.chat(
        "agent",
        "Stress test with " + source + ": 50 MuJoCo worlds, each with its own mass (±15 %), motor strength (−25…0 %), "
        "a gust of up to 6 m/s, and sensor noise.",
    )
    result = await call_tool(ctx, "stress_test", {})
    if result.get("ok") is False:
        await call_tool(ctx, "mascot_say", {"state": "besorgt", "say": "The stress test fell over."})
        await ctx.chat("agent", "The stress test failed: " + str(result.get("error")))
        return
    survived, total = result["survived"], result["total"]
    state = "freut_sich" if survived == total else "erklaert" if survived >= total * 0.9 else "besorgt"
    await call_tool(ctx, "mascot_say", {"state": state, "say": result["explanation"]})
    await ctx.chat("agent", f"Survived {survived}/{total}. " + result["explanation"])
