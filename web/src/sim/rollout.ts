// One rollout: reset, apply the perturbation, step the product's episode, collect frames.
// Pure apart from MuJoCo, so it runs the same in a worker and in Node.
import type { MjData, MjModel } from "@mujoco/mujoco";
import type { Mujoco, Perturbation, RolloutJob, RolloutResult, TrainingProduct } from "./types";

/** A compiled model plus the nominal values a perturbation scales from. */
export interface Compiled {
  model: MjModel;
  data: MjData;
  mass: Float64Array;
  inertia: Float64Array;
  ctrlrange: Float64Array;
  friction: Float64Array;
}

export function compile(mj: Mujoco, mjcf: string): Compiled {
  const model = mj.MjModel.from_xml_string(mjcf);
  const data = new mj.MjData(model);
  return {
    model,
    data,
    mass: Float64Array.from(model.body_mass as ArrayLike<number>),
    inertia: Float64Array.from(model.body_inertia as ArrayLike<number>),
    ctrlrange: Float64Array.from(model.actuator_ctrlrange as ArrayLike<number>),
    friction: Float64Array.from(model.geom_friction as ArrayLike<number>),
  };
}

export function disposeCompiled(c: Compiled) {
  c.data.delete();
  c.model.delete();
}

function applyPerturbation(c: Compiled, p: Perturbation) {
  const { model } = c;
  const mass = model.body_mass as Float64Array;
  const inertia = model.body_inertia as Float64Array;
  const ctrlrange = model.actuator_ctrlrange as Float64Array;
  const friction = model.geom_friction as Float64Array;
  const ms = p.mass_scale ?? 1;
  const mo = p.motor_scale ?? 1;
  const fr = p.friction_scale ?? 1;
  for (let i = 0; i < c.mass.length; i++) mass[i] = c.mass[i] * ms;
  for (let i = 0; i < c.inertia.length; i++) inertia[i] = c.inertia[i] * ms;
  for (let i = 0; i < c.ctrlrange.length; i++) ctrlrange[i] = c.ctrlrange[i] * mo;
  // Only the sliding coefficient (first of three per geom) scales.
  for (let i = 0; i < c.friction.length; i++) friction[i] = i % 3 === 0 ? c.friction[i] * fr : c.friction[i];
}

export function runRollout(mj: Mujoco, c: Compiled, product: TrainingProduct<any>, spec: unknown, job: RolloutJob): RolloutResult {
  const p = job.perturbation ?? {};
  applyPerturbation(c, p);
  const { model, data } = c;
  mj.mj_resetData(model, data);
  const episode = product.episode(job.params, p, spec);
  episode.start(model, data);
  mj.mj_forward(model, data);
  const dt = model.opt.timestep;
  const steps = Math.round(product.horizonS / dt);
  const every = Math.max(1, Math.round(1 / (product.frameHz * dt)));
  const nFrames = job.frames === false ? 0 : Math.floor(steps / every) + 1;
  const frames = new Float32Array(nFrames * product.frameSize);
  let written = 0;
  if (nFrames) episode.frame(data, frames, written++ * product.frameSize);
  for (let i = 1; i <= steps; i++) {
    const t = i * dt;
    episode.control(model, data, t);
    mj.mj_step(model, data);
    const alive = episode.observe(model, data, t);
    if (nFrames && i % every === 0) episode.frame(data, frames, written++ * product.frameSize);
    if (!alive) break;
  }
  const { score, metrics } = episode.finish();
  return {
    score: Number.isFinite(score) ? score : 0,
    metrics,
    frames: frames.subarray(0, written * product.frameSize),
    frameSize: product.frameSize,
    frameHz: product.frameHz,
  };
}
