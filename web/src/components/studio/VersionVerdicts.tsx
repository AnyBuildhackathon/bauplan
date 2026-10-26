// A version's verdict book (docs/events.md, version: verdicts): what independent judges such as Robo Use said
// about that exact design, next to AnyBuild's own test. The Versions tab, the side-by-side comparison and the
// chat's version card read it from here, so "v1 Robo Use 0, v2 Robo Use 1" reads the same everywhere.
import { Gavel } from "lucide-react";
import type { VersionEvent, VersionVerdict } from "../../events/types";

export type VerdictTone = "ok" | "fail" | "muted";

export const VERDICT_TEXT: Record<VerdictTone, string> = { ok: "text-ok-ink", fail: "text-fail-ink", muted: "text-muted" };

/** "Robo Use 0", "Robo Use 1", "Robo Use not counted", "Robo Use: can't take it". */
export function verdictWord(v: VersionVerdict): string {
  if (v.verdict === "invalid") return `${v.label} not counted`;
  if (v.verdict === "refused") return `${v.label}: can't take it`;
  return `${v.label} ${typeof v.reward === "number" ? v.reward.toFixed(0) : v.verdict}`;
}

export function verdictTone(v: VersionVerdict): VerdictTone {
  if (v.verdict === "invalid") return "muted";
  return v.verdict === "pass" ? "ok" : "fail";
}

/** Whether an independent judge failed this version: its badge turns red like a failed own test. */
export function failedVerdict(v: VersionEvent): boolean {
  return (v.verdicts ?? []).some((x) => x.verdict === "fail" || x.verdict === "refused");
}

/** How a verdict came to be, for its tooltip: a recorded one did not run now. */
export function verdictNote(v: VersionVerdict): string {
  const how = v.status === "recorded" ? "Recorded earlier on this same design; Robo Use did not run now." : "";
  return [v.summary, how].filter(Boolean).join(" ");
}

/** The own test and every verdict as one line of bold marks: "Own test passed  ⚖ Robo Use 0". */
export function VerdictMarks({ v, own = true, className = "" }: { v: VersionEvent; own?: boolean; className?: string }) {
  const verdicts = v.verdicts ?? [];
  return (
    <span className={`inline-flex flex-wrap items-center gap-x-2.5 gap-y-1 ${className}`}>
      {own && v.sim && (
        <span className={`text-[13px] font-bold ${v.sim === "fail" ? "text-fail-ink" : "text-ok-ink"}`} data-target={`version:${v.n}:own`}>
          {verdicts.length > 0 ? "Own test" : "Test"} {v.sim === "fail" ? "failed" : "passed"}
        </span>
      )}
      {verdicts.map((x) => (
        <span
          key={x.judge + x.harness}
          title={verdictNote(x)}
          data-target={`version:${v.n}:verdict`}
          className={`num inline-flex flex-wrap items-center gap-x-1 text-[13px] font-bold ${VERDICT_TEXT[verdictTone(x)]}`}
        >
          <Gavel className="h-3.5 w-3.5 shrink-0" strokeWidth={2.4} />
          <span className="whitespace-nowrap">{verdictWord(x)}</span>
          {x.status === "recorded" && <span className="font-semibold whitespace-nowrap text-muted">· recorded</span>}
        </span>
      ))}
    </span>
  );
}
