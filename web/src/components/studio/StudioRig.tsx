// The studio inside a 3D canvas (the Model and CAD tabs): it runs the view bar's camera
// commands (front, side, top, reset, zoom, fit), the lens (perspective, or orthographic as a
// 2° telephoto from far away, so every framing, explode and focus move keeps working), hides
// the parts the assembly tree switched off, measures between two points on the model, cuts it
// with the section plane, and keeps what the studio's notes to Mechanic read from the scene:
// the last click with the Select tool and how the view stands, in the build's mm (frame.ts).
// The scene keeps fitting its own camera; the rig only moves it on request.
import { Html, Line } from "@react-three/drei";
import { useFrame, useThree, type RootState } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useRef, useState, type ComponentRef } from "react";
import * as THREE from "three";
import { useAnalysisLayer, limitOf } from "../../events/analysis";
import { useSession } from "../../events/store";
import type { NotePoint, NoteView } from "../../events/types";
import { normaliseName } from "../../lib/targets";
import { useUi } from "../../lib/ui";
import { shownExplode } from "../canvas/explode";
import { treeNodes } from "./assembly";
import { axisInFile, dirToBuild, fileToBuild, hitModel, keptByCut, partLabel, partNode, toBuild, type ModelFrame } from "./frame";
import { useStudio, type CameraView } from "./studio";

export const PERSPECTIVE_FOV = 30;
const ORTHO_FOV = 2;
const LENS_MS = 520;
const MOVE_MS = 480;
const ZOOM_MS = 220;
const UP = new THREE.Vector3(0, 1, 0);

/** How much farther the camera stands at this field of view than at 30° for the same framing. */
export function lensFactor(fov: number): number {
  return Math.tan(THREE.MathUtils.degToRad(PERSPECTIVE_FOV) / 2) / Math.tan(THREE.MathUtils.degToRad(fov) / 2);
}

type Controls = THREE.EventDispatcher<{ start: object }> & {
  target: THREE.Vector3;
  update: () => void;
  enableDamping: boolean;
  minDistance: number;
  maxDistance: number;
  minPolarAngle: number;
  maxPolarAngle: number;
};

interface Move {
  t0: number;
  ms: number;
  target: [THREE.Vector3, THREE.Vector3];
  dir: [THREE.Vector3, THREE.Vector3];
  dist: [number, number];
}

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

export interface StudioRigProps {
  /** The model's root object: its part nodes are hidden, listed and measured. */
  model: THREE.Object3D | null;
  /** The model's bounding sphere in world space; the views frame it. */
  center: THREE.Vector3;
  radius: number;
  /** Direction from the model to the camera in the default view. */
  home: THREE.Vector3;
  /** Direction from the model to the camera in the front view. */
  front: THREE.Vector3;
  /** Metres per scene unit, for the measured distance. */
  unit: number;
  /** The model file is millimetres with Z up (a generated part), not metres with Y up (the drone). */
  zUp?: boolean;
}

export function StudioRig({ model, center, radius, home, front, unit, zUp = false }: StudioRigProps) {
  const frame: ModelFrame = { zUp, unit };
  return (
    <>
      <Camera center={center} radius={radius} home={home} front={front} />
      <PartVisibility model={model} />
      <Section model={model} zUp={zUp} unit={unit} />
      <Pick model={model} zUp={zUp} unit={unit} />
      <ViewReader model={model} />
      <Measure model={model} unit={unit} frame={frame} />
    </>
  );
}

/** Where a click lands on the model, as a note's point: the part, the place and the face, in the build's mm. */
function notePoint(hit: ReturnType<typeof hitModel>, frame: ModelFrame): (NotePoint & { node: string; cut: boolean }) | null {
  if (!hit) return null;
  const node = partNode(hit.object).name;
  return { node, part: partLabel(node).name, point_mm: toBuild(hit.object, hit.point, frame), normal: hit.normal ? dirToBuild(hit.normal) : null, cut: hit.cut };
}

const rayAt = (raycaster: THREE.Raycaster, camera: THREE.Camera, el: HTMLElement, e: PointerEvent) => {
  const r = el.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
};

/** With the Select tool, a click (not a drag of the camera) on the model is the last pick: what a selection note carries. */
function Pick({ model, zUp, unit }: { model: THREE.Object3D | null; zUp: boolean; unit: number }) {
  const camera = useThree((s) => s.camera);
  const gl = useThree((s) => s.gl);
  const raycaster = useThree((s) => s.raycaster);
  useEffect(() => {
    const el = gl.domElement;
    let down: { x: number; y: number } | null = null;
    let n = 0;
    const onDown = (e: PointerEvent) => {
      if (e.button === 0) down = { x: e.clientX, y: e.clientY };
    };
    const onUp = (e: PointerEvent) => {
      const click = down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5;
      down = null;
      if (!click || !model || useUi.getState().tool !== "select") return;
      rayAt(raycaster, camera, el, e);
      const pick = notePoint(hitModel(raycaster, model), { zUp, unit });
      useStudio.setState({ pick: pick && { ...pick, n: ++n } });
    };
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointerup", onUp);
    return () => {
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointerup", onUp);
    };
  }, [model, gl, camera, raycaster, zUp, unit]);
  // Another model (a new build, another tab) is not what was clicked.
  useEffect(() => () => useStudio.setState({ pick: null }), [model]);
  return null;
}

/** Lets a marking ask how the view stands right now: side, lens, explode, cut, colours, hidden parts, labels. */
function ViewReader({ model }: { model: THREE.Object3D | null }) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3 } | null;
  useEffect(() => {
    const read = (): NoteView => {
      const { studio, explode, tab } = useUi.getState();
      const { section, hidden, nodes } = useStudio.getState();
      const target = controls?.target ?? new THREE.Vector3();
      const layer = useAnalysisLayer.getState();
      const info = layer.check ? useSession.getState().analysis?.checks[layer.check] : undefined;
      return {
        tab: tab === "cad" ? "cad" : "modell",
        camera: dirToBuild(camera.position.clone().sub(target)),
        ortho: studio.ortho,
        explode,
        section: section && section.at !== null && section.keep ? { axis: section.axis, at_mm: section.at, keep: section.keep } : null,
        surface: layer.check && info ? { check: layer.check, limit: limitOf(layer.check, info, layer.limits) } : null,
        hidden: hidden.map((name) => partLabel(nodes[name] ?? name).name),
        labels: studio.labels,
      };
    };
    useStudio.setState({ view: read });
    return () => {
      if (useStudio.getState().view === read) useStudio.setState({ view: null });
    };
  }, [camera, controls, model]);
  return null;
}

const CAP = new THREE.Color();

/** The model file's root: the studio's model object itself, or inside it (the drone sits in groups around its file). */
function rootOf(model: THREE.Object3D | null): THREE.Object3D | null {
  if (!model || model.userData.glbRoot) return model;
  let found: THREE.Object3D | null = null;
  model.traverse((o) => {
    if (!found && o.userData.glbRoot) found = o;
  });
  return found;
}

/**
 * The section view: one plane across the build's X, Y or Z cuts the model, and the faces it cuts show as
 * flat darker shades of their parts (each part's inside drawn from behind, so every cut reads as filled).
 * The plane lives in the model file's frame, at `at` mm along its axis, and follows the model in the
 * scene; clicks and the hover go through what it took away. Off, the model is whole again.
 */
function Section({ model, zUp, unit }: { model: THREE.Object3D | null; zUp: boolean; unit: number }) {
  const section = useStudio((s) => s.section);
  const gl = useThree((s) => s.gl);
  const camera = useThree((s) => s.camera);
  const setEvents = useThree((s) => s.setEvents);
  const get = useThree((s) => s.get);
  const local = useRef(new THREE.Plane());
  const world = useRef(new THREE.Plane());
  const planes = useRef([world.current]);
  const caps = useRef(new Map<THREE.Mesh, THREE.Mesh>());
  // The file loads after the rig (the drone suspends): the root is looked for on every frame.
  const [root, setRoot] = useState<THREE.Object3D | null>(() => rootOf(model));
  const axis = section?.axis ?? null;
  const on = !!section && section.at !== null && section.keep !== null;

  // The model's extent along the axis, and the defaults: the middle, the half facing the camera cut away.
  useEffect(() => {
    if (!axis || !root) return;
    root.updateMatrixWorld(true);
    const inverse = root.matrixWorld.clone().invert();
    const box = new THREE.Box3();
    root.traverse((o) => {
      if (o instanceof THREE.Mesh && !o.userData.sectionCap && !o.userData.analysisLayer && o.visible) box.union(new THREE.Box3().setFromObject(o).applyMatrix4(inverse));
    });
    if (box.isEmpty()) return;
    const ends = [fileToBuild(box.min, { zUp, unit }), fileToBuild(box.max, { zUp, unit })];
    const i = { x: 0, y: 1, z: 2 }[axis];
    const min = Math.min(ends[0][i], ends[1][i]);
    const max = Math.max(ends[0][i], ends[1][i]);
    useStudio.setState({ sectionRange: { min, max } });
    const now = useStudio.getState().section;
    if (!now || now.axis !== axis) return;
    const at = now.at === null ? Math.round(((min + max) / 2) * 10) / 10 : Math.min(max, Math.max(min, now.at));
    let keep = now.keep;
    if (keep === null) {
      // The camera's place along the axis: the half on its side goes, so the cut faces it.
      const eye = fileToBuild(root.worldToLocal(camera.position.clone()), { zUp, unit })[i];
      keep = eye > at ? "below" : "above";
    }
    if (at !== now.at || keep !== now.keep) useStudio.setState({ section: { ...now, at, keep } });
  }, [axis, root, zUp, unit, camera]);

  useEffect(() => {
    if (!on || !section) return;
    const n = axisInFile(section.axis, { zUp, unit });
    const offset = (section.at as number) / (unit * 1000);
    // Keep n·p below or above the offset; three.js keeps the side its plane's normal points to.
    if (section.keep === "below") local.current.set(n.clone().negate(), offset);
    else local.current.set(n, -offset);
  }, [on, section, zUp, unit]);

  useEffect(() => {
    if (!on || !root) return;
    gl.localClippingEnabled = true;
    useStudio.setState({ clip: world.current });
    const previous = get().events.filter;
    // The hover and a click on a part go through what the cut took away.
    setEvents({ filter: (items: THREE.Intersection[], state: RootState) => (previous ? previous(items, state) : items).filter(keptByCut) });
    const own = caps.current;
    return () => {
      setEvents({ filter: previous });
      useStudio.setState({ clip: null });
      for (const [mesh, cap] of own) {
        mesh.remove(cap);
        (cap.material as THREE.Material).dispose();
      }
      own.clear();
      root.traverse((o) => {
        if (!(o instanceof THREE.Mesh || o instanceof THREE.LineSegments)) return;
        for (const m of (Array.isArray(o.material) ? o.material : [o.material]) as THREE.Material[]) {
          if (m.clippingPlanes === planes.current) m.clippingPlanes = null;
        }
      });
    };
  }, [on, root, gl, get, setEvents]);

  useFrame(() => {
    const found = rootOf(model);
    if (found !== root) setRoot(found);
    if (!on || !root) return;
    world.current.copy(local.current).applyMatrix4(root.matrixWorld);
    // Every surface of the model takes the plane, also what appears later (the surface colours, edges).
    root.traverse((o) => {
      if (!(o instanceof THREE.Mesh || o instanceof THREE.LineSegments)) return;
      const materials = (Array.isArray(o.material) ? o.material : [o.material]) as THREE.Material[];
      for (const m of materials) if (m.clippingPlanes !== planes.current) m.clippingPlanes = planes.current;
      if (!(o instanceof THREE.Mesh) || o.userData.sectionCap || o.userData.analysisLayer || caps.current.has(o)) return;
      const source = materials[0] as THREE.MeshStandardMaterial;
      if (source.transparent && source.opacity < 1) return;
      // A quarter of the part's colour in linear light reads about half as bright on screen: plainly darker, still its part.
      CAP.copy(source.color ?? CAP.set("#9a9da5")).multiplyScalar(0.25);
      // Drawn just in front of the part's own inside, so a two-sided part shows the cut too.
      const material = new THREE.MeshBasicMaterial({ color: CAP.clone(), side: THREE.BackSide, clippingPlanes: planes.current, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -1 });
      const cap = new THREE.Mesh(o.geometry, material);
      cap.userData.sectionCap = true;
      cap.name = o.name + " cut";
      o.add(cap);
      caps.current.set(o, cap);
    });
  });
  return null;
}

function Camera({ center, radius, home, front }: Pick<StudioRigProps, "center" | "radius" | "home" | "front">) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const controls = useThree((s) => s.controls) as unknown as Controls | null;
  const size = useThree((s) => s.size);
  const ortho = useUi((s) => s.studio.ortho);
  const command = useStudio((s) => s.command);
  const move = useRef<Move | null>(null);
  const lens = useRef<{ from: number; to: number; t0: number } | null>(null);
  // The controls' distance limits were set for the 30° lens; this is the factor already applied to them.
  const limits = useRef<{ controls: Controls | null; factor: number }>({ controls: null, factor: 1 });
  const seenCommand = useRef(command?.n ?? 0);

  /** Moves the camera to a new field of view, keeping the framing: distance, clip planes and limits scale along. */
  const applyFov = (fov: number) => {
    const target = controls?.target ?? center;
    const ratio = lensFactor(fov) / lensFactor(camera.fov);
    camera.position.sub(target).multiplyScalar(ratio).add(target);
    camera.near *= ratio;
    camera.far *= ratio;
    camera.fov = fov;
    camera.updateProjectionMatrix();
    if (controls) {
      controls.minDistance *= ratio;
      controls.maxDistance *= ratio;
      limits.current = { controls, factor: limits.current.factor * ratio };
      controls.update();
    }
  };

  // Mounting takes the lens over at once; fresh controls get their limits scaled to it.
  useLayoutEffect(() => {
    const fov = ortho ? ORTHO_FOV : PERSPECTIVE_FOV;
    if (lens.current === null && Math.abs(camera.fov - fov) > 1e-6) applyFov(fov);
    if (controls && limits.current.controls !== controls) {
      const factor = lensFactor(camera.fov);
      controls.minDistance *= factor;
      controls.maxDistance *= factor;
      limits.current = { controls, factor };
    }
    // Only the camera and the controls appearing matter here; lens changes animate below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera, controls]);

  // A lens change animates the field of view, so the model flattens into the orthographic view.
  useEffect(() => {
    const to = ortho ? ORTHO_FOV : PERSPECTIVE_FOV;
    if (Math.abs(camera.fov - to) < 1e-6) return;
    if (move.current && controls) controls.enableDamping = true;
    move.current = null;
    lens.current = { from: camera.fov, to, t0: performance.now() };
    // Only the switch starts it; the controls are read when it runs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ortho, camera]);

  /** The distance at which the whole bounding sphere fits, pulled back like the explode view does. */
  const fitDistance = () => {
    const vfov = THREE.MathUtils.degToRad(camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * (size.width / Math.max(1, size.height)));
    const explode = 1 + 0.9 * shownExplode();
    return (radius / Math.sin(Math.min(vfov, hfov) / 2)) * explode;
  };

  const clampDistance = (d: number) => (controls ? THREE.MathUtils.clamp(d, controls.minDistance, controls.maxDistance) : d);

  /** Keeps a direction inside the controls' polar limits (the Model tab never looks from below the floor). */
  const withinPolar = (dir: THREE.Vector3) => {
    if (!controls) return dir;
    const s = new THREE.Spherical().setFromVector3(dir);
    s.phi = THREE.MathUtils.clamp(s.phi, Math.max(controls.minPolarAngle, 1e-3), Math.min(controls.maxPolarAngle, Math.PI - 1e-3));
    return new THREE.Vector3().setFromSpherical(s).normalize();
  };

  const viewDir = (view: CameraView): THREE.Vector3 => {
    const f = front.clone().normalize();
    if (view === "front") return f;
    // The side view looks from the right of someone facing the front, as in a drawing.
    if (view === "side") return f.clone().negate().cross(UP).normalize();
    // From straight above, with the front at the bottom of the screen.
    if (view === "top") return UP.clone().addScaledVector(f, 0.002).normalize();
    return home.clone().normalize();
  };

  useEffect(() => {
    if (!command || command.n === seenCommand.current || !controls) return;
    seenCommand.current = command.n;
    if (lens.current) return;
    const target = controls.target.clone();
    const offset = camera.position.clone().sub(target);
    const dist = offset.length();
    const dir = offset.normalize();
    let to: Omit<Move, "t0" | "ms"> & { ms: number };
    if (command.kind === "zoom") to = { ms: ZOOM_MS, target: [target, target.clone()], dir: [dir, dir.clone()], dist: [dist, clampDistance(dist * command.factor)] };
    else if (command.kind === "fit") to = { ms: MOVE_MS, target: [target, center.clone()], dir: [dir, dir.clone()], dist: [dist, clampDistance(fitDistance())] };
    else to = { ms: MOVE_MS, target: [target, center.clone()], dir: [dir, withinPolar(viewDir(command.view))], dist: [dist, clampDistance(fitDistance())] };
    // A move ends the turn after a new build (IntroTurn listens for the controls' start).
    controls.dispatchEvent({ type: "start" });
    move.current = { ...to, t0: performance.now() };
    // Each command runs once, with the camera as it stands when it arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [command, controls]);

  useFrame(() => {
    if (!controls) return;
    const now = performance.now();
    const l = lens.current;
    if (l) {
      const t = Math.min(1, (now - l.t0) / LENS_MS);
      applyFov(l.from + (l.to - l.from) * ease(t));
      if (t >= 1) lens.current = null;
      return;
    }
    const m = move.current;
    if (!m) return;
    const t = Math.min(1, (now - m.t0) / m.ms);
    const e = ease(t);
    const target = m.target[0].clone().lerp(m.target[1], e);
    const turn = new THREE.Quaternion().setFromUnitVectors(m.dir[0], m.dir[1]);
    const dir = m.dir[0].clone().applyQuaternion(new THREE.Quaternion().slerp(turn, e));
    // Zooming is multiplicative, so the distance moves evenly in log space.
    const dist = m.dist[0] * (m.dist[1] / m.dist[0]) ** e;
    controls.enableDamping = false;
    controls.target.copy(target);
    camera.position.copy(target).addScaledVector(dir, dist);
    controls.update();
    if (t >= 1) {
      controls.enableDamping = true;
      move.current = null;
    }
  });
  return null;
}

/** Lists the model's part nodes for the assembly tree and hides the ones it switched off. */
function PartVisibility({ model }: { model: THREE.Object3D | null }) {
  const cad = useSession((s) => s.cad);
  const product = useSession((s) => s.product);
  const hidden = useStudio((s) => s.hidden);
  // A model that loads after the rig (the drone suspends while its file loads) counts its children again.
  const [loaded, setLoaded] = useState(0);
  const children = useRef(-1);
  useFrame(() => {
    const n = model?.children.length ?? -1;
    if (n !== children.current) {
      children.current = n;
      setLoaded((v) => v + 1);
    }
  });

  const [parts, setParts] = useState<Map<THREE.Object3D, string>>(new Map());
  useEffect(() => {
    const names = new Set(treeNodes(cad, product === "drone"));
    const found = new Map<THREE.Object3D, string>();
    const taken = new Set<string>();
    model?.traverse((o) => {
      const n = normaliseName(o.name);
      if (o === model || !names.has(n) || taken.has(n)) return;
      found.set(o, n);
      taken.add(n);
    });
    setParts(found);
    useStudio.getState().setNodes(Object.fromEntries([...found].map(([o, n]) => [n, o.name])));
  }, [model, cad, product, loaded]);

  useEffect(() => {
    if (!model) return;
    const off = new Set(hidden);
    for (const [node, name] of parts) node.userData.studioHidden = off.has(name);
    // A mesh belongs to its nearest part node: hiding a motor leaves the propeller on it.
    model.traverse((o) => {
      if (!(o instanceof THREE.Mesh)) return;
      let owner: THREE.Object3D | null = o;
      while (owner && owner !== model && !parts.has(owner)) owner = owner.parent;
      const name = owner ? parts.get(owner) : undefined;
      if (name) o.visible = !off.has(name);
    });
  }, [model, parts, hidden]);
  return null;
}

interface Pin {
  object: THREE.Object3D;
  local: THREE.Vector3;
  /** The point as a note's end, in the build's mm. */
  at: NotePoint;
}

const fmtMm = (mm: number) => (mm >= 1000 ? `${(mm / 1000).toFixed(2)} m` : `${mm.toFixed(mm < 100 ? 1 : 0)} mm`);

/** With the Measure tool, two clicks on the model give the distance between them; the points ride along when parts move.
 * Both points also wait in the studio as a measurement a note to Mechanic can carry. */
function Measure({ model, unit, frame }: { model: THREE.Object3D | null; unit: number; frame: ModelFrame }) {
  const tool = useUi((s) => s.tool);
  const camera = useThree((s) => s.camera);
  const gl = useThree((s) => s.gl);
  const raycaster = useThree((s) => s.raycaster);
  const [pins, setPins] = useState<Pin[]>([]);
  const pinsRef = useRef<Pin[]>([]);
  pinsRef.current = pins;
  const line = useRef<ComponentRef<typeof Line>>(null);
  const dots = useRef<(THREE.Group | null)[]>([]);
  const label = useRef<THREE.Group>(null);
  const [readout, setReadout] = useState<{ mm: number; dx: number; dy: number; dz: number; rise: number } | null>(null);

  useEffect(() => {
    if (tool !== "measure") setPins([]);
  }, [tool]);
  // A new model (another version, another tab) drops the points on the old one.
  useEffect(() => setPins([]), [model]);

  useEffect(() => {
    if (tool !== "measure") return;
    const el = gl.domElement;
    el.style.cursor = "crosshair";
    let down: { x: number; y: number } | null = null;
    const onDown = (e: PointerEvent) => {
      if (e.button === 0) down = { x: e.clientX, y: e.clientY };
    };
    const onUp = (e: PointerEvent) => {
      // A drag turns the camera; only a click sets a point.
      const click = down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5;
      down = null;
      if (!click || !model) return;
      rayAt(raycaster, camera, el, e);
      const hit = hitModel(raycaster, model);
      const at = notePoint(hit, frame);
      if (!hit || !at) return;
      const { cut: _cut, ...end } = at;
      const pin = { object: hit.object, local: hit.object.worldToLocal(hit.point.clone()), at: end };
      setPins((p) => (p.length >= 2 ? [pin] : [...p, pin]));
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (pinsRef.current.length) setPins([]);
      else useUi.getState().setTool("select");
    };
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointerup", onUp);
    window.addEventListener("keydown", onKey);
    return () => {
      el.style.cursor = "";
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointerup", onUp);
      window.removeEventListener("keydown", onKey);
    };
    // The frame is two plain values; a new object each render must not reset the tool.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tool, gl, camera, raycaster, model, frame.zUp, frame.unit]);
  useEffect(() => {
    useStudio.setState({ measurement: pins.length === 2 ? { a: pins[0].at, b: pins[1].at } : null });
  }, [pins]);
  useEffect(() => () => useStudio.setState({ measurement: null }), []);

  const world = (p: Pin) => p.object.localToWorld(p.local.clone());
  const last = useRef("");
  useFrame(() => {
    if (!pins.length) return;
    const points = pins.map(world);
    points.forEach((p, i) => dots.current[i]?.position.copy(p));
    if (points.length < 2) return;
    const [a, b] = points;
    line.current?.geometry.setPositions([a.x, a.y, a.z, b.x, b.y, b.z]);
    label.current?.position.copy(a).add(b).multiplyScalar(0.5);
    // Scene axes to CAD axes: x stays, CAD y runs along -z, CAD z is up.
    const d = b.clone().sub(a).multiplyScalar(unit * 1000);
    const mm = d.length();
    const next = { mm, dx: Math.abs(d.x), dy: Math.abs(d.z), dz: Math.abs(d.y), rise: mm > 0 ? THREE.MathUtils.radToDeg(Math.asin(Math.abs(d.y) / mm)) : 0 };
    const key = `${next.mm.toFixed(1)} ${next.dx.toFixed(1)} ${next.dy.toFixed(1)} ${next.dz.toFixed(1)}`;
    if (key !== last.current) {
      last.current = key;
      setReadout(next);
    }
  });
  useEffect(() => {
    if (pins.length < 2) {
      last.current = "";
      setReadout(null);
    }
  }, [pins]);

  if (!pins.length) return null;
  const start = world(pins[0]);
  return (
    <group>
      {pins.map((p, i) => (
        <group key={i} ref={(g) => void (dots.current[i] = g)} position={world(p)}>
          <Html center zIndexRange={[30, 30]} style={{ pointerEvents: "none" }}>
            <span className="block h-3 w-3 rounded-full bg-ink ring-[2.5px] ring-white shadow-[var(--shadow-pill)]" />
          </Html>
        </group>
      ))}
      {pins.length === 2 && (
        <>
          <Line ref={line} points={[start, world(pins[1])]} color="#1a1a18" lineWidth={2} depthTest={false} transparent opacity={0.9} renderOrder={30} />
          <group ref={label}>
            {readout && (
              <Html center zIndexRange={[31, 31]} style={{ pointerEvents: "none" }}>
                {/* Lifted off the line's middle, so the line stays visible under it. */}
                <div className="flex -translate-y-8 flex-col items-center rounded-[12px] bg-ink px-3 py-1.5 text-center whitespace-nowrap text-white shadow-[var(--shadow-float)]" data-target="measure:readout">
                  <span className="num text-[15px] font-bold">{fmtMm(readout.mm)}</span>
                  <span className="num font-label text-[11px] text-white/75">
                    x {readout.dx.toFixed(1)} · y {readout.dy.toFixed(1)} · z {readout.dz.toFixed(1)} · {Math.round(readout.rise)}° up
                  </span>
                </div>
              </Html>
            )}
          </group>
        </>
      )}
    </group>
  );
}
