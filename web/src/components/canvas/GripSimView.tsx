// Simulation tab for the gripper: replays `sim` events of kind "grip" as a front view.
// The hand lifts 15 cm and shakes; the object follows only as far as friction holds it.
// Before/after shows the previous run next to the selected one, on the shared playhead.
import { Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Run } from "../../events/store";
import { fmtNum } from "../../lib/format";
import { useSelectedVersion, useVersions } from "../../lib/hooks";
import { TrendChart } from "../ui/TrendChart";
import { seek, setPlaying, useSimClockDriver, useSimTime } from "./simClock";

const COLOR = { pass: "#2ed3ae", fail: "#ff5a5f" } as const;
const OBJECT_H = 120;

/** Linear lookup in a [t, value] series. */
function at(series: [number, number][], t: number): number {
  if (!series.length) return 0;
  if (t <= series[0][0]) return series[0][1];
  for (let i = 1; i < series.length; i++) {
    if (series[i][0] >= t) {
      const [t0, v0] = series[i - 1];
      const [t1, v1] = series[i];
      return v0 + ((v1 - v0) * (t - t0)) / Math.max(1e-9, t1 - t0);
    }
  }
  return series[series.length - 1][1];
}

const objectRise = (run: Run) => run.trajectory.map((s) => [s[0], s[3]] as [number, number]);

function GripStage({ run, t, label }: { run: Run; t: number; label: string }) {
  const width = run.object_width_mm ?? 66;
  const hand = at(run.hand ?? [], t) * 1000;
  const obj = at(objectRise(run), t) * 1000;
  const pass = run.result === "pass";
  // Scene in mm: floor at y = 0, up is negative SVG y. The pads hold the object's middle.
  const floor = 300;
  const objTop = floor - obj - OBJECT_H;
  const padY = floor - hand - OBJECT_H / 2 - 20;
  const palmY = padY - 80;
  const gap = width / 2;
  const slipping = hand - obj > 10;
  return (
    <div className="relative h-full min-h-0 min-w-0">
      <svg viewBox="-150 0 300 330" className="h-full w-full" preserveAspectRatio="xMidYMid meet" role="img" aria-label={`${label}: grip test ${run.run}`}>
        <line x1={-150} x2={150} y1={floor} y2={floor} stroke="#d6d5de" strokeWidth={2} />
        {/* Object: a can between the pads. */}
        <rect x={-gap} y={objTop} width={width} height={OBJECT_H} rx={8} fill={pass ? "#e8faf5" : slipping ? "#ffecec" : "#f4f4f7"} stroke={pass ? COLOR.pass : slipping ? COLOR.fail : "#9a9aa6"} strokeWidth={2.5} />
        <text x={0} y={objTop + OBJECT_H / 2 + 5} textAnchor="middle" fontSize={14} fontWeight={700} fill="#55565f">
          {fmtNum(run.payload_g ?? 0, 0)} g
        </text>
        {/* Hand: palm, two fingers, black pads on the inside. */}
        <rect x={-gap - 40} y={palmY} width={width + 80} height={14} rx={4} fill="#c9ccd3" />
        <rect x={-gap - 26} y={palmY + 10} width={14} height={padY - palmY + 30} rx={5} fill="#e7e8ec" stroke="#b9bcc6" />
        <rect x={gap + 12} y={palmY + 10} width={14} height={padY - palmY + 30} rx={5} fill="#e7e8ec" stroke="#b9bcc6" />
        <rect x={-gap - 12} y={padY} width={12} height={40} rx={2} fill="#2b2d33" />
        <rect x={gap} y={padY} width={12} height={40} rx={2} fill="#2b2d33" />
        <rect x={-14} y={palmY - 34} width={28} height={34} rx={4} fill="#3b5bdb" />
        {/* Squeeze arrows. */}
        <path d={`M ${-gap - 52} ${padY + 20} l 18 0 m -6 -6 l 6 6 l -6 6`} stroke="#ff8a3d" strokeWidth={3} fill="none" strokeLinecap="round" />
        <path d={`M ${gap + 52} ${padY + 20} l -18 0 m 6 -6 l -6 6 l 6 6`} stroke="#ff8a3d" strokeWidth={3} fill="none" strokeLinecap="round" />
      </svg>
      <div className="absolute top-3 left-3 flex flex-wrap items-center gap-2">
        <span className={`inline-flex h-8 items-center gap-2 rounded-full bg-white/95 px-3.5 text-[13px] font-bold shadow-[var(--shadow-pill)] ${pass ? "text-ok-ink" : "text-fail-ink"}`}>
          <span className="h-2 w-2 rounded-full" style={{ background: COLOR[run.result] }} />
          {label} · Run {run.run} · {pass ? "holds" : "slips"}
        </span>
        <span className="num inline-flex h-8 items-center rounded-full bg-white/95 px-3.5 text-[13px] font-semibold text-ink-2 shadow-[var(--shadow-pill)]">
          {fmtNum(run.force_n ?? 0, 1)} N per finger
        </span>
      </div>
    </div>
  );
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export function GripSimView() {
  const all = useVersions();
  const after = useSelectedVersion();
  const before = after ? all.find((v) => v.n === after.n - 1) ?? null : null;
  const duration = Math.max(...all.map((v) => v.run.trajectory.at(-1)?.[0] ?? 0), 1);
  useSimClockDriver(duration);
  const { t, playing } = useSimTime(30);
  const [chartRef, chartW] = useWidth<HTMLDivElement>();
  if (!after) return null;

  const upTo = (run: Run) => objectRise(run).filter((s) => s[0] <= t + 1e-6);
  const series = [
    ...(before ? [{ points: upTo(before.run), color: COLOR[before.run.result], dashed: true, glow: true }] : []),
    { points: upTo(after.run), color: COLOR[after.run.result], area: true },
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="relative grid min-h-0 flex-1" style={{ gridTemplateColumns: before ? "minmax(0,1fr) minmax(0,1fr)" : "minmax(0,1fr)" }}>
        {before && (
          <div className="min-h-0 min-w-0 border-r border-line">
            <GripStage run={before.run} t={t} label="Before" />
          </div>
        )}
        <GripStage run={after.run} t={t} label={before ? "After" : "Run"} />
      </div>
      <div className="flex shrink-0 items-center gap-4 border-t border-line bg-card/80 px-4 py-2.5">
        <button
          type="button"
          onClick={() => setPlaying(!playing)}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-ink text-white shadow-[var(--shadow-pill)]"
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? <Pause className="h-4 w-4" fill="currentColor" /> : <Play className="h-4 w-4 translate-x-[1px]" fill="currentColor" />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between text-[13px] font-semibold text-muted">
            <span>Object lifted over time</span>
            <span className="num text-ink-2">
              {fmtNum(t, 1)} / {fmtNum(duration, 1)} s
            </span>
          </div>
          <div
            ref={chartRef}
            className="cursor-pointer"
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              seek(((e.clientX - rect.left) / Math.max(1, rect.width - 40)) * duration);
            }}
          >
            <TrendChart
              series={series}
              width={chartW}
              height={70}
              xDomain={[0, duration]}
              yDomain={[0, 0.18]}
              yTicks={[0, 0.15]}
              formatY={(v) => `${fmtNum(v * 100)} cm`}
              marker={{ y: 0.15, label: "Lift 15 cm" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
