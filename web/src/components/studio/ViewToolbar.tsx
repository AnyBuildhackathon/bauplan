// The view bar between the canvas tabs and the canvas: perspective or orthographic, the camera
// views (keys 1 to 4), the explode amount in a popover, the surface check colour layer (overhang,
// wall thickness or clearance, once Mechanic has checked this build), and the grid and label
// switches. The grid switch also hides the lines of the test stage in the simulation replays; the
// rest needs the live model, so it rests while the Model tab shows the render or two versions
// side by side.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, Expand, Grid3x3, Layers, Tag, Video } from "lucide-react";
import { ANALYSIS_CHECKS, areas, formatArea, isCurrent, useAnalysisLayer } from "../../events/analysis";
import { useSession } from "../../events/store";
import { useUi } from "../../lib/ui";
import { ExplodeSlider } from "../canvas/ExplodeControls";
import { Segmented } from "../ui/primitives";
import { useStudio, VIEW_KEYS, type CameraView } from "./studio";

const VIEWS: { view: CameraView; label: string }[] = [
  { view: "front", label: "Front" },
  { view: "side", label: "Side" },
  { view: "top", label: "Top" },
  { view: "home", label: "Reset" },
];
const keyOf = (view: CameraView) => Object.keys(VIEW_KEYS).find((k) => VIEW_KEYS[k] === view);

/** A pill in the view bar; `on` marks a switch that is on or a popover that is open. */
export function BarButton({ on = false, className = "", children, ...rest }: { on?: boolean; className?: string; children: ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] font-semibold whitespace-nowrap transition disabled:cursor-not-allowed disabled:opacity-45 ${
        on ? "bg-accent-soft text-accent" : "text-ink-2 enabled:hover:bg-tile enabled:hover:text-ink"
      } ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/** Open state for a popover under a bar button: an outside press or Escape closes it. */
function usePopover() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const press = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("pointerdown", press);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("pointerdown", press);
      window.removeEventListener("keydown", key);
    };
  }, [open]);
  return { open, setOpen, ref };
}

/** A button's word, left out when the studio is too narrow for the whole bar. */
const Word = ({ children }: { children: ReactNode }) => <span className="hidden @min-[600px]:inline">{children}</span>;

const POPOVER = "absolute top-10 left-0 z-40 animate-rise rounded-[16px] bg-card p-1.5 shadow-[var(--shadow-float)]";
/** The same popover opening to the left, for a button too close to the right edge of the window. */
const POPOVER_LEFTWARD = POPOVER.replace("left-0", "right-0");

function ViewsMenu({ disabled }: { disabled: boolean }) {
  const { open, setOpen, ref } = usePopover();
  const send = useStudio((s) => s.send);
  return (
    <div ref={ref} className="relative">
      <BarButton on={open} disabled={disabled} onClick={() => setOpen(!open)} aria-haspopup="menu" aria-expanded={open} aria-label="Views" title="Camera views (keys 1 to 4)">
        <Video className="h-4 w-4" /> <Word>Views</Word> <ChevronDown className={`h-3.5 w-3.5 transition ${open ? "rotate-180" : ""}`} />
      </BarButton>
      {open && (
        <div role="menu" className={`${POPOVER} w-44`}>
          {VIEWS.map((v) => (
            <button
              key={v.view}
              type="button"
              role="menuitem"
              onClick={() => {
                send({ kind: "view", view: v.view });
                setOpen(false);
              }}
              className="flex h-9 w-full items-center justify-between rounded-[10px] px-3 text-left text-[14px] font-semibold text-ink-2 hover:bg-tile hover:text-ink"
            >
              {v.label}
              <kbd className="num rounded-[6px] bg-tile px-1.5 font-label text-[11px] text-muted">{keyOf(v.view)}</kbd>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ExplodeMenu({ disabled }: { disabled: boolean }) {
  const { open, setOpen, ref } = usePopover();
  const explode = useUi((s) => s.explode);
  const pct = Math.round(explode * 100);
  return (
    <div ref={ref} className="relative">
      <BarButton
        on={open || pct > 0}
        disabled={disabled}
        onClick={() => setOpen(!open)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label="Explode"
        title="Pull every part apart"
        data-control="explode"
      >
        <Expand className="h-4 w-4" /> <Word>Explode</Word>
        {pct > 0 && <span className="num font-label text-[11px]">{pct}%</span>}
      </BarButton>
      {open && (
        <div role="dialog" aria-label="Explode" className={`${POPOVER} px-3`}>
          <ExplodeSlider />
        </div>
      )}
    </div>
  );
}

/** The Surface menu's width, w-60. */
const SURFACE_MENU_PX = 240;

function SurfaceMenu({ disabled }: { disabled: boolean }) {
  const { open, setOpen, ref } = usePopover();
  const [leftward, setLeftward] = useState(false);
  const analysis = useSession((s) => s.analysis);
  const cadUrl = useSession((s) => s.cad?.glb_url);
  const check = useAnalysisLayer((s) => s.check);
  const show = useAnalysisLayer((s) => s.show);
  const current = isCurrent(analysis, cadUrl);
  const title = current
    ? "Colour the model by overhang, wall thickness or clearance"
    : analysis
      ? "The surface check is of an earlier build; Mechanic checks again with print_prep"
      : "No surface check yet; Mechanic runs one with print_prep";
  return (
    <div ref={ref} className="relative">
      <BarButton
        on={open || (current && !!check)}
        disabled={disabled || !current}
        onClick={() => {
          // Where the bar wraps on a phone the button sits at the right edge: the menu opens to its left there.
          const left = ref.current?.getBoundingClientRect().left ?? 0;
          setLeftward(left + SURFACE_MENU_PX > window.innerWidth - 12);
          setOpen(!open);
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Surface checks"
        title={title}
        data-target="studio:surface"
      >
        <Layers className="h-4 w-4" /> <Word>Surface</Word> <ChevronDown className={`h-3.5 w-3.5 transition ${open ? "rotate-180" : ""}`} />
      </BarButton>
      {open && current && (
        <div role="menu" aria-label="Surface checks" className={`${leftward ? POPOVER_LEFTWARD : POPOVER} w-60`}>
          {[null, ...ANALYSIS_CHECKS].map((c) => {
            const info = c ? analysis.checks[c] : undefined;
            if (c && !info) return null;
            // What needs a fix at Mechanic's limit; red at sharp edges, contact lines and specks needs none.
            const area = c ? areas(analysis, c).finding : 0;
            return (
              <button
                key={c ?? "off"}
                type="button"
                role="menuitemradio"
                aria-checked={check === c}
                onClick={() => {
                  show(c);
                  setOpen(false);
                }}
                className={`flex h-9 w-full items-center justify-between gap-3 rounded-[10px] px-3 text-left text-[14px] font-semibold hover:bg-tile hover:text-ink ${check === c ? "bg-accent-soft text-accent" : "text-ink-2"}`}
              >
                {info ? info.label : "Off"}
                {c && <span className={`num font-label text-[11px] ${area >= 1 ? "text-fail-ink" : "text-ok-ink"}`}>{area >= 1 ? formatArea(area) : "none"}</span>}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function ViewToolbar() {
  const tab = useUi((s) => s.tab);
  const look = useUi((s) => s.look);
  const compare = useUi((s) => s.compare);
  const studio = useUi((s) => s.studio);
  const setStudio = useUi((s) => s.setStudio);
  const product = useSession((s) => s.product);
  const cad = useSession((s) => s.cad);
  if (tab === "omniverse" || tab === "agents") return null;
  // The simulation replays only take the grid switch; the rest needs the live 3D model, and
  // rests (dimmed) while the Model tab shows the render or two versions side by side.
  const stage = tab === "simulation";
  const live = tab === "modell" ? look === "3d" && !compare && (product === "drone" || !!cad?.glb_url) : tab === "cad" && !!cad?.glb_url;
  return (
    // The canvas below keeps its own top margin; the bar sits 12 px above it. On a narrow
    // studio the buttons drop their words (a container query) and a phone wraps the bar, so
    // nothing scrolls away and the popovers never clip.
    <div role="toolbar" aria-label="View" className="@container mt-3 -mb-2 flex min-h-10 shrink-0 flex-wrap items-center gap-x-1 gap-y-1.5" data-target="view_bar">
      {!stage && (
        <>
          <div className={live ? "" : "pointer-events-none opacity-45"} aria-disabled={!live}>
            <Segmented
              size="sm"
              value={studio.ortho ? "ortho" : "perspective"}
              onChange={(v) => setStudio({ ortho: v === "ortho" })}
              options={[
                { value: "perspective", label: "Perspective", target: "studio:perspective" },
                { value: "ortho", label: "Ortho", target: "studio:ortho" },
              ]}
            />
          </div>
          <ViewsMenu disabled={!live} />
          <ExplodeMenu disabled={!live} />
          <SurfaceMenu disabled={!live} />
          <span className="mx-1.5 hidden h-5 w-px shrink-0 bg-track @min-[600px]:block" aria-hidden />
        </>
      )}
      <BarButton on={studio.grid} disabled={!live && !stage} onClick={() => setStudio({ grid: !studio.grid })} aria-pressed={studio.grid} aria-label="Grid" title="Grid lines (G)" data-target="studio:grid">
        <Grid3x3 className="h-4 w-4" /> <Word>Grid</Word>
      </BarButton>
      {!stage && (
        <BarButton on={studio.labels} disabled={!live} onClick={() => setStudio({ labels: !studio.labels })} aria-pressed={studio.labels} aria-label="Labels" title="Part names (L)" data-target="studio:labels">
          <Tag className="h-4 w-4" /> <Word>Labels</Word>
        </BarButton>
      )}
    </div>
  );
}
