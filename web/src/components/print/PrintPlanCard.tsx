// Print plan in the chat: totals for every printed part, then one row per part with
// time, filament, cost, printability warnings and the G-code or STL download.
import { useState } from "react";
import { AlertTriangle, ChevronDown, Download, Printer } from "lucide-react";
import type { PrintEvent, PrintPart } from "../../events/types";
import { assetUrl } from "../../lib/api";
import { fmtEur, fmtGram } from "../../lib/format";

function fmtTime(min: number): string {
  const m = Math.round(min);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

function PartRow({ part }: { part: PrintPart }) {
  const gcode = assetUrl(part.gcode_url);
  const stl = assetUrl(part.stl_url);
  return (
    <li className="border-t border-line py-2">
      <div className="flex items-baseline gap-2">
        <span className="min-w-0 flex-1 truncate text-[14px] font-semibold text-ink">
          {part.qty > 1 ? `${part.qty} × ` : ""}
          {part.name}
        </span>
        <span className="num shrink-0 text-[13px] text-muted">{fmtEur(part.cost_eur * part.qty)}</span>
      </div>
      <div className="num text-[13px] text-muted">
        {part.material} · {fmtTime(part.time_min)} · {fmtGram(part.filament_g)} · {part.size_mm.map((v) => Math.round(v)).join(" × ")} mm
      </div>
      {part.warnings.map((w) => (
        <div key={w.kind} className="mt-1 flex items-start gap-1.5 text-[13px] leading-snug text-fail-ink">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{w.text}</span>
        </div>
      ))}
      {(gcode || stl) && (
        <div className="mt-1 flex gap-3 text-[13px] font-semibold">
          {gcode && (
            <a href={gcode} download className="flex items-center gap-1 text-link hover:underline">
              <Download className="h-3.5 w-3.5" /> G-code
            </a>
          )}
          {stl && (
            <a href={stl} download className="flex items-center gap-1 text-link hover:underline">
              <Download className="h-3.5 w-3.5" /> STL
            </a>
          )}
        </div>
      )}
    </li>
  );
}

export function PrintPlanCard({ plan }: { plan: PrintEvent }) {
  const [open, setOpen] = useState(false);
  const { totals } = plan;
  const estimate = plan.source === "estimate";
  return (
    <div className="rounded-[14px] bg-page-2 p-3" data-target="print_plan">
      <button type="button" onClick={() => setOpen((v) => !v)} className="group flex w-full items-center gap-3 text-left" aria-expanded={open}>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white shadow-[var(--shadow-pill)]">
          <Printer className="h-5 w-5 text-ink-2" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-[14px] font-bold text-ink">
            Print plan · {totals.parts} part{totals.parts === 1 ? "" : "s"}
            <span className="rounded-full bg-white px-2 py-0.5 text-[12px] font-semibold text-muted">
              {estimate ? "estimate" : plan.slicer || "slicer"}
            </span>
          </div>
          <div className="num text-[13px] text-muted">
            {fmtTime(totals.time_min)} · {fmtGram(totals.filament_g)} · {fmtEur(totals.cost_eur)}
            {totals.warnings ? ` · ${totals.warnings} warning${totals.warnings === 1 ? "" : "s"}` : " · no warnings"}
          </div>
        </div>
        <ChevronDown className={`h-4 w-4 text-muted transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-2">
          <ul>
            {plan.parts.map((part) => (
              <PartRow key={part.id} part={part} />
            ))}
          </ul>
          <p className="border-t border-line pt-2 text-[12px] leading-snug text-muted">
            {estimate
              ? `Estimate from the mesh, no slicer installed: no G-code. ${plan.profile.layer_height_mm} mm layers, ${plan.profile.infill_pct} % infill, ${plan.profile.printer}.`
              : `Sliced by ${plan.slicer}: ${plan.profile.layer_height_mm} mm layers, ${plan.profile.infill_pct} % infill, ${plan.profile.printer}.`}
          </p>
        </div>
      )}
    </div>
  );
}
