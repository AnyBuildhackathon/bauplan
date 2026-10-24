// AnyBuild Bench as a drawer, opened from Settings (or ?benchmark): how often the agent
// turns a product prompt into a valid, checked product. One row per prompt with its
// checks, retries, time, tokens and cost; "Open on bench" builds that prompt again on a
// fresh bench. GET /api/bench serves the results agent/bench/run.py wrote. A mock run is
// labelled as mock everywhere: it replays the recorded mock story, not the live agent.
import { useEffect, useState } from "react";
import { create } from "zustand";
import { Check, ChevronDown, Play, X } from "lucide-react";
import { useSource } from "../events/source";
import { apiFetch } from "../lib/api";
import { fmtEur, fmtNum } from "../lib/format";
import { useUi } from "../lib/ui";

interface BenchCheck {
  id: string;
  label: string;
  pass: boolean;
  detail: string;
}

interface BenchResult {
  id: string;
  title: string;
  prompt: string;
  status: "done" | "timeout" | "error" | "skipped";
  error: string | null;
  pass: boolean;
  checks: BenchCheck[];
  checks_passed: number;
  checks_total: number;
  time_s: number;
  retries: number;
  tool_errors: number;
  fixes: number;
  cad_fallbacks?: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  product: string | null;
  mass_g: number | null;
  parts_eur: number | null;
}

interface BenchRun {
  mode: "live" | "mock";
  note: string | null;
  started_at: string;
  orchestrator_model: string | null;
  concurrency: number;
  prompts_total?: number;
  summary: {
    ran: number;
    prompts: number;
    passed: number;
    pass_rate: number;
    checks_passed: number;
    checks_total: number;
    cost_usd: number;
    cost_per_product_usd: number;
    cost_per_valid_product_usd: number | null;
    time_s: number;
    cad_fallbacks?: number;
  };
  results: BenchResult[];
}

export const useBenchResults = create<{ open: boolean; setOpen: (open: boolean) => void }>((set) => ({
  open: new URLSearchParams(window.location.search).has("benchmark"),
  setOpen: (open) => set({ open }),
}));

const usd = (v: number) => `$${v < 1 ? v.toFixed(3) : v.toFixed(2)}`;
const pct = (v: number) => `${Math.round(v * 100)} %`;
const tokens = (r: BenchResult) => {
  const n = r.input_tokens + r.output_tokens;
  return n >= 1000 ? `${fmtNum(n / 1000, 0)}k` : fmtNum(n);
};

function ModeBadge({ run }: { run: BenchRun }) {
  return run.mode === "mock" ? (
    <span className="rounded-full bg-fail-soft px-2.5 py-0.5 text-[12px] font-extrabold tracking-wide text-fail-ink">MOCK</span>
  ) : (
    <span className="rounded-full bg-ok-soft px-2.5 py-0.5 text-[12px] font-extrabold tracking-wide text-ok-ink">LIVE</span>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[18px] bg-card px-3.5 py-2.5 shadow-[var(--shadow-pill)]">
      <p className="num text-[22px] leading-none font-extrabold text-ink">{value}</p>
      <p className="mt-1 text-[12px] font-semibold text-muted">{label}</p>
    </div>
  );
}

function Row({ r, run }: { r: BenchResult; run: BenchRun }) {
  const [open, setOpen] = useState(false);
  const setBenchOpen = useBenchResults((s) => s.setOpen);
  const setView = useUi((s) => s.setView);
  const resetUi = useUi((s) => s.resetUi);
  const resetSession = useSource((s) => s.resetSession);
  const sendPrompt = useSource((s) => s.sendPrompt);
  const tone = r.status === "skipped" ? "text-muted" : r.pass ? "text-ok-ink" : "text-fail-ink";
  const verdict = r.status === "done" ? (r.pass ? "Valid" : "Failed") : r.status === "timeout" ? "Timeout" : r.status === "error" ? "Error" : "Skipped";
  const openOnBench = async () => {
    setBenchOpen(false);
    resetUi();
    setView("werkbank");
    await resetSession();
    await sendPrompt(r.prompt);
  };
  return (
    <li className="rounded-[20px] bg-page-2 px-4 py-3" data-target={`bench:${r.id}`}>
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-start gap-3 text-left" aria-expanded={open}>
        <span className={`num mt-0.5 w-16 shrink-0 text-[14px] font-extrabold ${tone}`}>{verdict}</span>
        <span className="min-w-0 flex-1">
          <span className="block text-[16px] leading-snug font-bold text-ink">{r.title}</span>
          <span className="num mt-0.5 block text-[13px] text-muted">
            {r.checks_passed}/{r.checks_total} checks · {r.retries} retries · {fmtNum(r.time_s, 1)} s · {tokens(r)} tokens · {usd(r.cost_usd)}
          </span>
        </span>
        <ChevronDown className={`mt-1 h-4 w-4 shrink-0 text-muted transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-2 space-y-2 pl-19">
          <p className="text-[14px] leading-snug text-ink-2">“{r.prompt}”</p>
          {r.error && <p className="text-[13px] font-semibold text-fail-ink">{r.error}</p>}
          <ul className="space-y-1">
            {r.checks.map((c) => (
              <li key={c.id} className="flex items-start gap-2 text-[13px] leading-snug">
                {c.pass ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ok-ink" /> : <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fail-ink" />}
                <span className="min-w-0 flex-1 text-ink">{c.label}</span>
                <span className="num shrink-0 text-muted">{c.detail}</span>
              </li>
            ))}
          </ul>
          <p className="num text-[12px] text-faint">
            {r.product ?? "No product"}
            {typeof r.mass_g === "number" ? ` · ${fmtNum(r.mass_g, 0)} g` : ""}
            {typeof r.parts_eur === "number" ? ` · ${fmtEur(r.parts_eur)} in parts` : ""} · {r.tool_errors} tool errors, {r.fixes} fixes
            {r.cad_fallbacks ? ` · ${r.cad_fallbacks} part(s) as CadQuery blocks (no FreeCAD)` : ""}
          </p>
          <button
            type="button"
            onClick={() => void openOnBench()}
            title={run.mode === "mock" ? "Builds this prompt again on a fresh bench (mock story without a key)" : "Builds this prompt again on a fresh bench"}
            className="inline-flex h-8 items-center gap-1.5 rounded-full bg-card px-3 text-[13px] font-bold text-ink-2 shadow-[var(--shadow-pill)] transition hover:bg-page"
          >
            <Play className="h-3.5 w-3.5" /> Open on bench
          </button>
        </div>
      )}
    </li>
  );
}

export function BenchResults() {
  const open = useBenchResults((s) => s.open);
  const setOpen = useBenchResults((s) => s.setOpen);
  const [runs, setRuns] = useState<BenchRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState(0);

  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", esc);
    setError(null);
    apiFetch("/api/bench")
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((body: { runs: BenchRun[] }) => setRuns(body.runs))
      .catch(() => setError("The bench results need the backend."));
    return () => window.removeEventListener("keydown", esc);
  }, [open, setOpen]);

  if (!open) return null;
  const run = runs?.[Math.min(pick, runs.length - 1)];
  return (
    <div className="fixed inset-0 z-[70] flex justify-end bg-ink/25 backdrop-blur-[2px]" onPointerDown={() => setOpen(false)}>
      <div
        className="flex h-full w-[min(640px,100vw)] animate-rise flex-col bg-page shadow-[var(--shadow-float)]"
        onPointerDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="AnyBuild Bench"
      >
        <div className="flex shrink-0 items-start gap-4 px-6 pt-5 pb-3">
          <div className="min-w-0">
            <h1 className="flex items-center gap-2.5 text-[30px] leading-none font-extrabold tracking-[-0.03em]">
              AnyBuild Bench {run && <ModeBadge run={run} />}
            </h1>
            <p className="mt-1.5 text-[15px] font-semibold text-muted">How often the agent turns a product prompt into a valid, checked product.</p>
          </div>
          <button type="button" onClick={() => setOpen(false)} className="ml-auto rounded-full p-2.5 text-muted hover:bg-card" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="scroll-soft min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-6">
          {runs && runs.length > 1 && (
            <div className="flex gap-2">
              {runs.map((r, i) => (
                <button
                  key={r.mode}
                  type="button"
                  onClick={() => setPick(i)}
                  className={`h-8 rounded-full px-3.5 text-[13px] font-bold transition ${i === pick ? "bg-ink text-white" : "bg-card text-ink-2 shadow-[var(--shadow-pill)]"}`}
                >
                  {r.mode === "live" ? "Live run" : "Mock run"}
                </button>
              ))}
            </div>
          )}
          {error && <p className="rounded-[20px] bg-page-2 px-4 py-6 text-center text-[15px] text-muted">{error}</p>}
          {runs && runs.length === 0 && (
            <p className="rounded-[20px] bg-page-2 px-4 py-6 text-center text-[15px] text-muted">
              No bench run yet. Run <span className="num font-bold text-ink">cd agent && uv run python -m bench.run</span>.
            </p>
          )}
          {run && (
            <>
              {run.mode === "mock" && (
                <p className="rounded-[18px] bg-fail-soft px-4 py-2.5 text-[14px] leading-snug font-semibold text-fail-ink">
                  Mock results: the recorded mock story without Claude, {run.summary.ran} of the {run.prompts_total ?? run.summary.prompts} prompts. Not a measure of the live agent.
                  {run.summary.cad_fallbacks ? " FreeCAD was missing, so printed parts were simplified blocks and their masses run high." : ""}
                </p>
              )}
              <div className="grid grid-cols-4 gap-2">
                <Stat label={`valid products (${run.summary.passed}/${run.summary.ran})`} value={pct(run.summary.pass_rate)} />
                <Stat label={`checks (${run.summary.checks_passed}/${run.summary.checks_total})`} value={pct(run.summary.checks_total ? run.summary.checks_passed / run.summary.checks_total : 0)} />
                <Stat label="cost per product" value={usd(run.summary.cost_per_product_usd)} />
                <Stat label="total time" value={`${fmtNum(run.summary.time_s / 60, 1)} min`} />
              </div>
              <p className="num text-[12px] text-faint">
                {new Date(run.started_at).toLocaleString("en-GB")} · {run.orchestrator_model ?? "no model (mock)"} · {run.concurrency} at a time · total {usd(run.summary.cost_usd)}
              </p>
              <ul className="space-y-2">
                {run.results.map((r) => (
                  <Row key={r.id} r={r} run={run} />
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
