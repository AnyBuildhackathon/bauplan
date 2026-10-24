// Voice in the side chat. Listening: Reson8 realtime speech-to-text when the backend
// has a key (it hands out a short-lived token), else the browser's own speech
// recognition. Speaking: ElevenLabs through the backend when it has a key, else the
// browser's speech synthesis. Without any of these the chat still takes typing.
import { apiUrl } from "./api";

export type SttMode = "reson8" | "browser" | "none";
export type TtsMode = "elevenlabs" | "browser" | "none";

interface Capabilities {
  stt: SttMode;
  tts: TtsMode;
  realtimeUrl: string;
  language: string;
}

const BROWSER_STT = typeof window !== "undefined" && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);
const BROWSER_TTS = typeof window !== "undefined" && "speechSynthesis" in window;

let caps: Capabilities = {
  stt: BROWSER_STT ? "browser" : "none",
  tts: BROWSER_TTS ? "browser" : "none",
  realtimeUrl: "wss://api.reson8.dev/v1/speech-to-text/realtime",
  language: "en",
};

/** Asks the backend which voice services have keys. The demo recording keeps the browser's own. */
export async function loadVoiceCapabilities(): Promise<Capabilities> {
  try {
    const res = await fetch(apiUrl("/api/voice"));
    if (res.ok) {
      const body = await res.json();
      caps = {
        stt: body.stt === "reson8" ? "reson8" : BROWSER_STT ? "browser" : "none",
        tts: body.tts === "elevenlabs" ? "elevenlabs" : BROWSER_TTS ? "browser" : "none",
        realtimeUrl: body.realtime_url || caps.realtimeUrl,
        language: body.language || "en",
      };
    }
  } catch {
    // No backend: the browser's own speech stays.
  }
  return caps;
}

export const voiceCapabilities = () => caps;

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

// --- Reson8 -------------------------------------------------------------------------

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

async function listenReson8({ onInterim, onError }: ListenHandlers): Promise<Listener> {
  const tokenRes = await fetch(apiUrl("/api/voice/token"), { method: "POST" });
  if (!tokenRes.ok) throw new Error(`Token HTTP ${tokenRes.status}`);
  const { access_token: token } = await tokenRes.json();
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const params = new URLSearchParams({
    encoding: "pcm_s16le",
    sample_rate: "16000",
    channels: "1",
    language: caps.language,
    include_interim: "true",
  });
  let ws: WebSocket | null = null;
  let ctx: AudioContext | null = null;
  const finals: string[] = [];
  let interim = "";
  let flushed: (() => void) | null = null;
  // Anything that fails during setup releases the microphone, the audio graph and the socket.
  const release = () => {
    stream.getTracks().forEach((t) => t.stop());
    void ctx?.close();
    if (ws && ws.readyState <= WebSocket.OPEN) ws.close(1000);
  };

  let source: MediaStreamAudioSourceNode;
  let node: AudioWorkletNode;
  try {
    const socket = new WebSocket(`${caps.realtimeUrl}?${params}`, ["bearer", token]);
    ws = socket;
    socket.binaryType = "arraybuffer";
    socket.onmessage = (msg) => {
      if (typeof msg.data !== "string") return;
      let data: { type?: string; text?: string; is_final?: boolean };
      try {
        data = JSON.parse(msg.data);
      } catch {
        return;
      }
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
    socket.onerror = () => onError("Reson8-Verbindung abgebrochen.");
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("keine Verbindung")), 5000);
      socket.onopen = () => {
        clearTimeout(timer);
        resolve();
      };
      socket.onclose = () => {
        clearTimeout(timer);
        reject(new Error("Verbindung abgelehnt"));
      };
    });
    socket.onclose = null;

    ctx = new AudioContext();
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    try {
      await ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    source = ctx.createMediaStreamSource(stream);
    node = new AudioWorkletNode(ctx, "pcm16");
    node.port.onmessage = (e) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(e.data as ArrayBuffer);
    };
    source.connect(node);
  } catch (err) {
    release();
    throw err;
  }
  const socket = ws;

  return {
    stop: async () => {
      source.disconnect();
      node.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      void ctx?.close();
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

function listenBrowser({ onInterim, onError }: ListenHandlers): Listener {
  const w = window as unknown as { SpeechRecognition?: new () => RecognitionLike; webkitSpeechRecognition?: new () => RecognitionLike };
  const Ctor = (w.SpeechRecognition ?? w.webkitSpeechRecognition)!;
  const rec = new Ctor();
  rec.lang = "en-US";
  rec.interimResults = true;
  rec.continuous = true;
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

// --- Bolzen speaks ---------------------------------------------------------------------

let audio: HTMLAudioElement | null = null;
let englishVoice: SpeechSynthesisVoice | null = null;

function pickVoice(): SpeechSynthesisVoice | null {
  if (!BROWSER_TTS) return null;
  if (englishVoice) return englishVoice;
  const voices = window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("en"));
  englishVoice = voices.find((v) => /samantha|daniel|google uk|google us|alex/i.test(v.name)) ?? voices[0] ?? null;
  return englishVoice;
}

export function stopSpeaking() {
  generation++;
  queue = Promise.resolve();
  if (BROWSER_TTS) window.speechSynthesis.cancel();
  audio?.pause();
  audio = null;
}

let queue: Promise<void> = Promise.resolve();
const STALE_MS = 8000;
let generation = 0;

/** Bolzen says one short line, after the line he is saying right now. */
export function speak(text: string, mode: "live" | "demo"): Promise<void> {
  const line = text.replace(/\*\*/g, "").trim();
  if (!line) return queue;
  const mine = generation;
  const queuedAt = Date.now();
  // A line that waited too long behind others is stale by the time it is its turn.
  queue = queue
    .then(() => (mine === generation && Date.now() - queuedAt < STALE_MS ? say(line, mode, mine) : undefined))
    .catch(() => undefined);
  return queue;
}

async function say(line: string, mode: "live" | "demo", mine: number): Promise<void> {
  if (caps.tts === "elevenlabs" && mode === "live") {
    try {
      const res = await fetch(apiUrl("/api/voice/speak"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: line }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      // The microphone may have opened while the audio was on its way.
      if (mine !== generation) return;
      const url = URL.createObjectURL(blob);
      const player = new Audio(url);
      audio = player;
      await new Promise<void>((resolve) => {
        player.onended = player.onpause = () => resolve();
        player.play().catch(() => resolve());
      });
      URL.revokeObjectURL(url);
      return;
    } catch {
      // Fall through to the browser voice.
    }
  }
  if (!BROWSER_TTS || mine !== generation) return;
  await new Promise<void>((resolve) => {
    const utterance = new SpeechSynthesisUtterance(line);
    utterance.lang = "en-US";
    const voice = pickVoice();
    if (voice) utterance.voice = voice;
    utterance.rate = 1.05;
    utterance.pitch = 0.9;
    utterance.onend = utterance.onerror = () => resolve();
    window.speechSynthesis.speak(utterance);
    // Some voices never fire onend; do not let the queue hang.
    setTimeout(resolve, 1500 + line.length * 90);
  });
}
