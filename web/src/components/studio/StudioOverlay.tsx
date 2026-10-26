// What floats over a studio canvas (the live model in the Model and CAD tabs): the tool rail on
// the left, the zoom pill on the right, the parts panel, the measuring hint (which adds a finished
// measurement to Mechanic's message box), the marking layer, the surface check's legend, and the
// studio's keys while no text field has the focus: 1 to 4 views, + − 0 zoom and fit, G grid,
// L labels, E explode, S section, V select, M measure, D mark, P parts.
import { useEffect } from "react";
import { MessageSquarePlus, Ruler } from "lucide-react";
import { attach, shownBuild } from "../../events/notes";
import { fmtNum } from "../../lib/format";
import { useUi } from "../../lib/ui";
import { useExplodeHover } from "../canvas/explode";
import { AnalysisLegend } from "./AnalysisLegend";
import { MarkupLayer } from "./MarkupLayer";
import { PartsPanel } from "./PartsPanel";
import { toggleMark, toggleSection, useStudio, VIEW_KEYS } from "./studio";
import { ToolRail } from "./ToolRail";
import { ZOOM_IN, ZOOM_OUT, ZoomPill } from "./ZoomPill";

function typing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
}

function useStudioKeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.repeat || e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      const ui = useUi.getState();
      const { send } = useStudio.getState();
      const view = VIEW_KEYS[e.key];
      if (view) send({ kind: "view", view });
      else if (e.key === "+" || e.key === "=") send({ kind: "zoom", factor: ZOOM_IN });
      else if (e.key === "-") send({ kind: "zoom", factor: ZOOM_OUT });
      else if (e.key === "0") send({ kind: "fit" });
      else if (e.key === "g") ui.setStudio({ grid: !ui.studio.grid });
      else if (e.key === "l") ui.setStudio({ labels: !ui.studio.labels });
      else if (e.key === "e") ui.setExploded(!ui.exploded);
      else if (e.key === "s") toggleSection();
      else if (e.key === "v") ui.setTool("select");
      else if (e.key === "m") {
        useExplodeHover.getState().pin(null);
        ui.setTool(ui.tool === "measure" ? "select" : "measure");
      } else if (e.key === "d") toggleMark();
      else if (e.key === "p") ui.setPartsOpen(!ui.partsOpen);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export function StudioOverlay() {
  useStudioKeys();
  const tool = useUi((s) => s.tool);
  const partsOpen = useUi((s) => s.partsOpen);
  const measurement = useStudio((s) => s.measurement);
  const distance = measurement ? Math.hypot(...measurement.b.point_mm.map((v, i) => v - measurement.a.point_mm[i])) : 0;
  return (
    <>
      <ToolRail />
      <ZoomPill />
      <AnalysisLegend />
      {partsOpen && <PartsPanel />}
      {tool === "mark" && <MarkupLayer />}
      {tool === "measure" && (
        <div
          role="status"
          className={`pointer-events-none absolute top-3 left-1/2 z-20 flex max-w-[calc(100%-24px)] -translate-x-1/2 animate-rise items-center gap-2 rounded-full bg-ink pl-3 text-[13px] font-semibold text-white shadow-[var(--shadow-float)] ${measurement ? "py-1 pr-1" : "py-1.5 pr-4"}`}
        >
          <Ruler className="h-4 w-4 shrink-0" />
          <span className="truncate">{measurement ? `${fmtNum(distance, distance < 100 ? 1 : 0)} mm measured · Esc to stop` : "Click two points on the model · Esc to stop"}</span>
          {measurement && (
            <button
              type="button"
              onClick={() => attach({ kind: "measure", a: measurement.a, b: measurement.b, build: shownBuild() })}
              data-target="measure:attach"
              title="Add this measurement to your message for Mechanic"
              className="pointer-events-auto inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-white px-3 text-[13px] font-bold text-ink transition hover:bg-white/90"
            >
              <MessageSquarePlus className="h-3.5 w-3.5" /> Add to message
            </button>
          )}
        </div>
      )}
    </>
  );
}
