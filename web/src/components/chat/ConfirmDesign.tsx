// The end of the flow: once a build has finished and nothing waits for an answer, one
// calm card under the chat asks whether the design is right. Confirming it opens the
// pricing (the bill of materials on its order by shop); a new version asks again.
import { useEffect, useState } from "react";
import { ArrowRight, Check } from "lucide-react";
import { useSession, type SessionState } from "../../events/store";
import { fmtEur } from "../../lib/format";
import { useUi } from "../../lib/ui";

/** Quiet time before the card shows, so a gap between two steps never reads as "done". */
const SETTLE_MS = 1200;
/** The confirmed state shows for a moment before the pricing slides in. */
const HANDOFF_MS = 450;

/** The finished build to confirm: its results card id, or null while anything still runs or asks. */
function finishedBuild(s: SessionState): string | null {
  const results = s.chat.findLast((c) => c.kind === "bom");
  if (!results || !s.bom) return null;
  if (Object.values(s.steps).some((step) => step.status === "running")) return null;
  if (Object.values(s.agents).some((a) => a.status === "running" || a.status === "queued")) return null;
  if (Object.values(s.questions).some((q) => q.status === "open")) return null;
  return results.id;
}

const focusChat = () => document.querySelector<HTMLTextAreaElement>('[data-target~="chat_input"]')?.focus();

export function ConfirmDesign({ onShow }: { onShow?: () => void }) {
  const build = useSession(finishedBuild);
  const total = useSession((s) => s.bom?.total_eur ?? 0);
  const version = useSession((s) => s.versions.at(-1)?.n ?? null);
  const confirmed = useUi((s) => s.confirmedBuild);
  const confirmDesign = useUi((s) => s.confirmDesign);
  const openPricing = useUi((s) => s.openPricing);
  const [settled, setSettled] = useState<string | null>(null);

  useEffect(() => {
    if (!build) return setSettled(null);
    const id = setTimeout(() => setSettled(build), SETTLE_MS);
    return () => clearTimeout(id);
  }, [build]);

  const shown = !!build && settled === build;
  useEffect(() => {
    if (shown) onShow?.();
  }, [shown, onShow]);
  useEffect(() => {
    if (!build || confirmed !== build) return;
    const id = setTimeout(openPricing, HANDOFF_MS);
    return () => clearTimeout(id);
    // Only the moment of confirming hands over; reopening is the "Show pricing" button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [confirmed]);

  if (!shown) return null;
  const done = confirmed === build;
  const name = version ? `v${version}` : "this design";

  return (
    <div
      key={build}
      data-target="confirm_design"
      className="mt-2 rounded-[14px] bg-page-2 p-3 motion-safe:animate-rise"
      role="group"
      aria-label="Confirm the design"
    >
      {done ? (
        <div className="flex items-center gap-2.5">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ok-soft text-ok-ink">
            <Check className="h-3.5 w-3.5" strokeWidth={3} />
          </span>
          <span className="min-w-0 flex-1 truncate text-[14px] font-semibold text-ink">
            Design confirmed <span className="font-label text-[11px] font-normal text-muted">{name} · {fmtEur(total)}</span>
          </span>
          <button
            type="button"
            onClick={openPricing}
            data-control="confirm:pricing"
            className="group flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[13px] font-semibold text-ink-2 transition hover:bg-white hover:text-ink"
          >
            Show pricing
            <ArrowRight className="h-3.5 w-3.5 text-muted transition group-hover:translate-x-0.5" />
          </button>
        </div>
      ) : (
        <>
          <p className="text-[14px] font-semibold text-ink">Happy with this design?</p>
          <p className="mt-0.5 text-[13px] leading-snug text-muted">
            Confirm {name} and Mechanic shows what the parts cost and where to buy them.
          </p>
          <div className="mt-2.5 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => confirmDesign(build)}
              data-control="confirm:design"
              className="flex h-8 items-center gap-1.5 rounded-full bg-ink px-4 text-[13px] font-semibold text-white transition hover:brightness-125 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
            >
              <Check className="h-3.5 w-3.5" strokeWidth={2.6} />
              Confirm design
            </button>
            <button
              type="button"
              onClick={focusChat}
              data-control="confirm:change"
              className="h-8 rounded-full bg-white px-4 text-[13px] font-semibold text-ink-2 shadow-[var(--shadow-pill)] transition hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
            >
              Change something
            </button>
          </div>
        </>
      )}
    </div>
  );
}
