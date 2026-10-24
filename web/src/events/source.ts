// Where events come from: the live backend over SSE, or the recorded demo fixture.
// The UI only ever reads the session store, so both sources look the same to it.
import { create } from "zustand";
import { DEMO_FIXTURE, type FixtureItem } from "./fixture";
import { useSession } from "./store";
import { parseEvent, type QuestionEvent } from "./types";
import { apiUrl } from "../lib/api";
import { useUi } from "../lib/ui";
import { loadVoiceCapabilities } from "../lib/voice";
import { handleSay, unlockAudio } from "../lib/speech";
import { recordedOmniverse } from "./omniverse";

export type SourceMode = "live" | "demo";

/** A library item a build can start from (GET /api/library): a reference build or a saved project. */
export interface ReferenceBuild {
  id: string;
  name: string;
  summary: string;
  kind: "reference" | "project";
  source: "code" | "registry" | "saved";
  product: string;
  printed: number;
  bought: number;
  requirements: number | null;
  thumbnail_url: string | null;
  saved_at: string | null;
}
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
  /** What the live backend runs: Claude with a key, or the scripted mock without one. */
  backend: "claude" | "mock" | null;
  references: ReferenceBuild[];
  /** Starts a fresh build from a reference; the chat then changes it. */
  startReference: (id: string) => Promise<void>;
  /** Makes an old version current again by rebuilding it as a new version. */
  restoreVersion: (n: number) => Promise<void>;
  /** Opens a community project on a fresh bench as a remix. */
  startRemix: (id: string) => Promise<void>;
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
  /** Starts a new product from a photo of a hand sketch, with what the user typed next to it. */
  sendSketch: (image: Blob, note?: string) => Promise<void>;
  /** Sends the sample phone stand sketch the backend ships with. */
  sendSampleSketch: () => Promise<void>;
  /** Changes CAD parameters; the backend recomputes and answers with a new `cad` event. */
  setCadParams: (params: Record<string, number>) => Promise<boolean>;
  /** Opens the current part in the FreeCAD app on this Mac. */
  openInFreecad: () => Promise<void>;
  /** Run test or Rebuild, pressed by a person (POST /api/control). */
  pressControl: (control: "run:test" | "run:rebuild") => Promise<void>;
  resetSession: () => Promise<void>;
  /** Ticks or unticks "bestellt" on an order task; the backend mirrors it to Jamie. */
  toggleTask: (id: string, done: boolean) => Promise<void>;
  /** Stands in for Jamie's webhook: marks a meeting as running, or as ended (which rebuilds). */
  meetingWebhook: (event: "started" | "ended", meeting: { id: string; title: string }) => Promise<void>;
  /** Answers Bolzen's question (a contradiction between meetings) with one of its options. */
  answerQuestion: (id: string, answerId: string) => Promise<void>;
  dismissNotice: () => void;
}

const SPEEDS = [1, 2, 4];

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

// The watchdog: a step that stays running with no event for this long gets one notice, so a quiet tool never looks frozen.
const STALL_MS = 45_000;
let lastEventAt = Date.now();
let stallNoticed = false;
let watchdog: ReturnType<typeof setInterval> | null = null;

function watchStalls() {
  if (watchdog) return;
  watchdog = setInterval(() => {
    if (stallNoticed || Date.now() - lastEventAt < STALL_MS) return;
    const running = Object.values(useSession.getState().steps).find((step) => step.status === "running");
    if (!running) return;
    stallNoticed = true;
    useSource.setState({ notice: `Mechanic is still working on ${running.label}. A stuck tool stops on its own time limit with a message.` });
  }, 5000);
}

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
  watchStalls();
  // The backlog a (re)connect replays is applied without animations or Bolzen speaking it again.
  let replaying = true;
  es.onopen = () => {
    // EventSource reconnects on its own too; each new connection starts with a backlog.
    replaying = true;
    onStatus("open");
    void probeBackend().then((backend) => useSource.setState({ backend }));
    void loadReferences().then((references) => useSource.setState({ references }));
    void loadVoiceCapabilities().then((caps) => useUi.setState({ stt: caps.stt }));
  };
  es.onerror = () => {
    if (es.readyState !== EventSource.CLOSED) return onStatus("connecting");
    onStatus("error");
    if (eventSource === es) retry = setTimeout(() => openLive(onStatus), RETRY_MS);
  };
  es.onmessage = (msg) => {
    lastEventAt = Date.now();
    stallNoticed = false;
    const ev = parseEvent(msg.data);
    if (!ev) return;
    if (ev.type === "replayed") {
      replaying = false;
      return;
    }
    if (ev.type === "say") {
      const ui = useUi.getState();
      if (!replaying) handleSay(ev, { voiceOn: ui.voiceOn, userTalking: ui.userTalking });
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

/** GET /api/health: "claude" or "mock" when the backend answers, else null. */
async function probeBackend(timeoutMs = 2500): Promise<"claude" | "mock" | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(apiUrl("/api/health"), { signal: controller.signal });
    if (!res.ok) return null;
    const body = (await res.json()) as { mode?: string };
    return body.mode === "claude" ? "claude" : "mock";
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

async function loadReferences(): Promise<ReferenceBuild[]> {
  try {
    const res = await fetch(apiUrl("/api/library"));
    if (!res.ok) return [];
    const body = (await res.json()) as { items?: ReferenceBuild[] };
    return body.items ?? [];
  } catch {
    return [];
  }
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
    // Playing is a click (or a URL), the moment the browser lets Mechanic's recorded voice make sound.
    unlockAudio();
    set((s) => ({ demo: { ...s.demo, started: true, playing: true } }));
    scheduleNext();
  };

  return {
    mode: "live",
    live: "idle",
    backend: null,
    references: [],
    demo: { playing: false, started: false, speed: 1, index: 0, total: fixture.length },
    notice: null,

    setMode: (mode) => {
      clearTimer();
      closeLive();
      useSession.getState().reset();
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

    sendSketch: async (image, note = "") => {
      if (get().mode === "demo") {
        set({ notice: "Sketches build in the live session. Switch to Live." });
        return;
      }
      try {
        const dataUrl = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = () => reject(reader.error ?? new Error("unreadable file"));
          reader.readAsDataURL(image);
        });
        const res = await fetch(apiUrl("/api/sketch"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ image_base64: dataUrl, media_type: image.type, note: note.trim() }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail ?? `HTTP ${res.status}`);
        }
      } catch (err) {
        set({ notice: `The sketch did not go through (${err instanceof Error ? err.message : "error"}).` });
      }
    },

    sendSampleSketch: async () => {
      try {
        const res = await fetch(apiUrl("/api/sketch/sample"));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await get().sendSketch(await res.blob());
      } catch (err) {
        set({ notice: `The sample sketch did not load (${err instanceof Error ? err.message : "error"}).` });
      }
    },

    startReference: async (id) => {
      if (get().mode === "demo") return;
      try {
        const res = await fetch(apiUrl(`/api/library/${encodeURIComponent(id)}/open`), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (err) {
        set({ notice: `The reference did not start (${err instanceof Error ? err.message : "error"}).` });
      }
    },

    restoreVersion: async (n) => {
      if (get().mode === "demo") return;
      try {
        const res = await fetch(apiUrl(`/api/versions/${n}/restore`), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (res.status === 409) {
          set({ notice: "Mechanic is building. Restore when the build is done." });
          return;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (err) {
        set({ notice: `The restore did not start (${err instanceof Error ? err.message : "error"}).` });
      }
    },

    startRemix: async (id) => {
      if (get().mode === "demo") return;
      try {
        const res = await fetch(apiUrl(`/api/community/${encodeURIComponent(id)}/remix`), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } catch (err) {
        set({ notice: `The remix did not start (${err instanceof Error ? err.message : "error"}).` });
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

    pressControl: async (control) => {
      if (get().mode === "demo") {
        set({ notice: "Tests and rebuilds run only in live mode." });
        return;
      }
      try {
        const res = await fetch(apiUrl("/api/control"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ control }) });
        const body = (await res.json()) as { ok?: boolean; error?: string };
        if (!res.ok || body.ok === false) throw new Error(body.error ?? `HTTP ${res.status}`);
      } catch (err) {
        set({ notice: err instanceof Error ? err.message : "The run could not start." });
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

/**
 * Picks the start mode: the URL (?demo / ?live) wins; otherwise the live backend when it
 * answers, with an empty bench. The recording only plays without a backend, and says so.
 */
export function initSource() {
  const params = new URLSearchParams(window.location.search);
  const source = useSource.getState();
  const speed = Number(params.get("speed"));
  if (speed) source.setSpeed(speed);

  const urlMode: SourceMode | null = params.has("live") ? "live" : params.has("demo") ? "demo" : null;
  if (urlMode) {
    source.setMode(urlMode);
  } else {
    source.setMode("live");
    void probeBackend().then((backend) => {
      if (backend) return useSource.setState({ backend });
      if (useSource.getState().live === "open" || useSource.getState().demo.started) return;
      useSource.getState().setMode("demo");
      useSource.setState({ notice: "No backend running: this is the recorded demo, not a live build." });
    });
  }

  // A share link (?project=<id>) rebuilds that library entry once, then drops the parameter so a reload does not rebuild again.
  const project = params.get("project");
  if (project && !params.has("demo")) {
    void probeBackend().then(async (backend) => {
      if (!backend) return;
      params.delete("project");
      const rest = params.toString();
      window.history.replaceState(null, "", `${window.location.pathname}${rest ? `?${rest}` : ""}${window.location.hash}`);
      const known = await loadReferences();
      if (!known.some((r) => r.id === project)) return useSource.setState({ notice: "That project is not in the library." });
      void useSource.getState().startReference(project);
    });
  }

  if (useSource.getState().mode === "demo") {
    const seek = params.get("seek");
    if (params.has("end")) useSource.getState().skipToEnd();
    else if (seek) useSource.getState().seekToMarker(seek);
    else if (params.has("autoplay")) useSource.getState().play();
  }
}

