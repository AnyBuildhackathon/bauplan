// Where events come from: the live backend over SSE, or the recorded demo fixture.
// The UI only ever reads the session store, so both sources look the same to it.
import { create } from "zustand";
import { DEMO_FIXTURE, type FixtureItem } from "./fixture";
import { useSession } from "./store";
import { parseEvent, type QuestionEvent } from "./types";
import { apiUrl } from "../lib/api";
import { useUi } from "../lib/ui";
import { loadVoiceCapabilities } from "../lib/voice";
import { recordedOmniverse } from "./omniverse";

export type SourceMode = "live" | "demo";
export type LiveStatus = "idle" | "connecting" | "open" | "error";

interface DemoState {
  playing: boolean;
  started: boolean;
  speed: number;
  index: number;
  total: number;
}

interface SourceState {
  mode: SourceMode;
  live: LiveStatus;
  demo: DemoState;
  notice: string | null;
  setMode: (mode: SourceMode) => void;
  play: () => void;
  pause: () => void;
  restart: () => void;
  setSpeed: (speed: number) => void;
  seekToMarker: (marker: string) => void;
  skipToEnd: () => void;
  sendPrompt: (text: string) => Promise<void>;
  /** Changes CAD parameters; the backend recomputes and answers with a new `cad` event. */
  setCadParams: (params: Record<string, number>) => Promise<boolean>;
  /** Opens the current part in the FreeCAD app on this Mac. */
  openInFreecad: () => Promise<void>;
  resetSession: () => Promise<void>;
  /** Ticks or unticks "bestellt" on an order task; the backend mirrors it to Jamie. */
  toggleTask: (id: string, done: boolean) => Promise<void>;
  /** Stands in for Jamie's webhook: marks a meeting as running, or as ended (which rebuilds). */
  meetingWebhook: (event: "started" | "ended", meeting: { id: string; title: string }) => Promise<void>;
  /** Answers Bolzen's question (a contradiction between meetings) with one of its options. */
  answerQuestion: (id: string, answerId: string) => Promise<void>;
  dismissNotice: () => void;
}

const MODE_KEY = "anybuild.source";
const SPEEDS = [1, 2, 4];

function storedMode(): SourceMode | null {
  try {
    const v = localStorage.getItem(MODE_KEY);
    return v === "live" || v === "demo" ? v : null;
  } catch {
    return null;
  }
}
function storeMode(mode: SourceMode) {
  try {
    localStorage.setItem(MODE_KEY, mode);
  } catch {
    // Private windows may refuse storage; the mode just will not be remembered.
  }
}

/** The option a spoken or typed answer names: "fifteen", "15", or "yes" for the suggestion. */
export function matchAnswer(text: string, q: QuestionEvent): string | null {
  let lowered = text.toLowerCase();
  for (const [word, digits] of Object.entries({
    zehn: "10",
    ten: "10",
    zwölf: "12",
    twelve: "12",
    fünfzehn: "15",
    fifteen: "15",
    zwanzig: "20",
    twenty: "20",
  })) {
    lowered = lowered.replace(new RegExp(`\\b${word}\\b`, "g"), digits);
  }
  for (const option of q.options) {
    const numbers = option.label.match(/\d+/g) ?? [];
    if (numbers.some((n) => new RegExp(`\\b${n}\\b`).test(lowered))) return option.id;
  }
  return /\b(ja|passt|okay|ok|genau|yes|fine|sure)\b/.test(lowered) ? q.default_id : null;
}

// --- live SSE ---------------------------------------------------------------

let eventSource: EventSource | null = null;
let retry: ReturnType<typeof setTimeout> | null = null;
const RETRY_MS = 3000;

/**
 * Opens the SSE stream. EventSource retries dropped connections itself, but gives
 * up for good after an HTTP error (for example 502 from the proxy while the backend
 * is still starting), so a closed stream is reopened here until it connects.
 */
function openLive(onStatus: (s: LiveStatus) => void) {
  closeLive();
  onStatus("connecting");
  const es = new EventSource(apiUrl("/api/events"));
  eventSource = es;
  // The backlog a (re)connect replays is applied without animations or Bolzen speaking it again.
  let replaying = true;
  es.onopen = () => {
    // EventSource reconnects on its own too; each new connection starts with a backlog.
    replaying = true;
    onStatus("open");
    void loadVoiceCapabilities().then((caps) => useUi.setState({ stt: caps.stt }));
  };
  es.onerror = () => {
    if (es.readyState !== EventSource.CLOSED) return onStatus("connecting");
    onStatus("error");
    if (eventSource === es) retry = setTimeout(() => openLive(onStatus), RETRY_MS);
  };
  es.onmessage = (msg) => {
    const ev = parseEvent(msg.data);
    if (!ev) return;
    if (ev.type === "replayed") {
      replaying = false;
      return;
    }
    useSession.getState().apply(ev, { instant: replaying });
  };
}
function closeLive() {
  if (retry) clearTimeout(retry);
  retry = null;
  eventSource?.close();
  eventSource = null;
}

// --- demo replay -------------------------------------------------------------

let timer: ReturnType<typeof setTimeout> | null = null;
const fixture: FixtureItem[] = DEMO_FIXTURE;

function clearTimer() {
  if (timer) clearTimeout(timer);
  timer = null;
}

export const useSource = create<SourceState>((set, get) => {
  const scheduleNext = () => {
    clearTimer();
    const { demo } = get();
    if (!demo.playing) return;
    if (demo.index >= fixture.length) {
      set({ demo: { ...demo, playing: false } });
      return;
    }
    const item = fixture[demo.index];
    timer = setTimeout(() => {
      useSession.getState().apply(item.event);
      set((s) => ({ demo: { ...s.demo, index: s.demo.index + 1 } }));
      scheduleNext();
    }, item.delay / demo.speed);
  };

  /** Applies fixture items up to (not including) `target` at once, without animations. */
  const fastForward = (target: number) => {
    const { demo } = get();
    const apply = useSession.getState().apply;
    for (let i = demo.index; i < target && i < fixture.length; i++) apply(fixture[i].event, { instant: true });
    set({ demo: { ...demo, index: Math.min(target, fixture.length), started: true } });
  };

  /** Applies the recording's zero-delay preamble (tool status, steps), so the start screen is not empty. */
  const primeDemo = () => {
    const firstTimed = fixture.findIndex((f) => f.delay > 0);
    fastForward(firstTimed < 0 ? fixture.length : firstTimed);
    set((s) => ({ demo: { ...s.demo, started: false } }));
  };

  const startDemo = () => {
    set((s) => ({ demo: { ...s.demo, started: true, playing: true } }));
    scheduleNext();
  };

  return {
    mode: "live",
    live: "idle",
    demo: { playing: false, started: false, speed: 1, index: 0, total: fixture.length },
    notice: null,

    setMode: (mode) => {
      clearTimer();
      closeLive();
      useSession.getState().reset();
      storeMode(mode);
      set({
        mode,
        live: "idle",
        notice: null,
        demo: { ...get().demo, playing: false, started: false, index: 0 },
      });
      if (mode === "live") openLive((live) => set({ live }));
      else primeDemo();
    },

    play: () => {
      if (get().mode !== "demo") return;
      if (get().demo.index >= fixture.length) get().restart();
      startDemo();
    },
    pause: () => {
      clearTimer();
      set((s) => ({ demo: { ...s.demo, playing: false } }));
    },
    restart: () => {
      clearTimer();
      useSession.getState().reset();
      set((s) => ({ demo: { ...s.demo, playing: false, started: false, index: 0 } }));
      primeDemo();
    },
    setSpeed: (speed) => {
      set((s) => ({ demo: { ...s.demo, speed: SPEEDS.includes(speed) ? speed : 1 } }));
      if (get().demo.playing) scheduleNext();
    },
    seekToMarker: (marker) => {
      const target = fixture.findIndex((f) => f.marker === marker);
      if (target < 0 || target <= get().demo.index) return;
      clearTimer();
      fastForward(target);
      // The marked event plays right away (with its animation); the story continues from there.
      useSession.getState().apply(fixture[target].event);
      set((s) => ({ demo: { ...s.demo, index: target + 1 } }));
      startDemo();
    },
    skipToEnd: () => {
      clearTimer();
      fastForward(fixture.length);
      set((s) => ({ demo: { ...s.demo, playing: false } }));
    },

    sendPrompt: async (text) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      const { mode, demo } = get();
      if (mode === "demo") {
        const omniverse = await recordedOmniverse(trimmed);
        if (omniverse) {
          const session = useSession.getState();
          session.addLocalUserMessage(trimmed);
          if (session.product !== "drone" || session.cad?.script_url) {
            session.apply({ type: "chat", role: "agent", text: "Omniverse hover tests and Crazyflie training support the drone only. Use the Simulation tab for the gripper lift-and-shake test." });
            return;
          }
          session.apply(omniverse);
          session.apply({ type: "chat", role: "agent", text: "Here is the recorded Omniverse demo. Its values and learning curve are illustrative; this request has not been simulated." });
          useUi.getState().setTab("omniverse");
          return;
        }
        const open = Object.values(useSession.getState().questions).find((q) => q.status === "open");
        const answer = open ? matchAnswer(trimmed, open) : null;
        if (open && answer) {
          useSession.getState().addLocalUserMessage(trimmed);
          void get().answerQuestion(open.id, answer);
          return;
        }
        if (!demo.started) {
          // The recording starts with its own prompt; this is what the presenter asked for.
          startDemo();
          return;
        }
        const session = useSession.getState();
        session.addLocalUserMessage(trimmed);
        setTimeout(() => {
          session.apply({
            type: "chat",
            role: "agent",
            text: "This is a recorded session. Switch to **Live** up top and I will build with you.",
          });
        }, 700);
        return;
      }
      useSession.getState().addLocalUserMessage(trimmed);
      try {
        const res = await fetch(apiUrl("/api/prompt"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: trimmed }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (err) {
        set({ notice: `Backend unreachable (${err instanceof Error ? err.message : "error"}). Is agent/ running on port 8100?` });
      }
    },

    setCadParams: async (params) => {
      if (get().mode === "demo") {
        set({ notice: "CAD does not recompute in the recorded session. Switch to Live." });
        return false;
      }
      try {
        const res = await fetch(apiUrl("/api/cad/params"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(params),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return true;
      } catch (err) {
        set({ notice: `CAD parameters did not arrive (${err instanceof Error ? err.message : "error"}).` });
        return false;
      }
    },

    openInFreecad: async () => {
      if (get().mode === "demo") {
        set({ notice: "FreeCAD opens only in live mode, on the Mac that runs the backend." });
        return;
      }
      try {
        const res = await fetch(apiUrl("/api/cad/open"), { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (err) {
        set({ notice: `FreeCAD could not be opened (${err instanceof Error ? err.message : "error"}).` });
      }
    },

    resetSession: async () => {
      if (get().mode === "demo") {
        get().restart();
        return;
      }
      // Archives the chat and clears now; the server's reset marker on the stream follows.
      useSession.getState().reset();
      try {
        const res = await fetch(apiUrl("/api/reset"), { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch {
        set({ notice: "Reset did not arrive: backend unreachable." });
      }
    },

    toggleTask: async (id, done) => {
      const session = useSession.getState();
      const tasks = session.tasks;
      if (!tasks) return;
      const local = () =>
        session.apply({ ...tasks, items: tasks.items.map((t) => (t.id === id ? { ...t, done } : t)) });
      if (get().mode === "demo") return local();
      try {
        const res = await fetch(apiUrl(`/api/tasks/${encodeURIComponent(id)}`), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ done }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (err) {
        set({ notice: `Task was not saved (${err instanceof Error ? err.message : "error"}).` });
      }
    },

    meetingWebhook: async (event, meeting) => {
      if (get().mode === "demo") {
        // The recording carries its own review; both buttons jump there.
        if (!get().demo.started) startDemo();
        get().seekToMarker("review");
        return;
      }
      try {
        const res = await fetch(apiUrl("/api/webhooks/jamie"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ event: `meeting.${event}`, meeting_id: meeting.id, title: meeting.title }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (err) {
        set({ notice: `Jamie event did not arrive (${err instanceof Error ? err.message : "error"}).` });
      }
    },

    answerQuestion: async (id, answerId) => {
      const session = useSession.getState();
      const q = session.questions[id];
      if (!q || q.status === "answered") return;
      if (get().mode === "demo") {
        session.apply({ ...q, status: "answered", answer_id: answerId });
        return;
      }
      try {
        const res = await fetch(apiUrl("/api/answer"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id, answer_id: answerId }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (err) {
        set({ notice: `Answer did not arrive (${err instanceof Error ? err.message : "error"}).` });
      }
    },

    dismissNotice: () => set({ notice: null }),
  };
});

/** Picks the start mode: URL (?demo / ?live) wins, then the remembered choice, else Live. */
export function initSource() {
  const params = new URLSearchParams(window.location.search);
  const source = useSource.getState();
  const speed = Number(params.get("speed"));
  if (speed) source.setSpeed(speed);

  const urlMode: SourceMode | null = params.has("live") ? "live" : params.has("demo") ? "demo" : null;
  source.setMode(urlMode ?? storedMode() ?? "live");

  if (useSource.getState().mode === "demo") {
    const seek = params.get("seek");
    if (params.has("end")) useSource.getState().skipToEnd();
    else if (seek) useSource.getState().seekToMarker(seek);
    else if (params.has("autoplay")) useSource.getState().play();
  }
}

