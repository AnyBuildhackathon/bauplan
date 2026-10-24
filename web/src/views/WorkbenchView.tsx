// Werkbank, the one main screen: Mechanic's chat sits beside it (App), the canvas
// fills the middle, and the requirements and key numbers card stays on the right.
// The divider before the card resizes it; App fits its width to the window.
import { CanvasCard } from "../components/canvas/CanvasCard";
import { BuildPanel } from "../components/panels/Panels";
import { ResizeHandle } from "../components/ui/ResizeHandle";

interface PanelWidth {
  width: number;
  min: number;
  max: number;
  onChange: (width: number) => void;
  onReset: () => void;
}

export function WorkbenchView({ panel }: { panel: PanelWidth }) {
  return (
    <div className="flex h-full min-h-0 px-6 pt-5 pb-5">
      <div className="min-h-0 min-w-0 flex-1">
        <CanvasCard />
      </div>
      <div className="flex w-6 shrink-0 justify-center">
        <ResizeHandle {...panel} side="after" label="Resize the panel" />
      </div>
      <div className="grid min-h-0 shrink-0" style={{ width: panel.width }}>
        <BuildPanel />
      </div>
    </div>
  );
}
