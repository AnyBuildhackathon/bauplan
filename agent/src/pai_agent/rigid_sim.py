"""MuJoCo tests for any assembly: a push at the top, or a drop onto the floor.

The assembly is one rigid body: its collision shape is the convex hull of every
vertex, its mass and centre of mass come from the CAD masses, the catalog parts and
the external loads, its inertia is that of its bounding box. The body frame is the
assembly frame shifted so the lowest point sits on the floor.

push: the assembly stands on the floor; from 0.5 s to 0.8 s a horizontal force pushes
at the push point, towards the direction it tips most easily. It passes when it ends
within the allowed tilt (default 5 degrees), so it rocked and settled instead of falling.
drop: it falls from a height with a 5 degree tilt; the peak deceleration of its centre
of mass is the drop load in g. It passes when that stays under the limit.
"""

from __future__ import annotations

import math

_DT = 0.001
_PUSH = (0.5, 0.8)
_DURATION = 3.0
_SAMPLE = 0.02


def _tilt_deg(quat) -> float:
    w, x, y, z = (float(v) for v in quat)
    zz = 1.0 - 2.0 * (x * x + y * y)
    return math.degrees(math.acos(max(-1.0, min(1.0, zz))))


def _rotate(quat, vector):
    w, x, y, z = (float(v) for v in quat)
    vx, vy, vz = vector
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty), vy + w * ty + (z * tx - x * tz), vz + w * tz + (x * ty - y * tx))


def _model(points_m: list[tuple[float, float, float]], mass_kg: float, com_m: list[float], size_m: list[float], z0: float, tilt_deg: float) -> str:
    vertex = " ".join(f"{x:.5f} {y:.5f} {z:.5f}" for x, y, z in points_m)
    sx, sy, sz = (max(v, 0.005) for v in size_m)
    ix, iy, iz = mass_kg * (sy**2 + sz**2) / 12, mass_kg * (sx**2 + sz**2) / 12, mass_kg * (sx**2 + sy**2) / 12
    half = math.radians(tilt_deg) / 2
    return f"""
<mujoco model="assembly">
  <compiler inertiafromgeom="false"/>
  <option timestep="{_DT}" gravity="0 0 -9.80665" cone="elliptic" impratio="5"/>
  <asset><mesh name="hull" vertex="{vertex}"/></asset>
  <worldbody>
    <geom name="floor" type="plane" size="3 3 0.1" friction="0.7 0.005 0.0001"/>
    <body name="product" pos="0 0 {z0:.4f}" quat="{math.cos(half):.6f} {math.sin(half):.6f} 0 0">
      <freejoint/>
      <inertial pos="{com_m[0]:.5f} {com_m[1]:.5f} {com_m[2]:.5f}" mass="{mass_kg:.5f}" diaginertia="{ix:.3e} {iy:.3e} {iz:.3e}"/>
      <geom type="mesh" mesh="hull" friction="0.7 0.005 0.0001"/>
    </body>
  </worldbody>
</mujoco>
"""


def _hull_points(points_mm: list, floor_mm: float, limit: int = 6000) -> list[tuple[float, float, float]]:
    import numpy as np

    pts = np.asarray(points_mm, dtype=float) / 1000.0
    pts[:, 2] -= floor_mm / 1000.0
    if len(pts) > limit:
        # The hull only needs the extremes: keep the points farthest out in many directions.
        i = np.arange(2000) + 0.5
        phi = np.arccos(1 - 2 * i / 2000)
        theta = math.pi * (1 + 5**0.5) * i
        directions = np.stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1)
        keep = np.unique(np.argmax((pts - pts.mean(axis=0)) @ directions.T, axis=0))
        pts = pts[keep]
    return [tuple(map(float, p)) for p in pts]


def run(
    points_mm: list,
    floor_mm: float,
    mass_g: float,
    com_mm: list[float],
    size_mm: list[float],
    mode: str,
    force_n: float = 1.0,
    push_point_mm: list[float] | None = None,
    direction: list[float] | None = None,
    drop_height_mm: float = 300.0,
) -> dict:
    import mujoco

    pts = _hull_points(points_mm, floor_mm)
    com = [com_mm[0] / 1000.0, com_mm[1] / 1000.0, (com_mm[2] - floor_mm) / 1000.0]
    size = [v / 1000.0 for v in size_mm]
    drop = mode == "drop"
    z0 = drop_height_mm / 1000.0 if drop else 0.0005
    model = mujoco.MjModel.from_xml_string(_model(pts, mass_g / 1000.0, com, size, z0, 5.0 if drop else 0.0))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "product")
    push_b = (0.0, 0.0, size[2])
    if push_point_mm is not None:
        push_b = (push_point_mm[0] / 1000.0, push_point_mm[1] / 1000.0, (push_point_mm[2] - floor_mm) / 1000.0)
    nx, ny = direction or (0.0, 1.0)
    poses: list[list[float]] = []
    tilt: list[list[float]] = []
    trajectory: list[list[float]] = []
    peak_g = 0.0
    max_tilt = 0.0
    last_vz = 0.0
    every = int(_SAMPLE / _DT)
    for step in range(int(_DURATION / _DT)):
        t = step * _DT
        data.xfrc_applied[body] = 0
        if not drop and _PUSH[0] <= t < _PUSH[1]:
            rel = _rotate(data.xquat[body], push_b)
            point = [data.xpos[body][i] + rel[i] for i in range(3)]
            arm = [point[i] - data.xipos[body][i] for i in range(3)]
            force = (nx * force_n, ny * force_n, 0.0)
            torque = (arm[1] * force[2] - arm[2] * force[1], arm[2] * force[0] - arm[0] * force[2], arm[0] * force[1] - arm[1] * force[0])
            data.xfrc_applied[body] = (*force, *torque)
        mujoco.mj_step(model, data)
        vz = float(data.qvel[2])
        if drop and step > 0:
            peak_g = max(peak_g, (vz - last_vz) / _DT / 9.80665)
        last_vz = vz
        angle = _tilt_deg(data.xquat[body])
        max_tilt = max(max_tilt, angle)
        if step % every == 0:
            pos = [round(float(v), 5) for v in data.xpos[body]]
            quat = [round(float(v), 5) for v in data.xquat[body]]
            poses.append([round(t, 3), *pos, *quat])
            tilt.append([round(t, 3), round(angle, 2)])
            trajectory.append([round(t, 3), *pos])
    final = _tilt_deg(data.xquat[body])
    finite = all(math.isfinite(v) for row in poses for v in row)
    return {
        "finite": finite,
        "final_tilt_deg": round(final, 1),
        "max_tilt_deg": round(max_tilt, 1),
        "peak_g": round(peak_g, 1),
        "poses": poses,
        "tilt": tilt,
        "trajectory": trajectory,
        "push_window_s": list(_PUSH) if not drop else None,
        "push_point_mm": [round(v * 1000.0, 1) for v in push_b] if not drop else None,
        "floor_mm": floor_mm,
    }
