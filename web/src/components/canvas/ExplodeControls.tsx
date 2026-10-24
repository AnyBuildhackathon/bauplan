// The explode slider in the corner of the Model tab, and the card a hovered or clicked part
// shows: its name, the part that was picked for it, mass, price and the shop link.
import { ArrowUpRight, Expand, X } from "lucide-react";
import { useEffect } from "react";
import { useSession } from "../../events/store";
import type { BomItem } from "../../events/types";
import { fmtEur, fmtGram } from "../../lib/format";
import { normaliseName } from "../../lib/targets";
import { useUi } from "../../lib/ui";
import { useExplodeHover } from "./explode";

export function ExplodeSlider() {
  const explode = useUi((s) => s.explode);
  const setExplode = useUi((s) => s.setExplode);
  const pct = Math.round(explode * 100);
  return (
    <label
      className="absolute bottom-3 left-3 z-10 flex h-10 items-center gap-2.5 rounded-full bg-white/90 pr-4 pl-3.5 shadow-[var(--shadow-pill)] backdrop-blur"
      title="Pull every part apart"
      data-control="explode"
    >
      <Expand className="h-4 w-4 shrink-0 text-ink-2" />
      <span className="text-[14px] font-semibold text-ink-2">Explode</span>
      <input
        type="range"
        min={0}
        max={100}
        step={1}
        value={pct}
        onChange={(e) => setExplode(Number(e.target.value) / 100)}
        className="bevel-range w-[120px]"
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
}

function usePartFacts(key: string | null, label: string): Facts | null {
  const product = useSession((s) => s.product);
  const parts = useSession((s) => s.parts);
  const bom = useSession((s) => s.bom);
  const bodies = useSession((s) => s.cad?.bodies);
  if (!key) return null;
  const facts: Facts = { title: label, picked: null, mass: null, price: null, qty: 1, url: null, shop: null };
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

export function PartCard() {
  const { key, label, x, y, pinned, pin } = useExplodeHover();
  const facts = usePartFacts(key, label);
  const tab = useUi((s) => s.tab);
  useEffect(() => {
    if (tab !== "modell") pin(null);
  }, [tab, pin]);
  if (!facts || tab !== "modell") return null;
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
      {facts.url && (
        <a href={facts.url} target="_blank" rel="noreferrer" className="mt-2.5 inline-flex h-8 items-center gap-1 rounded-full bg-ink px-3 text-[13px] font-bold text-white hover:bg-[#333]">
          {facts.shop || "Shop"} <ArrowUpRight className="h-3.5 w-3.5" />
        </a>
      )}
      {!pinned && facts.url && <p className="mt-1.5 text-[12px] font-medium text-faint">Click the part to open the link</p>}
    </div>
  );
}
