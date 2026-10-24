// Export on the bill of materials: the list as CSV, one ZIP with every STL and STEP file, the
// build guide, firmware and README (GET /api/export/bundle.zip), the order by shop, and a share
// link that reopens the build from the library (?project=<id>). Without a backend (?demo) the
// CSV is built here from the bom event and ZIP and Share are hidden.
import { useEffect, useRef, useState } from "react";
import { ChevronDown, FileArchive, FileSpreadsheet, Link2, ShoppingCart } from "lucide-react";
import { useSession } from "../events/store";
import { useSource } from "../events/source";
import type { BomEvent } from "../events/types";
import { apiFetch, apiStreamUrl } from "../lib/api";

const csvCell = (v: string | number) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));

/** Same columns as GET /api/export/bom.csv, with the byte order mark Excel needs for UTF-8. */
export function bomCsv(bom: BomEvent): string {
  const rows: (string | number)[][] = [["name", "qty", "unit_price_eur", "line_total_eur", "weight_g", "shop", "url", "price_source", "availability", "checked_at"]];
  for (const i of bom.items) {
    rows.push([
      i.name,
      i.qty,
      i.unit_price_eur.toFixed(2),
      (i.qty * i.unit_price_eur).toFixed(2),
      i.weight_g,
      i.shop,
      i.url,
      i.price_source ?? "catalog",
      i.availability ?? "",
      i.checked_at ?? "",
    ]);
  }
  rows.push(["Total", "", "", bom.total_eur.toFixed(2), "", "", "", "", "", ""]);
  return "﻿" + rows.map((r) => r.map(csvCell).join(",")).join("\n") + "\n";
}

function downloadText(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The drone and the gripper are built by their own code; their link reopens that code reference. */
const CODE_REFERENCE: Record<string, string> = { drone: "micro-drone", gripper: "robot-gripper" };

export function ExportMenu({ bom, onOrder }: { bom: BomEvent; onOrder: () => void }) {
  const live = useSource((s) => s.mode === "live" && s.live === "open");
  const product = useSession((s) => s.product);
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
      let id = CODE_REFERENCE[product];
      if (!id) {
        const res = await apiFetch("/api/library", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        const body = (await res.json()) as { item?: { id: string }; detail?: string };
        if (!res.ok || !body.item) throw new Error(body.detail ?? `HTTP ${res.status}`);
        id = body.item.id;
      }
      const link = `${window.location.origin}${window.location.pathname}?project=${encodeURIComponent(id)}`;
      // Without focus or permission the clipboard can hang or refuse; then the notice shows the link to copy by hand.
      const copied = await Promise.race([
        navigator.clipboard.writeText(link).then(() => true),
        new Promise<boolean>((resolve) => setTimeout(() => resolve(false), 1500)),
      ]).catch(() => false);
      notice(copied ? `Link copied: ${link}` : `Share link: ${link}`);
    } catch (err) {
      notice(`Not shared (${err instanceof Error ? err.message : "error"}).`);
    } finally {
      setSharing(false);
    }
  };

  const item = "flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-left text-[15px] font-semibold text-ink hover:bg-page-2 disabled:opacity-50";
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
        <div role="menu" className="card absolute right-0 z-10 mt-2 w-[270px] p-1.5 shadow-[var(--shadow-float)]">
          {live ? (
            <a role="menuitem" href={apiStreamUrl("/api/export/bom.csv")} download onClick={() => setOpen(false)} className={item}>
              <FileSpreadsheet className="h-4.5 w-4.5 text-muted" /> Download BOM (CSV)
            </a>
          ) : (
            <button type="button" role="menuitem" className={item} onClick={pick(() => downloadText(`anybuild-${product}-bom.csv`, bomCsv(bom), "text/csv;charset=utf-8"))}>
              <FileSpreadsheet className="h-4.5 w-4.5 text-muted" /> Download BOM (CSV)
            </button>
          )}
          {live && (
            <a role="menuitem" href={apiStreamUrl("/api/export/bundle.zip")} download onClick={() => setOpen(false)} className={item}>
              <FileArchive className="h-4.5 w-4.5 text-muted" /> Download all files (ZIP)
            </a>
          )}
          <button type="button" role="menuitem" className={item} onClick={pick(onOrder)}>
            <ShoppingCart className="h-4.5 w-4.5 text-muted" /> Order by shop
          </button>
          {live && (
            <button type="button" role="menuitem" className={item} disabled={sharing} onClick={pick(() => void share())}>
              <Link2 className="h-4.5 w-4.5 text-muted" /> Share link
            </button>
          )}
        </div>
      )}
    </div>
  );
}
