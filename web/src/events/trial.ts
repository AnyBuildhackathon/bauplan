// Robo Use trials (docs/events.md, trial): an independent benchmark drove the built gripper and its episode
// server judged the end state. The session store keeps the latest event per trial id through `reduceTrial`;
// the Simulation tab's Robo Use pane and the chat card read them, and `useTrialPane` remembers which one is open.
import { create } from "zustand";

/** `recorded`: Robo Use did not run now; a trial recorded earlier stands in (see `recorded`). */
export type TrialStatus = "running" | "done" | "recorded" | "failed";
/** oracle is the task's scripted reference solution; claude-code lets Claude Code drive the gripper. */
export type TrialHarness = "oracle" | "claude-code" | "noop";
/** invalid: the no-op control scored, so the task tests nothing; refused: the gripper cannot take the object at all. */
export type TrialVerdict = "pass" | "fail" | "invalid" | "refused";

export type Vec3 = [number, number, number];

/** One robo request of the policy, timed on the video. */
export interface TrialStep {
  index: number;
  op: string;
  /** The command line that sent it, e.g. `robo grip 1 --steps 25`. */
  action: string;
  /** The answer in short: reached, hand position, opening, what it holds. */
  result: string;
  ok: boolean;
  /** Video seconds; a request that moves nothing starts and ends at once. */
  t_start: number;
  t_end: number;
  env_steps: [number, number];
  hand_pos: Vec3 | null;
  gripper_open: number | null;
  holding: string[] | null;
  /** Where each object is after this request. */
  objects: Record<string, Vec3 | null>;
  /** An agent's own words before the request; null for the reference solution. */
  message: string | null;
}

export interface TrialValidity {
  reference: number | null;
  noop: number | null;
  valid: boolean;
  /** `robouse tasks check`'s report, one line each. */
  report: string[];
}

export interface TrialScene {
  object: { name: string; kind: string | null; color: string | null; size_m: Vec3 | null; path: [number, number, number, number][] } | null;
  target: {
    name: string;
    kind: string | null;
    pos: Vec3;
    floor_z: number | null;
    rim_z: number | null;
    inner_diameter_m: number | null;
    size_m: (number | null)[] | null;
  } | null;
}

export interface TrialDesign {
  servo: string | null;
  pads: string | null;
  opening_mm: number | null;
  object_mass_g: number | null;
  object_width_mm: number | null;
  goal: "bowl" | "pad" | string;
}

export interface TrialEvent {
  type: "trial";
  id: string;
  status: TrialStatus;
  /** While running: export, task, check, then agent for Claude Code. */
  stage?: "export" | "task" | "check" | "agent" | null;
  detail?: string;
  harness: TrialHarness | string;
  requested_harness?: string;
  task_id?: string;
  task_title: string;
  verdict?: TrialVerdict | null;
  reward?: number;
  success?: boolean;
  outcome?: string | null;
  steps_used?: number;
  max_steps?: number;
  wall_s?: number | null;
  /** Robo Use's episode metrics; max_contact_force_n and safety_events among them. */
  metrics?: Record<string, number>;
  validity: TrialValidity | null;
  video_url?: string | null;
  video_info?: { fps: number; duration_s: number; size: [number, number] | null };
  steps?: TrialStep[];
  /** The hand's tool point, [t, x, y, z] in video seconds and metres (z up, the table top at 0). */
  ee_path?: [number, number, number, number][];
  /** The largest contact force, [t, newtons]. */
  force?: [number, number][];
  scene?: TrialScene;
  analysis?: { held: boolean; lift_slip_mm: number | null; dropped: string | null; released: boolean; distance_mm: number | null };
  summary?: string;
  /** The bench version the trial ran on. */
  version: number;
  design?: TrialDesign;
  provenance?: { robouse?: string; mujoco?: string };
  ran_at?: string | null;
  /** Only on a recorded trial: why Robo Use did not run, and whether it is this same design. */
  recorded?: { matches_build: boolean; reason: string } | null;
  error?: string | null;
}

export type TrialRun = TrialEvent & { seq: number; at: number };

export interface TrialSlice {
  /** Trials by id, the latest event of each; `trialOrder` lists them oldest first. */
  trials: Record<string, TrialRun>;
  trialOrder: string[];
}

export const emptyTrials = (): TrialSlice => ({ trials: {}, trialOrder: [] });

/** Folds one trial event: a running trial updates in place until its result arrives under the same id. */
export function reduceTrial(s: TrialSlice, ev: TrialEvent, seq: number, at: number): TrialSlice {
  const known = s.trials[ev.id];
  return {
    trials: { ...s.trials, [ev.id]: { ...ev, seq: known?.seq ?? seq, at: known?.at ?? at } },
    trialOrder: known ? s.trialOrder : [...s.trialOrder, ev.id],
  };
}

/**
 * The trial picked for the Robo Use pane, and the newest trial when it was picked: a newer trial takes the pane
 * again, as the director shows every new result.
 */
export const useTrialPane = create<{ selected: string | null; newest: string | null; select: (id: string | null, newest: string | null) => void }>((set) => ({
  selected: null,
  newest: null,
  select: (selected, newest) => set({ selected, newest }),
}));

/** The trial the pane shows: the one picked while it was still the latest pick, else the newest. */
export function shownTrial(s: TrialSlice, pick: { selected: string | null; newest: string | null }): TrialRun | undefined {
  const newest = s.trialOrder.at(-1);
  if (pick.selected && pick.newest === newest && s.trials[pick.selected]) return s.trials[pick.selected];
  return newest ? s.trials[newest] : undefined;
}

export const HARNESS_LABEL: Record<string, string> = { oracle: "Reference solution", "claude-code": "Claude Code", noop: "No-op control" };

/** A reward as the check report writes it: 1.0, 0.0. */
export const fmtReward = (v: number | null | undefined) => (typeof v === "number" ? v.toFixed(1) : "–");

/** The design in one line: servo, pads, jaw, cube. */
export function designLine(d: TrialDesign | undefined): string {
  if (!d) return "";
  const pieces = [d.servo, d.pads, d.opening_mm != null ? `${d.opening_mm} mm jaw` : null];
  if (d.object_width_mm != null && d.object_mass_g != null) pieces.push(`cube ${d.object_width_mm} mm, ${d.object_mass_g} g`);
  return pieces.filter(Boolean).join(" · ");
}

export type TrialTone = "ok" | "fail" | "muted" | "agent";

/** How the verdict reads: a recorded trial of another design is an example, never this build's result. */
export function verdictOf(t: TrialEvent): { label: string; tone: TrialTone } {
  if (t.status === "running") return { label: "Running", tone: "agent" };
  if (t.status === "failed") return { label: t.verdict === "refused" ? "Cannot take the cube" : "Could not run", tone: "fail" };
  const example = t.status === "recorded" && !t.recorded?.matches_build;
  if (t.verdict === "invalid") return { label: "Not counted", tone: "muted" };
  const pass = t.verdict === "pass";
  if (example) return { label: pass ? "Example passed" : "Example failed", tone: "muted" };
  return { label: pass ? "Passed" : "Failed", tone: pass ? "ok" : "fail" };
}
