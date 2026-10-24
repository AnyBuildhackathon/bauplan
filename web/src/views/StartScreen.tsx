// The bench before anything has started: one big box asking what to build, with the prompt
// field and the starting points, and Mechanic peeking over its top edge. The first prompt,
// chip, spoken sentence, sketch, meeting or replay event fills the chat, and App swaps this
// for the normal bench.
import { useState, type CSSProperties } from "react";
import { ImagePlus } from "lucide-react";
import { useSource } from "../events/source";
import SidebarChatInput from "../components/chat/SidebarChatInput";
import { useSketchDrop } from "../components/chat/SketchDrop";
import { useWindowWidth } from "../components/ui/ResizeHandle";
import { EXAMPLES } from "../components/chat/examples";
import { HEAD_ABOVE, MechanicPeek } from "../components/start/MechanicPeek";

const chip = "h-9 rounded-full px-4 text-[14px] font-semibold transition";

export function StartScreen() {
  const sendPrompt = useSource((s) => s.sendPrompt);
  const sendSketch = useSource((s) => s.sendSketch);
  const sendSampleSketch = useSource((s) => s.sendSampleSketch);
  const startReference = useSource((s) => s.startReference);
  const allReferences = useSource((s) => s.references);
  const live = useSource((s) => s.mode === "live");
  const references = live ? allReferences : [];
  const [input, setInput] = useState("");
  const [sketch, setSketch] = useState<File | null>(null);
  const drop = useSketchDrop(live, setSketch, (text) => useSource.setState({ notice: text }));
  // On a phone the large field leaves no room to type beside its buttons.
  const narrow = useWindowWidth() < 640;

  const send = () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    void sendPrompt(text);
  };

  return (
    <div className="scroll-soft flex h-full overflow-x-hidden overflow-y-auto bg-page px-4 sm:px-8">
      <div
        className="relative m-auto w-full max-w-[1040px] animate-rise py-6"
        style={{ "--u": "clamp(0.5px, min(0.08vw, 0.085vh), 1px)", paddingTop: `calc(var(--u) * ${HEAD_ABOVE} + 24px)` } as CSSProperties}
      >
        <div className="absolute inset-x-0 top-6 bottom-6">
          <MechanicPeek />
        </div>
        <section
          className="relative z-10 rounded-[var(--radius-card)] bg-card px-6 pt-9 pb-8 shadow-[var(--shadow-float)] sm:px-12 sm:pt-12 sm:pb-10 lg:px-16"
          aria-labelledby="start-title"
          {...drop.handlers}
        >
          {drop.overlay}
          <h1 id="start-title" className="text-[clamp(30px,4vw,56px)] leading-[1.04] font-semibold tracking-[-0.03em] text-balance text-ink">
            What are we building today?
          </h1>
          {live && (
            <p className="mt-3 max-w-[60ch] text-[clamp(16px,1.4vw,19px)] leading-snug text-muted">
              Start from a reference build and change it, or describe any product from scratch.
            </p>
          )}
          <div className="mt-7 sm:mt-9">
            <SidebarChatInput
              size={narrow ? "md" : "lg"}
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
            <div className="mt-7 grid gap-x-6 gap-y-3 sm:mt-8 sm:grid-cols-[max-content_minmax(0,1fr)] sm:items-baseline">
              {references.length > 0 && (
                <>
                  <p className="text-[14px] font-semibold text-faint sm:pt-2">From a reference</p>
                  <div className="flex flex-wrap gap-2">
                    {references.map((ref) => (
                      <button
                        key={ref.id}
                        type="button"
                        onClick={() => void startReference(ref.id)}
                        title={ref.summary}
                        data-target={`reference:${ref.id}`}
                        className={`${chip} bg-accent-soft text-accent hover:brightness-95`}
                      >
                        {ref.name}
                      </button>
                    ))}
                  </div>
                </>
              )}
              <p className="text-[14px] font-semibold text-faint sm:pt-2">From scratch</p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLES.map((example) => (
                  <button
                    key={example.label}
                    type="button"
                    onClick={() => void sendPrompt(example.prompt)}
                    data-target={`example:${example.label}`}
                    className={`${chip} bg-tile text-ink-2 hover:bg-track`}
                  >
                    {example.label}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => void sendSampleSketch()}
                  data-target="example:sketch"
                  title="Build from a photo of a hand-drawn phone stand"
                  className={`${chip} flex items-center gap-1.5 bg-tile text-ink-2 hover:bg-track`}
                >
                  <ImagePlus className="h-4 w-4" />
                  Phone stand sketch
                </button>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
