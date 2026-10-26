// Which nodes of the 3D model a row of the CAD tree stands for (docs/events.md, `cad`): a row
// that lists its `nodes` (a standard part's) stands for those, a product built from a spec
// names its bodies per part and assembly in `bodies`, a generated part's rows are its bodies by
// name, and the drone's rows are its scene targets.
import type { CadEvent, CadNode } from "../../events/types";
import { normaliseName } from "../../lib/targets";

const CORNERS = ["front_left", "front_right", "rear_left", "rear_right"];

/** The FreeCAD drone's tree ids and the GLB nodes behind them. */
const DRONE_NODES: Record<string, string[]> = {
  plate: ["frame"],
  canopy: ["canopy"],
  motors: CORNERS.map((c) => `motor_${c}`),
  propellers: CORNERS.map((c) => `propeller_${c}`),
  flight_controller: ["flight_controller"],
  camera: ["camera"],
  battery: ["battery", "battery_strap"],
  antenna: ["antenna"],
};

/** Every part node of the drone, also for the recorded drone shown before the first CAD event. */
export const DRONE_PARTS = Object.values(DRONE_NODES).flat();

type Cad = Pick<CadEvent, "tree" | "bodies" | "part"> | null;

/** The part nodes (normalised names) one tree row stands for, its children's included. */
export function rowNodes(node: CadNode, cad: Cad): string[] {
  const bodies = cad?.bodies ?? [];
  const own = node.nodes
    ? node.nodes.map(normaliseName)
    : bodies.length
      ? bodies.filter((b) => b.part_id === node.id || b.group === node.id).map((b) => normaliseName(b.name))
      : cad && !cad.part
        ? (DRONE_NODES[node.id] ?? [])
        : [normaliseName(node.id)];
  return [...new Set([...own, ...node.children.flatMap((c) => rowNodes(c, cad))])];
}

/** Every part node the CAD tree names; the drone's before its first CAD event. */
export function treeNodes(cad: Cad, drone: boolean): string[] {
  if (!cad) return drone ? DRONE_PARTS : [];
  return [...new Set(cad.tree.flatMap((n) => rowNodes(n, cad)))];
}
