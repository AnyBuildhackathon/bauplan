// Library: the reference builds (the micro FPV drone first, the robot gripper second) and
// the projects saved from a session, from GET /api/library. Pick one to inspect it on the
// right, "Rebuild" starts a fresh bench from it (POST /api/library/{id}/open).
import { useEffect, useMemo, useState } from "react";
import { Box, Plus, RotateCcw, Save, Search } from "lucide-react";
import { useSession } from "../events/store";
import { useSource, type ReferenceBuild } from "../events/source";
import { apiFetch, assetUrl } from "../lib/api";
import { useUi } from "../lib/ui";

type Filter = "all" | "reference" | "project";

/** The recorded demo has no backend, so it shows the code references and the registry builds with their renders. */
const RECORDED: ReferenceBuild[] = [
  {
    id: "micro-drone",
    name: "Micro FPV drone ($59 video build)",
    summary: "The 1S 2-inch toothpick from the video, built by the drone flow from its catalog, with the MuJoCo gust test.",
    kind: "reference",
    source: "code",
    product: "drone",
    printed: 0,
    bought: 8,
    requirements: null,
    thumbnail_url: "/models/hero-drone-thumb.jpg",
    saved_at: null,
  },
  {
    id: "robot-gripper",
    name: "Robot gripper",
    summary: "Two-finger gear gripper for a robot arm, built by the gripper flow: 4 servos to choose from, the MuJoCo grip test and the servo pocket sized in FreeCAD.",
    kind: "reference",
    source: "code",
    product: "gripper",
    printed: 1,
    bought: 4,
    requirements: null,
    thumbnail_url: "/models/robot-gripper-thumb.jpg",
    saved_at: null,
  },
  ...(
    [
      ["bike-mount", "Handlebar phone and light mount", "Two-part PETG bar clamp with a TPU shim for 22.2 to 31.8 mm bars, a phone tray on top and an M5 lug for a front light.", 4, 2, 5],
      ["desk-fan", "USB desk fan", "80 mm USB fan on a printed neck and a 150 mm base; 280 g, takes a light bump.", 3, 2, 6],
      ["desk-lamp", "USB-C desk lamp", "1 W LED in a printed shade on a 200 mm arm, weighted base, USB-C in and a rocker switch.", 4, 6, 6],
      ["pet-feeder", "Automatic pet feeder", "1.3 l printed hopper over an auger turned by a 28BYJ-48 stepper, timed by an ESP32 on USB power; stays upright with a full hopper.", 3, 3, 6],
      ["phone-stand", "Desk phone stand", "Two PETG parts and four rubber feet; holds a 200 g phone at 65 degrees and takes a tap on the screen.", 2, 1, 6],
      ["plant-waterer", "Plant-watering robot", "1 litre tank, 5 V pump, capacitive soil sensor and an ESP32 on one 18650; runs about a month, stable with a full tank.", 3, 7, 6],
    ] as const
  ).map(
    ([id, name, summary, printed, bought, requirements]): ReferenceBuild => ({
      id,
      name,
      summary,
      kind: "reference",
      source: "registry",
      product: "generic",
      printed,
      bought,
      requirements,
      // Copies of agent/data/references/<id>/thumbnail.png, since the static demo has no backend.
      thumbnail_url: `/models/library/${id}.png`,
      saved_at: null,
    }),
  ),
];

const SOURCE_LABEL: Record<ReferenceBuild["source"], string> = { code: "Example", registry: "Reference", saved: "Saved" };

function savedLabel(iso: string | null): string {
  if (!iso) return "";
  const [date, time] = iso.split("T");
  return [date, time?.slice(0, 5)].filter(Boolean).join(" ");
}

function Thumbnail({ item, className = "" }: { item: ReferenceBuild; className?: string }) {
  const url = assetUrl(item.thumbnail_url);
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

function partsLine(item: ReferenceBuild): string {
  const parts = item.printed + item.bought;
  const bits = [`${parts} part${parts === 1 ? "" : "s"}`];
  if (item.printed) bits.push(`${item.printed} printed`);
  if (item.requirements != null) bits.push(`${item.requirements} requirements`);
  return bits.join(" · ");
}

function Card({ item, selected, onSelect }: { item: ReferenceBuild; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      data-target={`library:${item.id}`}
      data-control={`library:${item.id}`}
      aria-pressed={selected}
      className={`flex flex-col gap-3 rounded-[20px] bg-card p-2.5 pb-4 text-left transition ${
        selected ? "ring-[1.5px] ring-ink" : "ring-1 ring-line hover:ring-track"
      }`}
    >
      <div className="relative">
        <Thumbnail item={item} className="aspect-[16/10] w-full" />
        <span className="absolute top-2.5 left-2.5 rounded-full bg-white/95 px-2.5 py-0.5 text-[12px] font-semibold text-ink">
          {item.source === "saved" && item.saved_at ? `Saved · ${savedLabel(item.saved_at)}` : SOURCE_LABEL[item.source]}
        </span>
      </div>
      <div className="px-1.5">
        <div className="text-[16px] leading-snug font-semibold text-ink">{item.name}</div>
        <div className="mt-0.5 line-clamp-2 text-[13px] leading-snug text-muted">{item.summary}</div>
        <div className="num mt-2 text-[13px] font-medium text-ink-2">{partsLine(item)}</div>
      </div>
    </button>
  );
}

function Inspect({ item, live, onRebuild }: { item: ReferenceBuild; live: boolean; onRebuild: () => void }) {
  return (
    <aside className="card flex max-h-full min-h-0 flex-col gap-4 self-start overflow-y-auto px-5 pt-4 pb-5" data-target="library_inspect">
      <Thumbnail item={item} className="aspect-[16/10] w-full shrink-0" />
      <div>
        <div className="text-[13px] font-medium text-muted">
          {SOURCE_LABEL[item.source]}
          {item.product !== "generic" ? ` · ${item.product}` : ""}
          {item.saved_at ? ` · ${savedLabel(item.saved_at)}` : ""}
        </div>
        <h2 className="text-[20px] leading-tight font-semibold tracking-[-0.01em] text-ink">{item.name}</h2>
        <p className="mt-2 font-read text-[14px] leading-normal text-ink-2">{item.summary}</p>
      </div>
      <div className="grid grid-cols-3 gap-3 border-y border-line py-3">
        {[
          { label: "Bought", value: item.bought },
          { label: "Printed", value: item.printed },
          { label: "Requirements", value: item.requirements ?? "–" },
        ].map((n) => (
          <div key={n.label}>
            <div className="text-[13px] font-medium text-muted">{n.label}</div>
            <div className="num text-[26px] leading-tight font-semibold text-ink">{n.value}</div>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={onRebuild}
        disabled={!live}
        data-target="library_rebuild"
        className="flex h-12 shrink-0 items-center justify-center gap-2 rounded-full bg-ink text-[16px] font-semibold text-white transition hover:bg-[#333] disabled:bg-tile disabled:text-faint"
      >
        <RotateCcw className="h-4.5 w-4.5" /> Rebuild
      </button>
      <p className="-mt-2 text-center text-[13px] text-muted">
        {live ? "Starts a fresh bench from this build; then Mechanic asks what to change." : "Rebuilding needs the live backend."}
      </p>
    </aside>
  );
}

export function LibraryView() {
  const live = useSource((s) => s.mode === "live" && s.live === "open");
  const references = useSource((s) => s.references);
  const startReference = useSource((s) => s.startReference);
  const resetUi = useUi((s) => s.resetUi);
  const setView = useUi((s) => s.setView);
  const hasBuild = useSession((s) => s.versions.length > 0 || !!s.bom);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const picked = useUi((s) => s.libraryPick);
  const setPicked = useUi((s) => s.setLibraryPick);
  const [saving, setSaving] = useState(false);

  // Fresh list on every visit, so a project saved a moment ago shows up.
  useEffect(() => {
    if (!live) return;
    apiFetch("/api/library")
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { items?: ReferenceBuild[] } | null) => body?.items && useSource.setState({ references: body.items }))
      .catch(() => undefined);
  }, [live]);

  const all = live && references.length ? references : RECORDED;
  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    return all.filter((i) => (filter === "all" || i.kind === filter) && (!q || `${i.name} ${i.summary}`.toLowerCase().includes(q)));
  }, [all, filter, query]);
  const selected = all.find((i) => i.id === picked) ?? items[0] ?? null;
  const counts = { all: all.length, reference: all.filter((i) => i.kind === "reference").length, project: all.filter((i) => i.kind === "project").length };

  const rebuild = (id: string) => {
    resetUi();
    setView("werkbank");
    void startReference(id);
  };

  const save = async () => {
    setSaving(true);
    try {
      const res = await apiFetch("/api/library", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const body = (await res.json()) as { item?: ReferenceBuild; detail?: string };
      if (!res.ok || !body.item) throw new Error(body.detail ?? `HTTP ${res.status}`);
      useSource.setState((s) => ({ references: [...s.references.filter((r) => r.id !== body.item!.id), body.item!] }));
      setPicked(body.item.id);
      setFilter("all");
    } catch (err) {
      useSource.setState({ notice: `Not saved (${err instanceof Error ? err.message : "error"}).` });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_360px] gap-6 px-6 pt-5 pb-5">
      <div className="flex min-h-0 min-w-0 flex-col">
        <div className="flex shrink-0 items-end gap-6 border-b border-line" role="tablist">
          {(
            [
              ["all", "All"],
              ["reference", "References"],
              ["project", "Saved"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={filter === value}
              onClick={() => setFilter(value)}
              className={`-mb-px flex items-center gap-2 border-b-2 px-0.5 pb-3 text-[16px] transition ${
                filter === value ? "border-ink font-semibold text-ink" : "border-transparent font-medium text-muted hover:text-ink"
              }`}
            >
              {label}
              <span className="num text-[13px] font-medium text-muted">{counts[value]}</span>
            </button>
          ))}
          <label className="mb-2 ml-auto flex h-9 w-60 items-center gap-2 rounded-full bg-tile px-3.5">
            <Search className="h-4 w-4 shrink-0 text-muted" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search projects"
              aria-label="Search projects"
              className="min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-muted"
            />
          </label>
        </div>

        <div className="scroll-soft min-h-0 flex-1 overflow-y-auto pt-5">
          <div className="mb-5 flex items-end justify-between gap-4 px-1">
            <div>
              <h1 className="text-[28px] font-semibold tracking-[-0.02em] text-ink">Library</h1>
              <p className="font-read text-[15px] leading-normal text-ink-2">Start from a build that already flies or grips. Every project keeps its parts, checks and render.</p>
            </div>
            {live && hasBuild && (
              <button
                type="button"
                onClick={() => void save()}
                disabled={saving}
                className="flex h-10 shrink-0 items-center gap-2 rounded-full bg-tile px-4 text-[14px] font-semibold text-ink-2 transition hover:bg-track disabled:opacity-60"
              >
                <Save className="h-4 w-4" /> {saving ? "Saving …" : "Save current build"}
              </button>
            )}
          </div>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-4 pb-2">
            {items.map((item) => (
              <Card key={item.id} item={item} selected={selected?.id === item.id} onSelect={() => setPicked(item.id)} />
            ))}
            <button
              type="button"
              onClick={() => {
                resetUi();
                setView("werkbank");
                if (live) void useSource.getState().resetSession();
              }}
              className="flex min-h-[220px] flex-col items-center justify-center gap-2 rounded-[20px] border-[1.5px] border-dashed border-track text-center transition hover:bg-page-2"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-tile">
                <Plus className="h-4.5 w-4.5 text-ink-2" />
              </span>
              <span className="text-[15px] font-semibold text-ink-2">New project</span>
              <span className="text-[13px] text-muted">From a meeting, a sketch or a prompt</span>
            </button>
          </div>
          {items.length === 0 && <p className="px-1 py-4 text-[15px] text-muted">Nothing matches “{query}”.</p>}
        </div>
      </div>
      {selected ? <Inspect item={selected} live={live} onRebuild={() => rebuild(selected.id)} /> : <div />}
    </div>
  );
}
