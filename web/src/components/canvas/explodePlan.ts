// Where each part of an exploded model goes (U12): the way it leaves and how far, worked out once per model in the
// model file's own frame from the assembly data and the parts' own faces. A part leaves the way it goes on:
// - a standard part (screw, nut, washer, insert) along its own axis, out of its hole in the part that holds it;
// - a part on a joint along the joint's axis, away from the part it turns or slides on;
// - a part that sits against another along the normal of the faces they mate with, the way those faces leave free
//   (out of a pocket through its opening);
// - anything else from the assembly centre through its own centre.
// The largest part standing on the floor stays where it is (or the part marked as the base). Every other part first
// rides along with the part it leaves from, then moves on its own just far enough to clear what is in its way, plus
// a gap: a screw rides on its lid and then comes out of it, and the parts of one assembly group leave as one before
// they spread. Plain numbers only, so node's test runner checks it (web/unit/explodePlan.test.ts).

export type Vec3 = [number, number, number];
/** Why a part leaves the way it does. */
export type Basis = "base" | "fastener" | "joint" | "mate" | "centre";

export interface PlanJoint {
  /** The joint's axis in the model frame, either sign. */
  axis: Vec3;
  /** Where the joint sits, when known. */
  at: Vec3 | null;
  /** Keys of the parts on its other side, the side nearer the base. */
  parents: string[];
}

export interface PlanPart {
  key: string;
  /** The part's triangles at rest in the model frame, nine numbers each; empty for a part known by its box only. */
  triangles: Float32Array;
  min: Vec3;
  max: Vec3;
  /** Parts of one group (an assembly of the spec, a component on a joint) leave as one unit, then spread. */
  group?: string | null;
  /** The part everything else leaves from (the drone's frame). */
  isBase?: boolean;
  /** A load the product holds (the phone on a stand): never the base. */
  load?: boolean;
  /** A standard part: the way out of its hole and the parts that may hold it. */
  fastener?: { out: Vec3; holders: string[] } | null;
  joints?: PlanJoint[];
}

export interface Contact {
  /** The part that leaves (a) and the part whose face it sits against (b), as indices. */
  a: number;
  b: number;
  /** b's face normal, pointing into a: the way a can leave that face. */
  normal: Vec3;
  /** The area the two faces share. */
  area: number;
}

export interface PlannedPart {
  basis: Basis;
  /** The way the part leaves, a unit vector; zero for the base. */
  dir: Vec3;
  /** The part it leaves from; -1 for the base. */
  parent: number;
  /** Where it goes at full explode, from where it sits assembled, in the model frame (the lift not included). */
  offset: Vec3;
}

export interface Plan {
  parts: PlannedPart[];
  base: number;
  /** How far the whole model rises along `up` at full explode, so no part ends up below its floor. */
  lift: number;
  /** The model's box at full explode, the lift included. */
  min: Vec3;
  max: Vec3;
}

// --- vectors -----------------------------------------------------------------------------------------------------

const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const scale = (a: Vec3, s: number): Vec3 => [a[0] * s, a[1] * s, a[2] * s];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const length = (a: Vec3) => Math.hypot(a[0], a[1], a[2]);

/** `a` scaled to length one, or `fallback` when it is (nearly) zero. */
export function unit(a: Vec3, fallback: Vec3 = [0, 0, 1]): Vec3 {
  const l = length(a);
  return l > 1e-12 ? scale(a, 1 / l) : fallback;
}

interface Box {
  min: Vec3;
  max: Vec3;
}

const centreOf = (b: Box): Vec3 => scale(add(b.min, b.max), 0.5);
const shifted = (b: Box, by: Vec3): Box => ({ min: add(b.min, by), max: add(b.max, by) });

function union(boxes: Box[]): Box {
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const b of boxes) {
    for (let k = 0; k < 3; k++) {
      min[k] = Math.min(min[k], b.min[k]);
      max[k] = Math.max(max[k], b.max[k]);
    }
  }
  return { min, max };
}

/** The lowest and highest point of a box along a direction. */
function span(b: Box, d: Vec3): [number, number] {
  let lo = 0;
  let hi = 0;
  for (let k = 0; k < 3; k++) {
    const p = b.min[k] * d[k];
    const q = b.max[k] * d[k];
    lo += Math.min(p, q);
    hi += Math.max(p, q);
  }
  return [lo, hi];
}

/** How far apart two boxes are: the largest gap along an axis, negative when they overlap. */
function gapBetween(a: Box, b: Box): number {
  let g = -Infinity;
  for (let k = 0; k < 3; k++) g = Math.max(g, a.min[k] - b.max[k], b.min[k] - a.max[k]);
  return g;
}

/** Two directions square to `d` and to each other. */
function across(d: Vec3): [Vec3, Vec3] {
  const e1 = unit(cross(d, Math.abs(d[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0]), [1, 0, 0]);
  return [e1, cross(d, e1)];
}

// --- the faces parts mate with -----------------------------------------------------------------------------------

export interface FlatFace {
  /** Outward normal and offset of its plane: n · x = d. */
  n: Vec3;
  d: number;
  area: number;
  /** Its triangles, as indices into the part's triangles. */
  tris: number[];
}

/** A part's flat faces: its triangles grouped by the plane they lie in, the largest `keep` of them. */
export function flatFaces(triangles: Float32Array, tolerance: number, keep = 64): FlatFace[] {
  const groups = new Map<number, { nx: number; ny: number; nz: number; d: number; area: number; tris: number[] }>();
  const count = Math.floor(triangles.length / 9);
  for (let t = 0; t < count; t++) {
    const o = t * 9;
    const ax = triangles[o];
    const ay = triangles[o + 1];
    const az = triangles[o + 2];
    const ux = triangles[o + 3] - ax;
    const uy = triangles[o + 4] - ay;
    const uz = triangles[o + 5] - az;
    const vx = triangles[o + 6] - ax;
    const vy = triangles[o + 7] - ay;
    const vz = triangles[o + 8] - az;
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const l = Math.hypot(nx, ny, nz);
    if (l < 1e-30) continue;
    nx /= l;
    ny /= l;
    nz /= l;
    const d = nx * ax + ny * ay + nz * az;
    // One key per plane: the normal to a hundredth, the offset to the tolerance (2^20 steps either side).
    const facing = ((Math.round(nx * 100) + 100) * 201 + (Math.round(ny * 100) + 100)) * 201 + (Math.round(nz * 100) + 100);
    const key = facing * 2097152 + ((Math.round(d / tolerance) + 1048576) & 0x1fffff);
    const area = l / 2;
    const g = groups.get(key);
    if (g) {
      g.nx += nx * area;
      g.ny += ny * area;
      g.nz += nz * area;
      g.d += d * area;
      g.area += area;
      g.tris.push(t);
    } else groups.set(key, { nx: nx * area, ny: ny * area, nz: nz * area, d: d * area, area, tris: [t] });
  }
  return [...groups.values()]
    .sort((a, b) => b.area - a.area)
    .slice(0, keep)
    .map((g) => ({ n: unit([g.nx, g.ny, g.nz]), d: g.d / g.area, area: g.area, tris: g.tris }));
}

/** The triangles of a face in 2D coordinates of its plane, six numbers each, with their bounds. */
function inPlane(triangles: Float32Array, tris: number[], e1: Vec3, e2: Vec3) {
  const out = new Float64Array(tris.length * 6);
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  tris.forEach((t, i) => {
    for (let c = 0; c < 3; c++) {
      const o = t * 9 + c * 3;
      const x = triangles[o] * e1[0] + triangles[o + 1] * e1[1] + triangles[o + 2] * e1[2];
      const y = triangles[o] * e2[0] + triangles[o + 1] * e2[1] + triangles[o + 2] * e2[2];
      out[i * 6 + c * 2] = x;
      out[i * 6 + c * 2 + 1] = y;
      x0 = Math.min(x0, x);
      x1 = Math.max(x1, x);
      y0 = Math.min(y0, y);
      y1 = Math.max(y1, y);
    }
  });
  return { tri: out, x0, y0, x1, y1 };
}

/** Marks the cells of a grid whose centres lie in any of the 2D triangles. */
function rasterise(flat: Float64Array, grid: Uint8Array, cells: number, x0: number, y0: number, w: number, h: number) {
  for (let i = 0; i < flat.length; i += 6) {
    const ax = flat[i];
    const ay = flat[i + 1];
    const bx = flat[i + 2];
    const by = flat[i + 3];
    const cx = flat[i + 4];
    const cy = flat[i + 5];
    const area2 = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
    if (Math.abs(area2) < 1e-30) continue;
    const s = Math.sign(area2);
    const c0 = Math.max(0, Math.floor((Math.min(ax, bx, cx) - x0) / w - 0.5));
    const c1 = Math.min(cells - 1, Math.ceil((Math.max(ax, bx, cx) - x0) / w - 0.5));
    const r0 = Math.max(0, Math.floor((Math.min(ay, by, cy) - y0) / h - 0.5));
    const r1 = Math.min(cells - 1, Math.ceil((Math.max(ay, by, cy) - y0) / h - 0.5));
    for (let r = r0; r <= r1; r++) {
      const py = y0 + (r + 0.5) * h;
      for (let c = c0; c <= c1; c++) {
        const px = x0 + (c + 0.5) * w;
        const e0 = s * ((bx - ax) * (py - ay) - (by - ay) * (px - ax));
        const e1 = s * ((cx - bx) * (py - by) - (cy - by) * (px - bx));
        const e2 = s * ((ax - cx) * (py - cy) - (ay - cy) * (px - cx));
        if (e0 >= 0 && e1 >= 0 && e2 >= 0) grid[r * cells + c] = 1;
      }
    }
  }
}

/** The area two faces in one plane share, measured on a grid over where both lie. */
export function sharedArea(a: Float32Array, faceA: number[], b: Float32Array, faceB: number[], n: Vec3, cells = 24): number {
  const [e1, e2] = across(n);
  const A = inPlane(a, faceA, e1, e2);
  const B = inPlane(b, faceB, e1, e2);
  const x0 = Math.max(A.x0, B.x0);
  const x1 = Math.min(A.x1, B.x1);
  const y0 = Math.max(A.y0, B.y0);
  const y1 = Math.min(A.y1, B.y1);
  if (!(x1 > x0) || !(y1 > y0)) return 0;
  const w = (x1 - x0) / cells;
  const h = (y1 - y0) / cells;
  const gridA = new Uint8Array(cells * cells);
  const gridB = new Uint8Array(cells * cells);
  rasterise(A.tri, gridA, cells, x0, y0, w, h);
  rasterise(B.tri, gridB, cells, x0, y0, w, h);
  let both = 0;
  for (let i = 0; i < gridA.length; i++) both += gridA[i] & gridB[i];
  return both * w * h;
}

/** Where the parts' flat faces meet face to face: one contact each way for every pair of faces that share an area.
 * Standard parts are left out (their axis says how they leave); `tolerance` is how close two faces count as one plane. */
export function findContacts(parts: PlanPart[], tolerance: number): Contact[] {
  const faces = parts.map((p) => (p.fastener ? [] : flatFaces(p.triangles, tolerance)));
  const minArea = (tolerance * 4) ** 2;
  const out: Contact[] = [];
  for (let a = 0; a < parts.length; a++) {
    if (!faces[a].length) continue;
    for (let b = a + 1; b < parts.length; b++) {
      if (!faces[b].length || gapBetween(parts[a], parts[b]) > tolerance * 2) continue;
      // Only a's faces that reach b's box can meet one of b's.
      const near = faces[a].filter((f) => {
        const [lo, hi] = span(parts[b], f.n);
        return f.d >= lo - tolerance * 2 && f.d <= hi + tolerance * 2;
      });
      for (const fa of near) {
        for (const fb of faces[b]) {
          if (dot(fa.n, fb.n) > -0.996 || Math.abs(fa.d + fb.d) > tolerance * 2) continue;
          const area = sharedArea(parts[a].triangles, fa.tris, parts[b].triangles, fb.tris, fa.n);
          if (area <= minArea) continue;
          out.push({ a, b, normal: fb.n, area }, { a: b, b: a, normal: fa.n, area });
        }
      }
    }
  }
  return out;
}

/**
 * The way a part can leave the faces it sits against: of the faces' own normals, the main axes and `fallback`, the
 * direction that pulls away from (or slides along) every face and is nearest to their mean normal, weighted by area.
 * A part in a pocket leaves through the opening, one in a corner diagonally out of it; when the faces cancel out (a
 * slot) the free direction nearest `fallback` wins, and when nothing is free the mean (or `fallback`) still does.
 */
export function freeDirection(faces: { n: Vec3; w: number }[], fallback: Vec3): Vec3 {
  let total = 0;
  let mean: Vec3 = [0, 0, 0];
  for (const f of faces) {
    mean = add(mean, scale(f.n, f.w));
    total += f.w;
  }
  const want = total > 0 && length(mean) >= 0.25 * total ? unit(mean) : unit(fallback);
  const candidates: Vec3[] = [want, ...faces.map((f) => f.n), [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1], unit(fallback)];
  let best: Vec3 | null = null;
  let score = -Infinity;
  for (const c of candidates) {
    if (faces.some((f) => dot(c, f.n) < -0.05)) continue;
    const s = dot(c, want);
    if (s > score + 1e-9) {
      best = c;
      score = s;
    }
  }
  return best ?? want;
}

// --- what is in the way ------------------------------------------------------------------------------------------

/** A part's filled space as up to 4 x 4 x 4 small boxes, from points spread over its triangles. */
function blocksOf(part: PlanPart): Box[] {
  const t = part.triangles;
  if (t.length < 9) return [{ min: part.min, max: part.max }];
  const g = 4;
  const size = sub(part.max, part.min);
  const step = Math.max(size[0], size[1], size[2]) / g || 1;
  // Per cell: min x, y, z, then max x, y, z of the points in it.
  const cells = new Map<number, Float64Array>();
  const cell = (v: number, k: number) => Math.min(g - 1, Math.max(0, Math.floor(((v - part.min[k]) / (size[k] || 1)) * g)));
  const mark = (x: number, y: number, z: number) => {
    const id = (cell(x, 0) * g + cell(y, 1)) * g + cell(z, 2);
    const c = cells.get(id);
    if (!c) {
      cells.set(id, Float64Array.of(x, y, z, x, y, z));
      return;
    }
    if (x < c[0]) c[0] = x;
    if (y < c[1]) c[1] = y;
    if (z < c[2]) c[2] = z;
    if (x > c[3]) c[3] = x;
    if (y > c[4]) c[4] = y;
    if (z > c[5]) c[5] = z;
  };
  for (let o = 0; o + 8 < t.length; o += 9) {
    const reach = Math.max(Math.hypot(t[o + 3] - t[o], t[o + 4] - t[o + 1], t[o + 5] - t[o + 2]), Math.hypot(t[o + 6] - t[o], t[o + 7] - t[o + 1], t[o + 8] - t[o + 2]));
    // A large triangle gets points across it, so a big flat face fills every cell it crosses.
    const k = Math.min(16, Math.max(1, Math.ceil(reach / (step * 0.5))));
    for (let i = 0; i <= k; i++) {
      for (let j = 0; j <= k - i; j++) {
        const u = i / k;
        const v = j / k;
        const w = 1 - u - v;
        mark(w * t[o] + u * t[o + 3] + v * t[o + 6], w * t[o + 1] + u * t[o + 4] + v * t[o + 7], w * t[o + 2] + u * t[o + 5] + v * t[o + 8]);
      }
    }
  }
  return [...cells.values()].map((c) => ({ min: [c[0], c[1], c[2]], max: [c[3], c[4], c[5]] }));
}

/** What is placed so far, as each part's box and its blocks. */
interface Solid {
  whole: Box;
  blocks: Box[];
}

interface Footprint {
  /** Along the direction of travel. */
  lo: number;
  hi: number;
  /** Across it. */
  a0: number;
  a1: number;
  b0: number;
  b1: number;
}

function footprint(b: Box, d: Vec3, e1: Vec3, e2: Vec3): Footprint {
  const [lo, hi] = span(b, d);
  const [a0, a1] = span(b, e1);
  const [b0, b1] = span(b, e2);
  return { lo, hi, a0, a1, b0, b1 };
}

/**
 * How far `moving` must travel along `d` to clear every placed solid in its path: anything whose footprint across
 * `d` overlaps its own (by more than `slack`, so parts side by side never block each other) and that reaches past
 * its trailing face. Footprints are compared block by block, so a part only clears what really lies in its way.
 */
function clearance(moving: Solid, d: Vec3, placed: Solid[], slack: number): number {
  const [e1, e2] = across(d);
  const overlaps = (m: Footprint, q: Footprint) => Math.min(m.a1, q.a1) - Math.max(m.a0, q.a0) > slack && Math.min(m.b1, q.b1) - Math.max(m.b0, q.b0) > slack;
  const whole = footprint(moving.whole, d, e1, e2);
  const mine = moving.blocks.map((b) => footprint(b, d, e1, e2));
  let t = 0;
  for (const solid of placed) {
    const outline = footprint(solid.whole, d, e1, e2);
    if (outline.hi <= whole.lo || !overlaps(whole, outline)) continue;
    for (const o of solid.blocks) {
      const q = footprint(o, d, e1, e2);
      if (q.hi <= whole.lo) continue;
      for (const m of mine) if (q.hi > m.lo && overlaps(m, q)) t = Math.max(t, q.hi - m.lo);
    }
  }
  return t;
}

// --- the plan ----------------------------------------------------------------------------------------------------

/** The gap between a part and what it clears, as a share of the model's radius. */
export const GAP = 0.12;

interface Link {
  area: number;
  /** Normals of the faces of the other side, pointing into this one. */
  faces: { n: Vec3; w: number; a: number; b: number }[];
  joint: PlanJoint | null;
}

/**
 * Plans the explode: for every part the way it leaves, the part it leaves from and where it goes at full explode.
 * `contacts` come from `findContacts`; `up` is the model frame's up, for the floor the model stands on.
 */
export function planExplode(parts: PlanPart[], contacts: Contact[], up: Vec3 = [0, 0, 1]): Plan {
  const n = parts.length;
  if (!n) return { parts: [], base: -1, lift: 0, min: [0, 0, 0], max: [0, 0, 0] };
  const upward = unit(up);
  const boxes: Box[] = parts.map((p) => ({ min: p.min, max: p.max }));
  const centres = boxes.map(centreOf);
  const whole = union(boxes);
  const radius = Math.max(1e-9, length(sub(whole.max, whole.min)) / 2);
  const middle = centreOf(whole);
  const index = new Map(parts.map((p, i) => [p.key, i]));
  const size = (i: number) => length(sub(parts[i].max, parts[i].min));
  const largest = (list: number[]) => list.reduce((best, i) => (size(i) > size(best) ? i : best), list[0]);
  const nearestTo = (point: Vec3, list: number[]) =>
    list.reduce((best, i) => (length(sub(centres[i], point)) < length(sub(centres[best], point)) ? i : best), list[0]);

  // The base: the part marked so, else the largest part standing on the floor that is not a load or a standard part.
  const floor = Math.min(...boxes.map((b) => span(b, upward)[0]));
  const solid = parts.map((_, i) => i).filter((i) => !parts[i].load && !parts[i].fastener);
  const grounded = solid.filter((i) => span(boxes[i], upward)[0] <= floor + radius * 0.15);
  const marked = parts.findIndex((p) => p.isBase);
  const base = marked >= 0 ? marked : largest(grounded.length ? grounded : solid.length ? solid : parts.map((_, i) => i));

  // A standard part leaves from the holder nearest to it.
  const holder = new Int32Array(n).fill(-1);
  parts.forEach((p, i) => {
    if (!p.fastener || i === base) return;
    const options = p.fastener.holders.map((k) => index.get(k)).filter((j): j is number => j !== undefined && j !== i && !parts[j].fastener);
    if (options.length) holder[i] = options.reduce((best, j) => (gapBetween(boxes[i], boxes[j]) < gapBetween(boxes[i], boxes[best]) ? j : best), options[0]);
  });

  // Units: a group leaves as one, except the base's own group, which comes apart part by part.
  const nodeOf = new Int32Array(n);
  const nodes: number[][] = [];
  const groupNode = new Map<string, number>();
  const baseGroup = parts[base].group ?? null;
  parts.forEach((p, i) => {
    const group = p.group && holder[i] < 0 && i !== base && p.group !== baseGroup ? p.group : null;
    const known = group !== null ? groupNode.get(group) : undefined;
    if (known !== undefined) {
      nodeOf[i] = known;
      nodes[known].push(i);
      return;
    }
    nodeOf[i] = nodes.length;
    nodes.push([i]);
    if (group !== null) groupNode.set(group, nodeOf[i]);
  });
  const nodeBoxes = nodes.map((members) => union(members.map((i) => boxes[i])));
  const nodeCentres = nodeBoxes.map(centreOf);

  // Links between units: the faces where they mate and the joints between them; contacts inside a unit apart.
  const links = nodes.map(() => new Map<number, Link>());
  const inside: Contact[] = [];
  const link = (x: number, y: number) => {
    let found = links[x].get(y);
    if (!found) links[x].set(y, (found = { area: 0, faces: [], joint: null }));
    return found;
  };
  for (const c of contacts) {
    if (holder[c.a] >= 0 || holder[c.b] >= 0) continue;
    const x = nodeOf[c.a];
    const y = nodeOf[c.b];
    if (x === y) {
      inside.push(c);
      continue;
    }
    const l = link(x, y);
    l.area += c.area;
    l.faces.push({ n: c.normal, w: c.area, a: c.a, b: c.b });
  }
  parts.forEach((p, i) => {
    for (const joint of p.joints ?? []) {
      const others = joint.parents.map((k) => index.get(k)).filter((j): j is number => j !== undefined && nodeOf[j] !== nodeOf[i]);
      if (!others.length) continue;
      const other = nearestTo(joint.at ?? centres[i], others);
      link(nodeOf[i], nodeOf[other]).joint ??= joint;
      link(nodeOf[other], nodeOf[i]).joint ??= joint;
    }
  });

  // The explode tree over units, breadth first from the base; a standard part hangs under its holder's unit.
  const depth = new Int32Array(nodes.length).fill(-1);
  const parentNode = new Int32Array(nodes.length).fill(-1);
  const fastenersOf = new Map<number, number[]>();
  parts.forEach((_, i) => {
    if (holder[i] >= 0) fastenersOf.set(nodeOf[holder[i]], [...(fastenersOf.get(nodeOf[holder[i]]) ?? []), nodeOf[i]]);
  });
  const isFastenerNode = (x: number) => nodes[x].length === 1 && holder[nodes[x][0]] >= 0;
  const reach = (start: number, startDepth: number) => {
    depth[start] = startDepth;
    const queue = [start];
    for (let q = 0; q < queue.length; q++) {
      const x = queue[q];
      for (const y of links[x].keys()) {
        if (depth[y] >= 0 || isFastenerNode(y)) continue;
        depth[y] = depth[x] + 1;
        queue.push(y);
      }
      for (const f of fastenersOf.get(x) ?? []) {
        if (depth[f] >= 0) continue;
        depth[f] = depth[x] + 1;
        parentNode[f] = x;
        queue.push(f);
      }
    }
  };
  const baseNode = nodeOf[base];
  reach(baseNode, 0);
  // A cluster that touches nothing joined to the base leaves it from the centre, led by its largest unit.
  for (;;) {
    const left = nodes.map((_, x) => x).filter((x) => depth[x] < 0 && !isFastenerNode(x));
    if (!left.length) break;
    const lead = left.reduce((best, x) => (length(sub(nodeBoxes[x].max, nodeBoxes[x].min)) > length(sub(nodeBoxes[best].max, nodeBoxes[best].min)) ? x : best), left[0]);
    parentNode[lead] = baseNode;
    reach(lead, 1);
  }
  // A standard part whose holder is itself a standard part's (never) or missing stays with the base.
  nodes.forEach((_, x) => {
    if (depth[x] < 0) {
      depth[x] = 1;
      parentNode[x] = baseNode;
    }
  });
  // Each unit leaves from a neighbour one step nearer the base: across a joint first, else the largest shared face.
  nodes.forEach((_, x) => {
    if (x === baseNode || parentNode[x] >= 0) return;
    let best = -1;
    let bestScore = -Infinity;
    for (const [y, l] of links[x]) {
      if (depth[y] !== depth[x] - 1) continue;
      const score = (l.joint ? 1e300 : 0) + l.area;
      if (score > bestScore) {
        best = y;
        bestScore = score;
      }
    }
    parentNode[x] = best >= 0 ? best : baseNode;
  });

  // The way each unit leaves its parent, the part it leaves from and the member that leads it.
  const out: PlannedPart[] = parts.map(() => ({ basis: "centre", dir: [0, 0, 0], parent: base, offset: [0, 0, 0] }));
  out[base] = { basis: "base", dir: [0, 0, 0], parent: -1, offset: [0, 0, 0] };
  const nodeDir: Vec3[] = nodes.map(() => [0, 0, 0]);
  const anchor = nodes.map((members) => members[0]);
  const from = new Int32Array(nodes.length).fill(base);
  const fromCentre = (x: number) => unit(sub(nodeCentres[x], middle), upward);
  nodes.forEach((members, x) => {
    if (x === baseNode) return;
    const y = parentNode[x];
    const l = links[x].get(y);
    let basis: Basis;
    let dir: Vec3;
    if (isFastenerNode(x)) {
      const i = members[0];
      basis = "fastener";
      dir = unit(parts[i].fastener!.out, upward);
      from[x] = holder[i];
      anchor[x] = i;
    } else if (l?.joint) {
      // Away from the side the joint sits on, as a whole (a crank leaves the pin fixed in the base upwards).
      const axis = unit(l.joint.axis, upward);
      const other = l.joint.parents.map((k) => index.get(k)).filter((j): j is number => j !== undefined);
      const fixed = other.length ? centreOf(union(other.map((j) => boxes[j]))) : nodeCentres[y];
      let side = dot(sub(nodeCentres[x], fixed), axis);
      if (Math.abs(side) < radius * 1e-3) side = dot(sub(nodeCentres[x], middle), axis);
      basis = "joint";
      dir = side < 0 ? scale(axis, -1) : axis;
      const at = l.joint.at ?? nodeCentres[x];
      from[x] = nearestTo(at, nodes[y]);
      anchor[x] = nearestTo(at, members);
    } else if (l && l.faces.length) {
      basis = "mate";
      dir = freeDirection(l.faces, unit(sub(nodeCentres[x], nodeCentres[y]), fromCentre(x)));
      // The member with the largest face on the parent leads; it leaves from the part that face belongs to.
      const byPair = new Map<string, number>();
      for (const f of l.faces) byPair.set(f.a + ":" + f.b, (byPair.get(f.a + ":" + f.b) ?? 0) + f.w);
      const [pair] = [...byPair.entries()].sort((p, q) => q[1] - p[1])[0];
      const [a, b] = pair.split(":").map(Number);
      anchor[x] = a;
      from[x] = b;
    } else {
      basis = "centre";
      dir = fromCentre(x);
      from[x] = base;
      anchor[x] = largest(members);
    }
    nodeDir[x] = dir;
    out[anchor[x]] = { basis, dir, parent: from[x], offset: [0, 0, 0] };
  });

  // Inside a unit: each member leaves the member it mates with, breadth first from the one that leads; a member that
  // mates with none of them spreads from the unit's centre.
  const spreadOrder = nodes.map((members, x) => {
    if (members.length < 2) return [];
    const mine = new Set(members);
    const own = inside.filter((c) => mine.has(c.a) && mine.has(c.b));
    const seen = new Map<number, number>([[anchor[x], 0]]);
    const order: number[] = [];
    const queue = [anchor[x]];
    for (let q = 0; q < queue.length; q++) {
      const m = queue[q];
      const next = new Map<number, number>();
      for (const c of own) if (c.b === m && !seen.has(c.a)) next.set(c.a, (next.get(c.a) ?? 0) + c.area);
      for (const [a] of [...next.entries()].sort((p, r) => r[1] - p[1])) {
        if (seen.has(a)) continue;
        seen.set(a, seen.get(m)! + 1);
        const faces = own.filter((c) => c.a === a && c.b === m).map((c) => ({ n: c.normal, w: c.area }));
        out[a] = { basis: "mate", dir: freeDirection(faces, unit(sub(centres[a], centres[m]), unit(sub(centres[a], nodeCentres[x]), nodeDir[x]))), parent: m, offset: [0, 0, 0] };
        order.push(a);
        queue.push(a);
      }
    }
    for (const m of members) {
      if (seen.has(m)) continue;
      out[m] = { basis: "centre", dir: unit(sub(centres[m], nodeCentres[x]), nodeDir[x]), parent: anchor[x], offset: [0, 0, 0] };
      order.push(m);
    }
    return order;
  });

  // Where everything goes: units in the order of the tree, each first riding with the part it leaves from, then
  // clearing everything already placed in its way plus a gap. Children nearer their parent along their way go first.
  const blocks = parts.map(blocksOf);
  const offsets: Vec3[] = parts.map(() => [0, 0, 0]);
  const solidAt = (i: number, by: Vec3): Solid => ({ whole: shifted(boxes[i], by), blocks: blocks[i].map((b) => shifted(b, by)) });
  const placed: Solid[] = [solidAt(base, [0, 0, 0])];
  const gap = radius * GAP;
  const slack = radius * 0.01;
  const children = nodes.map(() => [] as number[]);
  nodes.forEach((_, x) => {
    if (x !== baseNode) children[parentNode[x]].push(x);
  });
  const lead = (x: number) => span(nodeBoxes[x], nodeDir[x])[0] - dot(nodeCentres[parentNode[x]], nodeDir[x]);
  const queue = [baseNode];
  for (let q = 0; q < queue.length; q++) {
    const x = queue[q];
    queue.push(...children[x].sort((a, b) => lead(a) - lead(b)));
    if (x === baseNode) continue;
    const start = offsets[from[x]];
    const dir = nodeDir[x];
    const members = nodes[x].map((i) => solidAt(i, start));
    const moving: Solid = { whole: union(members.map((m) => m.whole)), blocks: members.flatMap((m) => m.blocks) };
    const shift = add(start, scale(dir, clearance(moving, dir, placed, slack) + gap));
    for (const i of nodes[x]) offsets[i] = shift;
    if (nodes[x].length === 1) {
      placed.push(solidAt(nodes[x][0], shift));
      continue;
    }
    // The unit has left as one; now its members spread from the one that leads, clearing each other.
    const own: Solid[] = [solidAt(anchor[x], shift)];
    for (const m of spreadOrder[x]) {
      const d = out[m].dir;
      const begin = offsets[out[m].parent];
      offsets[m] = add(begin, scale(d, clearance(solidAt(m, begin), d, own, slack) + gap * 0.6));
      own.push(solidAt(m, offsets[m]));
    }
    placed.push(...own);
  }

  // Parts that leave downwards (a battery under a frame) would go through the floor: the whole model rises instead.
  const lowest = Math.min(...boxes.map((b, i) => span(shifted(b, offsets[i]), upward)[0]));
  const lift = Math.max(0, floor - lowest);
  const exploded = union(boxes.map((b, i) => shifted(b, add(offsets[i], scale(upward, lift)))));
  parts.forEach((_, i) => (out[i].offset = offsets[i]));
  return { parts: out, base, lift, min: exploded.min, max: exploded.max };
}

/** How many parts leave each way, the base left out. */
export function countBases(plan: Plan): Record<Exclude<Basis, "base">, number> {
  const counts = { fastener: 0, joint: 0, mate: 0, centre: 0 };
  for (const p of plan.parts) if (p.basis !== "base") counts[p.basis]++;
  return counts;
}

/**
 * Moves `x` (at speed `v`) towards `target` for `dt` seconds as a critically damped spring: smooth to start, smooth
 * to stop and never past the target. Returns the new place and speed; settled, it is the target exactly.
 */
export function springStep(x: number, v: number, target: number, dt: number, omega = 13): [number, number] {
  const c1 = x - target;
  const c2 = v + omega * c1;
  const e = Math.exp(-omega * dt);
  const nx = target + (c1 + c2 * dt) * e;
  const nv = (c2 - omega * (c1 + c2 * dt)) * e;
  if (Math.abs(nx - target) < 2e-4 && Math.abs(nv) < 2e-3) return [target, 0];
  return [nx, nv];
}

