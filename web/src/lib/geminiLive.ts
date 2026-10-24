// The voice agent is Gemini Live only: it hears the microphone, transcribes both sides for the
// chat and logbook, and speaks as Mechanic. Without Gemini Live there is no voice conversation;
// Mechanic answers typed messages in text.
import { apiStreamUrl } from "./api";
import { openMic, voiceCapabilities, type HandsFree } from "./voice";
import { playLivePcm, stopSpeaking, unlockAudio } from "./speech";
import { create } from "zustand";
import { useUi } from "./ui";

/** What Gemini heard of the current turn, and the last notice; shared by every chat input. */
export const useVoiceChat = create<{ heard: string; notice: { text: string; at: number } | null }>(() => ({ heard: "", notice: null }));
const notify = (text: string) => useVoiceChat.setState({ notice: { text, at: Date.now() } });
const hear = (heard: string) => useVoiceChat.setState({ heard });

// One conversation for the whole page: the start screen's input and the workbench's input
// replace each other when the first chat line arrives, and the conversation must not end then.
let conversation: HandsFree | null = null;
let starting = false;
// Only the newest socket may turn Talk off: an older one the server replaced closes later.
let latest = 0;

/** The one Talk button: turns the voice agent on (Mechanic greets, then listens hands-free). */
export async function startVoice() {
  if (conversation || starting) return;
  starting = true;
  unlockAudio();
  useUi.getState().setHandsFree(true);
  const active = await startVoiceConversation(notify, hear).catch(() => {
    notify("The microphone is unavailable. Check its permission or type instead.");
    return null;
  });
  starting = false;
  if (!active || !useUi.getState().handsFree) {
    active?.stop();
    useUi.getState().setHandsFree(false);
    return;
  }
  conversation = active;
}

/** The same button again: the voice agent is off. */
export function stopVoice() {
  conversation?.stop();
  conversation = null;
  useUi.getState().setHandsFree(false);
  hear("");
}

async function startVoiceConversation(onError: (message: string) => void, onHeard: (text: string) => void): Promise<HandsFree | null> {
  if (!voiceCapabilities().geminiLive) {
    onError("Gemini Live is not configured. Type to Mechanic instead.");
    return null;
  }
  const id = ++latest;
  let stopped = false;
  let failed = false;
  let mic: Awaited<ReturnType<typeof openMic>> | null = null;
  const audio = unlockAudio();
  const url = new URL(apiStreamUrl("/api/voice/live"), window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const live = new WebSocket(url);
  const release = () => {
    mic?.close();
    mic = null;
    live.close();
    stopSpeaking();
    useUi.getState().setUserTalking(false);
    onHeard("");
  };
  const fail = (message = "Gemini Live is unavailable. Type to Mechanic instead.") => {
    if (stopped || failed) return;
    failed = true;
    release();
    if (id !== latest || !useUi.getState().handsFree) return;
    onError(message);
    conversation = null;
    useUi.getState().setHandsFree(false);
  };
  let resolveReady: (ok: boolean) => void = () => undefined;
  const connected = new Promise<boolean>((resolve) => { resolveReady = resolve; });
  const timer = setTimeout(() => { resolveReady(false); fail(); }, 20000);
  live.onmessage = (event) => {
    if (stopped || failed) return;
    const data = JSON.parse(event.data);
    if (data.type === "ready") {
      clearTimeout(timer);
      resolveReady(true);
    } else if (data.type === "audio") {
      useUi.getState().setUserTalking(false);
      if (useUi.getState().voiceOn) playLivePcm(data.data);
    } else if (data.type === "interrupted") {
      stopSpeaking();
      useUi.getState().setUserTalking(true);
    } else if (data.type === "input") {
      useUi.getState().setUserTalking(true);
      onHeard(data.text);
    } else if (data.type === "turn_complete") {
      useUi.getState().setUserTalking(false);
      onHeard("");
    } else if (data.type === "ended") {
      // A new chat or a newer Talk ended this one on purpose: Talk turns off without an error.
      stopped = true;
      clearTimeout(timer);
      resolveReady(false);
      release();
      if (id !== latest) return;
      conversation = null;
      useUi.getState().setHandsFree(false);
      if (data.reason === "replaced") onError("Talk continues in another window.");
    } else if (data.type === "error") {
      resolveReady(false);
      fail();
    }
  };
  live.onclose = live.onerror = () => {
    clearTimeout(timer);
    resolveReady(false);
    fail();
  };
  if (await connected && !stopped && !failed) {
    try {
      mic = await openMic((chunk) => {
        if (!stopped && !failed && live.readyState === WebSocket.OPEN) live.send(chunk);
      }, audio);
      if (stopped || failed) mic.close();
      // Keep the output context awake after microphone permission.
      if (audio.state === "suspended") await audio.resume();
    } catch {
      fail("The microphone is unavailable. Check its permission or type instead.");
    }
  }
  return { stop: () => { stopped = true; clearTimeout(timer); release(); } };
}
