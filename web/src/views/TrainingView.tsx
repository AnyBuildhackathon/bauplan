// Training page: a browser quick check (1,024 MuJoCo sims), Isaac Lab on a GPU host,
// and the latest stress test. Isaac data is read from session events only.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { DroneSpec } from "../sim/drone";
import type { GripperSpec } from "../sim/gripper";
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
    <div className="grid grid-cols-2 gap-2 min-[900px]:grid-cols-4" data-target="training:tiles">
      {Array.from({ length: GRID_SIZE }, (_, k) => {
        const tile = tiles[k];
        const label = `Sim #${padSim(tile?.rank ?? k + 1)}`;
        return (
          <div
            key={k}
            title={label}
            className="group relative aspect-square overflow-hidden rounded-lg bg-tile transition-transform duration-150 ease-out hover:z-10 hover:scale-[1.04] motion-reduce:transition-none motion-reduce:hover:scale-100"
          >
            <canvas ref={(el) => void (canvases.current[k] = el)} className="absolute inset-0 h-full w-full" aria-hidden />
            <span className="pointer-events-none absolute inset-x-1 bottom-1 rounded-md bg-ink/90 px-1.5 py-0.5 text-center text-[13px] font-semibold text-white opacity-0 transition-opacity duration-150 group-hover:opacity-100 motion-reduce:transition-none">
              {label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function FitnessSpark({ points }: { points: [number, number][] }) {
  const reduced = usePrefersReducedMotion();
  const uid = useId().replace(/:/g, "");
  if (points.length < 2) {
    return <div className="flex h-[88px] items-end text-[13px] text-muted">Fitness appears as generations finish.</div>;
  }
  const w = 280;
  const h = 88;
  const vals = points.map((p) => p[1]);
  const min = Math.min(...vals);
  const max = Math.max(...vals, min + 1);
  const sx = (i: number) => (i / (points.length - 1)) * w;
  const sy = (v: number) => 8 + (1 - (v - min) / (max - min)) * (h - 16);
  let line = `M${sx(0)},${sy(points[0][1])}`;
  for (let i = 1; i < points.length; i++) line += ` L${sx(i)},${sy(points[i][1])}`;
  const area = `${line} L${w},${h} L0,${h} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-[88px] w-full" role="img" aria-label="Fitness curve">
      <path d={area} fill={`url(#${uid})`} />
      <path
        d={line}
        fill="none"
        stroke="var(--color-fail)"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={reduced ? 0 : 1}
        className={reduced ? undefined : "animate-spark-draw motion-reduce:animate-none"}
      />
      <defs>
        <linearGradient id={uid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--color-fail)" stopOpacity="0.08" />
          <stop offset="1" stopColor="var(--color-fail)" stopOpacity="0" />
        </linearGradient>
      </defs>
    </svg>
  );
}

function QuickCheck({ delay }: { delay: number }) {
  const reduced = usePrefersReducedMotion();
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
  const curve = here ? local.curve : sse?.curve ?? [];
  const status = here ? local.status : sse?.status ?? "idle";
  const running = status === "running" || status === "claiming" || status === "queued" || local.status === "elsewhere";
  const liveTiles = here && local.tiles.length > 0;
  const motion = rise(delay, reduced);
  const busy = local.status === "running" || local.status === "claiming";

  function start() {
    if (busy) return;
    if (mode === "live" && link === "open") void useSource.getState().sendPrompt("train it");
    else void runLocalTraining("drone", NOMINAL_DRONE);
  }

  const statusLine = running
    ? "Running in your browser"
    : status === "done"
      ? "Finished in your browser"
      : status === "failed"
        ? "Stopped in your browser"
        : "Ready in your browser";

  return (
    <Card className={`p-6 ${motion.className}`} style={motion.style} data-target="training:quick">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">Quick check</h2>
        <span className="ml-auto inline-flex items-center gap-2 text-[13px] font-semibold text-ink-2">
          <span className={`h-2 w-2 rounded-full ${running ? "animate-pulse-soft bg-fail motion-reduce:animate-none" : "bg-track"}`} />
          {statusLine}
        </span>
      </div>
      <div className="mt-5 grid items-start gap-6 min-[900px]:grid-cols-[minmax(0,2fr)_minmax(200px,1fr)]">
        <SimTiles tiles={local.tiles} tilesAt={local.tilesAt} productId={productId} spec={spec} live={liveTiles} />
        <div className="flex min-w-0 flex-col min-[900px]:sticky min-[900px]:top-4 min-[900px]:self-start">
          <div className="num text-[40px] leading-none font-bold tracking-[-0.03em] text-ink" data-target="training:counter">
            {fmtNum(rollouts)}
            <span className="text-[22px] font-semibold text-muted"> / {fmtNum(total)}</span>
          </div>
          <p className="mt-3 text-[13px] leading-snug text-muted">Fitness climbing — quick sanity check, not the final policy.</p>
          <div className="mt-3">
            <FitnessSpark points={curve} />
          </div>
          {local.status === "elsewhere" && (
            <p className="mt-2 text-[13px] text-muted">Replay is in the tab that claimed this run. The counter still follows it.</p>
          )}
          {(local.error || sse?.error) && status === "failed" && (
            <p className="mt-2 text-[13px] text-fail-ink">{local.error || sse?.error}</p>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={start}
            className="mt-4 h-10 self-start rounded-lg bg-fail px-4 text-[15px] font-semibold text-white transition hover:bg-fail-ink disabled:cursor-not-allowed disabled:opacity-45"
          >
            {status === "done" || status === "failed" ? "Run quick check again" : "Start quick check"}
          </button>
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
    <Card className={`p-6 ${motion.className}`} style={motion.style} data-target="training:deep">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">Deep training</h2>
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
          <span className={`h-2 w-2 shrink-0 rounded-full ${hostUp ? "bg-ok" : "bg-track"}`} />
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
                    series={[{ points: curve, color: "#e5484d", area: true }]}
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
                Latest trained flight — Isaac Lab{envs ? `, ${fmtNum(envs)} envs` : ""}
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
    <Card className={`w-full p-6 min-[900px]:max-w-[540px] ${motion.className}`} style={motion.style} data-target="training:stress">
      <h2 className="text-[13px] font-semibold tracking-[0.08em] text-muted uppercase">Stress test</h2>
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
                stroke="var(--color-fail)"
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
  const reduced = usePrefersReducedMotion();
  const task = useIsaacTaskLine();
  const head = rise(0, reduced);
  return (
    <div className="h-full min-h-0 overflow-y-auto scroll-soft">
      <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-4 px-6 py-8 min-[900px]:px-8">
        <header className={head.className} style={head.style}>
          <h1 className="text-[28px] leading-none font-semibold tracking-[-0.02em] text-ink min-[900px]:text-[32px]">Training</h1>
          <p className="mt-2 max-w-[46rem] text-[15px] leading-snug text-muted">
            Teach the controller to fly — quick check in your browser, deep training in the cloud.
            {task ? ` ${task}.` : ""}
          </p>
        </header>
        <QuickCheck delay={80} />
        <DeepTraining delay={160} />
        <StressSection delay={240} />
      </div>
    </div>
  );
}
