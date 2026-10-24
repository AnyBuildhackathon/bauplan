// Learning mode: engineering terms with a one-line definition, shown on hover by <Glossed>.

export const GLOSSARY: Record<string, string> = {
  "thrust-to-weight": "Total thrust of all motors divided by the weight. Above 1 it lifts off; about 2 or more leaves reserve for wind and manoeuvres.",
  "T/W": "Thrust-to-weight: total motor thrust divided by the weight.",
  "centre of mass": "The point where the whole weight acts. Lower and more central means more stable.",
  "tip-over": "Tipping over: the centre of mass passes the edge of the footprint and gravity pulls the product down.",
  "tipping edge": "The edge of the footprint the product would rotate about when it falls over.",
  footprint: "The area the product stands on: the outline around its lowest contact points.",
  "safety factor": "How much stronger a part is than it has to be: what it can take divided by what it gets. 2× means twice the load.",
  "stress safety": "The material's strength divided by the bending stress in the part.",
  deflection: "How far a part bends under load.",
  stress: "Force per area inside the material. Above its strength the part breaks or yields.",
  "Young's modulus": "How stiff a material is: the stress needed per unit of stretch, E in MPa.",
  "stall torque": "The most torque a motor or servo gives when held still; only part of it is usable in practice.",
  torque: "Turning force: force × lever arm, in N m.",
  KV: "Motor speed constant: revolutions per minute per volt, without load.",
  "C rating": "How fast a battery can be discharged: C × capacity is the maximum current.",
  mAh: "Milliamp-hours: the charge a battery holds. Energy in Wh is voltage × mAh / 1000.",
  Wh: "Watt-hours: the energy in the battery. Runtime is roughly usable Wh divided by the power drawn.",
  "battery runtime": "How long the battery lasts: usable energy divided by the average power drawn.",
  "hover power": "The electrical power the motors need to hold the drone in the air; it grows faster than the weight.",
  "duty cycle": "The share of time a load is on; average power is power × duty cycle.",
  downdraft: "Air pushing down on the drone, like a gust from above.",
  gust: "A short, strong change of wind. The test pushes down with 35 % of the weight for 0.3 s.",
  PID: "The controller that holds attitude and height: it reacts to the error now (P), its sum over time (I) and its rate of change (D).",
  MuJoCo: "A physics simulator. AnyBuild flies, pushes or drops the design there before anything is built.",
  "convex hull": "The tightest outline around a set of points, like a rubber band around them.",
  infill: "The inner fill pattern of a 3D-printed part; more infill is heavier and stronger.",
  PETG: "A tough, slightly flexible 3D-printing plastic that takes heat better than PLA.",
  STEP: "A CAD exchange file with exact geometry, readable by any CAD program.",
  STL: "A triangle mesh of a part, the file a 3D printer slicer reads.",
  "X frame": "A quadcopter frame with four arms in an X, motors at the tips.",
  "evolution strategy": "A training method that tries many random variations and keeps the best ones, generation after generation.",
};

const TERM_RE = new RegExp(
  `(${Object.keys(GLOSSARY)
    .sort((a, b) => b.length - a.length)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&"))
    .join("|")})`,
  "gi",
);

const LOOKUP = new Map(Object.keys(GLOSSARY).map((t) => [t.toLowerCase(), t]));

/** Splits text into plain pieces and glossary terms, each term marked once, whole words only. */
export function glossSegments(text: string): { text: string; term?: string }[] {
  const seen = new Set<string>();
  const out: { text: string; term?: string }[] = [];
  let last = 0;
  for (const m of text.matchAll(TERM_RE)) {
    const term = LOOKUP.get(m[0].toLowerCase());
    const before = text[m.index - 1] ?? " ";
    const after = text[m.index + m[0].length] ?? " ";
    if (!term || seen.has(term) || /\w/.test(before) || /\w/.test(after)) continue;
    // Short acronyms only match in their own case ("Wh", not "wh" inside a sentence).
    if (term.length <= 3 && m[0] !== term) continue;
    seen.add(term);
    if (m.index > last) out.push({ text: text.slice(last, m.index) });
    out.push({ text: m[0], term });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}
