// The mascot's live drawings (`draw` events): halos, force arrows with their value,
// hand-drawn circles and notes. They sit on the same layer as the pointer and stay
// attached to their target, 3D part or UI element, every frame.
import { useEffect, useRef } from "react";
import { useSession, type Draw } from "../../events/store";
import { resolveTarget } from "../../lib/targets";

const INK = "#FF8A3D";
/** Drawings explain the moment; after this they fade so the canvas stays readable. */
export const DRAW_TTL_MS = 22_000;
const FADE_MS = 900;

/** A wobbly closed loop, drawn slightly past its start like a quick pen circle. Unit radius. */
function sketchCircle(seed: number): [number, number][] {
  const pts: [number, number][] = [];
  const n = 40;
  for (let i = 0; i <= n + 5; i++) {
    const a = (i / n) * Math.PI * 2 - 0.6;
    const wobble = 1 + 0.045 * Math.sin(a * 3 + seed) + 0.03 * Math.cos(a * 5 + seed * 2);
    const grow = 1 + (i / n) * 0.06;
    pts.push([Math.cos(a) * 1.3 * wobble * grow, Math.sin(a) * 0.95 * wobble * grow]);
  }
  return pts;
}

const scaledPath = (pts: [number, number][], r: number) =>
  `M${pts.map(([x, y]) => `${(x * r).toFixed(1)},${(y * r).toFixed(1)}`).join(" L")}`;

const noteWidth = (text: string) => Math.max(60, text.length * 11.5 + 28);

const isUpward = (text: string) => /schub|thrust|auftrieb|lift|hoch/i.test(text);

function DrawItem({ draw, register }: { draw: Draw; register: (id: string, fn: (now: number) => void) => () => void }) {
  const g = useRef<SVGGElement>(null);
  const clipRect = useRef<SVGRectElement>(null);
  const clipId = `clip-${draw.id}`;
  const shape = useRef<SVGPathElement>(null);
  const label = useRef<SVGGElement>(null);
  const seed = parseInt(draw.id.replace(/\D/g, ""), 10) || 1;
  const circle = useRef(sketchCircle(seed));

  useEffect(
    () =>
      register(draw.id, (now) => {
        const el = g.current;
        if (!el) return;
        const age = Date.now() - draw.at;
        const spot = age < DRAW_TTL_MS + FADE_MS ? resolveTarget(draw.target) : null;
        if (!spot) {
          el.style.opacity = "0";
          return;
        }
        el.style.opacity = String(Math.max(0, Math.min(1, (DRAW_TTL_MS + FADE_MS - age) / FADE_MS)));
        el.setAttribute("transform", `translate(${spot.x.toFixed(1)} ${spot.y.toFixed(1)})`);
        // Part drawings stay inside the 3D canvas they belong to.
        const c = clipRect.current;
        if (c) {
          const r = spot.clip ?? new DOMRect(-1e4, -1e4, 2e4, 2e4);
          c.setAttribute("x", String(r.left - spot.x));
          c.setAttribute("y", String(r.top - spot.y));
          c.setAttribute("width", String(r.width));
          c.setAttribute("height", String(r.height));
        }
        const r = Math.max(16, spot.r);
        const s = shape.current;
        const l = label.current;
        switch (draw.kind) {
          case "halo": {
            const pulse = 1 + 0.06 * Math.sin(now / 260);
            s?.setAttribute("d", circleD(r + 10));
            s?.setAttribute("transform", `scale(${pulse.toFixed(3)})`);
            l?.setAttribute("transform", `translate(0 ${(r + 34).toFixed(1)})`);
            break;
          }
          case "circle":
            s?.setAttribute("d", scaledPath(circle.current, r + 8));
            // Label sits top-left; arrows label to the right and notes go top-right, so they rarely collide.
            l?.setAttribute("transform", `translate(${(-r * 1.1).toFixed(1)} ${(-r - 14).toFixed(1)})`);
            break;
          case "arrow": {
            const dir = isUpward(draw.text) ? -1 : 1;
            const y0 = dir * (r + 6);
            const y1 = dir * (r + 92);
            s?.setAttribute(
              "d",
              `M0 ${y0} C 6 ${y0 + dir * 30}, -6 ${y1 - dir * 30}, 0 ${y1} M -11 ${y1 - dir * 14} L 0 ${y1} L 11 ${y1 - dir * 14}`,
            );
            // The value sits right of the arrow tip, or left of it near the canvas edge.
            const right = spot.clip ? spot.clip.right : window.innerWidth;
            const flip = spot.x + 14 + draw.text.length * 13 > right - 8;
            l?.setAttribute("transform", `translate(${flip ? -14 : 14} ${(y1 + (dir > 0 ? 6 : 2)).toFixed(1)})`);
            l?.firstElementChild?.setAttribute("text-anchor", flip ? "end" : "start");
            break;
          }
          case "note": {
            // Notes go up and to the right, unless that would leave the canvas.
            const width = noteWidth(draw.text);
            const right = spot.clip ? spot.clip.right : window.innerWidth;
            const flip = spot.x + r + 36 + width > right - 8;
            const sx = flip ? -1 : 1;
            s?.setAttribute("d", `M ${sx * r * 0.6} ${-r * 0.6} L ${sx * (r + 36)} ${-r - 40}`);
            l?.setAttribute("transform", `translate(${(flip ? -(r + 36) - width : r + 36).toFixed(1)} ${(-r - 40).toFixed(1)})`);
            break;
          }
        }
      }),
    [draw, register],
  );

  const textWidth = noteWidth(draw.text);
  return (
    <g ref={g} style={{ opacity: 0 }} clipPath={`url(#${clipId})`}>
      <clipPath id={clipId}>
        <rect ref={clipRect} />
      </clipPath>
      {draw.kind === "halo" && (
        <>
          <path ref={shape} fill="none" stroke={INK} strokeWidth={4} opacity={0.9} style={{ filter: "drop-shadow(0 0 10px rgb(255 138 61 / .8))" }} className="draw-in" />
          <g ref={label}>
            <rect x={-textWidth / 2} y={-17} width={textWidth} height={34} rx={17} fill="white" opacity={0.96} />
            <text textAnchor="middle" y={7} fontFamily="var(--font-hand)" fontSize={25} fontWeight={700} fill="#d9620f">
              {draw.text}
            </text>
          </g>
        </>
      )}
      {draw.kind === "circle" && (
        <>
          <path ref={shape} fill="none" stroke={INK} strokeWidth={3.5} strokeLinecap="round" strokeLinejoin="round" className="draw-in" pathLength={1} />
          <g ref={label}>
            <text textAnchor="end" fontFamily="var(--font-hand)" fontSize={28} fontWeight={700} fill="#d9620f" paintOrder="stroke" stroke="white" strokeWidth={6} strokeLinejoin="round">
              {draw.text}
            </text>
          </g>
        </>
      )}
      {draw.kind === "arrow" && (
        <>
          <path ref={shape} fill="none" stroke={INK} strokeWidth={3.5} strokeLinecap="round" strokeLinejoin="round" className="draw-in" pathLength={1} />
          <g ref={label}>
            <text fontFamily="var(--font-hand)" fontSize={28} fontWeight={700} fill="#d9620f" paintOrder="stroke" stroke="white" strokeWidth={6} strokeLinejoin="round">
              {draw.text}
            </text>
          </g>
        </>
      )}
      {draw.kind === "note" && (
        <>
          <path ref={shape} fill="none" stroke={INK} strokeWidth={2.5} strokeLinecap="round" strokeDasharray="1 7" />
          <g ref={label}>
            <g transform="rotate(-3)">
              <rect x={0} y={-24} width={textWidth} height={48} rx={14} fill="#FFF1E6" stroke={INK} strokeWidth={2} />
              <text x={14} y={8} fontFamily="var(--font-hand)" fontSize={26} fontWeight={700} fill="#b4500a">
                {draw.text}
              </text>
            </g>
          </g>
        </>
      )}
    </g>
  );
}

function circleD(r: number) {
  return `M ${-r} 0 a ${r} ${r} 0 1 0 ${2 * r} 0 a ${r} ${r} 0 1 0 ${-2 * r} 0`;
}

export function DrawLayer() {
  const draws = useSession((s) => s.draws);
  const painters = useRef(new Map<string, (now: number) => void>());
  const register = useRef((id: string, fn: (now: number) => void) => {
    painters.current.set(id, fn);
    return () => {
      painters.current.delete(id);
    };
  }).current;

  useEffect(() => {
    let raf = 0;
    const loop = (now: number) => {
      painters.current.forEach((fn) => fn(now));
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <svg className="pointer-events-none fixed inset-0 z-[55] h-full w-full overflow-visible" aria-hidden>
      <style>{`
        .draw-in { stroke-dasharray: 1; stroke-dashoffset: 1; animation: draw-in 700ms cubic-bezier(.3,.7,.3,1) forwards; }
        path.draw-in:not([pathLength]) { stroke-dasharray: none; stroke-dashoffset: 0; animation: halo-in 500ms ease-out both; }
        @keyframes draw-in { to { stroke-dashoffset: 0; } }
        @keyframes halo-in { from { opacity: 0; } to { opacity: .9; } }
      `}</style>
      {draws.map((d) => (
        <DrawItem key={d.id} draw={d} register={register} />
      ))}
    </svg>
  );
}
