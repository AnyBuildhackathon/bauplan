// Mechanic standing behind the start screen's box: his head rises over the top edge near
// its right end and his fingers curl over the edge on either side of it. The pieces are cut
// from the full figures by web/scripts/mascot_peek.py; every size below is in those pixels
// and drawn at --u per pixel, which the box sets, so head and fingers keep one scale.
import { useEffect, useRef } from "react";

const peekAsset = (name: string) => `${import.meta.env.BASE_URL}mascot-peek/${name}`;
const u = (px: number) => `calc(var(--u) * ${px})`;

const HEAD = { width: 248, height: 244 };
/** How much of the head shows above the edge: hair top to the shirt collar. */
export const HEAD_ABOVE = 234;
/** From the box's right edge to the middle of his face. */
const FROM_RIGHT = 176;

// The hands, kept apart so their look can change in one place: the finger row of one hand
// (back of the fingers towards us, tips pointing down), how far each hand sits from the
// middle of his face. The row starts exactly on the edge, so its cut top reads as the edge.
// The row is drawn half again as large as the figure's own hand so it reads at a glance.
const FINGERS = { width: 47 * 1.6, height: 25 * 1.6 };
const HAND_SPREAD = 124;

export function MechanicPeek() {
  return (
    <>
      <Head />
      <Fingers side="left" />
      <Fingers side="right" />
    </>
  );
}

/** Behind the box: it rises into view once, then breathes. */
function Head() {
  const rise = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    rise.current?.animate([{ transform: "translateY(60%)" }, { transform: "none" }], {
      duration: 800,
      delay: 200,
      easing: "cubic-bezier(0.16, 1, 0.3, 1)",
      fill: "backwards",
    });
  }, []);
  return (
    <div
      ref={rise}
      aria-hidden
      className="absolute top-0 z-0"
      style={{ width: u(HEAD.width), height: u(HEAD.height), right: u(FROM_RIGHT - HEAD.width / 2) }}
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

/** In front of the box: one hand's fingers over the top edge. The left hand is the right one mirrored. */
function Fingers({ side }: { side: "left" | "right" }) {
  const centre = FROM_RIGHT + (side === "right" ? -HAND_SPREAD : HAND_SPREAD);
  return (
    <img
      src={peekAsset("fingers.webp")}
      alt=""
      aria-hidden
      draggable={false}
      className="pointer-events-none absolute z-20 max-w-none select-none drop-shadow-[0_1.5px_1.5px_rgb(26_26_24/0.18)]"
      style={{
        top: u(HEAD_ABOVE),
        width: u(FINGERS.width),
        height: u(FINGERS.height),
        right: u(centre - FINGERS.width / 2),
        transform: side === "left" ? "scaleX(-1)" : undefined,
      }}
    />
  );
}
