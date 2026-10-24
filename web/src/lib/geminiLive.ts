// Gemini Live is Mechanic's only voice. One microphone feeds Gemini and Reson8 in parallel;
// Reson8 only writes the chat transcript and never starts a second build. Without Gemini Live
// the microphone still dictates, and Mechanic answers in text.
import { apiFetch, apiStreamUrl } from "./api";
import { openMic, startHandsFree, voiceCapabilities, type HandsFree, type HandsFreeHandlers } from "./voice";
import { markTurnEnd, playLivePcm, stopSpeaking, unlockAudio } from "./speech";
import { useUi } from "./ui";

export async function startVoiceConversation(handlers: HandsFreeHandlers, onHeard: (text: string) => void): Promise<HandsFree | null> {
  if (!voiceCapabilities().geminiLive) {
    handlers.onError("Gemini Live is not configured. Mechanic answers in text.");
    return startHandsFree(handlers);
  }
  let stopped = false;
  let failed = false;
  let ready = false;
  let mic: Awaited<ReturnType<typeof openMic>> | null = null;
  let transcript: WebSocket | null = null;
  let fallback: HandsFree | null = null;
  const audio = unlockAudio();
  const url = new URL(apiStreamUrl("/api/voice/live"), window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const live = new WebSocket(url);
  const release = () => {
    mic?.close();
    mic = null;
    transcript?.close();
    transcript = null;
    live.close();
    stopSpeaking();
    useUi.getState().setUserTalking(false);
    onHeard("");
  };
  const fail = async () => {
    if (stopped || failed) return;
    failed = true;
    release();
    if (!useUi.getState().handsFree) return;
    handlers.onError("Gemini Live is unavailable. Mechanic answers in text.");
    try { fallback = await startHandsFree(handlers); }
    catch { handlers.onError("The microphone is unavailable. Check its permission or type instead."); }
    if (stopped) fallback?.stop();
    else if (!fallback) useUi.getState().setHandsFree(false);
  };
  let resolveReady: (ok: boolean) => void = () => undefined;
  const connected = new Promise<boolean>((resolve) => { resolveReady = resolve; });
  const timer = setTimeout(() => { resolveReady(false); void fail(); }, 20000);
  live.onmessage = (event) => {
    if (stopped || failed) return;
    const data = JSON.parse(event.data);
    if (data.type === "ready") {
      ready = true;
      clearTimeout(timer);
      resolveReady(true);
    } else if (data.type === "audio") {
      useUi.getState().setUserTalking(false);
      if (useUi.getState().voiceOn) playLivePcm(data.data);
    } else if (data.type === "interrupted") {
      stopSpeaking();
      useUi.getState().setUserTalking(true);
    } else if (data.type === "input") {
      if (!transcript || transcript.readyState !== WebSocket.OPEN) {
        useUi.getState().setUserTalking(true);
        onHeard(data.text);
      }
    } else if (data.type === "turn_complete") {
      useUi.getState().setUserTalking(false);
      onHeard("");
    } else if (data.type === "error") {
      resolveReady(false);
      void fail();
    }
  };
  live.onclose = live.onerror = () => {
    clearTimeout(timer);
    resolveReady(false);
    void fail();
  };
  if (await connected) {
    try {
      const caps = voiceCapabilities();
      if (caps.stt === "reson8") {
        try {
          const response = await apiFetch("/api/voice/token", { method: "POST" });
          if (!response.ok) throw new Error("transcript token unavailable");
          const token = (await response.json()).access_token;
          const params = new URLSearchParams({ encoding: "pcm_s16le", sample_rate: "16000", channels: "1", language: caps.language, eager_turn_probability: "0.3" });
          if (caps.customModelId) params.set("custom_model_id", caps.customModelId);
          else if (caps.phrases.length) params.set("phrases", caps.phrases.join(","));
          const ws = new WebSocket(`${caps.turnsUrl}?${params}`, ["bearer", token]);
          transcript = ws;
          await new Promise<void>((resolve, reject) => {
            const timeout = setTimeout(() => reject(new Error("transcript timeout")), 5000);
            ws.onopen = () => { clearTimeout(timeout); resolve(); };
            ws.onerror = () => { clearTimeout(timeout); reject(new Error("transcript unavailable")); };
            ws.onclose = () => { clearTimeout(timeout); reject(new Error("transcript closed")); };
          });
          if (!stopped && !failed) live.send(JSON.stringify({ type: "transcriber", source: "reson8" }));
          let heard = "";
          ws.onmessage = (event) => {
            if (stopped || failed || live.readyState !== WebSocket.OPEN) return;
            const data = JSON.parse(event.data);
            if (data.type === "turn_start") {
              heard = "";
              useUi.getState().setUserTalking(true);
              // Gemini's VAD owns barge-in; Reson8 is an independent transcript channel.
            } else if (data.type === "turn_end_candidate" && typeof data.text === "string") {
              heard = data.text.trim();
              onHeard(heard);
            } else if (data.type === "turn_end") {
              if (typeof data.text === "string" && data.text.trim()) heard = data.text.trim();
              markTurnEnd();
              if (heard) live.send(JSON.stringify({ type: "transcript", text: heard }));
              heard = "";
              onHeard("");
              useUi.getState().setUserTalking(false);
            }
          };
          ws.onclose = ws.onerror = () => {
            if (!stopped && !failed && live.readyState === WebSocket.OPEN) {
              live.send(JSON.stringify({ type: "transcriber", source: "gemini" }));
              handlers.onError("Reson8 disconnected. Gemini is keeping the transcript.");
            }
          };
        } catch {
          transcript?.close();
          transcript = null;
          handlers.onError("Reson8 is unavailable. Gemini is keeping the transcript.");
        }
      }
      if (!stopped && !failed && ready) {
        mic = await openMic((chunk) => {
          if (stopped || failed) return;
          if (live.readyState === WebSocket.OPEN) live.send(chunk);
          if (transcript?.readyState === WebSocket.OPEN) transcript.send(chunk);
        }, audio);
        if (stopped || failed) mic.close();
        // Keep the output context awake after microphone permission.
        if (audio.state === "suspended") await audio.resume();
      }
    } catch {
      await fail();
    }
  }
  return { stop: () => { stopped = true; clearTimeout(timer); release(); fallback?.stop(); } };
}
