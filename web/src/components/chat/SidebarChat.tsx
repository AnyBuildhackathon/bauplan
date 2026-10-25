// Adapted from core-oss (github.com/10xapp/core-oss, Apache-2.0),
// core-web/src/components/SidebarChat/SidebarChat.tsx. Modified: driven by our SSE
// session store instead of core.so's conversation API, Mechanic's state in the
// header, tool cards inline with the messages (repeats grouped into one card), a
// speaker toggle for Mechanic's voice, Bevel styling. The scroll handling is kept from core-oss.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowDown, CornerDownRight, GitFork, ImagePlus, Maximize2, Minimize2, RotateCcw, Volume2, VolumeX } from "lucide-react";
import { currentStep, useSession } from "../../events/store";
import { useSource } from "../../events/source";
import { assetUrl } from "../../lib/api";
import { keyFact, STARTER_PROMPTS, starterCards } from "./starterCards";
import { useUi, type Display } from "../../lib/ui";
import { MASCOT_LABEL, MascotFull } from "../mascot/Mascot";
import type { ChatItem } from "../../events/store";
import ContentPartsRenderer, { ProgressLineRenderer, ToolGroupRenderer } from "./ContentPartsRenderer";
import ChatMessage from "./SidebarChatMessage";
import SidebarChatInput from "./SidebarChatInput";
import RunControls from "./RunControls";
import { useSketchDrop } from "./SketchDrop";
import { ConfirmDesign } from "./ConfirmDesign";

const FRESH_MS = 2500;

type ToolItem = Extract<ChatItem, { kind: "tool" }>;
type Row =
  | ChatItem
  | { kind: "toolGroup"; id: string; at: number; items: ToolItem[] }
  | { kind: "progress"; id: string; at: number; items: ToolItem[] };

/** Consecutive finished calls of one tool (five part choices) collapse into one card.
 * With tool details hidden, every run of tool calls folds into one quiet progress line. */
function group(chat: ChatItem[], display: Display): Row[] {
  const rows: Row[] = [];
  for (const item of chat) {
    if (item.kind === "agent" && !display.agents) continue;
    if (item.kind === "explain" && !display.learning) continue;
    const last = rows.at(-1);
    if (item.kind === "tool" && !display.tools) {
      if (last?.kind === "progress") rows[rows.length - 1] = { ...last, items: [...last.items, item] };
      else rows.push({ kind: "progress", id: item.id, at: item.at, items: [item] });
      continue;
    }
    if (
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

function fillComposer(prompt: string, setInput: (value: string) => void) {
  setInput(prompt);
  requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('[data-target~="chat_input"]')?.focus());
}

export default function SidebarChat() {
  const chat = useSession((s) => s.chat);
  const display = useUi((s) => s.display);
  const rows = useMemo(() => group(chat, display), [chat, display]);
  const mascot = useSession((s) => s.mascot);
  const productLabel = useSession((s) => s.productLabel);
  const remixedFrom = useSession((s) => s.remixedFrom);
  const openCommunity = useUi((s) => s.openCommunity);
  const product = useSession((s) => s.product);
  const steps = useSession((s) => s.steps);
  const sendPrompt = useSource((s) => s.sendPrompt);
  const sendSketch = useSource((s) => s.sendSketch);
  const sendSampleSketch = useSource((s) => s.sendSampleSketch);
  const startReference = useSource((s) => s.startReference);
  const allReferences = useSource((s) => s.references);
  const live = useSource((s) => s.mode === "live");
  const references = live ? allReferences : [];
  const resetSession = useSource((s) => s.resetSession);
  const resetUi = useUi((s) => s.resetUi);
  const voiceOn = useUi((s) => s.voiceOn);
  const setVoiceOn = useUi((s) => s.setVoiceOn);
  const expanded = useUi((s) => s.chatExpanded);
  const setExpanded = useUi((s) => s.setChatExpanded);
  // Expanded, the chat keeps a readable line length in the middle of the window.
  const column = expanded ? "mx-auto w-full max-w-[780px]" : "";
  useEffect(() => {
    if (!expanded) return;
    const collapse = (e: KeyboardEvent) => e.key === "Escape" && setExpanded(false);
    window.addEventListener("keydown", collapse);
    return () => window.removeEventListener("keydown", collapse);
  }, [expanded, setExpanded]);

  const [input, setInput] = useState("");
  const [sketch, setSketch] = useState<File | null>(null);
  const drop = useSketchDrop(live, setSketch, (text) => useSource.setState({ notice: text }));
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const stickToBottom = useRef(true);
  const step = currentStep(steps);
  const isEmpty = chat.length === 0;
  const cards = useMemo(() => starterCards(references), [references]);
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
    <div className="relative flex h-full min-h-0 flex-col overflow-hidden bg-page" data-target="chat" {...drop.handlers}>
      {drop.overlay}
      {/* Header */}
      <div className="mx-5 flex h-[56px] shrink-0 items-center gap-3 border-b border-line">
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate text-[15px] font-semibold text-ink">{productLabel || "Mechanic"}</div>
          <div className={`truncate font-label text-[11px] ${stateTone}`}>
            Mechanic · {MASCOT_LABEL[mascot.state]}
            {working && <span className="text-muted"> · {step.label}</span>}
          </div>
        </div>
        <button
          onClick={() => setVoiceOn(!voiceOn)}
          data-control="setting:voice"
          className={`rounded-full p-2 transition-colors hover:bg-tile ${voiceOn ? "text-accent" : "text-faint hover:text-ink-2"}`}
          title={voiceOn ? "Mechanic is speaking" : "Mechanic is muted"}
          aria-label={voiceOn ? "Mute Mechanic" : "Let Mechanic speak"}
          aria-pressed={voiceOn}
        >
          {voiceOn ? <Volume2 className="h-4.5 w-4.5" /> : <VolumeX className="h-4.5 w-4.5" />}
        </button>
        <button
          onClick={() => setExpanded(!expanded)}
          className={`rounded-full p-2 transition-colors hover:bg-tile ${expanded ? "text-ink-2" : "text-faint hover:text-ink-2"}`}
          title={expanded ? "Back to the side column (Esc)" : "Expand the chat"}
          aria-label={expanded ? "Collapse the chat" : "Expand the chat"}
          aria-pressed={expanded}
          data-target="chat_expand"
        >
          {expanded ? <Minimize2 className="h-4.5 w-4.5" /> : <Maximize2 className="h-4.5 w-4.5" />}
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
      {remixedFrom && (
        <button
          type="button"
          onClick={() => openCommunity(remixedFrom.id)}
          data-target="remixed_from"
          className="mx-6 mt-2 flex shrink-0 items-center gap-1.5 self-start rounded-full bg-tile px-3 py-1 text-[13px] font-medium text-ink-2 transition hover:bg-track"
          title="Open the original in the community"
        >
          <GitFork className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">
            Remixed from {remixedFrom.title} by {remixedFrom.author}
          </span>
        </button>
      )}

      {/* Content */}
      <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
        {/* Expanded, the wide chat has room for Mechanic head to toe beside the column. */}
        {expanded && !isEmpty && (
          <div className="pointer-events-none absolute bottom-2 left-6 hidden min-[1300px]:block">
            <MascotFull state={mascot.state} height={360} />
          </div>
        )}
        {isEmpty ? (
          <div className="@container scroll-soft flex min-h-0 flex-1 flex-col overflow-y-auto">
            <div className={`m-auto flex w-full flex-col gap-4 py-4 ${column}`}>
              <div className="flex items-center gap-3 px-5">
                <MascotFull state={mascot.state} height={104} />
                <div className="min-w-0 text-left">
                  <p className="text-[17px] font-semibold leading-snug text-ink">“So. What are we building?”</p>
                  <p className="mt-0.5 text-[14px] leading-snug text-muted">Rebuild a reference, or describe something new.</p>
                </div>
              </div>
              {cards.length > 0 && (
                <div className="grid grid-cols-1 gap-2 px-5 @min-[520px]:grid-cols-2">
                  {cards.map((ref) => {
                    const thumb = assetUrl(ref.thumbnail_url);
                    return (
                      <button
                        key={ref.id}
                        type="button"
                        onClick={() => void startReference(ref.id)}
                        title={ref.summary}
                        data-target={`reference:${ref.id}`}
                        className="flex min-w-0 items-center gap-2.5 rounded-[16px] bg-card p-1.5 pr-3 text-left shadow-[var(--shadow-card)] transition hover:bg-page-2"
                      >
                        <span className="h-14 w-[4.5rem] shrink-0 overflow-hidden rounded-[12px] bg-stage">
                          {thumb ? <img src={thumb} alt="" className="h-full w-full object-cover" /> : null}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="line-clamp-2 text-[14px] font-semibold leading-snug text-ink">{ref.name}</span>
                          <span className="num mt-0.5 block truncate text-[13px] font-medium text-ink-2">{keyFact(ref)}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
              {live && (
                <div className="flex flex-col px-3">
                  {STARTER_PROMPTS.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      onClick={() => fillComposer(prompt, setInput)}
                      data-target={`prompt:${prompt}`}
                      className="rounded-xl px-2 py-1.5 text-left text-[14px] leading-snug text-muted transition hover:bg-tile hover:text-ink"
                    >
                      {prompt}
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => void sendSampleSketch()}
                    data-target="example:sketch"
                    title="Build from a photo of a hand-drawn phone stand"
                    className="mt-0.5 flex items-center gap-1.5 self-start rounded-xl px-2 py-1.5 text-[13px] font-semibold text-ink-2 transition hover:bg-tile hover:text-ink"
                  >
                    <ImagePlus className="h-3.5 w-3.5" />
                    Start from a sketch
                  </button>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div
            ref={scrollContainerRef}
            className="scroll-soft flex-1 overflow-y-auto px-5 [mask-image:linear-gradient(to_bottom,transparent,black_28px)]"
          >
            <div className={`space-y-1.5 pt-3 pb-3 ${column}`}>
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
                    ) : item.kind === "toolGroup" ? (
                      <div className="py-0.5">
                        <ToolGroupRenderer items={item.items} />
                      </div>
                    ) : item.kind === "msg" ? (
                      <ChatMessage
                        role={item.role}
                        content={item.text}
                        voice={item.voice}
                        animate={item.role === "agent" && Date.now() - item.at < FRESH_MS}
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
              <ConfirmDesign onShow={onRevealProgress} />
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
          <div className={`shrink-0 px-5 pb-1 ${column}`} data-target="follow_ups">
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
        <div className={`shrink-0 px-5 pt-2 pb-4 ${column}`}>
          <RunControls />
          <SidebarChatInput
            value={input}
            onChange={setInput}
            onSubmit={send}
            sketch={sketch}
            onSketchChange={live ? setSketch : undefined}
            onSendSketch={(image, note) => {
              stickToBottom.current = true;
              void sendSketch(image, note);
            }}
            onVoice={(text) => {
              stickToBottom.current = true;
              void sendPrompt(text, true);
            }}
          />
        </div>
      </div>
    </div>
  );
}
