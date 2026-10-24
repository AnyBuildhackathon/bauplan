import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { IconRail } from "./components/IconRail";
import SidebarChat from "./components/chat/SidebarChat";
import { TopBar } from "./components/TopBar";
import { useBrowserTraining } from "./components/training/useBrowserTraining";
import { DrawLayer } from "./components/overlay/DrawLayer";
import { PointerLayer } from "./components/overlay/PointerLayer";
import { useSource } from "./events/source";
import { useBolzenVoice } from "./lib/bolzenVoice";
import { useUi } from "./lib/ui";
import { BomDrawer } from "./views/BomDrawer";
import { BuildGuide } from "./views/BuildGuide";
import { LessonModal } from "./views/LessonModal";
import { LibraryView } from "./views/LibraryView";
import { LogbookView } from "./views/LogbookView";
import { TrainingView } from "./views/TrainingView";
import { WorkbenchView } from "./views/WorkbenchView";

const NOTICE_MS = 5000;

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
  return (
    <div className="flex h-full min-h-0">
      <IconRail />
      {(view === "werkbank" || view === "library") && (
        <div className="h-full w-[400px] shrink-0 border-r border-line">
          <SidebarChat />
        </div>
      )}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1">
          {view === "werkbank" && <WorkbenchView />}
          {view === "library" && <LibraryView />}
          {view === "training" && <TrainingView />}
          {view === "logbuch" && <LogbookView />}
        </main>
      </div>
      <BomDrawer />
      <BuildGuide />
      <DrawLayer />
      <PointerLayer />
      <LessonModal />
      <Notice />
    </div>
  );
}
