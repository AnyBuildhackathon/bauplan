// Shared motion rules for the canvas: with reduced motion every animation is an instant cut.
export { usePrefersReducedMotion as useReducedMotion } from "../components/canvas/GridStage";

export const MOTION = {
  /** Assembly fly-in: delay between parts and the flight of one part, in seconds. */
  flyStagger: 0.06,
  flyPart: 0.55,
  /** A cad event older than this is a backlog replay or a seek: it never animates. */
  liveMs: 5000,
} as const;

/** True for an event the store received live, not in a bulk replay (store.ts INSTANT_AGE_MS). */
export const isLive = (at: number) => Date.now() - at < MOTION.liveMs;
