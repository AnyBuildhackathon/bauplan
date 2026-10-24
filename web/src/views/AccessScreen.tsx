// What shows before the bench: the access code field when the public backend asks for one,
// or a short offline note while the backend does not answer (it retries on its own).
// Both sit in one large box with Mechanic standing behind it: his head rises over the top
// edge and his fingers hang over its front, cut from the full figure by web/scripts/mascot_peek.py.
import { useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";
import { Logo } from "../components/TopBar";
import { StatusDot } from "../components/ui/primitives";
import { useSource } from "../events/source";

const peekAsset = (name: string) => `${import.meta.env.BASE_URL}mascot-peek/${name}`;

// Everything about Mechanic is measured in full-calm.webp pixels and drawn at --u per pixel,
// so head and hands keep the figure's own proportions at every screen size.
const u = (px: number) => `calc(var(--u) * ${px})`;
// The crops from mascot_peek.py: head 248 x 244 from y 22, hand 52 x 62.
const HEAD = { width: 248, height: 244 };
const HAND = { width: 52, height: 62 };
// How much of the head shows above the edge (hair top to the shirt collar).
const HEAD_ABOVE = 234;
// His right hand hangs 118 px left of his centre; the left hand mirrors it.
const HAND_OFFSET = 118;

export function AccessScreen() {
  const access = useSource((s) => s.access);
  const unlock = useSource((s) => s.unlock);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // While the first health check runs, the page stays quiet instead of flashing a screen.
  if (access === "checking") return <div className="h-full bg-page" />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setError(await unlock(code));
    setBusy(false);
  };

  return (
    <div className="flex h-full items-center justify-center overflow-hidden bg-page px-4">
      <div
        className="relative w-full max-w-[920px] animate-rise"
        style={{ "--u": "clamp(0.6px, min(0.075vw, 0.13vh), 1px)", paddingTop: u(HEAD_ABOVE) } as CSSProperties}
      >
        <MechanicHead />
        <div className="relative z-10 flex min-h-[clamp(300px,52vh,480px)] flex-col items-center justify-center rounded-[var(--radius-card)] bg-card px-6 py-12 shadow-[var(--shadow-float)]">
          <div className="w-full max-w-[400px]">
            <div className="flex items-center gap-3">
              <Logo size={44} />
              <h1 className="text-[22px] font-semibold tracking-tight text-ink">AnyBuild</h1>
            </div>
            {access === "offline" ? (
              <p role="status" className="mt-6 flex items-center gap-2.5 text-[15px] font-semibold text-ink-2">
                <StatusDot tone="agent" pulse />
                Live backend offline, try again shortly.
              </p>
            ) : (
              <form onSubmit={submit} className="mt-6">
                <label htmlFor="access-code" className="text-[15px] font-semibold text-ink-2">
                  Enter access code
                </label>
                <div className="mt-2 flex gap-2">
                  <input
                    id="access-code"
                    type="password"
                    autoComplete="off"
                    autoFocus
                    value={code}
                    onChange={(e) => {
                      setCode(e.target.value);
                      setError(null);
                    }}
                    aria-invalid={error ? true : undefined}
                    aria-describedby={error ? "access-error" : undefined}
                    className="min-w-0 flex-1 rounded-[var(--radius-tile)] bg-tile px-4 py-3 text-[16px] text-ink outline-none placeholder:text-faint focus:ring-2 focus:ring-accent/40"
                  />
                  <button
                    type="submit"
                    disabled={!code.trim() || busy}
                    className="shrink-0 rounded-[var(--radius-tile)] bg-ink px-5 text-[15px] font-semibold text-white transition hover:brightness-125 disabled:opacity-40"
                  >
                    {busy ? "…" : "Enter"}
                  </button>
                </div>
                {error && (
                  <p id="access-error" role="alert" className="mt-3 text-[14px] font-medium text-fail-ink">
                    {error}
                  </p>
                )}
              </form>
            )}
          </div>
        </div>
        <MechanicHand side="right" />
        <MechanicHand side="left" />
      </div>
    </div>
  );
}

/** His head behind the box: it rises into view once, then breathes. */
function MechanicHead() {
  const rise = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    rise.current?.animate([{ transform: "translateY(55%)" }, { transform: "none" }], {
      duration: 700,
      delay: 150,
      easing: "cubic-bezier(0.16, 1, 0.3, 1)",
      fill: "backwards",
    });
  }, []);

  return (
    <div
      ref={rise}
      aria-hidden
      className="absolute left-1/2 top-0 z-0"
      style={{ width: u(HEAD.width), height: u(HEAD.height), marginLeft: u(-HEAD.width / 2) }}
    >
      <img
        src={peekAsset("head.webp")}
        alt=""
        draggable={false}
        className="h-full w-full origin-[50%_100%] animate-mech-breathe select-none motion-reduce:animate-none"
      />
    </div>
  );
}

/** One hand over the top edge, fingers hanging down the front; the left one is the right one mirrored. */
function MechanicHand({ side }: { side: "left" | "right" }) {
  const offset = side === "right" ? -HAND_OFFSET : HAND_OFFSET;
  return (
    <img
      src={peekAsset("hand.webp")}
      alt=""
      aria-hidden
      draggable={false}
      className="pointer-events-none absolute left-1/2 z-20 max-w-none select-none drop-shadow-[0_2px_2px_rgb(26_26_24/0.16)]"
      style={{
        top: u(HEAD_ABOVE),
        width: u(HAND.width),
        height: u(HAND.height),
        marginLeft: u(offset - HAND.width / 2),
        transform: side === "left" ? "scaleX(-1)" : undefined,
      }}
    />
  );
}
