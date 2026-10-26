// The view bar between the canvas tabs and the canvas: perspective or orthographic, the camera
// views (keys 1 to 4), the explode switch with its amount in a popover (key E), the surface check colour layer (overhang,
// wall thickness or clearance, once Mechanic has checked this build), and the grid, label and
// section switches; the section cuts the model across X, Y or Z at a slider's place (key S).
// The grid switch also hides the lines of the test stage in the simulation replays; the rest needs
// the live model, so it rests while the Model tab shows the render or two versions side by side.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowDownUp, ChevronDown, Expand, Grid3x3, Layers, ScissorsLineDashed, Tag, Video } from "lucide-react";
import { ANALYSIS_CHECKS, areas, formatArea, isCurrent, useAnalysisLayer } from "../../events/analysis";
import { useSession } from "../../events/store";
import { useUi } from "../../lib/ui";
import { fmtNum } from "../../lib/format";
import { useExplodePlan } from "../canvas/explode";
import { ExplodeSlider } from "../canvas/ExplodeControls";
import { Segmented } from "../ui/primitives";
import { useStudio, VIEW_KEYS, type CameraView, type SectionAxis } from "./studio";

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
  const exploded = useUi((s) => s.exploded);
  const amount = useUi((s) => s.explodeAmount);
  const setExploded = useUi((s) => s.setExploded);
  const counts = useExplodePlan((s) => s.counts);
  const ways = counts
    ? ([
        [counts.fastener, "along its axis", "along their axes"],
        [counts.joint, "along its joint", "along their joints"],
        [counts.mate, "off its face", "off their faces"],
        [counts.centre, "out from the middle", "out from the middle"],
      ] as const).filter(([n]) => n > 0).map(([n, one, many]) => `${n} ${n === 1 ? one : many}`)
    : [];
  return (
    <div ref={ref} className="relative">
      <BarButton
        on={open || exploded}
        disabled={disabled}
        onClick={() => {
          // Pressed, the parts glide apart at once; the popover sets how far.
          if (!exploded) setExploded(true);
          setOpen(!open || !exploded);
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-pressed={exploded}
        aria-label="Explode"
        title="Pull the parts apart along their assembly directions (E)"
        data-control="explode"
      >
        <Expand className="h-4 w-4" /> <Word>Explode</Word>
        {exploded && <span className="num font-label text-[11px]">{Math.round(amount * 100)}%</span>}
      </BarButton>
      {open && exploded && (
        <div role="dialog" aria-label="Explode" className={`${POPOVER} w-72 px-3 pt-1 pb-3`}>
          <div className="flex items-center gap-3">
            <ExplodeSlider />
            <button
              type="button"
              onClick={() => {
                setExploded(false);
                setOpen(false);
              }}
              className="ml-auto inline-flex h-8 items-center rounded-full px-2.5 text-[13px] font-semibold text-ink-2 hover:bg-tile hover:text-ink"
              data-target="explode:off"
            >
              Off
            </button>
          </div>
          <p className="text-[12px] leading-snug font-semibold text-muted" data-target="explode:ways">
            {ways.length ? `Each part leaves the way it goes on: ${ways.join(", ")}.` : "Each part leaves the way it goes on."}
          </p>
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

/** The Section menu's width, w-72. */
const SECTION_MENU_PX = 288;

function SectionMenu({ disabled }: { disabled: boolean }) {
  const { open, setOpen, ref } = usePopover();
  const [leftward, setLeftward] = useState(false);
  const section = useStudio((s) => s.section);
  const range = useStudio((s) => s.sectionRange);
  const setSection = useStudio((s) => s.setSection);
  const at = section?.at ?? null;
  const span = range ? range.max - range.min : 0;
  // About two hundred steps across the model, in tenths of a millimetre.
  const step = Math.max(0.1, Math.round((span / 200) * 10) / 10);
  const pct = range && at !== null && span > 0 ? ((at - range.min) / span) * 100 : 50;
  const label = section && at !== null ? `${section.axis.toUpperCase()} ${fmtNum(at, Math.abs(at) < 100 ? 1 : 0)}` : null;
  return (
    <div ref={ref} className="relative">
      <BarButton
        on={open || !!section}
        disabled={disabled}
        onClick={() => {
          // Pressed, the model is cut at once; the popover places the cut.
          if (!section) setSection({ axis: "z", at: null, keep: null });
          const left = ref.current?.getBoundingClientRect().left ?? 0;
          setLeftward(left + SECTION_MENU_PX > window.innerWidth - 12);
          setOpen(!open || !section);
        }}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-pressed={!!section}
        aria-label="Section"
        title="Cut the model to see inside (S)"
        data-target="studio:section"
      >
        <ScissorsLineDashed className="h-4 w-4" /> <Word>Section</Word>
        {label && <span className="num font-label text-[11px]">{label}</span>}
      </BarButton>
      {open && section && (
        <div role="dialog" aria-label="Section" className={`${leftward ? POPOVER_LEFTWARD : POPOVER} w-72 px-3 pt-2.5 pb-3`}>
          <div className="flex items-center gap-2">
            <Segmented
              size="sm"
              value={section.axis}
              onChange={(axis: SectionAxis) => setSection({ axis, at: null, keep: null })}
              options={(["x", "y", "z"] as const).map((axis) => ({ value: axis, label: axis.toUpperCase(), target: `section:${axis}` }))}
            />
            <button
              type="button"
              onClick={() => section.keep && setSection({ ...section, keep: section.keep === "below" ? "above" : "below" })}
              className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[13px] font-semibold text-ink-2 hover:bg-tile hover:text-ink"
              title="Keep the other half"
              data-target="section:flip"
            >
              <ArrowDownUp className="h-3.5 w-3.5" /> Flip
            </button>
            <button
              type="button"
              onClick={() => {
                setSection(null);
                setOpen(false);
              }}
              className="inline-flex h-8 items-center rounded-full px-2.5 text-[13px] font-semibold text-ink-2 hover:bg-tile hover:text-ink"
              data-target="section:off"
            >
              Off
            </button>
          </div>
          <label className="mt-2.5 flex items-center gap-2.5">
            <input
              type="range"
              min={range?.min ?? 0}
              max={range?.max ?? 1}
              step={step}
              value={at ?? 0}
              disabled={!range || at === null}
              onChange={(e) => setSection({ ...section, at: Number(e.target.value) })}
              aria-label={`Section along ${section.axis.toUpperCase()}`}
              className="bevel-range min-w-0 flex-1"
              style={{ "--p": `${pct}%` } as React.CSSProperties}
            />
            <span className="num w-[72px] shrink-0 text-right text-[14px] font-bold text-ink" data-target="section:at">
              {at === null ? "…" : `${fmtNum(at, 1)} mm`}
            </span>
          </label>
          {range && (
            <div className="num mt-0.5 flex justify-between pr-[82px] text-[11px] font-semibold text-muted">
              <span>{fmtNum(range.min, 0)} mm</span>
              <span>{fmtNum(range.max, 0)} mm</span>
            </div>
          )}
          <p className="mt-1.5 text-[12px] leading-snug font-semibold text-muted">Cut faces show darker. Keeps the half {section.keep === "above" ? "above" : "below"} the cut.</p>
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
      {!stage && <SectionMenu disabled={!live} />}
    </div>
  );
}
