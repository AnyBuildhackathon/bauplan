/**
 * The design optimizer's chat card: every variant as a point (weight against flight time,
 * colour = price), the Pareto front as a line, the current build as a square. Clicking a
 * point or a row builds that variant as the next version.
 */
import { useState } from "react";
import { CircleCheck, CircleX, Loader2, Sparkles } from "lucide-react";
import { useSession } from "../../events/store";
import { useSource } from "../../events/source";
import type { OptimizeEvent, OptimizeNumber, OptimizeVariant } from "../../events/types";
import { fmtNum } from "../../lib/format";

const AXIS: Record<OptimizeNumber, { label: string; unit: string; digits: number }> = {
  weight_g: { label: "Weight", unit: "g", digits: 1 },
  flight_time_min: { label: "Flight time", unit: "min", digits: 1 },
  price_eur: { label: "Price", unit: "€", digits: 2 },
  thrust_to_weight: { label: "Thrust/weight", unit: ": 1", digits: 2 },
  arm_stiffness: { label: "Arm stiffness", unit: "×", digits: 2 },
};
const GOAL_LABEL: Record<string, string> = { lighter: "lighter", cheaper: "cheaper", longer_runtime: "longer runtime", stronger: "stronger" };

const W = 320;
const H = 176;
const PAD = { left: 34, right: 12, top: 12, bottom: 30 };

function scale(values: number[]): (v: number) => number {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  return (v) => (v - lo + span * 0.08) / (span * 1.16);
}

function Chart({ ev, busy, onPick, hover, setHover }: { ev: OptimizeEvent; busy: boolean; onPick: (v: OptimizeVariant) => void; hover: string | null; setHover: (id: string | null) => void }) {
  const { x, y, color } = ev.axes;
  const base = ev.baseline!;
  const points = [...ev.variants, base];
  const sx = scale(points.map((p) => p[x]));
  const limit = ev.keep[y === "flight_time_min" ? "min_flight_time_min" : y === "arm_stiffness" ? "min_arm_stiffness" : ""];
  const sy = scale([...points.map((p) => p[y]), ...(limit !== undefined ? [limit] : [])]);
  const prices = ev.variants.map((v) => v[color]);
  const lo = Math.min(...prices);
  const hi = Math.max(...prices);
  const px = (v: number) => PAD.left + sx(v) * (W - PAD.left - PAD.right);
  const py = (v: number) => H - PAD.bottom - sy(v) * (H - PAD.top - PAD.bottom);
  // Cheaper is lighter teal, dearer is full accent.
  const fill = (v: OptimizeVariant) => `color-mix(in srgb, var(--color-accent) ${hi > lo ? Math.round(45 + ((v[color] - lo) / (hi - lo)) * 55) : 75}%, var(--color-accent-soft))`;
  const front = ev.variants.filter((v) => v.pareto).sort((a, b) => a[x] - b[x]);
  const canPick = !ev.applied && !busy;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full" role="img" aria-label={`${AXIS[y].label} against ${AXIS[x].label} for ${ev.variants.length} variants`}>
      <line x1={PAD.left} y1={H - PAD.bottom} x2={W - PAD.right} y2={H - PAD.bottom} stroke="var(--color-track)" />
      <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={H - PAD.bottom} stroke="var(--color-track)" />
      {limit !== undefined && py(limit) > PAD.top && py(limit) < H - PAD.bottom && (
        <g>
          <line x1={PAD.left} x2={W - PAD.right} y1={py(limit)} y2={py(limit)} stroke="var(--color-fail)" strokeDasharray="4 3" strokeOpacity={0.6} />
          <text x={W - PAD.right} y={py(limit) - 3} textAnchor="end" className="fill-fail-ink text-[9px] font-semibold">
            keep ≥ {fmtNum(limit, 0)} {AXIS[y].unit}
          </text>
        </g>
      )}
      {front.length > 1 && (
        <polyline points={front.map((v) => `${px(v[x])},${py(v[y])}`).join(" ")} fill="none" stroke="var(--color-accent)" strokeWidth={1.5} strokeOpacity={0.5} />
      )}
      <rect x={px(base[x]) - 4.5} y={py(base[y]) - 4.5} width={9} height={9} rx={1.5} fill="var(--color-ink)" />
      <text x={px(base[x]) + 8} y={py(base[y]) + 3.5} className="fill-ink text-[10px] font-bold">
        {base.label}
      </text>
      {ev.variants.map((v) => {
        const cx = px(v[x]);
        const cy = py(v[y]);
        const on = hover === v.id || ev.applied === v.id;
        return (
          <g
            key={v.id}
            role="button"
            aria-label={`Build variant ${v.id}`}
            data-target={`optimize:${v.id}`}
            className={canPick ? "cursor-pointer" : ""}
            onMouseEnter={() => setHover(v.id)}
            onMouseLeave={() => setHover(null)}
            onClick={() => canPick && onPick(v)}
          >
            <circle cx={cx} cy={cy} r={14} fill="transparent" />
            <circle
              cx={cx}
              cy={cy}
              r={on ? 8 : 6.5}
              fill={v.feasible ? fill(v) : "var(--color-card)"}
              stroke={v.feasible ? (v.pareto ? "var(--color-ink)" : "var(--color-accent)") : "var(--color-fail)"}
              strokeWidth={v.pareto || on ? 2 : 1.25}
            />
            <text x={cx} y={cy - 10} textAnchor="middle" className={`text-[10px] font-bold ${v.feasible ? "fill-ink-2" : "fill-fail-ink"}`}>
              {v.id}
              {ev.recommended === v.id ? " ★" : ""}
            </text>
          </g>
        );
      })}
      <text x={(PAD.left + W - PAD.right) / 2} y={H - 6} textAnchor="middle" className="fill-muted text-[10px] font-semibold">
        {AXIS[x].label} ({AXIS[x].unit}) →
      </text>
      <text x={10} y={(PAD.top + H - PAD.bottom) / 2} textAnchor="middle" transform={`rotate(-90 10 ${(PAD.top + H - PAD.bottom) / 2})`} className="fill-muted text-[10px] font-semibold">
        {AXIS[y].label} ({AXIS[y].unit.replace(": ", "")}) →
      </text>
    </svg>
  );
}

export function OptimizeCard({ optimizeId }: { optimizeId: string }) {
  const ev = useSession((s) => s.optimizes[optimizeId]);
  const apply = useSource((s) => s.applyVariant);
  const [hover, setHover] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  if (!ev) return null;
  const goals = ev.goals.map((g) => GOAL_LABEL[g] ?? g).join(" and ");
  if (ev.status === "running" || !ev.baseline) {
    return (
      <div className="rounded-[14px] bg-card p-3 ring-1 ring-line" data-target="optimize">
        <div className="flex items-center gap-2 text-[14px] font-bold text-accent">
          <Loader2 className="h-4.5 w-4.5 animate-spin" /> Optimizer · exploring variants for {goals}
        </div>
      </div>
    );
  }
  const busy = picked !== null && !ev.applied;
  const onPick = (v: OptimizeVariant) => {
    setPicked(v.id);
    // A refused start (Mechanic still building) frees the buttons again.
    void apply(ev.id, v.id).then((ok) => ok || setPicked(null));
  };
  const shown = ev.variants.find((v) => v.id === (hover ?? ev.applied ?? picked ?? ev.recommended));
  const { x, y } = ev.axes;
  const passing = ev.variants.filter((v) => v.feasible).length;
  return (
    <div className="rounded-[14px] bg-card p-3 ring-1 ring-line" data-target="optimize">
      <div className="flex items-center gap-2 text-[14px] font-bold text-accent">
        <Sparkles className="h-4.5 w-4.5" /> Optimizer · {goals}
      </div>
      <p className="num mt-0.5 text-[13px] text-muted">
        {ev.variants.length} variants · {passing} pass · {ev.variants.filter((v) => v.pareto).length} on the front · colour = price
      </p>
      <Chart ev={ev} busy={busy} onPick={onPick} hover={hover} setHover={setHover} />
      {shown && (
        <div className="num mt-1 rounded-xl bg-page-2 px-2.5 py-2 text-[13px] leading-snug">
          <div className="flex items-center gap-1.5 font-bold text-ink">
            {shown.feasible ? <CircleCheck className="h-4 w-4 shrink-0 text-ok-ink" /> : <CircleX className="h-4 w-4 shrink-0 text-fail-ink" />}
            <span className="truncate">
              {shown.id} {shown.label}
              {ev.recommended === shown.id ? " · recommended" : ""}
            </span>
          </div>
          <p className="mt-0.5 text-ink-2">
            {fmtNum(shown.weight_g, 1)} g · {fmtNum(shown.flight_time_min, 1)} min · {fmtNum(shown.price_eur, 2)} € · stiffness {fmtNum(shown.arm_stiffness, 2)}×
          </p>
          <p className="mt-0.5 text-muted">
            {shown.battery} · arm {fmtNum(shown.params.arm_length_mm, 1)} mm · plate {fmtNum(shown.params.thickness_mm, 1)} mm
          </p>
          {shown.checks.some((c) => !c.pass) && (
            <p className="mt-0.5 font-semibold text-fail-ink">
              Fails {shown.checks.filter((c) => !c.pass).map((c) => `${c.label} (${c.detail})`).join(", ")}
            </p>
          )}
        </div>
      )}
      {ev.applied ? (
        <p className="mt-2 text-[14px] font-semibold text-ok-ink">✓ Variant {ev.applied} built as v{ev.version}</p>
      ) : busy ? (
        <p className="mt-2 flex items-center gap-1.5 text-[14px] font-semibold text-accent">
          <Loader2 className="h-4 w-4 animate-spin" /> Building variant {picked}…
        </p>
      ) : (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {ev.variants
            .filter((v) => v.feasible)
            .map((v) => (
              <button
                key={v.id}
                type="button"
                data-target={`optimize:build:${v.id}`}
                onMouseEnter={() => setHover(v.id)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onPick(v)}
                className={`num h-8 rounded-full px-3 text-[13px] font-bold transition ${
                  ev.recommended === v.id ? "bg-accent text-white hover:brightness-110" : "bg-card text-ink-2 ring-1 ring-line hover:bg-page-2"
                }`}
              >
                Build {v.id} · {fmtNum(v[x], AXIS[x].digits)} {AXIS[x].unit} · {fmtNum(v[y], AXIS[y].digits)} {AXIS[y].unit.replace(": ", "")}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
