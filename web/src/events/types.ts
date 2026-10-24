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
  /** "grip": a gripper lifts and shakes an object; trajectory z is the object's rise, `hand` the hand's. */
  kind?: "hover" | "grip";
  hand?: [number, number][];
  object_width_mm?: number;
  payload_g?: number;
  force_n?: number;
  slip_mm?: number;
}
/** Which product this session builds. */
export interface ProductEvent {
  type: "product";
  id: "drone" | "gripper";
  label: string;
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
  /** "live" when a web search found a shop price, else the catalog sample. Older recordings omit it. */
  price_source?: "live" | "catalog";
  /** Shop price per piece in its own currency (live lines only). */
  price?: number;
  currency?: string;
  availability?: "in_stock" | "out_of_stock" | "unknown";
  pack_qty?: number;
  catalog_price_eur?: number;
  checked_at?: string;
}
export interface BomEvent {
  type: "bom";
  items: BomItem[];
  total_eur: number;
  stl_path: string;
  /** "searching" while live prices load, then "live" or "catalog". */
  prices?: "searching" | "live" | "catalog";
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
  | CadEvent
  | RenderEvent
  | MeetingEvent
  | VersionEvent
  | PartEvent
  | QuestionEvent
  | TasksEvent
  | ProductEvent
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
  "cad",
  "render",
  "meeting",
  "version",
  "part",
  "question",
  "tasks",
  "product",
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
