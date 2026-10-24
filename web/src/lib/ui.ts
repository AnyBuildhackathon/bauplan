import { create } from "zustand";
import { STEP_IDS, type StepId } from "../events/types";

/** The main screen is the Werkbank; Library, Training and Logbuch sit on the icon rail. */
export type View = "werkbank" | "library" | "training" | "logbuch";
export type CanvasTab = "modell" | "cad" | "simulation" | "omniverse";
export type ModelLook = "3d" | "render";
export type ConceptStatus = "verstanden" | "gesehen";
export type MicMode = "handsfree" | "ptt";

/** What the dashboard shows beyond the essentials. Off by default, remembered per browser. */
export interface Display {
  agents: boolean;
  tools: boolean;
  jamie: boolean;
  allMetrics: boolean;
  /** Learning mode: Mechanic explains every decision ("Why?" links, a glossary), and the logbook shows what was learned. */
  learning: boolean;
}

interface UiState {
  view: View;
  tab: CanvasTab;
  /** Inside the Modell tab: the live 3D model or the Blender render. */
  look: ModelLook;
  /** Version picked on the meeting timeline; null follows the newest. */
  selectedVersion: number | null;
  /** The version history drawer, opened from the timeline. */
  versionsOpen: boolean;
  /** Two versions side by side in the Model tab, older first; null shows the single model. */
  compare: [number, number] | null;
  /** Simulation run picked in the Simulation tab; null follows the newest run. */
  selectedRun: number | null;
  bomOpen: boolean;
  lessonStep: StepId | null;
  concepts: Record<string, ConceptStatus>;
  /** Push-to-talk is held down. */
  listening: boolean;
  /** Hands-free: the mic listens for turns and the button toggles it; push-to-talk is the fallback. Remembered per browser. */
  micMode: MicMode;
  /** The hands-free conversation is running. */
  handsFree: boolean;
  /** The person is in the middle of a spoken turn, so Mechanic keeps quiet. */
  userTalking: boolean;
  /** Mechanic reads his lines aloud. Remembered per browser. */
  voiceOn: boolean;
  /** Who listens to the microphone: Reson8, the browser, or nobody. */
  stt: "reson8" | "browser" | "none";
  display: Display;
  /** Explode amount of the Model tab, 0 assembled to 1 every part pulled apart. */
  explode: number;
  /** The part the 3D camera turns to; `at` restarts the move for the same part. */
  focus: { part: string; at: number } | null;
  settingsOpen: boolean;
  /** The library item shown in the inspector; null picks the first. */
  libraryPick: string | null;
  /** HeyClicky: Mechanic's pointer flies to the controls he operates. Remembered per browser. */
  clicky: boolean;
  setExplode: (explode: number) => void;
  setFocus: (part: string | null) => void;
  setSettingsOpen: (open: boolean) => void;
  setLibraryPick: (id: string | null) => void;
  setClicky: (on: boolean) => void;
  setDisplay: (patch: Partial<Display>) => void;
  setView: (view: View) => void;
  setTab: (tab: CanvasTab) => void;
  setLook: (look: ModelLook) => void;
  selectVersion: (n: number | null) => void;
  setVersionsOpen: (open: boolean) => void;
  setCompare: (pair: [number, number] | null) => void;
  selectRun: (run: number | null) => void;
  setBomOpen: (open: boolean) => void;
  openLesson: (step: StepId) => void;
  closeLesson: () => void;
  markConcept: (id: string, status: ConceptStatus) => void;
  setListening: (on: boolean) => void;
  setMicMode: (mode: MicMode) => void;
  setHandsFree: (on: boolean) => void;
  setUserTalking: (on: boolean) => void;
  setVoiceOn: (on: boolean) => void;
  resetUi: () => void;
}

const VIEWS: View[] = ["werkbank", "library", "training", "logbuch"];
const TABS: CanvasTab[] = ["modell", "cad", "simulation", "omniverse"];
const params = () => new URLSearchParams(window.location.search);
const VOICE_KEY = "bauplan.voice";
const DISPLAY_KEY = "anybuild.display";
const DISPLAY_DEFAULT: Display = { agents: false, tools: false, jamie: false, allMetrics: false, learning: false };

function storedDisplay(): Display {
  // `?learning` turns learning mode on for this page, for a demo link.
  const url: Partial<Display> = params().has("learning") ? { learning: true } : {};
  try {
    const raw = localStorage.getItem(DISPLAY_KEY);
    return { ...DISPLAY_DEFAULT, ...(raw ? (JSON.parse(raw) as Partial<Display>) : {}), ...url };
  } catch {
    return { ...DISPLAY_DEFAULT, ...url };
  }
}

const MIC_KEY = "anybuild.mic";
const CLICKY_KEY = "anybuild.clicky";

function storedClicky(): boolean {
  try {
    return localStorage.getItem(CLICKY_KEY) !== "off";
  } catch {
    return true;
  }
}

function storedMicMode(): MicMode {
  try {
    return localStorage.getItem(MIC_KEY) === "ptt" ? "ptt" : "handsfree";
  } catch {
    return "handsfree";
  }
}

function storedVoice(): boolean {
  if (params().has("mute")) return false;
  try {
    return localStorage.getItem(VOICE_KEY) !== "off";
  } catch {
    return true;
  }
}

function initialView(): View {
  const v = params().get("view");
  return VIEWS.includes(v as View) ? (v as View) : "werkbank";
}
function initialLesson(): StepId | null {
  const l = params().get("lesson");
  return STEP_IDS.includes(l as StepId) ? (l as StepId) : null;
}
function initialTab(): CanvasTab {
  const t = params().get("tab");
  if (t === "render") return "modell";
  return TABS.includes(t as CanvasTab) ? (t as CanvasTab) : "modell";
}

export const useUi = create<UiState>((set) => ({
  view: initialView(),
  tab: initialTab(),
  look: params().get("tab") === "render" ? "render" : "3d",
  selectedVersion: null,
  versionsOpen: false,
  compare: null,
  selectedRun: null,
  bomOpen: params().has("bom"),
  lessonStep: initialLesson(),
  concepts: {},
  listening: false,
  micMode: storedMicMode(),
  handsFree: false,
  userTalking: false,
  voiceOn: storedVoice(),
  display: storedDisplay(),
  explode: 0,
  focus: null,
  settingsOpen: false,
  libraryPick: null,
  clicky: storedClicky(),
  setExplode: (explode) => set({ explode: Math.max(0, Math.min(1, explode)) }),
  setFocus: (part) => set({ focus: part ? { part, at: Date.now() } : null }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
  setLibraryPick: (libraryPick) => set({ libraryPick }),
  setClicky: (clicky) => {
    try {
      localStorage.setItem(CLICKY_KEY, clicky ? "on" : "off");
    } catch {
      // Private windows may refuse storage; the choice lasts for this page.
    }
    set({ clicky });
  },
  setDisplay: (patch) =>
    set((s) => {
      const display = { ...s.display, ...patch };
      try {
        localStorage.setItem(DISPLAY_KEY, JSON.stringify(display));
      } catch {
        // Private windows may refuse storage; the choice lasts for this page.
      }
      return { display };
    }),
  stt: "SpeechRecognition" in window || "webkitSpeechRecognition" in window ? "browser" : "none",
  setView: (view) => set({ view }),
  setTab: (tab) => set({ tab }),
  setLook: (look) => set({ look, tab: "modell" }),
  selectVersion: (selectedVersion) => set({ selectedVersion }),
  setVersionsOpen: (versionsOpen) => set({ versionsOpen }),
  setCompare: (compare) => set(compare ? { compare, tab: "modell", look: "3d" } : { compare }),
  selectRun: (selectedRun) => set({ selectedRun }),
  setBomOpen: (bomOpen) => set({ bomOpen }),
  openLesson: (lessonStep) =>
    set((s) => ({ lessonStep, concepts: s.concepts[lessonStep] ? s.concepts : { ...s.concepts, [lessonStep]: "gesehen" } })),
  closeLesson: () => set({ lessonStep: null }),
  markConcept: (id, status) => set((s) => ({ concepts: { ...s.concepts, [id]: status } })),
  setListening: (listening) => set({ listening }),
  setMicMode: (micMode) => {
    try {
      localStorage.setItem(MIC_KEY, micMode);
    } catch {
      // Private windows may refuse storage; the choice lasts for this page.
    }
    set({ micMode });
  },
  setHandsFree: (handsFree) => set(handsFree ? { handsFree } : { handsFree, userTalking: false }),
  setUserTalking: (userTalking) => set({ userTalking }),
  setVoiceOn: (voiceOn) => {
    try {
      localStorage.setItem(VOICE_KEY, voiceOn ? "on" : "off");
    } catch {
      // Private windows may refuse storage; the choice lasts for this page.
    }
    set({ voiceOn });
  },
  resetUi: () => set({ selectedVersion: null, versionsOpen: false, compare: null, selectedRun: null, lessonStep: null, concepts: {}, bomOpen: false, explode: 0, focus: null }),
}));
