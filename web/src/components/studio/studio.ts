// Transient studio state shared by the view bar, the panels and the 3D scenes: one-shot
// camera commands (views, zoom), the parts the assembly tree hides, a draft the parts
// panel hands to Mechanic's message box, the section view, and what the studio's notes to
// Mechanic read from the scene (the last click, the measurement, the view). The lasting
// switches (grid, labels, ortho, the tool, the right tab) live in lib/ui.ts.
import type * as THREE from "three";
import { create } from "zustand";
import { useSession } from "../../events/store";
import type { NotePoint, NoteView } from "../../events/types";
import { useUi } from "../../lib/ui";
import { useExplodeHover } from "../canvas/explode";

export type CameraView = "front" | "side" | "top" | "home";
export type SectionAxis = "x" | "y" | "z";
/** One cutting plane across the build's X, Y or Z at `at` mm, keeping the side below or above it.
 * `at` and `keep` are null until the scene sets them: the middle of the model, the half facing the camera cut away. */
export interface Section {
  axis: SectionAxis;
  at: number | null;
  keep: "below" | "above" | null;
}
export type CameraCommand = { kind: "view"; view: CameraView } | { kind: "zoom"; factor: number } | { kind: "fit" };

/** The camera views by key, as the view bar lists them. */
export const VIEW_KEYS: Record<string, CameraView> = { "1": "front", "2": "side", "3": "top", "4": "home" };

interface StudioState {
  /** The latest camera command; `n` counts them, so pressing the same view twice moves twice. */
  command: (CameraCommand & { n: number }) | null;
  send: (command: CameraCommand) => void;
  /** The part nodes of the model the studio shows: normalised name to the node's own name. Set by the scene. */
  nodes: Record<string, string>;
  setNodes: (nodes: Record<string, string>) => void;
  /** Part nodes (normalised names) hidden from the assembly tree. */
  hidden: string[];
  setHidden: (names: string[], hide: boolean) => void;
  showAll: () => void;
  /** Text for Mechanic's message box; the chat takes it once. */
  draft: { text: string; n: number } | null;
  compose: (text: string) => void;
  /** The section view; null shows the whole model. Off on every new bench. */
  section: Section | null;
  setSection: (section: Section | null) => void;
  /** The model's extent along the section's axis in mm, set by the scene for the slider. */
  sectionRange: { min: number; max: number } | null;
  /** The cutting plane in world space while the section is on (the scene's), so a click goes through what it cut away. */
  clip: THREE.Plane | null;
  /** The last click on the model with the Select tool, in the build's mm. */
  pick: (NotePoint & { node: string; cut: boolean; n: number }) | null;
  /** Both points of the Measure tool, in the build's mm, once it has two. */
  measurement: { a: NotePoint; b: NotePoint } | null;
  /** Reads how the studio shows the model now, for a marking; set by the scene. */
  view: (() => NoteView) | null;
}

let count = 0;

export const useStudio = create<StudioState>((set) => ({
  command: null,
  send: (command) => set({ command: { ...command, n: ++count } }),
  nodes: {},
  setNodes: (nodes) => set({ nodes }),
  hidden: [],
  setHidden: (names, hide) =>
    set((s) => ({ hidden: hide ? [...new Set([...s.hidden, ...names])] : s.hidden.filter((n) => !names.includes(n)) })),
  showAll: () => set({ hidden: [] }),
  draft: null,
  compose: (text) => set({ draft: { text, n: ++count } }),
  section: null,
  setSection: (section) => set({ section }),
  sectionRange: null,
  clip: null,
  pick: null,
  measurement: null,
  view: null,
}));

/** The section on (across Z, which reads on most models) or off again. */
export function toggleSection() {
  const { section, setSection } = useStudio.getState();
  setSection(section ? null : { axis: "z", at: null, keep: null });
}

/** The Mark tool on or off; drawing takes the pointer, so the part card leaves as for measuring. */
export function toggleMark() {
  const ui = useUi.getState();
  useExplodeHover.getState().pin(null);
  ui.setTool(ui.tool === "mark" ? "select" : "mark");
}

// A reset bench starts with every part visible again and the whole model, uncut.
useSession.subscribe((s, prev) => {
  if (!s.cad && prev.cad) useStudio.setState({ hidden: [], section: null, pick: null, measurement: null });
});
