// Where events come from: the live backend over SSE.
// The UI only ever reads the session store.
import { create } from "zustand";
import { useSession } from "./store";
import { parseEvent } from "./types";
import { accessToken, apiFetch, apiStreamUrl, errorDetail, onAccessEvents, setAccessToken } from "../lib/api";
import { useUi } from "../lib/ui";
import { loadVoiceCapabilities } from "../lib/voice";

export type SourceMode = "live";

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
/** Whether the app may show the bench: checking the backend, backend offline, access code needed, or in. */
export type AccessStatus = "checking" | "offline" | "locked" | "open";

interface SourceState {
  mode: SourceMode;
  live: LiveStatus;
  access: AccessStatus;
  /** Trades the access code for a session; resolves to an error message, or null when it worked. */
  unlock: (code: string) => Promise<string | null>;
  /** What the live backend runs: Claude with a key, or the scripted mock without one. */
  backend: "claude" | "mock" | null;
  references: ReferenceBuild[];
  /** Starts a fresh build from a reference; the chat then changes it. */
  startReference: (id: string) => Promise<void>;
  /** Makes an old version current again by rebuilding it as a new version. */
  restoreVersion: (n: number) => Promise<void>;
  /** Builds one design optimizer variant as the next version. */
  applyVariant: (id: string, variant: string) => Promise<boolean>;
  /** Opens a community project on a fresh bench as a remix. */
  startRemix: (id: string) => Promise<void>;
  notice: string | null;
  setMode: (mode: SourceMode) => void;
  /** voice: the text is a spoken turn, shown with a mic marker. */
  sendPrompt: (text: string, voice?: boolean) => Promise<void>;
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
  const es = new EventSource(apiStreamUrl("/api/events"));
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
    if (eventSource !== es) return;
    retry = setTimeout(() => openLive(onStatus), RETRY_MS);
    // A stream refused with 401 means the session ended; apiFetch then locks the app (and closes this).
    void apiFetch("/api/access").catch(() => undefined);
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
    useSession.getState().apply(ev, { instant: replaying });
  };
}
function closeLive() {
  if (retry) clearTimeout(retry);
  retry = null;
  eventSource?.close();
  eventSource = null;
}

interface Health {
  backend: "claude" | "mock";
  /** "required" when the backend runs with ANYBUILD_ACCESS_CODE. */
  access: "open" | "required";
}

/** GET /api/health, or null when the backend does not answer. */
async function fetchHealth(timeoutMs = 6000): Promise<Health | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await apiFetch("/api/health", { signal: controller.signal });
    if (!res.ok) return null;
    const body = (await res.json()) as { mode?: string; access?: string };
    return { backend: body.mode === "claude" ? "claude" : "mock", access: body.access === "required" ? "required" : "open" };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

async function probeBackend(): Promise<"claude" | "mock" | null> {
  return (await fetchHealth())?.backend ?? null;
}

/** Throws with the backend's own message (e.g. a rate limit) when a call failed. */
async function ensureOk(res: Response): Promise<void> {
  if (res.ok) return;
  const err = new Error(await errorDetail(res)) as Error & { status?: number };
  err.status = res.status;
  throw err;
}

function notify(notice: string | null) {
  if (notice) useSource.setState({ notice });
}

/** The notice for a failed call; null when the access screen or a rate-limit notice already says it. */
function failure(what: string, err: unknown): string | null {
  const status = (err as { status?: number })?.status;
  if (status === 401 || status === 429) return null;
  return `${what} (${err instanceof Error ? err.message : "error"}).`;
}

async function loadReferences(): Promise<ReferenceBuild[]> {
  try {
    const res = await apiFetch("/api/library");
    if (!res.ok) return [];
    const body = (await res.json()) as { items?: ReferenceBuild[] };
    return body.items ?? [];
  } catch {
    return [];
  }
}

export const useSource = create<SourceState>((set, get) => {
  return {
    mode: "live",
    live: "idle",
    access: "checking",
    backend: null,
    references: [],
    notice: null,

    setMode: (mode) => {
      closeLive();
      useSession.getState().reset();
      set({ mode, live: "idle", notice: null });
      openLive((live) => set({ live }));
    },

    sendPrompt: async (text, voice = false) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      useSession.getState().addLocalUserMessage(trimmed, voice);
      try {
        const res = await apiFetch("/api/prompt", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: trimmed, voice }),
        });
        await ensureOk(res);
      } catch (err) {
        notify(failure("Your message did not reach AnyBuild", err));
      }
    },

    sendSketch: async (image, note = "") => {
      try {
        const dataUrl = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result));
          reader.onerror = () => reject(reader.error ?? new Error("unreadable file"));
          reader.readAsDataURL(image);
        });
        const res = await apiFetch("/api/sketch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ image_base64: dataUrl, media_type: image.type, note: note.trim() }),
        });
        await ensureOk(res);
      } catch (err) {
        notify(failure("The sketch did not go through", err));
      }
    },

    sendSampleSketch: async () => {
      try {
        const res = await apiFetch("/api/sketch/sample");
        await ensureOk(res);
        await get().sendSketch(await res.blob());
      } catch (err) {
        notify(failure("The sample sketch did not load", err));
      }
    },

    startReference: async (id) => {
      try {
        const res = await apiFetch(`/api/library/${encodeURIComponent(id)}/open`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        await ensureOk(res);
      } catch (err) {
        notify(failure("The reference did not start", err));
      }
    },

    restoreVersion: async (n) => {
      try {
        const res = await apiFetch(`/api/versions/${n}/restore`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        });
        if (res.status === 409) {
          set({ notice: "Mechanic is building. Restore when the build is done." });
          return;
        }
        await ensureOk(res);
      } catch (err) {
        notify(failure("The restore did not start", err));
      }
    },

    applyVariant: async (id, variant) => {
      try {
        const res = await apiFetch("/api/optimize/apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id, variant }),
        });
        if (res.status === 409) {
          set({ notice: "Mechanic is building. Pick a variant when the build is done." });
          return false;
        }
        await ensureOk(res);
        return true;
      } catch (err) {
        notify(failure("The variant did not start", err));
        return false;
      }
    },

    startRemix: async (id) => {
      try {
        const res = await apiFetch(`/api/community/${encodeURIComponent(id)}/remix`, {
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
      try {
        const res = await apiFetch("/api/cad/params", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(params),
        });
        await ensureOk(res);
        return true;
      } catch (err) {
        notify(failure("CAD parameters did not arrive", err));
        return false;
      }
    },

    openInFreecad: async () => {
      try {
        const res = await apiFetch("/api/cad/open", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        await ensureOk(res);
      } catch (err) {
        notify(failure("FreeCAD could not be opened", err));
      }
    },

    pressControl: async (control) => {
      try {
        const res = await apiFetch("/api/control", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ control }) });
        // The access screen or a rate-limit notice already says why.
        if (res.status === 401 || res.status === 429) return;
        const body = (await res.json()) as { ok?: boolean; error?: string };
        if (!res.ok || body.ok === false) throw new Error(body.error ?? `HTTP ${res.status}`);
      } catch (err) {
        set({ notice: err instanceof Error ? err.message : "The run could not start." });
      }
    },

    resetSession: async () => {
      // Archives the chat and clears now; the server's reset marker on the stream follows.
      useSession.getState().reset();
      try {
        const res = await apiFetch("/api/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        await ensureOk(res);
      } catch (err) {
        notify(failure("Reset did not arrive", err));
      }
    },

    toggleTask: async (id, done) => {
      const session = useSession.getState();
      const tasks = session.tasks;
      if (!tasks) return;
      try {
        const res = await apiFetch(`/api/tasks/${encodeURIComponent(id)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ done }),
        });
        await ensureOk(res);
      } catch (err) {
        notify(failure("Task was not saved", err));
      }
    },

    meetingWebhook: async (event, meeting) => {
      try {
        const res = await apiFetch("/api/webhooks/jamie", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ event: `meeting.${event}`, meeting_id: meeting.id, title: meeting.title }),
        });
        await ensureOk(res);
      } catch (err) {
        notify(failure("Jamie event did not arrive", err));
      }
    },

    answerQuestion: async (id, answerId) => {
      const session = useSession.getState();
      const q = session.questions[id];
      if (!q || q.status === "answered") return;
      try {
        const res = await apiFetch("/api/answer", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id, answer_id: answerId }),
        });
        await ensureOk(res);
      } catch (err) {
        notify(failure("Answer did not arrive", err));
      }
    },

    unlock: async (code) => {
      try {
        const res = await apiFetch("/api/access", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: code.trim() }),
        });
        if (!res.ok) return await errorDetail(res);
        const body = (await res.json()) as { token?: string };
        setAccessToken(body.token ?? null);
      } catch {
        return "Live backend offline, try again shortly.";
      }
      openBench();
      return null;
    },

    dismissNotice: () => set({ notice: null }),
  };
});

const OFFLINE_RETRY_MS = 5000;
let offlineRetry: ReturnType<typeof setTimeout> | null = null;
let sharedProject: string | null = null;

/** Opens the bench in live mode, then the shared project of a ?project=<id> link, once. */
function openBench() {
  useSource.setState({ access: "open" });
  useSource.getState().setMode("live");
  const project = sharedProject;
  if (!project) return;
  sharedProject = null;
  // Drops the parameter, so a reload does not rebuild again.
  const params = new URLSearchParams(window.location.search);
  params.delete("project");
  const rest = params.toString();
  window.history.replaceState(null, "", `${window.location.pathname}${rest ? `?${rest}` : ""}${window.location.hash}`);
  void loadReferences().then((known) => {
    if (!known.some((r) => r.id === project)) return useSource.setState({ notice: "That project is not in the library." });
    void useSource.getState().startReference(project);
  });
}

/**
 * Checks the backend before the bench opens: offline (retried on its own), access code
 * needed, or straight in.
 */
async function enterLive() {
  if (offlineRetry) clearTimeout(offlineRetry);
  offlineRetry = null;
  const health = await fetchHealth();
  if (!health) {
    useSource.setState({ access: "offline" });
    offlineRetry = setTimeout(() => void enterLive(), OFFLINE_RETRY_MS);
    return;
  }
  useSource.setState({ backend: health.backend });
  if (health.access === "required") {
    if (!accessToken()) return useSource.setState({ access: "locked" });
    // A stored session may have expired, or the code changed; apiFetch locks the app on 401.
    const res = await apiFetch("/api/access").catch(() => null);
    if (!res) return void enterLive();
    if (!res.ok) return useSource.setState({ access: "locked" });
  }
  openBench();
}

/** Opens the bench against the live backend. */
export function initSource() {
  const params = new URLSearchParams(window.location.search);

  onAccessEvents({
    onLocked: () => {
      closeLive();
      useSource.setState({ access: "locked", live: "idle" });
    },
    onLimited: (message) => useSource.setState({ notice: message }),
  });

  // A share link (?project=<id>) rebuilds that library entry once the bench is open.
  sharedProject = params.get("project");
  void enterLive();
}
