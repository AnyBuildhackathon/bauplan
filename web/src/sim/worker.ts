// One MuJoCo WASM instance per worker. It compiles each product spec once and runs
// whatever rollouts the pool sends.
/// <reference lib="webworker" />
import loadMujoco from "@mujoco/mujoco";
import wasmUrl from "@mujoco/mujoco/mujoco.wasm?url";
import { productFor } from "./products";
import { compile, disposeCompiled, runRollout, type Compiled } from "./rollout";
import type { Mujoco, RolloutJob } from "./types";

export interface WorkerRequest {
  id: number;
  productId: string;
  spec: unknown;
  /** Optional ready-made MJCF; otherwise the product builds it from `spec`. */
  mjcf?: string;
  jobs: { index: number; job: RolloutJob }[];
}

export type WorkerResponse =
  | { id: number; index: number; ok: true; score: number; metrics: Record<string, number | boolean>; frames: Float32Array; frameSize: number; frameHz: number }
  | { id: number; index: number; ok: false; error: string }
  | { id: number; done: true };

let mujoco: Promise<Mujoco> | null = null;
let cached: { key: string; compiled: Compiled } | null = null;

function engine(): Promise<Mujoco> {
  mujoco ??= loadMujoco({ locateFile: (path: string) => (path.endsWith(".wasm") ? wasmUrl : path) }) as Promise<Mujoco>;
  return mujoco;
}

self.onmessage = async (msg: MessageEvent<WorkerRequest>) => {
  const req = msg.data;
  const post = (r: WorkerResponse, transfer: Transferable[] = []) => (self as DedicatedWorkerGlobalScope).postMessage(r, transfer);
  try {
    const mj = await engine();
    const product = productFor(req.productId);
    const mjcf = req.mjcf ?? product.buildMjcf(req.spec);
    if (!cached || cached.key !== mjcf) {
      if (cached) disposeCompiled(cached.compiled);
      cached = { key: mjcf, compiled: compile(mj, mjcf) };
    }
    for (const { index, job } of req.jobs) {
      try {
        const r = runRollout(mj, cached.compiled, product, req.spec, job);
        const frames = r.frames.slice();
        post({ id: req.id, index, ok: true, score: r.score, metrics: r.metrics, frames, frameSize: r.frameSize, frameHz: r.frameHz }, [frames.buffer]);
      } catch (err) {
        post({ id: req.id, index, ok: false, error: String(err) });
      }
    }
  } catch (err) {
    for (const { index } of req.jobs) post({ id: req.id, index, ok: false, error: String(err) });
  }
  post({ id: req.id, done: true });
};
