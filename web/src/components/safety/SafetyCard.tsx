// Safety check in the chat: one line per finding, danger first; a tap opens the reason,
// the rule it rests on and the fix. Hints, not legal advice.
import { useState } from "react";
import { ChevronDown, ShieldAlert, ShieldCheck } from "lucide-react";
import type { SafetyEvent, SafetyFinding } from "../../events/types";

const TONE: Record<SafetyFinding["severity"], { dot: string; ink: string; label: string }> = {
  danger: { dot: "bg-fail", ink: "text-fail-ink", label: "Danger" },
  warning: { dot: "bg-agent", ink: "text-agent-ink", label: "Warning" },
  info: { dot: "bg-faint", ink: "text-ink-2", label: "Note" },
};

function FindingRow({ finding, open, onToggle }: { finding: SafetyFinding; open: boolean; onToggle: () => void }) {
  const tone = TONE[finding.severity];
  return (
    <li className="border-t border-line first:border-t-0">
      <button type="button" onClick={onToggle} className="flex w-full items-center gap-2 py-1.5 text-left" aria-expanded={open}>
        <span className={`h-2 w-2 shrink-0 rounded-full ${tone.dot}`} aria-hidden />
        <span className={`shrink-0 text-[12px] font-bold uppercase tracking-wide ${tone.ink}`}>{tone.label}</span>
        <span className="min-w-0 flex-1 truncate text-[14px] font-semibold text-ink">{finding.title}</span>
        <ChevronDown className={`h-4 w-4 shrink-0 text-muted transition ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="space-y-1 pb-2 pl-4 text-[13px] leading-snug">
          <p className="text-ink-2">{finding.reason}</p>
          <p className="text-ink">
            <span className="font-bold">Fix: </span>
            {finding.fix}
          </p>
          <p className="text-muted">
            {finding.source === "claude" ? "Agent · " : "Rule · "}
            {finding.rule}
          </p>
        </div>
      )}
    </li>
  );
}

export function SafetyCard({ safety }: { safety: SafetyEvent }) {
  const [open, setOpen] = useState<string | null>(safety.findings[0]?.id ?? null);
  const danger = safety.findings.some((f) => f.severity === "danger");
  const Icon = safety.findings.length ? ShieldAlert : ShieldCheck;
  return (
    <div className="rounded-[14px] bg-page-2 px-3 py-2.5" data-target="safety">
      <div className="flex items-center gap-2">
        <Icon className={`h-4.5 w-4.5 shrink-0 ${danger ? "text-fail" : "text-ink-2"}`} />
        <span className="text-[14px] font-bold text-ink">Safety check · {safety.label}</span>
        <span className="num ml-auto text-[13px] text-muted">{safety.findings.length} notes</span>
      </div>
      {safety.findings.length ? (
        <ul className="mt-1">
          {safety.findings.map((finding) => (
            <FindingRow
              key={finding.id}
              finding={finding}
              open={open === finding.id}
              onToggle={() => setOpen(open === finding.id ? null : finding.id)}
            />
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-[13px] text-muted">{safety.summary}</p>
      )}
      <p className="mt-1 text-[12px] text-faint">{safety.disclaimer}</p>
    </div>
  );
}
