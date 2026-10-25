// The bench before anything has started: one big box asking what to build, with reference
// cards, a large prompt field and a few ghost prompts, and Mechanic peeking over its top edge.
// The first prompt, card, spoken sentence, sketch or agent event fills the
// chat, and App swaps this for the normal bench.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { ImagePlus } from "lucide-react";
import { useSource } from "../events/source";
import { assetUrl } from "../lib/api";
import SidebarChatInput from "../components/chat/SidebarChatInput";
import { useSketchDrop } from "../components/chat/SketchDrop";
import { keyFact, STARTER_PROMPTS, starterCards } from "../components/chat/starterCards";
import { HEAD_ABOVE, MechanicPeek } from "../components/start/MechanicPeek";

/** `leaving`: the bench is taking over; the box stays where it was, fades and settles, then App drops it. */
export function StartScreen({ leaving = false }: { leaving?: boolean }) {
  const root = useRef<HTMLDivElement>(null);
  // Where the screen sat before the bench took the room, so it can fade out in place.
  const place = useRef<DOMRect | null>(null);
  useLayoutEffect(() => {
    if (!leaving && root.current) place.current = root.current.getBoundingClientRect();
  });
  useEffect(() => {
    if (!leaving) return;
    root.current?.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateY(-10px) scale(0.985)" }], {
      duration: 420,
      easing: "cubic-bezier(0.4, 0, 0.2, 1)",
      fill: "forwards",
    });
  }, [leaving]);
  const at = leaving ? place.current : null;
  const sendPrompt = useSource((s) => s.sendPrompt);
  const sendSketch = useSource((s) => s.sendSketch);
  const sendSampleSketch = useSource((s) => s.sendSampleSketch);
  const startReference = useSource((s) => s.startReference);
  const allReferences = useSource((s) => s.references);
  const live = useSource((s) => s.mode === "live");
  const cards = useMemo(() => (live ? starterCards(allReferences) : []), [live, allReferences]);
  const [input, setInput] = useState("");
  const [sketch, setSketch] = useState<File | null>(null);
  const drop = useSketchDrop(live, setSketch, (text) => useSource.setState({ notice: text }));

  const send = () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    void sendPrompt(text);
  };

  return (
    <div
      ref={root}
      aria-hidden={leaving || undefined}
      style={at ? { position: "fixed", left: at.left, top: at.top, width: at.width, height: at.height, zIndex: 40, pointerEvents: "none" } : undefined}
      className="scroll-soft flex h-full overflow-x-hidden overflow-y-auto bg-page bg-[radial-gradient(ellipse_70%_55%_at_55%_42%,#ffffff_0%,rgb(255_255_255/0)_70%)] px-4 sm:px-8">
      <div
        className="relative m-auto w-full max-w-[1000px] animate-rise py-4"
        style={{ "--u": "clamp(0.5px, min(0.08vw, 0.085vh), 1px)", paddingTop: `calc(var(--u) * ${HEAD_ABOVE} + 24px)` } as CSSProperties}
      >
        <div className="absolute inset-x-0 top-6 bottom-6">
          <MechanicPeek />
        </div>
        <section
          aria-labelledby="start-title"
          className="relative z-10 rounded-[28px] bg-[linear-gradient(180deg,#ffffff_0%,#fcfcfa_100%)] px-5 pt-7 pb-4 shadow-[inset_0_1px_0_#ffffff,0_0_0_1px_rgb(26_26_24/0.06),0_1px_2px_rgb(26_26_24/0.04),0_12px_32px_-12px_rgb(26_26_24/0.14),0_48px_96px_-32px_rgb(26_26_24/0.2)] sm:px-10 sm:pt-8 sm:pb-5 lg:px-12"
          {...drop.handlers}
        >
          {drop.overlay}
          <h1 id="start-title" className="text-[clamp(32px,4.3vw,60px)] leading-[1.02] font-semibold tracking-[-0.035em] text-balance text-ink">
            What are we building today?
          </h1>
          <p className="mt-3 max-w-[64ch] text-pretty text-[clamp(15px,1.3vw,18px)] leading-snug text-muted">
            Rebuild a reference, or describe something new.
          </p>
          {cards.length > 0 && (
            <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
              {cards.slice(0, 3).map((ref) => {
                const thumb = assetUrl(ref.thumbnail_url);
                return (
                  <button
                    key={ref.id}
                    type="button"
                    onClick={() => void startReference(ref.id)}
                    title={ref.summary}
                    data-target={`reference:${ref.id}`}
                    className="flex min-w-0 items-center gap-2.5 rounded-[16px] bg-page p-1.5 pr-3 text-left ring-1 ring-line transition hover:bg-tile"
                  >
                    <span className="block h-14 w-[4.5rem] shrink-0 overflow-hidden rounded-[12px] bg-stage">
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
          <div className="mt-5 sm:mt-6">
            <SidebarChatInput
              size="lg"
              value={input}
              onChange={setInput}
              onSubmit={send}
              sketch={sketch}
              onSketchChange={live ? setSketch : undefined}
              onSendSketch={(image, note) => void sendSketch(image, note)}
              onVoice={(text) => void sendPrompt(text, true)}
            />
          </div>
          {live && (
            <div className="mt-3 flex flex-col">
              {STARTER_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => {
                    setInput(prompt);
                    requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('[data-target~="chat_input"]')?.focus());
                  }}
                  data-target={`prompt:${prompt}`}
                  className="rounded-xl px-1 py-1.5 text-left text-[15px] leading-snug text-muted transition hover:bg-tile hover:text-ink"
                >
                  {prompt}
                </button>
              ))}
              <button
                type="button"
                onClick={() => void sendSampleSketch()}
                data-target="example:sketch"
                title="Build from a photo of a hand-drawn phone stand"
                className="mt-0.5 flex items-center gap-1.5 self-start rounded-xl px-1 py-1.5 text-[14px] font-semibold text-ink-2 transition hover:bg-tile hover:text-ink"
              >
                <ImagePlus className="h-4 w-4" />
                Start from a sketch
              </button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
