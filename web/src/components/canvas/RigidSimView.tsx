// Simulation tab for any assembled product: replays `sim` events of kind "rigid".
// The real assembly model moves with the MuJoCo body pose; an arrow shows the push.
// Before/after shows the previous run next to the selected one, on the shared playhead.
import { OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useLoader, useThree } from "@react-three/fiber";
import { Pause, Play } from "lucide-react";
import { Suspense, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import type { Run } from "../../events/store";
import { assetUrl } from "../../lib/api";
import { fmtNum } from "../../lib/format";
import { useSelectedVersion, useVersions } from "../../lib/hooks";
import { TrendChart } from "../ui/TrendChart";
import { partColor } from "./CadView";
import { GridStage, stageObstacles } from "./GridStage";
import { seek, setPlaying, simClock, useSimClockDriver, useSimTime } from "./simClock";

const COLOR = { pass: "#2ed3ae", fail: "#ff5a5f" } as const;
const SAMPLE_S = 0.02;

/** Body pose at time t: position (metres, z up) and orientation, interpolated between samples. */
function poseAt(poses: number[][], t: number): { p: THREE.Vector3; q: THREE.Quaternion } {
  const p = new THREE.Vector3();
  const q = new THREE.Quaternion();
  if (!poses.length) return { p, q };
  const i = Math.min(poses.length - 1, Math.max(0, Math.floor(t / SAMPLE_S)));
  const a = poses[i];
  const b = poses[Math.min(poses.length - 1, i + 1)];
  const u = b[0] > a[0] ? Math.min(1, Math.max(0, (t - a[0]) / (b[0] - a[0]))) : 0;
  p.set(a[1], a[2], a[3]).lerp(new THREE.Vector3(b[1], b[2], b[3]), u);
  q.set(a[5], a[6], a[7], a[4]).slerp(new THREE.Quaternion(b[5], b[6], b[7], b[4]), u);
  return { p, q };
}

function Model({ url }: { url: string }) {
  const gltf = useLoader(GLTFLoader, url);
  const object = useMemo(() => {
    const root = gltf.scene.clone(true);
    root.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        const { color, opacity } = partColor((o.material as THREE.Material | undefined)?.name ?? "");
        o.material = new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.08, transparent: opacity < 1, opacity, depthWrite: opacity >= 1 });
        o.castShadow = true;
      }
    });
    return root;
  }, [gltf]);
  return <primitive object={object} />;
}

/** Arrow along +X with its tip at the origin, length 1. */
function Arrow({ color }: { color: string }) {
  return (
    <group>
      <mesh position={[-0.6, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.06, 0.06, 0.8, 16]} />
        <meshBasicMaterial color={color} />
      </mesh>
      <mesh position={[-0.12, 0, 0]} rotation={[0, 0, -Math.PI / 2]}>
        <coneGeometry args={[0.16, 0.24, 20]} />
        <meshBasicMaterial color={color} />
      </mesh>
    </group>
  );
}

function Stage({ run }: { run: Run }) {
  const url = assetUrl(run.glb_url ?? null);
  const body = useRef<THREE.Group>(null);
  const pushAt = useRef<THREE.Group>(null);
  const arrow = useRef<THREE.Group>(null);
  const floor = (run.floor_mm ?? 0) / 1000;
  const size = productSize(run);
  const point = run.push_point_mm ?? [0, 0, 0];
  const dir = run.push_dir ?? [0, 1];
  const pushWindow = run.push_window_s ?? null;
  const world = useMemo(() => new THREE.Vector3(), []);

  useFrame(() => {
    const g = body.current;
    if (!g) return;
    const { p, q } = poseAt(run.poses ?? [], simClock.t);
    g.position.copy(p);
    g.quaternion.copy(q);
    const a = arrow.current;
    if (a && pushAt.current) {
      const on = !!pushWindow && simClock.t >= pushWindow[0] && simClock.t < pushWindow[1];
      a.visible = on;
      if (on) {
        pushAt.current.getWorldPosition(world);
        a.position.copy(world);
      }
    }
  });

  return (
    <>
      {/* MuJoCo is z up, three.js is y up. */}
      <group rotation={[-Math.PI / 2, 0, 0]}>
        <group ref={body}>
          <group position={[0, 0, -floor]} scale={0.001}>{url && <Model url={url} />}</group>
          <group ref={pushAt} position={[point[0] / 1000, point[1] / 1000, point[2] / 1000]} />
        </group>
      </group>
      {run.mode !== "drop" && (
        <group ref={arrow} visible={false}>
          {/* Points along the push direction in plan view: z-up (dx, dy) is y-up (dx, -dy). */}
          <group rotation={[0, Math.atan2(dir[1], dir[0]), 0]} scale={size * 0.45}>
            <Arrow color="#ff8a3d" />
          </group>
        </group>
      )}
    </>
  );
}

function Frame({ run }: { run: Run }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3; update: () => void } | null;
  useLayoutEffect(() => {
    const b = run.bbox_mm ?? [-75, -75, 0, 75, 75, 150];
    const w = (b[3] - b[0]) / 1000;
    const d = (b[4] - b[1]) / 1000;
    const h = (b[5] - b[2]) / 1000;
    const reach = Math.max(w, d, h);
    const center = new THREE.Vector3(0, h * 0.45, 0);
    let radius = Math.hypot(reach * 1.2, h) * 0.55;
    // A run that falls over lies along its push direction at the end: frame the whole way down.
    const end = run.poses?.at(-1);
    const fell = (run.tilt?.at(-1)?.[1] ?? 0) > 45;
    if (end && fell) {
      const dir = run.push_dir ?? [0, 1];
      const far = new THREE.Vector3(end[1] + dir[0] * h, 0, -(end[2] + dir[1] * h));
      center.set(far.x / 2, h * 0.3, far.z / 2);
      radius = Math.max(radius, far.length() / 2 + reach * 0.45);
    }
    const vfov = THREE.MathUtils.degToRad(camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * (size.width / Math.max(1, size.height)));
    const dist = radius / Math.sin(Math.min(vfov, hfov) / 2);
    camera.position.copy(center).addScaledVector(new THREE.Vector3(0.85, 0.5, 0.9).normalize(), dist);
    camera.near = dist / 100;
    camera.far = dist * 20;
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(center);
      controls.update();
    }
  }, [run, camera, size.width, size.height, controls]);
  return null;
}

function verdict(run: Run): string {
  if (run.mode === "drop") return run.result === "pass" ? "lands" : "too hard";
  return run.result === "pass" ? "stays upright" : "tips over";
}

/** Largest extent of the assembly in metres. */
const productSize = (run: Run) => (run.bbox_mm ? Math.max(run.bbox_mm[3] - run.bbox_mm[0], run.bbox_mm[4] - run.bbox_mm[1], run.bbox_mm[5] - run.bbox_mm[2]) / 1000 : 0.15);

function RigidStage({ run, label }: { run: Run; label: string }) {
  const pass = run.result === "pass";
  const size = productSize(run);
  const obstacles = useMemo(() => stageObstacles(size), [size]);
  return (
    <div className="relative h-full min-h-0 min-w-0">
      <Canvas dpr={[1, 2]} camera={{ fov: 32 }} gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }}>
        <Frame run={run} />
        <ambientLight intensity={0.3} />
        <GridStage size={size} shadowArea={size * 6} shadowReach={size * 1.2} obstacles={obstacles} />
        <Suspense fallback={null}>
          <Stage run={run} />
        </Suspense>
        <OrbitControls makeDefault enablePan={false} />
      </Canvas>
      <div className="pointer-events-none absolute top-3 left-3 flex flex-wrap items-center gap-2">
        <span className={`inline-flex h-8 items-center gap-2 rounded-full bg-white/95 px-3.5 text-[13px] font-bold shadow-[var(--shadow-pill)] ${pass ? "text-ok-ink" : "text-fail-ink"}`}>
          <span className="h-2 w-2 rounded-full" style={{ background: COLOR[run.result] }} />
          {label} · Run {run.run} · {verdict(run)}
        </span>
        {run.mode !== "drop" && run.force_n != null && (
          <span className="num inline-flex h-8 items-center rounded-full bg-white/95 px-3.5 text-[13px] font-semibold text-ink-2 shadow-[var(--shadow-pill)]">
            {fmtNum(run.force_n, 2)} N push
          </span>
        )}
      </div>
    </div>
  );
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export function RigidSimView() {
  const all = useVersions().filter((v) => v.run.kind === "rigid");
  const after = useSelectedVersion();
  const before = after ? all.filter((v) => v.n < after.n).at(-1) ?? null : null;
  const duration = Math.max(...all.map((v) => v.run.trajectory.at(-1)?.[0] ?? 0), 1);
  useSimClockDriver(duration);
  const { t, playing } = useSimTime(30);
  const [chartRef, chartW] = useWidth<HTMLDivElement>();
  if (!after) return null;

  const tiltUpTo = (run: Run) => (run.tilt ?? []).filter((s) => s[0] <= t + 1e-6);
  const series = [
    ...(before ? [{ points: tiltUpTo(before.run), color: COLOR[before.run.result], dashed: true, glow: true }] : []),
    { points: tiltUpTo(after.run), color: COLOR[after.run.result], area: true },
  ];
  const limit = after.run.limit_deg ?? 5;
  const top = Math.min(95, Math.max(limit * 3, ...all.flatMap((v) => (v.run.tilt ?? []).map((s) => s[1]))) * 1.08);

  return (
    <div className="flex h-full flex-col">
      <div className="relative grid min-h-0 flex-1" style={{ gridTemplateColumns: before ? "minmax(0,1fr) minmax(0,1fr)" : "minmax(0,1fr)" }}>
        {before && (
          <div className="min-h-0 min-w-0 border-r border-line">
            <RigidStage run={before.run} label="Before" />
          </div>
        )}
        <RigidStage run={after.run} label={before ? "After" : "Run"} />
      </div>
      <div className="flex shrink-0 items-center gap-4 border-t border-line bg-card/80 px-4 py-2.5">
        <button
          type="button"
          onClick={() => setPlaying(!playing)}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-ink text-white shadow-[var(--shadow-pill)]"
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? <Pause className="h-4 w-4" fill="currentColor" /> : <Play className="h-4 w-4 translate-x-[1px]" fill="currentColor" />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between text-[13px] font-semibold text-muted">
            <span>{after.run.mode === "drop" ? "Tilt while it lands" : "Tilt over time"}</span>
            <span className="num text-ink-2">
              {fmtNum(t, 1)} / {fmtNum(duration, 1)} s
            </span>
          </div>
          <div
            ref={chartRef}
            className="cursor-pointer"
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              seek(((e.clientX - rect.left) / Math.max(1, rect.width - 40)) * duration);
            }}
          >
            <TrendChart
              series={series}
              width={chartW}
              height={70}
              xDomain={[0, duration]}
              yDomain={[0, top]}
              yTicks={top >= limit * 4 ? [0, Math.floor(top / 10) * 10] : [0, limit]}
              formatY={(v) => `${fmtNum(v)}°`}
              marker={{ y: limit, label: `Limit ${fmtNum(limit)}°` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
