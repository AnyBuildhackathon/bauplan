// The legend of the surface check colour layer, in the studio's bottom-left corner while a check is
// shown: what the colours mean, how much needs a fix at Mechanic's limit (and what is red but needs
// none: sharp edges, contact lines, specks), a slider that moves the limit (it recolours the model at
// once and counts again; Mechanic keeps his own), and the value of the last spot clicked, which goes
// to Mechanic's message box as a spot note (U6).
import { MessageSquarePlus, X } from "lucide-react";
import { areas, buildOf, formatArea, formatLimit, formatValue, isCurrent, limitOf, limitRange, SHADES, useAnalysisLayer } from "../../events/analysis";
import { attach } from "../../events/notes";
import { useSession } from "../../events/store";
import type { AnalysisCheck, AnalysisCheckInfo, AnalysisEvent } from "../../events/types";
import { fmtNum } from "../../lib/format";
import { useUi } from "../../lib/ui";
import { useApproximateModels } from "../canvas/ExplodeControls";

/** Where the bar ends and how its colours run to there. */
function scale(check: AnalysisCheck, info: AnalysisCheckInfo, limit: number): { end: number; gradient: string } {
  if (check === "overhang") {
    const at = (limit / 90) * 100;
    return { end: 90, gradient: `linear-gradient(90deg, ${SHADES.plain} 0%, ${SHADES.near} ${at}%, ${SHADES.critical} ${at}%, ${SHADES.critical} 100%)` };
  }
  const end = check === "clearance" ? (info.range ?? 5) : Math.max(3 * limit, 1);
  const at = Math.min(100, (limit / end) * 100);
  const fade = Math.min(100, ((2 * limit) / end) * 100);
  return { end, gradient: `linear-gradient(90deg, ${SHADES.critical} 0%, ${SHADES.critical} ${at}%, ${SHADES.near} ${at}%, ${SHADES.plain} ${fade}%, ${SHADES.plain} 100%)` };
}

/** The print pose the overhang is judged in, said once. */
function poseLine(analysis: AnalysisEvent): string {
  const poses = [...new Set(analysis.parts.map((p) => (p.pose === "as_modeled" ? "as modelled" : p.pose)))];
  return poses.length === 1 ? `Printed ${poses[0]}` : "Each part in its print pose";
}

const SOFT: Partial<Record<AnalysisCheck, string>> = {
  thickness: "sharp edges and specks",
  clearance: "contact lines and specks",
};

function Swatch({ colour, children }: { colour: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: colour }} />
      {children}
    </span>
  );
}

export function AnalysisLegend() {
  const analysis = useSession((s) => s.analysis);
  const cadUrl = useSession((s) => s.cad?.glb_url);
  const check = useAnalysisLayer((s) => s.check);
  const limits = useAnalysisLayer((s) => s.limits);
  const counted = useAnalysisLayer((s) => s.area);
  const picked = useAnalysisLayer((s) => s.picked);
  const { show, setLimit, pick } = useAnalysisLayer.getState();
  const tab = useUi((s) => s.tab);
  // The Model tab's note on approximate part models has this corner; the legend sits above it.
  const lifted = useApproximateModels().length > 0 && tab === "modell";
  const info = check ? analysis?.checks[check] : undefined;
  if (!check || !info || !isCurrent(analysis, cadUrl)) return null;
  const limit = limitOf(check, info, limits);
  const moved = limits[check] !== undefined;
  const range = limitRange(check);
  const { end, gradient } = scale(check, info, limit);
  const word = { above: "over", below: "under" }[info.critical];
  const bound = formatLimit(check, limit, info.unit);
  // At Mechanic's limit the headline is what needs a fix; at a moved limit, what the colours count.
  const { critical, finding } = areas(analysis, check);
  const shown = moved ? (counted && counted.check === check && counted.limit === limit ? counted.mm2 : null) : finding;
  const headline = shown === null ? "…" : shown >= 1 ? `${formatArea(shown)} ${word} ${bound}` : moved ? `nothing ${word} ${bound}` : "nothing to fix";
  const soft = !moved && SOFT[check] && critical - finding >= 1 ? critical - finding : 0;
  const unit = info.unit === "deg" ? "°" : " mm";
  // Overlaps and rays that never came out get their own colour, named only when there are any.
  const special = check === "overhang" || analysis.parts.some((p) => ((check === "clearance" ? p.clearance?.overlap_mm2 : p.thickness?.unread_mm2) ?? 0) > 0);
  const pct = ((limit - range.min) / (range.max - range.min)) * 100;
  return (
    <section
      aria-label={`${info.label} legend`}
      data-target="surface:legend"
      className={`absolute left-3 z-20 w-[min(300px,calc(100%-96px))] animate-rise rounded-[16px] bg-white/95 px-3.5 pt-2.5 pb-3 shadow-[var(--shadow-float)] backdrop-blur ${lifted ? "bottom-[52px]" : "bottom-3"}`}
    >
      <div className="flex items-baseline gap-2">
        <h3 className="min-w-0 flex-1 truncate text-[14px] font-bold text-ink">{info.label}</h3>
        <span className={`num shrink-0 text-[13px] font-bold whitespace-nowrap ${shown === null ? "text-muted" : shown >= 1 ? "text-fail-ink" : "text-ok-ink"}`} data-target="surface:area">
          {headline}
        </span>
        <button type="button" onClick={() => show(null)} aria-label="Hide the surface check" className="-mr-1.5 self-center rounded-full p-1 text-muted hover:bg-tile hover:text-ink">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      {check === "overhang" && <p className="text-[12px] font-semibold text-muted">{poseLine(analysis)}</p>}
      <div className="relative mt-2 h-2.5 rounded-full" style={{ background: gradient }} aria-hidden>
        <span className="absolute -top-1 -bottom-1 w-0.5 rounded-full bg-ink" style={{ left: `${Math.min(100, (limit / end) * 100)}%` }} />
      </div>
      <div className="num mt-1 flex justify-between text-[11px] font-semibold text-muted">
        <span>0{unit}</span>
        <span>
          {fmtNum(end, check === "overhang" ? 0 : 1)}
          {unit}
          {check === "overhang" ? "" : "+"}
        </span>
      </div>
      <label className="mt-1.5 flex items-center gap-2.5">
        <span className="shrink-0 text-[12px] font-semibold text-ink-2">Limit</span>
        <input
          type="range"
          min={range.min}
          max={range.max}
          step={range.step}
          value={limit}
          onChange={(e) => setLimit(check, Number(e.target.value))}
          aria-label={`${info.label} limit`}
          className="bevel-range min-w-0 flex-1"
          style={{ "--p": `${pct}%` } as React.CSSProperties}
        />
        <span className="num w-14 shrink-0 text-right text-[13px] font-bold text-ink">{bound}</span>
      </label>
      {moved && (
        <button type="button" onClick={() => setLimit(check, null)} className="mt-0.5 text-[12px] font-semibold text-accent hover:underline">
          Back to Mechanic's {formatLimit(check, info.limit, info.unit)}
        </button>
      )}
      {soft > 0 && (
        <p className="mt-1 text-[12px] leading-snug font-semibold text-muted" data-target="surface:soft">
          {formatArea(soft)} red at {SOFT[check]}: no fix needed
        </p>
      )}
      {special && (
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[12px] font-semibold text-muted">
          {check === "overhang" && <Swatch colour={SHADES.bed}>On the bed</Swatch>}
          {check === "clearance" && <Swatch colour={SHADES.overlap}>Parts overlap</Swatch>}
          {check === "thickness" && <Swatch colour={SHADES.unread}>No reading</Swatch>}
        </div>
      )}
      {picked && picked.check === check && (
        <p className="mt-2 flex items-start gap-1.5 rounded-[10px] bg-page-2 px-2.5 py-1.5 text-[12px] leading-snug text-ink-2" data-target="surface:picked">
          <span className="min-w-0 flex-1">
            <b className={picked.critical ? "text-fail-ink" : "text-ink"}>{formatValue(check, picked.value, info)}</b> on {picked.part.replace(/_/g, " ")} at{" "}
            <span className="num whitespace-nowrap">({picked.atMm.map((v) => fmtNum(v, 1)).join(", ")}) mm</span>
          </span>
          <button
            type="button"
            onClick={() =>
              attach({ kind: "spot", check, value: picked.value, part: picked.part, part_id: picked.partId, at_mm: picked.atMm, limit, critical: picked.critical, build: Number(buildOf(cadUrl)) || null })
            }
            aria-label="Add this spot to your message for Mechanic"
            title="Add this spot to your message for Mechanic"
            data-target="surface:attach"
            className="-my-0.5 rounded-full p-1 text-accent hover:bg-accent-soft"
          >
            <MessageSquarePlus className="h-3.5 w-3.5" />
          </button>
          <button type="button" onClick={() => pick(null)} aria-label="Clear the picked spot" className="-mr-1 rounded-full p-0.5 text-muted hover:bg-tile hover:text-ink">
            <X className="h-3 w-3" />
          </button>
        </p>
      )}
    </section>
  );
}
