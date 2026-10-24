"""Run inside an isolated uploaded job directory, using the setup.sh environment.

The exported product is a single rigid assembly for tests.
Training uses Isaac Lab's reference Crazyflie, not the exported product.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

TASK = "Isaac-Quadcopter-Direct-v0"


def train(request: dict) -> dict:
    params = request["parameters"]
    script = Path.home() / "IsaacLab/scripts/reinforcement_learning/rsl_rl/train.py"
    # cwd keeps logs, videos and checkpoints isolated to this job.
    subprocess.run([
        sys.executable, str(script), "--task", TASK, "--headless", "--video",
        "--video_length", "200", "--video_interval", "1000", "--seed", "42",
        "--num_envs", str(params["num_envs"]), "--max_iterations", str(params["iterations"]),
    ], check=True)
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

    curve = []
    for event_file in sorted(Path("logs").rglob("events.out.tfevents.*")):
        accumulator = EventAccumulator(str(event_file), size_guidance={"scalars": 0})
        accumulator.Reload()
        tags = accumulator.Tags().get("scalars", [])
        tag = next((t for t in ("Train/mean_reward", "Train/mean_reward/time", "Episode/rew_total") if t in tags), None)
        if tag:
            curve = [[int(event.step), float(event.value)] for event in accumulator.Scalars(tag)]
    if not curve:
        raise RuntimeError("Training produced no reward curve.")
    videos = sorted(Path("logs").rglob("*.mp4"))
    if not videos:
        raise RuntimeError("Training produced no video.")
    shutil.copyfile(videos[-1], "result.mp4")
    return {"task": TASK, "curve": curve,
            "metrics": {"final_reward": curve[-1][1], "iterations": params["iterations"], "parallel_envs": params["num_envs"]},
            "detail": "Isaac Lab reference Crazyflie training. The recording is a training rollout, not a product certification.",
            "parameters": params, "product_tested": False}


def test(request: dict) -> dict:
    # Kit must start before importing simulation, PhysX or USD modules.
    from isaaclab.app import AppLauncher

    launcher = AppLauncher(headless=True, enable_cameras=True)
    app = launcher.app
    try:
        return _simulate(request)
    finally:
        app.close()


def _simulate(request: dict) -> dict:
    import imageio.v2 as imageio
    import numpy as np
    import torch
    from pxr import Usd, UsdPhysics
    import isaaclab.sim as sim_utils
    from isaaclab.assets import RigidObject, RigidObjectCfg
    from isaaclab.sensors import Camera, CameraCfg
    from isaaclab.utils.math import quat_apply_inverse
    from isaacsim.core.utils.stage import get_current_stage

    params, product = request["parameters"], request["product"]
    mass = product["mass_kg"] + params["payload_g"] / 1000
    max_thrust = product["max_thrust_n"]
    dt = 1 / 120
    sim = sim_utils.SimulationContext(sim_utils.SimulationCfg(dt=dt, device="cuda:0", render_interval=4))
    sim_utils.GroundPlaneCfg().func("/World/Ground", sim_utils.GroundPlaneCfg())
    sim_utils.DomeLightCfg(intensity=1800).func("/World/Light", sim_utils.DomeLightCfg(intensity=1800))
    robot = RigidObject(RigidObjectCfg(
        prim_path="/World/Product", spawn=sim_utils.UsdFileCfg(
            usd_path=str(Path("product.usda").resolve()),
            mass_props=sim_utils.MassPropertiesCfg(mass=mass),
        ), init_state=RigidObjectCfg.InitialStateCfg(pos=(0.0, 0.0, 0.5)),
    ))
    # One dynamic body with convex collision meshes, no nested rigid bodies.
    stage = get_current_stage()
    for prim in Usd.PrimRange(stage.GetPrimAtPath("/World/Product")):
        if prim.GetTypeName() == "Mesh":
            UsdPhysics.CollisionAPI.Apply(prim)
            UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr("convexHull")
    camera = Camera(CameraCfg(
        prim_path="/World/Camera", update_period=4 * dt, height=360, width=640,
        data_types=["rgb"], spawn=sim_utils.PinholeCameraCfg(
            focal_length=18.0, focus_distance=2.0, clipping_range=(0.01, 100.0)),
    ))
    sim.reset()
    camera.set_world_poses_from_view(
        torch.tensor([[0.65, 0.65, 0.85]], device=sim.device),
        torch.tensor([[0.0, 0.0, 0.45]], device=sim.device),
    )
    for _ in range(12):
        sim.step()
        camera.update(dt, force_recompute=True)
    positions, angles = [], []
    forces = torch.zeros((1, 1, 3), device=sim.device)
    torques = torch.zeros_like(forces)
    target = torch.tensor([[0.0, 0.0, 0.5]], device=sim.device)
    # Declared approximation: quadratic drag with a constant projected area and Cd.
    area = max(0.001, (product["arm_mm"] * 0.002) ** 2 * 0.35)
    first_failure_wind = None
    with imageio.get_writer("result.mp4", fps=30, codec="libx264", macro_block_size=2) as writer:
        for step in range(round(params["duration_s"] / dt)):
            t = step * dt
            robot.update(dt)
            data = robot.data
            position, velocity = data.root_pos_w, data.root_lin_vel_w
            # PD position and attitude control with thrust limited by selected motors.
            desired_accel = 12 * (target - position) - 4 * velocity
            desired_accel[:, 2] += 9.81
            wind = params["wind_m_s"] * min(1.0, max(0.0, (t - 1) / 2)) * (0.75 + 0.25 * math.sin(7 * t))
            drag = 0.5 * 1.225 * 1.1 * area * (wind - float(velocity[0, 0])) * abs(wind - float(velocity[0, 0]))
            body_accel = quat_apply_inverse(data.root_quat_w, desired_accel)
            thrust = torch.clamp(mass * body_accel[:, 2], 0, max_thrust)
            forces.zero_()
            torques.zero_()
            forces[:, 0, 2] = thrust
            # Wind acts in world X; convert it to body coordinates.
            wind_world = torch.tensor([[drag, 0.0, 0.0]], device=sim.device)
            forces[:, 0, :] += quat_apply_inverse(data.root_quat_w, wind_world)
            # Desired tilt follows horizontal acceleration. Body axes use Z up.
            gravity = data.projected_gravity_b
            torques[:, 0, 0] = 0.003 * (gravity[:, 1] - desired_accel[:, 1] / 9.81)
            torques[:, 0, 1] = 0.003 * (desired_accel[:, 0] / 9.81 - gravity[:, 0])
            torques[:, 0, :] -= 0.00015 * data.root_ang_vel_b
            torques.clamp_(-0.003, 0.003)
            robot.set_external_force_and_torque(forces, torques)
            robot.write_data_to_sim()
            sim.step()
            camera.update(dt)
            robot.update(dt)
            p = robot.data.root_pos_w[0].cpu().numpy()
            tilt = math.degrees(math.acos(float(torch.clamp(-robot.data.projected_gravity_b[0, 2], -1, 1))))
            if not np.isfinite(p).all() or not math.isfinite(tilt):
                raise RuntimeError("PhysX returned non-finite state.")
            positions.append(p)
            angles.append(tilt)
            if first_failure_wind is None and (p[2] < 0.15 or tilt > 45):
                first_failure_wind = wind
            if step % 4 == 0:
                frame = camera.data.output["rgb"][0, :, :, :3].cpu().numpy()
                writer.append_data(frame)
    position_array = np.asarray(positions)
    error = position_array[:, 2] - 0.5
    drift = np.linalg.norm(position_array[:, :2], axis=1)
    passed = bool(position_array[:, 2].min() >= 0.15 and max(angles) < 45 and drift.max() < 0.5)
    metrics = {"hover_rmse_m": float(np.sqrt(np.mean(error ** 2))), "max_tilt_deg": max(angles),
               "max_drift_m": float(drift.max()), "min_altitude_m": float(position_array[:, 2].min()),
               "total_mass_g": mass * 1000, "peak_wind_m_s": params["wind_m_s"], "payload_g": params["payload_g"]}
    if first_failure_wind is not None:
        metrics["first_failure_wind_m_s"] = first_failure_wind
    return {"parameters": params, "metrics": metrics, "curve": [], "passed": passed,
            "detail": "Product hover test with PD control, quadratic drag and centred payload mass. Aerodynamics and camera geometry are approximations.",
            "product_tested": True}


def main():
    request = json.loads(Path("request.json").read_text())
    mode = request["mode"]
    result = train(request) if mode == "train" else test(request)
    result.update({"mode": mode, "status": "done", "source": "live", "engine": "Isaac Lab" if mode == "train" else "Isaac Sim"})
    Path("result.json").write_text(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
