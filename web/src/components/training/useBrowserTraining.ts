// Starts a browser training run when the backend queues one, and keeps the local
// trainer in step with session resets. Mounted once in App.
import { useEffect } from "react";
import { create } from "zustand";
import { useSession } from "../../events/store";
import type { TrainingEvent } from "../../events/types";
import { useUi } from "../../lib/ui";
import { abandonTraining, resetTrainer, runBrowserTraining, useTrainer, watchElsewhere, type BrowserTrainingFields } from "../../sim/trainer";

export type BrowserTrainingEvent = TrainingEvent & BrowserTrainingFields & { at: number };

/** Inside the Simulation tab: the hover test runs, the mission tests, the browser training or the FEM stress of printed parts. */
export type SimPane = "hover" | "missions" | "training" | "stress";
export const useSimPane = create<{ pane: SimPane; setPane: (pane: SimPane) => void }>((set) => ({
  pane: "hover",
  setPane: (pane) => set({ pane }),
}));

/** The latest `training` event when it comes from a browser run, else null. */
export function useBrowserTrainingEvent(): BrowserTrainingEvent | null {
  return useSession((s) => s.browserTraining as BrowserTrainingEvent | null);
}

/** A queued job older than this is backlog from before this tab connected; it is not started again. */
const FRESH_MS = 30_000;

export function useBrowserTraining() {
  useEffect(() => {
    const handle = (t: BrowserTrainingEvent | null) => {
      if (!t) {
        const { status } = useTrainer.getState();
        if (status !== "idle" && status !== "running" && status !== "claiming") resetTrainer();
        return;
      }
      if (t.source !== "browser" || !t.job_id) return;
      const local = useTrainer.getState();
      if (t.status === "queued" && Date.now() - t.at < FRESH_MS && local.jobId !== t.job_id) {
        // The Training page already shows this run. Other views jump to the simulation grid.
        if (useUi.getState().view !== "training") {
          useUi.getState().setView("werkbank");
          useUi.getState().setTab("simulation");
          useSimPane.getState().setPane("training");
        }
        void runBrowserTraining(t.job_id, {
          productId: t.product ?? "drone",
          spec: t.spec,
          population: t.population ?? 64,
          generations: t.generations ?? 16,
        });
      } else if (local.jobId === t.job_id && t.status === "failed") {
        abandonTraining(t.job_id, t.error ?? "failed");
      } else if (local.jobId !== t.job_id && t.status !== "queued") {
        watchElsewhere(t.job_id);
      }
    };
    handle(useSession.getState().browserTraining as BrowserTrainingEvent | null);
    return useSession.subscribe((s, prev) => {
      if (s.browserTraining !== prev.browserTraining) handle(s.browserTraining as BrowserTrainingEvent | null);
    });
  }, []);
}
