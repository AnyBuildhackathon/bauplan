// The one compact panel on the right: the requirements as checks (from Jamie or the chat
// request), the four key numbers, and the button that opens the bill of materials.
import { useState } from "react";
import { Check, ChevronRight, X } from "lucide-react";
import { useSession } from "../../events/store";
import type { MetricCard, Quote, RequirementEvent } from "../../events/types";
import { meets, type MetricKey } from "../../lib/derived";
import { fmtEur, fmtGram, fmtMin, fmtNum, fmtRatio } from "../../lib/format";
import { useShownBuild, useTargets } from "../../lib/hooks";
import { useUi } from "../../lib/ui";
import { TrainedGains } from "../training/TrainedGains";

export function JamieMark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex h-6 items-center gap-1 rounded-full bg-lavender px-2.5 text-[12px] font-bold text-jamie ${className}`}>
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
        <circle cx="5" cy="5" r="4" fill="currentColor" />
      </svg>
      Jamie
    </span>
  );
}

/** A Jamie quote as a source citation: who said it, in which meeting, when, then the words. */
export function QuoteBubble({ quote, className = "" }: { quote: Pick<Quote, "text"> & Partial<Quote>; className?: string }) {
  const by = [quote.speaker, quote.meeting_title, quote.time].filter(Boolean).join(" · ");
  return (
    <div className={`animate-rise rounded-[14px] bg-page-2 px-3.5 py-3 ${className}`}>
      {by && <p className="mb-1 text-[12px] font-medium text-muted">{by}</p>}
      <p className="font-read text-[14px] leading-normal text-ink-2">“{quote.text}”</p>
    </div>
  );
}

function CheckDot({ state }: { state: "ok" | "fail" | "open" }) {
  if (state === "open") return <span className="mt-0.5 h-[22px] w-[22px] shrink-0 rounded-full shadow-[inset_0_0_0_2px_var(--color-track)]" />;
  return (
    <span
      className={`mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full ${state === "ok" ? "bg-ok-soft text-ok-ink" : "bg-fail-soft text-fail-ink"}`}
    >
      {state === "ok" ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : <X className="h-3.5 w-3.5" strokeWidth={3} />}
    </span>
  );
}

/** One requirement as a cited source: the check, who asked for it and when, and the quote. */
function RequirementRow({ r, open, onToggle }: { r: RequirementEvent; open: boolean; onToggle: () => void }) {
  const state = r.met === true ? "ok" : r.met === false ? "fail" : "open";
  const by = [r.speaker, r.meeting_title, r.time].filter(Boolean).join(" · ");
  return (
    <li data-target={`requirement:${r.id} ${r.id}`} data-state={state}>
      <button
        type="button"
        onClick={onToggle}
        className={`flex w-full gap-3 rounded-[14px] px-2 py-2 text-left transition ${open ? "bg-page-2" : "hover:bg-page-2"}`}
      >
        <CheckDot state={state} />
        <span className="min-w-0 flex-1">
          <span className={`block text-[15px] leading-snug font-medium ${r.met === false ? "text-fail-ink" : "text-ink"}`}>{r.text}</span>
          {r.changed_from && <span className="block text-[13px] font-medium text-muted line-through decoration-faint">{r.changed_from}</span>}
          {r.detail && <span className={`num block text-[13px] font-semibold ${r.met === false ? "text-fail-ink" : "text-muted"}`}>{r.detail}</span>}
          {open && (by || r.source_quote) && (
            <span className="mt-1.5 block animate-rise">
              {by && <span className="block text-[12px] font-medium text-muted">{by}</span>}
              {r.source_quote && <span className="block font-read text-[14px] leading-normal text-ink-2">“{r.source_quote}”</span>}
            </span>
          )}
        </span>
      </button>
    </li>
  );
}

const METRICS: { key: MetricKey; label: string; unit: string; target: string; format: (v: number) => string }[] = [
  { key: "weight_g", label: "Weight", unit: "g", target: "metric:weight weight weight_g gewicht", format: (v) => fmtNum(v, v < 100 ? 1 : 0) },
  { key: "thrust_to_weight", label: "Thrust to weight", unit: ": 1", target: "metric:thrust_to_weight thrust_to_weight schub tw", format: fmtRatio },
  { key: "flight_time_min", label: "Flight time", unit: "min", target: "metric:flight_time flight_time flight_time_min flugzeit", format: fmtMin },
  { key: "price_eur", label: "Price", unit: "€", target: "metric:price price price_eur preis budget", format: (v) => fmtNum(v, 2) },
];

function limitText(key: MetricKey, value: number, direction: "max" | "min") {
  const v =
    key === "weight_g" ? fmtGram(value) : key === "price_eur" ? fmtEur(value) : key === "flight_time_min" ? `${fmtMin(value)} min` : `${fmtRatio(value)} : 1`;
  return `${direction === "max" ? "max." : "min."} ${v}`;
}

/** Key numbers a product sends itself (the gripper), already judged against its limits. */
function CardGrid({ cards, busy, compact }: { cards: MetricCard[]; busy: boolean; compact: boolean }) {
  return (
    <div className={`grid gap-x-4 gap-y-4 ${compact ? "grid-cols-3" : "grid-cols-2"}`}>
      {cards.map((c) => (
        <div key={c.key} data-target={`metric:${c.key} ${c.key}`} className="min-w-0">
          <div className="flex items-center gap-1.5 text-[14px] font-medium text-muted">
            <span className={`h-2 w-2 rounded-full ${c.pending ? "bg-track" : c.ok ? "bg-ok" : "bg-fail"}`} />
            {c.label}
          </div>
          <div className={`num mt-1 flex items-baseline gap-1 ${c.pending ? "text-faint" : busy ? "text-agent-ink" : c.ok ? "text-ink" : "text-fail-ink"}`}>
            <span className={`${compact ? "text-[26px]" : "text-[32px]"} leading-none font-semibold tracking-[-0.025em]`}>{c.pending ? "–" : fmtNum(c.value, c.digits)}</span>
            <span className="text-[15px] font-medium text-muted">{c.unit}</span>
          </div>
          <div className="num mt-1 truncate text-[13px] font-medium text-muted">{c.limit || "\u00a0"}</div>
        </div>
      ))}
    </div>
  );
}

export function BuildPanel() {
  const requirements = useSession((s) => s.requirements);
  const bom = useSession((s) => s.bom);
  const simRunning = useSession((s) => s.steps.simulation.status === "running");
  const setBomOpen = useUi((s) => s.setBomOpen);
  const targets = useTargets();
  const { metrics, previous, version, pinned } = useShownBuild();
  const product = useSession((s) => s.product);
  const cards = useSession((s) => s.metrics?.cards);
  const [open, setOpen] = useState<string | null>(null);
  const allMetrics = useUi((s) => s.display.allMetrics);
  const met = requirements.filter((r) => r.met === true).length;

  return (
    <aside className="card flex max-h-full min-h-0 flex-col self-start overflow-hidden px-5 pt-4 pb-5">
      <div className="mb-3 flex items-center gap-2" data-target="metrics kennzahlen">
        <h2 className="text-[15px] font-semibold text-ink">Requirements and key numbers</h2>
        {version && (
          <span className={`num ml-auto text-[13px] font-medium ${pinned ? "text-agent-ink" : "text-muted"}`} title={version.meeting_title}>
            v{version.n}
          </span>
        )}
      </div>
      {product !== "drone" && cards ? (
        <CardGrid cards={allMetrics ? cards : cards.slice(0, 3)} busy={simRunning} compact={!allMetrics} />
      ) : product !== "drone" ? (
        <p className="py-1 text-[15px] leading-snug text-muted">Key numbers appear once Mechanic has chosen the parts.</p>
      ) : (
      <div className={`grid gap-x-4 gap-y-4 ${allMetrics ? "grid-cols-2" : "grid-cols-3"}`}>
        {METRICS.filter((m) => allMetrics || m.key !== "thrust_to_weight").map((m) => {
          const value = metrics?.[m.key];
          const t = targets[m.key];
          const ok = value !== undefined && meets(t, value);
          const tone = value === undefined ? "text-faint" : simRunning && !pinned ? "text-agent-ink" : ok ? "text-ink" : "text-fail-ink";
          const prev = previous?.[m.key];
          const changed = prev !== undefined && value !== undefined && m.format(prev) !== m.format(value);
          return (
            <div key={m.key} data-target={m.target} className="min-w-0">
              <div className="flex items-center gap-1.5 text-[14px] font-medium text-muted">
                <span className={`h-2 w-2 rounded-full ${value === undefined ? "bg-track" : ok ? "bg-ok" : "bg-fail"}`} />
                {m.label}
              </div>
              <div className={`num mt-1 flex items-baseline gap-1 ${tone}`}>
                <span className={`${allMetrics ? "text-[32px]" : "text-[26px]"} leading-none font-semibold tracking-[-0.025em]`}>{value === undefined ? "–" : m.format(value)}</span>
                <span className="text-[15px] font-medium text-muted">{m.unit}</span>
              </div>
              <div className="num mt-1 text-[13px] font-medium text-muted">
                {changed ? (
                  <>
                    before <span className="text-ink-2">{m.format(prev!)}</span>
                  </>
                ) : requirements.length > 0 ? (
                  limitText(m.key, t.value, t.direction)
                ) : (
                  "\u00a0"
                )}
              </div>
            </div>
          );
        })}
      </div>
      )}


      <div className="mt-5 mb-1 flex shrink-0 items-center gap-2 border-t border-line pt-4" data-target="requirements anforderungen">
        <h3 className="text-[14px] font-semibold text-ink-2">Requirements</h3>
        {product === "drone" ? (
          <JamieMark />
        ) : product ? (
          <span className="inline-flex h-6 items-center rounded-full bg-tile px-2.5 text-[12px] font-semibold text-ink-2">Chat request</span>
        ) : null}
        {requirements.length > 0 && (
          <span className={`num ml-auto text-[13px] font-semibold ${met === requirements.length ? "text-ok-ink" : "text-muted"}`}>
            {met} of {requirements.length} met
          </span>
        )}
      </div>
      {requirements.length === 0 ? (
        <p className="py-2 text-[15px] leading-snug text-muted shrink-0">Describe any product in the chat, or end a Jamie meeting. Mechanic turns it into checks here.</p>
      ) : (
        <ul className="scroll-soft -mx-2 min-h-0 flex-1 space-y-0.5 overflow-y-auto">
          {requirements.map((r) => (
            <RequirementRow key={r.id} r={r} open={open === r.id} onToggle={() => setOpen(open === r.id ? null : r.id)} />
          ))}
        </ul>
      )}

      <TrainedGains />

      <button
        type="button"
        onClick={() => setBomOpen(true)}
        disabled={!bom}
        data-target="bom stueckliste nav:stueckliste"
        className="group mt-4 flex w-full shrink-0 items-center gap-3 rounded-[14px] bg-page-2 px-4 py-3 text-left transition hover:bg-tile disabled:cursor-default disabled:opacity-60"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-[15px] font-semibold text-ink">Bill of materials</span>
          <span className="num block text-[13px] font-medium text-muted">{bom ? `${bom.items.length} parts · ${fmtEur(bom.total_eur)}` : "After the parts are picked"}</span>
        </span>
        <ChevronRight className="h-5 w-5 text-ink-2 transition group-hover:translate-x-0.5" />
      </button>
    </aside>
  );
}
