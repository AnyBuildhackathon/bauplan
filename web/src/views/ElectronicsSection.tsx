// Electronics in the bill-of-materials drawer: the wiring diagram as an SVG (blocks and
// numbered wires, coloured by voltage), the warnings for parts over their rating, the wire
// list and the power budget, all from the `electronics` event of electronics_plan.
import { AlertTriangle, Zap } from "lucide-react";
import { useSession } from "../events/store";
import type { ElectronicsBlock, ElectronicsEvent, ElectronicsWire } from "../events/types";
import { fmtNum } from "../lib/format";

const H = 62;
const ROW_GAP = 18;
const PAD = 12;

const COLORS: Record<ElectronicsWire["color"], string> = {
  "3v3": "#2f7fd8",
  "1s": "#e0820b",
  "5v": "#d6453d",
  high: "#8b3fd1",
  phase: "var(--color-ink)",
  signal: "var(--color-muted)",
  power: "var(--color-ink-2)",
};
const LEGEND: Record<ElectronicsWire["color"], string> = {
  "3v3": "up to 3.6 V",
  "1s": "1S battery",
  "5v": "5 V",
  high: "above 5.5 V",
  phase: "motor phases",
  signal: "signal",
  power: "power",
};
const ROLE: Record<ElectronicsBlock["role"], string> = {
  supply: "Supply",
  connector: "Connector",
  switch: "Switch",
  regulator: "Regulator",
  controller: "Controller",
  driver: "Driver",
  inline: "Resistor",
  load: "Load",
  sensor: "Sensor",
};

function clip(text: string, max: number) {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

function volts(v: number | null) {
  return v == null ? "" : `${fmtNum(v, v < 10 ? 1 : 0)} V`;
}

function amps(a: number | null) {
  if (a == null) return "";
  return a < 1 ? `${fmtNum(a * 1000, 0)} mA` : `${fmtNum(a, 2)} A`;
}

function runtime(h: number) {
  if (h < 1) return `${fmtNum(h * 60, 1)} min`;
  if (h < 48) return `${fmtNum(h, 1)} h`;
  return `${fmtNum(h / 24, 0)} days`;
}

function Diagram({ ev }: { ev: ElectronicsEvent }) {
  const byId = new Map(ev.blocks.map((b) => [b.id, b]));
  const cols = Math.max(...ev.blocks.map((b) => b.col)) + 1;
  // Four columns and more get narrower blocks, so the drawer still shows the whole diagram.
  const wide = cols < 4;
  const W = wide ? 150 : 128;
  const GAP = wide ? 84 : 56;
  const rows = Math.max(...ev.blocks.map((b) => b.row)) + 1;
  const width = PAD * 2 + cols * W + (cols - 1) * GAP;
  const x = (b: ElectronicsBlock) => PAD + b.col * (W + GAP);
  const failing = new Set(
    ev.warnings
      .filter((w) => w.severity === "fail")
      .flatMap((w) => ev.blocks.filter((b) => b.id === w.part || b.name.includes(w.part) || w.part.includes(b.name)).map((b) => b.id)),
  );

  // Each wire leaves its left block on the right edge and enters its right block on the left edge.
  const wires = ev.wires
    .map((wire) => {
      const a = byId.get(wire.from);
      const b = byId.get(wire.to);
      if (!a || !b || a.col === b.col) return null;
      const [left, right] = a.col < b.col ? [a, b] : [b, a];
      return { wire, left, right };
    })
    .filter((w): w is { wire: ElectronicsWire; left: ElectronicsBlock; right: ElectronicsBlock } => w !== null);
  const slots = new Map<string, string[]>();
  const slot = (key: string, id: string) => {
    const list = slots.get(key) ?? [];
    list.push(id);
    slots.set(key, list);
  };
  for (const { wire, left, right } of wires) {
    slot(`${left.id}:r`, wire.id);
    slot(`${right.id}:l`, wire.id);
    slot(`gap:${left.col}`, wire.id);
  }
  const at = (key: string, id: string) => {
    const list = slots.get(key) ?? [id];
    return { i: list.indexOf(id), n: list.length };
  };
  // A block grows with the wires on its busiest side; a short column sits centred against the tallest one.
  const h = (b: ElectronicsBlock) => Math.max(H, 16 * Math.max(slots.get(`${b.id}:r`)?.length ?? 0, slots.get(`${b.id}:l`)?.length ?? 0) + 8);
  const pitch = H + ROW_GAP;
  const perCol = (col: number) => ev.blocks.filter((b) => b.col === col).length;
  const top = Math.max(0, ...ev.blocks.map((b) => (h(b) - H) / 2));
  // A column a wire runs across keeps its rows, so the wire passes between its blocks.
  const crossed = new Set(wires.flatMap(({ left, right }) => Array.from({ length: Math.max(right.col - left.col - 1, 0) }, (_, i) => left.col + 1 + i)));
  const shift = (col: number) => (crossed.has(col) ? 0 : ((rows - perCol(col)) * pitch) / 2);
  const y = (b: ElectronicsBlock) => PAD + top + shift(b.col) + b.row * pitch + H / 2 - h(b) / 2;
  const height = Math.max(...ev.blocks.map((b) => y(b) + h(b))) + PAD;
  const used = [...new Set(ev.wires.map((w) => w.color))];

  return (
    <div className="overflow-x-auto">
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 px-1 text-[12px] font-semibold text-muted">
        {used.map((c) => (
          <span key={c} className="inline-flex items-center gap-1.5">
            <svg width="18" height="6" aria-hidden>
              <line x1="0" y1="3" x2="18" y2="3" stroke={COLORS[c]} strokeWidth="3" strokeDasharray={c === "signal" ? "4 3" : undefined} />
            </svg>
            {LEGEND[c]}
          </span>
        ))}
        <span>Grounds are common and not drawn.</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ minWidth: Math.min(width, Math.max(560, width * 0.75)) }} role="img" aria-label="Wiring diagram" data-target="electronics:diagram">
        {wires.map(({ wire, left, right }, index) => {
          const r = at(`${left.id}:r`, wire.id);
          const l = at(`${right.id}:l`, wire.id);
          const g = at(`gap:${left.col}`, wire.id);
          const x1 = x(left) + W;
          const y1 = y(left) + (h(left) * (r.i + 1)) / (r.n + 1);
          const x2 = x(right);
          const y2 = y(right) + (h(right) * (l.i + 1)) / (l.n + 1);
          const cx = x1 + (GAP * (g.i + 1)) / (g.n + 1);
          const tagX = (cx + x2) / 2;
          return (
            <g key={wire.id}>
              <title>{`${index + 1}: ${byId.get(wire.from)?.name} ${wire.from_pin} → ${byId.get(wire.to)?.name} ${wire.to_pin} ${wire.label}`}</title>
              <path
                d={`M ${x1} ${y1} H ${cx} V ${y2} H ${x2}`}
                fill="none"
                stroke={COLORS[wire.color]}
                strokeWidth={wire.kind === "signal" ? 1.6 : 2.4}
                strokeDasharray={wire.kind === "signal" ? "5 4" : undefined}
                strokeLinejoin="round"
              />
              <circle cx={tagX} cy={y2} r="8" fill="var(--color-card)" stroke={COLORS[wire.color]} strokeWidth="1.5" />
              <text x={tagX} y={y2 + 3.5} textAnchor="middle" fontSize="10" fontWeight="700" fill="var(--color-ink)">
                {index + 1}
              </text>
            </g>
          );
        })}
        {ev.blocks.map((b) => (
          <g key={b.id} data-target={`electronics:${b.id}`}>
            <rect
              x={x(b)}
              y={y(b)}
              width={W}
              height={h(b)}
              rx="10"
              fill="var(--color-card)"
              stroke={failing.has(b.id) ? "var(--color-fail)" : "var(--color-line)"}
              strokeWidth={failing.has(b.id) ? 2.5 : 1.2}
            />
            <text x={x(b) + 10} y={y(b) + 16} fontSize="9.5" fontWeight="700" letterSpacing="0.06em" fill="var(--color-muted)">
              {ROLE[b.role].toUpperCase()}
              {b.voltage_v != null ? ` · ${volts(b.voltage_v)}` : ""}
            </text>
            <text x={x(b) + 10} y={y(b) + 33} fontSize="12" fontWeight="700" fill="var(--color-ink)">
              <title>{b.name}</title>
              {clip(b.name, wide ? 21 : 17)}
            </text>
            <text x={x(b) + 10} y={y(b) + 50} fontSize="10" fill={failing.has(b.id) ? "var(--color-fail-ink)" : "var(--color-ink-2)"}>
              <title>{b.rating}</title>
              {clip(b.rating, wide ? 27 : 22)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

export function ElectronicsSection() {
  const ev = useSession((s) => s.electronics);
  if (!ev || ev.blocks.length === 0) return null;
  const byId = new Map(ev.blocks.map((b) => [b.id, b]));
  const budget = ev.budget;
  const fails = ev.warnings.filter((w) => w.severity === "fail").length;
  return (
    <section className="card px-4 pt-4 pb-3" data-target="electronics">
      <div className="mb-2 flex items-center gap-3 px-2">
        <Zap className="h-5 w-5 shrink-0 text-ink-2" />
        <div className="min-w-0">
          <h2 className="text-[18px] font-bold">Electronics</h2>
          <p className="truncate text-[13px] font-semibold text-muted">Wiring diagram and power budget</p>
        </div>
        <span className={`num ml-auto shrink-0 text-[14px] font-bold ${ev.ok ? "text-ok-ink" : "text-fail-ink"}`} data-target="electronics:verdict">
          {ev.ok ? "Within ratings" : `${fails} over rating`}
        </span>
      </div>
      <p className="px-2 pb-2 text-[15px] leading-snug text-ink-2">{ev.explanation || ev.summary}</p>
      {ev.warnings.length > 0 && (
        <ul className="mx-2 mb-3 space-y-1.5" data-target="electronics:warnings">
          {ev.warnings.map((w, i) => (
            <li
              key={i}
              className={`flex items-start gap-2 rounded-xl px-3 py-2 text-[14px] font-semibold ${w.severity === "fail" ? "bg-fail-soft text-fail-ink" : "bg-accent-soft text-ink"}`}
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              {w.text}
            </li>
          ))}
        </ul>
      )}
      <div className="px-2 pb-3">
        <Diagram ev={ev} />
      </div>
      <div className="overflow-x-auto px-2 pb-3">
        <table className="w-full text-left text-[14px]">
          <thead className="text-[12px] font-bold text-muted uppercase">
            <tr>
              <th className="py-1.5 pr-3">#</th>
              <th className="py-1.5 pr-3">From</th>
              <th className="py-1.5 pr-3">To</th>
              <th className="py-1.5 pr-3 text-right">Voltage</th>
              <th className="py-1.5 text-right">Peak</th>
            </tr>
          </thead>
          <tbody>
            {ev.wires.map((w, i) => (
              <tr key={w.id} className="border-t border-line align-top">
                <td className="num py-1.5 pr-3 font-bold" style={{ color: COLORS[w.color] }}>
                  {i + 1}
                </td>
                <td className="py-1.5 pr-3">
                  <span className="font-semibold">{byId.get(w.from)?.name}</span>
                  {w.from_pin && <span className="num block text-[13px] text-muted">{w.from_pin}</span>}
                </td>
                <td className="py-1.5 pr-3">
                  <span className="font-semibold">{byId.get(w.to)?.name}</span>
                  {w.to_pin && <span className="num block text-[13px] text-muted">{w.to_pin}</span>}
                </td>
                <td className="num py-1.5 pr-3 text-right">{w.kind === "signal" ? "signal" : volts(w.voltage_v)}</td>
                <td className="num py-1.5 text-right">{amps(w.current_a)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="overflow-x-auto px-2 pb-1" data-target="electronics:budget">
        <h3 className="pb-1 text-[15px] font-bold">Power budget</h3>
        <table className="w-full text-left text-[14px]">
          <thead className="text-[12px] font-bold text-muted uppercase">
            <tr>
              <th className="py-1.5 pr-3">Load</th>
              <th className="py-1.5 pr-3 text-right">On</th>
              <th className="py-1.5 pr-3 text-right">Average</th>
              <th className="py-1.5 text-right">Peak</th>
            </tr>
          </thead>
          <tbody>
            {budget.loads.map((l, i) => (
              <tr key={i} className="border-t border-line">
                <td className="py-1.5 pr-3 font-semibold">{l.name}</td>
                <td className="num py-1.5 pr-3 text-right">{l.duty >= 1 ? "always" : `${fmtNum(l.duty * 100, l.duty < 0.01 ? 3 : 1)} %`}</td>
                <td className="num py-1.5 pr-3 text-right">{fmtNum(l.average_w, l.average_w < 0.1 ? 4 : 2)} W</td>
                <td className="num py-1.5 text-right">{fmtNum(l.peak_w, 2)} W</td>
              </tr>
            ))}
            <tr className="border-t-2 border-line font-bold">
              <td className="py-1.5 pr-3">From {budget.supply}</td>
              <td className="num py-1.5 pr-3 text-right">{volts(budget.supply_voltage_v)}</td>
              <td className="num py-1.5 pr-3 text-right">{fmtNum(budget.average_w, budget.average_w < 0.1 ? 4 : 2)} W</td>
              <td className="num py-1.5 text-right">{fmtNum(budget.peak_w, 2)} W</td>
            </tr>
          </tbody>
        </table>
        <p className="num pt-2 text-[14px] font-semibold text-ink-2">
          Peak {amps(budget.peak_a)} of {amps(budget.supply_limit_a)} ·{" "}
          <span className={budget.headroom >= 1 ? "text-ok-ink" : "text-fail-ink"}>headroom {fmtNum(budget.headroom, 1)}×</span>
          {budget.runtime_h != null && <> · runs {runtime(budget.runtime_h)}</>}
        </p>
        {ev.gaps.length > 0 && <p className="pt-1 text-[12px] text-faint">Assumed: {ev.gaps.join(" ")}</p>}
      </div>
    </section>
  );
}
