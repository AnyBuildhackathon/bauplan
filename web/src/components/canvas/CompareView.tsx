// Two versions side by side in the Model tab: one synchronised camera for both
// canvases, the parts that changed glow in the agent orange, and a table of the
// parts and numbers underneath. Opened from the version history drawer.
import { Environment, Lightformer, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useLoader, useThree } from "@react-three/fiber";
import { ArrowRight, X } from "lucide-react";
import { Component, Suspense, useEffect, useId, useLayoutEffect, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { useSession } from "../../events/store";
import type { VersionEvent } from "../../events/types";
import { assetUrl } from "../../lib/api";
import { enLabel } from "../../lib/copy";
import { fmtNum } from "../../lib/format";
import { useUi } from "../../lib/ui";
import { partColor } from "./CadView";
import { HeroDrone, useDroneUrl } from "./HeroDrone";

const AGENT = new THREE.Color("#ff8a3d");
/** The kickoff's pack, the Tattu R-Line 1S 550 of the reference build. */
const RLINE_550: [number, number, number] = [59, 18, 8];

/** Drone part categories to the scene keys HeroDrone highlights. */
const DRONE_KEYS: Record<string, string> = {
  battery: "battery",
  motor: "motors",
  propeller: "propellers",
  flight_controller: "flight_controller",
  frame: "frame",
  canopy: "frame",
};

/** One camera for both canvases: whoever moves writes it, the other copies it on its next frame. */
interface SharedCamera {
  position: THREE.Vector3;
  target: THREE.Vector3;
  stamp: number;
  owner: string;
}

type Controls = { target: THREE.Vector3; update: () => void };

function CameraSync({ shared, me }: { shared: SharedCamera; me: string }) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as unknown as Controls | null;
  const seen = useRef(0);
  const applying = useRef(false);
  useEffect(() => {
    const c = controls as unknown as THREE.EventDispatcher<{ change: object }> | null;
    if (!c) return;
    const onChange = () => {
      if (applying.current) return;
      shared.position.copy(camera.position);
      shared.target.copy((controls as Controls).target);
      shared.owner = me;
      seen.current = ++shared.stamp;
    };
    c.addEventListener("change", onChange);
    return () => c.removeEventListener("change", onChange);
  }, [controls, camera, shared, me]);
  useFrame(() => {
    if (!controls || seen.current === shared.stamp) return;
    seen.current = shared.stamp;
    if (shared.owner === me) return;
    applying.current = true;
    camera.position.copy(shared.position);
    controls.target.copy(shared.target);
    controls.update();
    applying.current = false;
  });
  return null;
}

class LoadBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function NoModel() {
  return (
    <div className="flex h-full items-center justify-center px-6 text-center text-[15px] font-medium text-muted">
      No model saved for this version
    </div>
  );
}

function DroneScene({ version, highlight, shared }: { version: VersionEvent; highlight: Set<string>; shared: SharedCamera }) {
  const byName = useSession((s) => s.partsByName);
  const current = useDroneUrl();
  const me = useId();
  // A recording or an old run has no model copy: draw the shown drone with that version's pack.
  const url = assetUrl(version.files?.glb_url ?? null) ?? current;
  const size = byName[version.parts.battery]?.size_mm ?? RLINE_550;
  const battery: [number, number, number] = [size[0] / 1000, size[1] / 1000, size[2] / 1000];
  return (
    <Canvas dpr={[1, 2]} camera={{ position: [0.17, 0.14, 0.19], fov: 30, near: 0.005, far: 10 }} gl={{ antialias: true, alpha: true }}>
      <ambientLight intensity={0.7} />
      <hemisphereLight args={["#ffffff", "#d9d6e8", 0.6]} />
      <directionalLight position={[0.4, 0.8, 0.3]} intensity={1.8} />
      <Environment resolution={128} environmentIntensity={0.75}>
        <Lightformer form="rect" intensity={3} position={[0, 2, 0]} rotation={[Math.PI / 2, 0, 0]} scale={[3, 3, 1]} />
        <Lightformer form="ring" intensity={2} position={[0, 0.8, 2.4]} scale={1.2} />
      </Environment>
      <group position={[0, battery[2] + 0.0028, 0]}>
        <Suspense fallback={null}>
          <HeroDrone url={url} battery={battery} highlight={highlight} />
        </Suspense>
      </group>
      <OrbitControls makeDefault enableDamping={false} enablePan={false} minDistance={0.09} maxDistance={0.45} target={[0, 0.012, 0]} maxPolarAngle={Math.PI / 2.08} />
      <CameraSync shared={shared} me={me} />
    </Canvas>
  );
}

function ProductModel({ url, glow }: { url: string; glow: Set<string> }) {
  const gltf = useLoader(GLTFLoader, url);
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const controls = useThree((s) => s.controls) as unknown as Controls | null;
  const { object, center, radius } = useMemo(() => {
    const root = gltf.scene.clone(true);
    // Generated parts are modelled Z-up like FreeCAD; three.js is Y-up.
    root.rotation.x = -Math.PI / 2;
    root.updateMatrixWorld(true);
    root.traverse((o) => {
      if (!(o instanceof THREE.Mesh)) return;
      let named: THREE.Object3D | null = o;
      while (named && !glow.has(named.name)) named = named.parent;
      const { color, opacity } = partColor((o.material as THREE.Material | undefined)?.name ?? "");
      o.material = new THREE.MeshStandardMaterial({
        color,
        roughness: 0.55,
        metalness: 0.08,
        emissive: AGENT,
        emissiveIntensity: named ? 0.35 : 0,
        transparent: opacity < 1,
        opacity,
      });
    });
    const sphere = new THREE.Box3().setFromObject(root).getBoundingSphere(new THREE.Sphere());
    return { object: root, center: sphere.center, radius: sphere.radius || 1 };
  }, [gltf, glow]);
  useLayoutEffect(() => {
    // Both panes start from the same direction; the shared camera keeps them together after.
    const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov) / 2);
    camera.position.copy(center).addScaledVector(new THREE.Vector3(0.75, 0.62, 0.95).normalize(), dist);
    camera.near = dist / 100;
    camera.far = dist * 10;
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(center);
      controls.update();
    }
  }, [camera, controls, center, radius]);
  return <primitive object={object} />;
}

function ProductScene({ version, glow, shared }: { version: VersionEvent; glow: Set<string>; shared: SharedCamera }) {
  const me = useId();
  const url = assetUrl(version.files?.glb_url ?? null);
  if (!url) return <NoModel />;
  return (
    <Canvas dpr={[1, 2]} camera={{ fov: 30 }} gl={{ antialias: true, alpha: true }}>
      <ambientLight intensity={0.65} />
      <hemisphereLight args={["#ffffff", "#d9d6e8", 0.7]} />
      <directionalLight position={[3, 5, 2]} intensity={1.7} />
      <Suspense fallback={null}>
        <ProductModel url={url} glow={glow} />
      </Suspense>
      <OrbitControls makeDefault enableDamping={false} enablePan={false} />
      <CameraSync shared={shared} me={me} />
    </Canvas>
  );
}

interface Row {
  key: string;
  label: string;
  before: string;
  after: string;
  delta: string;
  /** Whether the change is good, bad, or neither. */
  tone: "ok" | "fail" | "none";
  changed: boolean;
}

const DRONE_NUMBERS = [
  { key: "weight_g", label: "Weight", unit: "g", digits: 1, better: -1 },
  { key: "flight_time_min", label: "Flight time", unit: "min", digits: 1, better: 1 },
  { key: "price_eur", label: "Price", unit: "€", digits: 2, better: -1 },
  { key: "thrust_to_weight", label: "Thrust/weight", unit: ": 1", digits: 2, better: 1 },
] as const;

function numberRow(key: string, label: string, unit: string, digits: number, better: number, a: unknown, b: unknown): Row | null {
  if (typeof a !== "number" && typeof b !== "number") return null;
  const show = (v: unknown) => (typeof v === "number" ? `${fmtNum(v, digits)} ${unit}`.trim() : "–");
  const d = typeof a === "number" && typeof b === "number" ? b - a : 0;
  const changed = Math.abs(d) >= 10 ** -digits / 2;
  const tone = !changed || !better ? "none" : d * better > 0 ? "ok" : "fail";
  return { key, label, before: show(a), after: show(b), delta: changed ? `${d > 0 ? "+" : "−"}${fmtNum(Math.abs(d), digits)}` : "", tone, changed };
}

function compareRows(a: VersionEvent, b: VersionEvent): Row[] {
  const rows: Row[] = [];
  const drone = (b.product ?? "drone") === "drone";
  for (const m of drone ? DRONE_NUMBERS : DRONE_NUMBERS.filter((m) => m.key === "weight_g" || m.key === "price_eur")) {
    const row = numberRow(m.key, m.label, m.unit, m.digits, m.better, a[m.key], b[m.key]);
    if (row) rows.push(row);
  }
  const before = new Map((a.cards ?? []).map((c) => [c.key, c]));
  for (const card of b.cards ?? []) {
    const old = before.get(card.key);
    if (!old || rows.some((r) => r.key === card.key)) continue;
    const row = numberRow(card.key, card.label, card.unit, card.digits ?? 1, 0, old.value, card.value);
    if (row) rows.push(row);
  }
  for (const category of new Set([...Object.keys(a.parts), ...Object.keys(b.parts)])) {
    const x = a.parts[category] ?? "–";
    const y = b.parts[category] ?? "–";
    rows.push({ key: `part:${category}`, label: enLabel(category.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())), before: x, after: y, delta: "", tone: "none", changed: x !== y });
  }
  for (const [name, value] of Object.entries(b.params ?? {})) {
    const old = a.params?.[name];
    if (typeof old !== "number" || old === value) continue;
    const row = numberRow(`param:${name}`, name, name.endsWith("_mm") ? "mm" : "", 1, 0, old, value);
    if (row) rows.push(row);
  }
  const reqs = new Map((a.requirements ?? []).map((r) => [r.id, r]));
  for (const r of b.requirements ?? []) {
    const old = reqs.get(r.id);
    if (!old || old.met === null || r.met === null || old.met === r.met) continue;
    rows.push({ key: `req:${r.id}`, label: r.text, before: old.met ? "pass" : "fail", after: r.met ? "pass" : "fail", delta: "", tone: r.met ? "ok" : "fail", changed: true });
  }
  return rows;
}

/** Scene keys (drone) or GLB node names (any other product) of the parts that differ. */
function changedParts(a: VersionEvent, b: VersionEvent, drone: boolean): Set<string> {
  const out = new Set<string>();
  for (const category of new Set([...Object.keys(a.parts), ...Object.keys(b.parts)])) {
    if (a.parts[category] === b.parts[category]) continue;
    if (drone) {
      if (DRONE_KEYS[category]) out.add(DRONE_KEYS[category]);
    } else {
      for (const v of [a, b]) {
        const node = v.nodes?.[category] ?? v.parts[category];
        if (node) out.add(node);
      }
    }
  }
  if (!drone) {
    for (const name of Object.keys(b.params ?? {})) {
      if (a.params?.[name] === b.params?.[name]) continue;
      const partId = name.split(".")[0];
      for (const v of [a, b]) {
        const node = v.nodes?.[partId];
        if (node) out.add(node);
      }
    }
  }
  return out;
}

function Pane({ version, side, glow, shared, drone }: { version: VersionEvent; side: "A" | "B"; glow: Set<string>; shared: SharedCamera; drone: boolean }) {
  return (
    <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden rounded-[16px] bg-white/60 ring-1 ring-line">
      <div className="absolute top-3 left-3 z-10 flex max-w-[85%] items-center gap-2 rounded-full bg-white/90 py-1 pr-3 pl-1 shadow-[var(--shadow-pill)] backdrop-blur">
        <span className={`num rounded-full px-2 py-0.5 text-[13px] font-bold text-white ${version.sim === "fail" ? "bg-fail" : "bg-ok"}`}>v{version.n}</span>
        <span className="truncate text-[14px] font-semibold text-ink">{version.label || `v${version.n}`}</span>
        <span className="sr-only">version {side}</span>
      </div>
      <LoadBoundary fallback={<NoModel />}>
        {drone ? <DroneScene version={version} highlight={glow} shared={shared} /> : <ProductScene version={version} glow={glow} shared={shared} />}
      </LoadBoundary>
    </div>
  );
}

const TONE = { ok: "text-ok-ink", fail: "text-fail-ink", none: "text-ink-2" } as const;

export function CompareView({ pair }: { pair: [number, number] }) {
  const versions = useSession((s) => s.versions);
  const setCompare = useUi((s) => s.setCompare);
  const a = versions.find((v) => v.n === pair[0]);
  const b = versions.find((v) => v.n === pair[1]);
  const shared = useMemo<SharedCamera>(() => ({ position: new THREE.Vector3(), target: new THREE.Vector3(), stamp: 0, owner: "" }), []);
  if (!a || !b) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-[16px] text-muted">
        These versions are gone (the session was reset).
        <button type="button" onClick={() => setCompare(null)} className="rounded-full bg-card px-4 py-2 font-semibold text-ink shadow-[var(--shadow-pill)]">
          Back to the model
        </button>
      </div>
    );
  }
  const drone = (b.product ?? "drone") === "drone";
  const glow = changedParts(a, b, drone);
  const rows = compareRows(a, b);
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 p-3" data-target="compare">
      <div className="flex shrink-0 items-center gap-3 px-1">
        <h3 className="num text-[16px] font-semibold text-ink">
          v{a.n} <ArrowRight className="inline h-4 w-4 text-muted" /> v{b.n}
        </h3>
        <span className="text-[14px] text-muted">One camera for both. Changed parts glow.</span>
        <button
          type="button"
          onClick={() => setCompare(null)}
          data-control="panel:compare:close"
          className="ml-auto flex items-center gap-1.5 rounded-full bg-card py-1.5 pr-3 pl-2.5 text-[14px] font-semibold text-ink-2 shadow-[var(--shadow-pill)] hover:bg-page-2"
        >
          <X className="h-4 w-4" /> Close compare
        </button>
      </div>
      <div className="flex min-h-0 flex-1 gap-3">
        <Pane version={a} side="A" glow={glow} shared={shared} drone={drone} />
        <Pane version={b} side="B" glow={glow} shared={shared} drone={drone} />
      </div>
      <div className="max-h-[42%] shrink-0 overflow-auto rounded-[16px] bg-card px-4 py-2 ring-1 ring-line">
        <table className="num w-full text-[14px]">
          <thead>
            <tr className="text-left text-[13px] font-semibold text-muted">
              <th className="py-1.5 pr-3 font-semibold"></th>
              <th className="py-1.5 pr-3 font-semibold">v{a.n}</th>
              <th className="py-1.5 pr-3 font-semibold">v{b.n}</th>
              <th className="py-1.5 text-right font-semibold">Change</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className={`border-t border-line ${r.changed ? "" : "text-muted"}`} data-target={r.changed ? `diff:${r.key}` : undefined}>
                <td className="py-1.5 pr-3 font-semibold text-ink-2">
                  {r.changed && r.key.startsWith("part:") && <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-agent" />}
                  {r.label}
                </td>
                <td className={`py-1.5 pr-3 ${r.changed ? "text-muted" : ""}`}>{r.before}</td>
                <td className={`py-1.5 pr-3 ${r.changed ? "font-semibold text-ink" : ""}`}>{r.after}</td>
                <td className={`py-1.5 text-right font-semibold ${TONE[r.tone]}`}>{r.delta || (r.changed && !r.key.startsWith("part:") ? r.after : "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
