// Resolves `point` and `draw` targets to screen positions. A target is either a
// 3D part of the drone (projected from the live scene every frame) or a UI element
// tagged with data-target. The agent may name parts in German or English, so names
// are normalised and mapped to one canonical key first.

export interface ScreenSpot {
  x: number;
  y: number;
  /** Approximate on-screen radius of the target in px. */
  r: number;
  /** The clip rectangle of the surface the target lives on (the 3D canvas or the viewport). */
  clip: DOMRect | null;
  kind: "part" | "ui";
}

// Canonical keys follow the backend's part list (agent/ scene.py, docs/events.md):
// frame, motor_front_left ... propeller_rear_right, battery, flight_controller.
const SYNONYMS: Record<string, string[]> = {
  frame: ["frame", "rahmen", "chassis", "body", "arms", "arm", "arme", "ausleger", "drohne", "drone", "quad"],
  motors: ["motors", "motor", "motoren", "antrieb"],
  motor_front_left: ["motor_front_left", "motor_fl", "motor_1", "motor1", "motor_vl", "motor_vorne_links"],
  motor_front_right: ["motor_front_right", "motor_fr", "motor_2", "motor2", "motor_vr", "motor_vorne_rechts"],
  motor_rear_left: ["motor_rear_left", "motor_bl", "motor_back_left", "motor_3", "motor3", "motor_hl", "motor_hinten_links"],
  motor_rear_right: ["motor_rear_right", "motor_br", "motor_back_right", "motor_4", "motor4", "motor_hr", "motor_hinten_rechts"],
  propellers: ["propellers", "propeller", "props", "prop", "rotor", "rotoren", "rotors"],
  propeller_front_left: ["propeller_front_left", "prop_fl", "propeller_fl", "propeller_vorne_links"],
  propeller_front_right: ["propeller_front_right", "prop_fr", "propeller_fr", "propeller_vorne_rechts"],
  propeller_rear_left: ["propeller_rear_left", "prop_bl", "propeller_bl", "propeller_hinten_links"],
  propeller_rear_right: ["propeller_rear_right", "prop_br", "propeller_br", "propeller_hinten_rechts"],
  battery: ["battery", "akku", "batterie", "lipo", "li_ion", "liion", "18650", "pack", "akkupack"],
  flight_controller: ["flight_controller", "flightcontroller", "fc", "flugcontroller", "controller", "esc", "regler", "aio"],
  receiver: ["receiver", "empfaenger", "elrs", "rx", "antenne", "antenna"],
};

const CANONICAL = new Map<string, string>();
for (const [key, names] of Object.entries(SYNONYMS)) for (const n of names) CANONICAL.set(n, key);
const BY_LENGTH = [...CANONICAL].sort((a, b) => b[0].length - a[0].length);

export function normaliseName(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .replace(/[^a-z0-9:]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

/** Maps a raw target to the canonical part key, or null when it is not a drone part. */
export function partKey(raw: string): string | null {
  const n = normaliseName(raw).replace(/^(part|teil|3d):/, "");
  // Prefixed names (metric:, requirement:, tool:, step:, nav:) always mean UI elements.
  if (n.includes(":")) return null;
  if (CANONICAL.has(n)) return CANONICAL.get(n)!;
  for (const [alias, key] of BY_LENGTH) if (alias.length > 3 && n.includes(alias)) return key;
  return null;
}

// --- 3D anchors, written by the active scene every frame -----------------------

interface AnchorSpot {
  x: number;
  y: number;
  r: number;
  visible: boolean;
  clip: DOMRect;
  owner: string;
}

const anchors = new Map<string, AnchorSpot>();

export function writeAnchor(key: string, spot: AnchorSpot) {
  anchors.set(key, spot);
}
export function dropAnchors(owner: string) {
  for (const [key, spot] of anchors) if (spot.owner === owner) anchors.delete(key);
}

// --- resolution ------------------------------------------------------------------

/** Whether an element can be seen: the chat stays mounted, invisible, behind the right panel's other tabs. */
function shown(el: HTMLElement): boolean {
  return el.checkVisibility ? el.checkVisibility({ visibilityProperty: true, checkVisibilityCSS: true }) : true;
}

function domSpot(raw: string): ScreenSpot | null {
  const wanted = normaliseName(raw);
  const bare = wanted.replace(/^[a-z]+:/, "");
  const els = document.querySelectorAll<HTMLElement>("[data-target]");
  let best: HTMLElement | null = null;
  for (const el of els) {
    const tokens = (el.dataset.target ?? "").split(/\s+/).map(normaliseName);
    if (tokens.includes(wanted)) {
      if (!shown(el)) continue;
      best = el;
      break;
    }
    if (!best && tokens.some((t) => t === bare || t.replace(/^[a-z]+:/, "") === bare) && shown(el)) best = el;
  }
  if (!best) return null;
  const rect = best.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  return {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
    r: Math.max(18, Math.min(rect.width, rect.height) / 2 + 6),
    clip: null,
    kind: "ui",
  };
}

/** A dashboard control Mechanic operates, tagged `data-control` (lib/pilot.ts). */
function controlSpot(id: string): ScreenSpot | null {
  for (const el of document.querySelectorAll<HTMLElement>(`[data-control~="${CSS.escape(id)}"]`)) {
    const rect = el.getBoundingClientRect();
    if ((rect.width === 0 && rect.height === 0) || !shown(el)) continue;
    return {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      r: Math.max(18, Math.min(rect.width, rect.height) / 2 + 6),
      clip: null,
      kind: "ui",
    };
  }
  return null;
}

/** Current screen position of a target, or null when it is not on screen right now. */
export function resolveTarget(raw: string): ScreenSpot | null {
  if (raw.startsWith("control:")) return controlSpot(raw.slice(8));
  // Drone parts by canonical key, any other product's parts by their normalised name or id.
  for (const key of [partKey(raw), normaliseName(raw)]) {
    const spot = key ? anchors.get(key) : undefined;
    if (spot && spot.visible) return { x: spot.x, y: spot.y, r: spot.r, clip: spot.clip, kind: "part" };
  }
  return domSpot(raw);
}
