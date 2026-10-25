// Version history as a drawer over the Werkbank: every build newest first with what
// started it, its numbers, restore of an old version, and a pair picker for the side by side view.
import { useEffect, useState } from "react";
import { GitCompare, RotateCcw, X } from "lucide-react";
import { useSession } from "../events/store";
import { useSource } from "../events/source";
import type { VersionEvent, VersionTrigger } from "../events/types";
import { fmtEur, fmtMin, fmtNum } from "../lib/format";
import { useUi } from "../lib/ui";

const TRIGGER_LABEL: Record<VersionTrigger, string> = {
  chat: "Chat",
  library: "Library",
  check_failed: "Failed check",
  restore: "Restore",
};

const clock = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
};

/** The three numbers a row shows: the drone's own, or the first cards of another product. */
function keyNumbers(v: VersionEvent): string[] {
  if (v.cards && v.cards.length > 0) return v.cards.slice(0, 3).map((c) => `${c.label} ${fmtNum(c.value, c.digits)} ${c.unit}`.trim());
  const out: string[] = [];
  if (typeof v.weight_g === "number") out.push(`${fmtNum(v.weight_g, 1)} g`);
  if (typeof v.flight_time_min === "number") out.push(`${fmtMin(v.flight_time_min)} min`);
  if (typeof v.price_eur === "number") out.push(fmtEur(v.price_eur));
  return out;
}

function VersionRow({ v, newest, selected, canRestore, building }: { v: VersionEvent; newest: boolean; selected: boolean; canRestore: boolean; building: boolean }) {
  const selectVersion = useUi((s) => s.selectVersion);
  const setOpen = useUi((s) => s.setVersionsOpen);
  const restoreVersion = useSource((s) => s.restoreVersion);
  const [confirm, setConfirm] = useState(false);
  const tone = v.sim === "fail" ? "bg-fail" : "bg-ok";
  const time = v.at ? clock(v.at) : "";
  const numbers = keyNumbers(v);

  return (
    <li className={`rounded-[22px] bg-page-2 px-4 py-3 ${selected ? "ring-2 ring-ink ring-inset" : ""}`} data-target={`version:${v.n}`}>
      <button type="button" onClick={() => selectVersion(newest ? null : v.n)} className="flex w-full items-start gap-3 text-left">
        <span className={`num mt-0.5 flex h-6 min-w-8 shrink-0 items-center justify-center rounded-full px-1.5 text-[13px] font-semibold text-white ${tone}`}>v{v.n}</span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="rounded-full bg-tile px-2.5 py-0.5 text-[12px] font-bold text-muted">{TRIGGER_LABEL[v.trigger ?? "chat"] ?? "Chat"}</span>
            {newest && <span className="rounded-full bg-ok-soft px-2.5 py-0.5 text-[12px] font-bold text-ok-ink">current</span>}
            {v.sim && (
              <span className={`text-[13px] font-bold ${v.sim === "fail" ? "text-fail-ink" : "text-ok-ink"}`}>{v.sim === "fail" ? "Test failed" : "Test passed"}</span>
            )}
            {time && <span className="num ml-auto text-[13px] font-semibold text-muted">{time}</span>}
          </span>
          <span className="mt-1 block text-[16px] leading-snug font-bold text-ink">{v.label || "Chat request"}</span>
          {numbers.length > 0 && <span className="num mt-0.5 block text-[14px] text-muted">{numbers.join(" · ")}</span>}
        </span>
      </button>
      {canRestore && !newest && !confirm && (
        <div className="mt-2 pl-11">
          <button
            type="button"
            disabled={building}
            onClick={() => setConfirm(true)}
            className="inline-flex h-8 items-center gap-1.5 rounded-full bg-card px-3 text-[13px] font-bold text-ink-2 shadow-[var(--shadow-pill)] transition hover:bg-page-2 disabled:opacity-40"
          >
            <RotateCcw className="h-3.5 w-3.5" /> Restore v{v.n}
          </button>
        </div>
      )}
      {confirm && (
        <div className="mt-2.5 ml-11 rounded-2xl bg-agent-soft px-3.5 py-2.5">
          <p className="text-[15px] leading-snug text-ink">Make v{v.n} current? Mechanic rebuilds it as a new version.</p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => {
                void restoreVersion(v.n);
                setConfirm(false);
                setOpen(false);
              }}
              className="h-8 rounded-full bg-ink px-3.5 text-[13px] font-bold text-white hover:brightness-110"
            >
              Restore
            </button>
            <button type="button" onClick={() => setConfirm(false)} className="h-8 rounded-full bg-card px-3.5 text-[13px] font-bold text-ink-2 shadow-[var(--shadow-pill)] hover:bg-page-2">
              Cancel
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

function VersionSelect({ label, value, versions, onChange }: { label: string; value: number; versions: VersionEvent[]; onChange: (n: number) => void }) {
  return (
    <label className="flex items-center gap-2 text-[14px] font-semibold text-muted">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="num h-9 rounded-full bg-card px-3 text-[14px] font-bold text-ink shadow-[var(--shadow-pill)]"
      >
        {versions.map((v) => (
          <option key={v.n} value={v.n}>
            v{v.n}
          </option>
        ))}
      </select>
    </label>
  );
}

export function VersionDrawer() {
  const open = useUi((s) => s.versionsOpen);
  const setOpen = useUi((s) => s.setVersionsOpen);
  const selected = useUi((s) => s.selectedVersion);
  const compare = useUi((s) => s.compare);
  const setCompare = useUi((s) => s.setCompare);
  const versions = useSession((s) => s.versions);
  const building = useSession((s) => Object.values(s.steps).some((st) => st.status === "running"));
  const [picking, setPicking] = useState(false);
  const [pickA, setPickA] = useState<number | null>(null);
  const [pickB, setPickB] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open, setOpen]);

  if (!open) return null;
  const newest = versions.at(-1)?.n ?? null;
  const a = pickA ?? versions.at(-2)?.n ?? newest ?? 0;
  const b = pickB ?? newest ?? 0;
  const listed = versions.slice().reverse();

  return (
    <div className="fixed inset-0 z-[70] flex justify-end bg-ink/25 backdrop-blur-[2px]" onPointerDown={() => setOpen(false)}>
      <div
        className="flex h-full w-[min(560px,100vw)] animate-rise flex-col bg-page shadow-[var(--shadow-float)]"
        onPointerDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Version history"
      >
        <div className="flex shrink-0 items-center gap-4 px-6 pt-5 pb-4">
          <div>
            <h1 className="text-[30px] leading-none font-extrabold tracking-[-0.03em]">Version history</h1>
            <p className="num mt-1.5 text-[16px] font-semibold text-muted">{versions.length === 1 ? "1 version" : `${versions.length} versions`}</p>
          </div>
          {versions.length >= 2 &&
            (compare ? (
              <button
                type="button"
                onClick={() => setCompare(null)}
                className="ml-auto inline-flex h-10 items-center gap-2 rounded-full bg-ink px-4 text-[14px] font-bold text-white hover:brightness-110"
              >
                <GitCompare className="h-4.5 w-4.5" /> Close compare
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setPicking(!picking)}
                className={`ml-auto inline-flex h-10 items-center gap-2 rounded-full px-4 text-[14px] font-bold transition ${
                  picking ? "bg-ink text-white" : "bg-card text-ink-2 shadow-[var(--shadow-pill)] hover:bg-page-2"
                }`}
              >
                <GitCompare className="h-4.5 w-4.5" /> Compare
              </button>
            ))}
          <button type="button" onClick={() => setOpen(false)} className={`rounded-full p-2.5 text-muted hover:bg-card ${versions.length >= 2 ? "" : "ml-auto"}`} aria-label="Close">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="scroll-soft min-h-0 flex-1 space-y-4 overflow-y-auto px-6 pb-6">
          {picking && !compare && versions.length >= 2 && (
            <div className="flex flex-wrap items-center gap-3 rounded-[22px] bg-card px-4 py-3 shadow-[var(--shadow-pill)]">
              <VersionSelect label="A" value={a} versions={versions} onChange={setPickA} />
              <VersionSelect label="B" value={b} versions={versions} onChange={setPickB} />
              <button
                type="button"
                disabled={a === b}
                onClick={() => {
                  setCompare([Math.min(a, b), Math.max(a, b)]);
                  setPicking(false);
                  setOpen(false);
                }}
                className="ml-auto h-9 rounded-full bg-agent px-4 text-[14px] font-bold text-white hover:brightness-105 disabled:opacity-40"
              >
                Show side by side
              </button>
            </div>
          )}
          {listed.length === 0 ? (
            <p className="rounded-[22px] bg-page-2 px-4 py-6 text-center text-[15px] text-muted">No versions yet. v1 comes out of the first build.</p>
          ) : (
            <ul className="space-y-2">
              {listed.map((v) => (
                <VersionRow key={v.n} v={v} newest={v.n === newest} selected={v.n === (selected ?? newest)} canRestore building={building} />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
