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
}

interface UiState {
  view: View;
  tab: CanvasTab;
  /** Inside the Modell tab: the live 3D model or the Blender render. */
  look: ModelLook;
  /** Version picked on the meeting timeline; null follows the newest. */
  selectedVersion: number | null;
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
  setDisplay: (patch: Partial<Display>) => void;
  setView: (view: View) => void;
  setTab: (tab: CanvasTab) => void;
  setLook: (look: ModelLook) => void;
  selectVersion: (n: number | null) => void;
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
const DISPLAY_DEFAULT: Display = { agents: false, tools: false, jamie: false, allMetrics: false };

function storedDisplay(): Display {
  try {
    const raw = localStorage.getItem(DISPLAY_KEY);
    return raw ? { ...DISPLAY_DEFAULT, ...(JSON.parse(raw) as Partial<Display>) } : DISPLAY_DEFAULT;
  } catch {
    return DISPLAY_DEFAULT;
  }
}

const MIC_KEY = "anybuild.mic";

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
  resetUi: () => set({ selectedVersion: null, selectedRun: null, lessonStep: null, concepts: {}, bomOpen: false }),
}));
