// The Agents tab: the orchestrator in the middle, every sub-agent it delegates to as a node
// around it, joined by an edge that flows while the job runs; a Gantt-like timeline below
// shows what ran in parallel, and a click on a node opens that agent's log.
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { ChevronLeft, ChevronRight, CircleCheck, CircleX, Network, X } from "lucide-react";
import { stripMarkdown } from "../../lib/format";
import {
  MODEL_STYLE,
  fmtCost,
  fmtSeconds,
  fmtTokens,
  modelFamily,
  roleIcon,
  shortName,
  toolInfo,
  useAgentRuns,
  type AgentNode,
  type AgentTeamRun,
} from "./agentRuns";

type Status = AgentNode["ev"]["status"];

const STATUS_TEXT: Record<Status, string> = { queued: "queued", running: "working", done: "done", error: "failed" };
const STATUS_TONE: Record<Status, string> = {
  queued: "bg-tile text-muted",
  running: "bg-agent-soft text-agent-ink",
  done: "bg-ok-soft text-ok-ink",
  error: "bg-fail-soft text-fail-ink",
};
const NODE_RING: Record<Status, string> = {
  queued: "ring-1 ring-track opacity-80",
  running: "ring-2 ring-agent",
  done: "ring-1 ring-line",
  error: "ring-2 ring-fail",
};
const EDGE: Record<Status, { stroke: string; width: number; dash?: string; opacity?: number }> = {
  queued: { stroke: "var(--color-track)", width: 2, dash: "2 7" },
  running: { stroke: "var(--color-agent)", width: 2.5, dash: "8 8" },
  done: { stroke: "var(--color-ok)", width: 2, opacity: 0.45 },
  error: { stroke: "var(--color-fail)", width: 2, opacity: 0.7 },
};

/** Ticks while something runs, so bars and clocks grow. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setSize({ w: entry.contentRect.width, h: entry.contentRect.height }));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, size] as const;
}

function StatusPill({ status }: { status: Status }) {
  return (
    <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-[12px] font-bold ${STATUS_TONE[status]}`}>
      {status === "running" && <span className="h-1.5 w-1.5 rounded-full bg-agent motion-safe:animate-pulse-soft" />}
      {status === "done" && <CircleCheck className="h-3.5 w-3.5" strokeWidth={2.4} />}
      {status === "error" && <CircleX className="h-3.5 w-3.5" strokeWidth={2.4} />}
      {STATUS_TEXT[status]}
    </span>
  );
}

function ModelChip({ node }: { node: AgentNode }) {
  return (
    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[12px] font-bold ${MODEL_STYLE[modelFamily(node.ev.model)].chip}`}>
      {node.ev.model_label.replace(/ \d+(\.\d+)?$/, "")}
    </span>
  );
}

function ToolChip({ tool }: { tool: string }) {
  const { label, icon: Icon } = toolInfo(tool);
  return (
    <span className="inline-flex min-w-0 shrink-0 items-center gap-1 rounded-full bg-white px-2 py-0.5 text-[12px] font-semibold text-ink-2 ring-1 ring-line">
      <Icon className="h-3.5 w-3.5 shrink-0 text-agent-ink" strokeWidth={2} />
      <span className="truncate">{label}</span>
    </span>
  );
}

const elapsed = (node: AgentNode, now: number) => (node.start === null ? 0 : (node.end ?? now) - node.start);

/** One sub-agent on the graph. */
function SubNode({ node, now, compact, selected, onOpen, style }: { node: AgentNode; now: number; compact: boolean; selected: boolean; onOpen: () => void; style: CSSProperties }) {
  const { ev } = node;
  const Icon = roleIcon(ev.role);
  return (
    <button
      type="button"
      onClick={onOpen}
      data-target={`agent-node:${ev.role} agent-node:${ev.id}`}
      aria-label={`${ev.label}, ${STATUS_TEXT[ev.status]}: ${ev.task}`}
      style={style}
      className={`absolute flex -translate-x-1/2 -translate-y-1/2 flex-col gap-1 rounded-[16px] bg-card px-3 py-2 text-left shadow-[var(--shadow-pill)] motion-safe:animate-rise motion-safe:transition-[left,top,opacity,box-shadow] motion-safe:duration-500 hover:shadow-[var(--shadow-float)] ${NODE_RING[ev.status]} ${selected ? "outline-2 outline-offset-2 outline-ink" : ""}`}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-page-2">
          <Icon className="h-4 w-4 text-ink-2" strokeWidth={2} />
        </span>
        <span className="min-w-0 flex-1 truncate text-[15px] font-bold text-ink">{shortName(ev)}</span>
      </div>
      {!compact && <div className="truncate text-[13px] leading-snug text-ink-2">{ev.task}</div>}
      <div className="flex min-w-0 items-center gap-1.5">
        <ModelChip node={node} />
        <StatusPill status={ev.status} />
        {compact && <span className="num ml-auto shrink-0 text-[13px] font-bold text-ink-2">{fmtCost(ev.cost_usd)}</span>}
      </div>
      {!compact && (
        <div className="flex h-[22px] min-w-0 items-center gap-2">
          {ev.tool && ev.status === "running" ? (
            <ToolChip tool={ev.tool} />
          ) : ev.status === "queued" ? (
            <span className="min-w-0 truncate text-[12px] font-semibold text-faint">{ev.summary || "waits for its turn"}</span>
          ) : (
            <span className="num min-w-0 truncate text-[12px] font-semibold text-faint">
              {ev.rounds} call{ev.rounds === 1 ? "" : "s"} · {fmtTokens(ev.input_tokens + ev.output_tokens + ev.cache_read_tokens)} tok · {fmtSeconds(elapsed(node, now))}
            </span>
          )}
          <span className="num ml-auto shrink-0 text-[13px] font-bold text-ink-2">{fmtCost(ev.cost_usd)}</span>
        </div>
      )}
    </button>
  );
}

/** The orchestrator in the middle, with the totals of its whole team. */
function LeadNode({ run, now, selected, onOpen, style }: { run: AgentTeamRun; now: number; selected: boolean; onOpen: () => void; style: CSSProperties }) {
  const lead = run.lead;
  const working = run.subs.filter((n) => n.ev.status === "running").length;
  const queued = run.subs.filter((n) => n.ev.status === "queued").length;
  const done = run.subs.filter((n) => n.ev.status === "done" || n.ev.status === "error").length;
  const status: Status = lead?.ev.status ?? (working || queued ? "running" : "done");
  const counts = [working && `${working} working`, queued && `${queued} queued`, done && `${done} done`].filter(Boolean).join(" · ") || "no sub-agents yet";
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!lead}
      data-target="agent-node:orchestrator"
      style={style}
      className={`absolute z-10 flex -translate-x-1/2 -translate-y-1/2 flex-col gap-1.5 rounded-[20px] bg-card px-4 py-3 text-left shadow-[var(--shadow-float)] motion-safe:transition-[left,top] motion-safe:duration-500 ${NODE_RING[status]} ${selected ? "outline-2 outline-offset-2 outline-ink" : ""}`}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-accent-soft">
          <Network className="h-4.5 w-4.5 text-accent" strokeWidth={2} />
        </span>
        <span className="min-w-0 flex-1 truncate text-[17px] font-bold text-ink">{lead?.ev.label ?? "Direct tool calls"}</span>
      </div>
      {lead && <div className="truncate text-[13px] text-ink-2">{lead.ev.task}</div>}
      <div className="flex min-w-0 items-center gap-1.5">
        {lead && <ModelChip node={lead} />}
        <StatusPill status={status} />
        <span className="num ml-auto shrink-0 text-[15px] font-bold text-ink">{fmtCost(run.costUsd)}</span>
      </div>
      <div className="num flex items-center justify-between gap-2 text-[12px] font-semibold text-faint">
        {lead?.ev.tool && status === "running" ? <ToolChip tool={lead.ev.tool} /> : <span className="truncate">{counts}</span>}
        <span className="shrink-0">{fmtTokens(run.tokens)} tok · {fmtSeconds((run.to ?? now) - run.from)}</span>
      </div>
    </button>
  );
}

interface Spot {
  x: number;
  y: number;
}

/** Where everyone sits: the sub-agents on an ellipse around the orchestrator, or, when that would overlap, the orchestrator on top and the team in a grid below. */
function layout(n: number, w: number, h: number, node: { w: number; h: number }, lead: { w: number; h: number }): { lead: Spot; subs: Spot[]; height: number } {
  const rx = Math.max(0, w / 2 - node.w / 2 - 16);
  const ry = Math.max(0, h / 2 - node.h / 2 - 14);
  const step = (2 * Math.PI) / Math.max(1, n);
  const start = n === 1 ? 0 : -Math.PI / 2 + step / 2;
  const ring = Array.from({ length: n }, (_, i) => ({ x: w / 2 + rx * Math.cos(start + i * step), y: h / 2 + ry * Math.sin(start + i * step) }));
  const centre = { x: w / 2, y: h / 2 };
  const boxes = [{ ...centre, ...lead }, ...ring.map((p) => ({ ...p, ...node }))];
  const clash = boxes.some((a, i) => boxes.some((b, j) => j > i && Math.abs(a.x - b.x) < (a.w + b.w) / 2 + 6 && Math.abs(a.y - b.y) < (a.h + b.h) / 2 + 6));
  if (!clash) return { lead: centre, subs: ring, height: h };
  const cols = Math.max(1, Math.floor((w - 16) / (node.w + 14)));
  const top = 14 + lead.h + 40;
  const subs = Array.from({ length: n }, (_, i) => {
    const row = Math.floor(i / cols);
    const inRow = Math.min(cols, n - row * cols);
    const col = i % cols;
    return { x: w / 2 + (col - (inRow - 1) / 2) * (node.w + 14), y: top + row * (node.h + 14) + node.h / 2 };
  });
  return { lead: { x: w / 2, y: 14 + lead.h / 2 }, subs, height: Math.max(h, top + Math.ceil(n / cols) * (node.h + 14)) };
}

function Graph({ run, now, selected, onOpen }: { run: AgentTeamRun; now: number; selected: string | null; onOpen: (id: string) => void }) {
  const [ref, { w, h }] = useSize<HTMLDivElement>();
  const n = run.subs.length;
  const compact = n > 8 || h < 340;
  const node = { w: Math.min(compact ? 200 : 236, Math.max(176, w / 3.6)), h: compact ? 70 : 112 };
  const lead = { w: Math.min(272, Math.max(220, w / 3.2)), h: 124 };
  const spots = layout(n, w, h, node, lead);
  return (
    <div ref={ref} className="relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto" data-target="agents graph">
      {w > 0 && (
        <div className="relative" style={{ height: spots.height }}>
          <svg className="pointer-events-none absolute inset-0" width={w} height={spots.height} aria-hidden>
            {run.subs.map((sub, i) => {
              const edge = EDGE[sub.ev.status];
              return (
                <line
                  key={sub.ev.id}
                  x1={spots.lead.x}
                  y1={spots.lead.y}
                  x2={spots.subs[i].x}
                  y2={spots.subs[i].y}
                  stroke={edge.stroke}
                  strokeWidth={edge.width}
                  strokeDasharray={edge.dash}
                  strokeLinecap="round"
                  opacity={edge.opacity ?? 1}
                  className={sub.ev.status === "running" ? "motion-safe:animate-edge-flow" : undefined}
                />
              );
            })}
          </svg>
          {run.subs.map((sub, i) => (
            <SubNode
              key={sub.ev.id}
              node={sub}
              now={now}
              compact={compact}
              selected={selected === sub.ev.id}
              onOpen={() => onOpen(sub.ev.id)}
              style={{ left: spots.subs[i].x, top: spots.subs[i].y, width: node.w }}
            />
          ))}
          <LeadNode
            run={run}
            now={now}
            selected={!!run.lead && selected === run.lead.ev.id}
            onOpen={() => run.lead && onOpen(run.lead.ev.id)}
            style={{ left: spots.lead.x, top: spots.lead.y, width: lead.w }}
          />
        </div>
      )}
    </div>
  );
}

/** A tick every 1, 2, 5, 10, 15, 30 or 60 s, about five across. */
function tickStep(spanMs: number): number {
  const target = spanMs / 5;
  return [1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000].find((s) => s >= target) ?? 600000;
}

/** Gantt-like strip: one row per agent, so parallel work lines up. */
function Timeline({ run, now, selected, onOpen }: { run: AgentTeamRun; now: number; selected: string | null; onOpen: (id: string) => void }) {
  const rows = run.lead ? [run.lead, ...run.subs] : run.subs;
  const from = run.from;
  const span = Math.max(1000, (run.to ?? now) - from);
  const pct = (t: number) => `${(Math.min(Math.max(t - from, 0), span) / span) * 100}%`;
  const step = tickStep(span);
  const ticks = Array.from({ length: Math.floor(span / step) + 1 }, (_, i) => i * step);
  return (
    <div className="max-h-[42%] shrink-0 overflow-y-auto border-t border-line bg-white/70 px-4 pt-2 pb-3 backdrop-blur" data-target="agents timeline">
      <div className="grid grid-cols-[minmax(0,180px)_minmax(0,1fr)] items-end gap-x-3">
        <span className="text-[12px] font-bold tracking-wide text-faint uppercase">Timeline</span>
        <div className="relative h-4">
          {ticks.map((t) => (
            <span key={t} className="num absolute -translate-x-1/2 text-[11px] font-semibold text-faint first:translate-x-0" style={{ left: `${(t / span) * 100}%` }}>
              {Math.round(t / 1000)}s
            </span>
          ))}
        </div>
      </div>
      <ul className="mt-1 space-y-1">
        {rows.map((node) => {
          const Icon = roleIcon(node.ev.role);
          const start = node.start ?? now;
          const end = node.end ?? now;
          const family = MODEL_STYLE[modelFamily(node.ev.model)];
          const failed = node.ev.status === "error";
          return (
            <li key={node.ev.id}>
              <button
                type="button"
                onClick={() => onOpen(node.ev.id)}
                className={`grid w-full grid-cols-[minmax(0,180px)_minmax(0,1fr)] items-center gap-x-3 rounded-md text-left hover:bg-page-2 ${selected === node.ev.id ? "bg-page-2" : ""}`}
              >
                <span className="flex min-w-0 items-center gap-1.5 text-[13px] font-semibold text-ink-2">
                  <Icon className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                  <span className="truncate">{shortName(node.ev)}</span>
                </span>
                <span className="relative h-3.5 rounded-full bg-tile">
                  {ticks.map((t) => (
                    <span key={t} className="absolute inset-y-0 w-px bg-line" style={{ left: `${(t / span) * 100}%` }} />
                  ))}
                  {node.start !== null && node.start > node.seen + 150 && (
                    <span
                      className="absolute inset-y-0 rounded-full bg-[repeating-linear-gradient(135deg,var(--color-track)_0_4px,transparent_4px_8px)]"
                      style={{ left: pct(node.seen), width: `calc(${pct(node.start)} - ${pct(node.seen)})` }}
                    />
                  )}
                  {node.ev.status === "queued" ? (
                    <span
                      className="absolute inset-y-0 rounded-full bg-[repeating-linear-gradient(135deg,var(--color-track)_0_4px,transparent_4px_8px)]"
                      style={{ left: pct(node.seen), width: `calc(${pct(now)} - ${pct(node.seen)})` }}
                    />
                  ) : (
                    <span
                      className={`absolute inset-y-0 min-w-1.5 rounded-full ${failed ? "bg-fail" : family.bar} ${node.end === null ? "opacity-100" : "opacity-80"}`}
                      style={{ left: pct(start), width: `calc(${pct(end)} - ${pct(start)})` }}
                    >
                      {node.end === null && <span className="absolute inset-y-0 right-0 w-1.5 rounded-full bg-agent motion-safe:animate-pulse-soft" />}
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** The side sheet with one agent's log: its job, numbers, tool calls and every report. */
function LogSheet({ node, now, onClose }: { node: AgentNode; now: number; onClose: () => void }) {
  const { ev } = node;
  const Icon = roleIcon(ev.role);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const base = node.seen;
  const stats: [string, string][] = [
    ["Model calls", String(ev.rounds)],
    ["Time", fmtSeconds(elapsed(node, now))],
    ["Cost", fmtCost(ev.cost_usd)],
    ["Input", fmtTokens(ev.input_tokens)],
    ["Output", fmtTokens(ev.output_tokens)],
    ["Cache read", fmtTokens(ev.cache_read_tokens)],
  ];
  const calls = ev.calls ?? [];
  return (
    <aside
      className="absolute top-3 right-3 bottom-3 z-20 flex w-[380px] max-w-[calc(100%-24px)] flex-col overflow-hidden rounded-[20px] bg-card shadow-[var(--shadow-float)] ring-1 ring-line motion-safe:animate-rise"
      data-target="agent-log"
      aria-label={`${ev.label} log`}
    >
      <div className="flex items-start gap-2.5 border-b border-line px-4 pt-3.5 pb-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-page-2">
          <Icon className="h-5 w-5 text-ink-2" strokeWidth={2} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-[17px] font-bold text-ink">{ev.label}</span>
            <StatusPill status={ev.status} />
          </div>
          <div className="truncate text-[13px] font-semibold text-muted">
            {ev.model_label} · effort {ev.effort}
          </div>
        </div>
        <button type="button" onClick={onClose} aria-label="Close log" className="-mr-1 rounded-full p-1.5 text-muted hover:bg-page-2 hover:text-ink">
          <X className="h-5 w-5" />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3.5">
        <section>
          <h3 className="text-[12px] font-bold tracking-wide text-faint uppercase">Job</h3>
          <p className="mt-1 text-[15px] leading-snug text-ink">{ev.task}</p>
        </section>
        <dl className="grid grid-cols-3 gap-2">
          {stats.map(([label, value]) => (
            <div key={label} className="rounded-xl bg-page-2 px-2.5 py-2">
              <dt className="text-[11px] font-semibold text-faint">{label}</dt>
              <dd className="num text-[16px] font-bold text-ink">{value}</dd>
            </div>
          ))}
        </dl>
        {ev.status === "running" && ev.tool && (
          <section className="flex items-center gap-2">
            <h3 className="text-[12px] font-bold tracking-wide text-faint uppercase">Running now</h3>
            <ToolChip tool={ev.tool} />
          </section>
        )}
        {(ev.status === "done" || ev.status === "error") && ev.summary && (
          <section>
            <h3 className="text-[12px] font-bold tracking-wide text-faint uppercase">{ev.status === "error" ? "Error" : "Report"}</h3>
            <p className="mt-1 text-[14px] leading-snug whitespace-pre-line text-ink-2">{stripMarkdown(ev.summary)}</p>
          </section>
        )}
        <section>
          <h3 className="text-[12px] font-bold tracking-wide text-faint uppercase">Tool calls</h3>
          {calls.length === 0 ? (
            <p className="mt-1 text-[13px] text-muted">{ev.calls ? "None yet." : "This backend does not report tool calls."}</p>
          ) : (
            <ol className="mt-1.5 space-y-1.5">
              {calls.map((call, i) => {
                const { label, icon: ToolIcon } = toolInfo(call.tool);
                return (
                  <li key={i} className="flex min-w-0 items-start gap-2">
                    {call.ok ? <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-ok" strokeWidth={2.2} /> : <CircleX className="mt-0.5 h-4 w-4 shrink-0 text-fail" strokeWidth={2.2} />}
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 text-[13px] font-bold text-ink-2">
                        <ToolIcon className="h-3.5 w-3.5" strokeWidth={2} /> {label}
                        <span className="font-mono text-[11px] font-medium text-faint">{call.tool}</span>
                      </div>
                      {call.detail && <div className="text-[13px] leading-snug text-muted">{call.detail}</div>}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </section>
        <section>
          <h3 className="text-[12px] font-bold tracking-wide text-faint uppercase">Log</h3>
          <ol className="mt-1.5 space-y-1">
            {node.reports.map((report, i) => (
              <li key={i} className="grid grid-cols-[52px_minmax(0,1fr)] gap-2 text-[13px] leading-snug">
                <span className="num text-right font-semibold text-faint">+{fmtSeconds(Math.max(0, report.at - base)).replace(" ", "")}</span>
                <span className="min-w-0 text-ink-2">
                  <span className="font-semibold">{STATUS_TEXT[report.status]}</span>
                  {report.summary && <span className="text-muted"> · {stripMarkdown(report.summary).replace(/\s+/g, " ")}</span>}
                </span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </aside>
  );
}

export function AgentsView() {
  const runs = useAgentRuns();
  const [picked, setPicked] = useState<number | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const index = picked !== null && picked < runs.length ? picked : runs.length - 1;
  const run = runs[index];
  const now = useNow(!!run && run.to === null);
  // A new run follows the newest one again.
  useEffect(() => setPicked(null), [runs.length]);
  if (!run) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center" data-target="agents graph">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-[var(--shadow-pill)]">
          <Network className="h-7 w-7 text-accent" strokeWidth={1.8} />
        </span>
        <p className="text-[18px] font-semibold text-ink-2">No agents yet</p>
        <p className="max-w-sm text-[15px] text-muted">When the orchestrator delegates a job, each sub-agent shows up here live: model, tool, tokens and cost.</p>
      </div>
    );
  }
  const members = run.lead ? [run.lead, ...run.subs] : run.subs;
  const node = members.find((n) => n.ev.id === open) ?? null;
  return (
    <div className="absolute inset-0 flex flex-col">
      <div className="flex shrink-0 items-center gap-2 px-4 pt-3">
        {runs.length > 1 && (
          <div className="flex items-center gap-1 rounded-full bg-white/90 p-0.5 shadow-[var(--shadow-pill)]">
            <button type="button" aria-label="Previous run" disabled={index === 0} onClick={() => setPicked(index - 1)} className="rounded-full p-1 text-ink-2 hover:bg-page-2 disabled:opacity-30">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="num px-1 text-[13px] font-semibold text-ink-2">
              Run {index + 1} of {runs.length}
            </span>
            <button
              type="button"
              aria-label="Next run"
              disabled={index === runs.length - 1}
              onClick={() => setPicked(index + 1)}
              className="rounded-full p-1 text-ink-2 hover:bg-page-2 disabled:opacity-30"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        )}
        <span className="text-[13px] font-semibold text-muted">
          {run.subs.length} sub-agent{run.subs.length === 1 ? "" : "s"} · {fmtCost(run.costUsd)} · {fmtSeconds((run.to ?? now) - run.from)}
        </span>
      </div>
      <Graph run={run} now={now} selected={open} onOpen={setOpen} />
      <Timeline run={run} now={now} selected={open} onOpen={setOpen} />
      {node && <LogSheet node={node} now={now} onClose={() => setOpen(null)} />}
    </div>
  );
}
