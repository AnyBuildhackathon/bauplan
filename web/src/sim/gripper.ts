// The two-finger gripper as a training product: the grip test of agent/src/pai_agent/grip_sim.py
// (squeeze, lift 15 cm, shake about 0.4 g, hold), with the grasp itself trained:
// how hard to squeeze, how fast to ramp, how long to settle, and how fast to lift.
import type { MjData, MjModel } from "@mujoco/mujoco";
import type { Episode, Params, Perturbation, TrainingProduct } from "./types";

/** What the backend sends in the `training` event (`spec`) for a gripper. */
export interface GripperSpec {
  product: "gripper";
  label?: string;
  nominal?: boolean;
  payload_g: number;
  width_mm: number;
  /** Finger force the servo can hold, per pad, newtons. */
  max_force_n: number;
  friction: number;
  parts?: { category: string; name: string; qty: number; mass_g: number }[];
}

const G = 9.80665;
const DT = 0.001;
const HORIZON_S = 3.6;
const LIFT_M = 0.15;
const SHAKE_M = 0.015;
const SHAKE_HZ = 2.5;
const SHAKE_S = 0.8;
const BASE_HAND = 0.08;
const SLIP_LIMIT_M = 0.01;
const DROP_M = 0.05;

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

function buildMjcf(spec: GripperSpec): string {
  const mass = Math.max(0.005, spec.payload_g / 1000);
  const halfW = Math.max(0.005, spec.width_mm / 2000);
  const mu = clamp(spec.friction, 0.05, 2);
  const fmax = Math.max(0.1, spec.max_force_n);
  return `<mujoco model="anybuild_grip">
  <option timestep="${DT}" gravity="0 0 -${G}" cone="elliptic" impratio="10" noslip_iterations="4"/>
  <worldbody>
    <geom name="floor" type="plane" size="1 1 0.1" friction="0.5 0.005 0.0001"/>
    <body name="object" pos="0 0 0.06">
      <freejoint/>
      <geom name="object" type="box" size="${halfW.toFixed(4)} 0.025 0.06" mass="${mass.toFixed(4)}" friction="${mu} 0.005 0.0001"/>
    </body>
    <body name="hand" pos="0 0 ${BASE_HAND}" gravcomp="1">
      <joint name="lift" type="slide" axis="0 0 1" damping="40"/>
      <geom type="box" size="${(halfW + 0.03).toFixed(4)} 0.03 0.004" pos="0 0 0.05" mass="0.3" contype="0" conaffinity="0"/>
      <body name="pad_l" pos="${(-halfW - 0.004).toFixed(4)} 0 0" gravcomp="1">
        <joint name="pad_l" type="slide" axis="1 0 0" range="-0.03 0.03" damping="2"/>
        <geom type="box" size="0.003 0.015 0.02" mass="0.01" friction="${mu} 0.005 0.0001"/>
      </body>
      <body name="pad_r" pos="${(halfW + 0.004).toFixed(4)} 0 0" gravcomp="1">
        <joint name="pad_r" type="slide" axis="1 0 0" range="-0.03 0.03" damping="2"/>
        <geom type="box" size="0.003 0.015 0.02" mass="0.01" friction="${mu} 0.005 0.0001"/>
      </body>
    </body>
  </worldbody>
  <actuator>
    <motor joint="pad_l" gear="1" ctrllimited="true" ctrlrange="0 ${fmax.toFixed(3)}"/>
    <motor joint="pad_r" gear="-1" ctrllimited="true" ctrlrange="0 ${fmax.toFixed(3)}"/>
    <position joint="lift" kp="20000" ctrllimited="true" ctrlrange="-1 1"/>
  </actuator>
</mujoco>`;
}

/** Timeline of one grasp: squeeze ramp, settle, lift, a short hold, the shake, then hold. */
function timeline(params: Params) {
  const ramp = params.ramp_s;
  const liftAt = ramp + params.settle_s;
  const liftEnd = liftAt + params.lift_s;
  const shakeAt = liftEnd + 0.2;
  return { ramp, liftAt, liftEnd, shakeAt, shakeEnd: shakeAt + SHAKE_S };
}

function handZ(t: number, tl: ReturnType<typeof timeline>): number {
  if (t < tl.liftAt) return 0;
  if (t < tl.liftEnd) return (LIFT_M * (1 - Math.cos((Math.PI * (t - tl.liftAt)) / (tl.liftEnd - tl.liftAt)))) / 2;
  if (t >= tl.shakeAt && t < tl.shakeEnd) return LIFT_M + SHAKE_M * Math.sin(2 * Math.PI * SHAKE_HZ * (t - tl.shakeAt));
  return LIFT_M;
}

// Body ids follow the MJCF order: world 0, object 1, hand 2, pad_l 3, pad_r 4.
const OBJ = 1, HAND = 2, PAD_L = 3, PAD_R = 4;

function episode(params: Params, p: Perturbation, spec: GripperSpec): Episode {
  const tl = timeline(params);
  const fmax = Math.max(0.1, spec.max_force_n);
  const force = clamp(params.squeeze, 0, 1) * fmax;
  const gust = p.gust_scale ?? 1;
  let objZ0 = 0;
  let maxSlip = 0;
  let finalSlip = 0;
  let dropped = false;
  return {
    start(_model: MjModel, data: MjData) {
      const q = data.qpos;
      const o = p.init_offset ?? [0, 0, 0];
      q[0] += o[0];
      q[1] += o[1];
      q[2] += Math.max(0, o[2]);
    },
    control(_model: MjModel, data: MjData, t: number) {
      const c = data.ctrl;
      const squeeze = Math.min(1, t / Math.max(0.01, tl.ramp)) * force;
      c[0] = squeeze;
      c[1] = squeeze;
      // A gust scale above 1 makes the shake harder; 0 drops it.
      const z = handZ(t, tl);
      c[2] = z > LIFT_M ? LIFT_M + (z - LIFT_M) * gust : z;
      const wind = p.wind_n;
      if (wind) {
        const f = data.xfrc_applied;
        f[OBJ * 6] = wind[0];
        f[OBJ * 6 + 1] = wind[1];
        f[OBJ * 6 + 2] = wind[2];
      }
    },
    observe(_model: MjModel, data: MjData, t: number) {
      const x = data.xpos;
      if (objZ0 === 0) objZ0 = x[OBJ * 3 + 2];
      const lifted = x[HAND * 3 + 2] - BASE_HAND;
      const rise = x[OBJ * 3 + 2] - objZ0;
      finalSlip = lifted - rise;
      if (t >= tl.liftAt) maxSlip = Math.max(maxSlip, finalSlip);
      if (!Number.isFinite(finalSlip)) return false;
      if (t > tl.liftEnd && finalSlip > DROP_M) {
        dropped = true;
        return false;
      }
      return true;
    },
    frame(data: MjData, out: Float32Array, o: number) {
      const x = data.xpos;
      out[o] = x[HAND * 3 + 2] - BASE_HAND;
      out[o + 1] = x[OBJ * 3 + 2] - (objZ0 || x[OBJ * 3 + 2]);
      out[o + 2] = x[PAD_L * 3];
      out[o + 3] = x[PAD_R * 3];
      out[o + 4] = x[OBJ * 3];
    },
    finish() {
      const slipMm = Math.max(0, maxSlip) * 1000;
      const held = !dropped && maxSlip <= SLIP_LIMIT_M;
      const cycle = tl.liftEnd;
      // Holding is the gate. A held grasp then scores for little force (servo heat, fragile parts),
      // a short cycle and little slip; a slipping one stays below every held one.
      const f = clamp(params.squeeze, 0, 1);
      const speed = 1 - 0.25 * clamp((cycle - 0.3) / 2, 0, 1);
      const score = dropped
        ? 4
        : held
          ? 100 * (1 - 0.6 * f) * speed * (1 - (0.3 * slipMm) / (SLIP_LIMIT_M * 1000))
          : 25 * Math.exp(-(slipMm - SLIP_LIMIT_M * 1000) / 20) * speed;
      return {
        score,
        metrics: {
          slip_mm: Math.round(slipMm * 10) / 10,
          force_n: Math.round(force * 100) / 100,
          cycle_s: Math.round(cycle * 100) / 100,
          crashed: dropped,
          held,
        },
      };
    },
  };
}

function exportGains(params: Params, spec: GripperSpec): Record<string, unknown> {
  const tl = timeline(params);
  return {
    squeeze: Number(params.squeeze.toPrecision(3)),
    grip_force_n: Number((clamp(params.squeeze, 0, 1) * spec.max_force_n).toPrecision(3)),
    ramp_ms: Math.round(params.ramp_s * 1000),
    settle_ms: Math.round(params.settle_s * 1000),
    lift_ms: Math.round(params.lift_s * 1000),
    cycle_ms: Math.round(tl.liftEnd * 1000),
  };
}

export const gripperProduct: TrainingProduct<GripperSpec> = {
  id: "gripper",
  label: "Grasp",
  goal: "Lift 15 cm and survive the shake without slipping, with as little force and time as it takes",
  params: [
    { name: "squeeze", label: "Squeeze", min: 0.05, max: 1, init: 0.12, unit: "of max" },
    { name: "ramp_s", label: "Ramp", min: 0.03, max: 0.4, init: 0.35, unit: "s" },
    { name: "settle_s", label: "Settle", min: 0, max: 0.4, init: 0.02, unit: "s" },
    { name: "lift_s", label: "Lift", min: 0.3, max: 1.5, init: 0.35, unit: "s" },
  ],
  // A local search from the weak starting grasp: four parameters need no wide first spread.
  search: { sigma0: 0.08, eliteFrac: 0.2, smooth: 0.5, floor: 0.03 },
  horizonS: HORIZON_S,
  frameSize: 5,
  frameHz: 30,
  buildMjcf,
  exportGains,
  describe: (m) => ({
    ok: m.held === true,
    headline: m.held === true ? "Holds through the shake" : m.crashed === true ? "Drops the part" : "Still slips",
    lines: [`${Number(m.force_n ?? 0).toFixed(1)} N per finger`, `${Number(m.slip_mm ?? 0).toFixed(1)} mm slip`, `lifted after ${Number(m.cycle_s ?? 0).toFixed(2)} s`],
  }),
  // The nominal object; the trainer does not perturb the gripper's world.
  trainingPerturbation: () => ({ seed: 1 }),
  episode,
};
