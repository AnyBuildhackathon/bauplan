// Views derived from the event log: metric targets parsed from the requirements,
// the version history (one version per simulation run) and what triggered each one.
import type { LoggedEvent, Run } from "../events/store";
import type { MetricsEvent, RequirementEvent } from "../events/types";

export type MetricKey = "weight_g" | "thrust_to_weight" | "flight_time_min" | "price_eur";

export interface MetricTarget {
  key: MetricKey;
  /** Limit value; `max` means the metric must stay at or below it. */
  value: number;
  direction: "max" | "min";
  requirementId: string | null;
}

const num = (s: string) => Number(s.replace(",", "."));

/** Reads limits like "under €120", "unter 80 €" or "mindestens 2 : 1" from requirement texts, with sane defaults. */
export function metricTargets(requirements: RequirementEvent[]): Record<MetricKey, MetricTarget> {
  const targets: Record<MetricKey, MetricTarget> = {
    weight_g: { key: "weight_g", value: 250, direction: "max", requirementId: null },
    thrust_to_weight: { key: "thrust_to_weight", value: 2, direction: "min", requirementId: null },
    flight_time_min: { key: "flight_time_min", value: 10, direction: "min", requirementId: null },
    price_eur: { key: "price_eur", value: 80, direction: "max", requirementId: null },
  };
  for (const r of requirements) {
    const t = r.text;
    let m: RegExpMatchArray | null;
    if ((m = t.match(/€\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:€|eur)/i))) {
      targets.price_eur = { ...targets.price_eur, value: num(m[1] ?? m[2]), requirementId: r.id };
    } else if ((m = t.match(/(\d+(?:[.,]\d+)?)\s*:\s*1/))) {
      targets.thrust_to_weight = { ...targets.thrust_to_weight, value: num(m[1]), requirementId: r.id };
    } else if ((m = t.match(/(\d+(?:[.,]\d+)?)\s*(?:min|minuten)/i))) {
      targets.flight_time_min = { ...targets.flight_time_min, value: num(m[1]), requirementId: r.id };
    } else if ((m = t.match(/(\d+(?:[.,]\d+)?)\s*(?:g|gramm)\b/i)) && !/cm|mm/.test(t)) {
      targets.weight_g = { ...targets.weight_g, value: num(m[1]), requirementId: r.id };
    }
  }
  return targets;
}

export function meets(target: MetricTarget, value: number): boolean {
  return target.direction === "max" ? value <= target.value : value >= target.value;
}

/** The meeting name the requirements came from, taken from Jamie's transcript call. */
export function meetingTitle(log: LoggedEvent[]): string {
  for (let i = log.length - 1; i >= 0; i--) {
    const ev = log[i].ev;
    if (ev.type === "jamie" && /transcript/i.test(ev.action) && ev.detail) return ev.detail.split("·")[0].trim();
  }
  return "Jamie-Meeting";
}

export interface Version {
  n: number;
  run: Run;
  metrics: MetricsEvent | null;
  /** Requirement states as they stood after this run (before the next one). */
  requirements: RequirementEvent[];
  trigger: { quote: string; requirementId: string } | null;
}

function stateBefore(log: LoggedEvent[], seq: number) {
  let metrics: MetricsEvent | null = null;
  const reqs = new Map<string, RequirementEvent>();
  for (const { seq: s, ev } of log) {
    if (s >= seq) break;
    if (ev.type === "metrics") metrics = ev;
    if (ev.type === "requirement") reqs.set(ev.id, { ...(reqs.get(ev.id) ?? ev), ...ev });
  }
  return { metrics, reqs };
}

const words = (s: string) =>
  new Set(
    s
      .toLowerCase()
      .replace(/[^a-zäöüß0-9 ]/g, " ")
      .split(/\s+/)
      .filter((w) => w.length >= 4),
  );

/** How far a metric is inside (positive) or outside (negative) its limit, relative to the limit. */
function margin(target: MetricTarget, value: number): number {
  return target.direction === "max" ? (target.value - value) / target.value : (value - target.value) / target.value;
}

/**
 * One version per simulation run. What triggered a version:
 * v1 is the brief itself (the user's prompt). A later version answers the requirement
 * the previous run failed and this one moved furthest towards its limit. When nothing
 * failed before, the requirement the run summary talks about (for example wind).
 */
export function versions(log: LoggedEvent[], runs: Run[]): Version[] {
  const out: Version[] = [];
  runs.forEach((run, i) => {
    const next = runs[i + 1];
    const before = stateBefore(log, run.seq);
    const after = stateBefore(log, next ? next.seq : Number.POSITIVE_INFINITY);
    const requirements = [...after.reqs.values()];
    const targets = metricTargets(requirements);
    let trigger: Version["trigger"] = null;

    if (i === 0) {
      const prompt = log.find((l) => l.seq < run.seq && l.ev.type === "chat" && l.ev.role === "user");
      if (prompt && prompt.ev.type === "chat") trigger = { quote: prompt.ev.text, requirementId: "" };
    } else {
      const prev = out[i - 1];
      const failed = [...before.reqs.values()].filter((r) => r.met === false);
      let best: { r: RequirementEvent; gain: number } | null = null;
      for (const r of failed) {
        const t = Object.values(targets).find((x) => x.requirementId === r.id);
        if (!t || !prev.metrics || !before.metrics) continue;
        const gain = margin(t, before.metrics[t.key]) - margin(t, prev.metrics[t.key]);
        if (!best || gain > best.gain) best = { r, gain };
      }
      const pick =
        best?.r ??
        failed[0] ??
        (() => {
          const w = words(run.summary);
          return requirements
            .map((r) => ({ r, score: [...words(`${r.text} ${r.source_quote}`)].filter((x) => w.has(x)).length }))
            .filter((x) => x.score > 0)
            .sort((a, b) => b.score - a.score)[0]?.r;
        })();
      if (pick) trigger = { quote: pick.source_quote, requirementId: pick.id };
    }

    out.push({ n: i + 1, run, metrics: before.metrics, requirements, trigger });
  });
  return out;
}
