// Transient studio state shared by the view bar, the panels and the 3D scenes: one-shot
// camera commands (views, zoom), the parts the assembly tree hides, and a draft the parts
// panel hands to Mechanic's message box. The lasting switches (grid, labels, ortho, the
// tool, the right tab) live in lib/ui.ts.
import { create } from "zustand";
import { useSession } from "../../events/store";

export type CameraView = "front" | "side" | "top" | "home";
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
}));

// A reset bench starts with every part visible again.
useSession.subscribe((s, prev) => {
  if (!s.cad && prev.cad) useStudio.setState({ hidden: [] });
});
