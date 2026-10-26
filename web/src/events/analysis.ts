// The studio's colour layer for the surface checks (the `analysis` event, docs/events.md): which check
// it paints over the model, the limit each one is shown against (Mechanic's, until the person moves
// it), the colours, and the spot a click picked. A picked spot carries the check, the part, the value
// and the place in the build's mm, which is what a context note to Mechanic needs (U6 takes it up).
import * as THREE from "three";
import { create } from "zustand";
import { useSession } from "./store";
import type { AnalysisCheck, AnalysisCheckInfo, AnalysisEvent } from "./types";

export const ANALYSIS_CHECKS: AnalysisCheck[] = ["overhang", "thickness", "clearance"];

/** A spot on the model a click picked while the layer was on. */
export interface AnalysisPick {
  check: AnalysisCheck;
  /** The model node, the part's name in the model. */
  part: string;
  partId: string | null;
  value: number;
  /** Where, in mm in the build's frame with Z up, as in Mechanic's numbers. */
  atMm: [number, number, number];
  critical: boolean;
}

interface LayerState {
  /** The check painted over the model; null shows the model as it is. */
  check: AnalysisCheck | null;
  /** Limits the person moved, per check; Mechanic's limit stands for the others. */
  limits: Partial<Record<AnalysisCheck, number>>;
  /** The critical area the layer counts at the limit shown, over every checked part. */
  area: { check: AnalysisCheck; limit: number; mm2: number } | null;
  picked: AnalysisPick | null;
  show: (check: AnalysisCheck | null) => void;
  setLimit: (check: AnalysisCheck, limit: number | null) => void;
  pick: (picked: AnalysisPick | null) => void;
}

export const useAnalysisLayer = create<LayerState>((set) => ({
  check: null,
  limits: {},
  area: null,
  picked: null,
  show: (check) => set({ check, picked: null }),
  setLimit: (check, limit) =>
    set((s) => {
      const limits = { ...s.limits };
      if (limit === null) delete limits[check];
      else limits[check] = limit;
      return { limits };
    }),
  pick: (picked) => set({ picked }),
}));

// A new check result is measured on new geometry: the picked spot goes; another product starts plain.
useSession.subscribe((s, prev) => {
  if (s.analysis === prev.analysis) return;
  useAnalysisLayer.setState(s.analysis ? { picked: null } : { check: null, limits: {}, picked: null });
});

/** The `?build=` of a model or analysis URL. */
export function buildOf(url: string | null | undefined): string | null {
  const match = url ? /[?&]build=([^&#]+)/.exec(url) : null;
  return match ? match[1] : null;
}

/** The analysis was measured on the model this URL shows, not an older or newer build. */
export function isCurrent(analysis: AnalysisEvent | null, modelUrl: string | null | undefined): analysis is AnalysisEvent {
  return !!analysis && buildOf(modelUrl) === String(analysis.build);
}

export function limitOf(check: AnalysisCheck, info: AnalysisCheckInfo, limits: LayerState["limits"]): number {
  return limits[check] ?? info.limit;
}

/** The range a limit slider offers, and its step. */
export function limitRange(check: AnalysisCheck): { min: number; max: number; step: number } {
  if (check === "overhang") return { min: 20, max: 80, step: 1 };
  if (check === "thickness") return { min: 0.2, max: 4, step: 0.02 };
  return { min: 0.05, max: 2, step: 0.05 };
}

// The GLB holds float32: a value the backend put on the limit (0.88 mm) comes back a hair below it.
const EPS = 1e-5;

export function isCritical(check: AnalysisCheck, value: number, info: AnalysisCheckInfo, limit: number): boolean {
  if (check === "overhang") return value > limit + EPS;
  if (check === "thickness") return value !== info.unread && value < limit - EPS;
  return value !== 0 && value < limit - EPS;
}

// Colours as the legend shows them (sRGB); THREE.Color takes them into the renderer's linear space.
export const SHADES = {
  plain: "#d6d9df",
  near: "#f2b33d",
  critical: "#e5484d",
  bed: "#3d7fd9",
  overlap: "#8f1d5b",
  unread: "#7c818c",
} as const;
const COLOURS = Object.fromEntries(Object.entries(SHADES).map(([k, v]) => [k, new THREE.Color(v)])) as Record<keyof typeof SHADES, THREE.Color>;

/** The colour of one value: critical red, amber as it nears the limit, plain grey when far from it. */
export function shade(check: AnalysisCheck, value: number, info: AnalysisCheckInfo, limit: number, out: THREE.Color): THREE.Color {
  if (check === "overhang") {
    if (value === info.bed) return out.copy(COLOURS.bed);
    if (value > limit + EPS) return out.copy(COLOURS.critical);
    const t = Math.max(0, value) / Math.max(limit, 1e-9);
    return out.copy(COLOURS.plain).lerp(COLOURS.near, t * t);
  }
  if (check === "thickness" && value === info.unread) return out.copy(COLOURS.unread);
  if (check === "clearance" && value < -(info.touch ?? 0)) return out.copy(COLOURS.overlap);
  if (check === "clearance" && value === 0) return out.copy(COLOURS.plain);
  if (value < limit - EPS) return out.copy(COLOURS.critical);
  // From the limit to twice the limit the colour fades from amber to grey.
  const t = Math.min(1, (value - limit) / Math.max(limit, 1e-9));
  return out.copy(COLOURS.near).lerp(COLOURS.plain, t);
}

const UNITS = { deg: "°", mm: " mm" } as const;

export function formatValue(check: AnalysisCheck, value: number, info: AnalysisCheckInfo): string {
  if (check === "overhang" && value === info.bed) return "on the bed";
  if (check === "thickness" && value === info.unread) return "no reading";
  if (check === "clearance") {
    if (value < -(info.touch ?? 0)) return `overlaps by ${(-value).toFixed(2)} mm`;
    if (value === 0) return "touches";
    if (info.range !== undefined && value >= info.range) return `${info.range} mm or more`;
  }
  return check === "overhang" ? `${value.toFixed(0)}°` : `${value.toFixed(2)}${UNITS[info.unit]}`;
}

/** An area as people read it: cm² from 1 cm² up, else whole mm². */
export function formatArea(mm2: number): string {
  return mm2 >= 100 ? `${(mm2 / 100).toFixed(1)} cm²` : `${Math.round(mm2)} mm²`;
}

/** Over every checked part: everything past Mechanic's limit, and the part of it that needs a fix. */
export function areas(analysis: AnalysisEvent, check: AnalysisCheck): { critical: number; finding: number } {
  let critical = 0;
  let finding = 0;
  for (const part of analysis.parts) {
    critical += part[check]?.critical_mm2 ?? 0;
    finding += part[check]?.finding_mm2 ?? part[check]?.critical_mm2 ?? 0;
  }
  return { critical, finding };
}

export function formatLimit(check: AnalysisCheck, limit: number, unit: AnalysisCheckInfo["unit"]): string {
  return check === "overhang" ? `${Math.round(limit)}°` : `${limit.toFixed(2).replace(/0$/, "")}${UNITS[unit]}`;
}
