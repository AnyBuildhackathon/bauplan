// The explode slider (in the popover of the view bar's Explode button), and the card a hovered
// or clicked part shows: its name, the part that was picked for it, mass, price, the shop link
// and which 3D model it shows.
import { ArrowUpRight, X } from "lucide-react";
import { useEffect } from "react";
import { useSession } from "../../events/store";
import type { BomItem, PartModelRow } from "../../events/types";
import { fmtEur, fmtGram } from "../../lib/format";
import { normaliseName } from "../../lib/targets";
import { useUi } from "../../lib/ui";
import { useExplodeHover } from "./explode";

export function ExplodeSlider() {
  const explode = useUi((s) => s.explode);
  const setExplode = useUi((s) => s.setExplode);
  const pct = Math.round(explode * 100);
  return (
    <label className="flex h-10 items-center gap-3">
      <span className="text-[13px] font-semibold text-muted">Assembled</span>
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        value={pct}
        onChange={(e) => setExplode(Number(e.target.value) / 100)}
        className="bevel-range w-[160px]"
        style={{ "--p": `${pct}%` } as React.CSSProperties}
        aria-label="Explode"
      />
      <span className="num w-9 text-right text-[14px] font-bold text-ink">{pct}%</span>
    </label>
  );
}

const DRONE_CATEGORY: [RegExp, string][] = [
  [/^motor_/, "motor"],
  [/^propeller_/, "propeller"],
  [/^battery/, "battery"],
  [/^flight_controller$/, "flight_controller"],
  [/^frame$/, "frame"],
  [/^canopy$/, "canopy"],
  [/^camera$/, "camera"],
];

interface Facts {
  title: string;
  picked: string | null;
  mass: number | null;
  price: number | null;
  qty: number;
  url: string | null;
  shop: string | null;
  model: PartModelRow | null;
}

/** How the card names a part's 3D model; an approximate one says what no source gave. */
export function modelLine(row: PartModelRow): string {
  if (row.model_kind === "official") return "Official 3D model";
  if (row.model_kind === "look-alike") return "3D look-alike from measured drawings";
  const missing = row.model_missing.map((name) => name.replace(/_mm$/, "").replace(/_/g, " "));
  return "Approximate 3D model" + (missing.length ? ": no source for " + missing.join(", ") : "");
}

function usePartFacts(key: string | null, label: string): Facts | null {
  const product = useSession((s) => s.product);
  const parts = useSession((s) => s.parts);
  const bom = useSession((s) => s.bom);
  const bodies = useSession((s) => s.cad?.bodies);
  const models = useSession((s) => s.cad?.part_models);
  if (!key) return null;
  const model = models?.find((row) => normaliseName(row.node) === normaliseName(key)) ?? null;
  const facts: Facts = { title: label, picked: null, mass: null, price: null, qty: 1, url: null, shop: null, model };
  let item: BomItem | undefined;
  if (product === "drone") {
    const category = DRONE_CATEGORY.find(([re]) => re.test(key))?.[1];
    const part = category ? parts[category] : undefined;
    item = part ? bom?.items.find((i) => i.name === part.name) : undefined;
    facts.picked = part?.name ?? item?.name ?? null;
    facts.mass = part?.mass_g ?? (item && item.weight_g / Math.max(1, item.qty)) ?? null;
    if (category === "frame" && item) facts.mass = item.weight_g;
  } else {
    const body = bodies?.find((b) => normaliseName(b.name) === normaliseName(key));
    item = body ? bom?.items.find((i) => i.category === body.part_id) : undefined;
    facts.picked = item && item.shop !== "printed" ? item.name : body?.kind === "printed" ? item?.name.split(", ").slice(1).join(", ") || "printed" : null;
    facts.mass = body ? body.mass_g || item?.weight_g || null : null;
  }
  if (item) {
    facts.price = item.unit_price_eur;
    facts.qty = item.qty;
    facts.shop = item.shop === "printed" ? null : item.shop || null;
    facts.url = item.shop !== "printed" && /^https?:\/\//.test(item.url) ? item.url : null;
  }
  return facts;
}

/** In the bottom-left corner of the Model tab, below Mechanic's line: which parts the 3D view shows as approximate models, if any. */
export function ApproximateModelsNote() {
  const models = useSession((s) => s.cad?.part_models);
  const names = [...new Set((models ?? []).filter((row) => row.model_kind === "approximate").map((row) => row.part_name))];
  if (!names.length) return null;
  return (
    <p
      className="absolute bottom-3 left-3 z-10 max-w-[60%] truncate rounded-full bg-white/90 px-3.5 py-1.5 text-[13px] font-semibold text-agent-ink shadow-[var(--shadow-pill)] backdrop-blur"
      title={names.join(", ")}
    >
      Approximate 3D model: {names.join(", ")}
    </p>
  );
}

export function PartCard() {
  const { key, label, x, y, pinned, pin } = useExplodeHover();
  const facts = usePartFacts(key, label);
  // The studio tabs show the live model; a tab change closes the card, its part is elsewhere now.
  const tab = useUi((s) => s.tab);
  useEffect(() => pin(null), [tab, pin]);
  if (!facts || (tab !== "modell" && tab !== "cad")) return null;
  const left = Math.min(x + 18, window.innerWidth - 300);
  const top = Math.min(y + 18, window.innerHeight - 190);
  return (
    <div
      className={`fixed z-[65] w-[280px] animate-rise rounded-[18px] bg-white px-4 py-3 shadow-[var(--shadow-float)] ${pinned ? "" : "pointer-events-none"}`}
      style={{ left, top }}
      role="tooltip"
    >
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 text-[17px] leading-tight font-bold text-ink">{facts.title}</p>
        {pinned && (
          <button type="button" onClick={() => pin(null)} className="-mt-1 -mr-2 rounded-full p-1.5 text-muted hover:bg-tile" aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      {facts.picked && <p className="mt-0.5 truncate text-[14px] font-medium text-ink-2">{facts.picked}</p>}
      <dl className="num mt-2 flex gap-5 text-[14px]">
        <div>
          <dt className="font-medium text-muted">Mass</dt>
          <dd className="font-bold text-ink">{facts.mass ? fmtGram(facts.mass) : "–"}</dd>
        </div>
        <div>
          <dt className="font-medium text-muted">Price</dt>
          <dd className="font-bold text-ink">
            {facts.price !== null ? fmtEur(facts.price) : "–"}
            {facts.qty > 1 && <span className="font-medium text-muted"> ×{facts.qty}</span>}
          </dd>
        </div>
      </dl>
      {facts.model && (
        <p className={`mt-2 text-[13px] leading-snug font-semibold ${facts.model.model_kind === "approximate" ? "text-agent-ink" : "text-muted"}`}>
          {modelLine(facts.model)}
        </p>
      )}
      {facts.url && (
        <a href={facts.url} target="_blank" rel="noreferrer" className="mt-2.5 inline-flex h-8 items-center gap-1 rounded-full bg-ink px-3 text-[13px] font-bold text-white hover:bg-[#333]">
          {facts.shop || "Shop"} <ArrowUpRight className="h-3.5 w-3.5" />
        </a>
      )}
      {!pinned && facts.url && <p className="mt-1.5 text-[12px] font-medium text-faint">Click the part to open the link</p>}
    </div>
  );
}
