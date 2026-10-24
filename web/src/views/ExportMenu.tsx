// Export on the bill of materials: the list as CSV, one ZIP with every STL and STEP file plus
// the build guide (GET /api/export/project.zip), the order grouped by shop with a total each,
// and a share link that reopens the build from the library (?project=<id>).
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUpRight, ChevronDown, FileArchive, FileSpreadsheet, Link2, Printer, ShoppingCart } from "lucide-react";
import { useSource } from "../events/source";
import type { BomEvent, BomItem } from "../events/types";
import { apiUrl } from "../lib/api";
import { fmtEur } from "../lib/format";

const csvCell = (v: string | number) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));

/** Same columns as the bom.csv in the project ZIP. */
export function bomCsv(bom: BomEvent): string {
  const rows: (string | number)[][] = [["name", "qty", "unit_price_eur", "line_eur", "weight_g", "shop", "price_source", "url"]];
  for (const i of bom.items) {
    rows.push([i.name, i.qty, i.unit_price_eur.toFixed(2), (i.qty * i.unit_price_eur).toFixed(2), i.weight_g, i.shop, i.price_source ?? "catalog", i.url]);
  }
  rows.push(["Total", "", "", bom.total_eur.toFixed(2), "", "", "", ""]);
  return rows.map((r) => r.map(csvCell).join(",")).join("\n") + "\n";
}

function download(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Printed parts come from the STL files in the project ZIP, not from a shop. */
const isPrinted = (i: BomItem) => i.shop === "printed" || !/^https?:\/\//.test(i.url);

export interface ShopGroup {
  shop: string;
  items: BomItem[];
  total: number;
  printed: boolean;
}

/** Shops by total, most expensive first; printed parts last. */
export function groupByShop(items: BomItem[]): ShopGroup[] {
  const groups = new Map<string, ShopGroup>();
  for (const item of items) {
    const printed = isPrinted(item);
    const shop = printed ? "Print yourself" : item.shop || "Unknown shop";
    const group = groups.get(shop) ?? { shop, items: [], total: 0, printed };
    group.items.push(item);
    group.total += item.qty * item.unit_price_eur;
    groups.set(shop, group);
  }
  return [...groups.values()].sort((a, b) => Number(a.printed) - Number(b.printed) || b.total - a.total);
}

export function OrderView({ bom, onBack }: { bom: BomEvent; onBack: () => void }) {
  const groups = groupByShop(bom.items);
  const shops = groups.filter((g) => !g.printed).length;
  return (
    <section className="space-y-3" data-target="order_by_shop">
      <div className="flex items-center gap-3">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[14px] font-bold text-muted hover:bg-card">
          <ArrowLeft className="h-4 w-4" /> Parts
        </button>
        <h2 className="text-[18px] font-bold">Order by shop</h2>
        <span className="num ml-auto text-[14px] font-semibold text-muted">
          {shops} {shops === 1 ? "shop" : "shops"} · {fmtEur(bom.total_eur)}
        </span>
      </div>
      {groups.map((g) => (
        <div key={g.shop} className="rounded-[22px] bg-page-2 px-4 py-3">
          <div className="flex items-center gap-2">
            {g.printed ? <Printer className="h-4.5 w-4.5 text-muted" /> : <ShoppingCart className="h-4.5 w-4.5 text-muted" />}
            <span className="text-[17px] font-bold">{g.shop}</span>
            <span className="num ml-auto text-[19px] font-extrabold">{fmtEur(g.total)}</span>
          </div>
          <ul className="mt-1.5 space-y-1">
            {g.items.map((i) => (
              <li key={i.name} className="num flex items-center gap-2 text-[14px] text-ink-2">
                <span className="w-9 shrink-0 text-muted">{i.qty} ×</span>
                {g.printed ? (
                  <span className="min-w-0 flex-1 truncate">{i.name}</span>
                ) : (
                  <a href={i.url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate font-semibold text-link hover:underline">
                    {i.name} <ArrowUpRight className="inline h-3.5 w-3.5" />
                  </a>
                )}
                {i.price_source === "live" && <span className="shrink-0 rounded-full bg-ok-soft px-2 py-0.5 text-[11px] font-bold text-ok-ink">live</span>}
                <span className="shrink-0 font-semibold">{fmtEur(i.qty * i.unit_price_eur)}</span>
              </li>
            ))}
          </ul>
          {g.printed && <p className="mt-1.5 text-[13px] text-faint">The STL files are in the project ZIP.</p>}
        </div>
      ))}
    </section>
  );
}

export function ExportMenu({ bom, onOrder }: { bom: BomEvent; onOrder: () => void }) {
  const live = useSource((s) => s.mode === "live" && s.live === "open");
  const [open, setOpen] = useState(false);
  const [sharing, setSharing] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    // Capture: the drawer stops pointerdown from bubbling.
    window.addEventListener("pointerdown", away, true);
    return () => window.removeEventListener("pointerdown", away, true);
  }, [open]);

  const notice = (text: string) => useSource.setState({ notice: text });

  const share = async () => {
    setSharing(true);
    try {
      const res = await fetch(apiUrl("/api/export/share"), { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const body = (await res.json()) as { id?: string; saved?: boolean; detail?: string };
      if (!res.ok || !body.id) throw new Error(body.detail ?? `HTTP ${res.status}`);
      const link = `${window.location.origin}${window.location.pathname}?project=${encodeURIComponent(body.id)}`;
      const what = body.saved ? "Saved to the library" : "In the library as a reference build";
      try {
        await navigator.clipboard.writeText(link);
        notice(`${what}; link copied: ${link}`);
      } catch {
        notice(`${what}: ${link}`);
      }
    } catch (err) {
      notice(`Not shared (${err instanceof Error ? err.message : "error"}).`);
    } finally {
      setSharing(false);
    }
  };

  const item = "flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-left text-[15px] font-semibold text-ink hover:bg-page-2 disabled:cursor-not-allowed disabled:opacity-50";
  const pick = (run: () => void) => () => {
    setOpen(false);
    run();
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="inline-flex h-11 items-center gap-1.5 rounded-full bg-tile px-5 text-[15px] font-bold text-ink-2 hover:bg-track"
      >
        Export <ChevronDown className="h-4 w-4" />
      </button>
      {open && (
        <div role="menu" className="card absolute right-0 z-10 mt-2 w-[290px] p-1.5 shadow-[var(--shadow-float)]">
          <button type="button" role="menuitem" className={item} onClick={pick(() => download("bom.csv", bomCsv(bom), "text/csv;charset=utf-8"))}>
            <FileSpreadsheet className="h-4.5 w-4.5 text-muted" /> Bill of materials (CSV)
          </button>
          <a
            role="menuitem"
            href={live ? apiUrl("/api/export/project.zip") : undefined}
            aria-disabled={!live}
            title={live ? undefined : "Needs the live backend"}
            onClick={() => setOpen(false)}
            className={`${item} ${live ? "" : "pointer-events-none opacity-50"}`}
          >
            <FileArchive className="h-4.5 w-4.5 text-muted" /> Project ZIP: STL, STEP, guide
          </a>
          <button type="button" role="menuitem" className={item} onClick={pick(onOrder)}>
            <ShoppingCart className="h-4.5 w-4.5 text-muted" /> Order by shop
          </button>
          <button type="button" role="menuitem" className={item} disabled={!live || sharing} title={live ? undefined : "Needs the live backend"} onClick={pick(() => void share())}>
            <Link2 className="h-4.5 w-4.5 text-muted" /> Share: save and copy link
          </button>
        </div>
      )}
    </div>
  );
}
