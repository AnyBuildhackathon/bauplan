// The parts panel beside the studio's tool rail: one search over the catalog's part models
// (every library part's 3D model from agent/data/models, listed in
// web/public/models/parts/index.json, each previewed from its own model) and the library's
// builds. A part goes to Mechanic as a request to edit and send; a build rebuilds on a fresh
// bench. Importing a STEP file is not here yet.
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Box, RotateCcw, Search, Send, X } from "lucide-react";
import { useSource, type ReferenceBuild } from "../../events/source";
import { assetUrl } from "../../lib/api";
import { fmtNum } from "../../lib/format";
import { useUi } from "../../lib/ui";
import { Segmented } from "../ui/primitives";
import { usePartThumb } from "./partThumbs";
import { useStudio } from "./studio";

/** One part model of the catalog, as web/scripts/parts_index.mjs writes it. */
export interface CatalogPart {
  id: string;
  name: string;
  category: string;
  kind: "official" | "look-alike" | "approximate";
  glb: string;
  size_mm: number[];
  source_url: string | null;
}

type Filter = "all" | "parts" | "builds";
type Picked = { kind: "part"; part: CatalogPart } | { kind: "build"; build: ReferenceBuild };

const KIND: Record<CatalogPart["kind"], { label: string; tone: string }> = {
  official: { label: "Official model", tone: "bg-ok-soft text-ok-ink" },
  "look-alike": { label: "Look-alike", tone: "bg-tile text-ink-2" },
  approximate: { label: "Approximate", tone: "bg-agent-soft text-agent-ink" },
};

const categoryLabel = (c: string) => (c === "vtx" ? "video transmitter" : c.replace(/_/g, " "));
const sizeLine = (mm: number[]) => (mm.length === 3 ? `${mm.map((v) => fmtNum(v, v < 10 ? 1 : 0)).join(" × ")} mm` : "");
const modelUrl = (glb: string) => `${import.meta.env.BASE_URL}${glb.replace(/^\//, "")}`;

/** Every word of the search appears in the text, in any order: "lava 1s" finds the LAVA II 1S too. */
function matches(text: string, words: string[]): boolean {
  const t = text.toLowerCase();
  return words.every((w) => t.includes(w));
}

let catalog: Promise<CatalogPart[]> | null = null;

/** The catalog, fetched once per session when the panel first opens. */
function useCatalog(): CatalogPart[] | null {
  const [parts, setParts] = useState<CatalogPart[] | null>(null);
  useEffect(() => {
    catalog ??= fetch(`${import.meta.env.BASE_URL}models/parts/index.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((body: { parts: CatalogPart[] }) => body.parts)
      .catch(() => {
        catalog = null;
        return [];
      });
    let live = true;
    void catalog.then((p) => live && setParts(p));
    return () => {
      live = false;
    };
  }, []);
  return parts;
}

/** True once the element has come within a screen of the visible part of the panel. */
function useNear(ref: React.RefObject<HTMLElement | null>): boolean {
  const [near, setNear] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || near) return;
    const io = new IntersectionObserver(([entry]) => entry.isIntersecting && setNear(true), { rootMargin: "240px" });
    io.observe(el);
    return () => io.disconnect();
  }, [ref, near]);
  return near;
}

function PartThumb({ part, className = "" }: { part: CatalogPart; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const image = usePartThumb(modelUrl(part.glb), useNear(ref));
  return (
    <div ref={ref} className={`flex items-center justify-center overflow-hidden rounded-[10px] bg-stage ${className}`}>
      {image ? (
        <img src={image} alt="" className="h-full w-full object-contain" draggable={false} />
      ) : image === "" ? (
        <Box className="h-7 w-7 text-faint" strokeWidth={1.5} />
      ) : (
        <span className="h-full w-full animate-pulse bg-track/50" />
      )}
    </div>
  );
}

function PartTile({ part, picked, onPick }: { part: CatalogPart; picked: boolean; onPick: () => void }) {
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={picked}
      title={part.name}
      data-target={`part:${part.id}`}
      className={`flex min-w-0 flex-col rounded-[14px] bg-page-2 p-1.5 pb-2 text-left transition ${picked ? "ring-[1.5px] ring-ink" : "ring-1 ring-transparent hover:ring-track"}`}
    >
      <PartThumb part={part} className="aspect-square w-full" />
      <span className="mt-1.5 line-clamp-2 px-1 text-[13px] leading-snug font-semibold text-ink">{part.name}</span>
      <span className="mt-0.5 truncate px-1 font-label text-[10.5px] text-muted">{categoryLabel(part.category)}</span>
    </button>
  );
}

function BuildRow({ build, picked, onPick }: { build: ReferenceBuild; picked: boolean; onPick: () => void }) {
  const thumb = assetUrl(build.thumbnail_url);
  const parts = build.printed + build.bought;
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={picked}
      data-target={`build:${build.id}`}
      className={`flex w-full min-w-0 items-center gap-2.5 rounded-[14px] bg-page-2 p-1.5 pr-3 text-left transition ${picked ? "ring-[1.5px] ring-ink" : "ring-1 ring-transparent hover:ring-track"}`}
    >
      <span className="h-12 w-[4.5rem] shrink-0 overflow-hidden rounded-[10px] bg-stage">{thumb && <img src={thumb} alt="" className="h-full w-full object-cover" loading="lazy" />}</span>
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 text-[13px] leading-snug font-semibold text-ink">{build.name}</span>
        <span className="num mt-0.5 block truncate font-label text-[10.5px] text-muted">
          {parts} {parts === 1 ? "part" : "parts"}
          {build.printed ? ` · ${build.printed} printed` : ""}
        </span>
      </span>
    </button>
  );
}

/** The picked part or build at the foot of the panel, with what can be done with it. */
function PickedSheet({ picked, onClose }: { picked: Picked; onClose: () => void }) {
  const live = useSource((s) => s.mode === "live" && s.live === "open");
  const [confirm, setConfirm] = useState(false);
  useEffect(() => setConfirm(false), [picked]);
  const close = (
    <button type="button" onClick={onClose} className="-mt-1 -mr-1.5 rounded-full p-1.5 text-muted hover:bg-tile" aria-label="Close">
      <X className="h-4 w-4" />
    </button>
  );
  if (picked.kind === "part") {
    const { part } = picked;
    const ask = () => {
      useStudio.getState().compose(`Use the ${part.name} as the ${categoryLabel(part.category)}.`);
      useUi.getState().setRightTab("mechanic");
    };
    return (
      <div className="shrink-0 border-t border-line px-4 pt-3 pb-4" data-target="parts:picked">
        <div className="flex gap-3">
          <PartThumb part={part} className="h-[76px] w-[76px] shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="flex items-start gap-2">
              <p className="min-w-0 flex-1 text-[15px] leading-snug font-bold text-ink">{part.name}</p>
              {close}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <span className="text-[13px] font-medium text-ink-2">{categoryLabel(part.category)}</span>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${KIND[part.kind].tone}`}>{KIND[part.kind].label}</span>
            </div>
            <p className="num mt-1 flex items-center gap-2 text-[13px] text-muted">
              {sizeLine(part.size_mm)}
              {part.source_url && (
                <a href={part.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 font-semibold text-link hover:underline">
                  Source <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
              )}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={ask}
          className="mt-3 flex h-9 w-full items-center justify-center gap-2 rounded-full bg-ink text-[14px] font-semibold text-white shadow-[var(--shadow-pill)] hover:bg-[#333]"
        >
          <Send className="h-4 w-4" /> Ask Mechanic to use it
        </button>
      </div>
    );
  }
  const { build } = picked;
  const rebuild = () => {
    useUi.getState().resetUi();
    void useSource.getState().startReference(build.id);
  };
  return (
    <div className="shrink-0 border-t border-line px-4 pt-3 pb-4" data-target="parts:picked">
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 text-[15px] leading-snug font-bold text-ink">{build.name}</p>
        {close}
      </div>
      <p className="mt-1 line-clamp-3 text-[13px] leading-snug text-muted">{build.summary}</p>
      {confirm ? (
        <div className="mt-3 rounded-[14px] bg-agent-soft px-3 py-2.5">
          <p className="text-[13px] leading-snug text-ink">This starts a fresh bench with the {build.name.toLowerCase()}. Rebuild it?</p>
          <div className="mt-2 flex gap-2">
            <button type="button" onClick={rebuild} className="h-8 rounded-full bg-ink px-3.5 text-[13px] font-bold text-white hover:brightness-110">
              Rebuild
            </button>
            <button type="button" onClick={() => setConfirm(false)} className="h-8 rounded-full bg-card px-3.5 text-[13px] font-bold text-ink-2 shadow-[var(--shadow-pill)] hover:bg-page-2">
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirm(true)}
          disabled={!live}
          title={live ? undefined : "Rebuilding needs the backend"}
          className="mt-3 flex h-9 w-full items-center justify-center gap-2 rounded-full bg-ink text-[14px] font-semibold text-white shadow-[var(--shadow-pill)] hover:bg-[#333] disabled:opacity-45"
        >
          <RotateCcw className="h-4 w-4" /> Rebuild on a fresh bench
        </button>
      )}
    </div>
  );
}

export function PartsPanel() {
  const setPartsOpen = useUi((s) => s.setPartsOpen);
  const parts = useCatalog();
  const builds = useSource((s) => s.references);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [picked, setPicked] = useState<Picked | null>(null);
  const search = useRef<HTMLInputElement>(null);
  useEffect(() => search.current?.focus({ preventScroll: true }), []);

  const words = useMemo(() => query.trim().toLowerCase().split(/\s+/).filter(Boolean), [query]);
  const shownParts = useMemo(() => (parts ?? []).filter((p) => matches(`${p.name} ${p.category} ${categoryLabel(p.category)} ${p.id}`, words)), [parts, words]);
  const shownBuilds = useMemo(() => builds.filter((b) => matches(`${b.name} ${b.summary}`, words)), [builds, words]);
  const showParts = filter !== "builds";
  const showBuilds = filter !== "parts" && builds.length > 0;
  const nothing = (!showParts || shownParts.length === 0) && (!showBuilds || shownBuilds.length === 0) && parts !== null;

  return (
    <div
      role="dialog"
      aria-label="Parts"
      className="absolute top-3 bottom-3 left-[68px] z-30 flex w-[min(340px,calc(100%-136px))] animate-rise flex-col overflow-hidden rounded-[20px] bg-card shadow-[var(--shadow-float)]"
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        e.stopPropagation();
        if (query) setQuery("");
        else setPartsOpen(false);
      }}
      data-target="parts_panel"
    >
      <div className="flex shrink-0 items-center gap-2 px-4 pt-3.5">
        <h2 className="min-w-0 flex-1 text-[17px] font-semibold tracking-[-0.01em] text-ink">Parts</h2>
        <button type="button" onClick={() => setPartsOpen(false)} className="-mr-1.5 rounded-full p-1.5 text-muted hover:bg-tile hover:text-ink" aria-label="Close parts">
          <X className="h-4.5 w-4.5" />
        </button>
      </div>
      <div className="shrink-0 space-y-2.5 px-4 pt-2.5 pb-3">
        <label className="flex h-9 items-center gap-2 rounded-full bg-tile px-3.5">
          <Search className="h-4 w-4 shrink-0 text-muted" />
          <input
            ref={search}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search parts and builds"
            aria-label="Search parts and builds"
            className="min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-muted"
          />
          {query && (
            <button type="button" onClick={() => setQuery("")} className="rounded-full p-0.5 text-muted hover:text-ink" aria-label="Clear the search">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </label>
        <Segmented<Filter>
          size="sm"
          value={filter}
          onChange={setFilter}
          className="w-full [&>button]:flex-1 [&>button]:justify-center"
          options={[
            { value: "all", label: "All" },
            { value: "parts", label: <>Parts <span className="num font-label text-[11px] font-medium">{shownParts.length}</span></> },
            { value: "builds", label: <>Builds <span className="num font-label text-[11px] font-medium">{shownBuilds.length}</span></> },
          ]}
        />
      </div>
      <div className="scroll-soft min-h-0 flex-1 overflow-y-auto px-4 pb-4">
        {parts === null && <p className="py-6 text-center text-[14px] text-muted">Loading the catalog …</p>}
        {nothing && <p className="py-6 text-center text-[14px] text-muted">Nothing matches “{query}”.</p>}
        {showParts && shownParts.length > 0 && (
          <section>
            <h3 className="eyebrow mb-2">Parts</h3>
            <div className="grid grid-cols-2 gap-2">
              {shownParts.map((p) => (
                <PartTile key={p.id} part={p} picked={picked?.kind === "part" && picked.part.id === p.id} onPick={() => setPicked({ kind: "part", part: p })} />
              ))}
            </div>
          </section>
        )}
        {showBuilds && shownBuilds.length > 0 && (
          <section className={showParts && shownParts.length > 0 ? "mt-5" : ""}>
            <h3 className="eyebrow mb-2">Builds</h3>
            <div className="space-y-2">
              {shownBuilds.map((b) => (
                <BuildRow key={b.id} build={b} picked={picked?.kind === "build" && picked.build.id === b.id} onPick={() => setPicked({ kind: "build", build: b })} />
              ))}
            </div>
          </section>
        )}
      </div>
      {picked && <PickedSheet picked={picked} onClose={() => setPicked(null)} />}
    </div>
  );
}
