// Panel block: the controller gains the browser training found, once a run finished.
import { productFor } from "../../sim/products";
import { fmtGain, fmtNum } from "./format";
import { useBrowserTrainingEvent } from "./useBrowserTraining";

export function TrainedGains() {
  const t = useBrowserTrainingEvent();
  if (!t || t.status !== "done" || !t.best_params) return null;
  let product: ReturnType<typeof productFor> | null = null;
  try {
    product = productFor(t.product ?? "drone");
  } catch {
    product = null;
  }
  const labels: Record<string, string> = Object.fromEntries((product?.params ?? []).map((p) => [p.name, p.label]));
  const verdict = product?.describe(t.best_metrics ?? {}) ?? { ok: false, headline: "Trained", lines: [] };
  return (
    <div className="mt-4" data-target="training:panel trained_gains">
      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-[18px] font-bold text-ink">{t.product === "gripper" ? "Trained grasp" : "Trained controller"}</h2>
        <span className="num text-[14px] font-semibold text-muted">{fmtNum(t.step)} sims · score {fmtNum(t.reward, 1)}</span>
      </div>
      <div className="rounded-[20px] bg-page-2 px-3.5 pt-2.5 pb-3">
        <div className="flex items-center gap-1.5 text-[14px] font-semibold text-ink-2">
          <span className={`h-2 w-2 rounded-full ${verdict.ok ? "bg-ok" : "bg-agent"}`} />
          {verdict.headline}
        </div>
        {verdict.lines.length > 0 && <div className="num mt-0.5 text-[13px] font-semibold text-muted">{verdict.lines.join(" · ")}</div>}
        <div className="num mt-2 grid grid-cols-4 gap-x-3 gap-y-1">
          {Object.entries(t.best_params).map(([k, v]) => (
            <div key={k} className="min-w-0">
              <div className="truncate text-[11px] font-semibold text-muted">{labels[k] ?? k}</div>
              <div className="text-[15px] font-bold text-ink">{fmtGain(v)}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
