import { Loader2, Pause, Play, Square } from "lucide-react";
import { useSession } from "../../events/store";
import { useSource } from "../../events/source";
import type { RunStatus } from "../../events/types";

const LABEL: Record<Exclude<RunStatus, "idle">, string> = {
  running: "Mechanic is working",
  pausing: "Pausing after this step…",
  paused: "Paused",
  stopping: "Stopping after this step…",
};

/** Pause, Resume and Stop for the build that runs now, above the composer. Hidden while nothing runs. */
export default function RunControls() {
  const run = useSession((s) => s.run);
  const controlRun = useSource((s) => s.controlRun);
  if (run === "idle") return null;
  const waiting = run === "pausing" || run === "stopping";
  const held = run === "paused" || run === "pausing";
  const button = "flex h-8 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] font-semibold transition disabled:opacity-50";
  return (
    <div
      className="mb-2 flex items-center gap-2 rounded-[18px] bg-card py-1.5 pr-1.5 pl-3.5 shadow-[var(--shadow-card)]"
      data-target="run_controls"
      title={run === "paused" ? "Resume carries on where it paused; a new message stops this run and starts from it" : undefined}
      role="status"
      aria-live="polite"
    >
      {waiting ? (
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted" />
      ) : (
        <span className={`h-2 w-2 shrink-0 rounded-full ${run === "paused" ? "bg-faint" : "animate-pulse bg-accent"}`} />
      )}
      <span className={`min-w-0 flex-1 truncate text-[13px] ${run === "paused" ? "font-medium text-ink" : "text-ink-2"}`}>{LABEL[run]}</span>
      {held ? (
        <button
          type="button"
          onClick={() => void controlRun("resume")}
          data-target="run_resume"
          className={`${button} bg-accent text-white hover:brightness-110`}
          title="Carry on from where it paused"
        >
          <Play className="h-3.5 w-3.5" fill="currentColor" />
          Resume
        </button>
      ) : (
        <button
          type="button"
          onClick={() => void controlRun("pause")}
          disabled={run === "stopping"}
          data-target="run_pause"
          className={`${button} bg-tile text-ink-2 hover:bg-track hover:text-ink`}
          title="Pause after the step that runs now"
        >
          <Pause className="h-3.5 w-3.5" fill="currentColor" />
          Pause
        </button>
      )}
      <button
        type="button"
        onClick={() => void controlRun("stop")}
        disabled={run === "stopping"}
        data-target="run_stop"
        className={`${button} bg-tile text-ink-2 hover:bg-track hover:text-fail-ink`}
        title="Stop after the step that runs now; everything built so far stays"
      >
        <Square className="h-3 w-3" fill="currentColor" />
        Stop
      </button>
    </div>
  );
}
