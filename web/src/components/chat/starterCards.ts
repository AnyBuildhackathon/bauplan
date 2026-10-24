import type { ReferenceBuild } from "../../events/source";

/** Reference builds on an empty bench. The prompt sentences name other products, so these cards do not repeat them. */
export const STARTER_IDS = ["micro-drone", "robot-gripper", "phone-stand", "desk-lamp", "pet-feeder"];

/** Sentences that fill the composer. They are requests, not a second copy of the reference names. */
export const STARTER_PROMPTS = ["A USB desk fan under 300 g", "A wall hook for 5 kg", "A plant-watering robot for one pot"];

/**
 * One measured line for a starter card.
 * Code references and the phone stand omit the product mass from their library summary;
 * these figures are the seeded builds in web/public/community/feed.json (joined on `base`).
 */
const MEASURED_FACT: Record<string, string> = {
  "micro-drone": "47 g · 8.5 min",
  "robot-gripper": "128 g",
  "phone-stand": "116 g",
};

function trimNum(raw: string): string {
  const n = Number(raw);
  return Number.isFinite(n) ? String(n) : raw;
}

/** A short fact from the library item: a seeded measurement, else the mass or size named in the summary. */
export function keyFact(item: ReferenceBuild): string {
  const measured = MEASURED_FACT[item.id];
  if (measured) return measured;
  const summary = item.summary;
  const mass = summary.match(/(\d+(?:\.\d+)?)\s*g(?!\s*(?:phone|soda|can)\b)/i);
  if (mass) return `${trimNum(mass[1])} g`;
  const litre = summary.match(/(\d+(?:\.\d+)?)\s*litres?\b/i);
  if (litre) return `${trimNum(litre[1])} litre`;
  const litres = summary.match(/(\d+(?:\.\d+)?)\s*l\b/i);
  if (litres) return `${trimNum(litres[1])} litre`;
  const watts = summary.match(/(\d+(?:\.\d+)?)\s*W\b/);
  const span = summary.match(/(\d+)\s*mm\b/);
  if (watts && span) return `${trimNum(watts[1])} W · ${span[1]} mm`;
  if (watts) return `${trimNum(watts[1])} W`;
  const range = summary.match(/(\d+(?:\.\d+)?)\s*to\s*(\d+(?:\.\d+)?)\s*mm/);
  if (range) return `${trimNum(range[1])}–${trimNum(range[2])} mm`;
  if (/about a month/i.test(summary)) return "1 month";
  const parts = item.printed + item.bought;
  return `${parts} part${parts === 1 ? "" : "s"}`;
}

/** Up to five reference builds, featured ids first. */
export function starterCards(items: ReferenceBuild[]): ReferenceBuild[] {
  const refs = items.filter((item) => item.kind === "reference");
  const byId = new Map(refs.map((item) => [item.id, item]));
  const cards = STARTER_IDS.flatMap((id) => {
    const item = byId.get(id);
    return item ? [item] : [];
  });
  if (cards.length >= 3) return cards.slice(0, 5);
  for (const item of refs) {
    if (cards.some((card) => card.id === item.id)) continue;
    cards.push(item);
    if (cards.length === 5) break;
  }
  return cards;
}
