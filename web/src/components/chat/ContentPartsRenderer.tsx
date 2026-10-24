// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/Chat/ContentPartsRenderer.tsx. Modified: renders our SSE
// chat items (tool, Jamie, simulation, bill of materials, training) as Bevel tool
// cards instead of core.so's message content parts; markdown, display cards and
// actions were removed.
import { memo, useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  CircleCheck,
  CircleX,
  Cpu,
  DraftingCompass,
  Gauge,
  GitCompareArrows,
  MessageCircleQuestion,
  Network,
  NotebookPen,
  Package,
  Receipt,
} from "lucide-react";
import { useSession, type ChatItem } from "../../events/store";
import { useSource } from "../../events/source";
import { enLabel, enText } from "../../lib/copy";
import { fmtDuration, fmtEur, fmtNum, stripMarkdown } from "../../lib/format";
import { useUi } from "../../lib/ui";
import { StressCard } from "../stress/StressCard";

const TOOL_LABELS: Record<string, { running: string; done: string }> = {
  Claude: { running: "Claude is thinking", done: "Claude" },
  CadQuery: { running: "CadQuery is building", done: "CadQuery" },
  MuJoCo: { running: "MuJoCo is simulating", done: "MuJoCo" },
  Blender: { running: "Blender is rendering", done: "Blender" },
  "Isaac Sim": { running: "Isaac Sim is starting", done: "Isaac Sim" },
  "Isaac Lab": { running: "Isaac Lab is training", done: "Isaac Lab" },
  RunPod: { running: "RunPod is starting the GPU", done: "RunPod" },
  Jamie: { running: "Asking Jamie", done: "Jamie" },
  Parts: { running: "Picking parts", done: "Parts" },
  Reson8: { running: "Reson8 is listening", done: "Reson8" },
};

const JAMIE_ACTIONS: Record<string, string> = {
  requirements: "Requirements read",
  search: "Meetings searched",
  search_meetings: "Meetings searched",
  get_meeting: "Meeting read",
  get_meeting_transcript: "Transcript read",
  create_tasks: "Tasks created",
  update_tasks: "Task updated",
  create_tag: "Tag created",
  add_tag_to_meetings: "Meeting tagged",
  upsert_template: "Template saved",
  note: "Note written",
  meeting_ended: "Meeting ended",
  summary: "Summary read",
};

function getToolLabel(name: string, phase: string): string {
  const l = TOOL_LABELS[name];
  if (!l) return phase === "running" ? `${name} running` : name;
  return phase === "running" ? l.running : l.done;
}

function PhaseIcon({ phase }: { phase: "running" | "ok" | "error" }) {
  if (phase === "running") {
    return (
      <span className="flex h-5 w-5 shrink-0 items-center justify-center">
        <span className="h-2.5 w-2.5 animate-pulse-soft rounded-full bg-agent" />
      </span>
    );
  }
  if (phase === "error") return <CircleX className="h-5 w-5 shrink-0 text-fail" strokeWidth={2.2} />;
  return <CircleCheck className="h-5 w-5 shrink-0 text-ok" strokeWidth={2.2} />;
}

function ToolCallPartRenderer({ item }: { item: Extract<ChatItem, { kind: "tool" }> }) {
  // Durations of bulk-replayed (seeked) calls are meaningless, so they are hidden.
  const duration = item.endedAt && !item.instant ? item.endedAt - item.at : null;
  return (
    <div
      className={`flex items-center gap-2.5 rounded-[14px] px-3 py-2.5 ${
        item.phase === "running" ? "bg-agent-soft" : item.phase === "error" ? "bg-fail-soft" : "bg-page-2"
      }`}
    >
      <PhaseIcon phase={item.phase} />
      <div className="min-w-0 flex-1">
        <div className={`text-[14px] font-semibold ${item.phase === "running" ? "text-agent-ink" : item.phase === "error" ? "text-fail-ink" : "text-ink-2"}`}>
          {getToolLabel(item.name, item.phase)}
        </div>
        {item.detail && <div className="truncate text-[13px] text-muted">{enText(item.detail)}</div>}
      </div>
      {duration != null && duration > 0 && <span className="num shrink-0 text-[12px] text-faint">{fmtDuration(duration)}</span>}
    </div>
  );
}

function JamiePartRenderer({ item }: { item: Extract<ChatItem, { kind: "jamie" }> }) {
  return (
    <div className="flex items-center gap-2.5 rounded-[14px] bg-page-2 px-3 py-2.5 ring-1 ring-line">
      <PhaseIcon phase={item.phase} />
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-semibold text-ink-2">
          <span className="text-jamie">Jamie</span> · {JAMIE_ACTIONS[item.action] ?? item.action.replace(/_/g, " ")}
        </div>
        {item.detail && <div className="truncate text-[13px] text-muted">{enText(item.detail)}</div>}
      </div>
      <NotebookPen className="h-4 w-4 shrink-0 text-jamie" />
    </div>
  );
}

function SimPartRenderer({ item }: { item: Extract<ChatItem, { kind: "sim" }> }) {
  const setTab = useUi((s) => s.setTab);
  const setView = useUi((s) => s.setView);
  const selectRun = useUi((s) => s.selectRun);
  const pass = item.result === "pass";
  return (
    <button
      type="button"
      onClick={() => {
        setView("werkbank");
        setTab("simulation");
        selectRun(item.run);
      }}
      className={`group w-full rounded-2xl p-3 text-left transition ${pass ? "bg-ok-soft" : "bg-fail-soft"}`}
    >
      <div className="flex items-center gap-2">
        {pass ? <CircleCheck className="h-5 w-5 text-ok" strokeWidth={2.2} /> : <CircleX className="h-5 w-5 text-fail" strokeWidth={2.2} />}
        <span className={`text-[14px] font-bold ${pass ? "text-ok-ink" : "text-fail-ink"}`}>
          Run {item.run} · {pass ? "passed" : "failed"}
        </span>
        <ArrowRight className="ml-auto h-4 w-4 text-muted transition group-hover:translate-x-0.5" />
      </div>
      <p className="mt-1 text-[14px] leading-snug text-ink-2">{item.summary}</p>
    </button>
  );
}

function BomPartRenderer({ item }: { item: Extract<ChatItem, { kind: "bom" }> }) {
  const setBomOpen = useUi((s) => s.setBomOpen);
  return (
    <button
      type="button"
      onClick={() => setBomOpen(true)}
      className="group flex w-full items-center gap-3 rounded-[14px] bg-page-2 p-3 text-left"
    >
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-white shadow-[var(--shadow-pill)]">
        <Boxes className="h-5 w-5 text-ink-2" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-bold text-ink">Bill of materials · {item.count} parts</div>
        <div className="num text-[13px] text-muted">{fmtEur(item.total)} · shop links and STL</div>
      </div>
      <ArrowRight className="h-4 w-4 text-muted transition group-hover:translate-x-0.5" />
    </button>
  );
}

function TrainingPartRenderer({ item }: { item: Extract<ChatItem, { kind: "training" }> }) {
  const setView = useUi((s) => s.setView);
  const phase = item.status === "done" ? "ok" : item.status === "failed" || item.status === "offline" ? "error" : "running";
  const title = { queued: "Training queued", running: "Training running", done: "Training done", failed: "Training stopped", offline: "Training offline" }[item.status];
  return (
    <button type="button" onClick={() => setView("training")} className="group flex w-full items-center gap-2.5 rounded-[14px] bg-page-2 px-3 py-2.5 text-left">
      <PhaseIcon phase={phase} />
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-semibold text-ink-2">{title}</div>
        <div className="truncate text-[13px] text-muted">Isaac Lab · {item.detail}</div>
      </div>
      <Cpu className="h-4 w-4 text-muted" />
    </button>
  );
}

function WarningPartRenderer({ item }: { item: Extract<ChatItem, { kind: "warning" }> }) {
  const w = item.warning;
  return (
    <div className="rounded-[14px] bg-agent-soft px-3 py-2.5">
      <div className="flex items-center gap-2 text-[14px] font-bold text-agent-ink">
        <AlertTriangle className="h-4.5 w-4.5 shrink-0" /> Warning from {w.meeting_title}
      </div>
      <p className="mt-1 text-[15px] leading-snug text-ink">“{w.text}”</p>
      <p className="mt-0.5 text-[13px] font-semibold text-muted">
        {w.speaker} · {w.time} · {item.part}
      </p>
    </div>
  );
}

function QuestionPartRenderer({ item }: { item: Extract<ChatItem, { kind: "question" }> }) {
  const q = useSession((s) => s.questions[item.questionId]);
  const answer = useSource((s) => s.answerQuestion);
  const [now, setNow] = useState(() => Date.now());
  const open = q?.status === "open";
  useEffect(() => {
    if (!open) return;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [open]);
  if (!q) return null;
  const left = Math.max(0, Math.ceil(q.timeout_s - (now - item.at) / 1000));
  const picked = q.options.find((o) => o.id === q.answer_id);
  return (
    <div className={`rounded-2xl px-3 py-3 ${open ? "bg-lavender ring-2 ring-jamie/40" : "bg-lavender/50"}`} data-target="question rueckfrage">
      <div className="flex items-center gap-2 text-[14px] font-bold text-jamie">
        <MessageCircleQuestion className="h-4.5 w-4.5" /> Question before building
      </div>
      {(() => {
        // The backend puts each quoted sentence on its own line and the question last.
        const lines = q.text.split("\n");
        const ask = lines.pop() ?? "";
        return (
          <>
            {lines.map((line, i) => (
              <p key={i} className="mt-1 text-[14px] leading-snug text-ink-2">
                {line}
              </p>
            ))}
            <p className="mt-1.5 text-[17px] leading-snug font-bold text-ink">{ask}</p>
          </>
        );
      })()}
      {open ? (
        <>
          <div className="mt-2.5 flex flex-wrap gap-2">
            {q.options.map((o) => (
              <button
                key={o.id}
                type="button"
                onClick={() => void answer(q.id, o.id)}
                className={`h-10 rounded-full px-4 text-[15px] font-bold transition ${
                  o.id === q.default_id ? "bg-jamie text-white hover:brightness-110" : "bg-card text-ink-2 ring-1 ring-line hover:bg-page-2"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
          {q.timeout_s > 0 && (
            <p className="num mt-2 text-[13px] font-semibold text-muted">
              Answer by voice or click · otherwise “{q.options.find((o) => o.id === q.default_id)?.label}” in {left} s
            </p>
          )}
        </>
      ) : (
        <p className="mt-1.5 text-[14px] font-semibold text-ok-ink">✓ {picked?.label ?? "answered"}</p>
      )}
    </div>
  );
}

function VersionPartRenderer({ item }: { item: Extract<ChatItem, { kind: "version" }> }) {
  const v = useSession((s) => s.versions.find((x) => x.n === item.n));
  const selectVersion = useUi((s) => s.selectVersion);
  if (!v) return null;
  const fmt = (value: number | string, unit: string) => (typeof value === "number" ? `${fmtNum(value, unit === "€" ? 2 : 1)} ${unit}` : value);
  return (
    <button type="button" onClick={() => selectVersion(null)} className="w-full rounded-[14px] bg-card p-3 text-left ring-1 ring-line">
      <div className="flex items-center gap-2 text-[14px] font-bold text-ok-ink">
        <GitCompareArrows className="h-4.5 w-4.5" /> Version {v.n} · from {v.meeting_title}
      </div>
      {v.diff.length > 0 ? (
        <ul className="num mt-1.5 space-y-0.5">
          {v.diff.map((d) =>
            d.unit ? (
              <li key={d.key} className="flex items-baseline gap-2 text-[15px]">
                <span className="w-[118px] shrink-0 font-semibold text-ink-2">{enLabel(d.label)}</span>
                <span className="text-muted">{fmt(d.before, d.unit)}</span>
                <ArrowRight className="h-3.5 w-3.5 shrink-0 self-center text-muted" />
                <span className="font-bold text-ink">{fmt(d.after, d.unit)}</span>
              </li>
            ) : (
              <li key={d.key} className="flex gap-2 pt-0.5 text-[15px]">
                <span className="w-[118px] shrink-0 font-semibold text-ink-2">{enLabel(d.label)}</span>
                <span className="min-w-0 leading-snug">
                  <span className="block truncate text-muted line-through decoration-faint">{d.before}</span>
                  <span className="block truncate font-bold text-ink">{d.after}</span>
                </span>
              </li>
            ),
          )}
        </ul>
      ) : (
        <p className="mt-1 text-[14px] leading-snug text-ink-2">{v.summary}</p>
      )}
    </button>
  );
}

/** Consecutive finished calls of one tool, such as the five part choices, as one card. */
export function ToolGroupRenderer({ items }: { items: Extract<ChatItem, { kind: "tool" }>[] }) {
  return (
    <div className="rounded-[14px] bg-page-2 px-3 py-2.5">
      <div className="mb-1 flex items-center gap-2.5">
        <PhaseIcon phase="ok" />
        <span className="text-[14px] font-semibold text-ink-2">{getToolLabel(items[0].name, "ok")}</span>
        <span className="num ml-auto text-[12px] text-faint">{items.length}×</span>
      </div>
      <ul className="space-y-0.5 pl-[30px]">
        {items.map((item) => (
          <li key={item.id} className="truncate text-[13px] text-muted">
            {enText(item.detail).replace(/^(Picked|Gewählt): /, "")}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Tool calls in a row, folded into one quiet progress line while tool details are hidden. */
export function ProgressLineRenderer({ items }: { items: Extract<ChatItem, { kind: "tool" }>[] }) {
  const running = items.filter((i) => i.phase === "running").at(-1);
  const failed = items.some((i) => i.phase === "error");
  const names = [...new Set(items.map((i) => i.name))];
  return (
    <div className="flex min-w-0 items-center gap-2 py-0.5 pl-9 text-[13px] text-muted" data-target="tool_progress">
      <PhaseIcon phase={running ? "running" : failed ? "error" : "ok"} />
      <span className="truncate">{running ? getToolLabel(running.name, "running") : names.join(" · ")}</span>
    </div>
  );
}

/** Several Jamie writes in a row (tags, note, tasks) as one card. */
export function JamieGroupRenderer({ items }: { items: Extract<ChatItem, { kind: "jamie" }>[] }) {
  const local = items.some((item) => /lokale Outbox|local outbox/.test(item.detail));
  return (
    <div className="rounded-[14px] bg-page-2 px-3 py-2.5 ring-1 ring-line">
      <div className="mb-1 flex items-center gap-2 text-[14px] font-bold text-jamie">
        <NotebookPen className="h-4 w-4" /> Jamie
        {local && <span className="ml-auto rounded-full bg-white/70 px-2 py-0.5 text-[12px] font-semibold text-muted">local outbox</span>}
      </div>
      <ul className="space-y-0.5">
        {items.map((item) => (
          <li key={item.id} className="flex min-w-0 items-center gap-2">
            <PhaseIcon phase={item.phase} />
            <span className="shrink-0 text-[14px] font-semibold text-ink-2">{JAMIE_ACTIONS[item.action] ?? item.action.replace(/_/g, " ")}</span>
            <span className="truncate text-[13px] text-muted">{enText(item.detail).replace(/ · local outbox$/, "")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const AGENT_ICON = { orchestrator: Network, cad: DraftingCompass, parts: Package, checks: Gauge, pricing: Receipt } as const;

const fmtTokens = (n: number) => (n >= 1000 ? `${fmtNum(n / 1000, n >= 10000 ? 0 : 1)}k` : fmtNum(n));

/** The orchestrator or a sub-agent: who, which model, what job, status, tokens and cost. */
function AgentPartRenderer({ item }: { item: Extract<ChatItem, { kind: "agent" }> }) {
  const agent = useSession((s) => s.agents[item.agentId]);
  if (!agent) return null;
  const Icon = AGENT_ICON[agent.role] ?? Cpu;
  const phase = agent.status === "running" ? "running" : agent.status === "error" ? "error" : "ok";
  const lead = agent.role === "orchestrator";
  return (
    <div className={`rounded-[14px] px-3 py-2.5 ${lead ? "bg-card ring-1 ring-line" : "bg-page-2"}`} data-target={`agent:${agent.role}`}>
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white shadow-[var(--shadow-pill)]">
          <Icon className={`h-4 w-4 ${lead ? "text-accent" : "text-ink-2"}`} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[14px] font-bold text-ink">
            {agent.label} <span className="font-semibold text-muted">· {agent.model_label} · {agent.effort}</span>
          </div>
          <div className="truncate text-[13px] text-ink-2">{agent.task}</div>
        </div>
        <PhaseIcon phase={phase} />
      </div>
      {agent.summary && <p className="mt-1.5 line-clamp-2 text-[13px] leading-snug text-muted">{stripMarkdown(agent.summary).replace(/\s+/g, " ")}</p>}
      <div className="num mt-1 text-[12px] font-semibold text-faint">
        {agent.rounds} call{agent.rounds === 1 ? "" : "s"} · {fmtTokens(agent.input_tokens + agent.cache_read_tokens)} in · {fmtTokens(agent.output_tokens)} out · $
        {fmtNum(agent.cost_usd, agent.cost_usd < 0.1 ? 3 : 2)}
      </div>
    </div>
  );
}

function ContentPartsRenderer({ item }: { item: Exclude<ChatItem, { kind: "msg" }> }) {
  switch (item.kind) {
    case "tool":
      return <ToolCallPartRenderer item={item} />;
    case "jamie":
      return <JamiePartRenderer item={item} />;
    case "sim":
      return <SimPartRenderer item={item} />;
    case "bom":
      return <BomPartRenderer item={item} />;
    case "training":
      return <TrainingPartRenderer item={item} />;
    case "warning":
      return <WarningPartRenderer item={item} />;
    case "question":
      return <QuestionPartRenderer item={item} />;
    case "version":
      return <VersionPartRenderer item={item} />;
    case "agent":
      return <AgentPartRenderer item={item} />;
    case "stress":
      return <StressCard run={item.run} />;
  }
}

export default memo(ContentPartsRenderer);
