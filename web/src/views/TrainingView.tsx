// Training page: a browser quick check (1,024 MuJoCo sims), Isaac Lab on a GPU host,
// and the latest stress test. Isaac data is read from session events only.
import { useEffect, useMemo, useRef, useState } from "react";
import type { DroneSpec } from "../sim/drone";
import type { GripperSpec } from "../sim/gripper";
import { productFor } from "../sim/products";
import { GRID_SIZE, REPLAY_SPEED, runLocalTraining, useTrainer, type Tile } from "../sim/trainer";
import { canonicalToolName, formatSteps, useSession } from "../events/store";
import { useSource } from "../events/source";
import type { OmniverseEvent, StressEvent } from "../events/types";
import { fmtNum } from "../lib/format";
import { assetUrl } from "../lib/api";
import { usePrefersReducedMotion } from "../components/canvas/GridStage";
import { StressCard } from "../components/stress/StressCard";
import { TrendChart } from "../components/ui/TrendChart";
import { Card } from "../components/ui/primitives";
import { drawDroneFrame, themeColors, type DrawStyle } from "../components/training/drawDrone";
import { drawGripperFrame } from "../components/training/drawGripper";
import { useBrowserTrainingEvent } from "../components/training/useBrowserTraining";

const NOMINAL_DRONE: DroneSpec = {
  product: "drone",
  nominal: true,
  label: "nominal drone",
  mass_g: 36.7,
  thrust_g: 4 * 28,
  motors: 4,
  arm_length_mm: 36,
  parts: [],
};

const PREVIEW_FRAMES = 24;
const PREVIEW = (() => {
  const frames = new Float32Array(PREVIEW_FRAMES * 7);
  for (let i = 0; i < PREVIEW_FRAMES; i++) {
    const t = (i / PREVIEW_FRAMES) * Math.PI * 2;
    const o = i * 7;
    const roll = Math.sin(t) * 0.18;
    frames[o] = Math.sin(t) * 0.05;
    frames[o + 1] = Math.cos(t) * 0.04;
    frames[o + 2] = 1 + Math.sin(t * 2) * 0.025;
    frames[o + 3] = Math.cos(roll / 2);
    frames[o + 4] = Math.sin(roll / 2);
  }
  return frames;
})();

const FAIL_REASON: Record<string, string> = {
  crashed: "touched down",
  drifted: "blown off its spot",
  sagged: "could not hold height",
  slipped: "object slipped",
  dropped: "object dropped",
};

function rise(delayMs: number, reduced: boolean): { className: string; style?: { animationDelay: string } } {
  if (reduced) return { className: "" };
  return { className: "animate-training-rise motion-reduce:animate-none", style: { animationDelay: `${delayMs}ms` } };
}

function useSize<T extends HTMLElement>() {
  const [el, ref] = useState<T | null>(null);
  const [size, setSize] = useState({ w: 320, h: 260 });
  useEffect(() => {
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [ref, size] as const;
}

function fit(cv: HTMLCanvasElement) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = Math.round(cv.clientWidth * dpr);
  const h = Math.round(cv.clientHeight * dpr);
  if (cv.width !== w || cv.height !== h) {
    cv.width = w;
    cv.height = h;
  }
}

function padSim(n: number) {
  return String(n).padStart(3, "0");
}

/** Stock connection lines stay off the projector; a real host error still shows. */
function gpuOfflineHint(detail: string | undefined): string {
  if (detail && !/not configured|waiting for pod|gpu ssh is configured/i.test(detail)) return detail;
  return "Deep training starts when an NVIDIA GPU host is online. The quick check above runs without it.";
}

function hostName(detail: string): string {
  const named = detail.match(/\b(A\d{2,3}|H100|H200|L40S?|A100|RTX\s*\d{3,4})\b/i);
  if (!named) return "GPU";
  return named[1].replace(/\s+/, " ").replace(/^rtx/i, "RTX");
}

function envCount(omni: OmniverseEvent | null, detail: string): number | null {
  const raw = omni?.parameters?.num_envs ?? omni?.requested?.num_envs;
  if (typeof raw === "number" && raw > 0) return raw;
  if (typeof raw === "string" && Number(raw) > 0) return Number(raw);
  const match = detail.match(/(\d[\d,]*)\s*(?:envs|environments|drohnen)/i);
  if (!match) return null;
  const n = Number(match[1].replace(/,/g, ""));
  return n > 0 ? n : null;
}

function realClip(url: string | null | undefined): string | null {
  if (!url || url.includes("/fallback/")) return null;
  return url;
}

/** Draws the 16 quick-check tiles from the live trainer, or a quiet preview before a run. */
function SimTiles({ tiles, tilesAt, productId, spec, live }: { tiles: Tile[]; tilesAt: number; productId: string; spec: unknown; live: boolean }) {
  const reduced = usePrefersReducedMotion();
  const canvases = useRef<(HTMLCanvasElement | null)[]>([]);
  const draw = useMemo(() => {
    if (productId === "gripper") {
      return (ctx: CanvasRenderingContext2D, w: number, h: number, frames: Float32Array, frameSize: number, index: number, style: DrawStyle) =>
        drawGripperFrame(ctx, w, h, frames, frameSize, index, style, spec as GripperSpec | null);
    }
    const armM = ((spec as DroneSpec | null)?.arm_length_mm ?? 36) / 1000;
    return (ctx: CanvasRenderingContext2D, w: number, h: number, frames: Float32Array, frameSize: number, index: number, style: DrawStyle) =>
      drawDroneFrame(ctx, w, h, frames, frameSize, index, style, armM);
  }, [productId, spec]);

  useEffect(() => {
    let raf = 0;
    let last = 0;
    const colors = themeColors();
    const paint = (now: number) => {
      for (let k = 0; k < GRID_SIZE; k++) {
        const cv = canvases.current[k];
        const ctx = cv?.getContext("2d");
        if (!cv || !ctx) continue;
        fit(cv);
        const tile = tiles[k];
        const style: DrawStyle = {
          color: tile ? (tile.crashed ? colors.fail : tile.held ? colors.ok : colors.agent) : colors.faint,
          ink: colors.ink,
          faint: colors.faint,
          line: colors.line,
        };
        if (tile && live) {
          const frames = Math.floor(tile.frames.length / Math.max(1, tile.frameSize));
          const index = Math.floor(((now - tilesAt) / 1000) * REPLAY_SPEED * tile.frameHz);
          draw(ctx, cv.width, cv.height, tile.frames, tile.frameSize, Math.min(index, Math.max(0, frames - 1)), style);
        } else if (productId !== "gripper") {
          const index = reduced ? 0 : Math.floor(now / 80 + k * 3) % PREVIEW_FRAMES;
          draw(ctx, cv.width, cv.height, PREVIEW, 7, index, style);
        } else {
          ctx.clearRect(0, 0, cv.width, cv.height);
        }
      }
    };
    const loop = (now: number) => {
      if (now - last < 80) {
        raf = requestAnimationFrame(loop);
        return;
      }
      last = now;
      paint(now);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(reduced ? paint : loop);
    const ro = new ResizeObserver(() => {
      if (!reduced) return;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(paint);
    });
    canvases.current.forEach((cv) => cv && ro.observe(cv));
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [tiles, tilesAt, draw, live, productId, reduced]);

  return (
    <div className="grid grid-cols-4 gap-2" data-target="training:tiles">
      {Array.from({ length: GRID_SIZE }, (_, k) => {
        const tile = live ? tiles[k] : undefined;
        const outcome = tile ? tileOutcome(tile) : null;
        const label = `Sim #${padSim(tile?.rank ?? k + 1)}`;
        return (
          <div
            key={k}
            title={tile ? `${label} · ${outcomeLabels(productId)[outcome!]} · fitness ${fmtNum(tile.score, 1)}` : label}
            className={`group relative aspect-square overflow-hidden rounded-xl transition-[transform,background-color] duration-300 ease-out hover:z-10 hover:scale-[1.04] motion-reduce:transition-none motion-reduce:hover:scale-100 ${
              outcome ? OUTCOME_TILE[outcome] : "bg-tile"
            } ${tile && k === 0 ? "ring-2 ring-accent ring-offset-2 ring-offset-card" : ""}`}
          >
            <canvas ref={(el) => void (canvases.current[k] = el)} className="absolute inset-0 h-full w-full" aria-hidden />
            <span className="num pointer-events-none absolute top-1.5 left-2 text-[12px] font-semibold text-muted">
              {tile && k === 0 ? "Best" : `#${padSim(tile?.rank ?? k + 1)}`}
            </span>
            {outcome && <span className={`pointer-events-none absolute top-2 right-2 h-2 w-2 rounded-full ${OUTCOME_DOT[outcome]}`} />}
          </div>
        );
      })}
    </div>
  );
}

type Outcome = "held" | "drifted" | "crashed";

function tileOutcome(tile: Tile): Outcome {
  return tile.crashed ? "crashed" : tile.held ? "held" : "drifted";
}

const OUTCOME_TILE: Record<Outcome, string> = { held: "bg-ok-soft", drifted: "bg-agent-soft", crashed: "bg-fail-soft" };
const OUTCOME_DOT: Record<Outcome, string> = { held: "bg-ok", drifted: "bg-agent", crashed: "bg-fail" };

/** Shared view of the quick check: this tab's own run, or the one another tab reports over SSE. */
function useQuickCheck() {
  const local = useTrainer();
  const sse = useBrowserTrainingEvent();
  const mode = useSource((s) => s.mode);
  const link = useSource((s) => s.live);
  const here = local.status === "running" || local.status === "done" || local.status === "claiming";
  const spec = here ? local.spec : sse?.spec ?? null;
  const productId = (here ? local.productId : sse?.product) ?? "drone";
  const population = (here ? local.population : sse?.population) ?? 64;
  const generations = (here ? local.generations : sse?.generations) ?? 16;
  const total = (here ? population * generations : sse?.rollouts_total) ?? population * generations;
  const rollouts = here ? local.rollouts : sse?.step ?? 0;
  const generation = here ? local.generation : sse?.generation ?? 0;
  const curve = here ? local.curve : sse?.curve ?? [];
  const meanCurve = here ? local.meanCurve : [];
  const status = here ? local.status : sse?.status ?? "idle";
  const settled = status === "done" || status === "failed";
  const running = status === "running" || status === "claiming" || status === "queued" || (local.status === "elsewhere" && !settled);
  const busy = local.status === "running" || local.status === "claiming";

  function start() {
    if (busy) return;
    if (mode === "live" && link === "open") void useSource.getState().sendPrompt("train it");
    else void runLocalTraining("drone", NOMINAL_DRONE);
  }

  return { local, sse, spec, productId, population, generations, total, rollouts, generation, curve, meanCurve, status, running, busy, start, liveTiles: here && local.tiles.length > 0 };
}

type QuickCheckState = ReturnType<typeof useQuickCheck>;

function productNames(productId: string, spec: unknown): { product: string; controller: string } {
  const label = (spec as { label?: string; nominal?: boolean } | null)?.nominal ? null : (spec as { label?: string } | null)?.label;
  let controller = "Controller";
  try {
    controller = productFor(productId).label;
  } catch {
    // An unknown product still shows its name.
  }
  const product = label || (productId === "gripper" ? "Gripper" : productId === "drone" ? "Drone" : productId);
  return { product: product.charAt(0).toUpperCase() + product.slice(1), controller };
}

function outcomeLabels(productId: string): Record<Outcome, string> {
  return productId === "gripper"
    ? { held: "Held", drifted: "Slipped", crashed: "Dropped" }
    : { held: "On target", drifted: "Drifted", crashed: "Crashed" };
}

function StartButton({ q }: { q: QuickCheckState }) {
  const again = q.status === "done" || q.status === "failed";
  return (
    <button
      type="button"
      disabled={q.busy}
      onClick={q.start}
      className="inline-flex h-11 shrink-0 items-center gap-2 rounded-full bg-accent pr-5 pl-4 text-[15px] font-semibold text-white shadow-[var(--shadow-pill)] transition hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-45"
    >
      {q.busy ? (
        <span className="h-3.5 w-3.5 animate-spin-slow rounded-full border-2 border-white/40 border-t-white motion-reduce:animate-none" aria-hidden />
      ) : again ? (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
          <path d="M13 8a5 5 0 1 1-1.5-3.6M13 2.5V5h-2.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : (
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
          <path d="M5 3.2v9.6a.6.6 0 0 0 .9.5l7.6-4.8a.6.6 0 0 0 0-1L5.9 2.7a.6.6 0 0 0-.9.5Z" fill="currentColor" />
        </svg>
      )}
      {q.busy ? "Training…" : again ? "Run quick check again" : "Start quick check"}
    </button>
  );
}

function Hero({ q, task }: { q: QuickCheckState; task: string | null }) {
  const reduced = usePrefersReducedMotion();
  const head = rise(0, reduced);
  const { product, controller } = productNames(q.productId, q.spec);
  const tiles = q.liveTiles ? q.local.tiles : [];
  const holding = tiles.filter((t) => tileOutcome(t) === "held").length;
  const best = q.curve.at(-1)?.[1];
  const firstBest = q.curve[0]?.[1];
  const stats: { label: string; value: string; of?: string; note?: string; tone?: string }[] = [
    { label: "Simulations", value: fmtNum(q.rollouts), of: fmtNum(q.total), note: "MuJoCo rollouts" },
    { label: "Generation", value: fmtNum(q.generation), of: fmtNum(q.generations), note: `${fmtNum(q.population)} candidates each` },
    {
      label: "Best fitness",
      value: best !== undefined ? fmtNum(best, 1) : "–",
      note: best !== undefined && firstBest !== undefined && q.curve.length > 1 ? `${best >= firstBest ? "+" : ""}${fmtNum(best - firstBest, 1)} since gen 1` : "Higher is steadier",
      tone: best !== undefined && firstBest !== undefined && best > firstBest ? "text-ok-ink" : undefined,
    },
    {
      label: outcomeLabels(q.productId).held,
      value: tiles.length ? fmtNum(holding) : "–",
      of: tiles.length ? fmtNum(tiles.length) : undefined,
      note: "Sampled sims this generation",
    },
  ];
  return (
    <header className={`flex flex-col gap-5 ${head.className}`} style={head.style}>
      <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
        <div className="min-w-0 flex-1">
          <p className="inline-flex h-7 items-center gap-2 rounded-full bg-accent-soft px-3 text-[13px] font-semibold text-accent">
            <span className={`h-1.5 w-1.5 rounded-full bg-accent ${q.running ? "animate-pulse-soft motion-reduce:animate-none" : ""}`} />
            {product} · {controller}
          </p>
          <h1 className="mt-3 text-[28px] leading-none font-semibold tracking-[-0.02em] text-ink min-[900px]:text-[32px]">Training</h1>
          <p className="mt-2 max-w-[44rem] text-[15px] leading-snug text-muted">
            Mechanic tunes the {controller.toLowerCase()} across {fmtNum(q.total)} MuJoCo simulations in your browser, then Isaac Lab trains the final policy on a cloud GPU.
            {task ? ` ${task}.` : ""}
          </p>
        </div>
        <StartButton q={q} />
      </div>
      <div className="card grid grid-cols-2 min-[900px]:grid-cols-4" data-target="training:stats">
        {stats.map((s, i) => (
          <div
            key={s.label}
            className={`min-w-0 px-5 py-4 ${i % 2 ? "border-l border-line" : ""} ${i >= 2 ? "border-t border-line min-[900px]:border-t-0" : ""} ${i === 2 ? "min-[900px]:border-l" : ""}`}
          >
            <p className="text-[13px] font-semibold text-muted">{s.label}</p>
            <p className="num mt-1.5 text-[28px] leading-none font-bold tracking-[-0.03em] text-ink" data-target={i === 0 ? "training:counter" : undefined}>
              {s.value}
              {s.of && <span className="text-[17px] font-semibold text-faint"> / {s.of}</span>}
            </p>
            {s.note && <p className={`mt-1.5 truncate text-[13px] ${s.tone ?? "text-muted"}`}>{s.note}</p>}
          </div>
        ))}
      </div>
    </header>
  );
}

function FitnessChart({ curve, mean, total }: { curve: [number, number][]; mean: [number, number][]; total: number }) {
  const [ref, size] = useSize<HTMLDivElement>();
  const all = [...curve, ...mean].map((p) => p[1]);
  const lo = all.length ? Math.min(...all) : 0;
  const hi = all.length ? Math.max(...all, lo + 1) : 1;
  const pad = (hi - lo) * 0.08;
  return (
    <div ref={ref} className="relative min-h-[200px] flex-1">
      {curve.length > 1 ? (
        <TrendChart
          series={[
            ...(mean.length > 1 ? [{ points: mean, color: "var(--color-faint)", dashed: true, glow: false }] : []),
            { points: curve, color: "var(--color-accent)", area: true },
          ]}
          width={Math.max(160, size.w)}
          height={Math.max(200, size.h)}
          xDomain={[0, Math.max(total, curve.at(-1)?.[0] ?? 1)]}
          yDomain={[lo - pad, hi + pad]}
          yTicks={[lo, (lo + hi) / 2, hi]}
          formatY={(v) => fmtNum(v, 1)}
        />
      ) : (
        <div className="absolute inset-0 flex flex-col justify-between py-2.5 pr-[54px]" aria-hidden>
          {[0, 1, 2].map((k) => (
            <div key={k} className="border-t border-dashed border-track" />
          ))}
          <p className="absolute inset-x-0 top-1/2 -translate-y-1/2 pr-[54px] text-center text-[13px] text-muted">The curve draws as each generation finishes.</p>
        </div>
      )}
    </div>
  );
}

function OutcomeBar({ tiles, productId }: { tiles: Tile[]; productId: string }) {
  const labels = outcomeLabels(productId);
  const counts: Record<Outcome, number> = { held: 0, drifted: 0, crashed: 0 };
  tiles.forEach((t) => counts[tileOutcome(t)]++);
  const order: Outcome[] = ["held", "drifted", "crashed"];
  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded-full bg-track">
        {tiles.length > 0 &&
          order.map((o) => (
            <div key={o} className={`h-full transition-[width] duration-500 ease-out ${OUTCOME_DOT[o]}`} style={{ width: `${(counts[o] / tiles.length) * 100}%` }} />
          ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-muted">
        {order.map((o) => (
          <span key={o} className="inline-flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${OUTCOME_DOT[o]}`} />
            {labels[o]}
            <span className="num font-semibold text-ink-2">{tiles.length ? counts[o] : "–"}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function QuickCheck({ q, delay }: { q: QuickCheckState; delay: number }) {
  const reduced = usePrefersReducedMotion();
  const motion = rise(delay, reduced);
  const statusLine = q.running
    ? "Running in your browser"
    : q.status === "done"
      ? "Finished in your browser"
      : q.status === "failed"
        ? "Stopped in your browser"
        : "Ready in your browser";
  const tiles = q.liveTiles ? q.local.tiles : [];

  return (
    <Card className={`p-6 ${motion.className}`} style={motion.style} data-target="training:quick">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
        <h2 className="text-[17px] font-semibold tracking-[-0.01em] text-ink">Quick check</h2>
        <p className="text-[13px] text-muted">
          {fmtNum(GRID_SIZE)} of {fmtNum(q.population)} sims per generation, best to worst
        </p>
        <span className="ml-auto inline-flex h-7 items-center gap-2 self-center rounded-full bg-tile px-3 text-[13px] font-semibold text-ink-2">
          <span
            className={`h-2 w-2 rounded-full ${q.running ? "animate-pulse-soft bg-accent motion-reduce:animate-none" : q.status === "done" ? "bg-ok" : q.status === "failed" ? "bg-fail" : "bg-track"}`}
          />
          {statusLine}
        </span>
      </div>
      <div className="mt-5 grid gap-6 min-[900px]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <SimTiles tiles={q.local.tiles} tilesAt={q.local.tilesAt} productId={q.productId} spec={q.spec} live={q.liveTiles} />
        <div className="flex min-w-0 flex-col rounded-xl bg-page px-5 pt-4 pb-5 ring-1 ring-line">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <p className="text-[15px] font-semibold text-ink">Fitness</p>
            <span className="ml-auto inline-flex items-center gap-1.5 text-[13px] text-muted">
              <span className="h-0.5 w-4 rounded-full bg-accent" />
              Best
            </span>
            <span className="inline-flex items-center gap-1.5 text-[13px] text-muted">
              <span className="w-4 border-t-2 border-dotted border-faint" />
              Mean
            </span>
          </div>
          <p className="mt-0.5 text-[13px] text-muted">A quick sanity check, not the final policy.</p>
          <div className="mt-3 flex min-h-0 flex-1 flex-col">
            <FitnessChart curve={q.curve} mean={q.meanCurve} total={q.total} />
          </div>
          <div className="mt-4 border-t border-line pt-4">
            <p className="mb-2 text-[13px] font-semibold text-muted">This generation</p>
            <OutcomeBar tiles={tiles} productId={q.productId} />
          </div>
          {q.local.status === "elsewhere" && q.running && (
            <p className="mt-3 text-[13px] text-muted">Replay is in the tab that claimed this run. The counter still follows it.</p>
          )}
          {(q.local.error || q.sse?.error) && q.status === "failed" && <p className="mt-3 text-[13px] text-fail-ink">{q.local.error || q.sse?.error}</p>}
        </div>
      </div>
    </Card>
  );
}

function rewardDelta(curve: [number, number][]): { text: string; up: boolean } | null {
  if (curve.length < 2) return null;
  const start = curve[0][1];
  const last = curve[curve.length - 1][1];
  const up = last >= start;
  const mark = up ? "▲" : "▼";
  if (Math.abs(start) < 1e-6) return { text: `${mark} ${fmtNum(Math.abs(last - start), 1)} vs start`, up };
  const pct = (Math.abs(last - start) / Math.abs(start)) * 100;
  return { text: `${mark} ${fmtNum(pct, 0)}% vs start`, up };
}

function DeepTraining({ delay }: { delay: number }) {
  const reduced = usePrefersReducedMotion();
  const training = useSession((s) => s.training);
  const omniverse = useSession((s) => s.omniverse);
  const tools = useSession((s) => s.tools);
  const isaac = tools["Isaac Lab"];
  const runpod = tools.RunPod;
  const motion = rise(delay, reduced);
  const [chartRef, chart] = useSize<HTMLDivElement>();
  const trainOmni = omniverse?.mode === "train" && omniverse.source === "live" ? omniverse : null;
  const job = training && training.status !== "offline" ? training : null;
  const curve = (job?.curve?.length ? job.curve : trainOmni?.curve) ?? [];
  const reward = job ? job.reward : curve.at(-1)?.[1];
  const video = realClip(job?.video_url) ?? realClip(trainOmni?.video_url);
  const detail = [isaac?.detail, runpod?.detail, trainOmni?.detail].filter(Boolean).join(" · ");
  const hostUp = isaac?.status === "connected" || isaac?.status === "running" || isaac?.status === "ok" || runpod?.status === "connected" || runpod?.status === "running";
  const name = hostName(detail);
  const envs = envCount(trainOmni, detail);
  const delta = rewardDelta(curve);
  const showBoard =
    curve.length > 1 ||
    Boolean(video) ||
    job?.status === "running" ||
    job?.status === "done" ||
    trainOmni?.status === "running" ||
    trainOmni?.status === "done";

  return (
    <Card className={`p-6 ${showBoard ? "min-[900px]:col-span-2" : ""} ${motion.className}`} style={motion.style} data-target="training:deep">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[17px] font-semibold tracking-[-0.01em] text-ink">Deep training</h2>
        {showBoard && hostUp && (
          <span className="ml-auto inline-flex items-center gap-2 rounded-full bg-tile px-3 py-1 text-[13px] font-semibold text-ink-2">
            <span className="h-2 w-2 rounded-full bg-ok" />
            {name} · Connected
          </span>
        )}
        {showBoard && !hostUp && (
          <span className="ml-auto inline-flex items-center gap-2 rounded-full bg-tile px-3 py-1 text-[13px] font-semibold text-ink-2">
            <span className={`h-2 w-2 rounded-full ${job?.status === "running" || trainOmni?.status === "running" ? "bg-agent" : job?.status === "failed" ? "bg-fail" : "bg-ok"}`} />
            {job?.status === "running" || trainOmni?.status === "running"
              ? "Training"
              : job?.status === "failed"
                ? "Stopped"
                : job?.status === "done" || trainOmni?.status === "done"
                  ? "Run finished"
                  : "Job queued"}
          </span>
        )}
      </div>

      {!showBoard && (
        <div className="mt-4 flex items-center gap-3 rounded-xl bg-tile px-4 py-3" role="status">
          <span className={`h-2 w-2 shrink-0 rounded-full ${hostUp ? "bg-ok" : "bg-faint"}`} />
          <div className="min-w-0">
            <p className="text-[15px] font-semibold text-ink">{hostUp ? `${name} · Connected` : "GPU not connected"}</p>
            <p className="text-[13px] leading-snug text-muted">
              {hostUp
                ? "No deep run yet. Ask Mechanic to train on Isaac Lab."
                : job?.status === "queued"
                  ? "A training job is waiting for an NVIDIA GPU host. The quick check above runs without it."
                  : gpuOfflineHint(isaac?.detail)}
            </p>
          </div>
        </div>
      )}

      {showBoard && (
        <>
          <div className="mt-5 grid items-stretch gap-4 min-[900px]:grid-cols-3">
            <div className="flex min-w-0 flex-col">
              <p className="text-[13px] font-semibold text-muted">Learning curve</p>
              <div ref={chartRef} className="mt-2 h-[260px] min-w-0">
                {curve.length > 1 ? (
                  <TrendChart
                    series={[{ points: curve, color: "var(--color-accent)", area: true }]}
                    width={Math.max(160, chart.w)}
                    height={260}
                    xDomain={[0, Math.max(curve.at(-1)?.[0] ?? 1, 1)]}
                    yDomain={[Math.min(0, ...curve.map((p) => p[1])), Math.max(1, ...curve.map((p) => p[1]))]}
                    yTicks={[Math.min(0, ...curve.map((p) => p[1])), Math.max(1, ...curve.map((p) => p[1]))]}
                    formatX={(v) => (v === 0 ? "0" : formatSteps(v))}
                    formatY={(v) => fmtNum(v, 1)}
                  />
                ) : (
                  <div className="flex h-full items-center justify-center rounded-xl bg-tile px-4 text-center text-[13px] text-muted">
                    The curve extends as Isaac Lab reports steps.
                  </div>
                )}
              </div>
            </div>
            <div className="flex min-w-0 flex-col justify-center rounded-xl bg-tile px-5 py-6">
              <p className="text-[13px] font-semibold text-muted">Episode reward</p>
              <p className="num mt-2 text-[32px] leading-none font-bold tracking-[-0.03em] text-ink">
                {reward !== undefined ? fmtNum(reward, 1) : "–"}
              </p>
              {delta && <p className={`mt-2 text-[13px] font-semibold ${delta.up ? "text-ok-ink" : "text-fail-ink"}`}>{delta.text}</p>}
              {job && <p className="num mt-2 text-[13px] text-muted">{formatSteps(job.step)} steps</p>}
            </div>
            <div className="min-w-0">
              {video ? (
                <video
                  key={video}
                  src={assetUrl(video) ?? undefined}
                  className="aspect-video w-full rounded-xl bg-ink object-contain ring-1 ring-line"
                  controls
                  autoPlay
                  muted
                  loop
                  playsInline
                />
              ) : (
                <div className="flex aspect-video items-center justify-center rounded-xl bg-tile px-4 text-center text-[13px] text-muted ring-1 ring-line">
                  The trained flight appears when the run finishes.
                </div>
              )}
              <p className="mt-2 text-[13px] leading-snug text-muted">
                Latest trained flight, Isaac Lab{envs ? `, ${fmtNum(envs)} envs` : ""}
              </p>
            </div>
          </div>
          <p className="mt-4 text-[13px] text-muted">Runs on NVIDIA Isaac Lab in the cloud. Closing this tab won't stop training.</p>
        </>
      )}
    </Card>
  );
}

function useLatestStress(): (StressEvent & { seq: number; at: number }) | null {
  return useSession((s) => {
    let best: (StressEvent & { seq: number; at: number }) | null = null;
    for (const ev of Object.values(s.stress)) {
      if (!best || ev.run > best.run) best = ev;
    }
    return best;
  });
}

function StressSection({ delay }: { delay: number }) {
  const reduced = usePrefersReducedMotion();
  const ev = useLatestStress();
  const [open, setOpen] = useState(false);
  const motion = rise(delay, reduced);
  const failed = ev?.worlds.filter((w) => !w.pass) ?? [];
  const lost = ev ? ev.done - ev.survived : 0;
  const pct = ev && ev.total > 0 ? ev.survived / ev.total : 0;
  const r = 26;
  const circ = 2 * Math.PI * r;

  return (
    <Card className={`p-6 ${motion.className}`} style={motion.style} data-target="training:stress">
      <h2 className="text-[17px] font-semibold tracking-[-0.01em] text-ink">Stress test</h2>
      {!ev && (
        <p className="mt-3 text-[15px] leading-snug text-ink-2">No stress test yet. It runs after a build, across randomized wind, obstacles, and payload.</p>
      )}
      {ev && (
        <>
          <div className="mt-4 flex items-center gap-4">
            <svg width="68" height="68" viewBox="0 0 68 68" aria-hidden>
              <circle cx="34" cy="34" r={r} fill="none" stroke="var(--color-track)" strokeWidth="4" />
              <circle
                cx="34"
                cy="34"
                r={r}
                fill="none"
                stroke="var(--color-ok)"
                strokeWidth="4"
                strokeLinecap="round"
                strokeDasharray={circ}
                strokeDashoffset={circ * (1 - pct)}
                transform="rotate(-90 34 34)"
              />
            </svg>
            <div>
              <p className="num text-[32px] leading-none font-bold tracking-[-0.03em] text-ink">
                {ev.status === "done" ? `${fmtNum(ev.survived)} / ${fmtNum(ev.total)}` : `${fmtNum(ev.done)} / ${fmtNum(ev.total)}`}
              </p>
              <p className="mt-1 text-[15px] font-semibold text-ink-2">{ev.status === "done" ? "worlds survived" : ev.status === "failed" ? "stopped" : "worlds flown"}</p>
            </div>
          </div>
          <p className="mt-3 text-[14px] leading-snug text-muted">
            {ev.status === "done"
              ? lost === 0
                ? "Randomized wind, obstacles, and payload. Every world survived."
                : `Randomized wind, obstacles, and payload. The ${fmtNum(lost)} ${lost === 1 ? "failure is" : "failures are"} saved for review.`
              : ev.status === "failed"
                ? ev.explanation
                : `Flying world ${fmtNum(ev.done)} of ${fmtNum(ev.total)}.`}
          </p>
          {ev.status === "done" && lost > 0 && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="mt-4 h-10 rounded-lg border border-track bg-transparent px-3.5 text-[15px] font-semibold text-ink-2 transition hover:bg-tile"
            >
              {open ? "Hide failures" : "Inspect failures"}
            </button>
          )}
          {open && (
            <div className="mt-4">
              <ul className="space-y-1.5">
                {failed.map((w) => (
                  <li key={w.i} className="flex items-baseline justify-between gap-3 text-[14px]">
                    <span className="font-semibold text-ink">World {w.i}</span>
                    <span className="text-fail-ink">{FAIL_REASON[w.reason] ?? w.reason}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-3">
                <StressCard run={ev.run} />
              </div>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function useIsaacTaskLine() {
  const log = useSession((s) => s.log);
  return useMemo(() => {
    for (let i = log.length - 1; i >= 0; i--) {
      const ev = log[i].ev;
      if (ev.type !== "tool" || canonicalToolName(ev.name) !== "Isaac Lab") continue;
      return ev.detail.match(/Isaac-[\w-]+/)?.[0] ?? null;
    }
    return null;
  }, [log]);
}

export function TrainingView() {
  const task = useIsaacTaskLine();
  const q = useQuickCheck();
  return (
    <div className="h-full min-h-0 overflow-y-auto scroll-soft">
      <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-4 px-6 py-8 min-[900px]:px-8">
        <Hero q={q} task={task} />
        <QuickCheck q={q} delay={80} />
        <div className="grid items-stretch gap-4 min-[900px]:grid-cols-2">
          <DeepTraining delay={160} />
          <StressSection delay={240} />
        </div>
      </div>
    </div>
  );
}
