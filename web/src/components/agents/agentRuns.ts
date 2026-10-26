// The orchestrator runs and the sub-agents each one delegated to, derived from the `agent`
// events in the log: one node per agent with its start, end and every report it sent.
import { useMemo } from "react";
import {
  Camera,
  Cpu,
  DraftingCompass,
  Eye,
  Gauge,
  Network,
  Package,
  Receipt,
  Rocket,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useSession } from "../../events/store";
import type { AgentRunEvent } from "../../events/types";

export interface AgentReport {
  at: number;
  status: AgentRunEvent["status"];
  summary: string;
  tool: string | null;
}

export interface AgentNode {
  ev: AgentRunEvent;
  /** When it started working, ms; null while queued. */
  start: number | null;
  /** When it was first seen, ms: the start of its queued time. */
  seen: number;
  /** When it finished, ms; null while it is queued or working. */
  end: number | null;
  reports: AgentReport[];
}

export interface AgentTeamRun {
  /** The orchestrator, or null for sub-agents that ran without one (a direct tool call). */
  lead: AgentNode | null;
  subs: AgentNode[];
  /** First start and last end (or now) of the whole run, ms. */
  from: number;
  to: number | null;
  costUsd: number;
  /** "subscription" when the run went through the local Claude Code login. */
  billing: "api" | "subscription";
  tokens: number;
}

/** Collects every `agent` event of the log into runs, oldest first. */
export function useAgentRuns(): AgentTeamRun[] {
  const log = useSession((s) => s.log);
  return useMemo(() => {
    const nodes = new Map<string, AgentNode>();
    for (const logged of log) {
      const ev = logged.ev;
      if (ev.type !== "agent") continue;
      // Server times when the backend sends them: a replayed backlog keeps its real timing.
      const at = ev.sent_at != null ? ev.sent_at * 1000 : logged.at;
      const start = ev.started_at != null ? ev.started_at * 1000 : ev.status === "queued" ? null : at;
      const end = ev.ended_at != null ? ev.ended_at * 1000 : ev.status === "done" || ev.status === "error" ? at : null;
      const known = nodes.get(ev.id);
      const report: AgentReport = { at, status: ev.status, summary: ev.summary, tool: ev.tool ?? null };
      if (!known) {
        nodes.set(ev.id, { ev, start, seen: start ?? at, end, reports: [report] });
        continue;
      }
      known.ev = ev;
      known.start = known.start ?? start;
      known.end = end;
      const last = known.reports[known.reports.length - 1];
      if (last.summary !== report.summary || last.status !== report.status || last.tool !== report.tool) known.reports.push(report);
    }
    const all = [...nodes.values()];
    const leads = all.filter((n) => n.ev.role === "orchestrator");
    const runs: AgentTeamRun[] = leads.map((lead) => ({ lead, subs: [], from: 0, to: null, costUsd: 0, billing: "api", tokens: 0 }));
    const solo: AgentNode[] = [];
    for (const node of all) {
      if (node.ev.role === "orchestrator") continue;
      let run: AgentTeamRun | undefined;
      if (node.ev.parent !== undefined) {
        run = runs.find((r) => r.lead?.ev.id === node.ev.parent);
      } else {
        // An older backend names no parent: the latest orchestrator that started before it.
        run = [...runs].reverse().find((r) => (r.lead?.seen ?? 0) <= node.seen);
      }
      if (run) run.subs.push(node);
      else solo.push(node);
    }
    if (solo.length) runs.push({ lead: null, subs: solo, from: 0, to: null, costUsd: 0, billing: "api", tokens: 0 });
    for (const run of runs) {
      const members = run.lead ? [run.lead, ...run.subs] : run.subs;
      run.from = Math.min(...members.map((n) => n.seen));
      run.to = members.some((n) => n.end === null) ? null : Math.max(...members.map((n) => n.end ?? 0));
      run.costUsd = members.reduce((sum, n) => sum + n.ev.cost_usd, 0);
      run.billing = members.some((n) => n.ev.billing === "subscription") ? "subscription" : "api";
      run.tokens = members.reduce((sum, n) => sum + n.ev.input_tokens + n.ev.output_tokens + n.ev.cache_read_tokens, 0);
    }
    return runs.sort((a, b) => a.from - b.from);
  }, [log]);
}

export type ModelFamily = "opus" | "sonnet" | "haiku" | "fable" | "other";

export function modelFamily(model: string): ModelFamily {
  const m = model.toLowerCase();
  if (m.includes("opus")) return "opus";
  if (m.includes("sonnet")) return "sonnet";
  if (m.includes("haiku")) return "haiku";
  if (m.includes("fable")) return "fable";
  return "other";
}

/** Chip and bar colors per model family; Opus leads in teal, Sonnet works in blue. */
export const MODEL_STYLE: Record<ModelFamily, { chip: string; bar: string }> = {
  opus: { chip: "bg-accent-soft text-accent", bar: "bg-accent" },
  sonnet: { chip: "bg-[#e6effd] text-[#2a5aa8]", bar: "bg-[#5b8fe0]" },
  haiku: { chip: "bg-lavender text-violet", bar: "bg-violet" },
  fable: { chip: "bg-agent-soft text-agent-ink", bar: "bg-agent" },
  other: { chip: "bg-tile text-ink-2", bar: "bg-ink-2" },
};

export const ROLE_ICON: Record<string, LucideIcon> = {
  orchestrator: Network,
  cad: DraftingCompass,
  parts: Package,
  checks: Gauge,
  pricing: Receipt,
  sketch: Eye,
};

export const roleIcon = (role: string): LucideIcon => ROLE_ICON[role] ?? Cpu;

/** The software behind a tool name, for the chip on a working node. */
export function toolInfo(tool: string): { label: string; icon: LucideIcon } {
  // Mechanic looking at his model: VTK renders it, not FreeCAD.
  if (tool === "cad_view") return { label: "VTK", icon: Eye };
  if (tool === "freecad" || tool.startsWith("cad_")) return { label: tool === "cad_part" ? "Script" : "FreeCAD", icon: DraftingCompass };
  if (tool.startsWith("blender")) return { label: "Blender", icon: Camera };
  if (tool.startsWith("simulate") || tool.startsWith("stress") || tool === "physics_calc") return { label: "MuJoCo", icon: Rocket };
  if (tool.startsWith("part")) return { label: "Catalog", icon: Package };
  if (tool === "bom_build") return { label: "BOM", icon: Receipt };
  if (tool.startsWith("check") || tool === "assemble") return { label: "Checks", icon: Gauge };
  if (tool === "delegate") return { label: "Delegating", icon: Network };
  return { label: tool.replace(/_/g, " "), icon: Wrench };
}

/** A short name for a node: "CAD · frame" for a part's CAD agent, else the label without "agent". */
export function shortName(ev: AgentRunEvent): string {
  if (ev.role === "cad") {
    const part = ev.task.replace(/^FreeCAD script for (the )?/i, "");
    return part && part !== ev.task ? `CAD · ${part}` : ev.label;
  }
  return ev.label.replace(/ agent$/i, "");
}

export const fmtTokens = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n));
export const fmtCost = (usd: number, billing?: string) => (billing === "subscription" ? "subscription" : `$${usd.toFixed(usd < 0.1 ? 3 : 2)}`);
export function fmtSeconds(ms: number): string {
  const s = Math.max(0, ms) / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")} min`;
}
