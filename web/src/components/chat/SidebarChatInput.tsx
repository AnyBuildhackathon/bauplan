// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/SidebarChat/SidebarChatInput.tsx. Modified: Bevel pill
// styling, a mic button and a sketch photo (SketchDrop.tsx) in place of attachments and mentions: hands-free by default
// (click to start a conversation; Reson8 hears when a turn ends and when the person
// interrupts Mechanic), push-to-talk as the fallback (hold the button or the space
// bar); speech goes to Reson8 or the browser (lib/voice.ts).
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Mic, MousePointer2 } from "lucide-react";
import { useUi } from "../../lib/ui";
import { hold, isEcho, isSpeaking, markTurnEnd, release, stopSpeaking, unlockAudio, warmUp } from "../../lib/speech";
import { startListening as listen, type HandsFree, type Listener } from "../../lib/voice";
import { startVoiceConversation } from "../../lib/geminiLive";
import { useVoiceEngine } from "../../lib/voiceEngine";
import { pickImage, SketchButton, SketchChip } from "./SketchDrop";

interface SidebarChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  /** A finished spoken sentence, sent as it is. */
  onVoice?: (text: string) => void;
  /** The attached sketch photo, set by the button, a paste or a drop on the chat column. */
  sketch?: File | null;
  onSketchChange?: (file: File | null) => void;
  /** Sends the sketch with the typed text as its note. */
  onSendSketch?: (file: File, note: string) => void;
  disabled?: boolean;
  placeholder?: string;
  size?: "md" | "lg";
}

export function Waveform({ active, bars = 7, className = "" }: { active: boolean; bars?: number; className?: string }) {
  return (
    <div className={`flex items-center gap-[3px] ${className}`} aria-hidden>
      {Array.from({ length: bars }, (_, i) => (
        <span
          key={i}
          className="w-[3px] rounded-full bg-accent transition-[height]"
          style={{
            height: active ? undefined : 4,
            animation: active ? `wave 0.9s ${i * 0.09}s ease-in-out infinite` : undefined,
          }}
        />
      ))}
      <style>{`@keyframes wave { 0%,100% { height: 5px } 50% { height: 20px } }`}</style>
    </div>
  );
}

export default function SidebarChatInput({
  value,
  onChange,
  onSubmit,
  onVoice,
  sketch = null,
  onSketchChange,
  onSendSketch,
  disabled = false,
  placeholder = "Describe what to build",
  size = "md",
}: SidebarChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const listening = useUi((s) => s.listening);
  const setListening = useUi((s) => s.setListening);
  const micMode = useUi((s) => s.micMode);
  const engineChoice = useVoiceEngine((s) => s.choice);
  const handsFree = useUi((s) => s.handsFree);
  const setHandsFree = useUi((s) => s.setHandsFree);
  const userTalking = useUi((s) => s.userTalking);
  const setUserTalking = useUi((s) => s.setUserTalking);
  const [hint, setHint] = useState<string | null>(null);
  const lg = size === "lg";

  // Auto-resize textarea without causing layout flash
  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const min = lg ? 112 : 22;
    textarea.style.height = `${min}px`;
    textarea.style.height = `${Math.min(Math.max(textarea.scrollHeight, min), lg ? 240 : 120)}px`;
  }, [lg]);

  useEffect(() => {
    adjustHeight();
  }, [value, adjustHeight]);

  const [heard, setHeard] = useState("");
  const listener = useRef<Promise<Listener | null> | null>(null);
  const flash = useCallback((text: string) => {
    setHint(text);
    setTimeout(() => setHint(null), 3600);
  }, []);

  // --- hands-free -----------------------------------------------------------
  const conversation = useRef<HandsFree | null>(null);
  const starting = useRef(false);
  const onVoiceRef = useRef(onVoice);
  onVoiceRef.current = onVoice;
  // Whether Mechanic was talking when this turn began; only then can the turn be his own echo.
  const overMechanic = useRef(false);

  const stopHandsFree = useCallback(() => {
    conversation.current?.stop();
    conversation.current = null;
    setHandsFree(false);
    setHeard("");
  }, [setHandsFree]);

  const startConversation = useCallback(async () => {
    if (conversation.current || starting.current) return;
    starting.current = true;
    setHint(null);
    unlockAudio();
    setHandsFree(true);
    const active = await startVoiceConversation({
      onTurnStart: () => {
        // Barge-in: Mechanic pauses mid-word the moment the person starts talking.
        overMechanic.current = isSpeaking();
        hold();
        warmUp();
        setUserTalking(true);
        setHeard("");
      },
      onPartial: (text) => {
        setHeard(text);
        if (text && !(overMechanic.current && isEcho(text))) stopSpeaking();
      },
      onTurnEnd: (text) => {
        setUserTalking(false);
        setHeard("");
        if (!text || (overMechanic.current && isEcho(text))) {
          // Noise, or Mechanic hearing himself: he carries on.
          release();
          return;
        }
        stopSpeaking();
        markTurnEnd();
        onVoiceRef.current?.(text);
      },
      onError: flash,
    }, setHeard).catch(() => {
      flash("The microphone is unavailable. Check its permission or type instead.");
      return null;
    });
    starting.current = false;
    if (!active || !useUi.getState().handsFree) {
      active?.stop();
      setHandsFree(false);
      return;
    }
    conversation.current = active;
  }, [setHandsFree, setUserTalking, flash]);

  useEffect(() => () => {
    useUi.getState().setHandsFree(false);
    conversation.current?.stop();
  }, []);
  useEffect(() => stopHandsFree(), [engineChoice, stopHandsFree]);
  useEffect(() => {
    if (micMode === "ptt") stopHandsFree();
  }, [micMode, stopHandsFree]);

  // --- push-to-talk -----------------------------------------------------------
  const startListening = useCallback(() => {
    if (useUi.getState().listening) return;
    setHint(null);
    setHeard("");
    setListening(true);
    listener.current = listen({ onInterim: setHeard, onError: flash });
  }, [setListening, flash]);
  const stopListening = useCallback(async () => {
    if (!useUi.getState().listening) return;
    const pending = listener.current;
    listener.current = null;
    let text = "";
    let active: Listener | null = null;
    try {
      active = pending ? await pending : null;
      text = active ? await active.stop() : "";
    } catch (err) {
      flash(`Microphone: ${err instanceof Error ? err.message : "error"}`);
    } finally {
      setListening(false);
      setHeard("");
    }
    if (text) onVoice?.(text);
    else if (active) flash("Didn't catch that. Hold the key and speak.");
  }, [setListening, onVoice, flash]);

  // A held key never comes up when the window loses focus; close the mic then too.
  useEffect(() => {
    const release = () => void stopListening();
    const hidden = () => document.hidden && release();
    window.addEventListener("blur", release);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("blur", release);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, [stopListening]);
  const stt = useUi((s) => s.stt);

  // Hold space anywhere outside a text field to talk.
  useEffect(() => {
    const isTyping = (t: EventTarget | null) =>
      t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
    const down = (e: KeyboardEvent) => {
      if (useUi.getState().micMode !== "ptt") return;
      if (e.code === "Space" && !e.repeat && !isTyping(e.target)) {
        e.preventDefault();
        startListening();
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space" && !isTyping(e.target)) void stopListening();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [startListening, stopListening]);

  const sketches = !!onSketchChange && !!onSendSketch;
  const submit = () => {
    if (sketch && onSendSketch) {
      onSendSketch(sketch, value);
      onSketchChange?.(null);
      onChange("");
      return;
    }
    onSubmit();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSubmit) submit();
    }
  };

  const canSubmit = (value.trim().length > 0 || !!sketch) && !disabled;
  const hearing = listening || (handsFree && userTalking);
  const micHot = listening || handsFree;

  return (
    <div>
      {sketch && onSketchChange && <SketchChip file={sketch} onRemove={() => onSketchChange(null)} />}
      <div
        className={`flex bg-card ring-1 transition ${micHot ? "ring-accent/50" : "ring-[#e2e2dd]"} ${
          lg
            ? "flex-col gap-3 rounded-[26px] pt-5 pr-4 pb-4 pl-6 shadow-[0_1px_2px_rgb(26_26_24/0.04),0_10px_30px_-12px_rgb(26_26_24/0.16)] focus-within:ring-accent/40 focus-within:shadow-[0_0_0_5px_rgb(31_111_120/0.08),0_10px_30px_-12px_rgb(26_26_24/0.16)] sm:pl-7"
            : "min-h-[64px] items-end gap-2 rounded-[24px] py-3 pr-3 pl-4 shadow-[var(--shadow-pill)]"
        }`}
      >
        {hearing ? (
          <div className={`flex flex-1 items-center gap-3 ${lg ? "min-h-[112px]" : "self-center"}`}>
            <Waveform active bars={lg ? 11 : 7} />
            <span className={`line-clamp-2 font-medium ${heard ? "text-ink" : "text-accent"} ${lg ? "text-[20px]" : "text-[15px]"}`}>
              {heard || (stt === "reson8" ? "Reson8 is listening…" : "Listening…")}
            </span>
          </div>
        ) : (
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={(e) => {
              if (!sketches) return;
              const picked = pickImage(e.clipboardData.files);
              if (!picked) return;
              e.preventDefault();
              if (picked.file) onSketchChange?.(picked.file);
              else if (picked.error) flash(picked.error);
            }}
            placeholder={sketch ? "What should I know about it? (optional)" : handsFree ? "Listening. Just talk, or type" : placeholder}
            rows={1}
            name="prompt"
            aria-label="Message to Mechanic"
            data-target="chat_input eingabe"
            className={`min-w-0 resize-none bg-transparent font-read text-ink outline-none placeholder:text-faint ${
              lg ? "w-full text-[19px] leading-[1.5] sm:text-[22px]" : "flex-1 self-center text-[15px] leading-snug"
            }`}
          />
        )}
        <div className={lg ? "flex items-center justify-end gap-2" : "contents"}>
        {canSubmit && !hearing && (
          <button
            type="button"
            onClick={submit}
            className={`flex shrink-0 items-center justify-center rounded-full bg-accent text-white transition hover:brightness-110 ${lg ? "h-11 w-11" : "h-9 w-9"}`}
            title="Send"
          >
            <ArrowUp className={lg ? "h-5 w-5" : "h-4.5 w-4.5"} strokeWidth={2.5} />
          </button>
        )}
        {sketches && !hearing && <SketchButton onPick={(file) => onSketchChange?.(file)} onError={flash} large={lg} />}
        <ClickyToggle size={lg ? "lg" : "sm"} />
        <button
          type="button"
          data-target="mic reson8_mic"
          onPointerDown={(e) => {
            if (micMode !== "ptt") return;
            e.preventDefault();
            startListening();
          }}
          onPointerUp={() => micMode === "ptt" && void stopListening()}
          onPointerLeave={() => micMode === "ptt" && void stopListening()}
          onClick={() => {
            if (micMode !== "handsfree") return;
            if (handsFree) stopHandsFree();
            else void startConversation();
          }}
          className={`flex shrink-0 items-center justify-center rounded-full transition select-none ${
            micHot ? "scale-105 bg-accent text-white shadow-[0_0_0_8px_rgb(31_111_120/0.16)]" : "bg-tile text-ink-2 hover:bg-track hover:text-ink"
          } ${lg ? "h-11 w-11" : "h-9 w-9"}`}
          title={stt === "none" ? "No speech recognition in this browser" : micMode === "ptt" ? "Hold to speak, or hold space" : handsFree ? "Stop listening" : "Talk hands-free"}
          aria-pressed={micMode === "handsfree" ? handsFree : undefined}
        >
          <Mic className={lg ? "h-5 w-5" : "h-4 w-4"} strokeWidth={2} />
        </button>
        </div>
      </div>
      {hint && <p className="mt-1.5 px-2 text-[12px] text-agent-ink">{hint}</p>}
    </div>
  );
}

/** HeyClicky: Mechanic's pointer flies to what he shows and presses the controls he operates. */
function ClickyToggle({ size }: { size: "sm" | "lg" }) {
  const clicky = useUi((s) => s.clicky);
  const setClicky = useUi((s) => s.setClicky);
  return (
    <button
      type="button"
      onClick={() => setClicky(!clicky)}
      aria-pressed={clicky}
      aria-label="HeyClicky pointer"
      title={clicky ? "HeyClicky on: Mechanic points and operates the app" : "HeyClicky off: actions happen without the pointer"}
      className={`flex shrink-0 items-center justify-center rounded-full transition ${
        clicky ? "bg-agent-soft text-agent-ink hover:brightness-95" : "bg-tile text-faint hover:bg-track hover:text-ink-2"
      } ${size === "lg" ? "h-11 w-11" : "h-10 w-10"}`}
    >
      <MousePointer2 className={size === "lg" ? "h-5 w-5" : "h-4.5 w-4.5"} strokeWidth={2} fill={clicky ? "currentColor" : "none"} />
    </button>
  );
}
