// Zoom in, zoom out and fit the model, floating at the right edge of the studio canvas, clear
// of Mechanic's line and his figure at the bottom.
import { Minus, Plus, Scan } from "lucide-react";
import { useStudio } from "./studio";

/** One step of the zoom buttons and keys: a fifth closer, or a quarter farther. */
export const ZOOM_IN = 0.8;
export const ZOOM_OUT = 1.25;

export function ZoomPill() {
  const send = useStudio((s) => s.send);
  const button = "flex h-9 w-9 items-center justify-center rounded-full text-ink-2 transition hover:bg-tile hover:text-ink";
  return (
    <div
      role="toolbar"
      aria-label="Zoom"
      aria-orientation="vertical"
      className="absolute top-1/2 right-3 z-20 flex -translate-y-1/2 flex-col items-center gap-0.5 rounded-full bg-white/95 p-1 shadow-[var(--shadow-pill)] backdrop-blur"
    >
      <button type="button" className={button} onClick={() => send({ kind: "zoom", factor: ZOOM_IN })} title="Zoom in (+)" aria-label="Zoom in">
        <Plus className="h-[18px] w-[18px]" strokeWidth={2} />
      </button>
      <button type="button" className={button} onClick={() => send({ kind: "zoom", factor: ZOOM_OUT })} title="Zoom out (−)" aria-label="Zoom out">
        <Minus className="h-[18px] w-[18px]" strokeWidth={2} />
      </button>
      <span className="my-0.5 h-px w-5 bg-line" aria-hidden />
      <button type="button" className={button} onClick={() => send({ kind: "fit" })} title="Fit the model (0)" aria-label="Fit the model">
        <Scan className="h-[17px] w-[17px]" strokeWidth={2} />
      </button>
    </div>
  );
}
