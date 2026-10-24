// Panel block: the controller gains the browser training found, once a run finished.
import { productFor } from "../../sim/products";
import { fmtGain, fmtNum } from "./format";
import { useBrowserTrainingEvent } from "./useBrowserTraining";

export function TrainedGains() {
  const t = useBrowserTrainingEvent();
  if (!t || t.status !== "done" || !t.best_params) return null;
  let labels: Record<string, string> = {};
  try {
    labels = Object.fromEntries(productFor(t.product ?? "drone").params.map((p) => [p.name, p.label]));
  } catch {
    labels = {};
  }
  const m = t.best_metrics ?? {};
  const held = m.held === true;
  return (
    <div className="mt-4" data-target="training:panel trained_gains">
      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-[18px] font-bold text-ink">Trained controller</h2>
        <span className="num text-[14px] font-semibold text-muted">{fmtNum(t.step)} sims · score {fmtNum(t.reward, 1)}</span>
      </div>
      <div className="rounded-[20px] bg-page-2 px-3.5 pt-2.5 pb-3">
        <div className="flex items-center gap-1.5 text-[14px] font-semibold text-ink-2">
          <span className={`h-2 w-2 rounded-full ${held ? "bg-ok" : "bg-agent"}`} />
          {held ? "Holds position for 10 s" : "Best found, not yet within 10 cm"}
        </div>
        {typeof m.rms_error_cm === "number" && (
          <div className="num mt-0.5 text-[13px] font-semibold text-muted">
            {fmtNum(m.rms_error_cm, 1)} cm RMS · max tilt {fmtNum(Number(m.max_tilt_deg ?? 0), 0)}°
          </div>
        )}
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
