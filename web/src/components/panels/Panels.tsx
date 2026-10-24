// The one compact panel on the right: the Jamie requirements as checks, the four
// key numbers, and the button that opens the bill of materials.
import { useState } from "react";
import { ChevronRight, Quote as QuoteIcon } from "lucide-react";
import { useSession } from "../../events/store";
import type { MetricCard, Quote, RequirementEvent } from "../../events/types";
import { meets, type MetricKey } from "../../lib/derived";
import { fmtEur, fmtGram, fmtMin, fmtNum, fmtRatio } from "../../lib/format";
import { useShownBuild, useTargets } from "../../lib/hooks";
import { useUi } from "../../lib/ui";
import { CheckCircle } from "../ui/primitives";
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

/** A Jamie quote with who said it, when, and in which meeting. */
export function QuoteBubble({ quote, className = "" }: { quote: Pick<Quote, "text"> & Partial<Quote>; className?: string }) {
  const by = [quote.speaker, quote.time, quote.meeting_title].filter(Boolean).join(" · ");
  return (
    <div className={`animate-rise rounded-2xl bg-lavender/55 px-3.5 py-3 ${className}`}>
      <div className="flex gap-2">
        <QuoteIcon className="mt-0.5 h-4 w-4 shrink-0 text-jamie" />
        <p className="text-[15px] leading-snug text-ink">„{quote.text}“</p>
      </div>
      {by && <p className="mt-1.5 pl-6 text-[13px] font-semibold text-jamie">{by}</p>}
    </div>
  );
}

function RequirementRow({ r, open, onToggle }: { r: RequirementEvent; open: boolean; onToggle: () => void }) {
  const state = r.met === true ? "ok" : r.met === false ? "fail" : "open";
  return (
    <li data-target={`requirement:${r.id} ${r.id}`}>
      <button
        type="button"
        onClick={onToggle}
        className={`flex w-full items-center gap-3 rounded-2xl px-2 py-[7px] text-left transition ${open ? "bg-tile" : "hover:bg-page-2"}`}
      >
        <CheckCircle state={state} size={26} />
        <span className="min-w-0 flex-1">
          <span className={`block text-[16px] leading-snug font-semibold ${r.met === false ? "text-fail-ink" : "text-ink"}`}>{r.text}</span>
          {r.changed_from && <span className="block text-[13px] font-semibold text-muted line-through decoration-faint">{r.changed_from}</span>}
        </span>
      </button>
      {open && (
        <QuoteBubble
          className="mx-2 mt-1 mb-2"
          quote={{ text: r.source_quote, speaker: r.speaker, time: r.time, meeting_title: r.meeting_title }}
        />
      )}
    </li>
  );
}

const METRICS: { key: MetricKey; label: string; unit: string; target: string; format: (v: number) => string }[] = [
  { key: "weight_g", label: "Gewicht", unit: "g", target: "metric:weight weight weight_g gewicht", format: (v) => fmtNum(v, v < 100 ? 1 : 0) },
  { key: "thrust_to_weight", label: "Schub/Gewicht", unit: ": 1", target: "metric:thrust_to_weight thrust_to_weight schub tw", format: fmtRatio },
  { key: "flight_time_min", label: "Flugzeit", unit: "min", target: "metric:flight_time flight_time flight_time_min flugzeit", format: fmtMin },
  { key: "price_eur", label: "Preis", unit: "€", target: "metric:price price price_eur preis budget", format: (v) => fmtNum(v, 2) },
];

function limitText(key: MetricKey, value: number, direction: "max" | "min") {
  const v =
    key === "weight_g" ? fmtGram(value) : key === "price_eur" ? fmtEur(value) : key === "flight_time_min" ? `${fmtMin(value)} min` : `${fmtRatio(value)} : 1`;
  return `${direction === "max" ? "max." : "min."} ${v}`;
}

/** Key numbers a product sends itself (the gripper), already judged against its limits. */
function CardGrid({ cards, busy }: { cards: MetricCard[]; busy: boolean }) {
  return (
    <div className="grid grid-cols-2 gap-2.5">
      {cards.map((c) => (
        <div key={c.key} data-target={`metric:${c.key} ${c.key}`} className="rounded-[20px] bg-page-2 px-3.5 pt-2.5 pb-3">
          <div className="flex items-center gap-1.5 text-[14px] font-semibold text-ink-2">
            <span className={`h-2 w-2 rounded-full ${c.ok ? "bg-ok" : "bg-fail"}`} />
            {c.label}
          </div>
          <div className={`num mt-1 flex items-baseline gap-1 ${busy ? "text-agent-ink" : c.ok ? "text-ink" : "text-fail-ink"}`}>
            <span className="text-[30px] leading-none font-extrabold tracking-[-0.02em]">{fmtNum(c.value, c.digits)}</span>
            <span className="text-[15px] font-bold text-muted">{c.unit}</span>
          </div>
          <div className="num mt-1 truncate text-[13px] font-semibold text-muted">{c.limit || "\u00a0"}</div>
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
  const met = requirements.filter((r) => r.met === true).length;

  return (
    <aside className="card scroll-soft flex min-h-0 flex-col overflow-y-auto px-5 pt-4 pb-5">
      <div className="mb-1.5 flex items-center gap-2" data-target="requirements anforderungen">
        <h2 className="text-[18px] font-bold text-ink">Anforderungen</h2>
        {product === "drone" ? <JamieMark /> : <span className="inline-flex h-6 items-center rounded-full bg-tile px-2.5 text-[12px] font-bold text-ink-2">Chat brief</span>}
        {requirements.length > 0 && (
          <span className="num ml-auto text-[14px] font-semibold text-muted">
            {met} / {requirements.length}
          </span>
        )}
      </div>
      {requirements.length === 0 ? (
        <p className="py-2 text-[15px] leading-snug text-muted">Kommen aus eurem Meeting, sobald Bolzen es bei Jamie gelesen hat.</p>
      ) : (
        <ul className="-mx-2">
          {requirements.map((r) => (
            <RequirementRow key={r.id} r={r} open={open === r.id} onToggle={() => setOpen(open === r.id ? null : r.id)} />
          ))}
        </ul>
      )}

      <div className="mt-4 mb-2 flex items-baseline gap-2" data-target="metrics kennzahlen">
        <h2 className="text-[18px] font-bold text-ink">Kennzahlen</h2>
        {version && (
          <span className={`text-[14px] font-semibold ${pinned ? "text-agent-ink" : "text-muted"}`}>
            v{version.n} · {version.meeting_title}
          </span>
        )}
      </div>
      {product !== "drone" && cards ? (
        <CardGrid cards={cards} busy={simRunning} />
      ) : product !== "drone" ? (
        <p className="py-2 text-[15px] leading-snug text-muted">Appear once Bolzen has chosen the parts.</p>
      ) : (
      <div className="grid grid-cols-2 gap-2.5">
        {METRICS.map((m) => {
          const value = metrics?.[m.key];
          const t = targets[m.key];
          const ok = value !== undefined && meets(t, value);
          const tone = value === undefined ? "text-faint" : simRunning && !pinned ? "text-agent-ink" : ok ? "text-ink" : "text-fail-ink";
          const prev = previous?.[m.key];
          const changed = prev !== undefined && value !== undefined && m.format(prev) !== m.format(value);
          return (
            <div key={m.key} data-target={m.target} className="rounded-[20px] bg-page-2 px-3.5 pt-2.5 pb-3">
              <div className="flex items-center gap-1.5 text-[14px] font-semibold text-ink-2">
                <span className={`h-2 w-2 rounded-full ${value === undefined ? "bg-track" : ok ? "bg-ok" : "bg-fail"}`} />
                {m.label}
              </div>
              <div className={`num mt-1 flex items-baseline gap-1 ${tone}`}>
                <span className="text-[30px] leading-none font-extrabold tracking-[-0.02em]">{value === undefined ? "–" : m.format(value)}</span>
                <span className="text-[15px] font-bold text-muted">{m.unit}</span>
              </div>
              <div className="num mt-1 text-[13px] font-semibold text-muted">
                {changed ? (
                  <>
                    vorher <span className="text-ink-2">{m.format(prev!)}</span>
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

      <TrainedGains />

      <button
        type="button"
        onClick={() => setBomOpen(true)}
        disabled={!bom}
        data-target="bom stueckliste nav:stueckliste"
        className="group mt-4 flex h-14 w-full shrink-0 items-center gap-3 rounded-full bg-ink pr-3 pl-5 text-left text-white transition hover:bg-[#333] disabled:bg-tile disabled:text-faint"
      >
        <span className="text-[16px] font-bold">Stückliste</span>
        {bom && (
          <span className="num text-[15px] font-semibold text-white/70">
            {bom.items.length} Teile · {fmtEur(bom.total_eur)}
          </span>
        )}
        <ChevronRight className="ml-auto h-5 w-5 transition group-hover:translate-x-0.5" />
      </button>
    </aside>
  );
}
