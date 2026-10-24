// Werkbank, the one main screen: Mechanic's chat sits beside it (App) and the canvas
// takes the rest. Requirements and results are cards in the chat; the bill of
// materials opens from those cards and from the canvas toolbar.
import { CanvasCard } from "../components/canvas/CanvasCard";

export function WorkbenchView() {
  return (
    <div className="h-full min-h-0 px-6 pt-5 pb-5">
      <CanvasCard />
    </div>
  );
}
