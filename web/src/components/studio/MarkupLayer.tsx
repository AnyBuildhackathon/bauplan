// The Mark tool: the person draws on the studio view (strokes over the 3D canvas) and attaches it to
// their next message for Mechanic as a marking note: the view as it shows now with the strokes on it,
// stored in the session (POST /api/notes/markup), and how the view stood (side, cut, explode, colours),
// so Mechanic looks at the very picture and knows what made it. Leaving the tool drops the strokes.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { MessageSquarePlus, PenLine, Undo2, X } from "lucide-react";
import { attach, shownBuild } from "../../events/notes";
import { useSource } from "../../events/source";
import { useSession } from "../../events/store";
import { useUi } from "../../lib/ui";
import { useStudio } from "./studio";

type Stroke = [number, number][];

/** The picture's longest side; enough for Mechanic to read a stroke, small enough to send every round. */
const MAX_SIDE = 1280;
const INK = "#6b4fd8";

function paint(ctx: CanvasRenderingContext2D, strokes: Stroke[], scale: number) {
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  // A white halo under the ink keeps a stroke readable on a dark part and on the light grid alike.
  for (const [color, width] of [["rgba(255,255,255,0.92)", 9], [INK, 4]] as const) {
    ctx.strokeStyle = color;
    ctx.lineWidth = width * scale;
    for (const stroke of strokes) {
      ctx.beginPath();
      stroke.forEach(([x, y], i) => (i ? ctx.lineTo(x * scale, y * scale) : ctx.moveTo(x * scale, y * scale)));
      if (stroke.length === 1) ctx.lineTo(stroke[0][0] * scale + 0.01, stroke[0][1] * scale);
      ctx.stroke();
    }
  }
}

/** The first colour behind the transparent 3D canvas, which the picture needs as its background. */
function backdrop(el: HTMLElement | null): string {
  for (let e = el; e; e = e.parentElement) {
    const colour = getComputedStyle(e).backgroundColor;
    if (colour && colour !== "transparent" && !/rgba\(.*,\s*0\)$/.test(colour)) return colour;
  }
  return "#fafaf8";
}

export function MarkupLayer() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const drawing = useRef<Stroke | null>(null);
  const [busy, setBusy] = useState(false);
  const leave = () => useUi.getState().setTool("select");

  // The drawing canvas matches its box at the screen's pixel density.
  const [size, setSize] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const fit = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    el.width = Math.round(size.w * dpr);
    el.height = Math.round(size.h * dpr);
    ctx.clearRect(0, 0, el.width, el.height);
    paint(ctx, drawing.current ? [...strokes, drawing.current] : strokes, dpr);
  }, [strokes, size]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") leave();
      else if ((e.metaKey || e.ctrlKey) && e.key === "z") {
        e.preventDefault();
        setStrokes((s) => s.slice(0, -1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const at = (e: React.PointerEvent): [number, number] => {
    const r = canvas.current!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  const redraw = () => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx || !drawing.current) return;
    const dpr = window.devicePixelRatio || 1;
    ctx.clearRect(0, 0, el.width, el.height);
    paint(ctx, [...strokes, drawing.current], dpr);
  };

  const send = async () => {
    const el = canvas.current;
    const source = el?.parentElement?.querySelector<HTMLCanvasElement>("canvas:not([data-markup])");
    if (!el || !source || strokes.length === 0 || busy) return;
    setBusy(true);
    try {
      // Sharp on a dense screen, but never past MAX_SIDE on the longest side.
      const scale = Math.min(Math.min(window.devicePixelRatio || 1, 2), MAX_SIDE / Math.max(el.clientWidth, el.clientHeight));
      const out = document.createElement("canvas");
      out.width = Math.round(el.clientWidth * scale);
      out.height = Math.round(el.clientHeight * scale);
      const ctx = out.getContext("2d")!;
      ctx.fillStyle = backdrop(source);
      ctx.fillRect(0, 0, out.width, out.height);
      ctx.drawImage(source, 0, 0, out.width, out.height);
      paint(ctx, strokes, scale);
      const png = await new Promise<Blob | null>((resolve) => out.toBlob(resolve, "image/png"));
      if (!png) throw new Error("no picture");
      const stored = await useSource.getState().uploadMarkup(png);
      if (!stored) return;
      const { selectedVersion } = useUi.getState();
      const latest = useSession.getState().versions.at(-1)?.n ?? null;
      const view = useStudio.getState().view?.() ?? {};
      attach({ kind: "markup", image: stored.name, view, build: shownBuild(), version: selectedVersion !== null && selectedVersion !== latest ? selectedVersion : null }, stored.url);
      leave();
    } catch {
      useSource.setState({ notice: "The marking could not be made from this view." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <canvas
        ref={canvas}
        data-markup
        data-target="markup:canvas"
        className="absolute inset-0 z-[15] h-full w-full cursor-crosshair touch-none"
        onPointerDown={(e) => {
          if (e.button !== 0) return;
          try {
            // The stroke goes on when the pointer leaves the canvas while drawing.
            e.currentTarget.setPointerCapture(e.pointerId);
          } catch {
            // A pointer the browser no longer tracks; the stroke still draws.
          }
          drawing.current = [at(e)];
          redraw();
        }}
        onPointerMove={(e) => {
          if (!drawing.current) return;
          const events = e.nativeEvent.getCoalescedEvents?.() ?? [e.nativeEvent];
          const r = canvas.current!.getBoundingClientRect();
          for (const ev of events.length ? events : [e.nativeEvent]) drawing.current.push([ev.clientX - r.left, ev.clientY - r.top]);
          redraw();
        }}
        onPointerUp={() => {
          const done = drawing.current;
          drawing.current = null;
          if (done) setStrokes((s) => [...s, done]);
        }}
        onPointerCancel={() => {
          drawing.current = null;
          redraw();
        }}
      />
      <div
        role="toolbar"
        aria-label="Marking"
        className="absolute top-3 left-1/2 z-30 flex max-w-[calc(100%-24px)] -translate-x-1/2 animate-rise items-center gap-1 rounded-full bg-ink py-1 pr-1 pl-3 text-white shadow-[var(--shadow-float)]"
      >
        <PenLine className="h-4 w-4 shrink-0" />
        <span className="mr-1 truncate text-[13px] font-semibold">{strokes.length ? "Mark what you mean" : "Draw on the model to show Mechanic"}</span>
        <button
          type="button"
          onClick={() => setStrokes((s) => s.slice(0, -1))}
          disabled={!strokes.length}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white/80 transition enabled:hover:bg-white/15 enabled:hover:text-white disabled:opacity-35"
          aria-label="Undo the last stroke"
          title="Undo (⌘Z)"
        >
          <Undo2 className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => void send()}
          disabled={!strokes.length || busy}
          data-target="markup:attach"
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-white px-3 text-[13px] font-bold text-ink transition enabled:hover:bg-white/90 disabled:opacity-40"
        >
          <MessageSquarePlus className="h-3.5 w-3.5" />
          {busy ? "Adding …" : "Add to message"}
        </button>
        <button
          type="button"
          onClick={leave}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white/80 transition hover:bg-white/15 hover:text-white"
          aria-label="Stop marking"
          title="Stop marking (Esc)"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </>
  );
}
