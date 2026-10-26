// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/SidebarChat/SidebarChatInput.tsx. Modified: Bevel pill
// styling, a mic button, a sketch photo (SketchDrop.tsx) and the studio's notes as chips (NoteChips.tsx)
// in place of attachments and mentions: hands-free by default
// (click Talk to start a Gemini Live conversation, lib/geminiLive.ts, which hears, transcribes
// and answers), push-to-talk dictation as the alternative (hold the button or the space
// bar; speech goes to Reson8 or the browser, lib/voice.ts).
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Mic, MousePointer2 } from "lucide-react";
import { useUi } from "../../lib/ui";
import { useSpeech } from "../../lib/speech";
import { startListening as listen, type Listener } from "../../lib/voice";
import { startVoice, stopVoice, useVoiceChat } from "../../lib/geminiLive";
import { pickImage, SketchButton, SketchChip } from "./SketchDrop";
import { DraftNoteChips } from "./NoteChips";
import { useNotes } from "../../events/notes";
import { PrinterButton } from "../print/PrinterPicker";

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
  const handsFree = useUi((s) => s.handsFree);
  const userTalking = useUi((s) => s.userTalking);
  const speaking = useSpeech((s) => s.speaking);
  const notes = useNotes((s) => s.notes.length);
  const [hint, setHint] = useState<string | null>(null);
  const lg = size === "lg";
  // A longer message gets the whole width, the buttons move under it; the row of buttons
  // beside the text would leave it a column a few words wide in the side panel. A box too
  // narrow for text and buttons side by side (a phone) stacks them always (container query).
  // Studio notes take the top row of the box, so it stacks with them too.
  const stacked = !lg && (value.length > 28 || value.includes("\n") || notes > 0);

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

  const [dictated, setHeard] = useState("");
  const voiceHeard = useVoiceChat((s) => s.heard);
  const notice = useVoiceChat((s) => s.notice);
  const listener = useRef<Promise<Listener | null> | null>(null);
  const flash = useCallback((text: string) => {
    setHint(text);
    setTimeout(() => setHint(null), 3600);
  }, []);

  // --- voice agent (Gemini Live, lib/geminiLive.ts) ---------------------------
  // The conversation lives outside this component, so it outlasts the start screen's input.
  const heard = handsFree ? voiceHeard : dictated;
  useEffect(() => {
    if (notice && Date.now() - notice.at < 1000) flash(notice.text);
  }, [notice, flash]);
  useEffect(() => {
    if (micMode === "ptt") stopVoice();
  }, [micMode]);

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

  // Notes alone make a message: Mechanic looks at what they point at.
  const canSubmit = (value.trim().length > 0 || !!sketch || notes > 0) && !disabled;
  const hearing = listening || (handsFree && userTalking);
  const micHot = listening || handsFree;

  return (
    <div className="@container">
      {sketch && onSketchChange && <SketchChip file={sketch} onRemove={() => onSketchChange(null)} />}
      <div
        className={`flex bg-card ring-1 transition ${micHot ? "ring-accent/50" : "ring-[#e2e2dd]"} ${
          lg
            ? "flex-col gap-3 rounded-[26px] pt-5 pr-4 pb-4 pl-6 shadow-[0_1px_2px_rgb(26_26_24/0.04),0_10px_30px_-12px_rgb(26_26_24/0.16)] focus-within:ring-accent/40 focus-within:shadow-[0_0_0_5px_rgb(31_111_120/0.08),0_10px_30px_-12px_rgb(26_26_24/0.16)] sm:pl-7"
            : `min-h-[64px] gap-2 rounded-[24px] py-3 pr-3 pl-4 shadow-[var(--shadow-pill)] ${stacked ? "flex-col pt-3.5" : "items-end @max-[360px]:flex-col @max-[360px]:items-stretch @max-[360px]:pt-3.5"}`
        }`}
      >
        {notes > 0 && !sketch && <DraftNoteChips />}
        {hearing ? (
          <div className={`flex flex-1 items-center gap-3 ${lg ? "min-h-[112px]" : "self-center"}`}>
            <Waveform active bars={lg ? 11 : 7} />
            <span className={`line-clamp-2 font-medium ${heard ? "text-ink" : "text-accent"} ${lg ? "text-[20px]" : "text-[15px]"}`}>
              {heard || (handsFree ? "Gemini is listening…" : stt === "reson8" ? "Reson8 is listening…" : "Listening…")}
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
            placeholder={sketch ? "What should I know about it? (optional)" : notes > 0 ? "What should Mechanic do here? (optional)" : handsFree ? "Just talk, or type" : placeholder}
            rows={1}
            name="prompt"
            aria-label="Message to Mechanic"
            data-target="chat_input eingabe"
            className={`min-w-0 resize-none bg-transparent font-read text-ink outline-none placeholder:text-faint ${
              lg ? "w-full text-[19px] leading-[1.5] sm:text-[22px]" : stacked ? "w-full pr-1 text-[15px] leading-snug" : "flex-1 self-center text-[15px] leading-snug @max-[360px]:w-full @max-[360px]:flex-none @max-[360px]:pr-1"
            }`}
          />
        )}
        <div className={lg || stacked ? "flex items-center justify-end gap-2" : "contents @max-[360px]:flex @max-[360px]:items-center @max-[360px]:justify-end @max-[360px]:gap-2"}>
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
        <PrinterButton size={lg ? "lg" : "sm"} />
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
            setHint(null);
            if (handsFree) stopVoice();
            else void startVoice();
          }}
          className={`flex shrink-0 items-center justify-center gap-1.5 rounded-full font-semibold transition select-none ${
            micHot ? "bg-accent text-white shadow-[0_0_0_6px_rgb(31_111_120/0.16)]" : "bg-tile text-ink-2 hover:bg-track hover:text-ink"
          } ${micMode === "handsfree" ? (lg ? "h-11 px-4 text-[15px]" : "h-9 px-3 text-[13px]") : lg ? "h-11 w-11" : "h-9 w-9"}`}
          title={stt === "none" && micMode === "ptt" ? "No speech recognition in this browser" : micMode === "ptt" ? "Hold to speak, or hold space" : handsFree ? "End the voice conversation" : "Talk to Mechanic"}
          aria-label={micMode === "ptt" ? "Hold to speak" : handsFree ? "End the voice conversation" : "Talk to Mechanic"}
          aria-pressed={micMode === "handsfree" ? handsFree : undefined}
        >
          {micMode === "handsfree" && handsFree ? <Waveform active={speaking || userTalking} bars={4} className="[&>span]:bg-white" /> : <Mic className={lg ? "h-5 w-5" : "h-4 w-4"} strokeWidth={2} />}
          {/* The large box on a phone is too narrow for its row of big buttons: the mic stays, the word goes (the button names itself). */}
          {micMode === "handsfree" && <span className={lg ? "@max-[340px]:hidden" : ""}>{handsFree ? "End" : "Talk"}</span>}
        </button>
        </div>
      </div>
      {hint ? (
        <p className="mt-1.5 px-2 text-[12px] text-agent-ink">{hint}</p>
      ) : handsFree && micMode === "handsfree" ? (
        <p className="mt-1.5 px-2 text-[12px] text-agent-ink">Live with Mechanic. Just talk; press End to stop.</p>
      ) : null}
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
