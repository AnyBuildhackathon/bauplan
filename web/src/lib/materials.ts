// PBR looks for generated products: the color stays the part's own (partColor), the
// surface follows its material, so PETG reads glossy, TPU matte and a load see-through.
import * as THREE from "three";
import type { CadNode } from "../events/types";

type Look = Partial<THREE.MeshPhysicalMaterialParameters>;

const LOOKS: Record<string, Look> = {
  PLA: { roughness: 0.62, metalness: 0, sheen: 0.25, sheenRoughness: 0.8 },
  PETG: { roughness: 0.35, metalness: 0, clearcoat: 0.3, clearcoatRoughness: 0.25 },
  ABS: { roughness: 0.5, metalness: 0 },
  ASA: { roughness: 0.5, metalness: 0 },
  NYLON: { roughness: 0.7, metalness: 0 },
  TPU: { roughness: 0.8, metalness: 0 },
  ALUMINIUM: { roughness: 0.32, metalness: 1 },
  STEEL: { roughness: 0.25, metalness: 1 },
  PCB: { roughness: 0.5, metalness: 0.1 },
  PLASTIC: { roughness: 0.45, metalness: 0 },
  // Standard parts, steel or brass by their color; drawn a hair in front, so an insert's top never flickers with the plastic it sits flush in.
  HARDWARE: { roughness: 0.45, metalness: 0.35, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 },
};
const DEFAULT: Look = { roughness: 0.55, metalness: 0.08 };

/** The look key for a material name or a free-text label ("45 g PETG", "Rubber foot (bought)"). */
export function materialKey(text: string): string | null {
  const t = text.toUpperCase();
  if (/ALUMIN/.test(t)) return "ALUMINIUM";
  if (/STEEL|STAINLESS|SCREW|BOLT|\bM\d\b/.test(t)) return "STEEL";
  if (/TPU|RUBBER|FOOT|FEET|SILICONE/.test(t)) return "TPU";
  if (/PCB|BOARD|ESP32|ARDUINO|CONTROLLER/.test(t)) return "PCB";
  if (/(BOUGHT)|MOTOR|SERVO|BATTERY|SENSOR|SWITCH/.test(t)) return "PLASTIC";
  for (const k of ["PETG", "PLA", "ABS", "ASA", "NYLON"]) if (new RegExp("\\b" + k + "\\b").test(t)) return k;
  return null;
}

/** GLTFLoader turns spaces in node names into underscores; compare names without either. */
const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

/** Node name to look key, from the `cad` tree labels (`Stand plate · 45 g PETG`, `Rubber foot ×4 (bought) · …`). */
export function materialsFromTree(tree: CadNode[]): Map<string, string> {
  const out = new Map<string, string>();
  const walk = (n: CadNode) => {
    // A standard part's row names its pieces.
    if (n.nodes) return n.nodes.forEach((node) => out.set(norm(node), "HARDWARE"));
    const name = n.label.split(" · ")[0].replace(/ ×\d+/, "").replace(/ \((bought|load)\)$/, "");
    const key = materialKey(n.label);
    // Only parts have a material, not the groups around them; the screws a part holds keep it a part.
    if (key && !n.children?.some((c) => !c.nodes)) out.set(norm(name), key);
    n.children?.forEach(walk);
  };
  tree.forEach(walk);
  return out;
}

/** The look for a mesh: its own node name or its nearest named ancestor in `byName`, else `fallback`. */
export function lookFor(o: THREE.Object3D, byName: Map<string, string>, fallback: string | null): string | null {
  for (let n: THREE.Object3D | null = o; n; n = n.parent) {
    const hit = n.name && byName.get(norm(n.name));
    if (hit) return hit;
  }
  return fallback;
}

/** A studio material: PBR by material key, a glass-like see-through look for loads (opacity below 1). */
export function pbrMaterial(key: string | null, color: string, opacity: number, emissive: THREE.Color): THREE.MeshPhysicalMaterial {
  const c = new THREE.Color(color);
  if (key === "TPU") c.multiplyScalar(0.7);
  if (key === "PCB" && color === "#c9ccd3") c.set("#1f6b45");
  if (key === "PLASTIC" && color === "#c9ccd3") c.set("#26282d");
  const see = opacity < 1;
  return new THREE.MeshPhysicalMaterial({
    ...(see ? { roughness: 0.08, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.05 } : (key && LOOKS[key]) || DEFAULT),
    color: c,
    emissive,
    emissiveIntensity: 0,
    transparent: see,
    opacity,
    depthWrite: !see,
  });
}
