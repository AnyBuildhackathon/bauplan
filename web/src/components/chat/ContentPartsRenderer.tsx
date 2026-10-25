// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/Chat/ContentPartsRenderer.tsx. Modified: renders our SSE
// chat items (tool, simulation, bill of materials, training) as Bevel tool
// cards instead of core.so's message content parts; markdown, display cards and
// actions were removed.
import { memo, useEffect, useState } from "react";
import {
  ArrowRight,
  CircleCheck,
  CircleX,
  Cpu,
  DraftingCompass,
  Gauge,
  GitCompareArrows,
  MessageCircleQuestion,
  Network,
  Package,
  Receipt,
  Sparkles,
} from "lucide-react";
import { useSession, type ChatItem } from "../../events/store";
import { useSource } from "../../events/source";
import { enLabel, enText } from "../../lib/copy";
import { fmtDuration, fmtNum, stripMarkdown } from "../../lib/format";
import { useUi } from "../../lib/ui";
import { StressCard } from "../stress/StressCard";
import { PrintPlanCard } from "../print/PrintPlanCard";
import { ExplainChatCard } from "../learn/Explain";
import { RequirementsCard, ResultsCard } from "./BuildCards";
import { SafetyCard } from "../safety/SafetyCard";
import { OptimizeCard } from "./OptimizeCard";
import { useSimPane } from "../training/useBrowserTraining";

const TOOL_LABELS: Record<string, { running: string; done: string }> = {
  Claude: { running: "Claude is thinking", done: "Claude" },
  CadQuery: { running: "CadQuery is building", done: "CadQuery" },
  MuJoCo: { running: "MuJoCo is simulating", done: "MuJoCo" },
  Blender: { running: "Blender is rendering", done: "Blender" },
  "Isaac Sim": { running: "Isaac Sim is starting", done: "Isaac Sim" },
  "Isaac Lab": { running: "Isaac Lab is training", done: "Isaac Lab" },
  RunPod: { running: "RunPod is starting the GPU", done: "RunPod" },
  Parts: { running: "Picking parts", done: "Parts" },
  Reson8: { running: "Reson8 is listening", done: "Reson8" },
};

function getToolLabel(name: string, phase: string): string {
  const l = TOOL_LABELS[name];
  if (!l) return phase === "running" ? `${name} running` : name;
  return phase === "running" ? l.running : l.done;
}

function PhaseIcon({ phase, small = false }: { phase: "running" | "ok" | "error"; small?: boolean }) {
  const size = small ? "h-3.5 w-3.5" : "h-5 w-5";
  if (phase === "running") {
    return (
      <span className={`flex shrink-0 items-center justify-center ${size}`}>
        <span className={`animate-pulse-soft rounded-full bg-agent ${small ? "h-2 w-2" : "h-2.5 w-2.5"}`} />
      </span>
    );
  }
  if (phase === "error") return <CircleX className={`shrink-0 text-fail ${size}`} strokeWidth={2.2} />;
  return <CircleCheck className={`shrink-0 text-ok ${size}`} strokeWidth={2.2} />;
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
        {item.detail && <div className="truncate font-label text-[12px] text-muted">{enText(item.detail)}</div>}
      </div>
      {duration != null && duration > 0 && <span className="num shrink-0 font-label text-[12px] text-faint">{fmtDuration(duration)}</span>}
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

/** One simulate_mission call: each mission with its result and number; a click opens its replay. */
function MissionsPartRenderer({ item }: { item: Extract<ChatItem, { kind: "missions" }> }) {
  const runs = useSession((s) => s.missionRuns);
  const setTab = useUi((s) => s.setTab);
  const setView = useUi((s) => s.setView);
  const selectMission = useUi((s) => s.selectMission);
  const rows = item.runs.flatMap((n) => (runs[n] ? [runs[n]] : []));
  const passed = rows.filter((r) => r.result === "pass").length;
  const open = (run: number) => {
    setView("werkbank");
    setTab("simulation");
    useSimPane.getState().setPane("missions");
    selectMission(run);
  };
  return (
    <div className={`w-full rounded-2xl p-3 ${passed === rows.length ? "bg-ok-soft" : "bg-fail-soft"}`}>
      <div className={`text-[14px] font-bold ${passed === rows.length ? "text-ok-ink" : "text-fail-ink"}`}>
        Missions · {passed} of {rows.length} passed
      </div>
      <div className="mt-1.5 flex flex-col gap-1">
        {rows.map((r) => (
          <button key={r.run} type="button" onClick={() => open(r.run)} className="group flex items-start gap-2 text-left">
            {r.result === "pass" ? (
              <CircleCheck className="mt-0.5 h-4 w-4 shrink-0 text-ok" strokeWidth={2.2} />
            ) : (
              <CircleX className="mt-0.5 h-4 w-4 shrink-0 text-fail" strokeWidth={2.2} />
            )}
            <span className="min-w-0 flex-1 text-[14px] leading-snug text-ink-2">
              <span className="font-semibold text-ink">{r.label}.</span> {r.summary.replace(/^(Pass|Fail)\. /, "")}
            </span>
            <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-muted transition group-hover:translate-x-0.5" />
          </button>
        ))}
      </div>
    </div>
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
        <div className="truncate font-label text-[12px] text-muted">Isaac Lab · {item.detail}</div>
      </div>
      <Cpu className="h-4 w-4 text-muted" />
    </button>
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
  const fallback = q.options.find((o) => o.id === q.default_id);
  // The backend puts each quoted sentence on its own line and the question last.
  const lines = q.text.split("\n");
  const ask = lines.pop() ?? "";
  return (
    <div
      className={`rounded-2xl px-3.5 py-3 ${open ? "bg-card shadow-[var(--shadow-pill)] ring-1 ring-line" : "bg-page-2"}`}
      data-target="question rueckfrage"
    >
      <div className="flex items-center gap-1.5 text-[12px] font-semibold text-muted">
        <MessageCircleQuestion className="h-3.5 w-3.5 text-violet" /> Question before building
      </div>
      {lines.length > 0 && (
        <div className="mt-2 space-y-1 border-l-2 border-line pl-2.5">
          {lines.map((line, i) => (
            <p key={i} className="text-[13px] leading-snug text-muted">
              {line}
            </p>
          ))}
        </div>
      )}
      <p className="mt-2 text-[15px] leading-snug font-semibold text-ink">{ask}</p>
      {open ? (
        <>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {q.options.map((o) => (
              <button
                key={o.id}
                type="button"
                onClick={() => void answer(q.id, o.id)}
                className={`h-8 rounded-[10px] px-3 text-[13px] transition hover:bg-page-2 ${
                  o.id === q.default_id ? "bg-card font-semibold text-ink ring-1 ring-ink/25" : "bg-card font-medium text-ink-2 ring-1 ring-line"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
          {q.timeout_s > 0 && (
            <div className="mt-3">
              <div className="h-0.5 overflow-hidden rounded-full bg-track">
                <div
                  className="h-full rounded-full bg-ink/30 transition-[width] duration-500 ease-linear"
                  style={{ width: `${(left / q.timeout_s) * 100}%` }}
                />
              </div>
              <p className="num mt-1.5 text-[12px] text-muted">
                Answer by voice or click. Otherwise {fallback?.label} in {left} s.
              </p>
            </div>
          )}
        </>
      ) : (
        <p className="mt-2 flex items-center gap-1.5 text-[13px] font-semibold text-ok-ink">
          <CircleCheck className="h-3.5 w-3.5" strokeWidth={2.4} /> {picked?.label ?? "Answered"}
        </p>
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
        <GitCompareArrows className="h-4.5 w-4.5" /> Version {v.n}{v.label ? ` · ${v.label}` : ""}
      </div>
      {v.diff.length > 0 ? (
        <ul className="num mt-1.5 space-y-0.5">
          {v.diff.map((d) =>
            d.unit ? (
              <li key={d.key} className="flex items-baseline gap-2 text-[13px]">
                <span className="w-[104px] shrink-0 font-semibold text-ink-2">{enLabel(d.label)}</span>
                <span className="font-label text-[12px] text-muted">{fmt(d.before, d.unit)}</span>
                <ArrowRight className="h-3.5 w-3.5 shrink-0 self-center text-muted" />
                <span className="font-label text-[12px] font-semibold text-ink">{fmt(d.after, d.unit)}</span>
              </li>
            ) : (
              <li key={d.key} className="flex gap-2 pt-0.5 text-[13px]">
                <span className="w-[104px] shrink-0 font-semibold text-ink-2">{enLabel(d.label)}</span>
                <span className="min-w-0 leading-snug">
                  <span className="block truncate text-muted line-through decoration-faint">{d.before}</span>
                  <span className="block truncate font-bold text-ink">{d.after}</span>
                </span>
              </li>
            ),
          )}
        </ul>
      ) : (
        <p className="mt-1 font-label text-[12px] text-ink-2">{v.summary}</p>
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
        <span className="num ml-auto font-label text-[12px] text-faint">{items.length}×</span>
      </div>
      <ul className="space-y-0.5 pl-[30px]">
        {items.map((item) => (
          <li key={item.id} className="truncate font-label text-[12px] text-muted">
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
    <div className="flex min-w-0 items-center gap-1.5 font-label text-[12px] text-faint" data-target="tool_progress">
      <PhaseIcon phase={running ? "running" : failed ? "error" : "ok"} small />
      <span className="truncate">{running ? getToolLabel(running.name, "running") : names.join(" · ")}</span>
    </div>
  );
}

const AGENT_ICON = { orchestrator: Network, cad: DraftingCompass, parts: Package, checks: Gauge, pricing: Receipt, optimizer: Sparkles } as const;

const fmtTokens = (n: number) => (n >= 1000 ? `${fmtNum(n / 1000, n >= 10000 ? 0 : 1)}k` : fmtNum(n));

/** The orchestrator or a sub-agent: who, which model, what job, status, tokens and cost. */
function AgentPartRenderer({ item }: { item: Extract<ChatItem, { kind: "agent" }> }) {
  const agent = useSession((s) => s.agents[item.agentId]);
  if (!agent) return null;
  const Icon = AGENT_ICON[agent.role as keyof typeof AGENT_ICON] ?? Cpu;
  const phase = agent.status === "running" || agent.status === "queued" ? "running" : agent.status === "error" ? "error" : "ok";
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
      <div className="num mt-1 font-label text-[12px] font-semibold text-faint">
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
    case "sim":
      return <SimPartRenderer item={item} />;
    case "missions":
      return <MissionsPartRenderer item={item} />;
    case "bom":
      return <ResultsCard item={item} />;
    case "requirements":
      return <RequirementsCard />;
    case "training":
      return <TrainingPartRenderer item={item} />;
    case "question":
      return <QuestionPartRenderer item={item} />;
    case "version":
      return <VersionPartRenderer item={item} />;
    case "agent":
      return <AgentPartRenderer item={item} />;
    case "stress":
      return <StressCard run={item.run} />;
    case "explain":
      return <ExplainChatCard explainKey={item.key} />;
    case "print":
      return <PrintPlanCard plan={item.plan} />;
    case "safety":
      return <SafetyCard safety={item.safety} />;
    case "optimize":
      return <OptimizeCard optimizeId={item.optimizeId} />;
  }
}

export default memo(ContentPartsRenderer);
