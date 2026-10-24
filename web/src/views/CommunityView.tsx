// Community: projects people published (GET /api/community), to open and keep working on.
// Pick one to inspect it on the right; "Remix" opens it on a fresh bench linked to its original
// (POST /api/community/{id}/remix), and "Publish current build" shares the bench (POST /api/community).
import { useEffect, useMemo, useState } from "react";
import { Box, Download, GitFork, Search, Send, X } from "lucide-react";
import { useSession } from "../events/store";
import { useSource } from "../events/source";
import { apiUrl, assetUrl } from "../lib/api";
import { useUi } from "../lib/ui";

/** A published project, as GET /api/community lists it. */
export interface CommunityEntry {
  id: string;
  title: string;
  description: string;
  author: string;
  published_at: string | null;
  product: string;
  product_label: string;
  base: string | null;
  seed: boolean;
  remixed_from: { id: string; title: string; author: string } | null;
  remixes: number;
  metrics: {
    mass_g?: number | null;
    cost_eur?: number | null;
    parts?: number | null;
    printed?: number;
    requirements_passed?: number;
    requirements?: number;
  };
  bom: { name: string; qty: number; unit_price_eur: number }[];
  versions: unknown[];
  files: { name: string; url: string }[];
  thumbnail_url: string | null;
}

type Sort = "new" | "popular";
const AUTHOR_KEY = "anybuild.author";
const PARTS_SHOWN = 5;
const TEAM = "AnyBuild team";

function storedAuthor(): string {
  try {
    return localStorage.getItem(AUTHOR_KEY) ?? "";
  } catch {
    return "";
  }
}

function dateLabel(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function numbers(entry: CommunityEntry): { label: string; value: string }[] {
  const m = entry.metrics;
  return [
    { label: "Mass", value: m.mass_g != null ? `${Math.round(m.mass_g)} g` : "–" },
    { label: "Parts cost", value: m.cost_eur != null ? `${m.cost_eur.toFixed(2)} €` : "–" },
    { label: "Parts", value: m.parts != null ? String(m.parts) : "–" },
    { label: "Checks", value: m.requirements ? `${m.requirements_passed ?? 0}/${m.requirements}` : "–" },
  ];
}

/** Entries the AnyBuild team published carry the AnyBuild mark next to the name. */
function Author({ name, className = "" }: { name: string; className?: string }) {
  return (
    <span className={`inline-flex min-w-0 items-center gap-1.5 ${className}`}>
      {name === TEAM && (
        <img src={`${import.meta.env.BASE_URL}logo-mark.webp`} alt="" draggable={false} className="h-4 w-4 shrink-0 rounded-[4px] select-none" />
      )}
      <span className="truncate">{name}</span>
    </span>
  );
}

function Thumbnail({ entry, className = "" }: { entry: CommunityEntry; className?: string }) {
  const url = assetUrl(entry.thumbnail_url);
  return (
    <div className={`relative overflow-hidden rounded-[12px] bg-stage ${className}`}>
      {url ? (
        <img src={url} alt="" className="h-full w-full object-cover" loading="lazy" />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-faint">
          <Box className="h-8 w-8" strokeWidth={1.5} />
        </div>
      )}
    </div>
  );
}

function Card({ entry, selected, onSelect }: { entry: CommunityEntry; selected: boolean; onSelect: () => void }) {
  const m = entry.metrics;
  const line = [
    m.mass_g != null && `${Math.round(m.mass_g)} g`,
    m.cost_eur != null && `${m.cost_eur.toFixed(2)} €`,
    m.parts != null && `${m.parts} parts`,
  ].filter(Boolean);
  return (
    <button
      type="button"
      onClick={onSelect}
      data-target={`community:${entry.id}`}
      aria-pressed={selected}
      className={`flex flex-col gap-3 rounded-[20px] bg-card p-2.5 pb-4 text-left transition ${
        selected ? "ring-[1.5px] ring-ink" : "ring-1 ring-line hover:ring-track"
      }`}
    >
      <div className="relative">
        <Thumbnail entry={entry} className="aspect-[16/10] w-full" />
        <span className="num absolute top-2.5 right-2.5 flex items-center gap-1 rounded-full bg-white/95 px-2.5 py-0.5 text-[12px] font-semibold text-ink">
          <GitFork className="h-3 w-3" /> {entry.remixes}
        </span>
      </div>
      <div className="px-1.5">
        <div className="text-[16px] leading-snug font-semibold text-ink">{entry.title}</div>
        <div className="mt-0.5 flex min-w-0 items-center text-[13px] text-muted">
          <Author name={entry.author} className="shrink-0" />
          <span className="truncate whitespace-pre">
            {entry.published_at ? ` · ${dateLabel(entry.published_at)}` : ""}
            {entry.remixed_from ? ` · remix of ${entry.remixed_from.title}` : ""}
          </span>
        </div>
        <div className="num mt-2 text-[13px] font-medium text-ink-2">{line.join(" · ")}</div>
      </div>
    </button>
  );
}

function Inspect({ entry, live, onRemix, onOpen }: { entry: CommunityEntry; live: boolean; onRemix: () => void; onOpen: (id: string) => void }) {
  return (
    <aside className="card flex max-h-full min-h-0 flex-col gap-4 self-start overflow-y-auto px-5 pt-4 pb-5" data-target="community_inspect">
      <Thumbnail entry={entry} className="aspect-[16/10] w-full shrink-0" />
      <div>
        <div className="text-[13px] font-medium text-muted">
          {[entry.product_label, dateLabel(entry.published_at), `${entry.remixes} remix${entry.remixes === 1 ? "" : "es"}`].filter(Boolean).join(" · ")}
        </div>
        <h2 className="text-[20px] leading-tight font-semibold tracking-[-0.01em] text-ink">{entry.title}</h2>
        <div className="mt-0.5 flex items-center gap-1 text-[14px] font-medium text-ink-2">
          by <Author name={entry.author} />
        </div>
        {entry.remixed_from && (
          <button
            type="button"
            onClick={() => onOpen(entry.remixed_from!.id)}
            className="mt-2 flex max-w-full items-center gap-1.5 rounded-full bg-tile px-3 py-1 text-[13px] font-medium text-ink-2 transition hover:bg-track"
          >
            <GitFork className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">
              Remixed from {entry.remixed_from.title} by {entry.remixed_from.author}
            </span>
          </button>
        )}
        {entry.description && <p className="mt-2 font-serif text-[16px] leading-snug text-ink-2">{entry.description}</p>}
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-2 border-y border-line py-3">
        {numbers(entry).map((n) => (
          <div key={n.label}>
            <div className="text-[13px] font-medium text-muted">{n.label}</div>
            <div className="num text-[22px] leading-tight font-semibold text-ink">{n.value}</div>
          </div>
        ))}
      </div>
      {entry.bom.length > 0 && (
        <div>
          <div className="eyebrow mb-1.5">Parts</div>
          <ul className="flex flex-col gap-1 text-[14px] text-ink-2">
            {entry.bom.slice(0, PARTS_SHOWN).map((item, i) => (
              <li key={`${item.name}-${i}`} className="flex gap-3">
                <span className="min-w-0 flex-1 truncate">
                  {item.qty > 1 ? `${item.qty}× ` : ""}
                  {item.name}
                </span>
                <span className="num shrink-0 text-muted">{(item.unit_price_eur * item.qty).toFixed(2)} €</span>
              </li>
            ))}
            {entry.bom.length > PARTS_SHOWN && <li className="text-muted">and {entry.bom.length - PARTS_SHOWN} more</li>}
          </ul>
        </div>
      )}
      {entry.files.length > 0 && (
        <div>
          <div className="eyebrow mb-1.5">Files</div>
          <div className="flex flex-wrap gap-1.5">
            {entry.files.map((f) => (
              <a
                key={f.name}
                href={assetUrl(f.url) ?? undefined}
                download={f.name}
                className="flex items-center gap-1 rounded-full bg-tile px-2.5 py-1 text-[12px] font-medium text-ink-2 transition hover:bg-track"
              >
                <Download className="h-3 w-3" /> {f.name}
              </a>
            ))}
          </div>
        </div>
      )}
      <button
        type="button"
        onClick={onRemix}
        disabled={!live}
        data-target="community_remix"
        className="flex h-12 shrink-0 items-center justify-center gap-2 rounded-full bg-ink text-[16px] font-semibold text-white transition hover:bg-[#333] disabled:bg-tile disabled:text-faint"
      >
        <GitFork className="h-4.5 w-4.5" /> Remix
      </button>
      <p className="-mt-2 text-center text-[13px] text-muted">
        {live ? "Opens a copy on your bench to keep working on." : "Remixing needs the live backend."}
      </p>
    </aside>
  );
}

function PublishDialog({ onClose, onPublished }: { onClose: () => void; onPublished: (entry: CommunityEntry) => void }) {
  const productLabel = useSession((s) => s.productLabel);
  const remixedFrom = useSession((s) => s.remixedFrom);
  const [title, setTitle] = useState(remixedFrom ? `${remixedFrom.title} remix` : productLabel === "Any product" ? "" : productLabel);
  const [description, setDescription] = useState("");
  const [author, setAuthor] = useState(storedAuthor);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      localStorage.setItem(AUTHOR_KEY, author.trim());
    } catch {
      // Private windows may refuse storage; the name is asked again next time.
    }
    try {
      const res = await fetch(apiUrl("/api/community"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description, author }),
      });
      const body = (await res.json()) as { item?: CommunityEntry; detail?: string };
      if (!res.ok || !body.item) throw new Error(body.detail ?? `HTTP ${res.status}`);
      onPublished(body.item);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Not published.");
      setBusy(false);
    }
  };

  const field = "w-full rounded-[12px] bg-tile px-3.5 py-2.5 text-[15px] text-ink outline-none placeholder:text-faint focus:ring-[1.5px] focus:ring-ink";
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-ink/25 backdrop-blur-[2px]" onMouseDown={onClose}>
      <form
        className="w-[440px] animate-rise rounded-[24px] bg-card p-6 shadow-[var(--shadow-float)]"
        onMouseDown={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-[20px] font-semibold tracking-[-0.01em] text-ink">Publish to community</h2>
            <p className="text-[14px] text-muted">
              {remixedFrom ? `Links back to ${remixedFrom.title} by ${remixedFrom.author}.` : "Shares the spec, parts, CAD files and renders."}
            </p>
          </div>
          <button type="button" onClick={onClose} className="-mt-1 -mr-2 rounded-full p-2 text-faint hover:bg-tile hover:text-ink-2" aria-label="Close">
            <X className="h-4.5 w-4.5" />
          </button>
        </div>
        <label className="mb-3 block">
          <span className="mb-1 block text-[13px] font-semibold text-ink-2">Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} className={field} required maxLength={80} autoFocus />
        </label>
        <label className="mb-3 block">
          <span className="mb-1 block text-[13px] font-semibold text-ink-2">Description</span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            maxLength={400}
            placeholder="What it does and what you changed"
            className={`${field} resize-none`}
          />
        </label>
        <label className="mb-4 block">
          <span className="mb-1 block text-[13px] font-semibold text-ink-2">Your name</span>
          <input value={author} onChange={(e) => setAuthor(e.target.value)} className={field} required maxLength={40} />
        </label>
        {error && <p className="mb-3 text-[14px] font-medium text-fail-ink">{error}</p>}
        <button
          type="submit"
          disabled={busy || !title.trim() || !author.trim()}
          className="flex h-11 w-full items-center justify-center gap-2 rounded-full bg-ink text-[15px] font-semibold text-white transition hover:bg-[#333] disabled:bg-tile disabled:text-faint"
        >
          <Send className="h-4 w-4" /> {busy ? "Publishing …" : "Publish"}
        </button>
      </form>
    </div>
  );
}

export function CommunityView() {
  const live = useSource((s) => s.mode === "live" && s.live === "open");
  const startRemix = useSource((s) => s.startRemix);
  const resetUi = useUi((s) => s.resetUi);
  const setView = useUi((s) => s.setView);
  const focus = useUi((s) => s.communityFocus);
  const hasBuild = useSession((s) => !!s.bom);
  const [entries, setEntries] = useState<CommunityEntry[]>([]);
  const [sort, setSort] = useState<Sort>("new");
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string | null>(focus);
  const [publishing, setPublishing] = useState(false);

  // Fresh feed on every visit; the recorded demo reads the same seeds from a static file.
  useEffect(() => {
    fetch(live ? apiUrl("/api/community") : "/community/feed.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { items?: CommunityEntry[] } | CommunityEntry[] | null) => {
        const items = Array.isArray(body) ? body : body?.items;
        if (items) setEntries(items);
      })
      .catch(() => undefined);
  }, [live]);

  // Opened from a "Remixed from" link: select that entry and bring its card into view once the feed is there.
  const [reveal, setReveal] = useState<string | null>(focus);
  useEffect(() => {
    if (focus) useUi.setState({ communityFocus: null });
  }, [focus]);
  useEffect(() => {
    if (!reveal || !entries.length) return;
    document.querySelector(`[data-target="community:${CSS.escape(reveal)}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    setReveal(null);
  }, [entries, reveal]);

  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    const found = entries.filter((e) => !q || `${e.title} ${e.description} ${e.author} ${e.product_label}`.toLowerCase().includes(q));
    const byDate = [...found].sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""));
    return sort === "popular" ? byDate.sort((a, b) => b.remixes - a.remixes) : byDate;
  }, [entries, sort, query]);
  const selected = entries.find((e) => e.id === picked) ?? items[0] ?? null;

  const remix = (id: string) => {
    resetUi();
    setView("werkbank");
    void startRemix(id);
  };

  const published = (entry: CommunityEntry) => {
    setPublishing(false);
    setEntries((all) => [entry, ...all.filter((e) => e.id !== entry.id)].map((e) => (e.id === entry.remixed_from?.id ? { ...e, remixes: e.remixes + 1 } : e)));
    setPicked(entry.id);
    setSort("new");
    setQuery("");
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_360px] gap-6 px-6 pt-5 pb-5">
      <div className="flex min-h-0 min-w-0 flex-col">
        <div className="flex shrink-0 items-end gap-6 border-b border-line" role="tablist">
          {(
            [
              ["new", "New"],
              ["popular", "Popular"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={sort === value}
              onClick={() => setSort(value)}
              className={`-mb-px border-b-2 px-0.5 pb-3 text-[16px] transition ${
                sort === value ? "border-ink font-semibold text-ink" : "border-transparent font-medium text-muted hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
          <label className="mb-2 ml-auto flex h-9 w-60 items-center gap-2 rounded-full bg-tile px-3.5">
            <Search className="h-4 w-4 shrink-0 text-muted" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search the community"
              aria-label="Search the community"
              className="min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-muted"
            />
          </label>
        </div>

        <div className="scroll-soft min-h-0 flex-1 overflow-y-auto pt-5">
          <div className="mb-5 flex items-end justify-between gap-4 px-1">
            <div>
              <h1 className="text-[28px] font-semibold tracking-[-0.02em] text-ink">Community</h1>
              <p className="font-serif text-[17px] leading-snug text-ink-2">Remix a published build and keep working on it with Mechanic.</p>
            </div>
            {live && hasBuild && (
              <button
                type="button"
                onClick={() => setPublishing(true)}
                data-target="community_publish"
                className="flex h-10 shrink-0 items-center gap-2 rounded-full bg-tile px-4 text-[14px] font-semibold text-ink-2 transition hover:bg-track"
              >
                <Send className="h-4 w-4" /> Publish current build
              </button>
            )}
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-4 pb-2">
            {items.map((entry) => (
              <Card key={entry.id} entry={entry} selected={selected?.id === entry.id} onSelect={() => setPicked(entry.id)} />
            ))}
          </div>
          {items.length === 0 && entries.length > 0 && <p className="px-1 py-4 text-[15px] text-muted">Nothing matches “{query}”.</p>}
        </div>
      </div>
      {selected ? <Inspect entry={selected} live={live} onRemix={() => remix(selected.id)} onOpen={setPicked} /> : <div />}
      {publishing && <PublishDialog onClose={() => setPublishing(false)} onPublished={published} />}
    </div>
  );
}
