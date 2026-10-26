// What floats over a studio canvas (the live model in the Model and CAD tabs): the tool rail on
// the left, the zoom pill on the right, the parts panel and the measuring hint, and the
// studio's keys while no text field has the focus: 1 to 4 views, + − 0 zoom and fit, G grid,
// L labels, V select, M measure, P parts.
import { useEffect } from "react";
import { Ruler } from "lucide-react";
import { useUi } from "../../lib/ui";
import { useExplodeHover } from "../canvas/explode";
import { PartsPanel } from "./PartsPanel";
import { useStudio, VIEW_KEYS } from "./studio";
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
      else if (e.key === "v") ui.setTool("select");
      else if (e.key === "m") {
        useExplodeHover.getState().pin(null);
        ui.setTool(ui.tool === "measure" ? "select" : "measure");
      } else if (e.key === "p") ui.setPartsOpen(!ui.partsOpen);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export function StudioOverlay() {
  useStudioKeys();
  const measuring = useUi((s) => s.tool === "measure");
  const partsOpen = useUi((s) => s.partsOpen);
  return (
    <>
      <ToolRail />
      <ZoomPill />
      {partsOpen && <PartsPanel />}
      {measuring && (
        <p
          role="status"
          className="pointer-events-none absolute top-3 left-1/2 z-20 flex max-w-[60%] -translate-x-1/2 animate-rise items-center gap-2 truncate rounded-full bg-ink py-1.5 pr-4 pl-3 text-[13px] font-semibold text-white shadow-[var(--shadow-float)]"
        >
          <Ruler className="h-4 w-4 shrink-0" />
          <span className="truncate">Click two points on the model · Esc to stop</span>
        </p>
      )}
    </>
  );
}
