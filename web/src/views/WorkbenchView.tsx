// Werkbank, the one main screen: Bolzen's chat on the left, the canvas in the
// middle, and the compact build panel on the right.
import SidebarChat from "../components/chat/SidebarChat";
import { CanvasCard } from "../components/canvas/CanvasCard";
import { BuildPanel } from "../components/panels/Panels";

export function WorkbenchView() {
  return (
    <div className="grid h-full min-h-0 grid-cols-[400px_minmax(0,1fr)_380px] gap-4 px-4 pb-4">
      <SidebarChat />
      <div className="min-h-0 min-w-0">
        <CanvasCard />
      </div>
      <BuildPanel />
    </div>
  );
}
