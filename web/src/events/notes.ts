// Studio notes waiting in Mechanic's message box (U6): what the person clicked, measured, drew on or
// read in the studio, as small chips that go with the next message as structured attachments
// (StudioNote, docs/events.md). A studio tool adds one with `attach`; the box shows the chips, a chip's
// × removes it, and sending takes them all (and puts them back when the message did not arrive).
import { create } from "zustand";
import { fmtNum } from "../lib/format";
import { useUi } from "../lib/ui";
import { buildOf } from "./analysis";
import { useSource } from "./source";
import { useSession } from "./store";
import type { SentNote, StudioNote } from "./types";

export const MAX_NOTES = 8;
/** Below this width the studio and the chat take turns; a note then says where it went instead of switching. */
const NARROW = 768;

export interface DraftNote {
  id: string;
  note: StudioNote;
  /** A marking's picture for its chip. */
  thumb?: string | null;
}

interface NotesState {
  notes: DraftNote[];
  /** False when the box holds MAX_NOTES already or the same note is in it. */
  add: (note: StudioNote, thumb?: string | null) => boolean;
  remove: (id: string) => void;
  /** Empties the box for a message that is being sent. */
  take: () => DraftNote[];
  /** A message that did not arrive gets its notes back. */
  restore: (drafts: DraftNote[]) => void;
}

let count = 0;

/** Two notes that say the same: the same part and point, the same spot, the same parameter. */
function same(a: StudioNote, b: StudioNote): boolean {
  if (a.kind !== b.kind) return false;
  if (a.kind === "markup") return a.image === (b as typeof a).image;
  if (a.kind === "param") return a.name === (b as typeof a).name;
  return JSON.stringify(a) === JSON.stringify(b);
}

export const useNotes = create<NotesState>((set, get) => ({
  notes: [],
  add: (note, thumb = null) => {
    const { notes } = get();
    // A parameter note follows its slider: the newer value replaces the older one.
    if (note.kind === "param" && notes.some((d) => same(d.note, note))) {
      set({ notes: notes.map((d) => (same(d.note, note) ? { ...d, note } : d)) });
      return true;
    }
    if (notes.length >= MAX_NOTES || notes.some((d) => same(d.note, note))) return false;
    set({ notes: [...notes, { id: `note-${++count}`, note, thumb }] });
    return true;
  },
  remove: (id) => set((s) => ({ notes: s.notes.filter((d) => d.id !== id) })),
  take: () => {
    const taken = get().notes;
    set({ notes: [] });
    return taken;
  },
  restore: (drafts) => set((s) => ({ notes: [...drafts, ...s.notes].slice(0, MAX_NOTES) })),
}));

// A fresh bench has nothing to point at yet.
useSession.subscribe((s, prev) => {
  if (s.chat.length === 0 && prev.chat.length > 0) useNotes.setState({ notes: [] });
});

/** The CAD build the studio shows now, the `?build=` of the model; null before the first build. */
export function shownBuild(): number | null {
  const build = buildOf(useSession.getState().cad?.glb_url);
  return build === null ? null : Number(build);
}

/** Puts a note into Mechanic's message box and brings the box into view. */
export function attach(note: StudioNote, thumb: string | null = null): boolean {
  if (!useNotes.getState().add(note, thumb)) {
    if (useNotes.getState().notes.length >= MAX_NOTES) useSource.setState({ notice: `A message takes ${MAX_NOTES} notes at most.` });
    return false;
  }
  if (window.innerWidth < NARROW) {
    useSource.setState({ notice: "Added to your message for Mechanic." });
    return true;
  }
  useUi.getState().setRightTab("mechanic");
  requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('[data-target="panel"] [data-target~="chat_input"]')?.focus());
  return true;
}

const mm = (v: number) => `${fmtNum(v, Math.abs(v) < 100 ? 1 : 0)} mm`;
const point = (p: number[]) => `(${p.map((v) => fmtNum(v, 1)).join(", ")}) mm`;
const UNIT = { overhang: "°", thickness: " mm", clearance: " mm" } as const;
const CHECK_WORD = { overhang: "Overhang", thickness: "Wall", clearance: "Gap" } as const;

/** What a chip says, and its tooltip with the rest. */
export function noteLabel(note: StudioNote | SentNote): { text: string; title: string } {
  const sent = note as SentNote;
  const older = sent.built_as && !sent.built_as.current ? " · on an older build" : "";
  switch (note.kind) {
    case "selection": {
      const at = note.point_mm ? `${note.cut ? " inside, on the cut," : ""} at ${point(note.point_mm)}` : "";
      const lines = sent.script && sent.lines ? ` · ${sent.script} lines ${sent.lines.map(([a, b]) => (a === b ? `${a}` : `${a}-${b}`)).join(", ")}` : "";
      return { text: note.part, title: `Selection: ${note.part}${at}${lines}${older}` };
    }
    case "measure": {
      const d = Math.hypot(note.b.point_mm[0] - note.a.point_mm[0], note.b.point_mm[1] - note.a.point_mm[1], note.b.point_mm[2] - note.a.point_mm[2]);
      const ends = [note.a.part, note.b.part].filter(Boolean);
      return { text: mm(d), title: `Measured ${mm(d)}${ends.length === 2 ? ` from ${ends[0]} to ${ends[1]}` : ""}${older}` };
    }
    case "markup":
      return { text: "Marking", title: `Your drawing on the ${note.view.tab === "cad" ? "CAD" : "Model"} view${note.view.section ? `, cut through ${note.view.section.axis.toUpperCase()}` : ""}${older}` };
    case "spot": {
      const value = note.check === "overhang" ? `${Math.round(note.value)}°` : `${note.value.toFixed(2)}${UNIT[note.check]}`;
      return { text: `${CHECK_WORD[note.check]} ${value}`, title: `${CHECK_WORD[note.check]} ${value} on ${note.part.replace(/_/g, " ")} at ${point(note.at_mm)}${older}` };
    }
    case "param": {
      const unit = note.unit ? ` ${note.unit}` : "";
      const value = `${fmtNum(note.value, Number.isInteger(note.value) ? 0 : 1)}${unit}`;
      const was = note.default !== null && note.default !== undefined && Math.abs(note.default - note.value) > 1e-9 ? ` (designed ${fmtNum(note.default, Number.isInteger(note.default) ? 0 : 1)}${unit})` : "";
      return { text: `${note.label} ${value}`, title: `Parameter ${note.label}: ${value}${was}${older}` };
    }
  }
}
