// Listening in the side chat. The voice conversation (Talk) is Gemini Live only
// (lib/geminiLive.ts); this file opens its microphone. Push-to-talk dictation uses
// Reson8's Realtime endpoint while a key is held, with a short-lived token from the
// backend and a phrase list for our part and tool names; without a Reson8 key the
// browser's own speech recognition does the same. Mechanic's speaking lives in speech.ts.
import { apiFetch } from "./api";
import { stopSpeaking } from "./speech";

export type SttMode = "reson8" | "browser" | "none";

interface Capabilities {
  stt: SttMode;
  realtimeUrl: string;
  turnsUrl: string;
  language: string;
  phrases: string[];
  customModelId: string | null;
  geminiLive: boolean;
}

const BROWSER_STT = typeof window !== "undefined" && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

let caps: Capabilities = {
  stt: BROWSER_STT ? "browser" : "none",
  realtimeUrl: "wss://api.reson8.dev/v1/speech-to-text/realtime",
  turnsUrl: "wss://api.reson8.dev/v1/speech-to-text/turns",
  language: "en",
  phrases: [],
  customModelId: null,
  geminiLive: false,
};

/** Asks the backend which voice services have keys. */
export async function loadVoiceCapabilities(): Promise<Capabilities> {
  try {
    const res = await apiFetch("/api/voice");
    if (res.ok) {
      const body = await res.json();
      caps = {
        stt: body.stt === "reson8" ? "reson8" : BROWSER_STT ? "browser" : "none",
        realtimeUrl: body.realtime_url || caps.realtimeUrl,
        turnsUrl: body.turns_url || caps.turnsUrl,
        language: body.language || "en",
        phrases: Array.isArray(body.phrases) ? body.phrases.filter((p: unknown) => typeof p === "string") : [],
        customModelId: typeof body.custom_model_id === "string" ? body.custom_model_id : null,
        geminiLive: body.gemini_live === true,
      };
    }
  } catch {
    // No backend: Mechanic stays silent and his text is the caption.
  }
  return caps;
}

export const voiceCapabilities = () => caps;

// --- microphone ---------------------------------------------------------------------

// Downsamples the microphone to 16 kHz mono PCM s16le and posts 100 ms chunks.
const WORKLET = `
class Pcm16 extends AudioWorkletProcessor {
  constructor() { super(); this.ratio = sampleRate / 16000; this.pos = 0; this.out = []; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    while (this.pos < ch.length) {
      const i = Math.floor(this.pos);
      const s = Math.max(-1, Math.min(1, (ch[i] + (ch[i + 1] ?? ch[i])) / 2));
      this.out.push(s < 0 ? s * 0x8000 : s * 0x7fff);
      this.pos += this.ratio;
    }
    this.pos -= ch.length;
    if (this.out.length >= 1600) {
      const chunk = Int16Array.from(this.out);
      this.out = [];
      this.port.postMessage(chunk.buffer, [chunk.buffer]);
    }
    return true;
  }
}
registerProcessor("pcm16", Pcm16);
`;

interface Mic {
  close: () => void;
}

/** Opens the microphone (with echo cancellation, so Mechanic's own voice is mostly kept out) and streams PCM chunks. */
export async function openMic(onChunk: (chunk: ArrayBuffer) => void, sharedContext?: AudioContext): Promise<Mic> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  let ctx: AudioContext | null = sharedContext ?? null;
  const close = () => {
    stream.getTracks().forEach((t) => t.stop());
    if (!sharedContext) void ctx?.close();
  };
  try {
    ctx ??= new AudioContext();
    await ctx.resume();
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    try {
      await ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, "pcm16");
    node.port.onmessage = (e) => onChunk(e.data as ArrayBuffer);
    source.connect(node);
    // Keep the worklet in the active graph; its output is silence.
    node.connect(ctx.destination);
    return {
      close: () => {
        source.disconnect();
        node.disconnect();
        close();
      },
    };
  } catch (err) {
    close();
    throw err;
  }
}

async function reson8Token(): Promise<string> {
  const res = await apiFetch("/api/voice/token", { method: "POST" });
  if (!res.ok) throw new Error(`Token HTTP ${res.status}`);
  const { access_token: token } = await res.json();
  return token;
}

function connect(url: string, token: string): Promise<WebSocket> {
  const socket = new WebSocket(url, ["bearer", token]);
  socket.binaryType = "arraybuffer";
  return new Promise<WebSocket>((resolve, reject) => {
    const timer = setTimeout(() => {
      socket.close();
      reject(new Error("no connection"));
    }, 5000);
    socket.onopen = () => {
      clearTimeout(timer);
      socket.onclose = null;
      resolve(socket);
    };
    socket.onclose = (e) => {
      clearTimeout(timer);
      // 429: Reson8 allows only so many open sessions per account.
      reject(new Error(e.reason || "connection refused"));
    };
  });
}

/** Query parameters both Reson8 endpoints share: raw 16 kHz PCM, the language, and our vocabulary. */
function baseParams(): URLSearchParams {
  const params = new URLSearchParams({ encoding: "pcm_s16le", sample_rate: "16000", channels: "1", language: caps.language });
  if (caps.customModelId) params.set("custom_model_id", caps.customModelId);
  else if (caps.phrases.length) params.set("phrases", caps.phrases.join(","));
  return params;
}

function parse(data: unknown): Record<string, unknown> | null {
  if (typeof data !== "string") return null;
  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}

/** A running Gemini Live voice conversation (lib/geminiLive.ts). */
export interface HandsFree {
  stop: () => void;
}

// --- push-to-talk ------------------------------------------------------------------------

export interface Listener {
  /** Stops listening and resolves with the final transcript. */
  stop: () => Promise<string>;
}

export interface ListenHandlers {
  onInterim: (text: string) => void;
  onError: (message: string) => void;
}

export async function startListening(handlers: ListenHandlers): Promise<Listener | null> {
  stopSpeaking();
  if (caps.stt === "reson8") {
    try {
      return await listenReson8(handlers);
    } catch (err) {
      handlers.onError(`Reson8 is unreachable (${err instanceof Error ? err.message : "error"}). The browser is listening.`);
    }
  }
  if (BROWSER_STT) return listenBrowser(handlers);
  handlers.onError("This browser has no speech recognition. Type it instead.");
  return null;
}

async function listenReson8({ onInterim, onError }: ListenHandlers): Promise<Listener> {
  const params = baseParams();
  params.set("include_interim", "true");
  const socket = await connect(`${caps.realtimeUrl}?${params}`, await reson8Token());
  const finals: string[] = [];
  let interim = "";
  let flushed: (() => void) | null = null;
  socket.onmessage = (msg) => {
    const data = parse(msg.data);
    if (!data) return;
    if (data.type === "transcript" && typeof data.text === "string") {
      if (data.is_final === false) {
        interim = data.text;
      } else {
        if (data.text.trim()) finals.push(data.text.trim());
        interim = "";
      }
      onInterim([...finals, interim].filter(Boolean).join(" "));
    } else if (data.type === "flush_confirmation") {
      flushed?.();
    }
  };
  socket.onerror = () => onError("The Reson8 connection dropped.");
  let mic: Mic;
  try {
    mic = await openMic((chunk) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(chunk);
    });
  } catch (err) {
    socket.close(1000);
    throw err;
  }

  return {
    stop: async () => {
      mic.close();
      if (socket.readyState === WebSocket.OPEN) {
        // Ask for the last words, then close once Reson8 confirms (or after 2 s).
        await new Promise<void>((resolve) => {
          flushed = resolve;
          socket.send(JSON.stringify({ type: "flush_request", id: "ptt" }));
          setTimeout(resolve, 2000);
        });
        socket.close(1000);
      }
      return [...finals, interim].filter(Boolean).join(" ").trim();
    },
  };
}

// --- browser speech recognition -------------------------------------------------------------

interface RecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

function newRecognition(): RecognitionLike {
  const w = window as unknown as { SpeechRecognition?: new () => RecognitionLike; webkitSpeechRecognition?: new () => RecognitionLike };
  const Ctor = (w.SpeechRecognition ?? w.webkitSpeechRecognition)!;
  const rec = new Ctor();
  rec.lang = "en-US";
  rec.interimResults = true;
  rec.continuous = true;
  return rec;
}

function listenBrowser({ onInterim, onError }: ListenHandlers): Listener {
  const rec = newRecognition();
  let text = "";
  let ended: (() => void) | null = null;
  rec.onresult = (e) => {
    let finals = "";
    let interim = "";
    for (let i = 0; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) finals += r[0].transcript;
      else interim += r[0].transcript;
    }
    text = `${finals} ${interim}`.trim();
    onInterim(text);
  };
  rec.onerror = (e) => {
    if (e.error !== "aborted" && e.error !== "no-speech") onError(`Speech recognition: ${e.error}`);
  };
  rec.onend = () => ended?.();
  rec.start();
  return {
    stop: async () => {
      await new Promise<void>((resolve) => {
        ended = resolve;
        rec.stop();
        setTimeout(resolve, 1200);
      });
      return text.trim();
    },
  };
}
