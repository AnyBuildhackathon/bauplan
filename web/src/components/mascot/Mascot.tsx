// Mechanic, the porcelain inventor in the pinstripe suit. Each state is a still made
// with Nano Banana (web/public/mascot/<clip>.webp), plus an eyes-only overlay for the
// blink (<clip>-blink.webp) and a mouth-only closed overlay for talking
// (talking-closed.webp). MascotLive brings the stills to life: it breathes, sways in a
// way that fits the state, blinks now and then, moves its mouth and bobs with the
// loudness of Mechanic's voice while he speaks, and cross-fades when the state changes.
// MascotFull is the whole figure (full-<clip>.webp, cut out, same scale and head position
// in every state) with the same breathing, sway, cross-fade and voice bob, without blink
// or mouth overlays. MascotHead and MascotBust are the plain stills for small and static places.
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { MascotState } from "../../events/types";
import { useSpeech } from "../../lib/speech";

export const MASCOT_LABEL: Record<MascotState, string> = {
  ruhig: "calm",
  denkt: "thinking",
  erklaert: "explaining",
  freut_sich: "pleased",
  besorgt: "worried",
};

const CLIPS = ["calm", "thinking", "talking", "pleased", "worried"] as const;
type Clip = (typeof CLIPS)[number];

/** The picture for each state; explaining without sound stays calm so the mouth is never open in silence. */
const LIVE_FOR: Record<MascotState, Clip> = {
  ruhig: "calm",
  denkt: "thinking",
  erklaert: "calm",
  freut_sich: "pleased",
  besorgt: "worried",
};

/** Static pictures show the expression itself, so explaining gets the talking face. */
const STILL_FOR: Record<MascotState, Clip> = { ...LIVE_FOR, erklaert: "talking" };

/** The slow motion layered over breathing; thinking ponders, pleased bounces, worried holds still. */
const SWAY: Record<Clip, string> = {
  calm: "animate-mech-sway",
  thinking: "animate-mech-ponder",
  talking: "",
  pleased: "animate-mech-bounce",
  worried: "",
};

const asset = (name: string) => `${import.meta.env.BASE_URL}mascot/${name}`;

/** Which picture shows: the talking one whenever Mechanic's voice is audible, otherwise the state's own. */
export function mascotClip(state: MascotState, speaking: boolean): Clip {
  return speaking ? "talking" : LIVE_FOR[state];
}

const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";

function subscribeReduced(onChange: () => void) {
  const query = window.matchMedia(REDUCED_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReduced,
    () => window.matchMedia(REDUCED_QUERY).matches,
    () => false,
  );
}

/** True for about 150 ms every few seconds, at a slightly random rhythm. */
function useBlink(enabled: boolean): boolean {
  const [closed, setClosed] = useState(false);
  useEffect(() => {
    if (!enabled) return;
    let timer = 0;
    const next = () => {
      timer = window.setTimeout(
        () => {
          setClosed(true);
          timer = window.setTimeout(() => {
            setClosed(false);
            next();
          }, 150);
        },
        2600 + Math.random() * 3400,
      );
    };
    next();
    return () => window.clearTimeout(timer);
  }, [enabled]);
  return enabled && closed;
}

/** Voice loudness above which the talking mouth shows open. */
const MOUTH_OPEN_LEVEL = 0.3;

// The head crop of the square bust: a 66% square starting 17% from the left and 7% from the top.
const HEAD_CROP = { scale: 1 / 0.664, left: -0.168, top: -0.073 };

/**
 * Mechanic, alive. `crop="head"` zooms into the face for round avatars. With reduced
 * motion the picture still follows the state but nothing moves.
 */
export function MascotLive({
  state,
  size,
  crop = "bust",
  className = "",
}: {
  state: MascotState;
  size: number;
  crop?: "bust" | "head";
  className?: string;
}) {
  const speaking = useSpeech((s) => s.speaking);
  const reduced = usePrefersReducedMotion();
  const active = mascotClip(state, speaking);
  const blink = useBlink(!reduced);
  const bob = useRef<HTMLDivElement>(null);
  const closedMouth = useRef<HTMLImageElement>(null);

  // Follow the voice loudness without re-rendering every frame: quiet moments close the
  // mouth, louder ones open it and lift and tilt him a little.
  useEffect(() => {
    if (reduced) return;
    const apply = (level: number) => {
      if (bob.current) bob.current.style.transform = `translateY(${-level * 2.2}%) rotate(${level * 1.4}deg)`;
      if (closedMouth.current) closedMouth.current.style.opacity = level < MOUTH_OPEN_LEVEL ? "1" : "0";
    };
    apply(useSpeech.getState().level);
    return useSpeech.subscribe((s) => apply(s.level));
  }, [reduced]);

  const layer =
    crop === "head"
      ? {
          width: `${HEAD_CROP.scale * 100}%`,
          height: `${HEAD_CROP.scale * 100}%`,
          left: `${HEAD_CROP.left * HEAD_CROP.scale * 100}%`,
          top: `${HEAD_CROP.top * HEAD_CROP.scale * 100}%`,
        }
      : { width: "100%", height: "100%", left: 0, top: 0 };

  return (
    <div
      role="img"
      aria-label={`Mechanic ${speaking ? "talking" : MASCOT_LABEL[state]}`}
      className={`relative shrink-0 overflow-hidden bg-[#f8f6f4] select-none ${className}`}
      style={{ width: size, height: size }}
    >
      <div className="absolute inset-0 origin-[50%_95%] animate-mech-breathe motion-reduce:animate-none">
        <div ref={bob} className="absolute inset-0 origin-[50%_85%] transition-transform duration-100 ease-out">
          <div className={`absolute inset-0 origin-[50%_90%] motion-reduce:animate-none ${SWAY[active]}`}>
            {CLIPS.map((clip) => {
              const shown = clip === active;
              return (
                <div
                  key={clip}
                  className={`absolute inset-0 transition-opacity duration-[350ms] ease-out motion-reduce:transition-none ${
                    shown ? "opacity-100" : "opacity-0"
                  }`}
                >
                  <img src={asset(`${clip}.webp`)} alt="" draggable={false} className="absolute max-w-none" style={layer} />
                  {clip === "talking" && !reduced && (
                    <img
                      ref={closedMouth}
                      src={asset("talking-closed.webp")}
                      alt=""
                      draggable={false}
                      className="absolute max-w-none"
                      style={layer}
                    />
                  )}
                  {shown && blink && (
                    <img
                      src={asset(`${clip}-blink.webp`)}
                      alt=""
                      draggable={false}
                      className="absolute max-w-none"
                      style={layer}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

/** The full figures are 640 × 820. */
const FULL_ASPECT = 640 / 820;

/** Mechanic head to toe, alive: the talking pose while his voice is audible, otherwise the state's own. */
export function MascotFull({ state, height, className = "" }: { state: MascotState; height: number; className?: string }) {
  const speaking = useSpeech((s) => s.speaking);
  const reduced = usePrefersReducedMotion();
  const active = mascotClip(state, speaking);
  const bob = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (reduced) return;
    const apply = (level: number) => {
      if (bob.current) bob.current.style.transform = `translateY(${-level * 1.6}%) rotate(${level * 1.2}deg)`;
    };
    apply(useSpeech.getState().level);
    return useSpeech.subscribe((s) => apply(s.level));
  }, [reduced]);

  return (
    <div
      role="img"
      aria-label={`Mechanic ${speaking ? "talking" : MASCOT_LABEL[state]}`}
      className={`relative shrink-0 select-none ${className}`}
      style={{ width: Math.round(height * FULL_ASPECT), height }}
    >
      <div className="absolute inset-0 origin-[50%_98%] animate-mech-breathe motion-reduce:animate-none">
        <div ref={bob} className="absolute inset-0 origin-[50%_95%] transition-transform duration-100 ease-out">
          <div className={`absolute inset-0 origin-[50%_98%] motion-reduce:animate-none ${SWAY[active]}`}>
            {CLIPS.map((clip) => (
              <img
                key={clip}
                src={asset(`full-${clip}.webp`)}
                alt=""
                draggable={false}
                className={`absolute inset-0 h-full w-full transition-opacity duration-[350ms] ease-out motion-reduce:transition-none ${
                  clip === active ? "opacity-100" : "opacity-0"
                }`}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function MascotHead({
  state = "ruhig",
  size = 44,
  className = "",
}: {
  state?: MascotState;
  size?: 96 | 44 | 24;
  className?: string;
}) {
  return (
    <img
      src={asset(`head-${STILL_FOR[state]}.webp`)}
      width={size}
      height={size}
      alt={`Mechanic ${MASCOT_LABEL[state]}`}
      className={`shrink-0 rounded-full bg-[#f8f6f4] select-none ${className}`}
      draggable={false}
    />
  );
}

export function MascotBust({ state, size, className = "" }: { state: MascotState; size: number; className?: string }) {
  return (
    <img
      src={asset(`${STILL_FOR[state]}.webp`)}
      width={size}
      height={size}
      alt={`Mechanic ${MASCOT_LABEL[state]}`}
      className={`shrink-0 select-none ${className}`}
      draggable={false}
    />
  );
}
