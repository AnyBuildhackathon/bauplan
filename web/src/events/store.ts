// The session store: folds the SSE event stream (docs/events.md, types in events/types.ts) into
// the UI state every view reads. `apply` is a reducer over one event at a time, so a client
// that connects late replays the backlog onto an empty state and ends up exactly where a live
// client is; `reset` empties it. Every event is also appended to `log`, which the camera
// director, the agent graph, the meeting timeline and the training view read in order.
// Nothing here calls the backend: user actions are posted through events/source.ts and
// lib/api.ts, and their effect comes back as events.
import { create } from "zustand";
import {
  STEP_IDS,
  type AgentEvent,
  type AgentRunEvent,
  type BomEvent,
  type BuildGuideEvent,
  type PrintEvent,
  type ExplainEvent,
  type CadEvent,
  type DrawEvent,
  type FirmwareEvent,
  type ElectronicsEvent,
  type RenderEvent,
  type MascotState,
  type MeetingEvent,
  type MetricsEvent,
  type PartEvent,
  type PartWarning,
  type ProductEvent,
  type SketchEvent,
  type QuestionEvent,
  type RemixEvent,
  type RunStatus,
  type SafetyEvent,
  type TasksEvent,
  type VersionEvent,
  type RequirementEvent,
  type SimEvent,
  type StepId,
  type StepStatus,
  type StressEvent,
  type ToolStatus,
  type TrainingEvent,
  type OmniverseEvent,
  type OptimizeEvent,
  type UiEvent,
} from "./types";

export const STEP_LABELS: Record<StepId, string> = {
  meeting: "Meeting",
  teile: "Parts",
  cad: "CAD",
  render: "Render",
  simulation: "Simulation",
  training: "Training",
  stueckliste: "BOM",
};

/** The fixed tool roster shown in the status card; unknown tool names are appended. */
export const TOOL_NAMES = [
  "Claude",
  "FreeCAD",
  "CadQuery",
  "MuJoCo",
  "Blender",
  "Isaac Sim",
  "Isaac Lab",
  "RunPod",
  "Jamie",
  "Reson8",
] as const;

export interface LoggedEvent {
  seq: number;
  at: number;
  ev: AgentEvent;
  /** Replayed in bulk (backlog or seek), not live. */
  instant?: boolean;
}

export interface StepState {
  id: StepId;
  status: StepStatus;
  label: string;
  at: number;
  seq: number;
}

export interface ToolState {
  name: string;
  status: ToolStatus | "unknown";
  detail: string;
  at: number;
}

export type Phase = "running" | "ok" | "error";

/** One key number on a results card, frozen when its bill of materials arrived. */
export interface ResultNumber {
  key: string;
  label: string;
  value: number;
  unit: string;
  digits: number;
  /** data-target of the number, so Mechanic can point at it. */
  target: string;
}

const DRONE_TARGETS: Record<string, string> = {
  weight_g: "metric:weight weight weight_g gewicht",
  flight_time_min: "metric:flight_time flight_time flight_time_min flugzeit",
  price_eur: "metric:price price price_eur preis budget",
};

/** The three key numbers for a results card: the product's own cards, or weight, flight time and price for the drone. */
function resultNumbers(metrics: MetricsEvent | null, total: number): ResultNumber[] {
  if (metrics?.cards?.length) {
    return metrics.cards
      .filter((c) => !c.pending)
      .slice(0, 3)
      .map((c) => ({
        key: c.key,
        label: c.label,
        value: c.key === "cost_eur" ? total : c.value,
        unit: c.unit,
        digits: c.digits,
        target: `metric:${c.key} ${c.key}`,
      }));
  }
  const price = { key: "price_eur", label: "Price", value: total, unit: "€", digits: 2, target: DRONE_TARGETS.price_eur };
  if (!metrics) return [price];
  return [
    { key: "weight_g", label: "Weight", value: metrics.weight_g, unit: "g", digits: 1, target: DRONE_TARGETS.weight_g },
    { key: "flight_time_min", label: "Flight time", value: metrics.flight_time_min, unit: "min", digits: 1, target: DRONE_TARGETS.flight_time_min },
    price,
  ];
}

export type ChatItem =
  | { kind: "msg"; id: string; seq: number; at: number; role: "user" | "agent"; text: string; local?: boolean; voice?: boolean }
  | { kind: "tool"; id: string; seq: number; at: number; name: string; phase: Phase; detail: string; endedAt?: number; instant?: boolean }
  | { kind: "jamie"; id: string; seq: number; at: number; action: string; phase: Phase; detail: string; endedAt?: number }
  | { kind: "sim"; id: string; seq: number; at: number; run: number; result: "pass" | "fail"; summary: string }
  | { kind: "bom"; id: string; seq: number; at: number; count: number; total: number; numbers: ResultNumber[] }
  /** The one requirements card; it reads the live requirements from the store. */
  | { kind: "requirements"; id: string; seq: number; at: number }
  | { kind: "training"; id: string; seq: number; at: number; status: TrainingEvent["status"]; detail: string }
  | { kind: "warning"; id: string; seq: number; at: number; part: string; warning: PartWarning }
  | { kind: "question"; id: string; seq: number; at: number; questionId: string }
  | { kind: "version"; id: string; seq: number; at: number; n: number }
  | { kind: "agent"; id: string; seq: number; at: number; agentId: string }
  | { kind: "stress"; id: string; seq: number; at: number; run: number }
  | { kind: "print"; id: string; seq: number; at: number; plan: PrintEvent }
  | { kind: "explain"; id: string; seq: number; at: number; key: string }
  | { kind: "safety"; id: string; seq: number; at: number; safety: SafetyEvent }
  | { kind: "optimize"; id: string; seq: number; at: number; optimizeId: string };

export interface Run extends SimEvent {
  seq: number;
  at: number;
}

export interface Draw extends DrawEvent {
  id: string;
  at: number;
}

export interface Pointing {
  id: string;
  target: string;
  label: string;
  at: number;
}

export interface JamieEntry {
  id: string;
  seq: number;
  at: number;
  action: string;
  status: string;
  phase: Phase;
  detail: string;
}

export interface SessionState {
  log: LoggedEvent[];
  steps: Record<StepId, StepState>;
  tools: Record<string, ToolState>;
  chat: ChatItem[];
  requirements: RequirementEvent[];
  metrics: MetricsEvent | null;
  runs: Run[];
  draws: Draw[];
  point: Pointing | null;
  mascot: { state: MascotState; say: string; voice?: string; at: number };
  bom: BomEvent | null;
  jamie: JamieEntry[];
  training: (TrainingEvent & { at: number }) | null;
  omniverse: OmniverseEvent | null;
  /** `training` events with `source: "browser"` (MuJoCo WASM in this dashboard), kept apart from Isaac Lab. */
  browserTraining: (TrainingEvent & { at: number }) | null;
  /** Latest CAD part, and how many `cad` events arrived (a new one answers a parameter change). */
  cad: (CadEvent & { at: number; n: number }) | null;
  renders: (RenderEvent & { id: string; at: number })[];
  /** Jamie meetings in timeline order (kickoff, reviews; archive meetings are kept too). */
  meetings: MeetingEvent[];
  versions: VersionEvent[];
  /** Chosen part per category, with the Jamie quote behind it. */
  parts: Record<string, PartEvent>;
  /** Every part announced so far by name, so an older version can still be drawn. */
  partsByName: Record<string, PartEvent>;
  questions: Record<string, QuestionEvent>;
  tasks: TasksEvent | null;
  /** The orchestrator and its sub-agents by id, as they last reported. */
  agents: Record<string, AgentRunEvent & { at: number }>;
  /** The product this session builds: empty on a fresh bench, set by a `product` event or by the first drone event. */
  product: ProductEvent["id"];
  firmware: FirmwareEvent | null;
  electronics: ElectronicsEvent | null;
  productLabel: string;
  /** The hand sketch this build started from, if any. */
  sketch: SketchEvent | null;
  /** The community project this bench was opened from, or null. */
  remixedFrom: Omit<RemixEvent, "type"> | null;
  run: RunStatus;
  /** Stress tests by run number, latest event of each. */
  stress: Record<number, StressEvent & { seq: number; at: number }>;
  /** Step-by-step build guide for the latest bill of materials. */
  buildGuide: BuildGuideEvent | null;
  /** The latest print plan: time, filament, cost and warnings per printed part. */
  printPlan: PrintEvent | null;
  /** Learning-mode explanations by key, the latest of each. */
  explains: Record<string, ExplainEvent>;
  /** Design optimizer runs by id, the latest event of each. */
  optimizes: Record<string, OptimizeEvent>;
  /** The newest dashboard control Mechanic operates (lib/pilot.ts plays it). */
  ui: (UiEvent & { at: number }) | null;
  /** Reduces one contract event. `instant` marks events replayed in bulk (seek), so nothing animates for them. */
  apply: (ev: AgentEvent, opts?: { instant?: boolean }) => void;
  addLocalUserMessage: (text: string, voice?: boolean) => void;
  reset: () => void;
}

/** Event order; one step per applied event, so neighbouring events differ by 1. */
let seqCounter = 0;
let idCounter = 0;
const nextId = (prefix: string) => `${prefix}-${++idCounter}`;

export function phaseOf(status: string): Phase {
  const s = status.toLowerCase();
  if (["error", "failed", "fail", "fehler"].includes(s)) return "error";
  if (["running", "pending", "queued", "started", "läuft"].includes(s)) return "running";
  return "ok";
}

function initialSteps(): Record<StepId, StepState> {
  return Object.fromEntries(
    STEP_IDS.map((id) => [id, { id, status: "pending" as StepStatus, label: STEP_LABELS[id], at: 0, seq: 0 }]),
  ) as Record<StepId, StepState>;
}

function initialTools(): Record<string, ToolState> {
  return Object.fromEntries(TOOL_NAMES.map((name) => [name, { name, status: "unknown", detail: "", at: 0 }]));
}

/** Backend tool functions shown under the program they drive. */
const TOOL_ALIASES: Record<string, string> = {
  jamie_requirements: "Jamie",
  jamie_search: "Jamie",
  jamie_meeting: "Jamie",
  jamie_create_tasks: "Jamie",
  jamie_templates: "Jamie",
  jamie_note: "Jamie",
  cad_frame: "FreeCAD",
  cad_part: "FreeCAD",
  simulate_grip: "MuJoCo",
  catalog_search: "Parts",
  grip_calc: "Physics",
  product_brief: "Brief",
  product_spec: "Spec",
  part_pick: "Parts",
  assemble: "Assembly",
  cad_update: "FreeCAD",
  check_totals: "Analysis",
  check_tip_over: "Analysis",
  check_deflection: "Analysis",
  check_torque: "Analysis",
  check_runtime: "Analysis",
  simulate_assembly: "MuJoCo",
  simulate_drone: "MuJoCo",
  stress_test: "MuJoCo",
  blender_render: "Blender",
  isaac_sim_render: "Isaac Sim",
  isaac_test: "Isaac Sim",
  isaac_train: "Isaac Lab",
  product_usd: "Blender",
  isaac_lab_train: "Isaac Lab",
  isaac_lab_status: "Isaac Lab",
  parts_search: "Parts",
  physics_calc: "Physics",
  bom_build: "BOM",
  build_guide: "Build guide",
  print_prep: "Print plan",
  firmware: "Firmware",
  electronics_plan: "Electronics",
  safety_check: "Safety",
  version_commit: "Version",
  ask_user: "Question",
};

/**
 * Tools that never get a chat card: pointer and face moves, and calls whose result
 * has its own card (Jamie actions, the question, the version).
 */
const SILENT_TOOLS = new Set([
  "ui_point_at",
  "ui_draw",
  "mascot_say",
  "ui_control",
  "ask_user",
  "version_commit",
  "requirements_accept",
  "jamie_templates",
  "jamie_requirements",
  "jamie_search",
  "jamie_meeting",
  "jamie_create_tasks",
  "bom_build",
  "physics_calc",
  "grip_calc",
  "product_brief",
  "delegate",
  "stress_test",
  "safety_check",
]);

/** Tool names from the backend may differ in case or spacing ("isaac_lab", "Isaac Lab"). */
export function canonicalToolName(name: string): string {
  if (TOOL_ALIASES[name]) return TOOL_ALIASES[name];
  const flat = name.toLowerCase().replace(/[^a-z0-9]/g, "");
  const known = TOOL_NAMES.find((t) => t.toLowerCase().replace(/[^a-z0-9]/g, "") === flat);
  return known ?? name;
}

const MAX_DRAWS = 8;
/** Age given to bulk-replayed events; animations only run for events younger than a few seconds. */
export const INSTANT_AGE_MS = 120_000;
const LOCAL_ECHO_WINDOW_MS = 15000;

function emptyState() {
  return {
    log: [] as LoggedEvent[],
    steps: initialSteps(),
    tools: initialTools(),
    chat: [] as ChatItem[],
    requirements: [] as RequirementEvent[],
    metrics: null as MetricsEvent | null,
    runs: [] as Run[],
    draws: [] as Draw[],
    point: null as Pointing | null,
    mascot: { state: "ruhig" as MascotState, say: "", at: 0 },
    bom: null as BomEvent | null,
    jamie: [] as JamieEntry[],
    training: null as SessionState["training"],
    omniverse: null as OmniverseEvent | null,
    browserTraining: null as SessionState["browserTraining"],
    cad: null as SessionState["cad"],
    renders: [] as SessionState["renders"],
    meetings: [] as MeetingEvent[],
    versions: [] as VersionEvent[],
    parts: {} as Record<string, PartEvent>,
    partsByName: {} as Record<string, PartEvent>,
    questions: {} as Record<string, QuestionEvent>,
    tasks: null as TasksEvent | null,
    firmware: null as FirmwareEvent | null,
    electronics: null as ElectronicsEvent | null,
    agents: {} as SessionState["agents"],
    product: "" as ProductEvent["id"],
    productLabel: "Any product",
    sketch: null as SketchEvent | null,
    remixedFrom: null as SessionState["remixedFrom"],
    run: "idle" as RunStatus,
    stress: {} as SessionState["stress"],
    buildGuide: null as BuildGuideEvent | null,
    printPlan: null as PrintEvent | null,
    explains: {} as Record<string, ExplainEvent>,
    optimizes: {} as Record<string, OptimizeEvent>,
    ui: null as SessionState["ui"],
  };
}

const meetingOrder = (m: MeetingEvent) => `${m.date}T${m.time}`;

const DRONE_PARTS = new Set(["motor", "propeller", "battery", "flight_controller", "frame"]);

function isDroneEvent(ev: AgentEvent): boolean {
  if (ev.type === "metrics") return !ev.cards;
  if (ev.type === "part") return DRONE_PARTS.has(ev.category);
  if (ev.type === "sim") return !ev.kind || ev.kind === "hover";
  if (ev.type === "cad") return !ev.part;
  return ev.type === "version";
}

/** Finds the newest still-running chat card of a tool or Jamie action so its result updates it in place. */
function findOpenCard(chat: ChatItem[], kind: "tool" | "jamie", key: string): number {
  for (let i = chat.length - 1; i >= 0; i--) {
    const item = chat[i];
    if (item.kind === "tool" && kind === "tool" && item.name === key && item.phase === "running") return i;
    if (item.kind === "jamie" && kind === "jamie" && item.action === key && item.phase === "running") return i;
  }
  return -1;
}

export const useSession = create<SessionState>((set, get) => ({
  ...emptyState(),

  apply: (ev, opts) => {
    // The server starts every stream, and every reset, with this marker; a reconnect replays from it.
    if (ev.type === "reset") return set(emptyState());
    // `replayed` only marks the end of the backlog for events/source.ts; it carries no state.
    if (ev.type === "replayed") return;
    const at = opts?.instant ? Date.now() - INSTANT_AGE_MS : Date.now();
    const seq = ++seqCounter;
    // The drone flow (Jamie kickoff, recordings) sends no product event; its own events name it.
    if (get().product === "" && isDroneEvent(ev)) set({ product: "drone", productLabel: "Drone" });
    const s = get();
    const log = [...s.log, opts?.instant ? { seq, at, ev, instant: true } : { seq, at, ev }];

    switch (ev.type) {
      case "step": {
        if (!STEP_IDS.includes(ev.id)) return set({ log });
        const steps = { ...s.steps, [ev.id]: { id: ev.id, status: ev.status, label: ev.label || STEP_LABELS[ev.id], at, seq } };
        return set({ log, steps });
      }
      case "chat": {
        if (ev.role === "user") {
          // The backend echoes prompts we already showed optimistically; drop the echo.
          const echo = s.chat.findIndex(
            (c) => c.kind === "msg" && c.local && c.text.trim() === ev.text.trim() && at - c.at < LOCAL_ECHO_WINDOW_MS,
          );
          if (echo >= 0) {
            const chat = s.chat.slice();
            const item = chat[echo];
            if (item.kind === "msg") chat[echo] = { ...item, local: false, voice: item.voice || ev.voice };
            return set({ log, chat });
          }
        }
        const chat: ChatItem[] = [...s.chat, { kind: "msg", id: nextId("msg"), seq, at, role: ev.role, text: ev.text, voice: ev.voice }];
        return set({ log, chat });
      }
      case "tool": {
        const name = canonicalToolName(ev.name);
        const tools = { ...s.tools, [name]: { name, status: ev.status, detail: ev.detail, at } };
        if (SILENT_TOOLS.has(ev.name)) return set({ log, tools });
        let chat = s.chat;
        if (ev.status === "running") {
          // A second "running" for an open card is progress (FreeCAD: Arm 2 von 4), not a new call.
          const open = findOpenCard(chat, "tool", name);
          if (open >= 0) {
            chat = chat.slice();
            const item = chat[open];
            if (item.kind === "tool") chat[open] = { ...item, detail: ev.detail || item.detail };
          } else {
            chat = [...chat, { kind: "tool", id: nextId("tool"), seq, at, name, phase: "running", detail: ev.detail, instant: opts?.instant }];
          }
        } else {
          // offline (a fallback took over) and connected also end a call.
          const phase: Phase = ev.status === "error" ? "error" : "ok";
          const open = findOpenCard(chat, "tool", name);
          if (open >= 0) {
            chat = chat.slice();
            const item = chat[open];
            if (item.kind === "tool")
              chat[open] = { ...item, phase, detail: ev.detail || item.detail, endedAt: at, instant: item.instant || opts?.instant };
          } else if (ev.status === "ok" || ev.status === "error") {
            // Connection status at startup (connected, offline) is not a call and gets no card.
            chat = [...chat, { kind: "tool", id: nextId("tool"), seq, at, name, phase, detail: ev.detail, endedAt: at }];
          }
        }
        return set({ log, tools, chat });
      }
      case "requirement": {
        const idx = s.requirements.findIndex((r) => r.id === ev.id);
        const requirements = s.requirements.slice();
        if (idx >= 0) requirements[idx] = { ...requirements[idx], ...ev };
        else requirements.push(ev);
        // The first requirement opens the card in the chat; later ones update it in place.
        const chat: ChatItem[] = s.chat.some((c) => c.kind === "requirements")
          ? s.chat
          : [...s.chat, { kind: "requirements", id: nextId("requirements"), seq, at }];
        return set({ log, requirements, chat });
      }
      case "metrics":
        return set({ log, metrics: ev });
      case "sim": {
        const runs = [...s.runs.filter((r) => r.run !== ev.run), { ...ev, seq, at }].sort((a, b) => a.run - b.run);
        const chat: ChatItem[] = [
          ...s.chat,
          { kind: "sim", id: nextId("sim"), seq, at, run: ev.run, result: ev.result, summary: ev.summary },
        ];
        // A new run result starts a fresh explanation, so old annotations go away.
        return set({ log, runs, chat, draws: [] });
      }
      case "draw": {
        const draws = [...s.draws, { ...ev, id: nextId("draw"), at }].slice(-MAX_DRAWS);
        return set({ log, draws });
      }
      case "point":
        return set({ log, point: { id: nextId("point"), target: ev.target, label: ev.label, at } });
      case "mascot":
        return set({ log, mascot: { state: ev.state, say: ev.say, voice: ev.voice, at } });
      case "bom": {
        const card = {
          kind: "bom" as const,
          id: nextId("bom"),
          seq,
          at,
          count: ev.items.length,
          total: ev.total_eur,
          numbers: resultNumbers(s.metrics, ev.total_eur),
        };
        // Live prices replace the catalog list they were searched for, so the card updates instead of repeating.
        let open = s.bom?.prices === "searching" ? s.chat.length - 1 : -1;
        while (open >= 0 && s.chat[open].kind !== "bom") open--;
        const chat: ChatItem[] = open >= 0 ? s.chat.map((c, i) => (i === open ? { ...card, id: c.id } : c)) : [...s.chat, card];
        return set({ log, bom: ev, chat });
      }
      case "jamie": {
        const phase = phaseOf(ev.status);
        const jamie = [...s.jamie, { id: nextId("jamie"), seq, at, action: ev.action, status: ev.status, phase, detail: ev.detail }];
        let chat = s.chat;
        const open = findOpenCard(chat, "jamie", ev.action);
        if (phase !== "running" && open >= 0) {
          chat = chat.slice();
          const item = chat[open];
          if (item.kind === "jamie") chat[open] = { ...item, phase, detail: ev.detail || item.detail, endedAt: at };
        } else {
          chat = [...chat, { kind: "jamie", id: nextId("jamie"), seq, at, action: ev.action, phase, detail: ev.detail }];
        }
        return set({ log, jamie, chat });
      }
      case "cad":
        return set({ log, cad: { ...ev, at, n: (s.cad?.n ?? 0) + 1 } });
      case "render":
        return set({ log, renders: [...s.renders, { ...ev, id: nextId("render"), at }] });
      case "meeting": {
        const meetings = [...s.meetings.filter((m) => m.id !== ev.id && m.id !== ev.replaces), ev].sort((a, b) =>
          meetingOrder(a).localeCompare(meetingOrder(b)),
        );
        return set({ log, meetings });
      }
      case "version": {
        const versions = [...s.versions.filter((v) => v.n !== ev.n), ev].sort((a, b) => a.n - b.n);
        // A version published again with its snapshot fields keeps its one chat card.
        const known = s.chat.some((c) => c.kind === "version" && c.n === ev.n);
        const chat: ChatItem[] = known ? s.chat : [...s.chat, { kind: "version", id: nextId("version"), seq, at, n: ev.n }];
        return set({ log, versions, chat });
      }
      case "part": {
        const parts = ev.considered ? s.parts : { ...s.parts, [ev.category]: ev };
        const partsByName = { ...s.partsByName, [ev.name]: ev };
        const chat: ChatItem[] = [
          ...s.chat,
          ...ev.warnings.map((warning) => ({ kind: "warning" as const, id: nextId("warn"), seq, at, part: ev.name, warning })),
        ];
        return set({ log, parts, partsByName, chat });
      }
      case "optimize": {
        const optimizes = { ...s.optimizes, [ev.id]: ev };
        const known = s.chat.some((c) => c.kind === "optimize" && c.optimizeId === ev.id);
        const chat: ChatItem[] = known ? s.chat : [...s.chat, { kind: "optimize", id: nextId("optimize"), seq, at, optimizeId: ev.id }];
        return set({ log, optimizes, chat });
      }
      case "question": {
        const questions = { ...s.questions, [ev.id]: ev };
        const known = s.chat.some((c) => c.kind === "question" && c.questionId === ev.id);
        const chat: ChatItem[] = known ? s.chat : [...s.chat, { kind: "question", id: nextId("question"), seq, at, questionId: ev.id }];
        return set({ log, questions, chat });
      }
      case "tasks":
        return set({ log, tasks: ev });
      case "remix":
        return set({ log, remixedFrom: { id: ev.id, title: ev.title, author: ev.author } });
      case "run":
        return set({ log, run: ev.status });
      case "agent": {
        // One card per agent, updated in place as it reports tokens, cost and its result.
        const known = !!s.agents[ev.id];
        const agents = { ...s.agents, [ev.id]: { ...ev, at: known ? s.agents[ev.id].at : at } };
        const chat: ChatItem[] = known ? s.chat : [...s.chat, { kind: "agent", id: nextId("agent"), seq, at, agentId: ev.id }];
        return set({ log, agents, chat });
      }
      case "sketch":
        return set({ log, sketch: ev });
      case "product": {
        if (ev.id === s.product) {
          const keep = ev.requirements;
          const requirements = keep ? s.requirements.filter((r) => keep.includes(r.id)) : s.requirements;
          return set({ log, productLabel: ev.label || s.productLabel, requirements });
        }
        // A new product starts its own build: drop the other product's numbers, parts and runs.
        return set({
          log,
          product: ev.id,
          productLabel: ev.label,
          // The sketch a fresh bench was built from stays next to its model.
          sketch: s.product === "" || s.sketch?.product === ev.id ? s.sketch : null,
          requirements: [],
          metrics: null,
          omniverse: null,
          runs: [],
          draws: [],
          bom: null,
          buildGuide: null,
          printPlan: null,
          cad: null,
          renders: [],
          parts: {},
          versions: [],
          firmware: null,
          electronics: null,
        });
      }
      case "stress": {
        const stress = { ...s.stress, [ev.run]: { ...ev, seq, at } };
        const known = s.chat.some((c) => c.kind === "stress" && c.run === ev.run);
        const chat: ChatItem[] = known ? s.chat : [...s.chat, { kind: "stress", id: nextId("stress"), seq, at, run: ev.run }];
        return set({ log, stress, chat });
      }
      case "build_guide":
        return set({ log, buildGuide: ev });
      case "print":
        return set({ log, printPlan: ev, chat: [...s.chat, { kind: "print", id: nextId("print"), seq, at, plan: ev }] });
      case "explain": {
        const explains = { ...s.explains, [ev.key]: ev };
        const known = s.chat.some((c) => c.kind === "explain" && c.key === ev.key);
        const chat: ChatItem[] = !ev.chat || known ? s.chat : [...s.chat, { kind: "explain", id: nextId("explain"), seq, at, key: ev.key }];
        return set({ log, explains, chat });
      }
      case "firmware":
        return set({ log, firmware: ev });
      case "electronics":
        return set({ log, electronics: ev });
      case "safety":
        return set({ log, chat: [...s.chat, { kind: "safety", id: nextId("safety"), seq, at, safety: ev }] });
      case "training": {
        // Browser training is narrated by its tool card and Mechanic, not the Isaac Lab card.
        if ((ev as { source?: string }).source === "browser") return set({ log, browserTraining: { ...ev, at } });
        const prev = s.training;
        let chat = s.chat;
        if (!prev || prev.status !== ev.status) {
          chat = [
            ...chat,
            { kind: "training", id: nextId("training"), seq, at, status: ev.status, detail: trainingDetail(ev) },
          ];
        }
        return set({ log, training: { ...ev, at }, chat });
      }
      case "omniverse":
        return set({ log, omniverse: ev });
      case "ui":
        return set({ log, ui: { ...ev, at } });
    }
  },

  addLocalUserMessage: (text, voice) => {
    const at = Date.now();
    set((s) => ({
      chat: [...s.chat, { kind: "msg", id: nextId("msg"), seq: ++seqCounter, at, role: "user", text, local: true, voice }],
    }));
  },

  reset: () => set(emptyState()),
}));

function trainingDetail(ev: TrainingEvent): string {
  switch (ev.status) {
    case "queued":
      return "waiting for the GPU";
    case "running":
      return `${formatSteps(ev.step)} steps`;
    case "done":
      return `done after ${formatSteps(ev.step)} steps`;
    case "failed":
      return "stopped";
    case "offline":
      return "RunPod unreachable";
  }
}

export function formatSteps(step: number): string {
  if (step >= 1_000_000) return `${(step / 1_000_000).toLocaleString("en-GB", { maximumFractionDigits: 1 })}M`;
  if (step >= 1000) return `${Math.round(step / 1000).toLocaleString("en-GB")}k`;
  return step.toLocaleString("en-GB");
}

/** The step the agent is on right now: the running one, else the last one that finished or failed. */
export function currentStep(steps: Record<StepId, StepState>): StepState {
  const all = STEP_IDS.map((id) => steps[id]);
  const running = all.filter((s) => s.status === "running").sort((a, b) => b.seq - a.seq)[0];
  if (running) return running;
  const touched = all.filter((s) => s.status !== "pending").sort((a, b) => b.seq - a.seq)[0];
  return touched ?? all[0];
}
