// The SSE contract shared with the agent backend (agent/, documented in docs/events.md).
// Every message on GET /api/events is one JSON object with a `type` field.

export const STEP_IDS = ["meeting", "teile", "cad", "render", "simulation", "training", "stueckliste"] as const;
export type StepId = (typeof STEP_IDS)[number];
export type StepStatus = "pending" | "running" | "done" | "failed";

export type ToolStatus = "connected" | "running" | "ok" | "error" | "offline";
export type MascotState = "ruhig" | "denkt" | "erklaert" | "freut_sich" | "besorgt";
export type DrawKind = "halo" | "arrow" | "circle" | "note";
export type TrainingStatus = "queued" | "running" | "done" | "failed" | "offline";

export interface StepEvent {
  type: "step";
  id: StepId;
  status: StepStatus;
  label: string;
}
export interface ChatEvent {
  type: "chat";
  role: "user" | "agent";
  text: string;
}
export interface ToolEvent {
  type: "tool";
  name: string;
  status: ToolStatus;
  detail: string;
}
export interface RequirementEvent {
  type: "requirement";
  id: string;
  text: string;
  source_quote: string;
  met: boolean | null;
  /** Who said it, when, and in which meeting (absent in older recordings). */
  speaker?: string;
  time?: string;
  meeting_title?: string;
  /** The earlier wording when a later meeting changed this requirement. */
  changed_from?: string | null;
  /** The number the check found against the limit, e.g. "0.81 N, min. 0.75 N" (any product). */
  detail?: string | null;
}
/** One key number as the backend wants it shown (products other than the drone send these). */
export interface MetricCard {
  key: string;
  label: string;
  value: number;
  unit: string;
  digits: number;
  /** The limit line under the number, e.g. "min. 2 ×". */
  limit: string;
  ok: boolean;
  /** The check behind this card has not run yet. */
  pending?: boolean;
}
export interface MetricsEvent {
  type: "metrics";
  weight_g: number;
  thrust_to_weight: number;
  flight_time_min: number;
  price_eur: number;
  /** When present, the panel shows these cards instead of the four drone numbers. */
  cards?: MetricCard[];
}
/** One trajectory sample: [t, x, y, z] in seconds and metres, z is up. */
export type TrajectorySample = [number, number, number, number];
export interface SimEvent {
  type: "sim";
  run: number;
  result: "pass" | "fail";
  summary: string;
  trajectory: TrajectorySample[];
  /** "grip": a gripper lifts and shakes an object; trajectory z is the object's rise, `hand` the hand's.
   * "rigid": any assembly as one body in a push or drop test; `poses` drive its model. */
  kind?: "hover" | "grip" | "rigid";
  hand?: [number, number][];
  object_width_mm?: number;
  payload_g?: number;
  force_n?: number | null;
  slip_mm?: number;
  /** rigid: push or drop. */
  mode?: "push" | "drop";
  /** rigid: [t, x, y, z, qw, qx, qy, qz] of the body frame, metres, z up. */
  poses?: number[][];
  /** rigid: [t, tilt in degrees]. */
  tilt?: [number, number][];
  /** rigid: the assembly model; the body frame is its frame shifted down by floor_mm. */
  glb_url?: string;
  floor_mm?: number;
  bbox_mm?: number[];
  /** rigid push: where it is pushed in the body frame (mm), the direction in plan view, and when. */
  push_point_mm?: number[] | null;
  push_dir?: number[] | null;
  push_window_s?: number[] | null;
  limit_deg?: number | null;
}
/** Which product this session builds. */
export interface ProductEvent {
  type: "product";
  /** "drone", "gripper", or the slug of a product spec such as "phone-stand". */
  id: string;
  label: string;
  /** "generic" for a product built from a spec. */
  kind?: "generic";
  /** A spec's requirement ids; a revised spec drops the rows it no longer has. */
  requirements?: string[];
}
export interface DrawEvent {
  type: "draw";
  kind: DrawKind;
  target: string;
  text: string;
}
export interface BomItem {
  name: string;
  qty: number;
  unit_price_eur: number;
  weight_g: number;
  shop: string;
  url: string;
  /** Where the price comes from: a catalog sample, an estimate, or a live shop price. */
  price_source?: "sample" | "estimated" | "live";
  /** The spec part this line belongs to (any product). */
  category?: string;
}
export interface BomEvent {
  type: "bom";
  items: BomItem[];
  total_eur: number;
  stl_path: string;
}
export interface MascotEvent {
  type: "mascot";
  state: MascotState;
  say: string;
}
export interface JamieEvent {
  type: "jamie";
  action: string;
  status: string;
  detail: string;
}
export interface PointEvent {
  type: "point";
  target: string;
  label: string;
}
export interface TrainingEvent {
  type: "training";
  status: TrainingStatus;
  step: number;
  reward: number;
  curve: [number, number][];
  video_url: string | null;
}
/** One randomized world of a stress test. Drone and gripper worlds share the first fields. */
export interface StressWorld {
  i: number;
  pass: boolean;
  /** Drone: crashed, drifted, sagged. Gripper: dropped, slipped. "" when it survived. */
  reason: string;
  mass_pct: number;
  /** Motor (drone) or servo (gripper) strength against the datasheet. */
  motor_pct: number;
  /** 1 is a perfect run, 0 or less a lost world. */
  margin: number;
  // Drone worlds.
  gust_mps?: number;
  downdraft_pct?: number;
  /** Where the gust blows to, 0 is +x. */
  gust_dir_deg?: number;
  gust_start_s?: number;
  gust_len_s?: number;
  noise_cm?: number;
  drift_m?: number;
  low_z_m?: number;
  // Gripper worlds.
  friction_pct?: number;
  shake_x?: number;
  noise_pct?: number;
  slip_mm?: number;
}
export interface StressEvent {
  type: "stress";
  run: number;
  product: "drone" | "gripper";
  status: "running" | "done" | "failed";
  total: number;
  done: number;
  survived: number;
  seed: number;
  /** trained or default controller gains for the drone; design for the gripper. */
  policy: "trained" | "default" | "design";
  gains: Record<string, number>;
  weight_g: number;
  thrust_to_weight?: number;
  payload_g?: number;
  object_width_mm?: number;
  force_n?: number;
  safety_factor?: number;
  worlds: StressWorld[];
  worst: (StressWorld & { trajectory: TrajectorySample[]; hand?: [number, number][] }) | null;
  weakest: string | null;
  explanation: string;
}

export interface OmniverseEvent {
  type: "omniverse";
  mode: "test" | "train";
  status: "running" | "done" | "recorded";
  source: "live" | "recorded";
  stage?: "export" | "upload" | "execute" | "download";
  engine?: string;
  detail: string;
  requested: Record<string, string | number>;
  parameters?: Record<string, string | number>;
  metrics: Record<string, number>;
  curve: [number, number][];
  video_url: string | null;
  json_url: string | null;
  passed?: boolean;
  product_tested?: boolean;
}

export interface CadNode {
  id: string;
  label: string;
  children: CadNode[];
}
export interface CadParam {
  value: number;
  min: number;
  max: number;
  unit: string;
  /** Display name; an assembly names the part, e.g. "Base plate · depth". */
  label?: string;
}
/** A CAD part as FreeCAD or CadQuery built it. File URLs are served by the backend under /files/. */
export interface CadEvent {
  type: "cad";
  source: "freecad" | "cadquery";
  tree: CadNode[];
  params: Record<string, CadParam>;
  glb_url: string | null;
  stl_url: string | null;
  step_url: string | null;
  view_png_url: string | null;
  /** A generated part: the FreeCAD script that built it (cad_part). */
  script_url?: string | null;
  part?: {
    name: string;
    material: string;
    mass_g: number;
    bbox_mm: number[];
    attempts: number;
    /** true when Claude wrote the script, false for a library template. */
    generated: boolean;
  };
  /** true for a whole assembled product: `part` then sums its printed parts. */
  assembly?: boolean;
}
/** One Blender render. */
export interface RenderEvent {
  type: "render";
  source: "blender";
  png_url: string;
  label: string;
}

/** One sentence from a Jamie meeting: who said it, when, and where. */
export interface Quote {
  text: string;
  speaker: string;
  time: string;
  meeting_id: string;
  meeting_title: string;
}
export interface MeetingEvent {
  type: "meeting";
  id: string;
  title: string;
  kind: "kickoff" | "review" | "archive";
  date: string;
  time: string;
  /** done: recorded and read; live: running right now; next: planned. */
  status: "done" | "live" | "next";
  /** The drone version built from this meeting, or null. */
  version: number | null;
  tags: string[];
  /** A live Jamie meeting that took over a planned timeline station names that station here. */
  replaces?: string;
}
/** Starts every stream and follows every server reset: drop all session state. */
export interface ResetEvent {
  type: "reset";
}
/** Sent once per connection after the backlog: events before it are history, not news. */
export interface ReplayedEvent {
  type: "replayed";
}
export interface VersionDiff {
  key: string;
  label: string;
  before: number | string;
  after: number | string;
  unit: string;
}
export interface VersionEvent {
  type: "version";
  n: number;
  meeting_id: string;
  meeting_title: string;
  weight_g: number;
  thrust_to_weight: number;
  flight_time_min: number;
  price_eur: number;
  sim: "pass" | "fail" | null;
  /** Category to part name. */
  parts: Record<string, string>;
  diff: VersionDiff[];
  summary: string;
  /** The note AnyBuild wrote back to the meeting in Jamie. */
  note?: string;
}
export interface PartWarning extends Quote {
  note: string;
}
export interface PartEvent {
  type: "part";
  category: string;
  id: string;
  name: string;
  why: Quote | null;
  /** The agent's own reason in one line. */
  reason: string;
  warnings: PartWarning[];
  /** A candidate that was weighed but not chosen; it only brings its warnings. */
  considered?: boolean;
  mass_g?: number;
  /** Length, width, height of a battery pack. */
  size_mm?: [number, number, number] | null;
  diameter_mm?: number | null;
}
export interface QuestionEvent {
  type: "question";
  id: string;
  text: string;
  options: { id: string; label: string }[];
  default_id: string;
  timeout_s: number;
  status: "open" | "answered";
  answer_id: string | null;
}
export interface TaskItem {
  id: string;
  title: string;
  assignee: string;
  due: string;
  done: boolean;
  part_category: string;
}
/** One agent on the bench: the orchestrator, or a sub-agent it delegated a bounded job to. */
export interface AgentRunEvent {
  type: "agent";
  id: string;
  role: "orchestrator" | "cad" | "parts" | "checks" | "pricing";
  label: string;
  model: string;
  model_label: string;
  effort: string;
  task: string;
  status: "running" | "done" | "error";
  /** Model calls so far. */
  rounds: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cost_usd: number;
  /** What it is doing now, or its report when done. */
  summary: string;
}
export interface TasksEvent {
  type: "tasks";
  meeting_id: string;
  items: TaskItem[];
  /** true when the tasks live in Jamie, false for the local outbox. */
  live: boolean;
}

export type AgentEvent =
  | StepEvent
  | ChatEvent
  | ToolEvent
  | RequirementEvent
  | MetricsEvent
  | SimEvent
  | DrawEvent
  | BomEvent
  | MascotEvent
  | JamieEvent
  | PointEvent
  | TrainingEvent
  | OmniverseEvent
  | StressEvent
  | CadEvent
  | RenderEvent
  | MeetingEvent
  | VersionEvent
  | PartEvent
  | QuestionEvent
  | TasksEvent
  | ProductEvent
  | AgentRunEvent
  | ResetEvent
  | ReplayedEvent;

const EVENT_TYPES = new Set<AgentEvent["type"]>([
  "step",
  "chat",
  "tool",
  "requirement",
  "metrics",
  "sim",
  "draw",
  "bom",
  "mascot",
  "jamie",
  "point",
  "training",
  "omniverse",
  "stress",
  "cad",
  "render",
  "meeting",
  "version",
  "part",
  "question",
  "tasks",
  "product",
  "agent",
  "reset",
  "replayed",
]);

/** Parses one SSE data payload; returns null for anything that is not a contract event. */
export function parseEvent(raw: string): AgentEvent | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const type = (value as { type?: unknown }).type;
  if (typeof type !== "string" || !EVENT_TYPES.has(type as AgentEvent["type"])) return null;
  return value as AgentEvent;
}
