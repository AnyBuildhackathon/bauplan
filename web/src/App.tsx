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
import { useSession } from "./events/store";
import { useSource } from "./events/source";
import { AccessScreen } from "./views/AccessScreen";
import { useBolzenVoice } from "./lib/bolzenVoice";
import { usePilotRunner } from "./lib/pilot";
import { useUi } from "./lib/ui";
import { useDirector } from "./lib/director";
import { BenchResults } from "./views/BenchResults";
import { BomDrawer } from "./views/BomDrawer";
import { VersionDrawer } from "./views/VersionDrawer";
import { BuildGuide } from "./views/BuildGuide";
import { LessonModal } from "./views/LessonModal";
import { CommunityView } from "./views/CommunityView";
import { LibraryView } from "./views/LibraryView";
import { LogbookView } from "./views/LogbookView";
import { StartScreen } from "./views/StartScreen";
import { TrainingView } from "./views/TrainingView";
import { WorkbenchView } from "./views/WorkbenchView";

const NOTICE_MS = 5000;
const HANDOVER_MS = 650;

// The chat column's width. The canvas keeps at least CANVAS_MIN; the rest of the
// window is shared by the icon rail and the chat.
const RAIL = 64;
const CANVAS_MIN = 480;
const WORKBENCH_GUTTERS = 48;
const CHAT = { initial: 420, min: 320, max: 860 };

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

/** The bench once the backend answered and, on the public deployment, the access code was entered. */
export default function App() {
  const access = useSource((s) => s.access);
  return access === "open" ? <Bench /> : <AccessScreen />;
}

function Bench() {
  useDirector();
  const view = useUi((s) => s.view);
  const chatExpanded = useUi((s) => s.chatExpanded);
  useBolzenVoice();
  useBrowserTraining();
  useBrowserStress();
  useAutoExplain();
  const vw = useWindowWidth();
  const chatPane = usePaneWidth("anybuild.chatWidth", CHAT.initial);
  const hasChat = view === "werkbank" || view === "library" || view === "community";
  const chatMax = Math.min(CHAT.max, vw - RAIL - WORKBENCH_GUTTERS - CANVAS_MIN);
  const chatWidth = fit(chatPane.wanted, CHAT.min, chatMax);
  usePilotRunner();
  // Before anything has started, the workbench is one start screen; the first chat line,
  // step or version (from any source) brings the normal bench.
  const started = useSession((s) => s.chat.length > 0 || s.versions.length > 0 || Object.values(s.steps).some((st) => st.status !== "pending"));
  const starting = view === "werkbank" && !started;
  // Leaving the start screen is a short hand-over: the box fades and settles in place while
  // the chat column and the canvas rise in. With reduced motion the bench simply appears.
  const [wasStarting, setWasStarting] = useState(starting);
  const [handover, setHandover] = useState(false);
  if (wasStarting !== starting) {
    setWasStarting(starting);
    setHandover(!starting && view === "werkbank" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }
  useEffect(() => {
    if (!handover) return;
    const done = setTimeout(() => setHandover(false), HANDOVER_MS);
    return () => clearTimeout(done);
  }, [handover]);
  const riseIn = handover ? "animate-rise [animation-duration:450ms]" : "";
  return (
    <div className="flex h-full min-h-0">
      <IconRail />
      {hasChat && !starting && (
        <>
          {/* Expanded, the chat takes the whole window; the bench stays mounted behind it. */}
          <div
            className={`${chatExpanded ? "h-full min-w-0 flex-1" : "h-full shrink-0 border-r border-line"} ${riseIn} [animation-delay:80ms]`}
            style={chatExpanded ? undefined : { width: chatWidth }}
          >
            <SidebarChat />
          </div>
          {!chatExpanded && (
            <ResizeHandle
            width={chatWidth}
            min={CHAT.min}
            max={chatMax}
            onChange={chatPane.set}
            onReset={chatPane.reset}
              side="before"
              label="Resize the chat"
            />
          )}
        </>
      )}
      <div className={`min-h-0 min-w-0 flex-1 flex-col ${hasChat && chatExpanded && !starting ? "hidden" : "flex"}`}>
        <TopBar />
        <main className="min-h-0 flex-1">
          {(starting || handover) && <StartScreen leaving={handover} />}
          {view === "werkbank" && !starting && (
            <div className={`h-full ${riseIn} [animation-delay:160ms]`}>
              <WorkbenchView />
            </div>
          )}
          {view === "library" && <LibraryView />}
          {view === "community" && <CommunityView />}
          {view === "training" && <TrainingView />}
          {view === "logbuch" && <LogbookView />}
        </main>
      </div>
      <BomDrawer />
      <VersionDrawer />
      <BuildGuide />
      <BenchResults />
      <DrawLayer />
      <PointerLayer />
      <LessonModal />
      <Notice />
    </div>
  );
}
