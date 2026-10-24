// Simulation tab: replays `sim` trajectories, before/after of the selected run and
// the one before it, with an altitude chart on the shared playhead.
import { Pause, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Run } from "../../events/store";
import { fmtNum } from "../../lib/format";
import { useSelectedVersion, useVersions } from "../../lib/hooks";
import { TrendChart } from "../ui/TrendChart";
import { GripSimView } from "./GripSimView";
import { SimScene, trajectoryBounds } from "./Scenes";
import { seek, setPlaying, useSimClockDriver, useSimTime } from "./simClock";

export const RUN_COLOR = { pass: "#2ed3ae", fail: "#ff5a5f" } as const;

function RunChip({ run, label }: { run: Run; label: string }) {
  const pass = run.result === "pass";
  return (
    <span
      className={`inline-flex h-8 items-center gap-2 rounded-full bg-white/95 px-3.5 text-[13px] font-bold shadow-[var(--shadow-pill)] ${
        pass ? "text-ok-ink" : "text-fail-ink"
      }`}
    >
      <span className="h-2 w-2 rounded-full" style={{ background: RUN_COLOR[run.result] }} />
      {label} · Lauf {run.run} · {pass ? "besteht" : "sackt ab"}
    </span>
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

export function SimView() {
  const grip = useSelectedVersion()?.run.kind === "grip";
  return grip ? <GripSimView /> : <HoverSimView />;
}

function HoverSimView() {
  const all = useVersions();
  const after = useSelectedVersion();
  const before = after ? all.find((v) => v.n === after.n - 1) ?? null : null;
  const duration = Math.max(...all.map((v) => v.run.trajectory.at(-1)?.[0] ?? 0), 1);
  useSimClockDriver(duration);
  const { t, playing } = useSimTime(20);
  const [chartRef, chartW] = useWidth<HTMLDivElement>();
  const bounds = useMemo(() => trajectoryBounds([after, before].flatMap((v) => (v ? [v.run] : []))), [after, before]);

  if (!after) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <p className="text-[18px] font-semibold text-ink-2">Noch kein Simulationslauf</p>
        <p className="max-w-sm text-[15px] text-muted">Bolzen testet in MuJoCo, sobald Teile und Rahmen stehen. Jeder Lauf wird hier abgespielt.</p>
      </div>
    );
  }

  const toAlt = (run: Run) =>
    run.trajectory.filter((s) => s[0] <= t + 1e-6).map((s) => [s[0], s[3]] as [number, number]);
  const series = [
    ...(before ? [{ points: toAlt(before.run), color: RUN_COLOR[before.run.result], dashed: true, glow: true }] : []),
    { points: toAlt(after.run), color: RUN_COLOR[after.run.result], area: true },
  ];
  const zMax = Math.max(0.7, ...all.flatMap((v) => v.run.trajectory.map((s) => s[3])));

  return (
    <div className="flex h-full flex-col">
      <div className="relative grid min-h-0 flex-1 gap-0" style={{ gridTemplateColumns: before ? "minmax(0,1fr) minmax(0,1fr)" : "minmax(0,1fr)" }}>
        {before && (
          <div className="relative min-h-0 min-w-0 overflow-hidden border-r border-line">
            <SimScene run={before.run} primary={false} color={RUN_COLOR[before.run.result]} bounds={bounds} />
            <div className="absolute top-3 left-3">
              <RunChip run={before.run} label="Vorher" />
            </div>
          </div>
        )}
        <div className="relative min-h-0 min-w-0 overflow-hidden">
          <SimScene run={after.run} primary color={RUN_COLOR[after.run.result]} bounds={bounds} />
          <div className="absolute top-3 left-3">
            <RunChip run={after.run} label={before ? "Nachher" : "Lauf"} />
          </div>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-4 border-t border-line bg-card/80 px-4 py-2.5">
        <button
          type="button"
          onClick={() => setPlaying(!playing)}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-ink text-white shadow-[var(--shadow-pill)]"
          aria-label={playing ? "Pause" : "Abspielen"}
        >
          {playing ? <Pause className="h-4 w-4" fill="currentColor" /> : <Play className="h-4 w-4 translate-x-[1px]" fill="currentColor" />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between text-[13px] font-semibold text-muted">
            <span>Höhe über Zeit</span>
            <span className="num text-ink-2">
              {fmtNum(t, 1)} / {fmtNum(duration, 1)} s
            </span>
          </div>
          <div ref={chartRef} className="cursor-pointer" onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            seek(((e.clientX - rect.left) / Math.max(1, rect.width - 40)) * duration);
          }}>
            <TrendChart
              series={series}
              width={chartW}
              height={70}
              xDomain={[0, duration]}
              yDomain={[0, zMax]}
              yTicks={[0, 0.5]}
              formatY={(v) => `${fmtNum(v * 100)} cm`}
              marker={{ y: 0.5, label: "Ziel 50 cm" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
