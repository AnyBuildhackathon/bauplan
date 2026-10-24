import { useEffect } from "react";
import { useSession, type LoggedEvent, type SessionState } from "../events/store";
import { useUi, type CanvasTab, type ModelLook } from "./ui";
import { useSimPane } from "../components/training/useBrowserTraining";

interface Shot {
  tab: CanvasTab;
  look?: ModelLook;
  compare?: [number, number] | null;
}

function shotFor({ ev }: LoggedEvent, state: SessionState): Shot | null {
  if (ev.type === "version") {
    const before = state.versions.filter((v) => v.n < ev.n && (v.product ?? "drone") === (ev.product ?? "drone")).at(-1);
    return { tab: "modell", look: "3d", compare: before ? [before.n, ev.n] : null };
  }
  if (ev.type === "step" && ev.status === "running") {
    if (ev.id === "cad" || ev.id === "teile") return { tab: "cad" };
    if (ev.id === "simulation") return { tab: "simulation" };
    if (ev.id === "render") return { tab: "modell", look: "render" };
  }
  if (ev.type === "cad") return { tab: "cad" };
  if (ev.type === "sim") return { tab: "simulation" };
  if (ev.type === "omniverse" && ev.source === "live") return { tab: "omniverse" };
  return null;
}

/** Keep the latest shot pending during manual browsing, then resume even if no new event arrives. */
export function useDirector() {
  useEffect(() => {
    let pending: Shot | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const sync = () => {
      clearTimeout(timer);
      const ui = useUi.getState();
      if (!pending || !ui.director || ui.view !== "werkbank") return;
      const remaining = ui.directorPausedUntil - Date.now();
      if (remaining > 0) {
        timer = setTimeout(sync, remaining);
        return;
      }
      if (pending.tab === "simulation") useSimPane.getState().setPane("hover");
      useUi.setState({
        tab: pending.tab,
        ...(pending.look ? { look: pending.look } : {}),
        compare: pending.compare ?? null,
        selectedVersion: null,
        selectedRun: null,
      });
    };
    const initial = useSession.getState();
    for (const entry of [...initial.log].reverse()) {
      if (entry.ev.type === "product") break;
      pending = shotFor(entry, initial);
      if (pending) break;
    }
    sync();
    const unsubscribeSession = useSession.subscribe((state, previous) => {
      if (state.log === previous.log) return;
      const entry = state.log.at(-1);
      if (!entry || entry.ev.type === "product") {
        pending = null;
        clearTimeout(timer);
        useUi.setState({ compare: null, selectedVersion: null, selectedRun: null });
        return;
      }
      const shot = shotFor(entry, state);
      if (shot) {
        pending = shot;
        sync();
      }
    });
    const unsubscribeUi = useUi.subscribe((state, previous) => {
      if (state.director !== previous.director || state.directorPausedUntil !== previous.directorPausedUntil || state.view !== previous.view) sync();
    });
    return () => {
      clearTimeout(timer);
      unsubscribeSession();
      unsubscribeUi();
    };
  }, []);
}
