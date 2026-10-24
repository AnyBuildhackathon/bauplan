// The order inside the bill of materials: one card per shop with its lines and a total,
// printed parts in their own group with the filament they take. Built from the bom event
// on the client, the same grouping GET /api/export/order answers, so it also works in ?demo.
import { ArrowUpRight, Printer, ShoppingCart } from "lucide-react";
import type { BomEvent, BomItem } from "../events/types";
import { fmtEur, fmtGram } from "../lib/format";

/** Printed parts come from the STL files in the ZIP, not from a shop. */
export const isPrinted = (i: BomItem) => i.shop === "printed" || !/^https?:\/\//.test(i.url);

export interface ShopGroup {
  shop: string;
  items: BomItem[];
  total: number;
  live: boolean;
}

/** Shops by total, most expensive first, and the printed parts apart. */
export function groupByShop(items: BomItem[]): { shops: ShopGroup[]; printed: BomItem[] } {
  const groups = new Map<string, ShopGroup>();
  const printed: BomItem[] = [];
  for (const item of items) {
    if (isPrinted(item)) {
      printed.push(item);
      continue;
    }
    const shop = item.shop || "Unknown shop";
    const group = groups.get(shop) ?? { shop, items: [], total: 0, live: false };
    group.items.push(item);
    group.total += item.qty * item.unit_price_eur;
    group.live ||= item.price_source === "live";
    groups.set(shop, group);
  }
  return { shops: [...groups.values()].sort((a, b) => b.total - a.total), printed };
}

const material = (name: string) => /printed (\w+)$/.exec(name)?.[1] ?? null;

function SourceChip({ live }: { live: boolean }) {
  return <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold ${live ? "bg-ok-soft text-ok-ink" : "bg-tile text-muted"}`}>{live ? "live" : "catalog"}</span>;
}

export function OrderView({ bom }: { bom: BomEvent }) {
  const { shops, printed } = groupByShop(bom.items);
  const filament = printed.reduce((s, i) => s + i.qty * i.weight_g, 0);
  const printCost = printed.reduce((s, i) => s + i.qty * i.unit_price_eur, 0);
  return (
    <section className="space-y-2" data-target="order_by_shop">
      <p className="num px-1 text-[14px] font-semibold text-muted">
        {shops.length} {shops.length === 1 ? "shop" : "shops"}
        {printed.length > 0 ? " and printed parts" : ""} · {fmtEur(bom.total_eur)}
        {bom.prices === "searching" ? " · Searching shops for live prices…" : ""}
      </p>
      {shops.map((g) => (
        <div key={g.shop} className="rounded-[22px] bg-page-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <ShoppingCart className="h-4.5 w-4.5 text-muted" />
            <span className="text-[17px] font-bold">{g.shop}</span>
            <SourceChip live={g.live} />
            <span className="num ml-auto text-[19px] font-extrabold">{fmtEur(g.total)}</span>
          </div>
          <ul className="mt-1.5 space-y-1">
            {g.items.map((i) => (
              <li key={i.name} className="num flex items-center gap-2 text-[14px] text-ink-2">
                <span className="w-9 shrink-0 text-muted">{i.qty} ×</span>
                <span className="min-w-0 flex-1 truncate">{i.name}</span>
                {i.url ? (
                  <a href={i.url} target="_blank" rel="noopener noreferrer" className="shrink-0 font-semibold text-link hover:underline">
                    Open shop <ArrowUpRight className="inline h-3.5 w-3.5" />
                  </a>
                ) : (
                  <span className="shrink-0 text-muted">estimate, no shop link</span>
                )}
                <span className="w-20 shrink-0 text-right font-semibold">{fmtEur(i.qty * i.unit_price_eur)}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {printed.length > 0 && (
        <div className="rounded-[22px] bg-page-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <Printer className="h-4.5 w-4.5 text-muted" />
            <span className="text-[17px] font-bold">Print yourself</span>
            <span className="num text-[14px] font-semibold text-muted">{fmtGram(filament)} filament</span>
            <span className="num ml-auto text-[19px] font-extrabold">{fmtEur(printCost)}</span>
          </div>
          <ul className="mt-1.5 space-y-1">
            {printed.map((i) => (
              <li key={i.name} className="num flex items-center gap-2 text-[14px] text-ink-2">
                <span className="w-9 shrink-0 text-muted">{i.qty} ×</span>
                <span className="min-w-0 flex-1 truncate">{i.name}</span>
                <span className="shrink-0 text-muted">{[material(i.name), fmtGram(i.qty * i.weight_g)].filter(Boolean).join(" · ")}</span>
                <span className="w-20 shrink-0 text-right font-semibold">{fmtEur(i.qty * i.unit_price_eur)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 text-[13px] text-faint">The STL files and print settings are in the ZIP.</p>
        </div>
      )}
    </section>
  );
}
