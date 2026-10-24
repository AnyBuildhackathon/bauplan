"""MuJoCo hover test with one gust. Mass and thrust come from the selected parts.

The drone climbs to 0.5 m, then a downdraft pushes on it for 0.3 s. A build with
thrust to spare catches itself; one that already hovers near full throttle sinks.
"""

from __future__ import annotations

import math

from pai_agent.context import Ctx, de
from pai_agent.tools.physics import PhysicsError, compute

_GRAVITY = 9.80665
_DT = 0.001
_DURATION = 4.0
_TARGET_Z = 0.5
_GUST = (1.6, 1.9)
_GUST_DOWN = 0.35
_GUST_SIDE = 0.1


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _roll_pitch(quat: tuple[float, float, float, float]) -> tuple[float, float]:
    w, x, y, z = quat
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    sinp = _clamp(2 * (w * y - z * x), -1.0, 1.0)
    pitch = math.asin(sinp)
    return roll, pitch


def _rotate(quat: tuple[float, float, float, float], vector: tuple[float, float, float]) -> tuple[float, float, float]:
    w, x, y, z = quat
    vx, vy, vz = vector
    tx = 2 * (y * vz - z * vy)
    ty = 2 * (z * vx - x * vz)
    tz = 2 * (x * vy - y * vx)
    cx = y * tz - z * ty
    cy = z * tx - x * tz
    cz = x * ty - y * tx
    return (vx + w * tx + cx, vy + w * ty + cy, vz + w * tz + cz)


def _model_xml(mass_kg: float, inertia: float) -> str:
    return f"""
<mujoco model="whoop">
  <option timestep="{_DT}" gravity="0 0 -{_GRAVITY}" integrator="RK4"/>
  <worldbody>
    <geom name="floor" type="plane" size="2 2 0.1" friction="0.9 0.05 0.01"/>
    <body name="drone" pos="0 0 0.03">
      <freejoint name="root"/>
      <inertial pos="0 0 0" mass="{mass_kg}" diaginertia="{inertia} {inertia} {inertia * 2}"/>
      <geom name="hull" type="box" size="0.02 0.02 0.005" mass="0"/>
    </body>
  </worldbody>
</mujoco>
"""


def run_hover(mass_g: float, thrust_g: float) -> dict:
    import mujoco

    mass_kg = mass_g / 1000.0
    max_thrust_n = thrust_g * 0.001 * _GRAVITY
    inertia = max(2.0e-5, mass_kg * 0.028 * 0.028 / 8.0)
    model = mujoco.MjModel.from_xml_string(_model_xml(mass_kg, inertia))
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    data.qpos[0:3] = (0.0, 0.0, 0.03)
    data.qpos[3:7] = (1.0, 0.0, 0.0, 0.0)
    mujoco.mj_forward(model, data)
    body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "drone")
    weight_n = mass_kg * _GRAVITY
    steps = int(_DURATION / _DT)
    sample_every = int(0.05 / _DT)
    trajectory: list[list[float]] = []

    for step in range(steps):
        quat = (float(data.qpos[3]), float(data.qpos[4]), float(data.qpos[5]), float(data.qpos[6]))
        roll, pitch = _roll_pitch(quat)
        wx, wy, wz = (float(data.qvel[3]), float(data.qvel[4]), float(data.qvel[5]))
        z = float(data.qpos[2])
        vz = float(data.qvel[2])
        thrust = _clamp(weight_n + 0.9 * (_TARGET_Z - z) - 0.55 * vz, 0.0, max_thrust_n)
        roll_tau = _clamp(-0.0016 * roll - 0.00018 * wx, -0.0008, 0.0008)
        pitch_tau = _clamp(-0.0016 * pitch - 0.00018 * wy, -0.0008, 0.0008)
        yaw_tau = _clamp(-0.00008 * wz, -0.0003, 0.0003)
        force = _rotate(quat, (0.0, 0.0, thrust))
        torque = _rotate(quat, (roll_tau, pitch_tau, yaw_tau))
        if _GUST[0] <= step * _DT < _GUST[1]:
            force = (force[0] + _GUST_SIDE * weight_n, force[1], force[2] - _GUST_DOWN * weight_n)
        data.xfrc_applied[body_id] = (*force, *torque)
        mujoco.mj_step(model, data)
        if step % sample_every == 0:
            trajectory.append(
                [
                    round(step * _DT, 3),
                    round(float(data.qpos[0]), 4),
                    round(float(data.qpos[1]), 4),
                    round(float(data.qpos[2]), 4),
                ]
            )

    heights = [point[3] for point in trajectory]
    tail = [point[3] for point in trajectory if point[0] >= _DURATION - 0.5]
    finite = all(math.isfinite(value) for point in trajectory for value in point)
    after_gust = [point[3] for point in trajectory if point[0] >= _GUST[0]]
    settled = bool(tail) and min(tail) >= 0.35 and (max(tail) - min(tail)) <= 0.15
    climbed = bool(heights) and max(heights) >= 0.45
    caught = bool(after_gust) and min(after_gust) >= 0.2
    passed = finite and settled and climbed and caught
    peak = max(heights) if heights else 0.0
    final = heights[-1] if heights else 0.0
    return {
        "result": "pass" if passed else "fail",
        "peak_z_m": round(peak, 4),
        "final_z_m": round(final, 4),
        "gust_low_z_m": round(min(after_gust), 4) if after_gust else 0.0,
        "trajectory": trajectory,
    }


async def simulate_drone(ctx: Ctx, args: dict) -> dict:
    del args
    try:
        metrics = compute(ctx.state)
    except PhysicsError as exc:
        return {"ok": False, "error": str(exc), "detail": str(exc)}

    import asyncio

    outcome = await asyncio.to_thread(run_hover, metrics["weight_g"], metrics["thrust_g"])
    ctx.state.sim_run += 1
    twr = metrics["thrust_to_weight"]
    low_cm = de(outcome["gust_low_z_m"] * 100, 0)
    if outcome["result"] == "pass":
        summary = (
            "Schub-Gewicht "
            + de(twr, 2)
            + ". Sie steigt auf 50 cm und fängt die Böe bei "
            + low_cm
            + " cm ab."
        )
    elif outcome["peak_z_m"] < 0.3:
        summary = "Schub-Gewicht " + de(twr, 2) + ". Zu schwer, sie kommt nicht frei vom Boden."
    else:
        summary = (
            "Schub-Gewicht "
            + de(twr, 2)
            + ". Sie schwebt nur knapp, die Böe drückt sie bis auf "
            + low_cm
            + " cm runter. Keine Schubreserve."
        )
    event = {
        "type": "sim",
        "run": ctx.state.sim_run,
        "result": outcome["result"],
        "summary": summary,
        "trajectory": outcome["trajectory"],
    }
    ctx.state.last_sim = {
        "result": outcome["result"],
        "summary": summary,
        "peak_z_m": outcome["peak_z_m"],
        "final_z_m": outcome["final_z_m"],
        "gust_low_z_m": outcome["gust_low_z_m"],
    }
    await ctx.emit(event)
    detail = "Lauf " + str(ctx.state.sim_run) + ": " + outcome["result"]
    return {
        "ok": True,
        "detail": detail,
        "result": outcome["result"],
        "summary": summary,
        "thrust_to_weight": twr,
        "weight_g": metrics["weight_g"],
        "thrust_g": metrics["thrust_g"],
        "peak_z_m": outcome["peak_z_m"],
        "final_z_m": outcome["final_z_m"],
    }
