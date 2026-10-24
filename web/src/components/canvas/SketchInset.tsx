// The hand sketch a build started from, pinned in the top-left corner of the Model tab so the
// drawing and what FreeCAD built from it sit side by side. A click opens it large inside the
// canvas, with what Claude read off it.
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { useSession } from "../../events/store";
import { assetUrl } from "../../lib/api";

const STATUS = {
  reading: "Reading the sketch …",
  read: "Your sketch",
  failed: "Could not read the sketch",
} as const;

export function SketchInset() {
  const sketch = useSession((s) => s.sketch);
  const [open, setOpen] = useState(false);
  const url = assetUrl(sketch?.url ?? null);
  useEffect(() => {
    if (!open) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [open]);
  if (!sketch || !url) return null;
  const tone = sketch.status === "failed" ? "text-fail-ink" : sketch.status === "reading" ? "text-agent-ink" : "text-muted";
  const label = (
    <span className={`min-w-0 flex-1 truncate text-[13px] font-semibold ${tone}`}>
      {STATUS[sketch.status] ?? "Your sketch"}
      {sketch.status === "read" && sketch.source === "recorded" && <span className="font-medium text-faint"> · recorded reading</span>}
    </span>
  );
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-target="sketch"
        title="Enlarge the sketch"
        className="absolute top-3 left-3 z-10 w-[min(200px,40%)] overflow-hidden rounded-[16px] bg-white/95 p-1.5 text-left shadow-[var(--shadow-float)] backdrop-blur"
      >
        <img src={url} alt="Hand sketch this build started from" className={`block w-full rounded-[11px] ring-1 ring-line ${sketch.status === "reading" ? "animate-pulse-soft" : ""}`} />
        <div className="flex items-center px-1.5 pt-1.5 pb-0.5">{label}</div>
      </button>
      {open && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/40 p-6 backdrop-blur-sm" onClick={() => setOpen(false)}>
          <div
            className="flex max-h-full w-full max-w-[880px] min-w-0 flex-col overflow-hidden rounded-[20px] bg-card shadow-[var(--shadow-float)]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
              {label}
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-full p-1.5 text-faint transition hover:bg-tile hover:text-ink-2"
                aria-label="Close the sketch"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 overflow-y-auto p-4">
              <img src={url} alt="Hand sketch this build started from" className="mx-auto block max-h-[60vh] w-auto max-w-full rounded-[12px] ring-1 ring-line" />
              {(sketch.summary || sketch.error) && (
                <p className={`mt-3 text-[15px] ${sketch.error ? "text-fail-ink" : "text-ink-2"}`}>{sketch.error ?? sketch.summary}</p>
              )}
              {sketch.read && sketch.read.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {sketch.read.map((r) => (
                    <span
                      key={r.label}
                      title={r.confidence ? `${r.confidence} confidence` : undefined}
                      className={`rounded-full px-2.5 py-1 text-[13px] tabular-nums ${r.confidence === "low" ? "bg-agent-soft text-agent-ink" : "bg-tile text-ink-2"}`}
                    >
                      {r.label}: <span className="font-semibold">{r.value}{r.unit ? ` ${r.unit}` : ""}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
