import { useEffect, useMemo, useState } from "react";
import { useSession } from "../events/store";
import type { MetricsEvent, VersionEvent } from "../events/types";
import { metricTargets, versions, type Version } from "./derived";
import { partKey } from "./targets";
import { useUi } from "./ui";

export function useVersions(): Version[] {
  const log = useSession((s) => s.log);
  const runs = useSession((s) => s.runs);
  return useMemo(() => versions(log, runs), [log, runs]);
}

/** The version picked on the timeline, else the newest. */
export function useSelectedVersion(): Version | null {
  const all = useVersions();
  const selected = useUi((s) => s.selectedRun);
  return all.find((v) => v.run.run === selected) ?? all[all.length - 1] ?? null;
}

export function useTargets() {
  const requirements = useSession((s) => s.requirements);
  return useMemo(() => metricTargets(requirements), [requirements]);
}

export interface Assembly {
  arm: number;
  thickness: number;
  battery: [number, number, number];
  propDiameter: number;
}

/** The kickoff's pack, the Tattu R-Line 1S 550 of the reference build. */
const RLINE_550: [number, number, number] = [59, 18, 8];

/**
 * What the 3D model draws, in metres: the frame from the CAD parameters and the
 * battery that was chosen. With `atSeq` it is the build as it stood at that event
 * (a simulation run), with "latest" the newest build, else the version picked on
 * the timeline, else the current one.
 */
export function useAssembly(atSeq?: number | "latest"): Assembly {
  const cad = useSession((s) => s.cad);
  const parts = useSession((s) => s.parts);
  const byName = useSession((s) => s.partsByName);
  const log = useSession((s) => s.log);
  const selected = useUi((s) => s.selectedVersion);
  const versionsList = useSession((s) => s.versions);
  return useMemo(() => {
    let battery = parts.battery;
    if (typeof atSeq === "number") {
      for (const { seq, ev } of log) {
        if (seq > atSeq) break;
        if (ev.type === "part" && ev.category === "battery" && !ev.considered) battery = ev;
      }
    } else if (atSeq === undefined && selected !== null) {
      const name = versionsList.find((v) => v.n === selected)?.parts.battery;
      if (name && byName[name]) battery = byName[name];
    }
    const size = battery?.size_mm ?? RLINE_550;
    return {
      arm: (cad?.params.arm_length_mm?.value ?? 42.5) / 1000,
      thickness: (cad?.params.thickness_mm?.value ?? 2) / 1000,
      battery: [size[0] / 1000, size[1] / 1000, size[2] / 1000],
      propDiameter: (parts.propeller?.diameter_mm ?? 51) / 1000,
    };
  }, [cad, parts, byName, log, selected, versionsList, atSeq]);
}

const HIGHLIGHT_MS = 7000;

/** Parts the agent is pointing at or drawing on right now. */
export function useHighlight(): Set<string> {
  const draws = useSession((s) => s.draws);
  const point = useSession((s) => s.point);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    // Re-evaluate when the newest point or drawing stops being fresh.
    const ends = [point ? point.at + HIGHLIGHT_MS : 0, ...draws.map((d) => d.at + HIGHLIGHT_MS * 2)];
    const left = Math.max(...ends) - Date.now();
    setNow(Date.now());
    if (left <= 0) return;
    const id = setTimeout(() => setNow(Date.now()), left + 50);
    return () => clearTimeout(id);
  }, [point, draws]);
  return useMemo(() => {
    const set = new Set<string>();
    for (const d of draws) {
      const k = partKey(d.target);
      if (k && now - d.at < HIGHLIGHT_MS * 2) set.add(k);
    }
    if (point && now - point.at < HIGHLIGHT_MS) {
      const k = partKey(point.target);
      if (k) set.add(k);
    }
    return set;
  }, [draws, point, now]);
}

type Numbers = Pick<MetricsEvent, "weight_g" | "thrust_to_weight" | "flight_time_min" | "price_eur">;
const same = (a: Numbers, b: Numbers) =>
  a.weight_g === b.weight_g && a.thrust_to_weight === b.thrust_to_weight && a.flight_time_min === b.flight_time_min && a.price_eur === b.price_eur;

/**
 * The numbers the panel shows: the version picked on the meeting timeline, else the
 * live build. `previous` is the version before it, so a rebuild reads "vorher …".
 */
export function useShownBuild(): { metrics: Numbers | null; previous: Numbers | null; version: VersionEvent | null; pinned: boolean } {
  const versions = useSession((s) => s.versions);
  const live = useSession((s) => s.metrics);
  const selected = useUi((s) => s.selectedVersion);
  return useMemo(() => {
    const pinned = selected !== null ? versions.find((v) => v.n === selected) ?? null : null;
    if (pinned) {
      const before = versions.filter((v) => v.n < pinned.n).at(-1) ?? null;
      return { metrics: pinned, previous: before, version: pinned, pinned: true };
    }
    const latest = versions.at(-1) ?? null;
    if (!live) return { metrics: latest, previous: versions.at(-2) ?? null, version: latest, pinned: false };
    const settled = latest !== null && same(live, latest);
    return { metrics: live, previous: settled ? versions.at(-2) ?? null : latest, version: settled ? latest : null, pinned: false };
  }, [versions, live, selected]);
}
