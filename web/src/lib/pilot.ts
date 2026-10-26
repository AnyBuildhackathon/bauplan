// Mechanic operating the dashboard (`ui` events, docs/events.md). For every control the
// pointer first flies to the real on-screen element tagged `data-control`, presses it with
// a short bubble, then the action happens, so the room sees him use the app. Controls that
// live behind another one (a setting inside the settings panel, the CAD tab while the
// library is open) press their way there first. With HeyClicky off the actions apply at once.
import { useEffect } from "react";
import { create } from "zustand";
import { INSTANT_AGE_MS, useSession } from "../events/store";
import type { UiEvent } from "../events/types";
import { useGuide } from "../views/BuildGuide";
import { useUi, type CanvasTab, type Display, type View } from "./ui";

export interface PilotFlight {
  id: number;
  target: string;
  label: string;
  /** Called once: true when the pointer landed on the target, false when it never showed up. */
  done: (landed: boolean) => void;
}

interface PilotState {
  flight: PilotFlight | null;
  fly: (target: string, label: string) => Promise<boolean>;
}

let flights = 0;

export const usePilot = create<PilotState>((set) => ({
  flight: null,
  fly: (target, label) =>
    new Promise<boolean>((resolve) => {
      set({ flight: { id: ++flights, target, label, done: resolve } });
    }),
}));

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
/** Lets React render what the last press opened before the pointer looks for the next control. */
const SETTLE_MS = 320;

const TABS: Record<string, CanvasTab> = { model: "modell", cad: "cad", simulation: "simulation", omniverse: "omniverse" };
const VIEWS: Record<string, View> = { workbench: "werkbank", library: "library", training: "training", logbook: "logbuch" };
const DISPLAY: Record<string, keyof Display> = { agents: "agents", tools: "tools", all_metrics: "allMetrics" };

/** Scrolls a control that sits below the fold (a library card) into view before the pointer goes there. */
async function reveal(control: string) {
  const el = document.querySelector<HTMLElement>(`[data-control~="${CSS.escape(control)}"]`);
  if (!el) return;
  const r = el.getBoundingClientRect();
  if (r.top >= 0 && r.bottom <= window.innerHeight) return;
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  await sleep(450);
}

/** Flies to a control and presses it, then acts; without HeyClicky it only acts. */
async function press(control: string, label: string, act: () => void = () => {}) {
  await reveal(control);
  if (useUi.getState().clicky) await usePilot.getState().fly(`control:${control}`, label);
  act();
  await sleep(SETTLE_MS);
}

async function toWorkbench() {
  if (useUi.getState().view !== "werkbank") await press("view:workbench", "", () => useUi.getState().setView("werkbank"));
}

async function toTab(tab: CanvasTab) {
  await toWorkbench();
  const ui = useUi.getState();
  if (ui.tab !== tab) {
    const name = Object.keys(TABS).find((k) => TABS[k] === tab)!;
    await press(`tab:${name}`, "", () => useUi.getState().setTab(tab));
  }
}

async function toModel3d() {
  await toTab("modell");
  if (useUi.getState().look !== "3d") await press("look:3d", "", () => useUi.getState().setLook("3d"));
}

/** Eases the explode amount, so the parts glide apart instead of jumping. */
function animateExplode(to: number) {
  const from = useUi.getState().explode;
  const start = performance.now();
  const ms = 1100;
  return new Promise<void>((resolve) => {
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      const e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
      useUi.getState().setExplode(from + (to - from) * e);
      if (t < 1) requestAnimationFrame(step);
      else resolve();
    };
    requestAnimationFrame(step);
  });
}

async function perform(ev: UiEvent) {
  const ui = useUi.getState();
  const [kind, name = ""] = ev.control.split(":");
  const open = ev.open !== false;
  switch (kind) {
    case "tab":
      await toWorkbench();
      if (TABS[name] === "modell" && useUi.getState().look !== "3d") return press("look:3d", ev.say, () => ui.setLook("3d"));
      return press(`tab:${name}`, ev.say, () => ui.setTab(TABS[name]));
    case "view":
      return press(`view:${name}`, ev.say, () => ui.setView(VIEWS[name]));
    case "library":
      if (useUi.getState().view !== "library") await press("view:library", "", () => ui.setView("library"));
      return press(`library:${name}`, ev.say, () => ui.setLibraryPick(name));
    case "explode": {
      await toModel3d();
      if (useUi.getState().clicky) await usePilot.getState().fly("control:explode", ev.say);
      return animateExplode(Number(ev.value ?? 100) / 100);
    }
    case "focus": {
      await toModel3d();
      const part = ev.part ?? "";
      ui.setFocus(part);
      if (useUi.getState().clicky) await usePilot.getState().fly(part, ev.say);
      return;
    }
    case "panel":
      if (name === "settings") {
        if (ui.settingsOpen === open) return;
        return press(open ? "panel:settings" : "panel:settings:close", ev.say, () => ui.setSettingsOpen(open));
      }
      await toWorkbench();
      if (name === "bom") {
        if (!open) return useUi.getState().bomOpen ? press("panel:bom:close", ev.say, () => ui.setBomOpen(false)) : undefined;
        return press("panel:bom", ev.say, () => ui.setBomOpen(true));
      }
      if (name === "guide") {
        if (!open) return useGuide.getState().open ? press("panel:guide:close", ev.say, () => useGuide.getState().show(false)) : undefined;
        if (!useUi.getState().bomOpen) await press("panel:bom", "", () => ui.setBomOpen(true));
        return press("panel:guide", ev.say, () => useGuide.getState().show(true));
      }
      if (name === "compare") {
        if (!open) return useUi.getState().compare ? press("panel:compare:close", ev.say, () => ui.setCompare(null)) : undefined;
        const versions = useSession.getState().versions.map((v) => v.n);
        const pair = ev.versions ?? (versions.slice(-2) as [number, number]);
        return press("panel:compare", ev.say, () => ui.setCompare(pair));
      }
      return;
    case "setting": {
      const on = ev.value !== false;
      if (name === "voice") {
        // The voice switch sits in the chat's header, so the chat comes to the front first.
        if (useUi.getState().rightTab !== "mechanic" || !useUi.getState().panelOpen) await press("rail:mechanic", "", () => ui.setRightTab("mechanic"));
        return press("setting:voice", ev.say, () => ui.setVoiceOn(on));
      }
      const wasOpen = useUi.getState().settingsOpen;
      if (!wasOpen) await press("panel:settings", "", () => ui.setSettingsOpen(true));
      await press(`setting:${name}`, ev.say, () => {
        if (name === "push_to_talk") ui.setMicMode(on ? "ptt" : "handsfree");
        else if (DISPLAY[name]) ui.setDisplay({ [DISPLAY[name]]: on });
      });
      if (!wasOpen) {
        await sleep(1400);
        useUi.getState().setSettingsOpen(false);
      }
      return;
    }
    case "run":
      // The backend runs the test or the rebuild; the pointer shows which button that is.
      if (name === "test") await toTab("simulation");
      if (name === "rebuild") await toTab("cad");
      return press(`run:${name}`, ev.say);
  }
}

let queue: Promise<void> = Promise.resolve();

/** Plays every fresh `ui` event in order; replayed history only restores nothing. */
export function usePilotRunner() {
  useEffect(
    () =>
      useSession.subscribe((s, prev) => {
        const ev = s.ui;
        if (!ev || ev === prev.ui || Date.now() - ev.at > INSTANT_AGE_MS / 2) return;
        queue = queue.then(() => perform(ev)).catch((err) => console.warn("[pilot]", err));
      }),
    [],
  );
}
