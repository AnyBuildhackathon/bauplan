import { create } from "zustand";
import { STEP_IDS, type StepId } from "../events/types";

/** The main screen is the Werkbank; Library, Training and Logbuch sit on the icon rail. */
export type View = "werkbank" | "library" | "community" | "training" | "logbuch";
export type CanvasTab = "modell" | "cad" | "simulation" | "omniverse" | "agents";
export type ModelLook = "3d" | "render";
export type ConceptStatus = "verstanden" | "gesehen";
export type MicMode = "handsfree" | "ptt";
/** The tabs of the panel right of the studio. */
export type RightTab = "mechanic" | "versions" | "assembly" | "joints" | "checks";
/** What a click on the model does in the studio: select the part, set a measuring point, or draw a marking for Mechanic. */
export type StudioTool = "select" | "measure" | "mark";

/** The studio's view switches (the bar above the canvas). On by default except labels and ortho, remembered per browser. */
export interface StudioView {
  /** Grid lines: the CAD grid under the model, and the lines of the test stage in the simulation replays. */
  grid: boolean;
  /** Part names on the model at any explode amount; exploded parts name themselves either way. */
  labels: boolean;
  /** Orthographic projection instead of perspective. */
  ortho: boolean;
}

/** What the dashboard shows beyond the essentials. Off by default, remembered per browser. */
export interface Display {
  agents: boolean;
  tools: boolean;
  allMetrics: boolean;
  /** Learning mode: Mechanic explains every decision ("Why?" links, a glossary), and the logbook shows what was learned. */
  learning: boolean;
  /** Mechanic's full figure in the canvas corner while he speaks or explains. */
  mascot: boolean;
}

interface UiState {
  view: View;
  tab: CanvasTab;
  /** Follow engineering activity unless a person has taken the tabs for 30 seconds. */
  director: boolean;
  directorPausedUntil: number;
  setDirector: (on: boolean) => void;
  selectTab: (tab: CanvasTab) => void;
  /** Inside the Modell tab: the live 3D model or the Blender render. */
  look: ModelLook;
  /** Version picked in the Versions tab; null follows the newest. */
  selectedVersion: number | null;
  /** Two versions side by side in the Model tab, older first; null shows the single model. */
  compare: [number, number] | null;
  /** Simulation run picked in the Simulation tab; null follows the newest run. */
  selectedRun: number | null;
  /** Mission test run picked in the Simulation tab; null shows the hover test, or the newest mission when it came last. */
  selectedMission: number | null;
  bomOpen: boolean;
  /** The drawer was opened by confirming the design: it leads with the price and the order by shop. */
  bomPricing: boolean;
  /** The finished build (its results card id) the person confirmed; a new version asks again. */
  confirmedBuild: string | null;
  confirmDesign: (build: string) => void;
  openPricing: () => void;
  lessonStep: StepId | null;
  concepts: Record<string, ConceptStatus>;
  /** Push-to-talk is held down. */
  listening: boolean;
  /** Hands-free (the default): the Talk button turns the Gemini voice agent on and off; push-to-talk is an opt-in. */
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
  /** The chat fills the window beside the icon rail instead of sitting in its column. */
  chatExpanded: boolean;
  setChatExpanded: (on: boolean) => void;
  /** The studio's view switches (grid, labels, ortho), remembered per browser. */
  studio: StudioView;
  setStudio: (patch: Partial<StudioView>) => void;
  /** The tab shown in the panel right of the studio. */
  rightTab: RightTab;
  /** Shows a tab and opens the panel if it was closed. */
  setRightTab: (tab: RightTab) => void;
  /** The right panel is open; closed, only its tab bar shows. On a narrow screen the open panel takes the place of the studio. */
  panelOpen: boolean;
  setPanelOpen: (open: boolean) => void;
  tool: StudioTool;
  setTool: (tool: StudioTool) => void;
  /** The parts panel beside the studio's tool rail. */
  partsOpen: boolean;
  setPartsOpen: (open: boolean) => void;
  setDisplay: (patch: Partial<Display>) => void;
  setView: (view: View) => void;
  /** The community project to show selected when the Community view opens next. */
  communityFocus: string | null;
  openCommunity: (id: string | null) => void;
  setTab: (tab: CanvasTab) => void;
  setLook: (look: ModelLook) => void;
  selectVersion: (n: number | null) => void;
  setCompare: (pair: [number, number] | null) => void;
  selectRun: (run: number | null) => void;
  selectMission: (run: number | null) => void;
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

const VIEWS: View[] = ["werkbank", "library", "community", "training", "logbuch"];
const TABS: CanvasTab[] = ["modell", "cad", "simulation", "omniverse", "agents"];
const params = () => new URLSearchParams(window.location.search);
const VOICE_KEY = "bauplan.voice";
const DISPLAY_KEY = "anybuild.display";
const DISPLAY_DEFAULT: Display = { agents: false, tools: false, allMetrics: false, learning: false, mascot: true };

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

const STUDIO_KEY = "anybuild.studio";
const STUDIO_DEFAULT: StudioView = { grid: true, labels: false, ortho: false };

function storedStudio(): StudioView {
  try {
    const raw = localStorage.getItem(STUDIO_KEY);
    return { ...STUDIO_DEFAULT, ...(raw ? (JSON.parse(raw) as Partial<StudioView>) : {}) };
  } catch {
    return STUDIO_DEFAULT;
  }
}

const CLICKY_KEY = "anybuild.clicky";
const DIRECTOR_KEY = "anybuild.director";

function storedDirector(): boolean {
  try {
    return localStorage.getItem(DIRECTOR_KEY) !== "off";
  } catch {
    return true;
  }
}

function storedClicky(): boolean {
  try {
    return localStorage.getItem(CLICKY_KEY) !== "off";
  } catch {
    return true;
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
  director: storedDirector(),
  directorPausedUntil: params().has("tab") ? Date.now() + 30_000 : 0,
  setDirector: (director) => {
    try {
      localStorage.setItem(DIRECTOR_KEY, director ? "on" : "off");
    } catch {
      // Private windows may refuse storage; the choice lasts for this page.
    }
    set({ director, directorPausedUntil: 0 });
  },
  selectTab: (tab) => set({ tab, directorPausedUntil: Date.now() + 30_000 }),
  look: params().get("tab") === "render" ? "render" : "3d",
  selectedVersion: null,
  compare: null,
  selectedRun: null,
  selectedMission: null,
  bomOpen: params().has("bom"),
  bomPricing: false,
  confirmedBuild: null,
  confirmDesign: (confirmedBuild) => set({ confirmedBuild }),
  openPricing: () => set({ bomOpen: true, bomPricing: true }),
  lessonStep: initialLesson(),
  concepts: {},
  listening: false,
  // Every load starts with the one Talk button; push-to-talk is an opt-in for this page only.
  micMode: "handsfree",
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
  chatExpanded: false,
  setChatExpanded: (chatExpanded) => set({ chatExpanded }),
  studio: storedStudio(),
  setStudio: (patch) =>
    set((s) => {
      const studio = { ...s.studio, ...patch };
      try {
        localStorage.setItem(STUDIO_KEY, JSON.stringify(studio));
      } catch {
        // Private windows may refuse storage; the choice lasts for this page.
      }
      return { studio };
    }),
  rightTab: "mechanic",
  setRightTab: (rightTab) => set({ rightTab, panelOpen: true }),
  panelOpen: true,
  setPanelOpen: (panelOpen) => set({ panelOpen }),
  tool: "select",
  setTool: (tool) => set({ tool }),
  partsOpen: false,
  setPartsOpen: (partsOpen) => set({ partsOpen }),
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
  setView: (view) => set({ view, chatExpanded: false }),
  communityFocus: null,
  openCommunity: (communityFocus) => set({ view: "community", communityFocus, chatExpanded: false }),
  setTab: (tab) => set({ tab }),
  setLook: (look) => set({ look, tab: "modell" }),
  selectVersion: (selectedVersion) => set({ selectedVersion }),
  setCompare: (compare) => set(compare ? { compare, tab: "modell", look: "3d" } : { compare }),
  selectRun: (selectedRun) => set({ selectedRun, selectedMission: null }),
  selectMission: (selectedMission) => set({ selectedMission }),
  // Closing the pricing returns to the model it priced.
  setBomOpen: (bomOpen) => set((s) => (bomOpen || !s.bomPricing ? { bomOpen } : { bomOpen, bomPricing: false, tab: "modell" })),
  openLesson: (lessonStep) =>
    set((s) => ({ lessonStep, concepts: s.concepts[lessonStep] ? s.concepts : { ...s.concepts, [lessonStep]: "gesehen" } })),
  closeLesson: () => set({ lessonStep: null }),
  markConcept: (id, status) => set((s) => ({ concepts: { ...s.concepts, [id]: status } })),
  setListening: (listening) => set({ listening }),
  setMicMode: (micMode) => set({ micMode }),

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
  resetUi: () => set({ selectedVersion: null, compare: null, selectedRun: null, selectedMission: null, lessonStep: null, concepts: {}, bomOpen: false, bomPricing: false, confirmedBuild: null, explode: 0, focus: null, tool: "select", partsOpen: false }),
}));
