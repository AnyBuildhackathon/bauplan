// The reusable rollout API: N MuJoCo rollouts of one product, spread over Web Workers
// (cores minus one). The trainer and the stress test both call `runRollouts`.
import type { WorkerRequest, WorkerResponse } from "./worker";
import type { RolloutJob, RolloutResult } from "./types";

export interface RolloutBatch {
  productId: string;
  /** The product's spec, e.g. DroneSpec from the backend's `training` event. */
  spec: unknown;
  /** Optional MJCF that replaces the product's own builder. */
  mjcf?: string;
  jobs: RolloutJob[];
  /** Called as each rollout finishes, in completion order. */
  onResult?: (index: number, result: RolloutResult) => void;
  signal?: AbortSignal;
}

const failed = (): RolloutResult => ({ score: 0, metrics: { error: true }, frames: new Float32Array(0), frameSize: 0, frameHz: 0 });

export class RolloutPool {
  readonly size: number;
  private workers: Worker[] = [];
  private nextId = 1;

  constructor(size = defaultPoolSize()) {
    this.size = Math.max(1, size);
  }

  private ensure() {
    while (this.workers.length < this.size) {
      this.workers.push(new Worker(new URL("./worker.ts", import.meta.url), { type: "module", name: `mujoco-${this.workers.length}` }));
    }
  }

  /** Runs every job once and resolves with the results in job order. */
  run(batch: RolloutBatch): Promise<RolloutResult[]> {
    this.ensure();
    const { jobs } = batch;
    const results: RolloutResult[] = new Array(jobs.length);
    if (jobs.length === 0) return Promise.resolve(results);
    // Interleave jobs so every worker gets a similar share.
    const shares: { index: number; job: RolloutJob }[][] = this.workers.map(() => []);
    jobs.forEach((job, index) => shares[index % this.workers.length].push({ index, job }));
    const active = shares.map((share, w) => ({ share, worker: this.workers[w] })).filter((s) => s.share.length > 0);
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      let open = active.length;
      const cleanups: (() => void)[] = [];
      const finish = () => {
        cleanups.forEach((c) => c());
        for (let i = 0; i < results.length; i++) results[i] ??= failed();
        resolve(results);
      };
      const onAbort = () => {
        cleanups.forEach((c) => c());
        reject(new DOMException("Aborted", "AbortError"));
      };
      if (batch.signal?.aborted) return onAbort();
      batch.signal?.addEventListener("abort", onAbort, { once: true });
      cleanups.push(() => batch.signal?.removeEventListener("abort", onAbort));
      for (const { share, worker } of active) {
        const listener = (msg: MessageEvent<WorkerResponse>) => {
          const r = msg.data;
          if (r.id !== id) return;
          if ("done" in r) {
            worker.removeEventListener("message", listener);
            if (--open === 0) finish();
            return;
          }
          const result = r.ok ? { score: r.score, metrics: r.metrics, frames: r.frames, frameSize: r.frameSize, frameHz: r.frameHz } : failed();
          results[r.index] = result;
          batch.onResult?.(r.index, result);
        };
        worker.addEventListener("message", listener);
        cleanups.push(() => worker.removeEventListener("message", listener));
        const req: WorkerRequest = { id, productId: batch.productId, spec: batch.spec, mjcf: batch.mjcf, jobs: share };
        worker.postMessage(req);
      }
    });
  }

  terminate() {
    this.workers.forEach((w) => w.terminate());
    this.workers = [];
  }
}

export function defaultPoolSize(): number {
  const cores = typeof navigator !== "undefined" ? navigator.hardwareConcurrency || 4 : 4;
  return Math.max(1, Math.min(15, cores - 1));
}

let shared: RolloutPool | null = null;

/** One pool for the whole page, so training and the stress test reuse warm workers. */
export function sharedPool(): RolloutPool {
  shared ??= new RolloutPool();
  return shared;
}

/** Runs N rollouts of a product with given parameters and per-run perturbations. */
export function runRollouts(batch: RolloutBatch): Promise<RolloutResult[]> {
  return sharedPool().run(batch);
}
