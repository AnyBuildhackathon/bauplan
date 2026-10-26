// The explode view's direction logic (src/components/canvas/explodePlan.ts) on small models made of boxes:
// the faces parts mate with, the way a part can leave them, and the plan for a screwed sensor box, a part on a
// joint, a group, a part that floats and a battery under a frame. Run with `npm test` (node's test runner).
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { countBases, findContacts, flatFaces, freeDirection, planExplode, springStep, type PlanPart, type Vec3 } from "../src/components/canvas/explodePlan.ts";

/** The twelve triangles of a box, each facing out. */
function boxTriangles(min: Vec3, max: Vec3): number[] {
  const out: number[] = [];
  const corner = (x: number, y: number, z: number): Vec3 => [[min[0], max[0]][x], [min[1], max[1]][y], [min[2], max[2]][z]];
  for (let axis = 0; axis < 3; axis++) {
    for (const side of [0, 1]) {
      const [u, v] = [(axis + 1) % 3, (axis + 2) % 3];
      const at = (a: number, b: number) => {
        const index = [0, 0, 0];
        index[axis] = side;
        index[u] = a;
        index[v] = b;
        return corner(index[0], index[1], index[2]);
      };
      let quad = [at(0, 0), at(1, 0), at(1, 1), at(0, 1)];
      const e1 = quad[1].map((c, k) => c - quad[0][k]);
      const e2 = quad[2].map((c, k) => c - quad[0][k]);
      const normal = e1[(axis + 1) % 3] * e2[(axis + 2) % 3] - e1[(axis + 2) % 3] * e2[(axis + 1) % 3];
      if ((normal > 0) !== (side === 1)) quad = [quad[0], quad[3], quad[2], quad[1]];
      out.push(...quad[0], ...quad[1], ...quad[2], ...quad[0], ...quad[2], ...quad[3]);
    }
  }
  return out;
}

/** A part made of one or more boxes. */
function part(key: string, boxes: [Vec3, Vec3][], extra: Partial<PlanPart> = {}): PlanPart {
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const [lo, hi] of boxes) {
    for (let k = 0; k < 3; k++) {
      min[k] = Math.min(min[k], lo[k]);
      max[k] = Math.max(max[k], hi[k]);
    }
  }
  return { key, triangles: Float32Array.from(boxes.flatMap(([lo, hi]) => boxTriangles(lo, hi))), min, max, ...extra };
}

const near = (actual: number[], expected: number[], tolerance = 1e-6) =>
  assert.ok(actual.every((v, k) => Math.abs(v - expected[k]) <= tolerance), `${JSON.stringify(actual)} is not ${JSON.stringify(expected)}`);

const TOLERANCE = 0.05;

describe("faces", () => {
  test("a box has six flat faces, each facing out with its area", () => {
    const faces = flatFaces(Float32Array.from(boxTriangles([0, 0, 0], [10, 20, 30])), TOLERANCE);
    assert.equal(faces.length, 6);
    const top = faces.find((f) => f.n[2] > 0.99)!;
    assert.ok(Math.abs(top.d - 30) < 1e-6);
    assert.ok(Math.abs(top.area - 200) < 1e-6);
    const left = faces.find((f) => f.n[0] < -0.99)!;
    assert.ok(Math.abs(left.d - 0) < 1e-6);
    assert.ok(Math.abs(left.area - 600) < 1e-6);
  });

  test("a part on top of another mates with it face to face, each way", () => {
    const parts = [part("lid", [[[0, 0, 10], [40, 20, 13]]]), part("box", [[[-10, -10, 0], [50, 30, 10]]])];
    const contacts = findContacts(parts, TOLERANCE);
    const up = contacts.find((c) => c.a === 0)!;
    near(up.normal, [0, 0, 1]);
    // The lid's whole underside rests on the box.
    assert.ok(Math.abs(up.area - 800) / 800 < 0.1, `area ${up.area}`);
    near(contacts.find((c) => c.a === 1)!.normal, [0, 0, -1]);
  });

  test("a gap, a corner touch or a part beside another in the air are no contact; parts side by side are", () => {
    assert.equal(findContacts([part("a", [[[0, 0, 10.5], [10, 10, 12]]]), part("b", [[[0, 0, 0], [10, 10, 10]]])], TOLERANCE).length, 0);
    assert.equal(findContacts([part("a", [[[10, 10, 10], [20, 20, 20]]]), part("b", [[[0, 0, 0], [10, 10, 10]]])], TOLERANCE).length, 0);
    const side = findContacts([part("a", [[[10, 0, 0], [20, 10, 10]]]), part("b", [[[0, 0, 0], [10, 10, 10]]])], TOLERANCE);
    near(side.find((c) => c.a === 0)!.normal, [1, 0, 0]);
  });
});

describe("free direction", () => {
  test("a part in a pocket leaves through its opening", () => {
    const faces = [
      { n: [0, 0, 1] as Vec3, w: 100 },
      { n: [1, 0, 0] as Vec3, w: 40 },
      { n: [-1, 0, 0] as Vec3, w: 40 },
      { n: [0, 1, 0] as Vec3, w: 60 },
      { n: [0, -1, 0] as Vec3, w: 60 },
    ];
    near(freeDirection(faces, [1, 0, 0]), [0, 0, 1]);
  });

  test("a part in a corner leaves diagonally, one in a slot slides out the free way nearest the fallback", () => {
    const s = Math.SQRT1_2;
    near(freeDirection([{ n: [0, 0, 1], w: 50 }, { n: [1, 0, 0], w: 50 }], [0, 1, 0]), [s, 0, s]);
    near(freeDirection([{ n: [0, 0, 1], w: 50 }, { n: [0, 0, -1], w: 50 }], [0.9, 0.1, 0.4]), [1, 0, 0]);
  });
});

/** The sensor box of e2e/explode.spec.ts: an open box with a post in each corner, inserts in the posts, a lid on top
 * and a screw through each corner of the lid into its insert. */
function sensorBox(): PlanPart[] {
  const corners: [number, number][] = [[25, 15], [-25, 15], [25, -15], [-25, -15]];
  const base = part("base", [
    [[-30, -20, 0], [30, 20, 2]],
    [[-30, -20, 2], [-28, 20, 20]],
    [[28, -20, 2], [30, 20, 20]],
    [[-28, -20, 2], [28, -18, 20]],
    [[-28, 18, 2], [28, 20, 20]],
    ...corners.map(([x, y]): [Vec3, Vec3] => [[x - 4, y - 4, 2], [x + 4, y + 4, 16]]),
  ]);
  const inserts = corners.map(([x, y], i) => part(`insert-${i}`, [[[x - 2.5, y - 2.5, 16], [x + 2.5, y + 2.5, 20]]], { fastener: { out: [0, 0, 1], holders: ["base"] } }));
  const lid = part("lid", [[[-30, -20, 20], [30, 20, 23]]]);
  const screws = corners.map(([x, y], i) =>
    part(`screw-${i}`, [[[x - 1.5, y - 1.5, 15], [x + 1.5, y + 1.5, 23]], [[x - 2.75, y - 2.75, 23], [x + 2.75, y + 2.75, 26]]], { fastener: { out: [0, 0, 1], holders: ["lid"] } }),
  );
  return [base, ...inserts, lid, ...screws];
}

describe("plan", () => {
  test("the sensor box: the box stays, inserts and screws leave along their axes, the lid off its face, all stacked clear", () => {
    const parts = sensorBox();
    const plan = planExplode(parts, findContacts(parts, TOLERANCE), [0, 0, 1]);
    const at = (key: string) => plan.parts[parts.findIndex((p) => p.key === key)];
    const top = (key: string) => parts.find((p) => p.key === key)!.max[2] + at(key).offset[2];
    const bottom = (key: string) => parts.find((p) => p.key === key)!.min[2] + at(key).offset[2];

    assert.equal(parts[plan.base].key, "base");
    near(at("base").offset, [0, 0, 0]);
    for (let i = 0; i < 4; i++) {
      assert.equal(at(`insert-${i}`).basis, "fastener");
      near(at(`insert-${i}`).dir, [0, 0, 1]);
      assert.equal(parts[at(`insert-${i}`).parent].key, "base");
      // Out of its post, clear of the box.
      assert.ok(bottom(`insert-${i}`) > 20, `insert ${i} at ${bottom(`insert-${i}`)}`);
      assert.equal(at(`screw-${i}`).basis, "fastener");
      assert.equal(parts[at(`screw-${i}`).parent].key, "lid");
      // A screw rides on the lid, then comes out of it.
      assert.ok(bottom(`screw-${i}`) > top("lid"), `screw ${i} at ${bottom(`screw-${i}`)}, lid up to ${top("lid")}`);
    }
    assert.equal(at("lid").basis, "mate");
    near(at("lid").dir, [0, 0, 1]);
    assert.equal(parts[at("lid").parent].key, "base");
    // The lid clears the inserts that came up below it.
    assert.ok(bottom("lid") > top("insert-0"), `lid at ${bottom("lid")}, insert up to ${top("insert-0")}`);
    // Nothing moves sideways.
    for (const p of plan.parts) assert.ok(Math.abs(p.offset[0]) < 1e-9 && Math.abs(p.offset[1]) < 1e-9);
    assert.equal(plan.lift, 0);
    assert.ok(plan.max[2] > 40);
    assert.deepEqual(countBases(plan), { fastener: 8, joint: 0, mate: 1, centre: 0 });
  });

  test("a part on a joint leaves along the joint's axis, away from the side that holds it", () => {
    const parts = [
      part("plate", [[[-20, -20, 0], [20, 20, 4]]]),
      part("pin", [[[-1, -1, 4], [1, 1, 14]]]),
      part("crank", [[[-3, -3, 6], [30, 3, 10]]], { joints: [{ axis: [0, 0, -1], at: [0, 0, 8], parents: ["plate", "pin"] }] }),
    ];
    const plan = planExplode(parts, findContacts(parts, TOLERANCE), [0, 0, 1]);
    const crank = plan.parts[2];
    assert.equal(crank.basis, "joint");
    // The axis came in pointing down; the crank still leaves upwards, off the pin.
    near(crank.dir, [0, 0, 1]);
    assert.equal(parts[crank.parent].key, "pin");
    assert.ok(parts[2].min[2] + crank.offset[2] > 14, "the crank clears the top of its pin");
  });

  test("a group leaves as one, then its parts spread; a part that touches nothing leaves from the centre", () => {
    const parts = [
      part("base", [[[-50, -50, 0], [50, 50, 10]]]),
      part("jaw", [[[-10, -10, 10], [10, 10, 20]]], { group: "head" }),
      part("finger", [[[-2, -2, 20], [2, 2, 30]]], { group: "head" }),
      part("sensor", [[[70, -5, 20], [80, 5, 30]]]),
    ];
    const plan = planExplode(parts, findContacts(parts, TOLERANCE), [0, 0, 1]);
    const [, jaw, finger, sensor] = plan.parts;
    assert.equal(jaw.basis, "mate");
    near(jaw.dir, [0, 0, 1]);
    assert.equal(finger.basis, "mate");
    assert.equal(parts[finger.parent].key, "jaw");
    assert.ok(finger.offset[2] > jaw.offset[2], "the finger spreads beyond the jaw it rides on");
    assert.equal(sensor.basis, "centre");
    // From the middle of the whole model (x 15, z 15) through the sensor's centre (x 75, z 25).
    near(sensor.dir, [60 / Math.hypot(60, 10), 0, 10 / Math.hypot(60, 10)]);
  });

  test("a battery under a frame leaves downwards and the whole model rises so it stays above the floor", () => {
    const parts = [
      part("frame", [[[-40, -40, 10], [40, 40, 13]]], { isBase: true }),
      part("battery", [[[-30, -10, 0], [30, 10, 10]]]),
      part("board", [[[-15, -15, 13], [15, 15, 15]]]),
    ];
    const plan = planExplode(parts, findContacts(parts, TOLERANCE), [0, 0, 1]);
    assert.equal(plan.base, 0);
    near(plan.parts[1].dir, [0, 0, -1]);
    near(plan.parts[2].dir, [0, 0, 1]);
    assert.ok(plan.lift > 0);
    const lowest = Math.min(...parts.map((p, i) => p.min[2] + plan.parts[i].offset[2])) + plan.lift;
    assert.ok(Math.abs(lowest) < 1e-9, `lowest point ${lowest}`);
  });

  test("a load is never the base, even when it is the largest part", () => {
    const parts = [part("phone", [[[-40, -5, 0], [40, 5, 160]]], { load: true }), part("stand", [[[-20, -20, 0], [20, 20, 30]]])];
    assert.equal(planExplode(parts, findContacts(parts, TOLERANCE), [0, 0, 1]).base, 1);
  });
});

test("the spring glides to its target without passing it, then rests on it exactly", () => {
  let [x, v] = [0, 0];
  let previous = 0;
  for (let frame = 0; frame < 60; frame++) {
    [x, v] = springStep(x, v, 1, 1 / 60);
    assert.ok(x >= previous - 1e-12 && x <= 1, `frame ${frame}: ${x}`);
    previous = x;
  }
  assert.equal(x, 1);
  assert.equal(v, 0);
});
