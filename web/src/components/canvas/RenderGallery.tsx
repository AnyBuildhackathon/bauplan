// Render tab: Blender images from `render` events as a gallery. Until the first
// render arrives, a studio-lit 3D preview stands in.
import { useEffect, useState } from "react";
import { useSession } from "../../events/store";
import { assetUrl } from "../../lib/api";
import { fmtClock } from "../../lib/format";
import { ModelScene } from "./Scenes";

export function RenderGallery() {
  const renders = useSession((s) => s.renders);
  const product = useSession((s) => s.product);
  const [picked, setPicked] = useState<string | null>(null);
  const latest = renders.at(-1);

  // A new render takes the stage.
  useEffect(() => setPicked(null), [latest?.id]);

  if (!renders.length && product !== "drone") {
    return (
      <div className="flex h-full items-center justify-center px-8 text-center text-[16px] font-semibold text-muted">No Blender render yet</div>
    );
  }
  if (!renders.length) {
    return (
      <div className="relative h-full">
        <ModelScene look="render" />
        <span className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-white/90 px-3.5 py-1.5 text-[13px] font-semibold text-muted shadow-[var(--shadow-pill)]">
          No Blender render yet · 3D preview
        </span>
      </div>
    );
  }

  const current = renders.find((r) => r.id === picked) ?? latest!;
  const index = renders.indexOf(current) + 1;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative min-h-0 flex-1 p-3 pb-2">
        <img
          key={current.id}
          src={assetUrl(current.png_url) ?? undefined}
          alt={current.label}
          className="h-full w-full animate-rise rounded-[18px] bg-[#e9e8ef] object-contain shadow-[var(--shadow-card)]"
        />
        <div className="pointer-events-none absolute top-6 left-6 flex items-center gap-2">
          <span className="inline-flex h-8 items-center gap-2 rounded-full bg-white/92 px-3.5 text-[13px] font-bold text-ink-2 shadow-[var(--shadow-pill)]">
            <span className="h-2 w-2 rounded-full bg-[#ea7600]" /> Blender
          </span>
          <span className="inline-flex h-8 items-center rounded-full bg-white/92 px-3.5 text-[13px] font-semibold text-ink shadow-[var(--shadow-pill)]">
            {current.label}
          </span>
        </div>
        <span className="num pointer-events-none absolute top-6 right-6 inline-flex h-8 items-center rounded-full bg-white/92 px-3 text-[13px] font-semibold text-muted shadow-[var(--shadow-pill)]">
          {index} / {renders.length} · {fmtClock(current.at)}
        </span>
      </div>
      {renders.length > 1 && (
        <div className="flex shrink-0 gap-2 overflow-x-auto px-3 pb-3">
          {renders.map((r) => {
            const active = r.id === current.id;
            return (
              <button
                key={r.id}
                type="button"
                onClick={() => setPicked(r.id)}
                title={r.label}
                className={`h-16 w-24 shrink-0 overflow-hidden rounded-xl transition ${active ? "ring-[3px] ring-ink" : "opacity-75 ring-1 ring-line hover:opacity-100"}`}
              >
                <img src={assetUrl(r.png_url) ?? undefined} alt={r.label} className="h-full w-full object-cover" />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
