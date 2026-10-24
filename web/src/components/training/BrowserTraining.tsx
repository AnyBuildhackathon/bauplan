// Simulation tab, training pane: 16 of each generation's 64 MuJoCo runs replayed in a
// grid, the rollout counter up to 1,024, the fitness curve, and the best run large.
import { useEffect, useMemo, useRef, useState } from "react";
import { productFor } from "../../sim/products";
import { GRID_SIZE, REPLAY_SPEED, useTrainer, type Tile } from "../../sim/trainer";
import type { DroneSpec } from "../../sim/drone";
import type { GripperSpec } from "../../sim/gripper";
import { fmtGain, fmtNum } from "./format";
import { TrendChart } from "../ui/TrendChart";
import { drawDroneFrame, themeColors, type DrawStyle } from "./drawDrone";
import { drawGripperFrame } from "./drawGripper";
import { useBrowserTrainingEvent } from "./useBrowserTraining";

/** Callback ref, so the observer follows the element even when it remounts (after a reset). */
function useSize<T extends HTMLElement>() {
  const [el, ref] = useState<T | null>(null);
  const [size, setSize] = useState({ w: 400, h: 300 });
  useEffect(() => {
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [ref, size] as const;
}

type Renderer = (ctx: CanvasRenderingContext2D, w: number, h: number, frames: Float32Array, frameSize: number, index: number, style: DrawStyle) => void;

/** How each product's rollout frames are drawn. */
function rendererFor(productId: string, spec: unknown): Renderer {
  if (productId === "gripper") return (ctx, w, h, f, n, i, st) => drawGripperFrame(ctx, w, h, f, n, i, st, spec as GripperSpec | null);
  const armM = ((spec as DroneSpec | null)?.arm_length_mm ?? 36) / 1000;
  return (ctx, w, h, f, n, i, st) => drawDroneFrame(ctx, w, h, f, n, i, st, armM);
}

function tileColor(t: { crashed: boolean; held: boolean }, c: ReturnType<typeof themeColors>) {
  return t.crashed ? c.fail : t.held ? c.ok : c.agent;
}

/** Draws every tile canvas and the large replay from one animation loop. */
function useReplayLoop(
  tiles: Tile[],
  tilesAt: number,
  canvases: React.RefObject<(HTMLCanvasElement | null)[]>,
  big: React.RefObject<HTMLCanvasElement | null>,
  draw: Renderer,
) {
  const best = useTrainer((s) => s.best);
  useEffect(() => {
    let raf = 0;
    const colors = themeColors();
    const bigStart = performance.now();
    const loop = () => {
      const now = performance.now();
      tiles.forEach((tile, k) => {
        const cv = canvases.current?.[k];
        const ctx = cv?.getContext("2d");
        if (!cv || !ctx) return;
        const frames = Math.floor(tile.frames.length / Math.max(1, tile.frameSize));
        const index = Math.floor((((now - tilesAt) / 1000) * REPLAY_SPEED * tile.frameHz));
        fit(cv);
        draw(ctx, cv.width, cv.height, tile.frames, tile.frameSize, Math.min(index, frames - 1), {
          color: tileColor(tile, colors),
          ink: colors.ink,
          faint: colors.faint,
          line: colors.line,
        });
      });
      const bc = big.current;
      const bctx = bc?.getContext("2d");
      if (bc && bctx && best) {
        fit(bc);
        const frames = Math.floor(best.frames.length / Math.max(1, best.frameSize));
        // The best run loops at real time with a short hold at the end.
        const loopFrames = frames + best.frameHz;
        const index = Math.floor(((now - bigStart) / 1000) * best.frameHz) % Math.max(1, loopFrames);
        const crashed = best.metrics.crashed === true;
        const held = best.metrics.held === true;
        draw(bctx, bc.width, bc.height, best.frames, best.frameSize, Math.min(index, frames - 1), {
          color: tileColor({ crashed, held }, colors),
          ink: colors.ink,
          faint: colors.faint,
          line: colors.line,
          big: true,
        });
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [tiles, tilesAt, canvases, big, best, draw]);
}

/** Matches the canvas backing store to its CSS size at device pixel ratio. */
function fit(cv: HTMLCanvasElement) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = Math.round(cv.clientWidth * dpr);
  const h = Math.round(cv.clientHeight * dpr);
  if (cv.width !== w || cv.height !== h) {
    cv.width = w;
    cv.height = h;
  }
}



export function BrowserTraining() {
  const local = useTrainer();
  const sse = useBrowserTrainingEvent();
  const canvases = useRef<(HTMLCanvasElement | null)[]>([]);
  const big = useRef<HTMLCanvasElement | null>(null);
  const [chartRef, chartSize] = useSize<HTMLDivElement>();
  const here = local.status === "running" || local.status === "done" || local.status === "claiming";
  const spec = here ? local.spec : sse?.spec ?? null;
  const productId = (here ? local.productId : sse?.product) ?? "drone";
  const draw = useMemo(() => rendererFor(productId, spec), [productId, spec]);
  useReplayLoop(local.tiles, local.tilesAt, canvases, big, draw);

  let product: ReturnType<typeof productFor> | null = null;
  try {
    product = productFor(productId);
  } catch {
    product = null;
  }
  const population = (here ? local.population : sse?.population) ?? 64;
  const generations = (here ? local.generations : sse?.generations) ?? 16;
  const total = population * generations;
  const rollouts = here ? local.rollouts : sse?.step ?? 0;
  const generation = here ? local.generation : sse?.generation ?? 0;
  const curve = here ? local.curve : sse?.curve ?? [];
  const meanCurve = here ? local.meanCurve : [];
  const bestParams = here ? local.best?.params : sse?.best_params ?? undefined;
  const bestMetrics = here ? local.best?.metrics : sse?.best_metrics ?? undefined;
  const status = here ? local.status : sse?.status ?? "idle";
  const bestScore = curve.at(-1)?.[1];

  if (!sse && local.status === "idle") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <p className="text-[18px] font-semibold text-ink-2">No training yet</p>
        <p className="max-w-sm text-[15px] text-muted">Ask Bolzen to “train it”: 1,024 MuJoCo simulations run right here in the browser.</p>
      </div>
    );
  }

  const statusText =
    status === "done"
      ? "done"
      : status === "failed"
        ? `failed${local.error ? ": " + local.error : sse?.error ? ": " + sse.error : ""}`
        : status === "queued" || status === "claiming"
          ? "starting workers"
          : local.status === "elsewhere"
            ? "running in another dashboard tab"
            : `generation ${generation} / ${generations}`;

  return (
    <div className="grid h-full min-h-0 gap-3 p-3" style={{ gridTemplateColumns: "minmax(0,1.3fr) minmax(0,1fr)" }}>
      <div className="flex min-h-0 min-w-0 flex-col gap-2">
        <div className="flex items-baseline gap-3 px-1">
          <span className="num text-[34px] leading-none font-extrabold tracking-[-0.02em] text-ink" data-target="training:counter">
            {fmtNum(rollouts)}
          </span>
          <span className="num text-[16px] font-bold whitespace-nowrap text-muted">/ {fmtNum(total)} simulations</span>
          <span className="ml-auto truncate text-[13px] font-semibold text-muted">{statusText}</span>
        </div>
        <div className="grid min-h-0 flex-1 grid-cols-4 grid-rows-4 gap-1.5">
          {Array.from({ length: GRID_SIZE }, (_, k) => {
            const tile = local.tiles[k];
            return (
              <div key={k} className="relative min-h-0 min-w-0 overflow-hidden rounded-[12px] bg-white/70">
                <canvas ref={(el) => void (canvases.current[k] = el)} className="absolute inset-0 h-full w-full" />
                {tile && (
                  <span className="num absolute top-1 left-1.5 text-[11px] font-bold text-muted">
                    #{tile.rank} · {fmtNum(tile.score, 0)}
                  </span>
                )}
              </div>
            );
          })}
        </div>
        <p className="px-1 text-[12px] text-muted">
          {product?.goal ?? "Training"} · {local.workers ? `${local.workers} Web Workers` : "MuJoCo WASM"} · grid: every 4th of 64 by rank, at {REPLAY_SPEED}× speed
        </p>
      </div>

      <div className="flex min-h-0 min-w-0 flex-col gap-2">
        <div className="relative min-h-0 flex-[1.4] overflow-hidden rounded-[16px] bg-white/80">
          <canvas ref={big} className="absolute inset-0 h-full w-full" />
          <div className="absolute top-2.5 left-3 text-[13px] font-bold text-ink-2">
            Best so far{local.best ? ` · gen ${local.best.generation}` : ""}
          </div>
          {bestMetrics && product && (
            <div className="num absolute right-3 bottom-2.5 text-right text-[13px] font-semibold text-ink-2">
              {product.describe(bestMetrics).lines.map((line) => (
                <div key={line}>{line}</div>
              ))}
            </div>
          )}
          {!here && !local.best && (
            <div className="absolute inset-0 flex items-center justify-center text-[14px] text-muted">Replay shows in the tab that runs the training.</div>
          )}
        </div>
        <div className="shrink-0 rounded-[16px] bg-white/80 px-3 pt-2 pb-1">
          <div className="flex items-baseline justify-between text-[13px] font-semibold text-muted">
            <span>Fitness (best, mean)</span>
            <span className="num text-ink-2">{bestScore !== undefined ? fmtNum(bestScore, 1) : "–"} / 100</span>
          </div>
          <div ref={chartRef}>
            <TrendChart
              series={[
                ...(meanCurve.length ? [{ points: meanCurve, color: "#a3a3aa", dashed: true }] : []),
                { points: curve, color: "#ff8a3d", area: true, glow: true },
              ]}
              width={chartSize.w}
              height={92}
              xDomain={[0, total]}
              yDomain={[0, 100]}
              yTicks={[0, 50, 100]}
              formatY={(v) => fmtNum(v)}
            />
          </div>
        </div>
        {bestParams && product && (
          <div className="grid shrink-0 grid-cols-4 gap-1.5" data-target="training:gains">
            {product.params.map((p) => (
              <div key={p.name} className="rounded-[12px] bg-white/80 px-2.5 py-1.5">
                <div className="truncate text-[11px] font-semibold text-muted">{p.label}</div>
                <div className="num text-[15px] font-bold text-ink">{bestParams[p.name] !== undefined ? fmtGain(bestParams[p.name]) : "–"}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
