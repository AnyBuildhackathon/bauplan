// A draggable divider between two columns. Dragging changes the width of the column
// on one side, the width is remembered per browser, double-click resets it, and the
// arrow keys move it in steps when the divider has focus.
import { useCallback, useEffect, useRef, useState } from "react";

function stored(key: string, initial: number): number {
  try {
    return Number(localStorage.getItem(key)) || initial;
  } catch {
    return initial;
  }
}

export function useWindowWidth(): number {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const update = () => setWidth(window.innerWidth);
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return width;
}

/** The width someone chose for a column, remembered under key. The caller fits it to the window. */
export function usePaneWidth(key: string, initial: number) {
  const [wanted, setWanted] = useState(() => stored(key, initial));
  const set = useCallback(
    (width: number) => {
      setWanted(width);
      try {
        localStorage.setItem(key, String(width));
      } catch {
        // Private windows may refuse storage; the width lasts for this page.
      }
    },
    [key],
  );
  return { wanted, set, reset: useCallback(() => set(initial), [set, initial]) };
}

/**
 * side tells which column the divider sizes: "before" grows when dragged right (the chat),
 * "after" grows when dragged left (the right panel).
 */
export function ResizeHandle({
  width,
  min,
  max,
  onChange,
  onReset,
  side,
  label,
}: {
  width: number;
  min: number;
  max: number;
  onChange: (width: number) => void;
  onReset: () => void;
  side: "before" | "after";
  label: string;
}) {
  const start = useRef<{ x: number; width: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const sign = side === "before" ? 1 : -1;
  const change = (next: number) => onChange(Math.round(Math.min(Math.max(min, max), Math.max(min, next))));
  const stop = () => {
    start.current = null;
    setDragging(false);
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      title="Drag to resize, double-click to reset"
      data-target={`resize:${side === "before" ? "chat" : "panel"}`}
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        start.current = { x: e.clientX, width };
        setDragging(true);
      }}
      onPointerMove={(e) => {
        if (start.current) change(start.current.width + sign * (e.clientX - start.current.x));
      }}
      onPointerUp={stop}
      onPointerCancel={stop}
      onDoubleClick={onReset}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 64 : 16;
        if (e.key === "ArrowLeft") change(width - sign * step);
        else if (e.key === "ArrowRight") change(width + sign * step);
        else return;
        e.preventDefault();
      }}
      className="group relative z-10 -mx-1.5 w-3 shrink-0 cursor-col-resize touch-none outline-none select-none"
    >
      {/* The grip is wider than the line, which shows on hover, focus and drag. */}
      <span
        className={`pointer-events-none absolute inset-y-0 left-1/2 w-[2px] -translate-x-1/2 transition-colors ${
          dragging ? "bg-accent" : "bg-transparent group-hover:bg-faint/60 group-focus-visible:bg-accent"
        }`}
      />
      {dragging && <style>{"body { cursor: col-resize; user-select: none; }"}</style>}
    </div>
  );
}
