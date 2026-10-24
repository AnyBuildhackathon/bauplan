// Flies a stress test's worlds in this tab when the backend queues them, and drops a
// local run on session reset. Mounted once in App.
import { useEffect } from "react";
import { useSession } from "../../events/store";
import { resetStress, runBrowserStress } from "../../sim/stress";

/** A queued job older than this is backlog from before this tab connected; it is not started again. */
const FRESH_MS = 30_000;

export function useBrowserStress() {
  useEffect(() => {
    const handle = (stress: ReturnType<typeof useSession.getState>["stress"]) => {
      const runs = Object.keys(stress).map(Number);
      if (!runs.length) return resetStress();
      const ev = stress[Math.max(...runs)];
      if (ev.source === "browser" && ev.job_id && ev.status === "queued" && Date.now() - ev.at < FRESH_MS) {
        void runBrowserStress(ev.job_id, ev.seed);
      }
    };
    handle(useSession.getState().stress);
    return useSession.subscribe((s, prev) => {
      if (s.stress !== prev.stress) handle(s.stress);
    });
  }, []);
}
