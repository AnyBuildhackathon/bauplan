// CAD tab: the part from the latest `cad` event (glb_url) in 3D, its feature tree,
// the parameters as sliders (POST /api/cad/params, the next `cad` event updates
// the view), a small image of the real FreeCAD view and "In FreeCAD öffnen".
import { OrbitControls } from "@react-three/drei";
import { Canvas, useLoader, useThree } from "@react-three/fiber";
import { ChevronRight, Download, ExternalLink, FileCode2, Layers, RefreshCw, X } from "lucide-react";
import { Component, Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { useSession } from "../../events/store";
import { useSource } from "../../events/source";
import type { CadEvent, CadNode, CadParam } from "../../events/types";
import { assetUrl } from "../../lib/api";
import { fmtNum } from "../../lib/format";
import { useHighlight } from "../../lib/hooks";
import { lookFor, materialKey, materialsFromTree, pbrMaterial } from "../../lib/materials";
import { isLive } from "../../lib/motion";
import { AnalysisLayer } from "./AnalysisLayer";
import { useAssemblyFlyIn } from "./AssemblyMotion";
import { normaliseName } from "../../lib/targets";
import { AnchorScope, useAnchor } from "./anchors";
import { GridStage, usePrefersReducedMotion } from "./GridStage";
import { ExplodeCamera, ExplodeLayer, type PieceSpec } from "./explode";
import { IntroTurn } from "./IntroTurn";
import { StudioOverlay } from "../studio/StudioOverlay";
import { StudioRig } from "../studio/StudioRig";

export const CAD_SOURCE_LABEL = { freecad: "FreeCAD", cadquery: "CadQuery", solidcraft: "SolidCraft" } as const;

/** Generated parts are millimetres with Z up, like FreeCAD; the drone's GLB is metres with Y up (docs/events.md). */
const MM = 0.001;
/** The camera's default direction, and the front view: FreeCAD's front (-Y) is +Z once a part stands Y up; the drone's nose is -Z. */
const HOME = new THREE.Vector3(0.75, 0.62, 0.95).normalize();
const FRONT_Z_UP = new THREE.Vector3(0, 0, 1);
const FRONT_DRONE = new THREE.Vector3(0, 0, -1);

/** The model's size and the height it stands at, for the studio grid under it. */
interface Bounds {
  size: number;
  floor: number;
}

const PARAM_LABELS: Record<string, string> = {
  arm_length_mm: "Arm length",
  thickness_mm: "Arm thickness",
  motor_spacing_mm: "Bolt circle",
  diagonal_mm: "Diagonal",
  plate_width_mm: "Plate width",
};
/** "finger_length_mm" as "Finger length"; a product's "base.length_mm" as "Base length". */
export const paramLabel = (key: string) =>
  PARAM_LABELS[key] ?? key.replace(/_(mm|deg|g)$/, "").replace(/[._]/g, " ").replace(/^\w/, (c) => c.toUpperCase());

class LoadBoundary extends Component<{ children: ReactNode; fallback: ReactNode; resetKey: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.failed) this.setState({ failed: false });
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

const AGENT = new THREE.Color("#ff8a3d");

/** A generated body names its color `pai:#rrggbb`, or `pai:#rrggbbaa` when it is see-through (a load). */
export function partColor(name: string): { color: string; opacity: number } {
  if (!name.startsWith("pai:")) return { color: "#c9ccd3", opacity: 1 };
  // The drone's materials add their look after a space: `pai:#c9ccd3 carbon`.
  const hex = name.slice(4).split(" ")[0];
  return hex.length === 9 ? { color: hex.slice(0, 7), opacity: parseInt(hex.slice(7), 16) / 255 } : { color: hex, opacity: 1 };
}

/** "finger_left" or "Base_plate" (GLTFLoader turns spaces into underscores) as a label. */
const prettyName = (raw: string) => raw.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

function Part({
  url,
  zUp,
  staged,
  onBounds,
  edged,
  still,
  explodable = false,
  unit,
}: {
  url: string;
  zUp: boolean;
  /** Stands the model on the floor at y = 0 (the Model tab). */
  staged: boolean;
  onBounds: (bounds: Bounds) => void;
  edged: boolean;
  still: boolean;
  explodable?: boolean;
  unit: number;
}) {
  const bodies = useSession((s) => s.cad?.bodies);
  const gltf = useLoader(GLTFLoader, url);
  const cad = useSession((s) => s.cad);
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3; update: () => void } | null;
  const highlight = useHighlight();
  const glow = highlight.has("frame");

  // A studio PBR material per part (lib/materials.ts), plus crisp edges in the CAD tab.
  const tree = cad?.tree;
  const single = cad?.part && !cad.assembly ? cad.part.material : "";
  const { object, center, radius, size: partSize, floor, edges } = useMemo(() => {
    const looks = materialsFromTree(tree ?? []);
    const fallback = single ? materialKey(single) : null;
    const root = gltf.scene.clone(true);
    // Generated parts are modelled Z-up like FreeCAD; three.js is Y-up.
    if (zUp) {
      root.rotation.x = -Math.PI / 2;
      root.updateMatrixWorld(true);
    }
    let box = new THREE.Box3().setFromObject(root);
    // On the stage the part stands on the floor at y = 0.
    if (staged) {
      root.position.y -= box.min.y;
      root.updateMatrixWorld(true);
      box = new THREE.Box3().setFromObject(root);
    }
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const lines: THREE.LineSegments[] = [];
    root.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        // A generated part names its colors `pai:#rrggbb`; everything else gets the calm CAD grey.
        const { color, opacity } = partColor((o.material as THREE.Material | undefined)?.name ?? "");
        o.material = pbrMaterial(lookFor(o, looks, fallback), color, opacity, AGENT);
        o.castShadow = true;
        if (!edged) return;
        const e = new THREE.LineSegments(new THREE.EdgesGeometry(o.geometry, 30), new THREE.LineBasicMaterial({ color: "#2b2d33", transparent: true, opacity: 0.55 }));
        e.matrixAutoUpdate = false;
        o.add(e);
        lines.push(e);
      }
    });
    const extent = box.getSize(new THREE.Vector3());
    return { object: root, center: sphere.center, radius: sphere.radius || 1, size: Math.max(extent.x, extent.y, extent.z) || 0.1, floor: box.min.y, edges: lines };
  }, [gltf, zUp, staged, edged, tree, single]);

  // A live assembly flies together; a backlog replay, a seek or reduced motion just shows it.
  const fly = !still && !!cad?.assembly && isLive(cad.at) && assetUrl(cad.glb_url) === url;
  useAssemblyFlyIn(object, radius, fly);

  useEffect(() => {
    object.traverse((o) => {
      if (o instanceof THREE.Mesh) (o.material as THREE.MeshStandardMaterial).emissiveIntensity = glow ? 0.18 : 0;
    });
  }, [object, glow]);
  useEffect(() => () => edges.forEach((e) => e.geometry.dispose()), [edges]);
  useEffect(() => onBounds({ size: partSize, floor }), [onBounds, partSize, floor]);

  useLayoutEffect(() => {
    const vfov = THREE.MathUtils.degToRad(camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * (size.width / Math.max(1, size.height)));
    // The part can turn around itself, so the whole bounding sphere has to stay in view.
    const dist = radius / Math.sin(Math.min(vfov, hfov) / 2);
    const dir = new THREE.Vector3(0.75, 0.62, 0.95).normalize();
    camera.position.copy(center).addScaledVector(dir, dist);
    camera.near = dist / 100;
    // On the stage the floor has to reach its fog, about 26 part sizes out.
    camera.far = staged ? Math.max(dist * 10, partSize * 40) : dist * 10;
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(center);
      controls.update();
    }
  }, [camera, center, radius, partSize, staged, size.width, size.height, controls]);

  // One piece per GLB node; an assembled product names its spec part and group per node.
  const specs = useMemo<PieceSpec[]>(() => {
    if (!explodable) return [];
    return object.children.map((node) => {
      const body = bodies?.find((b) => normaliseName(b.name) === normaliseName(node.name));
      const name = body?.part_name ?? prettyName(node.name);
      const label = body && body.name !== body.part_name ? prettyName(body.name) : name;
      // Screws, nuts and inserts come in numbers: they name themselves on hover, without a pill each.
      const pill = body?.kind === "hardware" ? "" : label;
      return { node, key: node.name, label: pill, name: label, group: body?.group ?? null, load: body?.kind === "external", aliases: body ? [body.part_id, body.part_name] : [] };
    });
  }, [object, bodies, explodable]);

  const anchor = useAnchor("frame", radius * 0.8);
  return (
    <>
      {explodable && specs.length > 1 ? (
        <ExplodeLayer root={object} specs={specs} glow>
          <primitive object={object} />
        </ExplodeLayer>
      ) : (
        <primitive object={object} />
      )}
      <group ref={anchor} position={center} />
      <AnalysisLayer root={object} modelUrl={url} />
      <StudioRig model={object} center={center} radius={radius} home={HOME} front={zUp ? FRONT_Z_UP : FRONT_DRONE} unit={unit} />
    </>
  );
}

/** The generated part in 3D on the studio grid; with `stage` it stands on the floor (Model tab), otherwise it keeps its own place (CAD tab). */
export function CadScene({ url, zUp = false, stage = false, explodable = false }: { url: string; zUp?: boolean; stage?: boolean; explodable?: boolean }) {
  const [bounds, setBounds] = useState<Bounds | null>(null);
  const still = usePrefersReducedMotion();
  const unit = zUp ? MM : 1;
  return (
    <>
      <Canvas dpr={[1, 2]} camera={{ fov: 30 }} gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }}>
        <AnchorScope primary>
          <ambientLight intensity={stage ? 0.35 : 0.65} />
          {!stage && (
            <>
              <hemisphereLight args={["#ffffff", "#d9d6e8", 0.7]} />
              <directionalLight position={[3, 5, 2]} intensity={1.7} />
              <directionalLight position={[-3, 2, -2]} intensity={0.5} />
            </>
          )}
          {bounds && (
            <GridStage variant="studio" size={bounds.size} floor={bounds.floor} unit={unit} lights={stage} shadowArea={bounds.size * 3} shadowReach={bounds.size * 0.8} />
          )}
          <Suspense fallback={null}>
            <Part url={url} zUp={zUp} staged={stage} onBounds={setBounds} edged={!stage} still={still} explodable={explodable} unit={unit} />
          </Suspense>
          <OrbitControls makeDefault enablePan={false} maxPolarAngle={stage ? Math.PI / 2.08 : Math.PI} />
          <IntroTurn disabled={still} />
          {explodable && <ExplodeCamera />}
        </AnchorScope>
      </Canvas>
      <StudioOverlay />
    </>
  );
}

function TreeNode({ node, depth }: { node: CadNode; depth: number }) {
  const [open, setOpen] = useState(depth < 2);
  const hasKids = node.children?.length > 0;
  return (
    <li>
      <button
        type="button"
        onClick={() => hasKids && setOpen(!open)}
        className={`flex w-full items-center gap-1.5 rounded-lg py-1 pr-2 text-left text-[14px] ${hasKids ? "hover:bg-tile" : "cursor-default"}`}
        style={{ paddingLeft: 4 + depth * 14 }}
      >
        <ChevronRight className={`h-3.5 w-3.5 shrink-0 text-faint transition ${hasKids ? "" : "opacity-0"} ${open ? "rotate-90" : ""}`} />
        <span className={`h-2 w-2 shrink-0 rounded-[3px] ${depth === 0 ? "bg-ink" : "bg-track"}`} />
        <span className={`truncate ${depth === 0 ? "font-bold text-ink" : "font-medium text-ink-2"}`}>{node.label}</span>
      </button>
      {hasKids && open && (
        <ul>
          {node.children.map((c) => (
            <TreeNode key={c.id} node={c} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

function ParamSlider({
  name,
  param,
  value,
  pending,
  onChange,
  onCommit,
}: {
  name: string;
  param: CadParam;
  value: number;
  pending: boolean;
  onChange: (v: number) => void;
  onCommit: () => void;
}) {
  const span = param.max - param.min || 1;
  const pct = ((value - param.min) / span) * 100;
  const step = span <= 10 ? 0.1 : span <= 50 ? 0.5 : 1;
  const changed = Math.abs(value - param.value) > 1e-9;
  return (
    <label className="block" data-target={`param:${name} ${name}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="min-w-0 truncate text-[14px] font-semibold text-ink-2" title={param.label ?? paramLabel(name)}>{param.label ?? paramLabel(name)}</span>
        <span className={`num shrink-0 text-[15px] font-bold whitespace-nowrap ${pending ? "text-agent-ink" : changed ? "text-ink" : "text-ink"}`}>
          {changed && <span className="mr-1 text-[13px] font-semibold text-faint">{fmtNum(param.value, step < 1 ? 1 : 0)} →</span>}
          {fmtNum(value, step < 1 ? 1 : 0)} {param.unit}
        </span>
      </div>
      <input
        type="range"
        min={param.min}
        max={param.max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        onPointerUp={onCommit}
        onKeyUp={(e) => ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(e.key) && onCommit()}
        className={`bevel-range mt-1.5 w-full ${pending ? "is-pending" : ""}`}
        style={{ "--p": `${pct}%` } as React.CSSProperties}
        aria-label={param.label ?? paramLabel(name)}
      />
      <div className="num flex justify-between text-[11px] font-semibold text-faint">
        <span>{fmtNum(param.min)}</span>
        <span>{fmtNum(param.max)}</span>
      </div>
    </label>
  );
}

/** The script behind a generated part (FreeCAD Python, or SolidCraft's command script), so everyone can see what Claude wrote. */
function ScriptPanel({ url, title, onClose }: { url: string; title: string; onClose: () => void }) {
  const [code, setCode] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    fetch(url)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((text) => live && setCode(text))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [url]);
  return (
    <div className="absolute inset-0 z-20 flex flex-col bg-[#16171b]/95 backdrop-blur">
      <div className="flex shrink-0 items-center gap-3 px-4 py-2.5">
        <FileCode2 className="h-4 w-4 text-white/70" />
        <span className="text-[14px] font-bold text-white">{title}</span>
        <span className="text-[13px] font-semibold text-white/50">runs headless in a sandbox</span>
        <button type="button" onClick={onClose} className="ml-auto rounded-full p-1.5 text-white/70 hover:bg-white/10" aria-label="Close script">
          <X className="h-4 w-4" />
        </button>
      </div>
      <pre className="scroll-soft min-h-0 flex-1 overflow-auto px-4 pb-4 font-mono text-[12.5px] leading-[1.55] text-[#e7e8ec]">
        {failed ? "The script could not be loaded." : code ?? "Loading …"}
      </pre>
    </div>
  );
}

function PartFacts({ part, assembly }: { part: NonNullable<CadEvent["part"]>; assembly: boolean }) {
  const b = part.bbox_mm;
  const size = b.length === 6 ? [0, 1, 2].map((i) => fmtNum(b[i + 3] - b[i], 0)).join(" × ") : "";
  const runs = `${part.attempts} FreeCAD run${part.attempts === 1 ? "" : "s"}`;
  const fixed = `by Claude, fixed after ${part.attempts - 1} error${part.attempts > 2 ? "s" : ""}`;
  const script = !part.generated ? "library template" : assembly ? `by Claude, ${runs}` : part.attempts > 1 ? fixed : "by Claude";
  const rows: [string, string][] = [
    [assembly ? "Printed parts" : "Printed mass", `${fmtNum(part.mass_g, 1)} g ${part.material}`],
    ["Size", `${size} mm`],
    [assembly ? "Scripts" : "Script", script],
  ];
  return (
    <section className="mt-4">
      <h3 className="eyebrow mb-1">Part</h3>
      <dl className="space-y-1">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-3 text-[14px]">
            <dt className="font-semibold text-ink-2">{k}</dt>
            <dd className="num truncate text-right font-bold text-ink">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function CadView() {
  const cad = useSession((s) => s.cad);
  const cadStep = useSession((s) => s.steps.cad.status);
  const { setCadParams, openInFreecad, pressControl } = useSource.getState();
  const [values, setValues] = useState<Record<string, number>>({});
  const [pending, setPending] = useState<string | null>(null);
  const [showScript, setShowScript] = useState(false);
  const answeredBy = useRef(0);

  // A new `cad` event is the backend's answer: take its values, clear the pending state.
  useEffect(() => {
    if (!cad) return;
    setValues(Object.fromEntries(Object.entries(cad.params).map(([k, p]) => [k, p.value])));
    if (cad.n > answeredBy.current) setPending(null);
  }, [cad]);

  if (!cad) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
        <Layers className="h-8 w-8 text-faint" />
        <p className="text-[18px] font-semibold text-ink-2">{cadStep === "running" ? "FreeCAD is building the part …" : "No CAD part yet"}</p>
        <p className="max-w-sm text-[15px] text-muted">FreeCAD builds every printed part in the CAD step. Then the sliders here change its dimensions and the checks run again.</p>
      </div>
    );
  }

  const glb = assetUrl(cad.glb_url);
  const view = assetUrl(cad.view_png_url);
  const stl = assetUrl(cad.stl_url);
  const step = assetUrl(cad.step_url);
  const script = assetUrl(cad.script_url ?? null);
  const source = CAD_SOURCE_LABEL[cad.source] ?? cad.source;

  const commit = async (name: string) => {
    const v = values[name];
    if (v === undefined || Math.abs(v - cad.params[name].value) < 1e-9) return;
    answeredBy.current = cad.n;
    setPending(name);
    const ok = await setCadParams({ [name]: v });
    if (!ok) {
      setPending(null);
      setValues((prev) => ({ ...prev, [name]: cad.params[name].value }));
    }
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_268px]">
      <div className="relative min-h-0 min-w-0">
        {glb ? (
          <LoadBoundary
            resetKey={glb}
            fallback={<div className="flex h-full items-center justify-center px-6 text-center text-[15px] text-muted">The 3D model failed to load ({glb}).</div>}
          >
            <CadScene url={glb} zUp={!!cad.part} explodable />
          </LoadBoundary>
        ) : (
          <div className="flex h-full items-center justify-center text-[15px] text-muted">No 3D model in the CAD event.</div>
        )}
        <span className="pointer-events-none absolute top-3 left-3 inline-flex h-8 items-center gap-2 rounded-full bg-white/90 px-3.5 text-[13px] font-bold text-ink-2 shadow-[var(--shadow-pill)]">
          <span className={`h-2 w-2 rounded-full ${cad.source === "freecad" ? "bg-[#d23f31]" : "bg-sky"}`} />
          {source}
          {pending && <span className="font-semibold text-agent-ink">· computing …</span>}
        </span>
        {script && (
          <button
            type="button"
            onClick={() => setShowScript(true)}
            data-target="cad_script script"
            className="absolute top-3 right-3 inline-flex h-8 items-center gap-1.5 rounded-full bg-ink px-3.5 text-[13px] font-bold text-white shadow-[var(--shadow-pill)] hover:bg-[#333]"
          >
            <FileCode2 className="h-3.5 w-3.5" /> Script
          </button>
        )}
        {script && showScript && (
          <ScriptPanel url={script} title={cad.source === "solidcraft" ? "SolidCraft script" : "FreeCAD script"} onClose={() => setShowScript(false)} />
        )}
      </div>

      <div className="scroll-soft min-h-0 overflow-y-auto border-l border-line bg-card/70 px-4 py-3.5">
        <section>
          <h3 className="eyebrow mb-1">Feature tree</h3>
          <ul className="-mx-1">
            {cad.tree.map((n) => (
              <TreeNode key={n.id} node={n} depth={0} />
            ))}
          </ul>
        </section>

        {cad.part && <PartFacts part={cad.part} assembly={!!cad.assembly} />}

        {Object.keys(cad.params).length > 0 && (
          <section className="mt-4 space-y-3">
            <h3 className="eyebrow">Parameters</h3>
            {Object.entries(cad.params).map(([name, p]) => (
              <ParamSlider
                key={name}
                name={name}
                param={p}
                value={values[name] ?? p.value}
                pending={pending === name}
                onChange={(v) => setValues((prev) => ({ ...prev, [name]: v }))}
                onCommit={() => void commit(name)}
              />
            ))}
          </section>
        )}

        <section className="mt-4">
          {(view || !cad.part) && (
            <>
          <h3 className="eyebrow mb-1.5">FreeCAD view</h3>
          <div className="overflow-hidden rounded-2xl bg-tile ring-1 ring-line">
            {view ? (
              <img src={view} alt="View from FreeCAD" className="block aspect-[4/3] w-full object-cover" />
            ) : (
              <div className="flex aspect-[4/3] items-center justify-center px-4 text-center text-[13px] text-muted">
                Appears once the part is open in FreeCAD.
              </div>
            )}
          </div>
            </>
          )}
          <button
            type="button"
            onClick={() => void pressControl("run:rebuild")}
            data-control="run:rebuild"
            className="mt-2.5 flex h-10 w-full items-center justify-center gap-2 rounded-full bg-tile text-[14px] font-semibold text-ink shadow-[var(--shadow-pill)] hover:bg-track"
          >
            <RefreshCw className="h-4 w-4" /> Rebuild and recheck
          </button>
          <button
            type="button"
            onClick={() => void openInFreecad()}
            data-target="freecad_open in_freecad_oeffnen"
            className="mt-2.5 flex h-10 w-full items-center justify-center gap-2 rounded-full bg-ink text-[14px] font-semibold text-white shadow-[var(--shadow-pill)] hover:bg-[#333]"
          >
            <ExternalLink className="h-4 w-4" /> Open in FreeCAD
          </button>
          {(stl || step) && (
            <div className="mt-2 flex gap-2">
              {stl && (
                <a href={stl} download className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-full bg-tile text-[13px] font-semibold text-ink-2 hover:bg-track">
                  <Download className="h-3.5 w-3.5" /> STL
                </a>
              )}
              {step && (
                <a href={step} download className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-full bg-tile text-[13px] font-semibold text-ink-2 hover:bg-track">
                  <Download className="h-3.5 w-3.5" /> STEP
                </a>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
