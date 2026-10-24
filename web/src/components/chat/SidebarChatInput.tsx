// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/SidebarChat/SidebarChatInput.tsx. Modified: Bevel pill
// styling, a push-to-talk mic button (hold the button or the space bar) in place
// of attachments and mentions; speech goes to Reson8 or the browser (lib/voice.ts).
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Mic } from "lucide-react";
import { useUi } from "../../lib/ui";
import { startListening as listen, type Listener } from "../../lib/voice";

interface SidebarChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  /** A finished spoken sentence, sent as it is. */
  onVoice?: (text: string) => void;
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
          className="w-[3px] rounded-full bg-agent transition-[height]"
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
  disabled = false,
  placeholder = "Say or type what to build or change",
  size = "md",
}: SidebarChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const listening = useUi((s) => s.listening);
  const setListening = useUi((s) => s.setListening);
  const [hint, setHint] = useState<string | null>(null);
  const lg = size === "lg";

  // Auto-resize textarea without causing layout flash
  const adjustHeight = useCallback(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const min = lg ? 28 : 22;
    textarea.style.height = `${min}px`;
    textarea.style.height = `${Math.min(Math.max(textarea.scrollHeight, min), 120)}px`;
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

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSubmit) onSubmit();
    }
  };

  const canSubmit = value.trim().length > 0 && !disabled;

  return (
    <div>
      <div
        className={`flex items-center gap-2 rounded-[26px] bg-card shadow-[var(--shadow-pill)] ring-1 transition ${
          listening ? "ring-agent/60" : "ring-line"
        } ${lg ? "min-h-[72px] py-3 pr-3 pl-6" : "min-h-[60px] py-2.5 pr-2.5 pl-4.5"}`}
      >
        {listening ? (
          <div className="flex flex-1 items-center gap-3">
            <Waveform active bars={lg ? 11 : 7} />
            <span className={`line-clamp-2 font-semibold ${heard ? "text-ink" : "text-agent-ink"} ${lg ? "text-[20px]" : "text-[15px]"}`}>
              {heard || (stt === "reson8" ? "Reson8 is listening…" : "Listening…")}
            </span>
          </div>
        ) : (
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            rows={1}
            name="prompt"
            aria-label="Message to Mechanic"
            data-target="chat_input eingabe"
            className={`min-w-0 flex-1 resize-none bg-transparent leading-snug text-ink outline-none placeholder:text-faint ${
              lg ? "text-[20px]" : "text-[15px]"
            }`}
          />
        )}
        {canSubmit && !listening && (
          <button
            type="button"
            onClick={onSubmit}
            className={`flex shrink-0 items-center justify-center rounded-full bg-ink text-white transition hover:bg-[#333] ${lg ? "h-12 w-12" : "h-10 w-10"}`}
            title="Send"
          >
            <ArrowUp className={lg ? "h-5 w-5" : "h-4.5 w-4.5"} strokeWidth={2.5} />
          </button>
        )}
        <button
          type="button"
          data-target="mic reson8_mic"
          onPointerDown={(e) => {
            e.preventDefault();
            startListening();
          }}
          onPointerUp={() => void stopListening()}
          onPointerLeave={() => void stopListening()}
          className={`flex shrink-0 items-center justify-center rounded-full text-white transition select-none ${
            listening ? "scale-105 bg-agent shadow-[0_0_0_8px_rgb(255_138_61/0.18)]" : "bg-agent shadow-[0_8px_20px_-8px_rgb(255_138_61/0.8)] hover:brightness-105"
          } ${lg ? "h-14 w-14" : "h-10 w-10"}`}
          title="Hold to speak"
        >
          <Mic className={lg ? "h-6 w-6" : "h-4.5 w-4.5"} strokeWidth={2.4} />
        </button>
      </div>
      <div className={`mt-2 flex items-center justify-between px-2 text-[13px] ${hint ? "text-agent-ink" : "text-faint"}`}>
        <span>{hint ?? (stt === "none" ? "Type and press Enter" : "Hold space to speak")}</span>
        {!hint && <span>{stt === "reson8" ? "Reson8 · English" : stt === "browser" ? "Browser · English" : ""}</span>}
      </div>
    </div>
  );
}
