// Stückliste as a drawer over the Werkbank: every part with price, weight and shop
// link, a "Warum?" with the Jamie quote behind it, warnings from earlier meetings,
// and the order tasks per person that live in Jamie (ticking "bestellt" ticks them there).
import { useEffect, useState } from "react";
import { AlertTriangle, ArrowUpRight, Battery, Box, Cable, Camera, CircuitBoard, Cog, Download, Fan, Shield, Wrench, X } from "lucide-react";
import { useSession } from "../events/store";
import { useSource } from "../events/source";
import type { BomEvent, BomItem, PartEvent, TaskItem } from "../events/types";
import { JamieMark, QuoteBubble } from "../components/panels/Panels";
import { enText } from "../lib/copy";
import { FirmwareSection } from "./FirmwareSection";
import { meets } from "../lib/derived";
import { assetUrl } from "../lib/api";
import { fmtEur, fmtGram, fmtNum } from "../lib/format";
import { useTargets } from "../lib/hooks";
import { useUi } from "../lib/ui";
import { Segmented } from "../components/ui/primitives";
import { BuildGuideButton } from "./BuildGuide";
import { WhyButton } from "../components/learn/Explain";
import { ExportMenu } from "./ExportMenu";
import { OrderView } from "./OrderView";

function iconFor(name: string) {
  const n = name.toLowerCase();
  if (/canopy|holder|halter/.test(n)) return Shield;
  if (/bolt|screw|schraube/.test(n)) return Wrench;
  if (/camera|kamera|caddx/.test(n)) return Camera;
  if (/akku|batter|lipo|li-?ion|lava|funfly/.test(n)) return Battery;
  if (/motor|kv\b|\d{4,5}kv/.test(n)) return Cog;
  if (/propeller|prop|gemfan/.test(n)) return Fan;
  if (/flug|controller|esc|fc|aio/.test(n)) return CircuitBoard;
  if (/rahmen|frame/.test(n)) return Box;
  return Cable;
}

const AVAILABILITY = { in_stock: "in stock", out_of_stock: "out of stock", unknown: "" } as const;

/** "live" when the price came from a shop page found by web search, else the catalog sample. */
function PriceSource({ item, searching }: { item: BomItem; searching: boolean }) {
  if (item.shop === "printed") return null;
  const live = item.price_source === "live";
  const estimated = item.price_source === "estimated";
  const label = live ? "live" : estimated ? "estimated" : searching ? "searching" : "catalog";
  const title = live && item.checked_at ? `Checked ${new Date(item.checked_at).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : undefined;
  const tone = live ? "bg-ok-soft text-ok-ink" : estimated ? "bg-agent-soft text-agent-ink" : "bg-tile text-muted";
  return (
    <span title={title} className={`shrink-0 rounded-full px-2.5 py-1 text-[12px] font-bold ${tone}`}>
      {label}
    </span>
  );
}

/** Absolute URLs stay, backend paths go to the backend, a bare repo path is served under /files/. */
const href = (u: string) => (/^(https?:)?\/\//.test(u) || u.startsWith("/") ? assetUrl(u) ?? u : assetUrl(`/files/${u}`) ?? u);

function PartRow({ item, part, searching }: { item: BomItem; part: PartEvent | undefined; searching: boolean }) {
  const [why, setWhy] = useState(false);
  const Icon = iconFor(item.name);
  const warnings = part?.warnings ?? [];
  return (
    <li className="rounded-[22px] bg-page-2 px-4 py-3" data-target={`part:${part?.category ?? item.name}`}>
      <div className="flex items-center gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-card text-ink-2 shadow-[var(--shadow-pill)]">
          <Icon className="h-5.5 w-5.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[17px] font-bold">{item.name}</div>
          <div className="num text-[14px] text-muted">
            {item.qty > 1 ? `${item.qty} × ${fmtEur(item.unit_price_eur)}` : fmtEur(item.unit_price_eur)} · {fmtGram(item.qty * item.weight_g)} ·{" "}
            {item.url ? (
              <a href={href(item.url)} target="_blank" rel="noopener noreferrer" className="font-semibold text-link hover:underline">
                {item.shop} <ArrowUpRight className="inline h-3.5 w-3.5" />
              </a>
            ) : (
              item.shop
            )}
            {item.price_source === "live" && item.currency && item.currency !== "EUR" && item.price ? ` · ${fmtNum(item.price, 2)} ${item.currency}` : ""}
            {item.price_source === "live" && item.availability && AVAILABILITY[item.availability] ? ` · ${AVAILABILITY[item.availability]}` : ""}
          </div>
        </div>
        <PriceSource item={item} searching={searching} />
        <span className="num shrink-0 text-[19px] font-extrabold">{fmtEur(item.qty * item.unit_price_eur)}</span>
        {part && (part.why || part.reason) && (
          <button
            type="button"
            onClick={() => setWhy(!why)}
            className={`h-9 shrink-0 rounded-full px-3.5 text-[14px] font-bold transition ${why ? "bg-jamie text-white" : "bg-lavender text-jamie hover:brightness-95"}`}
          >
            Why?
          </button>
        )}
      </div>
      {why && part && (
        <div className="mt-2.5 space-y-2 pl-14">
          {part.reason && <p className="text-[15px] leading-snug text-ink-2">{part.reason}</p>}
          {part.why && <QuoteBubble quote={part.why} />}
          <WhyButton kind="part" id={part.category} label="Explain the physics" />
        </div>
      )}
      {warnings.map((w, i) => (
        <div key={i} className="mt-2.5 ml-14 flex gap-2.5 rounded-2xl bg-agent-soft px-3.5 py-2.5">
          <AlertTriangle className="mt-0.5 h-4.5 w-4.5 shrink-0 text-agent-ink" />
          <div>
            <p className="text-[15px] leading-snug text-ink">“{w.text}”</p>
            <p className="mt-0.5 text-[13px] font-semibold text-agent-ink">
              {[w.speaker, w.time, w.meeting_title].filter(Boolean).join(" · ")}
              {w.note ? ` · ${w.note}` : ""}
            </p>
          </div>
        </div>
      ))}
    </li>
  );
}

function TaskRow({ task }: { task: TaskItem }) {
  const toggleTask = useSource((s) => s.toggleTask);
  return (
    <li>
      <label className="flex cursor-pointer items-center gap-3 rounded-2xl px-2 py-2 hover:bg-page-2">
        <input
          type="checkbox"
          checked={task.done}
          onChange={(e) => void toggleTask(task.id, e.target.checked)}
          className="h-6 w-6 shrink-0 cursor-pointer accent-[#0b9677]"
          aria-label={`${enText(task.title)} ordered`}
        />
        <span className="min-w-0 flex-1">
          <span className={`block truncate text-[16px] font-semibold ${task.done ? "text-muted line-through" : "text-ink"}`}>{enText(task.title)}</span>
          <span className="num block text-[13px] font-semibold text-muted">
            {task.assignee} · by {task.due}
          </span>
        </span>
        <span className={`shrink-0 rounded-full px-2.5 py-1 text-[12px] font-bold ${task.done ? "bg-ok-soft text-ok-ink" : "bg-tile text-muted"}`}>
          {task.done ? "ordered" : "open"}
        </span>
      </label>
    </li>
  );
}

function priceNote(prices: BomEvent["prices"], live: number, total: number): string {
  if (prices === "searching") return "Searching shops for live prices…";
  if (live > 0) return `Live prices from the web for ${live} of ${total} lines, catalog samples for the rest. Check before ordering.`;
  return "Catalog prices are samples to verify, estimated prices are marked; this is not a live checkout.";
}

export function BomDrawer() {
  const open = useUi((s) => s.bomOpen);
  const setOpen = useUi((s) => s.setBomOpen);
  const bom = useSession((s) => s.bom);
  const parts = useSession((s) => s.parts);
  const tasks = useSession((s) => s.tasks);
  const cadStl = useSession((s) => s.cad?.stl_url ?? null);
  const product = useSession((s) => s.product);
  const targets = useTargets();
  const [ordering, setOrdering] = useState(false);

  useEffect(() => {
    if (!open) setOrdering(false);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open, setOpen]);

  if (!open || !bom) return null;
  const weight = bom.items.reduce((s, i) => s + i.qty * i.weight_g, 0);
  const priceOk = meets(targets.price_eur, bom.total_eur);
  const byName = new Map(Object.values(parts).map((p) => [p.name, p]));
  const drone = product === "drone";
  const stlHref = cadStl ? assetUrl(cadStl) ?? cadStl : href(bom.stl_path);
  const ordered = tasks?.items.filter((t) => t.done).length ?? 0;
  const liveCount = bom.items.filter((i) => i.price_source === "live").length;

  return (
    <div className="fixed inset-0 z-[70] flex justify-end bg-ink/25 backdrop-blur-[2px]" onPointerDown={() => setOpen(false)}>
      <div
        className="flex h-full w-[min(760px,100vw)] animate-rise flex-col bg-page shadow-[var(--shadow-float)]"
        onPointerDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Bill of materials"
      >
        <div className="flex shrink-0 items-center gap-4 px-6 pt-5 pb-4">
          <div>
            <h1 className="text-[30px] leading-none font-extrabold tracking-[-0.03em]">Bill of materials</h1>
            <p className="num mt-1.5 text-[16px] font-semibold text-muted">
              <span className={priceOk ? "text-ok-ink" : "text-fail-ink"}>{fmtEur(bom.total_eur)}</span> of max {fmtEur(targets.price_eur.value)} ·{" "}
              {fmtGram(weight)}
            </p>
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-4 whitespace-nowrap">
            <a
              href={stlHref}
              download={drone ? "frame.stl" : `${product}.stl`}
              className="inline-flex h-11 items-center gap-2 rounded-full bg-agent px-5 text-[15px] font-bold text-white shadow-[0_8px_20px_-8px_rgb(255_138_61/0.7)] hover:brightness-105"
            >
              <Download className="h-4.5 w-4.5" /> {drone ? "Frame STL" : "Model STL"}
            </a>
            <BuildGuideButton />
            <ExportMenu bom={bom} onOrder={() => setOrdering(true)} />
          </div>
          <button type="button" onClick={() => setOpen(false)} data-control="panel:bom:close" className="rounded-full p-2.5 text-muted hover:bg-card" aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="scroll-soft min-h-0 flex-1 space-y-5 overflow-y-auto px-6 pb-6">
          <Segmented
            size="sm"
            value={ordering ? "order" : "parts"}
            onChange={(v) => setOrdering(v === "order")}
            options={[
              { value: "parts", label: "Parts" },
              { value: "order", label: "Order by shop", target: "order_tab" },
            ]}
          />
          {ordering && <OrderView bom={bom} />}
          <ul className={ordering ? "hidden" : "space-y-2"}>
            {bom.items.map((item) => (
              <PartRow
                key={item.name}
                item={item}
                part={(item.category ? parts[item.category] : undefined) ?? byName.get(item.name)}
                searching={bom.prices === "searching"}
              />
            ))}
          </ul>
          <p className="text-[13px] text-faint">{priceNote(bom.prices, liveCount, bom.items.length)}</p>
          <FirmwareSection />
          {tasks && tasks.items.length > 0 && (
            <section className="card px-4 pt-4 pb-3" data-target="tasks bestellen">
              <div className="mb-1 flex items-center gap-2 px-2">
                <h2 className="text-[18px] font-bold">Order</h2>
                <JamieMark />
                <span className="num ml-auto text-[14px] font-semibold text-muted">
                  {ordered} / {tasks.items.length} · {tasks.live ? "in Jamie" : "local outbox"}
                </span>
              </div>
              <ul>
                {tasks.items.map((t) => (
                  <TaskRow key={t.id} task={t} />
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
