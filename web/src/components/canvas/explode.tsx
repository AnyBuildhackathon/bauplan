// The Model tab's explode view: one slider (lib/ui `explode`, 0 to 1) pulls every part of
// the loaded assembly out from its base, reverse-engineering style. It works on any GLB with
// one node per part: the FreeCAD drone (a propeller is a child of its motor and rides along),
// the gripper and every spec product (parts of one assembly group move as a unit, then
// spread inside it). Directions come from the parts' bounding boxes: away from the largest
// part, straight up when a part sits right on top of it. Labels fade in past the middle,
// and a hovered part glows and names itself in the card (PartCard).
import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { create } from "zustand";
import { normaliseName } from "../../lib/targets";
import { useUi } from "../../lib/ui";
import { useAnchorMap } from "./anchors";

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
}

interface Piece extends PieceSpec {
  base: THREE.Vector3;
  /** Parent-local offset at full explode. */
  offset: THREE.Vector3;
  /** Child of the node at its bounding-box centre: anchor, label and camera focus. */
  center: THREE.Group;
  radius: number;
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

/** Every focusable piece of the live explode view, by normalised name and alias. */
const focusable = new Map<string, Piece>();

const UP = new THREE.Vector3(0, 1, 0);

function boxOf(node: THREE.Object3D): THREE.Box3 {
  return new THREE.Box3().setFromObject(node);
}

/** Bounding boxes in world space; call with the assembly at rest. */
function plan(root: THREE.Object3D, specs: PieceSpec[]): { pieces: Piece[]; lift: number } {
  root.updateMatrixWorld(true);
  const nodes = new Set(specs.map((s) => s.node));
  const parentPiece = (node: THREE.Object3D) => {
    for (let p = node.parent; p && p !== root.parent; p = p.parent) if (nodes.has(p)) return p;
    return null;
  };
  const info = specs.map((spec) => {
    const box = boxOf(spec.node);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    return { spec, box, center, radius: Math.max(1e-6, size.length() / 2), parent: parentPiece(spec.node) };
  });
  const all = new THREE.Box3();
  for (const i of info) all.union(i.box);
  const R = all.getBoundingSphere(new THREE.Sphere()).radius || 1;

  // The base everything leaves from: the one marked, else the largest piece that stands on the floor
  // (a base plate, not the phone a stand holds).
  const top = info.filter((i) => !i.parent && !i.spec.load);
  const floor = Math.min(...top.map((i) => i.box.min.y));
  const grounded = top.filter((i) => i.box.min.y <= floor + R * 0.15);
  const base = top.find((i) => i.spec.isBase) ?? grounded.sort((a, b) => b.radius - a.radius)[0];

  // Units move as one: a group, or a lone top-level piece.
  const units = new Map<string, typeof info>();
  for (const i of info) {
    if (i.parent) continue;
    // The base's own group comes apart piece by piece; other groups leave it as one.
    const id = i.spec.group && i.spec.group !== base?.spec.group ? `g:${i.spec.group}` : `p:${i.spec.key}`;
    units.set(id, [...(units.get(id) ?? []), i]);
  }
  const unitBox = (members: typeof info) => members.reduce((b, m) => b.union(m.box), new THREE.Box3());
  const C = base ? base.center.clone() : all.getCenter(new THREE.Vector3());
  const world = new Map<THREE.Object3D, THREE.Vector3>();
  let stack = 0;
  for (const members of units.values()) {
    const ub = unitBox(members);
    const uc = ub.getCenter(new THREE.Vector3());
    const isBase = members.includes(base);
    const d = uc.clone().sub(C);
    let unitOffset = new THREE.Vector3();
    if (!isBase) {
      // Right on the base: straight up, or straight down for a part hanging below it (a battery).
      const dir = d.length() > R * 0.08 ? d.clone().normalize() : UP.clone().multiplyScalar(d.y < 0 ? -1 : 1);
      // Parts sitting in the same spot stack up instead of landing on each other.
      if (d.length() <= R * 0.08) stack++;
      unitOffset = dir.multiplyScalar(d.length() * 0.75 + R * (0.22 + 0.14 * Math.max(0, stack - 1)));
    }
    for (const m of members) {
      const inner = m.center.clone().sub(uc);
      const spread = members.length > 1 && !(isBase && m === base) ? (inner.length() > 1e-6 ? inner.normalize() : UP.clone()).multiplyScalar(m.radius * 0.6 + R * 0.08) : new THREE.Vector3();
      world.set(m.spec.node, unitOffset.clone().add(spread));
    }
  }
  for (const i of info) {
    if (!i.parent) continue;
    const parentInfo = info.find((p) => p.spec.node === i.parent)!;
    const d = i.center.clone().sub(parentInfo.center);
    const dir = d.length() > i.radius * 0.2 ? d.normalize() : UP.clone();
    world.set(i.spec.node, dir.multiplyScalar(i.radius * 0.6 + R * 0.08));
  }

  // Parts that leave downwards (a battery under the frame) would sink through the floor: lift the model instead.
  const drop = Math.min(0, ...info.map((i) => i.box.min.y + (world.get(i.spec.node)?.y ?? 0) - all.min.y));
  const pieces = info.map((i) => {
    const node = i.spec.node;
    const offsetWorld = world.get(node) ?? new THREE.Vector3();
    // The offset in the frame the node's position lives in (its parent), scale and rotation included.
    const parent = node.parent!;
    const origin = node.getWorldPosition(new THREE.Vector3());
    const local = parent.worldToLocal(origin.clone().add(offsetWorld)).sub(parent.worldToLocal(origin.clone()));
    const center = new THREE.Group();
    center.position.copy(node.worldToLocal(i.center.clone()));
    // The label sits on the side the part flies out to, so neighbouring labels part ways too.
    const out = offsetWorld.lengthSq() > 1e-12 ? offsetWorld.clone().normalize() : UP;
    // Where a ray from the centre along that side leaves the part's box.
    let reach = Infinity;
    for (const axis of ["x", "y", "z"] as const) {
      if (Math.abs(out[axis]) < 1e-6) continue;
      reach = Math.min(reach, ((out[axis] > 0 ? i.box.max[axis] : i.box.min[axis]) - i.center[axis]) / out[axis]);
    }
    const edge = i.center.clone().addScaledVector(out, (Number.isFinite(reach) ? reach : i.radius) + R * 0.05);
    center.userData.explodeTop = node.worldToLocal(edge);
    return { ...i.spec, base: node.position.clone(), offset: local, center, radius: i.radius };
  });
  return { pieces, lift: -drop * root.scale.y };
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
  const { pieces, lift } = useMemo(() => plan(root, specs), [root, specs]);
  const layer = useRef<THREE.Group>(null);
  // Labels live beside the model, not in it, so they never count towards a part's bounding box.
  const labelRoot = useMemo(() => new THREE.Group(), []);
  const labels = useRef<(THREE.Sprite | null)[]>([]);
  const shown = useRef(-1);

  // Attached in an effect, so a remount (React's strict mode) attaches them again.
  useEffect(() => {
    for (const p of pieces) {
      p.node.add(p.center);
      for (const name of [p.key, ...(p.aliases ?? [])]) focusable.set(normaliseName(name), p);
    }
    labels.current = pieces.map((p) => (p.label ? labelSprite(p.label) : null));
    for (const l of labels.current) if (l) labelRoot.add(l);
    shown.current = -1;
    return () => {
      for (const p of pieces) {
        for (const name of [p.key, ...(p.aliases ?? [])]) if (focusable.get(normaliseName(name)) === p) focusable.delete(normaliseName(name));
        p.node.position.copy(p.base);
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
  useFrame(() => {
    const e = useUi.getState().explode;
    if (e !== shown.current) {
      shown.current = e;
      for (const p of pieces) p.node.position.copy(p.base).addScaledVector(p.offset, e);
      if (layer.current) layer.current.position.y = lift * e;
      const alpha = Math.max(0, Math.min(1, (e - 0.45) / 0.3));
      for (const l of labels.current) if (l) l.material.opacity = alpha;
    }
    if (e <= 0.45) return;
    pieces.forEach((p, i) => {
      const l = labels.current[i];
      if (!l) return;
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

  return {
    labels: labelRoot,
    layer,
    onPointerMove: (e: ThreeEvent<PointerEvent>) => {
      const p = pieceOf(e.object);
      e.stopPropagation();
      useExplodeHover.getState().hover(p?.key ?? null, p ? p.name || p.label || p.key : "", e.nativeEvent.clientX, e.nativeEvent.clientY);
    },
    onPointerOut: () => useExplodeHover.getState().hover(null),
    onClick: (e: ThreeEvent<MouseEvent>) => {
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
  const move = useRef<{ target: THREE.Vector3; dist: number; until: number; rotating: boolean } | null>(null);
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
    const rotating = move.current?.rotating ?? controls.autoRotate;
    move.current = { target, dist: Math.max(piece.radius * 5, camera.position.distanceTo(controls.target) * 0.55), until: performance.now() + 9000, rotating };
  }, [focus, controls, camera]);

  useFrame(() => {
    if (!controls) return;
    const want = 1 + 0.9 * useUi.getState().explode;
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
      // The focus ends: back to the turntable around the model.
      move.current = null;
      controls.autoRotate = m.rotating;
      if (home.current) controls.target.copy(home.current);
      home.current = null;
    }
    camera.position.copy(controls.target).add(offset);
    controls.update();
  });
  return null;
}
