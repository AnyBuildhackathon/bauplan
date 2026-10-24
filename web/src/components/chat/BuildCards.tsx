// The build's checks and numbers live in the chat instead of a side panel: one
// requirements card that updates as the checks run, and one results card per bill of
// materials with the three key numbers and the button to the full list.
import { useState } from "react";
import { ArrowRight, Check, X } from "lucide-react";
import { useSession, type ChatItem } from "../../events/store";
import type { RequirementEvent } from "../../events/types";
import { fmtEur, fmtNum } from "../../lib/format";
import { useUi } from "../../lib/ui";
import { WhyButton } from "../learn/Explain";

function CheckDot({ state }: { state: "ok" | "fail" | "open" }) {
  if (state === "open")
    return (
      <span
        className="mt-[3px] h-4 w-4 shrink-0 rounded-full shadow-[inset_0_0_0_1.5px_var(--color-track)]"
        aria-label="pending"
      />
    );
  return (
    <span
      className={`mt-[3px] flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${state === "ok" ? "bg-ok-soft text-ok-ink" : "bg-fail-soft text-fail-ink"}`}
      aria-label={state === "ok" ? "met" : "failed"}
    >
      {state === "ok" ? (
        <Check className="h-2.5 w-2.5" strokeWidth={3.5} />
      ) : (
        <X className="h-2.5 w-2.5" strokeWidth={3.5} />
      )}
    </span>
  );
}

/** Who asked for it: the Jamie speaker and time, or "you" for the chat request. */
function source(r: RequirementEvent): { label: string; jamie: boolean } {
  const you = !r.speaker || r.speaker === "You";
  return you
    ? { label: "you", jamie: false }
    : { label: [r.speaker, r.time].filter(Boolean).join(" "), jamie: true };
}

function RequirementLine({ r }: { r: RequirementEvent }) {
  const [open, setOpen] = useState(false);
  const state = r.met === true ? "ok" : r.met === false ? "fail" : "open";
  const from = source(r);
  return (
    <li data-target={`requirement:${r.id} ${r.id}`} data-state={state}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full gap-2 rounded-[10px] px-1.5 py-1 text-left transition hover:bg-white/70"
      >
        <CheckDot state={state} />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span
              className={`min-w-0 flex-1 text-[14px] leading-snug ${state === "fail" ? "text-fail-ink" : "text-ink"}`}
            >
              {r.text}
            </span>
            <span
              className={`shrink-0 rounded-full px-1.5 font-label text-[10.5px] leading-[18px] ${from.jamie ? "bg-lavender text-jamie" : "bg-white text-muted"}`}
              title={
                from.jamie
                  ? `${r.speaker} in ${r.meeting_title ?? "a Jamie meeting"}${r.time ? ` at ${r.time}` : ""}`
                  : "From your request"
              }
            >
              {from.label}
            </span>
          </span>
          {r.detail && (
            <span
              className={`block font-label text-[11px] ${state === "fail" ? "text-fail-ink" : "text-muted"}`}
            >
              {r.detail}
            </span>
          )}
          {r.changed_from && (
            <span className="block text-[12px] text-faint line-through">
              {r.changed_from}
            </span>
          )}
          {open && r.source_quote && (
            <span className="mt-1 block animate-rise font-read text-[13px] leading-normal text-ink-2">
              “{r.source_quote}”
            </span>
          )}
        </span>
      </button>
      {r.met !== null && <WhyButton kind="requirement" id={r.id} className="pb-1 pl-[30px]" />}
    </li>
  );
}

export function RequirementsCard() {
  const requirements = useSession((s) => s.requirements);
  if (requirements.length === 0) return null;
  const met = requirements.filter((r) => r.met === true).length;
  const failed = requirements.filter((r) => r.met === false).length;
  const jamie = requirements.some((r) => source(r).jamie);
  return (
    <div
      className="rounded-[14px] bg-page-2 px-2 pt-2.5 pb-1.5"
      data-target="requirements anforderungen"
    >
      <div className="mb-1 flex items-center gap-2 px-1.5">
        <span className="text-[14px] font-semibold text-ink">Requirements</span>
        <span className="font-label text-[11px] text-muted">
          {jamie ? "from Jamie" : "from your request"}
        </span>
        <span
          className={`ml-auto font-label text-[11px] ${failed ? "text-fail-ink" : met === requirements.length ? "text-ok-ink" : "text-muted"}`}
        >
          {met} of {requirements.length} met
        </span>
      </div>
      <ul>
        {requirements.map((r) => (
          <RequirementLine key={r.id} r={r} />
        ))}
      </ul>
    </div>
  );
}

export function ResultsCard({
  item,
}: {
  item: Extract<ChatItem, { kind: "bom" }>;
}) {
  const setBomOpen = useUi((s) => s.setBomOpen);
  return (
    <div className="rounded-[14px] bg-page-2 p-3">
      <div className="mb-2 text-[14px] font-semibold text-ink">Results</div>
      {item.numbers.length > 0 && (
        <div
          className="mb-2.5 grid grid-cols-3 gap-2"
          data-target="metrics kennzahlen"
        >
          {item.numbers.map((n) => (
            <div key={n.key} className="min-w-0" data-target={n.target}>
              <div className="num truncate text-[18px] leading-tight font-semibold tracking-[-0.01em] text-ink">
                {fmtNum(n.value, n.digits)}
                <span className="ml-0.5 text-[13px] font-medium text-muted">
                  {n.unit}
                </span>
              </div>
              <div className="truncate font-label text-[11px] text-muted">
                {n.label}
              </div>
            </div>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={() => setBomOpen(true)}
        data-target="bom_card"
        className="group flex w-full items-center gap-2 rounded-[10px] bg-white px-3 py-2 text-left shadow-[var(--shadow-pill)] transition hover:bg-page"
      >
        <span className="text-[13px] font-semibold text-ink">
          Bill of materials
        </span>
        <span className="font-label text-[11px] text-muted">
          {item.count} parts · {fmtEur(item.total)}
        </span>
        <ArrowRight className="ml-auto h-4 w-4 text-muted transition group-hover:translate-x-0.5" />
      </button>
    </div>
  );
}
