// Mechanic speaks only through Gemini Live (lib/geminiLive.ts), inside a voice conversation
// the person started. Its native 24 kHz PCM plays gaplessly through Web Audio here, and
// `useSpeech` exposes the output level for the mascot's lip-sync. Without Gemini Live,
// Mechanic stays silent and his text is the caption.
import { create } from "zustand";

interface SpeechState {
  /** Loudness of Mechanic's voice right now, 0 to 1, updated every animation frame while speaking. */
  level: number;
  speaking: boolean;
}

export const useSpeech = create<SpeechState>(() => ({ level: 0, speaking: false }));

let generation = 0;

// --- latency ------------------------------------------------------------------

let pendingLatency: { turnEnd: number } | null = null;
const latencies: { first_audio_ms: number; tts: string }[] = [];

/** Called when Reson8 says the person's turn has ended; the next reply's first audio closes the measurement. */
export function markTurnEnd() {
  pendingLatency = { turnEnd: performance.now() };
}

function audioStarted(tts: string) {
  const l = pendingLatency;
  if (!l) return;
  pendingLatency = null;
  const entry = { first_audio_ms: Math.round(performance.now() - l.turnEnd), tts };
  latencies.push(entry);
  (window as unknown as { __voiceLatency?: typeof latencies }).__voiceLatency = latencies;
  console.info(`[voice] end of turn → first audio ${entry.first_audio_ms} ms (${tts})`);
}

// --- Web Audio output -----------------------------------------------------------

let audioCtx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let nextTime = 0;
const sources = new Set<AudioBufferSourceNode>();

/** Creates (or wakes) the output context; call it from a click so the browser allows sound. */
export function unlockAudio() {
  if (!audioCtx) {
    audioCtx = new AudioContext();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 512;
    analyser.connect(audioCtx.destination);
  }
  if (audioCtx.state === "suspended") void audioCtx.resume();
  return audioCtx;
}

/** Mechanic is saying something right now. */
export function isSpeaking(): boolean {
  return sources.size > 0 || useSpeech.getState().speaking;
}

/** Stops everything Mechanic is saying. */
export function stopSpeaking() {
  if (isSpeaking()) console.info("[voice] stopped speaking");
  generation++;
  for (const source of sources) {
    try {
      source.stop();
    } catch {
      // Already ended.
    }
  }
  sources.clear();
  nextTime = 0;
  void audioCtx?.resume();
  endSpeaking();
}

// --- output level for lip-sync ---------------------------------------------------------

let metering = false;
let frame = 0;
let samples: Float32Array<ArrayBuffer> | null = null;

function beginSpeaking() {
  metering = true;
  if (!useSpeech.getState().speaking) useSpeech.setState({ speaking: true });
  if (!frame) frame = requestAnimationFrame(tick);
}

function endSpeaking() {
  metering = false;
  if (frame) cancelAnimationFrame(frame);
  frame = 0;
  useSpeech.setState({ speaking: false, level: 0 });
}

function tick() {
  frame = requestAnimationFrame(tick);
  let level = 0;
  if (metering && analyser) {
    samples ??= new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (const s of samples) sum += s * s;
    // Speech RMS sits around 0.05 to 0.3; this maps it onto 0 to 1.
    level = Math.min(1, Math.sqrt(sum / samples.length) * 4);
  }
  const previous = useSpeech.getState().level;
  if (Math.abs(previous - level) > 0.02) useSpeech.setState({ level });
}

/** Gemini's native 24 kHz PCM uses the same audio output and lip-sync meter. */
export function playLivePcm(data: string) {
  const ctx = unlockAudio();
  const raw = atob(data);
  const bytes = Uint8Array.from(raw, (c) => c.charCodeAt(0));
  const pcm = new DataView(bytes.buffer);
  const buffer = ctx.createBuffer(1, Math.floor(bytes.length / 2), 24000);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < channel.length; i++) channel[i] = pcm.getInt16(i * 2, true) / 32768;
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(analyser!);
  const at = Math.max(ctx.currentTime + 0.02, nextTime);
  source.start(at);
  nextTime = at + buffer.duration;
  sources.add(source);
  const mine = generation;
  source.onended = () => {
    sources.delete(source);
    if (!sources.size && mine === generation) endSpeaking();
  };
  setTimeout(() => {
    if (mine !== generation) return;
    beginSpeaking();
    audioStarted("gemini-live");
  }, Math.max(0, (at - ctx.currentTime) * 1000));
}
