// The bench before anything has started: one big box asking what to build, with a large
// prompt field and one quiet line of suggestions, and Mechanic peeking over its top edge.
// The first prompt, suggestion, spoken sentence, sketch, meeting or agent event fills the
// chat, and App swaps this for the normal bench.
import { useState, type CSSProperties } from "react";
import { useSource } from "../events/source";
import SidebarChatInput from "../components/chat/SidebarChatInput";
import { useSketchDrop } from "../components/chat/SketchDrop";
import { EXAMPLES } from "../components/chat/examples";
import { HEAD_ABOVE, MechanicPeek } from "../components/start/MechanicPeek";

/** The reference builds offered on the start screen, with short labels for the one-line row. */
const SUGGESTED_REFERENCES: { id: string; label: string }[] = [
  { id: "micro-drone", label: "Micro drone" },
  { id: "robot-gripper", label: "Robot gripper" },
  { id: "desk-lamp", label: "Desk lamp" },
  { id: "pet-feeder", label: "Pet feeder" },
];
const SCRATCH = EXAMPLES.find((e) => e.label === "Phone stand") ?? EXAMPLES[0];

const suggestion =
  "h-8 shrink-0 rounded-full px-3.5 text-[13px] font-medium text-muted ring-1 ring-line transition hover:bg-tile hover:text-ink hover:ring-transparent focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none";

export function StartScreen() {
  const sendPrompt = useSource((s) => s.sendPrompt);
  const sendSketch = useSource((s) => s.sendSketch);
  const startReference = useSource((s) => s.startReference);
  const allReferences = useSource((s) => s.references);
  const live = useSource((s) => s.mode === "live");
  const references = live
    ? SUGGESTED_REFERENCES.flatMap((s) => {
        const ref = allReferences.find((r) => r.id === s.id);
        return ref ? [{ ...ref, label: s.label }] : [];
      })
    : [];
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
    <div className="scroll-soft flex h-full overflow-x-hidden overflow-y-auto bg-page bg-[radial-gradient(ellipse_70%_55%_at_55%_42%,#ffffff_0%,rgb(255_255_255/0)_70%)] px-4 sm:px-8">
      <div
        className="relative m-auto w-full max-w-[1000px] animate-rise py-6"
        style={{ "--u": "clamp(0.5px, min(0.08vw, 0.085vh), 1px)", paddingTop: `calc(var(--u) * ${HEAD_ABOVE} + 24px)` } as CSSProperties}
      >
        <div className="absolute inset-x-0 top-6 bottom-6">
          <MechanicPeek />
        </div>
        <section
          aria-labelledby="start-title"
          className="relative z-10 rounded-[28px] bg-[linear-gradient(180deg,#ffffff_0%,#fcfcfa_100%)] px-5 pt-9 pb-6 shadow-[inset_0_1px_0_#ffffff,0_0_0_1px_rgb(26_26_24/0.06),0_1px_2px_rgb(26_26_24/0.04),0_12px_32px_-12px_rgb(26_26_24/0.14),0_48px_96px_-32px_rgb(26_26_24/0.2)] sm:px-12 sm:pt-12 sm:pb-9 lg:px-14"
          {...drop.handlers}
        >
          {drop.overlay}
          <h1 id="start-title" className="text-[clamp(32px,4.3vw,60px)] leading-[1.02] font-semibold tracking-[-0.035em] text-balance text-ink">
            What are we building today?
          </h1>
          <p className="mt-3 max-w-[64ch] text-pretty text-[clamp(15px,1.3vw,18px)] leading-snug text-muted">
            Start from a reference build and change it, or describe any product from scratch.
          </p>
          <div className="mt-7 sm:mt-9">
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
            // One line only: on a narrow screen the row scrolls within itself.
            <div className="mt-5 -mr-5 flex items-center gap-2 overflow-x-auto pr-5 [mask-image:linear-gradient(to_right,black_calc(100%-32px),transparent)] [scrollbar-width:none] sm:mr-0 sm:pr-0 sm:[mask-image:none]">
              <span className="shrink-0 pr-1 text-[13px] text-faint">Try</span>
              {references.map((ref) => (
                <button
                  key={ref.id}
                  type="button"
                  onClick={() => void startReference(ref.id)}
                  title={ref.name}
                  data-target={`reference:${ref.id}`}
                  className={suggestion}
                >
                  {ref.label}
                </button>
              ))}
              <button
                type="button"
                onClick={() => void sendPrompt(SCRATCH.prompt)}
                title="Design it from scratch"
                data-target={`example:${SCRATCH.label}`}
                className={suggestion}
              >
                {SCRATCH.label}
              </button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
