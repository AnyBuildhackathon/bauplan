// The Versions tab of the right panel: every build newest first with what started it, its
// numbers and its test, selecting one shows it in the Model tab, an old one can be restored,
// and two can be compared side by side.
import { useState } from "react";
import { GitCommitVertical, GitCompare, RotateCcw } from "lucide-react";
import { useSession } from "../../events/store";
import { useSource } from "../../events/source";
import type { VersionEvent, VersionTrigger } from "../../events/types";
import { fmtEur, fmtMin, fmtNum } from "../../lib/format";
import { useUi } from "../../lib/ui";
import { PanelEmpty, PanelHeader } from "./RightRail";

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

function VersionRow({ v, newest, selected, building }: { v: VersionEvent; newest: boolean; selected: boolean; building: boolean }) {
  const selectVersion = useUi((s) => s.selectVersion);
  const selectTab = useUi((s) => s.selectTab);
  const restoreVersion = useSource((s) => s.restoreVersion);
  const [confirm, setConfirm] = useState(false);
  const tone = v.sim === "fail" ? "bg-fail" : "bg-ok";
  const time = v.at ? clock(v.at) : "";
  const numbers = keyNumbers(v);

  return (
    <li className={`rounded-[18px] bg-page-2 px-3.5 py-3 ${selected ? "ring-2 ring-ink ring-inset" : ""}`} data-target={`version:${v.n}`}>
      <button
        type="button"
        onClick={() => {
          selectVersion(newest ? null : v.n);
          selectTab("modell");
        }}
        aria-pressed={selected}
        className="flex w-full items-start gap-3 text-left"
      >
        <span className={`num mt-0.5 flex h-6 min-w-8 shrink-0 items-center justify-center rounded-full px-1.5 text-[13px] font-semibold text-white ${tone}`}>v{v.n}</span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="rounded-full bg-tile px-2.5 py-0.5 text-[12px] font-bold text-muted">{TRIGGER_LABEL[v.trigger ?? "chat"] ?? "Chat"}</span>
            {newest && <span className="rounded-full bg-ok-soft px-2.5 py-0.5 text-[12px] font-bold text-ok-ink">current</span>}
            {v.sim && <span className={`text-[13px] font-bold ${v.sim === "fail" ? "text-fail-ink" : "text-ok-ink"}`}>{v.sim === "fail" ? "Test failed" : "Test passed"}</span>}
            {time && <span className="num ml-auto text-[13px] font-semibold text-muted">{time}</span>}
          </span>
          <span className="mt-1 line-clamp-2 block text-[15px] leading-snug font-bold text-ink">{v.label || "Chat request"}</span>
          {numbers.length > 0 && <span className="num mt-0.5 block text-[14px] text-muted">{numbers.join(" · ")}</span>}
        </span>
      </button>
      {!newest && !confirm && (
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
          <p className="text-[14px] leading-snug text-ink">Make v{v.n} current? Mechanic rebuilds it as a new version.</p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={() => {
                void restoreVersion(v.n);
                setConfirm(false);
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

export function VersionsTab() {
  const selected = useUi((s) => s.selectedVersion);
  const compare = useUi((s) => s.compare);
  const setCompare = useUi((s) => s.setCompare);
  const versions = useSession((s) => s.versions);
  const building = useSession((s) => Object.values(s.steps).some((st) => st.status === "running"));
  const [picking, setPicking] = useState(false);
  const [pickA, setPickA] = useState<number | null>(null);
  const [pickB, setPickB] = useState<number | null>(null);

  const newest = versions.at(-1)?.n ?? null;
  const a = pickA ?? versions.at(-2)?.n ?? newest ?? 0;
  const b = pickB ?? newest ?? 0;
  const listed = versions.slice().reverse();

  return (
    <>
      <PanelHeader title="Versions" detail={versions.length === 1 ? "1 version" : `${versions.length} versions`}>
        {versions.length >= 2 &&
          (compare ? (
            <button
              type="button"
              onClick={() => setCompare(null)}
              className="inline-flex h-8 items-center gap-1.5 rounded-full bg-ink px-3 text-[13px] font-bold text-white hover:brightness-110"
            >
              <GitCompare className="h-4 w-4" /> Close compare
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setPicking(!picking)}
              aria-pressed={picking}
              className={`inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[13px] font-bold transition ${
                picking ? "bg-ink text-white" : "bg-card text-ink-2 shadow-[var(--shadow-pill)] hover:bg-page-2"
              }`}
            >
              <GitCompare className="h-4 w-4" /> Compare
            </button>
          ))}
      </PanelHeader>
      <div className="scroll-soft min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {picking && !compare && versions.length >= 2 && (
          <div className="flex flex-wrap items-center gap-3 rounded-[18px] bg-card px-3.5 py-3 shadow-[var(--shadow-pill)]">
            <VersionSelect label="A" value={a} versions={versions} onChange={setPickA} />
            <VersionSelect label="B" value={b} versions={versions} onChange={setPickB} />
            <button
              type="button"
              disabled={a === b}
              onClick={() => {
                setCompare([Math.min(a, b), Math.max(a, b)]);
                setPicking(false);
              }}
              className="ml-auto h-9 rounded-full bg-agent px-4 text-[14px] font-bold text-white hover:brightness-105 disabled:opacity-40"
            >
              Show side by side
            </button>
          </div>
        )}
        {listed.length === 0 ? (
          <PanelEmpty icon={GitCommitVertical} title="No versions yet">
            Version 1 comes out of the first build. Every change after it is a new version you can compare or restore.
          </PanelEmpty>
        ) : (
          <ul className="space-y-2">
            {listed.map((v) => (
              // With one version there is nothing to pick between, so no ring.
              <VersionRow key={v.n} v={v} newest={v.n === newest} selected={versions.length > 1 && v.n === (selected ?? newest)} building={building} />
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
