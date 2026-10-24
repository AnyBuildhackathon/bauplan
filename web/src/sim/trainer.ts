// Browser training: claims a queued `training` job from the backend, runs the evolution
// strategy over the rollout pool, and posts every generation back as a `training` event.
// The local store feeds the grid and the large replay in this tab.
import { create } from "zustand";
import { apiUrl } from "../lib/api";
import { CrossEntropy, toParams } from "./es";
import { sharedPool } from "./pool";
import { productFor } from "./products";
import type { Params, RolloutResult } from "./types";

export const GRID_SIZE = 16;
/** Each generation stays on screen at least this long, so its 16 runs can be watched. */
const MIN_GENERATION_MS = 2200;
/** Replay speed of the 10 s runs in the grid. */
export const REPLAY_SPEED = 5;

export interface Tile {
  rank: number;
  score: number;
  crashed: boolean;
  held: boolean;
  frames: Float32Array;
  frameSize: number;
  frameHz: number;
}

export interface Best {
  score: number;
  params: Params;
  metrics: Record<string, number | boolean>;
  frames: Float32Array;
  frameSize: number;
  frameHz: number;
  generation: number;
}

/** The fields this module adds to the contract's `training` event. */
export interface BrowserTrainingFields {
  source?: "browser";
  job_id?: string;
  product?: string;
  spec?: unknown;
  population?: number;
  generations?: number;
  rollouts_total?: number;
  generation?: number;
  best_params?: Params | null;
  best_metrics?: Record<string, number | boolean> | null;
  error?: string;
}

interface TrainerState {
  jobId: string | null;
  status: "idle" | "claiming" | "running" | "done" | "failed" | "elsewhere";
  productId: string;
  spec: unknown;
  population: number;
  generations: number;
  generation: number;
  rollouts: number;
  workers: number;
  curve: [number, number][];
  meanCurve: [number, number][];
  tiles: Tile[];
  /** When the current tiles were put on screen, for the replay clock. */
  tilesAt: number;
  best: Best | null;
  error: string | null;
  startedAt: number;
  finishedAt: number;
}

const initial: TrainerState = {
  jobId: null,
  status: "idle",
  productId: "drone",
  spec: null,
  population: 64,
  generations: 16,
  generation: 0,
  rollouts: 0,
  workers: 0,
  curve: [],
  meanCurve: [],
  tiles: [],
  tilesAt: 0,
  best: null,
  error: null,
  startedAt: 0,
  finishedAt: 0,
};

export const useTrainer = create<TrainerState>(() => ({ ...initial }));

const CLIENT = "tab-" + Math.random().toString(36).slice(2, 10);
let abort: AbortController | null = null;

async function post(path: string, body: unknown): Promise<Response> {
  return fetch(apiUrl(path), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (ms <= 0 || signal.aborted) return resolve();
    const id = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => (clearTimeout(id), resolve()), { once: true });
  });

/** Drops the local run (session reset). A running loop stops at its next await. */
export function resetTrainer() {
  abort?.abort();
  abort = null;
  useTrainer.setState({ ...initial });
}

/** The backend gave up on this tab's job (timeout, reset): stop computing and show why. */
export function abandonTraining(jobId: string, error: string) {
  const s = useTrainer.getState();
  if (s.jobId !== jobId || (s.status !== "running" && s.status !== "claiming")) return;
  abort?.abort();
  abort = null;
  useTrainer.setState({ status: "failed", error });
}

/** Marks a job that another tab claimed: this tab only shows the shared curve. */
export function watchElsewhere(jobId: string) {
  if (useTrainer.getState().jobId === jobId) return;
  useTrainer.setState({ ...initial, jobId, status: "elsewhere" });
}

export async function runBrowserTraining(jobId: string, fallback: { productId: string; spec: unknown; population: number; generations: number }) {
  const cur = useTrainer.getState();
  if (cur.jobId === jobId && cur.status !== "elsewhere") return;
  abort?.abort();
  const ctl = new AbortController();
  abort = ctl;
  useTrainer.setState({ ...initial, jobId, status: "claiming", productId: fallback.productId, spec: fallback.spec });

  let claimed: { spec: unknown; population: number; generations: number };
  try {
    const res = await post(`/api/training/${jobId}/claim`, { client: CLIENT });
    if (res.status === 409) return watchElsewhere(jobId);
    if (!res.ok) throw new Error(`claim failed: HTTP ${res.status}`);
    claimed = await res.json();
  } catch (err) {
    if (!ctl.signal.aborted) useTrainer.setState({ status: "failed", error: String(err) });
    return;
  }
  const spec = claimed.spec ?? fallback.spec;
  const productId = (spec as { product?: string } | null)?.product ?? fallback.productId;
  const population = claimed.population ?? fallback.population;
  const generations = claimed.generations ?? fallback.generations;
  const pool = sharedPool();
  useTrainer.setState({ status: "running", productId, spec, population, generations, workers: pool.size, startedAt: Date.now() });

  const report = (body: Record<string, unknown>) =>
    post(`/api/training/${jobId}/progress`, { client: CLIENT, ...body }).catch(() => undefined);

  try {
    const product = productFor(productId);
    const es = new CrossEntropy(product.params);
    let best: Best | null = null;
    await report({ status: "running", step: 0, generation: 0 });
    for (let g = 0; g < generations; g++) {
      const t0 = performance.now();
      const xs = es.ask(population);
      const params = xs.map((x) => toParams(product.params, x));
      // Common random numbers: one scenario per generation for every candidate.
      const scenario = product.trainingPerturbation(g);
      const jobs = params.map((p) => ({ params: p, perturbation: scenario }));
      const results: RolloutResult[] = await pool.run({
        productId,
        spec,
        jobs,
        signal: ctl.signal,
        onResult: () => useTrainer.setState((s) => ({ rollouts: s.rollouts + 1 })),
      });
      const scores = results.map((r) => r.score);
      es.tell(xs, scores);
      const order = scores.map((s, i) => [s, i] as const).sort((a, b) => b[0] - a[0]);
      const [topScore, topIndex] = order[0];
      if (!best || topScore > best.score) {
        const r = results[topIndex];
        best = { score: topScore, params: params[topIndex], metrics: r.metrics, frames: r.frames, frameSize: r.frameSize, frameHz: r.frameHz, generation: g + 1 };
      }
      const step = (g + 1) * population;
      const mean = scores.reduce((a, b) => a + b, 0) / scores.length;
      // 16 of the 64, evenly spread over the ranking: best to worst, so failures stay visible.
      const stride = population / GRID_SIZE;
      const tiles: Tile[] = Array.from({ length: Math.min(GRID_SIZE, population) }, (_, k) => {
        const [score, index] = order[Math.min(order.length - 1, Math.round(k * stride))];
        const r = results[index];
        return { rank: Math.round(k * stride) + 1, score, crashed: r.metrics.crashed === true, held: r.metrics.held === true, frames: r.frames, frameSize: r.frameSize, frameHz: r.frameHz };
      });
      useTrainer.setState((s) => ({
        generation: g + 1,
        rollouts: step,
        curve: [...s.curve, [step, round(best!.score)]],
        meanCurve: [...s.meanCurve, [step, round(mean)]],
        tiles,
        tilesAt: performance.now(),
        best,
      }));
      await report({ status: "running", step, generation: g + 1, best_score: best.score, best_params: roundParams(best.params), best_metrics: best.metrics });
      if (g < generations - 1) await sleep(MIN_GENERATION_MS - (performance.now() - t0), ctl.signal);
      if (ctl.signal.aborted) return;
    }
    useTrainer.setState({ status: "done", finishedAt: Date.now() });
    await report({
      status: "done",
      step: generations * population,
      generation: generations,
      best_score: best?.score ?? 0,
      best_params: best ? roundParams(best.params) : null,
      best_metrics: best?.metrics ?? null,
    });
  } catch (err) {
    if (ctl.signal.aborted) return;
    useTrainer.setState({ status: "failed", error: String(err) });
    await report({ status: "failed", step: useTrainer.getState().rollouts, error: String(err).slice(0, 200) });
  }
}

const round = (v: number) => Math.round(v * 100) / 100;

function roundParams(p: Params): Params {
  return Object.fromEntries(Object.entries(p).map(([k, v]) => [k, Number(v.toPrecision(4))]));
}
