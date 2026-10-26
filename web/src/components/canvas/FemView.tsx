// Simulation tab, Stress pane: the FEM of each printed part (`fem` events) on its real shape,
// coloured by von Mises stress from blue (none) to red (the printed strength), with the
// worst load case, the safety factor against the requirement, the deflection, the loads and
// the FEM's self-check, its notes (a peak that depends on the mesh) in the fail ink.
import { OrbitControls } from "@react-three/drei";
import { Canvas, useLoader, useThree } from "@react-three/fiber";
import { Suspense, useLayoutEffect, useMemo, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { useSession } from "../../events/store";
import type { FemEvent } from "../../events/types";
import { assetUrl } from "../../lib/api";
import { fmtNum } from "../../lib/format";

// The same stops as pai_agent/fem.py colour_map.
const SCALE = "linear-gradient(90deg, #2954d9 0%, #1abdd9 25%, #2ecc70 50%, #facc2e 75%, #ed3333 100%)";

function StressModel({ url, hot }: { url: string; hot: number[] }) {
  const gltf = useLoader(GLTFLoader, url);
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3; update: () => void } | null;
  const { root, center, radius } = useMemo(() => {
    const root = gltf.scene.clone(true);
    root.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        o.material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.65, metalness: 0, side: THREE.DoubleSide });
      }
    });
    // FreeCAD and the FEM mesh are Z-up; three.js is Y-up.
    root.rotation.x = -Math.PI / 2;
    root.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(root);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    return { root, center: sphere.center, radius: sphere.radius || 1 };
  }, [gltf]);
  useLayoutEffect(() => {
    const vfov = THREE.MathUtils.degToRad(camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * (size.width / Math.max(1, size.height)));
    const dist = (radius / Math.sin(Math.min(vfov, hfov) / 2)) * 1.05;
    camera.position.copy(center).addScaledVector(new THREE.Vector3(0.75, 0.62, 0.95).normalize(), dist);
    camera.near = dist / 100;
    camera.far = dist * 10;
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(center);
      controls.update();
    }
  }, [camera, center, radius, size.width, size.height, controls]);
  // The most stressed point, in the model's own (Z-up) frame.
  const marker = new THREE.Vector3(hot[0] ?? 0, hot[1] ?? 0, hot[2] ?? 0).applyMatrix4(root.matrixWorld);
  return (
    <>
      <primitive object={root} />
      {hot.length === 3 && (
        <mesh position={marker}>
          <sphereGeometry args={[radius * 0.035, 20, 14]} />
          <meshBasicMaterial color="#1a1a18" transparent opacity={0.85} />
        </mesh>
      )}
    </>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "ok" | "fail" }) {
  return (
    <div className="min-w-0">
      <div className="truncate text-[12px] font-semibold text-muted">{label}</div>
      <div className={`num text-[17px] font-bold whitespace-nowrap ${tone === "ok" ? "text-ok-ink" : tone === "fail" ? "text-fail-ink" : "text-ink"}`}>{value}</div>
    </div>
  );
}

export function FemView() {
  const fem = useSession((s) => s.fem);
  const order = useSession((s) => s.femOrder);
  const [picked, setPicked] = useState<string | null>(null);
  const id = picked && fem[picked] ? picked : order.at(-1);
  const run: FemEvent | undefined = id ? fem[id] : undefined;
  if (!run) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <p className="text-[18px] font-semibold text-ink-2">No stress simulation yet</p>
        <p className="max-w-sm text-[15px] text-muted">With your 3D printer set, Mechanic simulates each printed part in CalculiX on its real shape.</p>
      </div>
    );
  }
  const url = assetUrl(run.glb_url);
  const pass = run.result === "pass";
  const worst = run.cases.find((c) => c.name === run.governing) ?? run.cases[0];
  return (
    <div className="flex h-full flex-col">
      <div className="relative min-h-0 flex-1">
        {url && (
          <Canvas dpr={[1, 2]} camera={{ fov: 30 }} gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }}>
            <ambientLight intensity={0.75} />
            <hemisphereLight args={["#ffffff", "#d9d6e8", 0.6]} />
            <directionalLight position={[3, 5, 2]} intensity={1.2} />
            <Suspense fallback={null}>
              <StressModel key={url} url={url} hot={run.hot_spot_mm} />
            </Suspense>
            <OrbitControls makeDefault enablePan={false} />
          </Canvas>
        )}
        <div className="absolute top-3 left-3 flex max-w-[calc(100%-180px)] flex-wrap gap-2">
          {order.map((partId) => {
            const r = fem[partId];
            const active = partId === id;
            return (
              <button
                key={partId}
                type="button"
                onClick={() => setPicked(partId)}
                className={`inline-flex h-8 items-center gap-2 rounded-full px-3.5 text-[13px] font-bold shadow-[var(--shadow-pill)] ${active ? "bg-white" : "bg-white/70"} ${
                  r.result === "pass" ? "text-ok-ink" : "text-fail-ink"
                }`}
              >
                <span className="h-2 w-2 rounded-full" style={{ background: r.result === "pass" ? "#2ed3ae" : "#ff5a5f" }} />
                {r.part_name} · {r.safety >= 99 ? "99+" : fmtNum(r.safety, 1)}×
              </button>
            );
          })}
        </div>
      </div>
      <div className="shrink-0 border-t border-line bg-card/80 px-4 py-2.5">
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-4">
          <Stat label={`Safety (min. ${fmtNum(run.limit, 0)}×)`} value={`${run.safety >= 99 ? "99+" : fmtNum(run.safety, 1)}×`} tone={pass ? "ok" : "fail"} />
          <Stat label="Max stress" value={`${fmtNum(run.max_von_mises_mpa, 1)} MPa`} />
          <Stat label="Bends" value={`${fmtNum(run.max_deflection_mm, 2)} mm`} />
          <Stat label="Worst case" value={worst?.name ?? run.governing} />
        </div>
        <div className="mt-2 flex items-center gap-2 text-[12px] font-semibold text-muted">
          <span className="num shrink-0">0</span>
          <span className="h-2 min-w-0 flex-1 rounded-full" style={{ background: SCALE }} />
          <span className="num shrink-0 whitespace-nowrap">{fmtNum(run.scale_mpa, 0)} MPa printed strength</span>
        </div>
        <p className="mt-1.5 text-[12px] leading-snug text-muted">
          {run.material} at {fmtNum(run.fill * 100, 0)} % plastic ({run.walls} walls, {fmtNum(run.infill_pct, 0)} % infill)
          {run.governs === "layers" ? ", weakest across the layers" : ""}. {run.loads.join(" ")} {run.solver}, {run.nodes.toLocaleString("en-US")} nodes
          {run.printer ? `, printed on your ${run.printer}` : ""}.{run.self_check ? ` ${run.self_check}` : ""}
        </p>
        {run.notes?.map((note) => (
          <p key={note} className="mt-1 text-[12px] font-semibold leading-snug text-fail-ink">
            {note}
          </p>
        ))}
      </div>
    </div>
  );
}
