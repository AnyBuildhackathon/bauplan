// Bolzen's pointer, in the style of Clicky (github.com/farzaa/clicky, MIT, see
// THIRD_PARTY_NOTICES). Ported mechanism: the pointer flies along a quadratic
// bezier arc (duration distance/800 px/s clamped to 0.6-1.4 s, arc height
// min(distance*0.2, 80 px), smoothstep easing, scale swell at mid-flight, nose
// following the tangent), lands at a cursor-like angle, pops a speech bubble that
// streams its text with a waveform, and fades out shortly after the answer.
// Unlike Clicky it aims at exact projected 3D part positions and keeps following
// the target while the drone rotates.
import { useEffect, useRef } from "react";
import { INSTANT_AGE_MS, useSession } from "../../events/store";
import { resolveTarget } from "../../lib/targets";
import { MascotHead } from "../mascot/Mascot";

type Phase = "idle" | "waiting" | "flying" | "pointing" | "fading";

interface Flight {
  id: string;
  target: string;
  label: string;
  phase: Phase;
  from: { x: number; y: number };
  startedAt: number;
  duration: number;
  arrivedAt: number;
  fadeAt: number;
  fallback: boolean;
}

const CHAR_MS = 28;
const WAIT_FOR_TARGET_MS = 1500;
const FADE_MS = 450;
/** Rough speaking time of a short German sentence. */
const speakMs = (label: string) => Math.max(1600, label.split(/\s+/).length * 330);

function smoothstep(t: number) {
  return t * t * (3 - 2 * t);
}
function easeOutBack(t: number) {
  const c1 = 1.70158;
  return 1 + (c1 + 1) * (t - 1) ** 3 + c1 * (t - 1) ** 2;
}

function mascotOrigin(): { x: number; y: number } {
  const el = document.querySelector<HTMLElement>('[data-target~="mascot"]');
  if (el) {
    const r = el.getBoundingClientRect();
    if (r.width > 0) return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  }
  return { x: window.innerWidth / 2, y: window.innerHeight - 80 };
}

export function PointerLayer() {
  const point = useSession((s) => s.point);
  const flight = useRef<Flight | null>(null);
  const pos = useRef({ x: -100, y: -100, angle: -35, scale: 1, opacity: 0 });
  const cursorRef = useRef<HTMLDivElement>(null);
  const bubbleRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const waveRef = useRef<HTMLDivElement>(null);

  // A new `point` event starts a new flight from wherever the pointer is now.
  useEffect(() => {
    if (!point || Date.now() - point.at > INSTANT_AGE_MS / 2) return;
    const visible = pos.current.opacity > 0.05;
    flight.current = {
      id: point.id,
      target: point.target,
      label: point.label,
      phase: "waiting",
      from: visible ? { x: pos.current.x, y: pos.current.y } : mascotOrigin(),
      startedAt: performance.now(),
      duration: 0,
      arrivedAt: 0,
      fadeAt: 0,
      fallback: false,
    };
    if (textRef.current) textRef.current.textContent = "";
  }, [point]);

  useEffect(() => {
    let raf = 0;
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const f = flight.current;
      const p = pos.current;
      if (!f || f.phase === "idle") {
        p.opacity = 0;
        paint(now);
        return;
      }

      const spot = resolveTarget(f.target);
      if (f.phase === "waiting") {
        if (spot) {
          const dist = Math.hypot(spot.x - f.from.x, spot.y - f.from.y);
          f.duration = Math.min(Math.max(dist / 800, 0.6), 1.4) * 1000;
          f.startedAt = now;
          f.phase = "flying";
          p.opacity = 1;
        } else if (now - f.startedAt > WAIT_FOR_TARGET_MS) {
          // Target is not on screen (other view): Bolzen says it from where he stands.
          f.fallback = true;
          f.phase = "pointing";
          f.arrivedAt = now;
          f.fadeAt = now + f.label.length * CHAR_MS + speakMs(f.label) + 1000;
          const o = mascotOrigin();
          p.x = o.x + 18;
          p.y = o.y - 6;
          p.opacity = 1;
        }
      }

      if (f.phase === "flying" && spot) {
        const t = Math.min(1, (now - f.startedAt) / f.duration);
        const e = smoothstep(t);
        const end = { x: spot.x, y: spot.y };
        const dist = Math.hypot(end.x - f.from.x, end.y - f.from.y);
        const ctrl = { x: (f.from.x + end.x) / 2, y: (f.from.y + end.y) / 2 - Math.min(dist * 0.2, 80) };
        const u = 1 - e;
        p.x = u * u * f.from.x + 2 * u * e * ctrl.x + e * e * end.x;
        p.y = u * u * f.from.y + 2 * u * e * ctrl.y + e * e * end.y;
        const tx = 2 * u * (ctrl.x - f.from.x) + 2 * e * (end.x - ctrl.x);
        const ty = 2 * u * (ctrl.y - f.from.y) + 2 * e * (end.y - ctrl.y);
        // The arrow tip rests pointing up-left (-35° here); +100° turns it along the flight path.
        p.angle = (Math.atan2(ty, tx) * 180) / Math.PI + 100;
        p.scale = 1 + Math.sin(Math.PI * t) * 0.3;
        if (t >= 1) {
          f.phase = "pointing";
          f.arrivedAt = now;
          f.fadeAt = now + f.label.length * CHAR_MS + speakMs(f.label) + 1000;
          p.scale = 1;
        }
      } else if (f.phase === "pointing" || f.phase === "fading") {
        // Keep glued to the target while the scene moves.
        if (spot && !f.fallback) {
          p.x += (spot.x - p.x) * 0.35;
          p.y += (spot.y - p.y) * 0.35;
        }
        const turn = ((((-35 - p.angle) % 360) + 540) % 360) - 180;
        p.angle += turn * 0.2;
        if (f.phase === "pointing" && now >= f.fadeAt) f.phase = "fading";
        if (f.phase === "fading") {
          p.opacity = Math.max(0, 1 - (now - f.fadeAt) / FADE_MS);
          if (p.opacity === 0) f.phase = "idle";
        }
      }

      // Stream the bubble text, Clicky-style, once the pointer has landed.
      if (textRef.current && (f.phase === "pointing" || f.phase === "fading")) {
        const chars = Math.min(f.label.length, Math.floor((now - f.arrivedAt) / CHAR_MS));
        const shown = f.label.slice(0, chars);
        if (textRef.current.textContent !== shown) textRef.current.textContent = shown;
      }
      paint(now);
    };

    const paint = (now: number) => {
      const p = pos.current;
      const f = flight.current;
      const cursor = cursorRef.current;
      const bubble = bubbleRef.current;
      if (cursor) {
        cursor.style.opacity = String(p.opacity);
        cursor.style.transform = `translate(${p.x}px, ${p.y}px)`;
        const arrow = cursor.firstElementChild as HTMLElement | null;
        if (arrow) arrow.style.transform = `rotate(${p.angle + 35}deg) scale(${p.scale})`;
      }
      if (bubble) {
        const landed = f && (f.phase === "pointing" || f.phase === "fading");
        const since = landed ? now - f!.arrivedAt : 0;
        // Pop in from 0.5x with a little overshoot.
        const k = Math.min(1, since / 380);
        const scale = landed ? 0.5 + 0.5 * easeOutBack(k) : 0.5;
        const flipLeft = p.x > window.innerWidth - 360;
        bubble.style.opacity = landed ? String(p.opacity) : "0";
        bubble.style.transform = `translate(${flipLeft ? p.x - 22 : p.x + 22}px, ${p.y + 20}px) translateX(${flipLeft ? "-100%" : "0"}) scale(${scale})`;
        bubble.style.transformOrigin = flipLeft ? "top right" : "top left";
        const speaking = landed && f && now < f.arrivedAt + f.label.length * CHAR_MS + speakMs(f.label);
        if (waveRef.current) {
          const bars = waveRef.current.children;
          for (let i = 0; i < bars.length; i++) {
            const h = speaking ? 5 + Math.abs(Math.sin(now / 110 + i * 1.3)) * 11 * (0.6 + 0.4 * Math.sin(now / 370 + i)) : 4;
            (bars[i] as HTMLElement).style.height = `${h}px`;
          }
        }
      }
    };

    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div className="pointer-events-none fixed inset-0 z-[60]" aria-hidden>
      <div ref={cursorRef} className="absolute top-0 left-0 opacity-0 will-change-transform">
        <div className="origin-top-left">
          <svg width="30" height="34" viewBox="0 0 30 34" className="-translate-x-[3px] -translate-y-[2px] drop-shadow-[0_0_10px_rgb(255_138_61/0.75)]">
            <path d="M3 2 L26 19 L15.5 20.5 L9.5 31 Z" fill="#FF8A3D" stroke="white" strokeWidth="2.5" strokeLinejoin="round" />
          </svg>
        </div>
      </div>
      <div
        ref={bubbleRef}
        className="absolute top-0 left-0 flex max-w-[340px] items-center gap-2.5 rounded-[18px] bg-white py-2.5 pr-4 pl-2.5 opacity-0 shadow-[var(--shadow-float)] will-change-transform"
      >
        <MascotHead size={24} state="erklaert" />
        <span ref={textRef} className="text-[15px] leading-snug font-semibold text-ink" />
        <div ref={waveRef} className="flex h-5 shrink-0 items-center gap-[3px]">
          {Array.from({ length: 5 }, (_, i) => (
            <span key={i} className="w-[3px] rounded-full bg-agent" style={{ height: 4 }} />
          ))}
        </div>
      </div>
    </div>
  );
}
