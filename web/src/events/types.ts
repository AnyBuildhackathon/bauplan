// The SSE contract shared with the agent backend (agent/, documented in docs/events.md).
// Every message on GET /api/events is one JSON object with a `type` field.
import type { TrialEvent } from "./trial";

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
  /** A spoken line: the person's turn heard by Reson8 or the browser, or what Mechanic said aloud. */
  voice?: boolean;
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
  /** Who it comes from and when: "You" with the words from the request, or "Mechanic" for a proposal. */
  speaker?: string;
  time?: string;
  /** user: the limit is in what the user typed; proposed: Mechanic proposed it (absent in older recordings). */
  source?: "user" | "proposed";
  /** The earlier wording when a later message changed this requirement. */
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
  /** Drone flight performance from the parts' specs (physics_calc); all estimates. */
  top_speed_mps?: number;
  top_speed_kmh?: number;
  accel_mps2?: number;
  /** Seconds from a hover to 90 % of the top speed. */
  time_to_90pct_s?: number;
  climb_rate_mps?: number;
  /** Sustained level turn at half the top speed. */
  turn_rate_dps?: number;
  turn_radius_m?: number;
  /** A 180 degree roll from hover, two motors at full and two cut back. */
  flip_time_s?: number;
  flight_time_full_speed_min?: number;
  flight_time_full_throttle_min?: number;
  /** True: the performance numbers are model estimates, not measurements. */
  estimate?: boolean;
  /** Chosen parts whose numbers are estimates, not stated on their pages: "Part: field, field". */
  estimated_inputs?: string[];
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
/** One dimension or label read off a sketch. */
export interface SketchReading {
  label: string;
  value: string;
  unit?: string;
  confidence?: "high" | "medium" | "low";
}
/** The photo of a hand sketch a build started from, and what Claude vision read off it. */
export interface SketchEvent {
  type: "sketch";
  /** "sketch-1" */
  id: string;
  /** The stored photo, served by the backend under /files/. */
  url: string;
  status: "reading" | "read" | "failed";
  note?: string;
  summary?: string;
  read?: SketchReading[];
  unreadable?: string[];
  /** The spec id the sketch became, once read. */
  product?: string;
  /** "claude" for a live vision read, "recorded" for the sample's recorded reading. */
  source?: "claude" | "recorded";
  error?: string;
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
  /**
   * Where the price comes from: "live" when a web search found a shop price, "catalog" (drone and gripper)
   * or "sample" (spec products) for the catalog sample, "estimated" for an estimate. Older recordings omit it.
   */
  price_source?: "live" | "catalog" | "sample" | "estimated";
  /** Shop price per piece in its own currency (live lines only). */
  price?: number;
  currency?: string;
  availability?: "in_stock" | "out_of_stock" | "unknown";
  pack_qty?: number;
  catalog_price_eur?: number;
  checked_at?: string;
  /** The spec part this line belongs to (any product); `hw-…` for a line of standard parts. */
  category?: string;
  /** A line of standard parts (screws, nuts, washers, heat-set inserts) the printed parts hold. */
  role?: "hardware";
  /** Its standard ("ISO 4762"), or null for an insert; its thread ("M3") and length in mm (null for nuts and washers). */
  standard?: string | null;
  size?: string;
  length_mm?: number | null;
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
  /** Optional pre-rendered audio of `say`. */
  voice?: string;
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
  gains?: FirmwareGains;
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
  /** queued: the drone's worlds wait for a dashboard tab to fly them in the browser. */
  status: "queued" | "running" | "done" | "failed";
  /** The drone's worlds fly in the browser: the job a tab claims, and the spec it builds the MJCF from. */
  source?: "browser";
  job_id?: string;
  spec?: unknown;
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
  /** Trained Betaflight gains for the firmware, read from a live `done` training; no Isaac job emits them yet. */
  gains?: Partial<Record<"roll" | "pitch" | "yaw", Partial<{ p: number; i: number; d: number; f: number }>>>;
  video_url: string | null;
  json_url: string | null;
  passed?: boolean;
  product_tested?: boolean;
}

export interface CadNode {
  id: string;
  label: string;
  children: CadNode[];
  /** The GLB nodes the row stands for, when it names them: a standard part's row lists its pieces. */
  nodes?: string[];
}
export interface CadParam {
  value: number;
  min: number;
  max: number;
  unit: string;
  /** Display name; an assembly names the part, e.g. "Base plate · depth". */
  label?: string;
}
/** A CAD part as FreeCAD, CadQuery or SolidCraft built it. File URLs are served by the backend under /files/. */
export interface CadEvent {
  type: "cad";
  source: "freecad" | "cadquery" | "solidcraft";
  tree: CadNode[];
  params: Record<string, CadParam>;
  glb_url: string | null;
  stl_url: string | null;
  step_url: string | null;
  view_png_url: string | null;
  /** A generated part: the script that built it, FreeCAD Python (cad_part) or SolidCraft's command script (solidcraft_part). */
  script_url?: string | null;
  /** A SolidCraft design (solidcraft_part): the .solidcraft file, which opens in SolidCraft with its timeline. */
  design_url?: string | null;
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
  /** An assembled product: one row per GLB node, with its spec part, assembly group and mass. */
  bodies?: CadBody[];
  /** The GLB nodes that show a bought part's own 3D model instead of a simple solid. */
  part_models?: PartModelRow[];
}
/** Which 3D model a GLB node shows: official, a look-alike from measured numbers, or approximate. */
export interface PartModelRow {
  node: string;
  part_id: string;
  part_name: string;
  model_kind: "official" | "look-alike" | "approximate";
  /** The numbers no real source gave, drawn in proportion (approximate models only). */
  model_missing: string[];
  model_source: string | null;
}
export interface CadBody {
  name: string;
  /** The spec part; for a standard part (`hardware`) the `category` of its bill-of-materials line. */
  part_id: string;
  part_name: string;
  kind: "printed" | "bought" | "external" | "hardware";
  group: string | null;
  mass_g: number;
}
/** Mechanic operates a dashboard control: the pointer flies to `[data-control~=control]`, then it acts. */
export interface UiEvent {
  type: "ui";
  id: string;
  control: string;
  say: string;
  open?: boolean;
  value?: number | boolean;
  part?: string;
  versions?: [number, number] | null;
}
/** One Blender render. */
export interface RenderEvent {
  type: "render";
  source: "blender";
  png_url: string;
  label: string;
}

/** The words a choice rests on: the user's request, or Mechanic's proposal. */
export interface Quote {
  text: string;
  speaker: string;
  time: string;
}
/** The bench holds a remix of a community project; publishing it links back to that original. */
export interface RemixEvent {
  type: "remix";
  /** The community entry id it was opened from. */
  id: string;
  title: string;
  author: string;
}
/** Starts every stream and follows every server reset: drop all session state. */
export interface ResetEvent {
  type: "reset";
  /** A reopened saved chat (POST /api/history/{id}/open): its backlog follows, up to `replayed`. */
  replay?: boolean;
}
/** The build on the bench: `pausing` and `stopping` wait for the tool that runs now to finish. */
export type RunStatus = "idle" | "running" | "pausing" | "paused" | "stopping";
export interface RunEvent {
  type: "run";
  status: RunStatus;
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
  weight_g: number;
  thrust_to_weight: number;
  flight_time_min: number;
  price_eur: number;
  sim: "pass" | "fail" | null;
  /** Category to part name. */
  parts: Record<string, string>;
  diff: VersionDiff[];
  summary: string;
  /** What started the rebuild. */
  trigger?: VersionTrigger;
  product?: "drone" | "gripper" | "generic";
  /** One line naming the trigger: the chat request, the library item, the restored version. */
  label?: string;
  /** The metric cards of a non-drone product as the panel showed them. */
  cards?: MetricCard[];
  requirements?: { id: string; text: string; met: boolean | null; detail: string }[];
  /** CAD parameters by name: frame params for the drone, `{part_id}.{param}` for a product. */
  params?: Record<string, number>;
  /** A product's part id to its body name in the GLB, so a compare can light the changed bodies. */
  nodes?: Record<string, string>;
  /** Copies of the model and render made for this version, so an old one can still be drawn. */
  files?: { glb_url: string | null; render_url: string | null };
  restored_from?: number | null;
  /** ISO time the version was committed. */
  at?: string;
  /** What independent judges said about this exact design, next to its own test in `sim`; a verdict arrives after the commit. */
  verdicts?: VersionVerdict[];
}
/** One independent judge's verdict in a version's book (docs/events.md, version). */
export interface VersionVerdict {
  /** The judge: robouse (robouse_trial). */
  judge: string;
  /** "Robo Use", or "Robo Use, Claude Code" when Claude Code drove the gripper. */
  label: string;
  trial_id: string;
  harness: string;
  verdict: "pass" | "fail" | "invalid" | "refused";
  /** 1 or 0; null when the gripper cannot take the object at all. */
  reward: number | null;
  /** done: it ran on this build; recorded: recorded earlier on this same design; failed: the task was refused. */
  status: "done" | "recorded" | "failed";
  summary: string;
  at?: string;
}
export type VersionTrigger = "chat" | "library" | "check_failed" | "restore";
/** One mission test (simulate_mission) of the drone built from its parts, with its replay. */
export type MissionId = "speed_run" | "turn" | "hold" | "chase";
export interface MissionEvent {
  type: "mission";
  run: number;
  mission: MissionId;
  label: string;
  result: "pass" | "fail";
  summary: string;
  /** What limits the build in this mission, so a fix has a direction. */
  why: string;
  requirement_id: string;
  limit: number;
  limit_kind: "min" | "max";
  unit: string;
  /** The number judged against the limit; null when it never got one (no fly caught). */
  value: number | null;
  metrics: Record<string, number | number[] | (number | null)[] | boolean | null>;
  /** [t, value] of the mission's own curve: speed m/s, heading degrees, error cm or distance cm. */
  series: [number, number][];
  /** [t, x, y, z, qw, qx, qy, qz] of the drone, metres, z up. */
  poses: number[][];
  /** chase: [t, x, y, z] of the fly. */
  target?: number[][];
  /** hold: [t, wx, wy, wz] of the air, m/s. */
  wind?: number[][];
  parts: Record<string, string | null>;
  mass_g: number;
  /** Who flew it: the reference controller (the hardware check) or the trained gains (train_controller). */
  controller?: "reference" | "trained";
  /** A trained run: the reference controller's result on the same build, for the comparison. */
  reference?: { value: number | null; result: "pass" | "fail"; summary: string } | null;
  /** Estimated part numbers this result rests on, and the camera defaults a chase used. */
  estimated_inputs?: string[];
}
/** The drone's dimensioned parts (drone_geometry.py): what the model, the sim and the BOM share. */
export interface GeometryEvent {
  type: "geometry";
  arm_length_mm: number;
  thickness_mm: number;
  motor: { id: string | null; bell_diameter_mm: number; height_mm: number; stator_diameter_mm: number; stator_height_mm: number; shaft_mm: number | null; size: string | null };
  propeller: { id: string | null; diameter_mm: number; pitch_in: number | null; blades: number; z_mm: number };
  battery: { id: string | null; size_mm: [number, number, number] };
  flight_controller: { id: string | null; mount_mm: number; board_mm: number };
  prop_clearance_mm: number;
  total_mass_g: number;
  /** Fields a part did not carry, filled from the reference build. */
  assumed: string[];
}
export interface PartEvent {
  type: "part";
  category: string;
  id: string;
  name: string;
  why: Quote | null;
  /** The agent's own reason in one line. */
  reason: string;
  mass_g?: number;
  /** Length, width, height of a battery pack. */
  size_mm?: [number, number, number] | null;
  diameter_mm?: number | null;
  /** curated: from the parts library; web: found and validated on the web during this build. */
  provenance?: "curated" | "web" | "catalog" | "estimate";
  /** The product page its specs come from. */
  source_url?: string | null;
  /** How its numbers are known: stated on its pages (sourced), read off a drawing or computed (derived),
   * estimated (exploration mode only), or a catalog sample. */
  confidence?: Confidence;
  /** The fields that are estimates. */
  estimated?: string[];
  /** Per field: its confidence, the page it came from, or the basis of an estimate. */
  fields?: Record<string, { confidence: Confidence; source?: string; basis?: string }>;
  /** Every page the part's numbers come from: shop, maker page, datasheet, distributor listing. */
  sources?: { url: string; kind?: string; distributor?: string }[];
}
export type Confidence = "sourced" | "derived" | "estimated" | "catalog";
export interface QuestionEvent {
  type: "question";
  id: string;
  text: string;
  options: { id: string; label: string }[];
  default_id: string;
  timeout_s: number;
  status: "open" | "answered";
  answer_id: string | null;
  /** Optional pre-rendered audio of the question's last sentence. */
  voice?: string;
}
/** One agent on the bench: the orchestrator, or a sub-agent it delegated a bounded job to. */
export interface AgentRunEvent {
  type: "agent";
  id: string;
  role: "orchestrator" | "cad" | "parts" | "checks" | "pricing" | "sketch" | "optimizer";
  label: string;
  model: string;
  model_label: string;
  effort: string;
  task: string;
  /** `queued` waits for another job of the same fan-out to finish first. */
  status: "queued" | "running" | "done" | "error";
  /** Model calls so far. */
  rounds: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cost_usd: number;
  /** "subscription" when it ran on the local Claude Code login: the plan pays, cost_usd is 0. Older backends omit it. */
  billing?: "api" | "subscription";
  /** What it is doing now, or its report when done. */
  summary: string;
  /** Server time in epoch seconds when this report was sent. Older backends omit it and the fields below. */
  sent_at?: number;
  /** The orchestrator run that delegated this job; null for the orchestrator. */
  parent?: string | null;
  /** Server time in epoch seconds when it started working, null while queued. */
  started_at?: number | null;
  /** Server time in epoch seconds when it finished, null while it works. */
  ended_at?: number | null;
  /** The tool it runs right now (`freecad`, `blender_render`, `simulate_assembly`, …), or null. */
  tool?: string | null;
  /** Its tool calls so far, newest last, at most 30. */
  calls?: AgentToolCall[];
}
export interface AgentToolCall {
  tool: string;
  ok: boolean;
  detail: string;
}

export interface BuildGuideStep {
  n: number;
  title: string;
  instructions: string;
  /** Scene part names to highlight, from the "Scene targets" list in docs/events.md. */
  parts: string[];
  tools: string[];
  minutes: number;
  /** Bill-of-materials names of those parts. */
  items: string[];
}
export interface BuildGuideEvent {
  type: "build_guide";
  version: number;
  steps: BuildGuideStep[];
  total_minutes: number;
}
export interface PrintWarning {
  /** material: the user's printer cannot print it or it is not among their spools; warp: warping risk on that printer. */
  kind: "overhang" | "thin_wall" | "bed_size" | "material" | "warp";
  text: string;
}
/** One printed part of the print plan, for a single piece. */
export interface PrintPart {
  id: string;
  name: string;
  material: string;
  qty: number;
  orientation: "flat" | "upright" | "as_modeled";
  size_mm: [number, number, number];
  volume_cm3: number;
  time_min: number;
  filament_g: number;
  filament_m: number;
  cost_eur: number;
  warnings: PrintWarning[];
  stl_url: string;
  /** Empty without a slicer: an estimate has no G-code. */
  gcode_url: string;
  source: "slicer" | "estimate";
  slicer_error?: string;
  /** Overhangs need supports in this pose; support_g is the support plastic in the grams. */
  supports?: boolean;
  support_g?: number;
  /** The thinnest wall the surface check measured, and the axis of the part that needs clearly less support up; null without one. */
  wall_mm?: number | null;
  better_up?: string | null;
}
/** Print plan from print_prep: a headless slicer when installed, else an estimate from the mesh. */
export interface PrintEvent {
  type: "print";
  source: "slicer" | "estimate";
  slicer: string;
  profile: { printer: string; nozzle_mm: number; layer_height_mm: number; infill_pct: number; walls: number; bed_mm: number[]; enclosure?: boolean | null };
  /** The user's own printer when one is set, else null (a generic 220 mm bed). */
  printer?: string | null;
  parts: PrintPart[];
  totals: { parts: number; time_min: number; filament_g: number; cost_eur: number; warnings: number; support_g?: number };
}
/** One load case of a FEM run. */
export interface FemCase {
  name: string;
  force_n: number[];
  max_von_mises_mpa: number;
  max_across_layers_mpa: number;
  max_deflection_mm: number;
  safety: number;
  safety_in_plane: number;
  safety_across_layers: number;
  governs: "layers" | "in-plane";
  hot_spot_mm: number[];
}
/** FEM of one printed part on its real shape (gmsh + CalculiX), the stress-coloured model and the verdict. */
export interface FemEvent {
  type: "fem";
  part_id: string;
  part_name: string;
  material: string;
  /** Plastic share of the section (walls solid, core at infill_pct) that scales modulus and strength. */
  fill: number;
  infill_pct: number;
  walls: number;
  modulus_mpa: number;
  strength_mpa: number;
  z_strength_mpa: number;
  safety: number;
  max_von_mises_mpa: number;
  max_deflection_mm: number;
  governing: string;
  governs: "layers" | "in-plane";
  limit: number;
  result: "pass" | "fail";
  cases: FemCase[];
  /** Where it is held and what loads it, one line each. */
  loads: string[];
  /** Vertex-coloured surface of the governing case: blue no stress, red at scale_mpa (the printed strength). */
  glb_url: string;
  scale_mpa: number;
  nodes: number;
  elements: number;
  solver: string;
  printer: string | null;
  hot_spot_mm: number[];
  /** The FEM's own checks in one line: held against every motion, reactions balancing the loads, the peak on a finer mesh. */
  self_check?: string;
  /** What to tell with the safety factor: a peak that depends on the mesh, load straight into the support, a loose body left out. */
  notes?: string[];
}
export type AnalysisCheck = "overhang" | "thickness" | "clearance";
/** One check of the surface checks: its limit, unit, which side is critical and the GLB attribute with its values. */
export interface AnalysisCheckInfo {
  label: string;
  limit: number;
  unit: "deg" | "mm";
  critical: "above" | "below";
  attribute: string;
  /** Overhang: the value of a face on the bed. */
  bed?: number;
  /** Thickness: the value where no ray came out. */
  unread?: number;
  /** Clearance: how far it looks (that value means as far or farther), and how close counts as touching. */
  range?: number;
  touch?: number;
}
/** Critical samples that share an edge; count says how many spots of the same area, size and worst value. */
export interface AnalysisSpot {
  count: number;
  area_mm2: number;
  size_mm: number[];
  worst: number;
  at_mm: number[];
  centers_mm: number[][];
  /** Clearance: the other part the spot is close to. */
  with?: string | null;
  /** Spots that need no fix: smaller than one sample, the taper of a sharp edge, the wedge where two parts meet. */
  speck?: boolean;
  taper?: boolean;
  contact?: boolean;
}
export interface AnalysisSummary {
  min: number | null;
  max: number | null;
  /** Everything past the limit, as the colours show it. */
  critical_mm2: number;
  /** What needs a fix: without specks, the tapers of sharp edges and the wedges where parts meet at an angle. */
  finding_mm2: number;
  worst?: { value: number; at_mm: number[]; with?: string | null };
  spots: AnalysisSpot[];
  spot_count: number;
  overlap_mm2?: number;
  unread_mm2?: number;
  up?: number[];
  by_axis_mm2?: Record<string, number>;
  better?: { axis: string; up: number[]; critical_mm2: number; pose: string | null } | null;
}
export interface AnalysisPart {
  /** The model GLB's node the layer lies over. */
  node: string;
  part_id: string | null;
  name: string;
  pose: string;
  samples: number;
  spacing_mm: number;
  overhang?: AnalysisSummary;
  thickness?: AnalysisSummary;
  clearance?: AnalysisSummary;
}
/** The surface checks of the printed parts (surface_check, print_prep): numbers, places and the colour layer's GLB. */
export interface AnalysisEvent {
  type: "analysis";
  source: "surface_check" | "print_prep";
  /** The build it ran on: the model's glb_url carries the same ?build=. */
  build: number;
  glb_url: string;
  frame: string;
  checks: Partial<Record<AnalysisCheck, AnalysisCheckInfo>>;
  parts: AnalysisPart[];
  result: "pass" | "fail";
  summary: string;
  seconds?: number;
}
/** A printer profile from the backend's store, with the maker's spec page. */
export interface PrinterProfile {
  id: string;
  name: string;
  maker: string;
  bed_mm: number[];
  nozzle_mm: number;
  max_hotend_c: number;
  max_bed_c: number;
  enclosure: boolean;
  materials: string[];
  source_url: string;
}
/** The user's printer as the backend has it: the profile, their filaments, which of them it prints. */
export interface UserPrinter extends Omit<PrinterProfile, "id"> {
  model: string;
  filaments: string[];
  printable: string[];
  not_printable: string[];
}
export interface WiringRow {
  component: string;
  connects_to: string;
  pin: string;
  wire: string;
  note: string;
}
export type FirmwareGains = Record<"roll" | "pitch" | "yaw", { p: number; i: number; d: number; f: number }>;
/** Firmware for the built product: a Betaflight CLI file or an Arduino sketch, plus the wiring table. */
export interface FirmwareEvent {
  type: "firmware";
  kind: "betaflight" | "arduino";
  product: string;
  filename: string;
  url: string;
  /** The whole file, so the download does not need a second request. */
  content: string;
  gains: FirmwareGains | null;
  /** Isaac Lab training, then the browser training, then the Betaflight defaults; `none` for an Arduino sketch. */
  gains_source: "isaac" | "browser" | "defaults" | "none";
  explanation: string;
  wiring: WiringRow[];
}

export interface ElectronicsBlock {
  id: string;
  name: string;
  role: "supply" | "connector" | "switch" | "regulator" | "controller" | "driver" | "inline" | "load" | "sensor";
  col: number;
  row: number;
  voltage_v: number | null;
  rating: string;
  qty: number;
}
export interface ElectronicsWire {
  id: string;
  from: string;
  to: string;
  from_pin: string;
  to_pin: string;
  kind: "power" | "phase" | "signal";
  voltage_v: number | null;
  current_a: number | null;
  color: "3v3" | "1s" | "5v" | "high" | "phase" | "signal" | "power";
  label: string;
}
export interface ElectronicsLoad {
  name: string;
  voltage_v: number;
  power_w: number;
  duty: number;
  peak_w: number;
  average_w: number;
  current_a: number;
}
/** Wiring diagram and power budget from the chosen parts (`electronics_plan`). */
export interface ElectronicsEvent {
  type: "electronics";
  product: string;
  ok: boolean;
  summary: string;
  explanation?: string;
  blocks: ElectronicsBlock[];
  wires: ElectronicsWire[];
  budget: {
    supply: string;
    supply_voltage_v: number;
    supply_limit_a: number;
    average_a: number;
    peak_a: number;
    average_w: number;
    peak_w: number;
    headroom: number;
    runtime_h?: number;
    loads: ElectronicsLoad[];
  };
  warnings: { part: string; text: string; severity: "fail" | "warn" }[];
  gaps: string[];
  wiring: WiringRow[];
}
export type SafetySeverity = "danger" | "warning" | "info";
/** One safety or regulatory note: why it fires, the rule or source it rests on, and a fix the agent can apply. */
export interface SafetyFinding {
  id: string;
  severity: SafetySeverity;
  title: string;
  reason: string;
  rule: string;
  fix: string;
  /** `rule` from the fixed rule set, `claude` from the agent's own reasoning. */
  source: "rule" | "claude";
}
/** The safety check before ordering parts, findings sorted danger first. Hints, not legal advice. */
export interface SafetyEvent {
  type: "safety";
  product: string;
  label: string;
  findings: SafetyFinding[];
  summary: string;
  disclaimer: string;
}

/**
 * Mechanic's spoken line, streamed live: `delta` pieces while the fast model writes it,
 * then `done` with the whole `text`. `kind` is `reply` (an answer to the person) or
 * `update` (a build milestone). Never replayed on reconnect.
 */
/** Learning mode: one decision explained with its physics (POST /api/explain). */
export interface ExplainEvent {
  type: "explain";
  key: string;
  kind: "part" | "swap" | "requirement" | "sim" | "param";
  target_id: string;
  title: string;
  text: string;
  formula: string;
  numbers: { label: string; value: number | string; unit: string }[];
  source: "claude" | "template";
  model: string | null;
  /** Asked for by a live event, so it shows as a chat card; a "Why?" click shows it in place. */
  chat?: boolean;
}

export type AgentEvent =
  | UiEvent
  | StepEvent
  | ChatEvent
  | ToolEvent
  | RequirementEvent
  | MetricsEvent
  | SimEvent
  | MissionEvent
  | GeometryEvent
  | DrawEvent
  | BomEvent
  | MascotEvent
  | PointEvent
  | TrainingEvent
  | OmniverseEvent
  | StressEvent
  | TrialEvent
  | CadEvent
  | RenderEvent
  | VersionEvent
  | PartEvent
  | QuestionEvent
  | ProductEvent
  | SketchEvent
  | RemixEvent
  | BuildGuideEvent
  | PrintEvent
  | FemEvent
  | AnalysisEvent
  | FirmwareEvent
  | ElectronicsEvent
  | SafetyEvent
  | AgentRunEvent
  | ExplainEvent
  | OptimizeEvent
  | RunEvent
  | ResetEvent
  | ReplayedEvent;

const EVENT_TYPES = new Set<AgentEvent["type"]>([
  "ui",
  "step",
  "chat",
  "tool",
  "requirement",
  "metrics",
  "sim",
  "mission",
  "geometry",
  "draw",
  "bom",
  "mascot",
  "point",
  "training",
  "omniverse",
  "stress",
  "trial",
  "cad",
  "render",
  "version",
  "part",
  "question",
  "product",
  "sketch",
  "remix",
  "build_guide",
  "print",
  "fem",
  "analysis",
  "firmware",
  "electronics",
  "safety",
  "agent",
  "explain",
  "optimize",
  "reset",
  "run",
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

/** One variant the design optimizer checked: its parts, its numbers and every check. */
export interface OptimizeVariant {
  id: string;
  label: string;
  reason: string;
  agent: string;
  battery: string;
  battery_id: string;
  params: { arm_length_mm: number; thickness_mm: number };
  frame_g: number;
  weight_g: number;
  thrust_to_weight: number;
  flight_time_min: number;
  price_eur: number;
  /** Arm stiffness relative to the current build (1 = now). */
  arm_stiffness: number;
  warnings: string[];
  checks: { id: string; label: string; pass: boolean; detail: string }[];
  feasible: boolean;
  pareto: boolean;
}

export type OptimizeGoal = "lighter" | "cheaper" | "longer_runtime" | "stronger";
export type OptimizeNumber = "weight_g" | "flight_time_min" | "price_eur" | "thrust_to_weight" | "arm_stiffness";

/** The design optimizer explored variants; sent running, done, and again once a variant is built. */
export interface OptimizeEvent {
  type: "optimize";
  id: string;
  status: "running" | "done";
  goals: OptimizeGoal[];
  keep: Record<string, number>;
  axes: { x: OptimizeNumber; y: OptimizeNumber; color: OptimizeNumber };
  /** The current build through the same checks, or null while running. */
  baseline: (Omit<OptimizeVariant, "id" | "reason" | "agent" | "pareto"> & { label: string }) | null;
  variants: OptimizeVariant[];
  recommended: string | null;
  /** The variant built as a version, and that version's number. */
  applied: string | null;
  version: number | null;
}
