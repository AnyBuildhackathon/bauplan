import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { IconRail } from "./components/IconRail";
import SidebarChat from "./components/chat/SidebarChat";
import { TopBar } from "./components/TopBar";
import { useBrowserTraining } from "./components/training/useBrowserTraining";
import { useBrowserStress } from "./components/stress/useBrowserStress";
import { useAutoExplain } from "./components/learn/Explain";
import { ResizeHandle, usePaneWidth, useWindowWidth } from "./components/ui/ResizeHandle";
import { DrawLayer } from "./components/overlay/DrawLayer";
import { PointerLayer } from "./components/overlay/PointerLayer";
import { useSource } from "./events/source";
import { useBolzenVoice } from "./lib/bolzenVoice";
import { usePilotRunner } from "./lib/pilot";
import { useUi } from "./lib/ui";
import { BomDrawer } from "./views/BomDrawer";
import { VersionDrawer } from "./views/VersionDrawer";
import { BuildGuide } from "./views/BuildGuide";
import { LessonModal } from "./views/LessonModal";
import { LibraryView } from "./views/LibraryView";
import { LogbookView } from "./views/LogbookView";
import { TrainingView } from "./views/TrainingView";
import { WorkbenchView } from "./views/WorkbenchView";

const NOTICE_MS = 5000;

// Column widths around the canvas. The canvas keeps at least CANVAS_MIN; the rest of
// the window is shared by the icon rail, the chat and the right panel.
const RAIL = 64;
const CANVAS_MIN = 380;
const WORKBENCH_GUTTERS = 72;
const CHAT = { initial: 400, min: 320, max: 760 };
const PANEL = { initial: 360, min: 300, max: 520 };

const fit = (wanted: number, min: number, max: number) => Math.round(Math.max(min, Math.min(max, wanted)));

/** Short system notices. They sit at the top under the bar, where views keep free
 * space, and fade on their own so they never cover the work for long. */
function Notice() {
  const notice = useSource((s) => s.notice);
  const dismiss = useSource((s) => s.dismissNotice);
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    if (!notice) return;
    setLeaving(false);
    const fade = setTimeout(() => setLeaving(true), NOTICE_MS);
    const gone = setTimeout(dismiss, NOTICE_MS + 400);
    return () => {
      clearTimeout(fade);
      clearTimeout(gone);
    };
  }, [notice, dismiss]);
  if (!notice) return null;
  return (
    <div
      role="status"
      className={`fixed top-[72px] left-1/2 z-[80] flex -translate-x-1/2 animate-rise items-center gap-3 rounded-full bg-ink py-2 pr-2 pl-5 text-[15px] font-semibold text-white shadow-[var(--shadow-float)] transition-opacity duration-400 ${
        leaving ? "opacity-0" : "opacity-100"
      }`}
    >
      {notice}
      <button onClick={dismiss} className="rounded-full p-1.5 hover:bg-white/15" aria-label="Close">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

export default function App() {
  const view = useUi((s) => s.view);
  useBolzenVoice();
  useBrowserTraining();
  useBrowserStress();
  useAutoExplain();
  const vw = useWindowWidth();
  const chatPane = usePaneWidth("anybuild.chatWidth", CHAT.initial);
  const panelPane = usePaneWidth("anybuild.panelWidth", PANEL.initial);
  // The panel only sits on the workbench; when the window is narrow the chat gives way first.
  const room = vw - RAIL - WORKBENCH_GUTTERS - CANVAS_MIN;
  const hasPanel = view === "werkbank";
  const panelWidth = hasPanel ? fit(panelPane.wanted, PANEL.min, Math.min(PANEL.max, room - CHAT.min)) : 0;
  const chatMax = Math.min(CHAT.max, room - panelWidth);
  const chatWidth = fit(chatPane.wanted, CHAT.min, chatMax);
  const panel = {
    width: panelWidth,
    min: PANEL.min,
    max: Math.min(PANEL.max, room - chatWidth),
    onChange: panelPane.set,
    onReset: panelPane.reset,
  };
  usePilotRunner();
  return (
    <div className="flex h-full min-h-0">
      <IconRail />
      {(view === "werkbank" || view === "library") && (
        <>
          <div className="h-full shrink-0 border-r border-line" style={{ width: chatWidth }}>
            <SidebarChat />
          </div>
          <ResizeHandle
            width={chatWidth}
            min={CHAT.min}
            max={chatMax}
            onChange={chatPane.set}
            onReset={chatPane.reset}
            side="before"
            label="Resize the chat"
          />
        </>
      )}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1">
          {view === "werkbank" && <WorkbenchView panel={panel} />}
          {view === "library" && <LibraryView />}
          {view === "training" && <TrainingView />}
          {view === "logbuch" && <LogbookView />}
        </main>
      </div>
      <BomDrawer />
      <VersionDrawer />
      <BuildGuide />
      <DrawLayer />
      <PointerLayer />
      <LessonModal />
      <Notice />
    </div>
  );
}
