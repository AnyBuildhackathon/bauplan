// Browser stress test: claims a queued drone `stress` job from the backend, flies its 50
// seeded worlds on the training module's rollout pool with the trained gains, and posts
// the outcomes back. The backend scores them and publishes the `stress` events.
import { apiFetch } from "../lib/api";
import { DRONE_TARGET, droneParams, droneProduct, type DroneSpec } from "./drone";
import { sharedPool } from "./pool";
import type { Perturbation, RolloutResult } from "./types";

/** One world as the backend drew it (`World` in agent/src/pai_agent/tools/stress.py). */
export interface StressWorldSpec {
  i: number;
  mass_scale: number;
  motor_scale: number;
  gust_mps: number;
  gust_dir_deg: number;
  gust_start_s: number;
  gust_len_s: number;
  downdraft_share: number;
  noise_m: number;
}

interface Claimed {
  spec: DroneSpec;
  gains: Record<string, number>;
  worlds: StressWorldSpec[];
}

/** Outcomes go back in small batches, so the card fills while the pool works. */
const BATCH = 5;
const CLIENT = "tab-" + Math.random().toString(36).slice(2, 10);
const started = new Set<string>();
let abort: AbortController | null = null;

async function post(path: string, body: unknown): Promise<Response> {
  return apiFetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

/** A world starts level on the hover spot; the trainer's scripted push is off and the world's own gust blows. */
function perturbation(w: StressWorldSpec, seed: number): Perturbation {
  return {
    seed: seed * 1000 + w.i,
    mass_scale: w.mass_scale,
    motor_scale: w.motor_scale,
    gust_scale: 0,
    init_offset: [DRONE_TARGET[0] - 0.35, DRONE_TARGET[1] + 0.25, DRONE_TARGET[2] - 0.55],
    init_tilt: [0, 0],
    gust_wind: { mps: w.gust_mps, dir_deg: w.gust_dir_deg, start_s: w.gust_start_s, len_s: w.gust_len_s, downdraft: w.downdraft_share },
    noise_m: w.noise_m,
  };
}

/** Replay frames (qpos at frameHz) as the `sim` trajectory: [[t, x, y, z], ...]. */
function trajectory(r: RolloutResult): number[][] {
  const out: number[][] = [];
  const n = r.frameSize ? r.frames.length / r.frameSize : 0;
  const round = (v: number) => Math.round(v * 10000) / 10000;
  for (let k = 0; k < n; k++) {
    const o = k * r.frameSize;
    out.push([round(k / r.frameHz), round(r.frames[o]), round(r.frames[o + 1]), round(r.frames[o + 2])]);
  }
  return out;
}

/** Drops a local run after a session reset; the backend no longer knows its job. */
export function resetStress() {
  abort?.abort();
  abort = null;
}

export async function runBrowserStress(jobId: string, seed = 7) {
  if (started.has(jobId)) return;
  started.add(jobId);
  abort?.abort();
  const ctl = new AbortController();
  abort = ctl;

  let claimed: Claimed;
  try {
    const res = await post(`/api/stress/${jobId}/claim`, { client: CLIENT });
    // Another tab flies it, or the job is from an earlier session.
    if (!res.ok) return;
    claimed = await res.json();
  } catch {
    return;
  }
  const report = (body: Record<string, unknown>) => post(`/api/stress/${jobId}/progress`, { client: CLIENT, ...body }).catch(() => undefined);

  try {
    const params = droneParams(claimed.gains, claimed.spec);
    const jobs = claimed.worlds.map((w) => ({ params, perturbation: perturbation(w, seed) }));
    let pending: { i: number; metrics: Record<string, number | boolean>; trajectory: number[][] }[] = [];
    // One post at a time, in order, so the last batch lands before `done`.
    let chain: Promise<unknown> = Promise.resolve();
    const flush = () => {
      if (!pending.length) return;
      const results = pending;
      pending = [];
      chain = chain.then(() => report({ status: "running", results }));
    };
    const results = await sharedPool().run({
      productId: droneProduct.id,
      spec: claimed.spec,
      jobs,
      signal: ctl.signal,
      onResult: (index, r) => {
        // A world the worker could not run is not a crash; the run fails below instead.
        if (r.metrics.error === true) return;
        pending.push({ i: claimed.worlds[index].i, metrics: r.metrics, trajectory: trajectory(r) });
        if (pending.length >= BATCH) flush();
      },
    });
    flush();
    await chain;
    const broken = results.findIndex((r) => r.metrics.error === true);
    if (broken >= 0) throw new Error(`MuJoCo could not run world ${claimed.worlds[broken].i}`);
    await report({ status: "done" });
  } catch (err) {
    if (ctl.signal.aborted) return;
    await report({ status: "failed", error: String(err).slice(0, 200) });
  }
}
