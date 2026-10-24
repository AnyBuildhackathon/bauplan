// The build guide: the steps the agent wrote for the bill of materials, one at a time,
// next to the drone pulled apart. The step's parts glow, earlier parts stay solid and
// later ones fade. Opened from the bill of materials; Escape closes.
import { useEffect, useMemo } from "react";
import { create } from "zustand";
import { ChevronLeft, ChevronRight, Clock, ListChecks, Package, Wrench, X } from "lucide-react";
import { useSession } from "../events/store";
import { ExplodedScene, type PartState } from "../components/guide/ExplodedDrone";
import { useAssembly } from "../lib/hooks";

interface GuideUi {
  open: boolean;
  /** Index into the guide's steps. */
  index: number;
  show: (open: boolean) => void;
  go: (index: number) => void;
}

export const useGuide = create<GuideUi>((set) => ({
  open: false,
  index: 0,
  show: (open) => set({ open, index: 0 }),
  go: (index) => set({ index }),
}));

/** The button the bill of materials shows once a guide exists. */
export function BuildGuideButton() {
  const guide = useSession((s) => s.buildGuide);
  const show = useGuide((s) => s.show);
  if (!guide) return null;
  return (
    <button
      type="button"
      onClick={() => show(true)}
      data-control="panel:guide"
      className="inline-flex h-11 items-center gap-2 rounded-full bg-ink px-5 text-[15px] font-bold text-white hover:bg-[#333]"
    >
      <ListChecks className="h-4.5 w-4.5" /> Build guide
    </button>
  );
}

const fmtMinutes = (m: number) => `${Number.isInteger(m) ? m : m.toFixed(1)} min`;

export function BuildGuide() {
  const guide = useSession((s) => s.buildGuide);
  const { open, index, show, go } = useGuide();
  const build = useAssembly("latest");
  const steps = guide?.steps ?? [];
  const at = Math.min(index, Math.max(0, steps.length - 1));
  const step = steps[at];

  useEffect(() => {
    if (!guide) show(false);
  }, [guide, show]);

  const states = useMemo(() => {
    const out: Record<string, PartState> = {};
    // A part belongs to the first step that names it; later mentions highlight it again.
    steps.forEach((s, i) => {
      for (const p of s.parts) if (!(p in out)) out[p] = i < at ? "done" : "later";
    });
    for (const p of step?.parts ?? []) out[p] = "current";
    return out;
  }, [steps, step, at]);

  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      show(false);
      // The bill of materials underneath also closes on Escape; this one goes first.
      e.stopImmediatePropagation();
      e.preventDefault();
    };
    window.addEventListener("keydown", key, { capture: true });
    return () => window.removeEventListener("keydown", key, { capture: true });
  }, [open, show]);

  if (!open || !guide || !step) return null;
  const elapsed = steps.slice(0, at).reduce((sum, s) => sum + s.minutes, 0);
  const last = at === steps.length - 1;

  return (
    <div className="fixed inset-0 z-[75] flex items-center justify-center bg-ink/30 p-6 backdrop-blur-[2px]" onPointerDown={() => show(false)}>
      <div
        className="flex h-[min(820px,100%)] w-[min(1280px,100%)] animate-rise flex-col overflow-hidden rounded-[28px] bg-page shadow-[var(--shadow-float)]"
        onPointerDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Build guide"
      >
        <div className="flex shrink-0 items-center gap-4 px-6 pt-5 pb-4">
          <div>
            <h1 className="text-[30px] leading-none font-extrabold tracking-[-0.03em]">Build guide</h1>
            <p className="num mt-1.5 text-[16px] font-semibold text-muted">
              v{guide.version} · {steps.length} steps · about {fmtMinutes(guide.total_minutes)}
            </p>
          </div>
          <button type="button" onClick={() => show(false)} data-control="panel:guide:close" className="ml-auto rounded-full p-2.5 text-muted hover:bg-card" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] gap-4 px-6 pb-4">
          <div className="card relative min-h-0 overflow-hidden" data-guide-parts={step.parts.join(" ")}>
            <ExplodedScene build={build} states={states} />
          </div>

          <div className="card scroll-soft flex min-h-0 flex-col overflow-y-auto px-6 pt-5 pb-5">
            <div className="num text-[14px] font-bold tracking-wide text-agent-ink uppercase">
              Step {step.n} of {steps.length}
            </div>
            <h2 className="mt-1 text-[26px] leading-tight font-extrabold tracking-[-0.02em]">{step.title}</h2>
            <p className="mt-3 text-[17px] leading-relaxed text-ink-2">{step.instructions}</p>

            {step.items.length > 0 && (
              <section className="mt-5">
                <h3 className="flex items-center gap-2 text-[14px] font-bold text-muted">
                  <Package className="h-4 w-4" /> Parts
                </h3>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {step.items.map((name) => (
                    <li key={name} className="rounded-full bg-agent-soft px-3 py-1 text-[14px] font-semibold text-agent-ink">
                      {name}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {step.tools.length > 0 && (
              <section className="mt-4">
                <h3 className="flex items-center gap-2 text-[14px] font-bold text-muted">
                  <Wrench className="h-4 w-4" /> Tools
                </h3>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {step.tools.map((tool) => (
                    <li key={tool} className="rounded-full bg-tile px-3 py-1 text-[14px] font-semibold text-ink-2">
                      {tool}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <p className="num mt-4 flex items-center gap-2 text-[14px] font-semibold text-muted">
              <Clock className="h-4 w-4" /> {fmtMinutes(step.minutes)} · {fmtMinutes(elapsed)} done before this step
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-3 px-6 pb-5">
          <button
            type="button"
            onClick={() => go(at - 1)}
            disabled={at === 0}
            className="inline-flex h-12 items-center gap-1.5 rounded-full bg-card pr-5 pl-3.5 text-[16px] font-bold text-ink shadow-[var(--shadow-pill)] hover:bg-page-2 disabled:text-faint disabled:shadow-none"
          >
            <ChevronLeft className="h-5 w-5" /> Back
          </button>
          <ol className="flex flex-1 items-center justify-center gap-2" aria-label="Steps">
            {steps.map((s, i) => (
              <li
                key={s.n}
                aria-label={`Step ${s.n}: ${s.title}`}
                aria-current={i === at ? "step" : undefined}
                className={`num flex h-9 min-w-9 items-center justify-center rounded-full px-2 text-[14px] font-bold transition ${
                  i === at ? "bg-agent text-white" : i < at ? "bg-ok-soft text-ok-ink" : "bg-tile text-muted"
                }`}
              >
                {s.n}
              </li>
            ))}
          </ol>
          <button
            type="button"
            onClick={() => (last ? show(false) : go(at + 1))}
            className="inline-flex h-12 items-center gap-1.5 rounded-full bg-ink pr-3.5 pl-5 text-[16px] font-bold text-white hover:bg-[#333]"
          >
            {last ? "Done" : "Next"} <ChevronRight className="h-5 w-5" />
          </button>
        </div>
      </div>
    </div>
  );
}
