// The studio's tools, floating at the left edge of the canvas: Select (a click on a part opens
// its card and marks it in the assembly tree), Measure (two clicks give the distance), Mark (draw
// on the view for Mechanic) and Parts (the panel with the catalog's part models and the library's builds).
import type { ReactNode } from "react";
import { MousePointer2, PenLine, Ruler, Shapes } from "lucide-react";
import { useUi } from "../../lib/ui";
import { useExplodeHover } from "../canvas/explode";
import { toggleMark } from "./studio";

export function RailButton({ label, active, onClick, target, children }: { label: string; active: boolean; onClick: () => void; target: string; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      data-target={target}
      className={`flex h-10 w-10 items-center justify-center rounded-[12px] transition ${active ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-tile hover:text-ink"}`}
    >
      {children}
    </button>
  );
}

export function ToolRail() {
  const tool = useUi((s) => s.tool);
  const setTool = useUi((s) => s.setTool);
  const partsOpen = useUi((s) => s.partsOpen);
  const setPartsOpen = useUi((s) => s.setPartsOpen);
  return (
    <div
      role="toolbar"
      aria-label="Tools"
      aria-orientation="vertical"
      className="absolute top-1/2 left-3 z-20 flex -translate-y-1/2 flex-col items-center gap-1 rounded-[16px] bg-white/95 p-1 shadow-[var(--shadow-pill)] backdrop-blur"
    >
      <RailButton label="Select (V)" active={tool === "select"} onClick={() => setTool("select")} target="tool:select">
        <MousePointer2 className="h-[18px] w-[18px]" strokeWidth={1.9} />
      </RailButton>
      <RailButton
        label="Measure (M)"
        active={tool === "measure"}
        onClick={() => {
          // The part card would sit in the way of the points.
          useExplodeHover.getState().pin(null);
          setTool(tool === "measure" ? "select" : "measure");
        }}
        target="tool:measure"
      >
        <Ruler className="h-[18px] w-[18px]" strokeWidth={1.9} />
      </RailButton>
      <RailButton label="Mark for Mechanic (D)" active={tool === "mark"} onClick={toggleMark} target="tool:mark">
        <PenLine className="h-[18px] w-[18px]" strokeWidth={1.9} />
      </RailButton>
      <span className="my-0.5 h-px w-6 bg-line" aria-hidden />
      <RailButton label="Parts (P)" active={partsOpen} onClick={() => setPartsOpen(!partsOpen)} target="tool:parts">
        <Shapes className="h-[18px] w-[18px]" strokeWidth={1.9} />
      </RailButton>
    </div>
  );
}
