// The drone as a training product: a free body with four filtered thrust motors in X,
// built from the backend's parts and masses. Trained: the cascaded PD hover gains.
import type { MjData, MjModel } from "@mujoco/mujoco";
import type { Episode, Params, Perturbation, TrainingProduct } from "./types";

/** What the backend sends in the `training` event (`spec`). */
export interface DroneSpec {
  product: "drone";
  label?: string;
  nominal?: boolean;
  mass_g: number;
  /** Total maximum thrust of all motors, grams-force. */
  thrust_g: number;
  motors: number;
  arm_length_mm: number;
  parts?: { category: string; name: string; qty: number; mass_g: number }[];
}

const G = 9.80665;
const DT = 0.002;
const HORIZON_S = 10;
export const DRONE_TARGET: [number, number, number] = [0, 0, 1];
const START: [number, number, number] = [0.35, -0.25, 0.55];
const START_TILT: [number, number] = [0.3, -0.2];
const GUST = { from: 4, to: 4.6, weights: 0.15 };
// Propeller drag torque per newton of thrust (m). Diagonal motors spin the same way.
const YAW_K = 0.008;
const MOTOR_TAU_S = 0.03;
const SETTLE_S = 2;

function dims(spec: DroneSpec) {
  const mass = Math.max(0.005, spec.mass_g / 1000);
  const arm = Math.max(0.01, spec.arm_length_mm / 1000);
  const d = arm / Math.SQRT2;
  const ixx = Math.max(2e-6, (mass * arm * arm) / 4);
  const fmax = (spec.thrust_g / 1000) * G / Math.max(1, spec.motors);
  return { mass, arm, d, ixx, izz: 2 * ixx, fmax };
}

function buildMjcf(spec: DroneSpec): string {
  const { mass, arm, d, ixx, izz, fmax } = dims(spec);
  const motor = (name: string, x: number, y: number, spin: number) =>
    `<site name="${name}" pos="${x.toFixed(4)} ${y.toFixed(4)} 0" size="0.004"/>` +
    `<geom type="cylinder" pos="${x.toFixed(4)} ${y.toFixed(4)} 0.006" size="${(arm * 0.55).toFixed(4)} 0.001" mass="0" rgba="0.5 0.5 0.6 0.3" contype="0" conaffinity="0"/>` +
    `<!-- spin ${spin} -->`;
  const sites = [motor("m_fl", d, d, 1), motor("m_fr", d, -d, -1), motor("m_rl", -d, d, -1), motor("m_rr", -d, -d, 1)].join("\n        ");
  const act = (name: string, spin: number) =>
    `<general site="${name}" gear="0 0 1 0 0 ${(spin * YAW_K).toFixed(4)}" dyntype="filter" dynprm="${MOTOR_TAU_S}" gainprm="1" biasprm="0 0 0" ctrllimited="true" ctrlrange="0 ${fmax.toFixed(5)}"/>`;
  return `<mujoco model="anybuild_drone">
  <option timestep="${DT}" gravity="0 0 -${G}" integrator="RK4"/>
  <worldbody>
    <geom name="floor" type="plane" size="4 4 0.1" friction="0.9 0.05 0.01"/>
    <body name="drone" pos="${START.join(" ")}">
      <freejoint name="root"/>
      <inertial pos="0 0 0" mass="${mass.toFixed(5)}" diaginertia="${ixx.toExponential(4)} ${ixx.toExponential(4)} ${izz.toExponential(4)}"/>
      <geom name="hull" type="box" size="${(arm * 0.4).toFixed(4)} ${(arm * 0.4).toFixed(4)} 0.006" mass="0" friction="0.9 0.05 0.01"/>
      ${sites}
    </body>
  </worldbody>
  <actuator>
    ${act("m_fl", 1)}
    ${act("m_fr", -1)}
    ${act("m_rl", -1)}
    ${act("m_rr", 1)}
  </actuator>
</mujoco>`;
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Seeded uniform [0, 1). */
export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function euler(qw: number, qx: number, qy: number, qz: number) {
  const roll = Math.atan2(2 * (qw * qx + qy * qz), 1 - 2 * (qx * qx + qy * qy));
  const pitch = Math.asin(clamp(2 * (qw * qy - qz * qx), -1, 1));
  const yaw = Math.atan2(2 * (qw * qz + qx * qy), 1 - 2 * (qy * qy + qz * qz));
  return { roll, pitch, yaw };
}

function episode(params: Params, p: Perturbation, spec: DroneSpec): Episode {
  const { d, mass, ixx, izz } = dims(spec);
  const massScale = p.mass_scale ?? 1;
  const m = mass * massScale;
  const ix = ixx * massScale;
  const iz = izz * massScale;
  const rnd = mulberry32(p.seed ?? 1);
  const offset = p.init_offset ?? [0, 0, 0];
  const tilt = p.init_tilt ?? START_TILT;
  const wind = p.wind_n ?? [0, 0, 0];
  const gustScale = p.gust_scale ?? 1;
  // The gust comes from a random side, so a controller cannot overfit one direction.
  const gustAngle = rnd() * Math.PI * 2;
  const gustN = GUST.weights * m * G * gustScale;
  const [kpZ, kdZ, kpXY, kdXY, kpA, kdA] = [params.kp_z, params.kd_z, params.kp_xy, params.kd_xy, params.kp_att, params.kd_att];
  let err2 = 0;
  let errN = 0;
  let maxTilt = 0;
  let crashedAt = -1;
  let lastT = 0;
  let cost = 0;

  return {
    start(_model: MjModel, data: MjData) {
      const qpos = data.qpos;
      qpos[0] = START[0] + offset[0];
      qpos[1] = START[1] + offset[1];
      qpos[2] = START[2] + offset[2];
      const [r, pi] = tilt;
      const cr = Math.cos(r / 2), sr = Math.sin(r / 2), cp = Math.cos(pi / 2), sp = Math.sin(pi / 2);
      qpos[3] = cr * cp;
      qpos[4] = sr * cp;
      qpos[5] = cr * sp;
      qpos[6] = -sr * sp;
    },
    control(_model: MjModel, data: MjData, t: number) {
      const q = data.qpos;
      const v = data.qvel;
      const { roll, pitch, yaw } = euler(q[3], q[4], q[5], q[6]);
      const ax = kpXY * (DRONE_TARGET[0] - q[0]) - kdXY * v[0];
      const ay = kpXY * (DRONE_TARGET[1] - q[1]) - kdXY * v[1];
      const az = kpZ * (DRONE_TARGET[2] - q[2]) - kdZ * v[2];
      const cy = Math.cos(yaw), sy = Math.sin(yaw);
      const axb = cy * ax + sy * ay;
      const ayb = -sy * ax + cy * ay;
      const pitchDes = clamp(axb / G, -0.6, 0.6);
      const rollDes = clamp(-ayb / G, -0.6, 0.6);
      const tiltCos = Math.max(0.5, Math.cos(roll) * Math.cos(pitch));
      const thrust = Math.max(0, (m * (G + az)) / tiltCos);
      const tx = ix * (kpA * (rollDes - roll) - kdA * v[3]);
      const ty = ix * (kpA * (pitchDes - pitch) - kdA * v[4]);
      const tz = iz * (4 * (0 - yaw) - 1.5 * v[5]);
      const c = data.ctrl;
      const a = thrust / 4, bx = tx / (4 * d), by = ty / (4 * d), bz = tz / (4 * YAW_K);
      c[0] = a + bx - by + bz;
      c[1] = a - bx - by - bz;
      c[2] = a + bx + by - bz;
      c[3] = a - bx + by + bz;
      const f = data.xfrc_applied;
      const gust = t >= GUST.from && t < GUST.to ? gustN : 0;
      f[6] = wind[0] + gust * Math.cos(gustAngle);
      f[7] = wind[1] + gust * Math.sin(gustAngle);
      f[8] = wind[2];
    },
    observe(_model: MjModel, data: MjData, t: number) {
      const q = data.qpos;
      const ex = q[0] - DRONE_TARGET[0], ey = q[1] - DRONE_TARGET[1], ez = q[2] - DRONE_TARGET[2];
      const e = Math.sqrt(ex * ex + ey * ey + ez * ez);
      const { roll, pitch } = euler(q[3], q[4], q[5], q[6]);
      const tiltNow = Math.acos(clamp(Math.cos(roll) * Math.cos(pitch), -1, 1));
      lastT = t;
      cost += (Math.min(e, 2) + 0.15 * tiltNow) * DT;
      if (t >= SETTLE_S) {
        err2 += e * e;
        errN += 1;
        maxTilt = Math.max(maxTilt, tiltNow);
      }
      const bad = !Number.isFinite(e) || q[2] < 0.03 || tiltNow > 1.4 || e > 3;
      if (bad) {
        crashedAt = t;
        return false;
      }
      return true;
    },
    frame(data: MjData, out: Float32Array, o: number) {
      const q = data.qpos;
      for (let i = 0; i < 7; i++) out[o + i] = q[i];
    },
    finish() {
      const crashed = crashedAt >= 0;
      // A crash costs the rest of the episode as if it sat 2 m off the target.
      const total = cost + (crashed ? (HORIZON_S - lastT) * 2.3 : 0);
      const meanCost = total / HORIZON_S;
      const score = 100 / (1 + 6 * meanCost);
      const rms = errN > 0 ? Math.sqrt(err2 / errN) : 2;
      return {
        score,
        metrics: {
          rms_error_cm: Math.round(rms * 1000) / 10,
          max_tilt_deg: Math.round((maxTilt * 180) / Math.PI * 10) / 10,
          survived_s: Math.round((crashed ? crashedAt : HORIZON_S) * 100) / 100,
          crashed,
          held: !crashed && rms < 0.1,
        },
      };
    },
  };
}

export const droneProduct: TrainingProduct<DroneSpec> = {
  id: "drone",
  label: "Hover controller",
  goal: "Stay level and hold position for 10 s, with a gust from a random side",
  params: [
    { name: "kp_z", label: "Altitude P", min: 0.5, max: 40, init: 1.2, log: true, unit: "1/s²" },
    { name: "kd_z", label: "Altitude D", min: 0.2, max: 15, init: 0.4, log: true, unit: "1/s" },
    { name: "kp_xy", label: "Position P", min: 0.1, max: 15, init: 0.25, log: true, unit: "1/s²" },
    { name: "kd_xy", label: "Position D", min: 0.1, max: 10, init: 0.2, log: true, unit: "1/s" },
    { name: "kp_att", label: "Attitude P", min: 5, max: 1500, init: 12, log: true, unit: "1/s²" },
    { name: "kd_att", label: "Attitude D", min: 0.5, max: 80, init: 1.2, log: true, unit: "1/s" },
  ],
  horizonS: HORIZON_S,
  frameSize: 7,
  frameHz: 20,
  buildMjcf,
  episode,
};
