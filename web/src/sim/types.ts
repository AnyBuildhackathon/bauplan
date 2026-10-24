// Browser simulation: the contract between a product (drone, gripper, legged robot)
// and the generic MuJoCo WASM rollout pool and trainer.
import type { MainModule, MjData, MjModel } from "@mujoco/mujoco";
import type { CrossEntropyOptions } from "./es";

export type Mujoco = MainModule;

/** One tunable parameter. The optimizer works in [0, 1] and maps to [min, max] (log when `log`). */
export interface ParamSpec {
  name: string;
  label: string;
  min: number;
  max: number;
  /** Where the search starts. Deliberately weak, so the curve has somewhere to climb. */
  init: number;
  log?: boolean;
  unit?: string;
}

export type Params = Record<string, number>;

/**
 * Per-run physics changes. Every field is optional; a missing field means nominal.
 * The trainer uses only `seed`, `init_*` and `gust_scale`; the stress test varies the rest.
 */
export interface Perturbation {
  seed?: number;
  /** Scales every body mass and inertia. */
  mass_scale?: number;
  /** Scales the actuator range: motor thrust for the drone, motor torque for a robot. */
  motor_scale?: number;
  /** Scales every geom's sliding friction. */
  friction_scale?: number;
  /** Constant wind force in newtons on the main body, [fx, fy, fz]. */
  wind_n?: [number, number, number];
  /** Scales the scripted gust of the product's scenario. 0 turns it off. */
  gust_scale?: number;
  /** Start offset from the nominal start, metres [x, y, z]. */
  init_offset?: [number, number, number];
  /** Start tilt, radians [roll, pitch]. */
  init_tilt?: [number, number];
  /** A 1-cosine gust of wind instead of the scripted push (the stress test): peak m/s, where it blows to, when, and its downward share. */
  gust_wind?: { mps: number; dir_deg: number; start_s: number; len_s: number; downdraft: number };
  /** Sensor noise, metres: the standard deviation of the position the controller reads. */
  noise_m?: number;
}

export interface RolloutJob {
  params: Params;
  perturbation?: Perturbation;
  /** Keep the replay frames. Off saves memory when nobody draws the run. */
  frames?: boolean;
}

export interface RolloutResult {
  /** Higher is better, 0-100. */
  score: number;
  /** Product-specific readouts, for example rms_error_cm and max_tilt_deg. */
  metrics: Record<string, number | boolean>;
  /** Flat replay frames, `frameSize` numbers per frame at `frameHz`. Empty when not asked for. */
  frames: Float32Array;
  frameSize: number;
  frameHz: number;
}

/** Runs one episode on an already-reset MjData. Lives in the worker, so it must not touch the DOM. */
export interface Episode {
  /** Called once after mj_resetData, before the first step. */
  start(model: MjModel, data: MjData): void;
  /** Called before every mj_step: write data.ctrl (and xfrc_applied for scripted forces). */
  control(model: MjModel, data: MjData, t: number): void;
  /** Called after every mj_step. Return false to end the episode early (crash). */
  observe(model: MjModel, data: MjData, t: number): boolean;
  /** One replay frame, `frameSize` numbers. */
  frame(data: MjData, out: Float32Array, offset: number): void;
  finish(): { score: number; metrics: Record<string, number | boolean> };
}

export interface TrainingProduct<Spec = unknown> {
  id: string;
  label: string;
  /** One-line goal shown in the UI, such as "stay level and hold position for 10 s". */
  goal: string;
  params: ParamSpec[];
  /** Search settings for this product's parameter space; the defaults suit a 7-gain controller. */
  search?: CrossEntropyOptions;
  horizonS: number;
  frameSize: number;
  frameHz: number;
  buildMjcf(spec: Spec): string;
  /**
   * The trained parameters as other modules read them (the `gains` field of the final `training` event):
   * physical units for the stress test, and the firmware's shape where the product has one.
   */
  exportGains(params: Params, spec: Spec): Record<string, unknown>;
  /** The scenario every candidate of one generation runs (common random numbers). */
  trainingPerturbation(generation: number): Perturbation;
  episode(params: Params, perturbation: Perturbation, spec: Spec): Episode;
  /** How a result reads in the UI: whether it passed, a headline, and short readouts. */
  describe(metrics: Record<string, number | boolean>): { ok: boolean; headline: string; lines: string[] };
}
