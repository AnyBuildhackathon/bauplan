// Mechanic speaks, always in his ElevenLabs voice and never in the system voice. The
// backend streams each spoken line as `say` deltas; they are cut into phrases (the first
// one at a comma, the rest at sentence ends) so speech starts while the text is still
// coming. Each phrase is a streamed PCM request that starts as soon as the phrase is
// complete and plays gaplessly through Web Audio. The recorded demo has no backend: its
// lines come with pre-rendered clips (same voice and model) that play through the same
// output. Without either, Mechanic stays silent and his text is the caption. `useSpeech`
// exposes the output level for the mascot's lip-sync. When the person starts talking (Reson8 turn
// start), speech pauses at once; it stops for good when they really said something, and
// resumes when the "turn" was only Mechanic's own voice echoing into the microphone.
import { create } from "zustand";
import { apiFetch } from "./api";
import { voiceCapabilities } from "./voice";
import type { SayEvent } from "../events/types";

interface SpeechState {
  /** Loudness of Mechanic's voice right now, 0 to 1, updated every animation frame while speaking. */
  level: number;
  speaking: boolean;
}

export const useSpeech = create<SpeechState>(() => ({ level: 0, speaking: false }));

// A line that waited too long behind others is stale by the time it is its turn.
const STALE_MS = 8000;
const ECHO_WINDOW_MS = 15000;

interface Phrase {
  text: string;
  previous: string;
  queuedAt: number;
  /** ElevenLabs audio, requested as soon as the phrase is complete. */
  audio?: Promise<ReadableStreamDefaultReader<Uint8Array> | null>;
  /** A pre-rendered clip of the recorded demo, decoded as soon as the phrase is queued. */
  clip?: Promise<AudioBuffer | null>;
  /** The first phrase of the reply to a spoken turn: its first sound closes the latency measurement. */
  measure: boolean;
}

let generation = 0;
let chain: Promise<void> = Promise.resolve();
// Phrases queued or playing; between two phrases `speaking` is briefly false, this is not.
let pending = 0;
let held = false;
const spoken: { text: string; at: number }[] = [];

// --- latency ------------------------------------------------------------------

interface Latency {
  turnEnd: number;
  firstToken?: number;
  firstPhrase?: number;
}
let pendingLatency: Latency | null = null;
const latencies: { first_audio_ms: number; first_token_ms?: number; first_phrase_ms?: number; tts: string }[] = [];

/** Called when Reson8 says the person's turn has ended; the next reply's first audio closes the measurement. */
export function markTurnEnd() {
  pendingLatency = { turnEnd: performance.now() };
}

function audioStarted(phrase: Pick<Phrase, "measure">, tts: string) {
  const l = pendingLatency;
  if (!l || !phrase.measure) return;
  pendingLatency = null;
  const ms = (t?: number) => (t === undefined ? undefined : Math.round(t - l.turnEnd));
  const entry = { first_audio_ms: ms(performance.now())!, first_token_ms: ms(l.firstToken), first_phrase_ms: ms(l.firstPhrase), tts };
  latencies.push(entry);
  (window as unknown as { __voiceLatency?: typeof latencies }).__voiceLatency = latencies;
  console.info(
    `[voice] end of turn → first audio ${entry.first_audio_ms} ms (first token ${entry.first_token_ms} ms, first phrase ${entry.first_phrase_ms} ms, ${tts})`,
  );
}

// --- streamed lines -------------------------------------------------------------

interface Line {
  buffer: string;
  phrases: number;
  previous: string;
  latency: boolean;
}
const lines = new Map<string, Line>();

/** Cuts the complete phrases off the front of the buffer; the first phrase of a line may end at a comma. */
function takePhrases(line: Line, final: boolean): string[] {
  const out: string[] = [];
  for (;;) {
    const sentence = /[.!?…]+["”’)]*\s/.exec(line.buffer);
    let end = sentence ? sentence.index + sentence[0].length : -1;
    if (line.phrases + out.length === 0) {
      const clause = /[,;:\u2014-]\s/.exec(line.buffer);
      if (clause && (end < 0 || clause.index < end) && line.buffer.slice(0, clause.index).trim().split(/\s+/).length >= 2) {
        end = clause.index + clause[0].length;
      }
    }
    if (end < 0) break;
    const phrase = line.buffer.slice(0, end).trim();
    line.buffer = line.buffer.slice(end);
    if (phrase) out.push(phrase);
  }
  if (final && line.buffer.trim()) {
    out.push(line.buffer.trim());
    line.buffer = "";
  }
  return out;
}

/**
 * One `say` event from the backend. Replies are always spoken; updates are dropped while the
 * person is talking, since Mechanic does not talk over them.
 */
export function handleSay(ev: SayEvent, opts: { voiceOn: boolean; userTalking: boolean }) {
  let line = lines.get(ev.id);
  if (!line) {
    if (ev.done && !ev.text) return;
    line = { buffer: "", phrases: 0, previous: "", latency: ev.kind === "reply" && pendingLatency !== null };
    lines.set(ev.id, line);
    if (line.latency && pendingLatency) pendingLatency.firstToken = performance.now();
  }
  if (ev.cancelled) {
    lines.delete(ev.id);
    return;
  }
  if (ev.delta) line.buffer += ev.delta;
  else if (ev.done && ev.text && line.phrases === 0 && !line.buffer) line.buffer = ev.text;
  const phrases = takePhrases(line, ev.done);
  if (ev.done) lines.delete(ev.id);
  if (!opts.voiceOn || (ev.kind === "update" && opts.userTalking)) return;
  for (const text of phrases) {
    if (line.latency && line.phrases === 0 && pendingLatency) pendingLatency.firstPhrase = performance.now();
    enqueue(text, line.previous, "live", line.latency && line.phrases === 0);
    line.phrases++;
    line.previous = `${line.previous} ${text}`.trim();
  }
}

/**
 * Mechanic says one short line (a speech bubble or a question), after what he is saying now.
 * In the recorded demo `clip` is the line's pre-rendered audio; without it (and without a live
 * ElevenLabs voice) the line stays silent.
 */
export function speak(text: string, mode: "live" | "demo", clip?: string): Promise<void> {
  const line = text.replace(/\*\*/g, "").trim();
  if (!line) return chain;
  return enqueue(line, "", mode, false, clip);
}

function enqueue(text: string, previous: string, mode: "live" | "demo" = "live", measure = false, clip?: string): Promise<void> {
  const mine = generation;
  const phrase: Phrase = { text, previous, queuedAt: Date.now(), measure };
  const eleven = voiceCapabilities().tts === "elevenlabs" && mode === "live";
  const recorded = mode === "demo" && !!clip;
  if (!eleven && !recorded) return chain;
  // The request starts now, so it streams while the phrases before it are still playing.
  if (eleven) phrase.audio = requestAudio(phrase);
  else phrase.clip = loadClip(clip!);
  pending++;
  chain = chain
    .then(() => {
      if (mine !== generation || Date.now() - phrase.queuedAt > STALE_MS) return;
      remember(text);
      return eleven ? playEleven(phrase, mine) : playClip(phrase, mine);
    })
    .catch(() => undefined)
    .finally(() => {
      if (mine === generation) pending = Math.max(0, pending - 1);
    });
  return chain;
}

function remember(text: string) {
  const now = Date.now();
  spoken.push({ text, at: now });
  while (spoken.length && now - spoken[0].at > ECHO_WINDOW_MS) spoken.shift();
}

const words = (text: string) => text.toLowerCase().match(/[a-z0-9']+/g) ?? [];

/** Mechanic is saying something or has phrases waiting. */
export function isSpeaking(): boolean {
  return pending > 0 || useSpeech.getState().speaking;
}

/**
 * True when a transcript is mostly words Mechanic just said: his own voice came back through
 * the microphone. Short answers ("yes", "fifteen") always count as the person's.
 */
export function isEcho(text: string): boolean {
  const heard = words(text);
  if (heard.length < 3) return false;
  const now = Date.now();
  const said = new Set(spoken.filter((s) => now - s.at < ECHO_WINDOW_MS).flatMap((s) => words(s.text)));
  if (said.size === 0) return false;
  return heard.filter((w) => said.has(w)).length / heard.length >= 0.7;
}

// --- barge-in -------------------------------------------------------------------

/** The person started talking: the backend opens its model and voice connections before the reply needs them. */
export function warmUp() {
  void apiFetch("/api/voice/warm", { method: "POST" }).catch(() => undefined);
}

/** The person started talking: pause at once, mid-word. */
export function hold() {
  if (!isSpeaking()) return;
  console.info("[voice] barge-in: paused");
  held = true;
  void audioCtx?.suspend();
}

/** Their turn was only an echo of Mechanic (or noise): carry on where he stopped. */
export function release() {
  if (!held) return;
  console.info("[voice] barge-in: resumed (echo or noise)");
  held = false;
  void audioCtx?.resume();
}

/** Stops everything Mechanic is saying or about to say. */
export function stopSpeaking() {
  if (isSpeaking()) console.info("[voice] stopped speaking");
  generation++;
  chain = Promise.resolve();
  pending = 0;
  lines.clear();
  held = false;
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

// --- ElevenLabs over Web Audio ----------------------------------------------------

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
  if (!held && audioCtx.state === "suspended") void audioCtx.resume();
  return audioCtx;
}

// ElevenLabs answers in well under a second; without headers by then, the browser voice speaks instead.
const SPEAK_FIRST_BYTE_MS = 3000;

async function requestAudio(phrase: Phrase): Promise<ReadableStreamDefaultReader<Uint8Array> | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SPEAK_FIRST_BYTE_MS);
  try {
    const res = await apiFetch("/api/voice/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: phrase.text, previous_text: phrase.previous }),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) return null;
    return res.body.getReader();
  } catch {
    return null;
  } finally {
    // Only the wait for the first response is limited; the stream itself may run as long as the sentence.
    clearTimeout(timer);
  }
}

async function playEleven(phrase: Phrase, mine: number): Promise<void> {
  const reader = await phrase.audio;
  if (!reader) return;
  const ctx = unlockAudio();
  const rate = voiceCapabilities().ttsSampleRate;
  let carry: Uint8Array | null = null;
  let first = true;
  for (;;) {
    const { value, done } = await reader.read();
    if (mine !== generation) {
      void reader.cancel();
      return;
    }
    if (done) break;
    let bytes = value;
    if (carry) {
      const joined = new Uint8Array(carry.length + bytes.length);
      joined.set(carry);
      joined.set(bytes, carry.length);
      bytes = joined;
      carry = null;
    }
    if (bytes.length % 2) {
      carry = bytes.slice(bytes.length - 1);
      bytes = bytes.subarray(0, bytes.length - 1);
    }
    if (!bytes.length) continue;
    const pcm = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.length / 2);
    const buffer = ctx.createBuffer(1, pcm.length, rate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / 0x8000;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(analyser!);
    const at = Math.max(ctx.currentTime + 0.02, nextTime);
    source.start(at);
    nextTime = at + buffer.duration;
    sources.add(source);
    source.onended = () => {
      sources.delete(source);
      if (sources.size === 0 && mine === generation) endSpeaking();
    };
    if (first) {
      first = false;
      const startsIn = Math.max(0, (at - ctx.currentTime) * 1000);
      setTimeout(() => {
        if (mine === generation) {
          beginSpeaking();
          audioStarted(phrase, "elevenlabs");
        }
      }, startsIn);
    }
  }
  // The next phrase is scheduled right after this one; wait until this one is nearly through.
  const left = (nextTime - ctx.currentTime) * 1000 - 150;
  if (left > 0) await new Promise((resolve) => setTimeout(resolve, left));
}

// --- pre-rendered clips (the recorded demo) ---------------------------------------------

async function loadClip(url: string): Promise<AudioBuffer | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return await unlockAudio().decodeAudioData(await res.arrayBuffer());
  } catch {
    return null;
  }
}

async function playClip(phrase: Phrase, mine: number): Promise<void> {
  const buffer = await phrase.clip;
  if (!buffer || mine !== generation) return;
  const ctx = unlockAudio();
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(analyser!);
  const at = Math.max(ctx.currentTime + 0.02, nextTime);
  source.start(at);
  nextTime = at + buffer.duration;
  sources.add(source);
  source.onended = () => {
    sources.delete(source);
    if (sources.size === 0 && mine === generation) endSpeaking();
  };
  setTimeout(() => {
    if (mine === generation) beginSpeaking();
  }, Math.max(0, (at - ctx.currentTime) * 1000));
  // The next clip is scheduled right after this one; wait until this one is nearly through.
  const left = (nextTime - ctx.currentTime) * 1000 - 150;
  if (left > 0) await new Promise((resolve) => setTimeout(resolve, left));
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
  if (held) level = 0;
  else if (metering && analyser) {
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
    audioStarted({ measure: true }, "gemini-live");
  }, Math.max(0, (at - ctx.currentTime) * 1000));
}
