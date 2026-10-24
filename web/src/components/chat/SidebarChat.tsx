// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/SidebarChat/SidebarChat.tsx. Modified: driven by our SSE
// session store instead of core.so's conversation API, Bolzen's state in the
// header, tool cards inline with the messages (repeats grouped into one card), a
// speaker toggle for Bolzen's voice, Bevel styling. The scroll handling is kept from core-oss.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowDown, CornerDownRight, RotateCcw, Volume2, VolumeX } from "lucide-react";
import { currentStep, useSession } from "../../events/store";
import { useSource } from "../../events/source";
import { useUi, type Display } from "../../lib/ui";
import { MASCOT_LABEL, MascotLive } from "../mascot/Mascot";
import type { ChatItem } from "../../events/store";
import ContentPartsRenderer, { JamieGroupRenderer, ProgressLineRenderer, ToolGroupRenderer } from "./ContentPartsRenderer";
import ChatMessage from "./SidebarChatMessage";
import SidebarChatInput from "./SidebarChatInput";

const FRESH_MS = 2500;

type JamieItem = Extract<ChatItem, { kind: "jamie" }>;
type ToolItem = Extract<ChatItem, { kind: "tool" }>;
type Row =
  | ChatItem
  | { kind: "jamieGroup"; id: string; at: number; items: JamieItem[] }
  | { kind: "toolGroup"; id: string; at: number; items: ToolItem[] }
  | { kind: "progress"; id: string; at: number; items: ToolItem[] };

/** Consecutive Jamie actions, and consecutive finished calls of one tool (five part choices), collapse into one card.
 * With tool details hidden, every run of tool calls folds into one quiet progress line. */
function group(chat: ChatItem[], display: Display): Row[] {
  const rows: Row[] = [];
  for (const item of chat) {
    if (item.kind === "agent" && !display.agents) continue;
    if (item.kind === "jamie" && !display.jamie) continue;
    const last = rows.at(-1);
    if (item.kind === "tool" && !display.tools) {
      if (last?.kind === "progress") rows[rows.length - 1] = { ...last, items: [...last.items, item] };
      else rows.push({ kind: "progress", id: item.id, at: item.at, items: [item] });
      continue;
    }
    if (item.kind === "jamie" && last && (last.kind === "jamie" || last.kind === "jamieGroup")) {
      const items = last.kind === "jamie" ? [last, item] : [...last.items, item];
      rows[rows.length - 1] = { kind: "jamieGroup", id: items[0].id, at: items[0].at, items };
    } else if (
      item.kind === "tool" &&
      item.phase === "ok" &&
      last &&
      ((last.kind === "tool" && last.phase === "ok" && last.name === item.name) || (last.kind === "toolGroup" && last.items[0].name === item.name))
    ) {
      const items = last.kind === "tool" ? [last, item] : [...(last as Extract<Row, { kind: "toolGroup" }>).items, item];
      rows[rows.length - 1] = { kind: "toolGroup", id: items[0].id, at: items[0].at, items };
    } else {
      rows.push(item);
    }
  }
  return rows;
}

/** Follow-ups under the conversation, like the suggestions under an answer. */
const FOLLOW_UPS: Record<string, string[]> = {
  drone: ["Make it lighter", "Why this battery?"],
  default: ["Make it lighter", "Make it cheaper"],
};

/** Starting points that show AnyBuild builds more than the drone. */
const EXAMPLES = [
  { label: "Phone stand", prompt: "Design a phone stand for my desk that holds my phone for video calls. It must not tip when I tap the screen and cost under 6 €." },
  { label: "Desk fan", prompt: "Design a small USB desk fan that stands stable on the desk, under 300 g and 25 €." },
  { label: "Plant-watering robot", prompt: "Design a plant-watering robot for one pot: a water tank, a pump and a soil sensor, running a month on a battery, under 40 €." },
  { label: "Drone", prompt: "Build the small drone from the kickoff." },
  { label: "Robot gripper", prompt: "Design a robot gripper for our arm that picks up a 200 g soda can, 66 mm wide. Keep it under 150 g and 30 €." },
];

export default function SidebarChat() {
  const allChat = useSession((s) => s.chat);
  // A Jamie tool call and its Jamie action card describe the same thing; keep the action card.
  const chat = useMemo(
    () =>
      allChat.filter(
        (c) => !(c.kind === "tool" && c.name === "Jamie" && allChat.some((j) => j.kind === "jamie" && Math.abs(j.seq - c.seq) <= 2)),
      ),
    [allChat],
  );
  const display = useUi((s) => s.display);
  const rows = useMemo(() => group(chat, display), [chat, display]);
  const mascot = useSession((s) => s.mascot);
  const productLabel = useSession((s) => s.productLabel);
  const product = useSession((s) => s.product);
  const steps = useSession((s) => s.steps);
  const sendPrompt = useSource((s) => s.sendPrompt);
  const startReference = useSource((s) => s.startReference);
  const allReferences = useSource((s) => s.references);
  const live = useSource((s) => s.mode === "live");
  const references = live ? allReferences : [];
  const resetSession = useSource((s) => s.resetSession);
  const resetUi = useUi((s) => s.resetUi);
  const voiceOn = useUi((s) => s.voiceOn);
  const setVoiceOn = useUi((s) => s.setVoiceOn);

  const [input, setInput] = useState("");
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const stickToBottom = useRef(true);
  const step = currentStep(steps);
  const isEmpty = chat.length === 0;
  const working = Object.values(steps).some((s) => s.status === "running");

  // Check scroll position
  const checkScrollPosition = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const threshold = 100;
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
    stickToBottom.current = isNearBottom;
    setShowScrollButton(!isNearBottom);
  }, []);

  const scrollToBottom = useCallback((smooth = true) => {
    const container = scrollContainerRef.current;
    if (container) container.scrollTo({ top: container.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  }, []);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.addEventListener("scroll", checkScrollPosition);
    return () => container.removeEventListener("scroll", checkScrollPosition);
  }, [checkScrollPosition, isEmpty]);

  // Auto-scroll when new content arrives, unless the reader scrolled up.
  useEffect(() => {
    if (stickToBottom.current) scrollToBottom(false);
  }, [chat, scrollToBottom]);
  const onRevealProgress = useCallback(() => {
    if (stickToBottom.current) scrollToBottom(false);
  }, [scrollToBottom]);

  const send = () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    stickToBottom.current = true;
    void sendPrompt(text);
  };

  const stateTone =
    mascot.state === "freut_sich" ? "text-ok-ink" : mascot.state === "besorgt" ? "text-fail-ink" : "text-agent-ink";

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-page" data-target="chat">
      {/* Header */}
      <div className="mx-5 flex h-[56px] shrink-0 items-center gap-3 border-b border-line">
        <div data-target="mascot bolzen" className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full bg-tile">
          <MascotLive state={mascot.state} size={40} crop="head" />
        </div>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-[15px] font-semibold text-ink">{productLabel || "Mechanic"}</div>
          <div className={`truncate text-[12px] font-medium ${stateTone}`}>
            Mechanic · {MASCOT_LABEL[mascot.state]}
            {working && <span className="text-muted"> · {step.label}</span>}
          </div>
        </div>
        <button
          onClick={() => setVoiceOn(!voiceOn)}
          className={`rounded-full p-2 transition-colors hover:bg-tile ${voiceOn ? "text-accent" : "text-faint hover:text-ink-2"}`}
          title={voiceOn ? "Mechanic is speaking" : "Mechanic is muted"}
          aria-label={voiceOn ? "Mute Mechanic" : "Let Mechanic speak"}
          aria-pressed={voiceOn}
        >
          {voiceOn ? <Volume2 className="h-4.5 w-4.5" /> : <VolumeX className="h-4.5 w-4.5" />}
        </button>
        <button
          onClick={() => {
            resetUi();
            void resetSession();
          }}
          className="-mr-2 rounded-full p-2 text-faint transition-colors hover:bg-tile hover:text-ink-2"
          title="Start over"
          aria-label="Start over"
        >
          <RotateCcw className="h-4.5 w-4.5" />
        </button>
      </div>

      {/* Content */}
      <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
        {isEmpty ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
            <MascotLive state={mascot.state} size={200} className="rounded-[32px]" />
            <p className="text-[17px] font-semibold text-ink-2">“So. What are we building?”</p>
            {!live ? (
              <>
                <p className="text-[15px] text-muted">This is the recorded drone run, not a live build. Start the backend to build any product.</p>
                <button
                  type="button"
                  onClick={() => useSource.getState().play()}
                  className="mt-1 h-9 rounded-full bg-ink px-4 text-[14px] font-semibold text-white transition hover:bg-[#333]"
                >
                  Play the recording
                </button>
              </>
            ) : (
              <p className="text-[15px] text-muted">Start from a reference build and change it, or describe any product from scratch.</p>
            )}
            {references.length > 0 && (
              <div className="mt-1 w-full">
                <p className="eyebrow mb-1.5">From a reference</p>
                <div className="flex flex-wrap justify-center gap-2">
                  {references.map((ref) => (
                    <button
                      key={ref.id}
                      type="button"
                      onClick={() => void startReference(ref.id)}
                      title={ref.summary}
                      data-target={`reference:${ref.id}`}
                      className="h-9 rounded-full bg-accent-soft px-4 text-[14px] font-semibold text-accent transition hover:brightness-95"
                    >
                      {ref.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {live && <p className="eyebrow mt-2 -mb-1.5">From scratch</p>}
            <div className={`mt-1 flex-wrap justify-center gap-2 ${live ? "flex" : "hidden"}`}>
              {EXAMPLES.map((example) => (
                <button
                  key={example.label}
                  type="button"
                  onClick={() => void sendPrompt(example.prompt)}
                  data-target={`example:${example.label}`}
                  className="h-9 rounded-full bg-tile px-4 text-[14px] font-semibold text-ink-2 transition hover:bg-track"
                >
                  {example.label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div
            ref={scrollContainerRef}
            className="scroll-soft flex-1 overflow-y-auto px-5 [mask-image:linear-gradient(to_bottom,transparent,black_28px)]"
          >
            <div className="space-y-1.5 pt-3 pb-3">
              <AnimatePresence initial={false}>
                {rows.map((item) => (
                  <motion.div
                    key={item.id}
                    initial={Date.now() - item.at < FRESH_MS ? { opacity: 0, y: 8 } : false}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25, ease: [0.2, 0.8, 0.2, 1] }}
                  >
                    {item.kind === "progress" ? (
                      <ProgressLineRenderer items={item.items} />
                    ) : item.kind === "jamieGroup" ? (
                      <div className="py-0.5">
                        <JamieGroupRenderer items={item.items} />
                      </div>
                    ) : item.kind === "toolGroup" ? (
                      <div className="py-0.5">
                        <ToolGroupRenderer items={item.items} />
                      </div>
                    ) : item.kind === "msg" ? (
                      <ChatMessage
                        role={item.role}
                        content={item.text}
                        animate={item.role === "agent" && Date.now() - item.at < FRESH_MS}
                        mascot={mascot.state}
                        onRevealProgress={onRevealProgress}
                      />
                    ) : (
                      <div className="py-0.5">
                        <ContentPartsRenderer item={item} />
                      </div>
                    )}
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          </div>
        )}

        {/* Scroll to bottom button */}
        {showScrollButton && !isEmpty && (
          <button
            onClick={() => scrollToBottom()}
            className="absolute bottom-[96px] left-1/2 flex h-8 w-8 -translate-x-1/2 items-center justify-center rounded-full bg-card text-muted shadow-[var(--shadow-pill)] transition-colors hover:text-ink"
            aria-label="Scroll to bottom"
          >
            <ArrowDown className="h-4 w-4" />
          </button>
        )}

        {/* Follow-up suggestions */}
        {!isEmpty && !working && live && (
          <div className="shrink-0 px-5 pb-1" data-target="follow_ups">
            {(FOLLOW_UPS[product ?? ""] ?? FOLLOW_UPS.default).map((text) => (
              <button
                key={text}
                type="button"
                onClick={() => {
                  stickToBottom.current = true;
                  void sendPrompt(text);
                }}
                className="flex w-full items-center gap-2.5 border-t border-line py-2 text-left text-[14px] text-ink-2 transition hover:text-ink"
              >
                <CornerDownRight className="h-3.5 w-3.5 shrink-0 text-faint" />
                {text}
              </button>
            ))}
          </div>
        )}

        {/* Input */}
        <div className="shrink-0 px-5 pt-2 pb-4">
          <SidebarChatInput
            value={input}
            onChange={setInput}
            onSubmit={send}
            onVoice={(text) => {
              stickToBottom.current = true;
              void sendPrompt(text);
            }}
          />
        </div>
      </div>
    </div>
  );
}
