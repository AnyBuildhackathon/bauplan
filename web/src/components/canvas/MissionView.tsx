// Simulation tab, Missions pane: replays the simulate_mission runs (speed run, hard turn,
// position hold, chase) with the drone at its MuJoCo pose and attitude, the fly it chases or the
// wind it holds against, and the mission's own curve against its requirement's limit.
import { Line } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Pause, Play } from "lucide-react";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { useSession, type MissionRun } from "../../events/store";
import type { MissionId } from "../../events/types";
import { fmtNum } from "../../lib/format";
import { useAssembly, useHighlight } from "../../lib/hooks";
import { useUi } from "../../lib/ui";
import { TrendChart } from "../ui/TrendChart";
import { AnchorScope } from "./anchors";
import { GridStage } from "./GridStage";
import { HeroDrone, useDroneUrl } from "./HeroDrone";
import { SimSpeed } from "./SimSpeed";
import { seek, setPlaying, simClock, useSimClockDriver, useSimTime, useSlowWindow } from "./simClock";

const RESULT_COLOR = { pass: "#2ed3ae", fail: "#ff5a5f" } as const;
const ORDER: MissionId[] = ["speed_run", "turn", "hold", "chase"];

/** How each mission is framed: stage size, drawn drone scale, and whether the camera follows. */
const FRAMING: Record<MissionId, { stage: number; scale: number; follow: boolean }> = {
  speed_run: { stage: 3, scale: 4, follow: true },
  turn: { stage: 1.5, scale: 4, follow: true },
  hold: { stage: 0.5, scale: 2, follow: false },
  chase: { stage: 1, scale: 6, follow: false },
};

/** three.js is y-up; MuJoCo is z-up with the nose on +y, the model's nose on -z. */
const toScene = (x: number, y: number, z: number) => new THREE.Vector3(x, z, -y);

function poseAt(poses: number[][], t: number): { p: THREE.Vector3; q: THREE.Quaternion } {
  const q = new THREE.Quaternion();
  if (!poses.length) return { p: new THREE.Vector3(), q };
  let i = poses.findIndex((row) => row[0] >= t);
  if (i < 0) i = poses.length - 1;
  const b = poses[i];
  const a = poses[Math.max(0, i - 1)];
  const span = b[0] - a[0] || 1;
  const k = i === 0 ? 0 : THREE.MathUtils.clamp((t - a[0]) / span, 0, 1);
  const p = toScene(a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, a[3] + (b[3] - a[3]) * k);
  // A rotation's vector part maps like a vector: (x, y, z) -> (x, z, -y).
  const qa = new THREE.Quaternion(a[5], a[7], -a[6], a[4]);
  const qb = new THREE.Quaternion(b[5], b[7], -b[6], b[4]);
  q.slerpQuaternions(qa, qb, k);
  return { p, q };
}

function pointAt(rows: number[][], t: number): THREE.Vector3 {
  if (!rows.length) return new THREE.Vector3();
  let i = rows.findIndex((row) => row[0] >= t);
  if (i < 0) i = rows.length - 1;
  const b = rows[i];
  const a = rows[Math.max(0, i - 1)];
  const k = i === 0 ? 0 : THREE.MathUtils.clamp((t - a[0]) / (b[0] - a[0] || 1), 0, 1);
  return toScene(a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, a[3] + (b[3] - a[3]) * k);
}

/** The newest run of each mission, in the fixed mission order. */
export function useLatestMissions(): MissionRun[] {
  const runs = useSession((s) => s.missionRuns);
  return useMemo(() => {
    const latest = new Map<MissionId, MissionRun>();
    for (const run of Object.values(runs)) {
      const known = latest.get(run.mission);
      if (!known || run.run > known.run) latest.set(run.mission, run);
    }
    return ORDER.flatMap((m) => (latest.has(m) ? [latest.get(m)!] : []));
  }, [runs]);
}

function FlyingDrone({ run }: { run: MissionRun }) {
  const build = useAssembly("latest");
  const url = useDroneUrl();
  const highlight = useHighlight();
  const ref = useRef<THREE.Group>(null);
  useFrame(() => {
    const g = ref.current;
    if (!g) return;
    const { p, q } = poseAt(run.poses, simClock.t);
    g.position.copy(p);
    g.quaternion.copy(q);
  });
  const scale = FRAMING[run.mission].scale;
  return (
    <group ref={ref}>
      <group scale={scale}>
        <Suspense fallback={null}>
          <HeroDrone url={url} battery={build.battery} sizes={build.sizes} highlight={highlight} spin={60} />
        </Suspense>
      </group>
    </group>
  );
}

function Fly({ target }: { target: number[][] }) {
  const ref = useRef<THREE.Group>(null);
  useFrame(() => {
    if (ref.current) ref.current.position.copy(pointAt(target, simClock.t));
  });
  return (
    <group ref={ref}>
      <mesh>
        <sphereGeometry args={[0.1, 16, 12]} />
        <meshStandardMaterial color="#1c1c1f" roughness={0.4} />
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.16, 0.01, 8, 40]} />
        <meshBasicMaterial color="#ff8a3d" transparent opacity={0.7} />
      </mesh>
    </group>
  );
}

function Wind({ run }: { run: MissionRun }) {
  const ref = useRef<THREE.ArrowHelper>(null);
  const arrow = useMemo(() => new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(), 0.5, 0x3b82f6, 0.12, 0.08), []);
  useFrame(() => {
    const rows = run.wind ?? [];
    if (!rows.length) return;
    const t = simClock.t;
    const row = rows.find((r) => r[0] >= t) ?? rows[rows.length - 1];
    const air = toScene(row[1], row[2], row[3]);
    const speed = air.length();
    const { p } = poseAt(run.poses, t);
    arrow.visible = speed > 0.05;
    if (!arrow.visible) return;
    const dir = air.clone().normalize();
    const length = 0.12 * speed + 0.1;
    // The air arrives from upwind: the arrow ends at the drone.
    arrow.position.copy(p.clone().addScaledVector(dir, -length - 0.25));
    arrow.setDirection(dir);
    arrow.setLength(length, 0.12, 0.08);
  });
  return <primitive ref={ref} object={arrow} />;
}

function MissionCamera({ run, bounds }: { run: MissionRun; bounds: THREE.Box3 }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  const follow = FRAMING[run.mission].follow;
  useEffect(() => {
    if (follow) {
      camera.near = 0.05;
      camera.far = 400;
      camera.updateProjectionMatrix();
      return;
    }
    const center = bounds.getCenter(new THREE.Vector3());
    const radius = bounds.getBoundingSphere(new THREE.Sphere()).radius * 1.1;
    const vfov = THREE.MathUtils.degToRad(camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * (size.width / Math.max(1, size.height)));
    const dist = radius / Math.sin(Math.min(vfov, hfov) / 2);
    camera.position.copy(center).addScaledVector(new THREE.Vector3(0.55, 0.45, 0.9).normalize(), dist);
    camera.near = Math.max(0.02, dist - radius * 3);
    camera.far = dist + radius * 30;
    camera.lookAt(center);
    camera.updateProjectionMatrix();
  }, [follow, bounds, camera, size.width, size.height]);
  const look = useRef(new THREE.Vector3());
  useFrame(() => {
    if (!follow) return;
    const { p } = poseAt(run.poses, simClock.t);
    // Beside and a little behind the flight, so speed and lean both read.
    const want = p.clone().add(new THREE.Vector3(-1.1, 0.55, 3.0));
    camera.position.lerp(want, 0.2);
    look.current.lerp(p, 0.3);
    camera.lookAt(look.current);
  });
  return null;
}

function MissionScene({ run }: { run: MissionRun }) {
  const color = RESULT_COLOR[run.result];
  const path = useMemo(() => run.poses.map((p) => toScene(p[1], p[2], p[3])), [run]);
  const ground = useMemo(() => path.map((p) => new THREE.Vector3(p.x, 0.003, p.z)), [path]);
  const flyPath = useMemo(() => (run.target ?? []).map((p) => toScene(p[1], p[2], p[3])), [run]);
  const bounds = useMemo(() => {
    const box = new THREE.Box3();
    for (const p of [...path, ...flyPath]) box.expandByPoint(p);
    const c = box.getCenter(new THREE.Vector3());
    // Hold drifts by centimetres: frame at least a metre so the drone and its drift both show.
    box.expandByPoint(c.clone().add(new THREE.Vector3(0.6, 0.6, 0.6)));
    box.expandByPoint(c.clone().add(new THREE.Vector3(-0.6, -0.6, -0.6)));
    box.expandByPoint(new THREE.Vector3(c.x, 0, c.z));
    return box;
  }, [path, flyPath]);
  const framing = FRAMING[run.mission];
  const center = bounds.getCenter(new THREE.Vector3());
  return (
    <Canvas dpr={[1, 2]} camera={{ fov: 34, position: [3, 2, 5] }} gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }}>
      <MissionCamera run={run} bounds={bounds} />
      <AnchorScope primary>
        <ambientLight intensity={0.35} />
        <GridStage size={framing.stage} center={[center.x, center.z]} shadowArea={Math.max(4, bounds.getSize(new THREE.Vector3()).length())} shadowReach={2.5} shadowOpacity={0.4} />
        {path.length > 1 && <Line points={path} color={color} lineWidth={3} transparent opacity={0.9} />}
        {ground.length > 1 && <Line points={ground} color={color} lineWidth={1.5} transparent opacity={0.25} dashed dashSize={0.1} gapSize={0.08} />}
        {flyPath.length > 1 && <Line points={flyPath} color="#45454b" lineWidth={1.5} transparent opacity={0.55} dashed dashSize={0.06} gapSize={0.05} />}
        {run.target && <Fly target={run.target} />}
        {run.wind && <Wind run={run} />}
        <FlyingDrone run={run} />
      </AnchorScope>
    </Canvas>
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

/** The mission's own curve, as the chart shows it, and the line it is judged against. */
function curve(run: MissionRun): { label: string; points: [number, number][]; unit: string; marker: number; markerLabel: string } {
  if (run.mission === "speed_run") {
    return { label: "Speed over time", points: run.series.map(([t, v]) => [t, v * 3.6]), unit: "km/h", marker: run.limit, markerLabel: `Needs ${fmtNum(run.limit)} km/h` };
  }
  if (run.mission === "turn") {
    return { label: "Course over time", points: run.series, unit: "°", marker: 90, markerLabel: "90° turn" };
  }
  if (run.mission === "hold") {
    return { label: "Drift from the hold point", points: run.series, unit: "cm", marker: run.limit, markerLabel: `Within ${fmtNum(run.limit)} cm` };
  }
  return { label: "Distance to the fly", points: run.series, unit: "cm", marker: Number(run.metrics.capture_radius_cm ?? 12), markerLabel: "Caught" };
}

function valueText(run: MissionRun): string {
  if (run.value === null) return run.mission === "chase" ? "no catch" : "–";
  const digits = run.unit === "s" ? 1 : 0;
  return `${fmtNum(run.value, digits)} ${run.unit}`;
}

export function MissionView() {
  const missions = useLatestMissions();
  const allRuns = useSession((s) => s.missionRuns);
  const selected = useUi((s) => s.selectedMission);
  const selectMission = useUi((s) => s.selectMission);
  const newest = missions.reduce<MissionRun | null>((best, run) => (!best || run.run > best.run ? run : best), null);
  const run = (selected !== null && allRuns[selected]) || newest;
  const duration = Math.max(run?.poses.at(-1)?.[0] ?? 1, 0.5);
  useSimClockDriver(duration);
  useSlowWindow(null);
  const { t, playing } = useSimTime(20);
  const [chartRef, chartW] = useWidth<HTMLDivElement>();
  useEffect(() => {
    simClock.t = 0;
  }, [run?.run]);

  if (!run) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
        <p className="text-[18px] font-semibold text-ink-2">No mission flown yet</p>
        <p className="max-w-sm text-[15px] text-muted">Ask for a job, like a fast fly hunter, and Mechanic flies it in MuJoCo with the parts it picked.</p>
      </div>
    );
  }

  const c = curve(run);
  const shown = c.points.filter(([time]) => time <= t + 1e-6);
  const yMax = Math.max(c.marker * 1.15, ...c.points.map(([, v]) => v)) * 1.05 || 1;
  const pass = run.result === "pass";

  return (
    <div className="flex h-full flex-col">
      <div className="relative min-h-0 flex-1">
        <MissionScene key={run.run} run={run} />
        <div className="absolute top-3 left-3 flex max-w-[calc(100%-140px)] flex-wrap gap-2">
          {missions.map((m) => {
            const active = m.run === run.run;
            return (
              <button
                key={m.mission}
                type="button"
                onClick={() => selectMission(m.run)}
                data-target={`mission:${m.mission}`}
                className={`inline-flex h-8 items-center gap-2 rounded-full px-3.5 text-[13px] font-bold shadow-[var(--shadow-pill)] transition ${
                  active ? "bg-ink text-white" : "bg-white/95 text-ink-2 hover:bg-white"
                }`}
              >
                <span className="h-2 w-2 rounded-full" style={{ background: RESULT_COLOR[m.result] }} />
                {m.label}
                <span className={`num font-semibold ${active ? "text-white/80" : "text-muted"}`}>{valueText(m)}</span>
              </button>
            );
          })}
        </div>
        <div className="absolute right-3 bottom-3 left-3 rounded-2xl bg-white/92 px-3.5 py-2.5 shadow-[var(--shadow-pill)] backdrop-blur sm:right-auto sm:max-w-[min(560px,100%)]">
          <p className={`text-[14px] font-bold ${pass ? "text-ok-ink" : "text-fail-ink"}`}>
            {run.label} · {pass ? "passed" : "failed"} · {fmtNum(run.mass_g, 1)} g
          </p>
          <p className="mt-0.5 text-[13px] leading-snug text-ink-2">{run.summary}</p>
          <p className="mt-0.5 text-[12px] leading-snug text-muted">{run.why}</p>
        </div>
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
          <div className="flex items-center justify-between text-[13px] font-semibold text-muted">
            <span className="min-w-0 truncate">{c.label}</span>
            <SimSpeed />
            <span className="num shrink-0 whitespace-nowrap text-ink-2">
              {fmtNum(t, 1)} / {fmtNum(duration, 1)} s
            </span>
          </div>
          <div
            ref={chartRef}
            className="cursor-pointer"
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              seek(((e.clientX - rect.left) / Math.max(1, rect.width - 54)) * duration);
            }}
          >
            <TrendChart
              series={[{ points: shown, color: RESULT_COLOR[run.result], area: true }]}
              width={chartW}
              height={70}
              xDomain={[0, duration]}
              yDomain={[0, yMax]}
              yTicks={c.marker > yMax * 0.2 ? [0, c.marker] : [c.marker, Math.round(yMax * 0.8)]}
              formatY={(v) => `${fmtNum(v)} ${c.unit}`}
              marker={{ y: c.marker, label: c.markerLabel }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
