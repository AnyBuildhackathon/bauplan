// Werkbank, the one main screen: Mechanic's chat sits beside it (App), the canvas
// fills the middle, and the requirements and key numbers card stays on the right.
import { CanvasCard } from "../components/canvas/CanvasCard";
import { BuildPanel } from "../components/panels/Panels";

export function WorkbenchView() {
  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_360px] gap-6 px-6 pt-5 pb-5">
      <div className="min-h-0 min-w-0">
        <CanvasCard />
      </div>
      <BuildPanel />
    </div>
  );
}
