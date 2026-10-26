// The studio's explode view (U12): the view bar's Explode switch and its slider (lib/ui `explode`, 0 to 1)
// pull the loaded assembly apart, each part along the way it goes on. It works on any GLB with one node per
// part: the FreeCAD drone (a propeller is a child of its motor and leaves it along the shaft), the gripper,
// SolidCraft designs and every spec product. The first time the model explodes, explodePlan.ts works out from
// the parts' own faces, the standard parts' axes and the joints where each part goes: a screw out of its hole
// along its axis, a part on a joint along the joint's axis, a part off the faces it sits on, anything else away
// from the middle; the parts of one assembly group leave as one, then spread. The parts glide there on a spring
// and keep their colours, the surface check's colour layer and the section's cut. Labels ride with their parts,
// fading in past the middle (or at any amount with the studio's Labels switch), and a hovered part glows and
// names itself in the card (PartCard). While the studio measures, the pointer belongs to the tool.
import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { create } from "zustand";
import { normaliseName } from "../../lib/targets";
import { useUi } from "../../lib/ui";
import { useAnchorMap } from "./anchors";
import { countBases, findContacts, planExplode, springStep, type Basis, type PlanJoint, type PlanPart, type Vec3 } from "./explodePlan";
import { usePrefersReducedMotion } from "./GridStage";

export interface PieceSpec {
  node: THREE.Object3D;
  /** Stable key: the GLB node name. */
  key: string;
  /** Pill text when exploded; empty for no label. */
  label: string;
  /** The name a hover shows; defaults to the label. */
  name?: string;
  /** Parts with the same group move together (an assembly of a spec product). */
  group?: string | null;
  /** Other names the pointer and the camera focus may use for it (a spec part id). */
  aliases?: string[];
  /** The part everything else leaves from (the drone's frame); else the largest part. */
  isBase?: boolean;
  /** A load the product holds (the phone on a stand): never the base. */
  load?: boolean;
  /** A standard part: the way out of its hole in the model file's frame, and the keys of the parts that may hold it. */
  fastener?: { out: Vec3; holders: string[] } | null;
  /** The joints it moves on, axis and place in the model file's frame, with the keys of the parts on their other side. */
  joints?: PlanJoint[];
}

interface Piece extends PieceSpec {
  base: THREE.Vector3;
  /** Parent-local offset at full explode, once the explode is planned. */
  offset: THREE.Vector3;
  /** Child of the node at its bounding-box centre: anchor, label and camera focus. */
  center: THREE.Group;
  radius: number;
  /** Its box and centre at rest, in the frame the model's root sits in. */
  box: THREE.Box3;
  middle: THREE.Vector3;
  /** The piece it hangs under in the file (a propeller under its motor), if any. */
  parent: Piece | null;
}

/** What the pointer is over in the explode view; a click pins it so its shop link can be clicked. */
export const useExplodeHover = create<{
  key: string | null;
  label: string;
  x: number;
  y: number;
  pinned: boolean;
  hover: (key: string | null, label?: string, x?: number, y?: number) => void;
  pin: (key: string | null, label?: string, x?: number, y?: number) => void;
}>((set, get) => ({
  key: null,
  label: "",
  x: 0,
  y: 0,
  pinned: false,
  hover: (key, label = "", x = 0, y = 0) => {
    if (get().pinned) return;
    set(key ? { key, label, x, y } : { key: null });
  },
  pin: (key, label = "", x = 0, y = 0) => set(key ? { key, label, x, y, pinned: true } : { key: null, pinned: false }),
}));

/** How the live explode view takes the model apart: how many parts leave which way, once it first explodes. */
export const useExplodePlan = create<{ counts: Record<Exclude<Basis, "base">, number> | null }>(() => ({ counts: null }));

/** Every focusable piece of the live explode view, by normalised name and alias. */
const focusable = new Map<string, Piece>();

/** The explode amount the live model shows right now, as it glides to the switch's amount. */
let shownAmount = 0;
export const shownExplode = () => shownAmount;

const UP = new THREE.Vector3(0, 1, 0);
/** A part with more triangles is sampled for its mating faces, so a detailed bought model plans in a few frames. */
const MAX_TRIANGLES = 24000;

/** The pieces at rest: boxes, centres and the label anchors, in the frame the model's root sits in. */
function piecesOf(root: THREE.Object3D, specs: PieceSpec[]): Piece[] {
  // A remount while exploded: back to rest first, so the boxes are the assembled ones.
  for (const s of specs) if (s.node.userData.restPosition) s.node.position.copy(s.node.userData.restPosition as THREE.Vector3);
  root.updateMatrixWorld(true);
  const frame = root.parent?.matrixWorld ?? new THREE.Matrix4();
  const toFrame = frame.clone().invert();
  const byNode = new Map<THREE.Object3D, Piece>();
  const pieces = specs.map((spec) => {
    const box = new THREE.Box3().setFromObject(spec.node).applyMatrix4(toFrame);
    const middle = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const center = new THREE.Group();
    center.position.copy(spec.node.worldToLocal(middle.clone().applyMatrix4(frame)));
    const piece: Piece = { ...spec, base: spec.node.position.clone(), offset: new THREE.Vector3(), center, radius: Math.max(1e-6, size.length() / 2), box, middle, parent: null };
    byNode.set(spec.node, piece);
    return piece;
  });
  for (const p of pieces) {
    for (let o = p.node.parent; o && o !== root.parent; o = o.parent) {
      const hit = byNode.get(o);
      if (hit) {
        p.parent = hit;
        break;
      }
    }
  }
  const R = radiusOf(pieces);
  for (const p of pieces) labelEdge(p, UP, R, frame);
  return pieces;
}

/** Puts the label anchor where a ray from the piece's centre along `out` leaves its box, a little beyond; `frame` is
 * the world matrix of the frame the boxes are in. */
function labelEdge(p: Piece, out: THREE.Vector3, R: number, frame: THREE.Matrix4) {
  let reach = Infinity;
  for (const axis of ["x", "y", "z"] as const) {
    if (Math.abs(out[axis]) < 1e-6) continue;
    reach = Math.min(reach, ((out[axis] > 0 ? p.box.max[axis] : p.box.min[axis]) - p.middle[axis]) / out[axis]);
  }
  const edge = p.middle.clone().addScaledVector(out, (Number.isFinite(reach) ? reach : p.radius) + R * 0.05);
  p.center.userData.explodeTop = p.node.worldToLocal(edge.applyMatrix4(frame));
}

/** The radius of the pieces' bounding sphere together. */
function radiusOf(pieces: Piece[]): number {
  const all = new THREE.Box3();
  for (const p of pieces) all.union(p.box);
  return all.getBoundingSphere(new THREE.Sphere()).radius || 1;
}

const vec = (v: THREE.Vector3): Vec3 => [v.x, v.y, v.z];

/**
 * Plans where every piece goes (explodePlan.ts) from its triangles at rest, the standard parts' axes and the joints,
 * in the frame the model's root sits in (Y up, like the scene), and sets each piece's offset in its node's own
 * parent frame. Returns how far the whole model rises at full explode, so nothing ends up under the floor.
 */
function planPieces(root: THREE.Object3D, pieces: Piece[]): number {
  // At rest, also when the assembly is still flying in (AssemblyMotion.tsx lands it next).
  for (const p of pieces) p.node.position.copy(p.base);
  root.updateMatrixWorld(true);
  const frame = root.parent?.matrixWorld ?? new THREE.Matrix4();
  const toFrame = frame.clone().invert();
  const nodes = new Set(pieces.map((p) => p.node));
  const parts: PlanPart[] = pieces.map((p) => {
    const tris: number[] = [];
    const m = new THREE.Matrix4();
    const v = new THREE.Vector3();
    const visit = (o: THREE.Object3D) => {
      if (o !== p.node && nodes.has(o)) return;
      if (o instanceof THREE.Mesh && !o.userData.sectionCap && !o.userData.analysisLayer) {
        const g = o.geometry as THREE.BufferGeometry;
        const pos = g.getAttribute("position");
        if (pos) {
          m.multiplyMatrices(toFrame, o.matrixWorld);
          const index = g.getIndex();
          const count = index ? index.count : pos.count;
          const triangles = Math.floor(count / 3);
          const stride = Math.max(1, Math.ceil(triangles / MAX_TRIANGLES));
          for (let t = 0; t < triangles; t += stride) {
            for (let c = 0; c < 3; c++) {
              const i = index ? index.getX(t * 3 + c) : t * 3 + c;
              v.fromBufferAttribute(pos, i).applyMatrix4(m);
              tris.push(v.x, v.y, v.z);
            }
          }
        }
      }
      for (const child of o.children) visit(child);
    };
    visit(p.node);
    const fileDir = (d: Vec3) => vec(new THREE.Vector3(...d).transformDirection(root.matrix));
    const joints: PlanJoint[] = (p.joints ?? []).map((j) => ({
      axis: fileDir(j.axis),
      at: j.at ? vec(new THREE.Vector3(...j.at).applyMatrix4(root.matrix)) : null,
      parents: j.parents,
    }));
    // A piece under another in the file rides on it, as on a joint: a propeller leaves its motor along the shaft.
    if (p.parent) {
      const d = p.middle.clone().sub(p.parent.middle);
      joints.push({ axis: vec(d.lengthSq() > (p.radius * 0.2) ** 2 ? d.normalize() : UP), at: null, parents: [p.parent.key] });
    }
    return {
      key: p.key,
      triangles: Float32Array.from(tris),
      min: vec(p.box.min),
      max: vec(p.box.max),
      group: p.parent ? null : p.group,
      isBase: p.isBase,
      load: p.load,
      fastener: p.fastener ? { out: fileDir(p.fastener.out), holders: p.fastener.holders } : null,
      joints,
    };
  });
  const R = radiusOf(pieces);
  const plan = planExplode(parts, findContacts(parts, R * 0.004), [0, 1, 0]);
  pieces.forEach((p, i) => {
    const planned = plan.parts[i];
    // Its own move: a piece under another one already rides along with it.
    const own = new THREE.Vector3(...planned.offset);
    if (p.parent) own.sub(new THREE.Vector3(...plan.parts[pieces.indexOf(p.parent)].offset));
    // Into the frame the node's position lives in, scale and rotation included.
    const parent = p.node.parent!;
    const origin = p.node.getWorldPosition(new THREE.Vector3());
    const moved = origin.clone().applyMatrix4(toFrame).add(own).applyMatrix4(frame);
    p.offset.copy(parent.worldToLocal(moved).sub(parent.worldToLocal(origin)));
    // The label sits on the side the part flies out to, so neighbouring labels part ways too.
    const out = new THREE.Vector3(...planned.offset);
    labelEdge(p, out.lengthSq() > 1e-12 ? out.normalize() : UP, R, frame);
  });
  useExplodePlan.setState({ counts: countBases(plan) });
  return plan.lift;
}

/** A rounded pill label drawn into a canvas texture, shared with the build guide. */
export function pillTexture(text: string, { bg, fg, weight = 700 }: { bg: string; fg: string; weight?: number }) {
  const scale = 3;
  const c = document.createElement("canvas");
  const ctx = c.getContext("2d")!;
  const font = `${weight} ${13 * scale}px "Inter Tight", sans-serif`;
  ctx.font = font;
  const w = Math.ceil(ctx.measureText(text).width + 22 * scale);
  const h = 26 * scale;
  c.width = w;
  c.height = h;
  ctx.font = font;
  ctx.fillStyle = bg;
  ctx.beginPath();
  ctx.roundRect(0, 0, w, h, h / 2);
  ctx.fill();
  ctx.fillStyle = fg;
  ctx.textBaseline = "middle";
  ctx.fillText(text, 11 * scale, h / 2 + scale);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return { texture: t, aspect: w / h };
}

function labelSprite(text: string): THREE.Sprite {
  const { texture, aspect } = pillTexture(text, { bg: "rgba(255,255,255,0.96)", fg: "#1f1f1f" });
  const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false, depthWrite: false, sizeAttenuation: false, toneMapped: false, opacity: 0 });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(0.02 * aspect, 0.02, 1);
  sprite.center.set(0.5, 0.5);
  sprite.renderOrder = 20;
  return sprite;
}

const AGENT = new THREE.Color("#ff8a3d");

/**
 * Makes `root` explodable: moves the pieces with the slider, registers their anchors for the
 * pointer and the camera focus, labels them, and reports hover and click. Spread the returned
 * handlers onto the <primitive> that renders `root`.
 */
export function useExplode(root: THREE.Object3D, specs: PieceSpec[], opts: { glow?: boolean } = {}) {
  const anchors = useAnchorMap();
  const pieces = useMemo(() => piecesOf(root, specs), [root, specs]);
  // Planned the first time the model explodes, so loading a model never waits for it.
  const lift = useRef<number | null>(null);
  const motion = useRef({ x: 0, v: 0 });
  const still = usePrefersReducedMotion();
  const layer = useRef<THREE.Group>(null);
  // Labels live beside the model, not in it, so they never count towards a part's bounding box.
  const labelRoot = useMemo(() => new THREE.Group(), []);
  const labels = useRef<(THREE.Sprite | null)[]>([]);
  const shown = useRef(-1);

  // Attached in an effect, so a remount (React's strict mode) attaches them again.
  useEffect(() => {
    for (const p of pieces) {
      p.node.add(p.center);
      // Where the part sits assembled, so a click on it reads as a place on the build (studio/frame.ts).
      p.node.userData.restPosition = p.base;
      for (const name of [p.key, ...(p.aliases ?? [])]) focusable.set(normaliseName(name), p);
    }
    labels.current = pieces.map((p) => (p.label ? labelSprite(p.label) : null));
    for (const l of labels.current) if (l) labelRoot.add(l);
    shown.current = -1;
    lift.current = null;
    motion.current = { x: 0, v: 0 };
    useExplodePlan.setState({ counts: null });
    return () => {
      for (const p of pieces) {
        for (const name of [p.key, ...(p.aliases ?? [])]) if (focusable.get(normaliseName(name)) === p) focusable.delete(normaliseName(name));
        p.node.position.copy(p.base);
        delete p.node.userData.restPosition;
        p.center.removeFromParent();
      }
      for (const l of labels.current) {
        l?.removeFromParent();
        l?.material.map?.dispose();
        l?.material.dispose();
      }
      labels.current = [];
    };
  }, [pieces, labelRoot]);

  // Any product's parts become pointer targets by name and id; the drone has its own anchors.
  useEffect(() => {
    if (!anchors) return;
    const names: string[] = [];
    for (const p of pieces) {
      for (const name of [p.key, ...(p.aliases ?? [])]) {
        const key = normaliseName(name);
        if (anchors.has(key)) continue;
        anchors.set(key, { object: p.center, radius: p.radius * 0.6 });
        names.push(key);
      }
    }
    return () => names.forEach((n) => anchors.delete(n));
  }, [anchors, pieces]);

  const hoverKey = useExplodeHover((s) => s.key);
  useEffect(() => {
    if (!opts.glow) return;
    for (const p of pieces) {
      const on = p.key === hoverKey;
      p.node.traverse((o) => {
        if (!(o instanceof THREE.Mesh)) return;
        const m = o.material as THREE.MeshStandardMaterial;
        if (!m.emissive) return;
        m.emissive.copy(AGENT);
        m.emissiveIntensity = on ? 0.32 : 0;
      });
    }
  }, [pieces, hoverKey, opts.glow]);

  const top = useMemo(() => new THREE.Vector3(), []);
  useFrame((_, dt) => {
    const { explode: target, studio } = useUi.getState();
    if (target > 0 && lift.current === null) lift.current = planPieces(root, pieces);
    // The parts glide to the switch's amount: smooth to start and to stop, never past it.
    const m = motion.current;
    [m.x, m.v] = still ? [target, 0] : springStep(m.x, m.v, target, Math.min(dt, 0.1));
    const e = m.x;
    shownAmount = e;
    if (e !== shown.current) {
      shown.current = e;
      for (const p of pieces) p.node.position.copy(p.base).addScaledVector(p.offset, e);
      if (layer.current) layer.current.position.y = (lift.current ?? 0) * e;
    }
    const alpha = studio.labels ? 1 : Math.max(0, Math.min(1, (e - 0.45) / 0.3));
    pieces.forEach((p, i) => {
      const l = labels.current[i];
      if (!l) return;
      // A part hidden from the assembly tree (StudioRig) takes its label along.
      l.material.opacity = p.node.userData.studioHidden ? 0 : alpha;
      if (alpha <= 0) return;
      top.copy(p.center.userData.explodeTop as THREE.Vector3);
      p.node.localToWorld(top);
      l.position.copy(labelRoot.worldToLocal(top));
    });
  });

  const pieceOf = (object: THREE.Object3D): Piece | null => {
    // The deepest piece wins: a propeller over its motor.
    for (let o: THREE.Object3D | null = object; o; o = o.parent) {
      const hit = pieces.find((p) => p.node === o);
      if (hit) return hit;
    }
    return null;
  };

  const selecting = () => useUi.getState().tool === "select";
  return {
    labels: labelRoot,
    layer,
    onPointerMove: (e: ThreeEvent<PointerEvent>) => {
      if (!selecting()) return;
      const p = pieceOf(e.object);
      e.stopPropagation();
      useExplodeHover.getState().hover(p?.key ?? null, p ? p.name || p.label || p.key : "", e.nativeEvent.clientX, e.nativeEvent.clientY);
    },
    onPointerOut: () => useExplodeHover.getState().hover(null),
    onClick: (e: ThreeEvent<MouseEvent>) => {
      if (!selecting()) return;
      const p = pieceOf(e.object);
      e.stopPropagation();
      const s = useExplodeHover.getState();
      if (!p || (s.pinned && s.key === p.key)) return s.pin(null);
      s.pin(p.key, p.name || p.label || p.key, e.nativeEvent.clientX, e.nativeEvent.clientY);
    },
    onPointerMissed: () => useExplodeHover.getState().pin(null),
  };
}

/** Wraps the model: its parts explode with the slider and answer hover and click. */
export function ExplodeLayer({ root, specs, glow, children }: { root: THREE.Object3D; specs: PieceSpec[]; glow?: boolean; children: React.ReactNode }) {
  const { labels, layer, ...handlers } = useExplode(root, specs, { glow });
  return (
    <group ref={layer} {...handlers}>
      {children}
      <primitive object={labels} />
    </group>
  );
}

/**
 * Pulls the camera back while the model explodes, so the spread parts stay in frame, and turns
 * it to the part Mechanic focuses on. Works with any OrbitControls set as default controls.
 */
export function ExplodeCamera({ maxDistance }: { maxDistance?: number }) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3; update: () => void; autoRotate: boolean; maxDistance: number } | null;
  const zoom = useRef(1);
  const focus = useUi((s) => s.focus);
  const move = useRef<{ target: THREE.Vector3; dist: number; until: number } | null>(null);
  const home = useRef<THREE.Vector3 | null>(null);

  useLayoutEffect(() => {
    if (controls && maxDistance) controls.maxDistance = maxDistance * 1.9;
  }, [controls, maxDistance]);

  useEffect(() => {
    if (!focus || !controls) return;
    const piece = focusable.get(normaliseName(focus.part)) ?? [...focusable.entries()].find(([k]) => k.includes(normaliseName(focus.part)))?.[1];
    if (!piece) return;
    home.current ??= controls.target.clone();
    const target = piece.center.getWorldPosition(new THREE.Vector3());
    move.current = { target, dist: Math.max(piece.radius * 5, camera.position.distanceTo(controls.target) * 0.55), until: performance.now() + 9000 };
  }, [focus, controls, camera]);

  useFrame(() => {
    if (!controls) return;
    const want = 1 + 0.9 * shownAmount;
    const offset = camera.position.clone().sub(controls.target);
    if (Math.abs(want - zoom.current) > 1e-4) {
      offset.multiplyScalar(want / zoom.current);
      zoom.current = want;
    }
    const m = move.current;
    if (m && performance.now() < m.until) {
      controls.autoRotate = false;
      controls.target.lerp(m.target, 0.08);
      const len = offset.length();
      offset.setLength(len + (m.dist * want - len) * 0.08);
    } else if (m) {
      // The focus ends: back to the whole model, standing still.
      move.current = null;
      if (home.current) controls.target.copy(home.current);
      home.current = null;
    }
    camera.position.copy(controls.target).add(offset);
    controls.update();
  });
  return null;
}
