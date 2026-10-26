// Learning mode: Mechanic explains a decision with the physics and the real numbers.
// The backend computes the facts and the formula (POST /api/explain) and publishes the answer
// as an `explain` event; the card shows the sentences, the formula line, the numbers as chips
// and whether Claude Haiku or the template wrote the text. A "Why?" asks on click; live
// events (a part swap, a failed check or run, a frame parameter change) ask on their own.
import { useEffect, useState } from "react";
import { useSession } from "../../events/store";
import { useSource } from "../../events/source";
import { isSlider, type AgentEvent, type ExplainEvent } from "../../events/types";
import { apiFetch } from "../../lib/api";
import { useUi } from "../../lib/ui";
import { Chip } from "../ui/primitives";
import { Glossed } from "./Term";

export type ExplainKind = ExplainEvent["kind"];

const fmtValue = (v: number | string) => (typeof v === "number" ? String(Number(v.toFixed(3))) : v);

/** Asks the backend; the answer arrives as an `explain` event too. Null when there is nothing to explain yet. */
export async function requestExplain(kind: ExplainKind, id: string, chat = false): Promise<ExplainEvent | null> {
  try {
    const res = await apiFetch("/api/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, id, chat }),
    });
    if (!res.ok) return null;
    const body = (await res.json()) as Omit<ExplainEvent, "type">;
    return { type: "explain", ...body };
  } catch {
    return null;
  }
}

export function ExplainCard({ ev, compact = false }: { ev: ExplainEvent; compact?: boolean }) {
  return (
    <div className={`animate-rise rounded-[16px] bg-agent-soft ${compact ? "px-3.5 py-3" : "px-4 py-3.5"}`} data-target={`explain:${ev.kind}:${ev.target_id}`}>
      <div className="flex items-center gap-2">
        <span className="text-[12px] font-extrabold tracking-[0.08em] text-agent-ink">WHY</span>
        <span className="ml-auto text-[12px] font-semibold text-agent-ink/80">{ev.source === "claude" ? "Claude Haiku" : "Template"}</span>
      </div>
      <p className="mt-0.5 text-[15px] leading-snug font-bold text-ink">{ev.title}</p>
      <p className="mt-1 text-[15px] leading-snug text-ink-2">
        <Glossed text={ev.text} />
      </p>
      {ev.formula && (
        <p className="num mt-2 rounded-[10px] bg-card/70 px-2.5 py-1.5 text-[13px] leading-snug font-semibold text-ink">
          <Glossed text={ev.formula} />
        </p>
      )}
      {ev.numbers.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {ev.numbers.map((nb) => (
            <Chip key={nb.label} tone="muted" className="num bg-card text-ink-2">
              <span className="text-muted">{nb.label}</span> {fmtValue(nb.value)}
              {nb.unit ? ` ${nb.unit}` : ""}
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

/** The chat card for an explanation a live event asked for. */
export function ExplainChatCard({ explainKey }: { explainKey: string }) {
  const ev = useSession((s) => s.explains[explainKey]);
  const learning = useUi((s) => s.display.learning);
  if (!ev || !learning) return null;
  return <ExplainCard ev={ev} compact />;
}

/** "Why?" next to a requirement or part: only in learning mode with the live backend. */
export function WhyButton({ kind, id, label = "Why?", className = "" }: { kind: ExplainKind; id: string; label?: string; className?: string }) {
  const learning = useUi((s) => s.display.learning);
  const live = useSource((s) => s.mode === "live");
  const [open, setOpen] = useState(false);
  const [ev, setEv] = useState<ExplainEvent | null>(null);
  const [missing, setMissing] = useState(false);
  if (!learning || !live) return null;
  const toggle = async () => {
    if (open) return setOpen(false);
    setOpen(true);
    const answer = await requestExplain(kind, id);
    setEv(answer);
    setMissing(!answer);
  };
  return (
    <span className={`block ${className}`}>
      <button
        type="button"
        onClick={() => void toggle()}
        className={`h-7 rounded-full px-3 text-[13px] font-bold transition ${open ? "bg-agent-ink text-white" : "bg-agent-soft text-agent-ink hover:brightness-95"}`}
        aria-expanded={open}
      >
        {label}
      </button>
      {open && (
        <span className="mt-2 block">
          {ev ? <ExplainCard ev={ev} compact /> : <span className="text-[13px] text-muted">{missing ? "Nothing to explain until the check has run." : "Explaining …"}</span>}
        </span>
      )}
    </span>
  );
}

/** Learning mode: live decisions ask for an explanation on their own, at most one per target per build. */
export function useAutoExplain() {
  const learning = useUi((s) => s.display.learning);
  const live = useSource((s) => s.mode === "live");
  useEffect(() => {
    if (!learning || !live) return;
    const asked = new Set<string>();
    const parts: Record<string, string> = {};
    let swap: string | null = null;
    let frameError = false;
    let params: Record<string, number> = {};
    let seen = useSession.getState().log.at(-1)?.seq ?? 0;
    for (const { ev } of useSession.getState().log) remember(ev);

    function remember(ev: AgentEvent) {
      if (ev.type === "part") parts[ev.category] = ev.id;
      if (ev.type === "cad") for (const [k, p] of Object.entries(ev.params ?? {})) if (isSlider(p)) params[k] = p.value;
    }
    function ask(kind: ExplainKind, id: string) {
      if (asked.has(`${kind}:${id}`)) return;
      asked.add(`${kind}:${id}`);
      void requestExplain(kind, id, true);
    }

    return useSession.subscribe((s) => {
      if (s.log.length === 0) {
        // A reset emptied the session: start over.
        asked.clear();
        params = {};
        for (const k of Object.keys(parts)) delete parts[k];
        swap = null;
        frameError = false;
      }
      for (const entry of s.log) {
        if (entry.seq <= seen) continue;
        seen = entry.seq;
        const ev = entry.ev;
        if (entry.instant) {
          remember(ev);
          continue;
        }
        switch (ev.type) {
          case "part":
            if (parts[ev.category] && parts[ev.category] !== ev.id) swap = ev.category;
            break;
          case "metrics":
            if (swap) ask("swap", swap);
            swap = null;
            break;
          case "requirement":
            if (ev.met === false) ask("requirement", ev.id);
            break;
          case "sim":
            if (ev.result === "fail") ask("sim", String(ev.run));
            break;
          case "tool":
            if (ev.name === "cad_frame" && ev.status === "error") frameError = true;
            break;
          case "cad": {
            // A number explains its change; a switch or a choice has no formula to show.
            for (const [k, p] of Object.entries(ev.params ?? {})) {
              if (!isSlider(p)) continue;
              const changed = k in params && params[k] !== p.value;
              if (changed || (frameError && k === "arm_length_mm")) ask("param", k);
            }
            frameError = false;
            break;
          }
          case "version":
            // A new build may make the same decision again.
            asked.clear();
            break;
        }
        remember(ev);
      }
    });
  }, [learning, live]);
}
