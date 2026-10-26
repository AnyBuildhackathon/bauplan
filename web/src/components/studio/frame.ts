// The build's frame in the studio's 3D scene: millimetres with Z up, the frame Mechanic's numbers,
// cad_view and the studio notes use. A model file is millimetres with Z up (a generated part, standing
// Y up in the scene) or metres with Y up (the drone); its root object carries `userData.glbRoot`. A point
// is read in its part's own place: an exploded part counts where it sits assembled (explode.tsx keeps
// `userData.restPosition`). With the section on, a click goes through what the cut took away.
import * as THREE from "three";
import { useSession } from "../../events/store";
import { normaliseName } from "../../lib/targets";
import { useStudio } from "./studio";

export type Vec3 = [number, number, number];
export type Axis = "x" | "y" | "z";

/** How a model file maps to the build's frame. */
export interface ModelFrame {
  /** Millimetres with Z up (a generated part); otherwise metres with Y up and the nose at -Z (the drone). */
  zUp: boolean;
  /** Metres per unit of the file. */
  unit: number;
}

// Notes keep a thousandth of a millimetre; what shows them rounds, so a chip and the readout agree.
const round3 = (v: number) => Math.round(v * 1000) / 1000 || 0;

/** The file's root above an object: its frame is the file's own. */
export function glbRoot(object: THREE.Object3D | null): THREE.Object3D | null {
  for (let o = object; o; o = o.parent) if (o.userData.glbRoot) return o;
  return null;
}

/** File coordinates to the build's mm. */
export function fileToBuild(p: THREE.Vector3, frame: ModelFrame): Vec3 {
  const k = frame.unit * 1000;
  return frame.zUp ? [round3(p.x * k), round3(p.y * k), round3(p.z * k)] : [round3(p.x * k), round3(-p.z * k), round3(p.y * k)];
}

/** A point on `object` (in world space) in the build's mm, with every exploded part back in its place. */
export function toBuild(object: THREE.Object3D, world: THREE.Vector3, frame: ModelFrame): Vec3 {
  const p = object.worldToLocal(world.clone());
  const m = new THREE.Matrix4();
  for (let o: THREE.Object3D | null = object; o && !o.userData.glbRoot; o = o.parent) {
    const rest = o.userData.restPosition as THREE.Vector3 | undefined;
    p.applyMatrix4(m.compose(rest ?? o.position, o.quaternion, o.scale));
  }
  return fileToBuild(p, frame);
}

/** A direction in the scene (a face normal, where the camera stands) along the build's axes. Both kinds of file
 * stand Y up in the scene with the build's -Y (a product's front; the drone's tail) towards +Z. */
export function dirToBuild(world: THREE.Vector3): Vec3 {
  const d = world.clone().normalize();
  const r = (v: number) => Math.round(v * 1000) / 1000 || 0;
  return [r(d.x), r(-d.z), r(d.y)];
}

/** The build's axis as a direction in the file's own frame. */
export function axisInFile(axis: Axis, frame: ModelFrame): THREE.Vector3 {
  if (axis === "x") return new THREE.Vector3(1, 0, 0);
  if (frame.zUp) return axis === "y" ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(0, 0, 1);
  return axis === "y" ? new THREE.Vector3(0, 0, -1) : new THREE.Vector3(0, 1, 0);
}

function visible(o: THREE.Object3D | null): boolean {
  for (; o; o = o.parent) if (!o.visible) return false;
  return true;
}

/** False for a hit on what the section cut away. */
export function keptByCut(hit: THREE.Intersection): boolean {
  const clip = useStudio.getState().clip;
  return !clip || clip.distanceToPoint(hit.point) >= -1e-6 * Math.max(1, Math.abs(clip.constant));
}

export interface ModelHit {
  /** The mesh that was hit; for a cut face, the part's own mesh. */
  object: THREE.Object3D;
  point: THREE.Vector3;
  /** The face's outward normal in world space. */
  normal: THREE.Vector3 | null;
  /** On the face the section cut. */
  cut: boolean;
}

/** The first visible point of the model under the ray, minding hidden parts and the section. */
export function hitModel(raycaster: THREE.Raycaster, model: THREE.Object3D): ModelHit | null {
  const clip = useStudio.getState().clip;
  for (const hit of raycaster.intersectObject(model, true)) {
    if (!(hit.object instanceof THREE.Mesh) || !visible(hit.object) || !keptByCut(hit)) continue;
    const normal = hit.face ? hit.face.normal.clone().applyMatrix3(new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld)).normalize() : null;
    // Through a cut the ray meets a part from inside: what shows there is the cut face, on the plane itself.
    if (clip && (hit.object.userData.sectionCap || (normal && normal.dot(raycaster.ray.direction) > 0))) {
      const point = raycaster.ray.intersectPlane(clip, new THREE.Vector3());
      const part = hit.object.userData.sectionCap ? (hit.object.parent ?? hit.object) : hit.object;
      if (point) return { object: part, point, normal: clip.normal.clone().negate(), cut: true };
      continue;
    }
    return { object: hit.object, point: hit.point.clone(), normal, cut: false };
  }
  return null;
}

/** The part a mesh belongs to: its nearest node the assembly tree knows, else the file's top node above it. */
export function partNode(object: THREE.Object3D): THREE.Object3D {
  const known = useStudio.getState().nodes;
  let top = object;
  for (let o: THREE.Object3D | null = object; o && !o.userData.glbRoot; o = o.parent) {
    if (known[normaliseName(o.name)]) return o;
    top = o;
  }
  return top;
}

const pretty = (raw: string) => raw.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** A part node's name as the studio shows it: the product's body or part name, else the node's own name. */
export function partLabel(node: string): { name: string; partId: string | null } {
  const bodies = useSession.getState().cad?.bodies;
  const body = bodies?.find((b) => normaliseName(b.name) === normaliseName(node));
  if (body) return { name: body.name, partId: body.part_id };
  return { name: pretty(node), partId: null };
}
