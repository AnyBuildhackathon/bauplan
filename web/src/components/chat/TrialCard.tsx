// Robo Use trial in the chat: the independent verdict on the built gripper, what happened in one sentence,
// the validity check, and a button to the video in the Simulation tab. One card per trial, updated in place
// while it runs.
import { CircleCheck, CircleX, Gavel, Play } from "lucide-react";
import { useSession } from "../../events/store";
import { fmtReward, HARNESS_LABEL, useTrialPane, verdictOf, type TrialEvent, type TrialTone, type TrialValidity } from "../../events/trial";
import { useUi } from "../../lib/ui";
import { useSimPane } from "../training/useBrowserTraining";

const STAGE: Record<string, string> = {
  export: "exporting the gripper to MuJoCo",
  task: "writing the task from the brief",
  check: "checking the reference solution and the no-op control",
  agent: "Claude Code is driving the gripper",
};

export const TONE_TEXT: Record<TrialTone, string> = { ok: "text-ok-ink", fail: "text-fail-ink", muted: "text-ink-2", agent: "text-agent-ink" };
const TONE_BG: Record<TrialTone, string> = { ok: "bg-ok-soft", fail: "bg-fail-soft", muted: "bg-tile", agent: "bg-agent-soft" };

/** "Reference 1.0 · No-op 0.0 · valid": the task counts only when the reference scores 1 and doing nothing 0. */
export function ValidityChip({ validity, className = "" }: { validity: TrialValidity | null; className?: string }) {
  if (!validity) return null;
  return (
    <span
      title={validity.report.join("\n")}
      data-target="trial:validity"
      className={`num inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full px-3 text-[12px] font-semibold whitespace-nowrap ${
        validity.valid ? "bg-ok-soft text-ok-ink" : "bg-fail-soft text-fail-ink"
      } ${className}`}
    >
      {validity.valid ? <CircleCheck className="h-3.5 w-3.5" strokeWidth={2.4} /> : <CircleX className="h-3.5 w-3.5" strokeWidth={2.4} />}
      Reference {fmtReward(validity.reference)} · No-op {fmtReward(validity.noop)} · {validity.valid ? "valid" : "not valid"}
    </span>
  );
}

/** The recorded stand-in in a few words: why nothing ran, and whether it is this design. */
export function recordedNote(t: TrialEvent): string | null {
  if (t.status !== "recorded" || !t.recorded) return null;
  return t.recorded.matches_build
    ? "Recorded earlier on this same design. Robo Use did not run now."
    : "Recorded earlier on AnyBuild's example gripper, not this build. Robo Use did not run now.";
}

/** Opens the trial in the Simulation tab's Robo Use pane. */
export function openTrial(id: string) {
  useUi.getState().setView("werkbank");
  useUi.getState().selectTab("simulation");
  useSimPane.getState().setPane("robouse");
  useTrialPane.getState().select(id, useSession.getState().trialOrder.at(-1) ?? null);
}

export function TrialCard({ trialId }: { trialId: string }) {
  const t = useSession((s) => s.trials[trialId]);
  if (!t) return null;
  const verdict = verdictOf(t);
  const running = t.status === "running";
  const note = recordedNote(t);
  return (
    <div className={`rounded-2xl p-3 ${TONE_BG[verdict.tone]}`} data-target="trial:card">
      <div className="flex items-center gap-2 text-[14px] font-bold text-ink-2">
        <Gavel className="h-4.5 w-4.5 shrink-0" />
        <span className="min-w-0 truncate">Robo Use · independent test</span>
        {t.status !== "failed" && (
          <span className="ml-auto shrink-0 rounded-full bg-white/80 px-2 py-0.5 text-[12px] font-semibold text-muted">
            {HARNESS_LABEL[t.harness] ?? t.harness}
          </span>
        )}
      </div>
      {running ? (
        <div className="mt-1.5 flex items-center gap-2">
          <span className="h-2.5 w-2.5 shrink-0 animate-pulse-soft rounded-full bg-agent" />
          <span className="text-[15px] font-semibold text-agent-ink">Running · {STAGE[t.stage ?? ""] ?? "starting"}</span>
        </div>
      ) : (
        <div className={`num mt-1 text-[24px] leading-tight font-bold ${TONE_TEXT[verdict.tone]}`}>
          {verdict.label}
          {t.status !== "failed" && typeof t.reward === "number" && <span className="text-[16px] font-semibold"> · reward {fmtReward(t.reward)}</span>}
        </div>
      )}
      <p className="mt-1 text-[14px] leading-snug text-ink-2">{running ? t.detail : t.summary ?? t.detail}</p>
      {note && <p className="mt-1 text-[12px] leading-snug text-muted">{note}</p>}
      {!running && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <ValidityChip validity={t.validity} />
          {t.video_url && (
            <button
              type="button"
              onClick={() => openTrial(t.id)}
              className="ml-auto inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-ink px-3.5 text-[13px] font-semibold text-white shadow-[var(--shadow-pill)] transition hover:bg-[#333]"
            >
              <Play className="h-3.5 w-3.5" fill="currentColor" /> Watch video
            </button>
          )}
        </div>
      )}
    </div>
  );
}
