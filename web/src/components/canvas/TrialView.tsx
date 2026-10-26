// Simulation tab, Robo Use pane: an independent benchmark drove the built gripper (robouse_trial, docs/events.md
// trial). The verdict on top; the trial's own video with its step track, every robo request a mark that jumps
// there; the hand's path on AnyBuild's stage beside it; the requests with Robo Use's answers and the contact
// force below, all on the video's clock. A recorded trial says so, and one of another design reads as an example.
import { Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { CircleX, Gavel, LoaderCircle, Pause, Play } from "lucide-react";
import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import * as THREE from "three";
import { useSession } from "../../events/store";
import { useSource } from "../../events/source";
import { designLine, fmtReward, HARNESS_LABEL, shownTrial, useTrialPane, verdictOf, type TrialRun, type TrialStep, type Vec3 } from "../../events/trial";
import { assetUrl } from "../../lib/api";
import { fmtNum } from "../../lib/format";
import { recordedNote, TONE_TEXT, ValidityChip } from "../chat/TrialCard";
import { Segmented } from "../ui/primitives";
import { TrendChart } from "../ui/TrendChart";
import { GridStage } from "./GridStage";

const COLOR = { pass: "#2ed3ae", fail: "#ff5a5f", neutral: "#45454b" } as const;
const SPEEDS = [
  { value: "0.25", label: "0.25×" },
  { value: "0.5", label: "0.5×" },
  { value: "1", label: "1×" },
];
const STAGES = [
  { id: "export", label: "Export" },
  { id: "task", label: "Task" },
  { id: "check", label: "Check" },
  { id: "agent", label: "Agent" },
] as const;

/** Robo Use is z-up with y away from its front camera; three.js is y-up, so (x, y, z) -> (x, z, -y). */
const toScene = (p: Vec3 | number[]) => new THREE.Vector3(p[0], p[2], -p[1]);

interface Clock {
  t: number;
  playing: boolean;
  speed: number;
}

/** The trial's clock: the video's own time once it plays, else a timer over the hand's path. */
function usePlayback(video: RefObject<HTMLVideoElement | null>, duration: number, key: string) {
  const clock = useRef<Clock>({ t: 0, playing: true, speed: 1 });
  const [view, setView] = useState({ t: 0, playing: true });
  useEffect(() => {
    clock.current.t = 0;
    clock.current.playing = true;
    let raf = 0;
    let last = 0;
    let shown = 0;
    const tick = (now: number) => {
      const c = clock.current;
      const v = video.current;
      if (v && v.readyState >= 2) {
        c.t = v.currentTime;
        c.playing = !v.paused;
      } else if (c.playing && duration > 0) {
        c.t = (c.t + (last ? Math.min(0.1, (now - last) / 1000) : 0) * c.speed) % duration;
      }
      last = now;
      // The DOM follows at 20 Hz; the 3D scene reads the clock every frame.
      if (now - shown > 50) {
        shown = now;
        setView((prev) => (prev.t === c.t && prev.playing === c.playing ? prev : { t: c.t, playing: c.playing }));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [video, duration, key]);
  const seek = (t: number) => {
    const at = Math.max(0, Math.min(duration, t));
    clock.current.t = at;
    if (video.current && video.current.readyState >= 1) video.current.currentTime = at;
    setView((prev) => ({ ...prev, t: at }));
  };
  const toggle = () => {
    const v = video.current;
    if (v && v.readyState >= 2) {
      if (v.paused) void v.play();
      else v.pause();
    } else {
      clock.current.playing = !clock.current.playing;
    }
  };
  const setSpeed = (speed: number) => {
    clock.current.speed = speed;
    if (video.current) video.current.playbackRate = speed;
  };
  return { clock, t: view.t, playing: view.playing, seek, toggle, setSpeed };
}

/** The request playing at time t: the last one that started by then. */
function stepAt(steps: TrialStep[], t: number): number {
  let current = 0;
  for (let i = 0; i < steps.length; i++) if (steps[i].t_start <= t + 1e-6) current = i;
  return current;
}

function lerp(a: number, b: number, k: number) {
  return a + (b - a) * k;
}

/** Linear lookup in [t, ...values] rows. */
function sample(rows: number[][], t: number): number[] {
  if (!rows.length) return [];
  if (t <= rows[0][0]) return rows[0].slice(1);
  for (let i = 1; i < rows.length; i++) {
    if (rows[i][0] >= t) {
      const a = rows[i - 1];
      const b = rows[i];
      const k = (t - a[0]) / Math.max(1e-9, b[0] - a[0]);
      return a.slice(1).map((v, j) => lerp(v, b[j + 1], k));
    }
  }
  return rows[rows.length - 1].slice(1);
}

/** Where the object is at time t: carried with the hand while held through a request, else between its sampled places. */
function objectAt(trial: TrialRun, t: number, hand: number[]): number[] | null {
  const name = trial.scene?.object?.name;
  const steps = trial.steps ?? [];
  if (!name || !steps.length) return null;
  const k = steps.findIndex((s) => s.t_end >= t);
  const i = k < 0 ? steps.length - 1 : k;
  const end = steps[i];
  const start = steps[i - 1] ?? steps[0];
  const a = start.objects[name];
  const b = end.objects[name];
  if (!a || !b) return a ?? b ?? null;
  const f = end.t_end > end.t_start ? Math.max(0, Math.min(1, (t - end.t_start) / (end.t_end - end.t_start))) : 1;
  const held = (s: TrialStep) => !!s.holding?.includes(name);
  if (held(start) && held(end) && start.hand_pos && end.hand_pos && hand.length === 3) {
    return [0, 1, 2].map((j) => hand[j] + lerp(a[j] - start.hand_pos![j], b[j] - end.hand_pos![j], f));
  }
  return [0, 1, 2].map((j) => lerp(a[j], b[j], i === 0 ? 1 : f));
}

/** How far the fingers are open at time t, 0 to 1, between the requests' reported openings. */
function openingAt(steps: TrialStep[], t: number): number {
  const k = steps.findIndex((s) => s.t_end >= t);
  if (k < 0) return steps.at(-1)?.gripper_open ?? 1;
  const end = steps[k];
  const before = k > 0 ? steps[k - 1].gripper_open ?? 1 : 1;
  const f = end.t_end > end.t_start ? Math.max(0, Math.min(1, (t - end.t_start) / (end.t_end - end.t_start))) : 1;
  return lerp(before, end.gripper_open ?? before, f);
}

/** A simple two-finger hand at the tool point: palm and servo above it, fingers down, closing along Robo Use's y. */
function Hand({ trial, clock }: { trial: TrialRun; clock: RefObject<Clock> }) {
  const group = useRef<THREE.Group>(null);
  const left = useRef<THREE.Group>(null);
  const right = useRef<THREE.Group>(null);
  const opening = (trial.design?.opening_mm ?? 76) / 1000;
  useFrame(() => {
    const t = clock.current?.t ?? 0;
    const p = sample(trial.ee_path ?? [], t);
    if (group.current && p.length === 3) group.current.position.copy(toScene(p));
    const gap = Math.max(0.004, opening * openingAt(trial.steps ?? [], t));
    // Robo Use's y is the scene's -z.
    if (left.current) left.current.position.z = gap / 2 + 0.003;
    if (right.current) right.current.position.z = -gap / 2 - 0.003;
  });
  const fingerColor = "#eceef2";
  return (
    <group ref={group}>
      <mesh position={[0, 0.034, 0]}>
        <boxGeometry args={[0.034, 0.012, opening + 0.03]} />
        <meshStandardMaterial color="#dfe2e8" roughness={0.45} metalness={0.15} />
      </mesh>
      <mesh position={[0.03, 0.052, 0]}>
        <boxGeometry args={[0.022, 0.042, 0.04]} />
        <meshStandardMaterial color="#3b5bdb" roughness={0.4} />
      </mesh>
      {[left, right].map((ref, i) => (
        <group key={i} ref={ref}>
          <mesh position={[0, 0.006, 0]}>
            <boxGeometry args={[0.012, 0.056, 0.006]} />
            <meshStandardMaterial color={fingerColor} roughness={0.5} />
          </mesh>
          <mesh position={[0, -0.012, i === 0 ? -0.004 : 0.004]}>
            <boxGeometry args={[0.012, 0.02, 0.003]} />
            <meshStandardMaterial color="#2b2d33" roughness={0.9} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

function Cube({ trial, clock }: { trial: TrialRun; clock: RefObject<Clock> }) {
  const ref = useRef<THREE.Mesh>(null);
  const size = trial.scene?.object?.size_m ?? [0.04, 0.04, 0.04];
  const named = trial.scene?.object?.color;
  useFrame(() => {
    const t = clock.current?.t ?? 0;
    const p = objectAt(trial, t, sample(trial.ee_path ?? [], t));
    if (ref.current && p) ref.current.position.copy(toScene(p));
  });
  return (
    <mesh ref={ref}>
      <boxGeometry args={[size[0], size[2], size[1]]} />
      <meshStandardMaterial color={!named || named === "red" ? "#e5484d" : named} roughness={0.55} />
    </mesh>
  );
}

function Target({ trial }: { trial: TrialRun }) {
  const target = trial.scene?.target;
  if (!target) return null;
  const at = toScene(target.pos);
  if (target.kind === "bowl") {
    const r = (target.inner_diameter_m ?? 0.14) / 2;
    const h = target.rim_z ?? 0.035;
    return (
      <group position={[at.x, 0, at.z]}>
        <mesh position={[0, h / 2, 0]}>
          <cylinderGeometry args={[r + 0.004, r + 0.004, h, 48, 1, true]} />
          <meshStandardMaterial color="#ffffff" roughness={0.35} side={THREE.DoubleSide} />
        </mesh>
        <mesh position={[0, (target.floor_z ?? 0.006) / 2, 0]}>
          <cylinderGeometry args={[r + 0.004, r + 0.004, target.floor_z ?? 0.006, 48]} />
          <meshStandardMaterial color="#f4f4f2" roughness={0.4} />
        </mesh>
      </group>
    );
  }
  const [sx, sy] = [target.size_m?.[0] ?? 0.05, target.size_m?.[1] ?? 0.05];
  return (
    <mesh position={[at.x, 0.002, at.z]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[sx * 2, sy * 2]} />
      <meshStandardMaterial color="#2fa86f" roughness={0.6} />
    </mesh>
  );
}

function FitCamera({ bounds }: { bounds: THREE.Box3 }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3; update: () => void } | null;
  useLayoutEffect(() => {
    const center = bounds.getCenter(new THREE.Vector3());
    // From the front and a little to the right, above the table: the video's view, turned so the path's depth reads.
    const back = new THREE.Vector3(0.42, 0.62, 1).normalize();
    const right = new THREE.Vector3(0, 1, 0).cross(back).normalize();
    const up = back.clone().cross(right);
    const tanV = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * 0.9;
    const tanH = tanV * (size.width / Math.max(1, size.height));
    // The nearest distance at which every corner of the bounds is inside the view, with a margin.
    let dist = 0.1;
    for (const x of [bounds.min.x, bounds.max.x])
      for (const y of [bounds.min.y, bounds.max.y])
        for (const z of [bounds.min.z, bounds.max.z]) {
          const d = new THREE.Vector3(x, y, z).sub(center);
          const depth = d.dot(back);
          dist = Math.max(dist, depth + Math.abs(d.dot(right)) / tanH, depth + Math.abs(d.dot(up)) / tanV);
        }
    camera.position.copy(center).addScaledVector(back, dist);
    camera.near = dist / 100;
    camera.far = dist * 20;
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    if (controls) {
      controls.target.copy(center);
      controls.update();
    }
  }, [bounds, camera, size.width, size.height, controls]);
  return null;
}

/** The hand's path on AnyBuild's stage, with the cube carried along it and the bowl it goes to. */
const PathScene = memo(function PathScene({ trial, clock }: { trial: TrialRun; clock: RefObject<Clock> }) {
  const color = trial.status === "recorded" && !trial.recorded?.matches_build ? COLOR.neutral : trial.verdict === "pass" ? COLOR.pass : COLOR.fail;
  const path = useMemo(() => (trial.ee_path ?? []).map((row) => toScene(row.slice(1))), [trial.ee_path]);
  const ground = useMemo(() => path.map((p) => new THREE.Vector3(p.x, 0.0015, p.z)), [path]);
  const objectPath = useMemo(() => (trial.scene?.object?.path ?? []).map((row) => toScene(row.slice(1))), [trial.scene]);
  const bounds = useMemo(() => {
    const box = new THREE.Box3();
    for (const p of [...path, ...objectPath]) box.expandByPoint(p);
    const target = trial.scene?.target;
    if (target) {
      const r = (target.inner_diameter_m ?? 0.1) / 2 + 0.01;
      const at = toScene(target.pos);
      box.expandByPoint(at.clone().add(new THREE.Vector3(r, 0, r)));
      box.expandByPoint(at.clone().add(new THREE.Vector3(-r, 0, -r)));
    }
    if (box.isEmpty()) box.set(new THREE.Vector3(-0.15, 0, -0.15), new THREE.Vector3(0.15, 0.25, 0.15));
    box.expandByPoint(new THREE.Vector3(box.min.x, 0, box.min.z));
    return box;
  }, [path, objectPath, trial.scene]);
  const center = bounds.getCenter(new THREE.Vector3());
  return (
    <Canvas dpr={[1, 2]} camera={{ fov: 32 }} gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }} aria-label="The hand's path in Robo Use">
      <FitCamera bounds={bounds} />
      <ambientLight intensity={0.3} />
      <GridStage size={0.25} center={[center.x, center.z]} shadowArea={0.9} shadowReach={0.3} shadowOpacity={0.35} />
      {path.length > 1 && <Line points={path} color={color} lineWidth={3} transparent opacity={0.9} />}
      {ground.length > 1 && <Line points={ground} color={color} lineWidth={1.5} transparent opacity={0.3} dashed dashSize={0.012} gapSize={0.008} />}
      {objectPath.length > 1 && <Line points={objectPath} color="#e5484d" lineWidth={1.5} transparent opacity={0.45} dashed dashSize={0.008} gapSize={0.006} />}
      <Target trial={trial} />
      <Cube trial={trial} clock={clock} />
      <Hand trial={trial} clock={clock} />
      <OrbitControls makeDefault enablePan={false} maxPolarAngle={Math.PI / 2.08} />
    </Canvas>
  );
});

/** A callback ref and the element's size: it follows the element even when it mounts later, as the grid does after a running trial. */
function useSize<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null);
  const [size, setSize] = useState({ w: 320, h: 240 });
  useEffect(() => {
    if (!node) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(node);
    return () => ro.disconnect();
  }, [node]);
  return [setNode, size] as const;
}

const GAP = 12;
// The step track under the video: its card's height and the gap above it.
const TRACK = 74 + 8;

/** Columns and rows for the wide layout: the video exactly as wide as its aspect at the height left, within limits. */
function useTrialGrid(aspect: number) {
  const [ref, size] = useSize<HTMLDivElement>();
  const wide = size.w >= 760;
  const lower = Math.round(Math.min(210, Math.max(150, size.h * 0.28)));
  const video = (size.h - lower - GAP - TRACK) * aspect;
  const left = Math.round(Math.min(size.w * 0.64, Math.max(size.w * 0.42, video)));
  const style = wide ? { gridTemplateColumns: `${left}px minmax(0, 1fr)`, gridTemplateRows: `minmax(0, 1fr) ${lower}px` } : undefined;
  return [ref, wide, style] as const;
}

/** Every robo request as a mark on the video's timeline; a click jumps there. */
function StepTrack({ trial, duration, t, current, playing, onSeek, onToggle, onSpeed }: {
  trial: TrialRun;
  duration: number;
  t: number;
  current: number;
  playing: boolean;
  onSeek: (t: number) => void;
  onToggle: () => void;
  onSpeed: (speed: number) => void;
}) {
  const steps = trial.steps ?? [];
  const [speed, setSpeed] = useState("1");
  const span = Math.max(duration, 0.001);
  const step = steps[current];
  return (
    <div className="shrink-0 rounded-2xl bg-white px-3 pt-2 pb-2.5 shadow-[var(--shadow-pill)]" data-target="trial:track">
      <div className="flex items-center gap-2.5">
        <button
          type="button"
          onClick={onToggle}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink text-white"
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? <Pause className="h-3.5 w-3.5" fill="currentColor" /> : <Play className="h-3.5 w-3.5 translate-x-[1px]" fill="currentColor" />}
        </button>
        <span className="min-w-0 flex-1 truncate font-label text-[12px] font-semibold text-ink-2" title={step?.action}>
          {step ? `${step.index}/${steps.length} · ${step.action.replace(/^robo /, "")}` : "No robo requests"}
        </span>
        <span className="num shrink-0 text-[12px] font-semibold text-ink-2">
          {fmtNum(t, 1)} / {fmtNum(duration, 1)} s
        </span>
        <Segmented
          size="sm"
          className="shrink-0 [&>button]:h-6 [&>button]:px-2 [&>button]:text-[12px]"
          options={SPEEDS}
          value={speed}
          onChange={(v) => {
            setSpeed(v);
            onSpeed(Number(v));
          }}
        />
      </div>
      <div
        className="relative mx-1.5 mt-2 h-4 cursor-pointer"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          onSeek(((e.clientX - rect.left) / Math.max(1, rect.width)) * span);
        }}
      >
        <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-track" />
        {steps.map((s, i) => (
          <div
            key={s.index}
            className={`absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full ${i === current ? "bg-agent" : s.op === "grip" ? "bg-ink/35" : "bg-ink/15"}`}
            style={{ left: `${(s.t_start / span) * 100}%`, width: `${(Math.max(0, s.t_end - s.t_start) / span) * 100}%` }}
          />
        ))}
        {steps.map((s, i) => (
          <button
            key={s.index}
            type="button"
            data-target="trial:mark"
            title={`${s.index} · ${s.action}`}
            aria-label={`Step ${s.index}: ${s.action}`}
            onClick={(e) => {
              e.stopPropagation();
              onSeek(s.t_start);
            }}
            className={`absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white shadow-[var(--shadow-pill)] transition ${
              i === current ? "bg-agent" : "bg-ink-2 hover:bg-ink"
            }`}
            style={{ left: `${(s.t_start / span) * 100}%` }}
          />
        ))}
        <div className="pointer-events-none absolute top-0 bottom-0 w-0.5 -translate-x-1/2 rounded-full bg-ink" style={{ left: `${(Math.min(t, span) / span) * 100}%` }} />
      </div>
    </div>
  );
}

function StepList({ trial, current, onSeek }: { trial: TrialRun; current: number; onSeek: (t: number) => void }) {
  const steps = trial.steps ?? [];
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const row = list.current?.children[current] as HTMLElement | undefined;
    const box = list.current;
    if (!row || !box) return;
    // Keep the playing request in view without moving the page.
    if (row.offsetTop < box.scrollTop || row.offsetTop + row.offsetHeight > box.scrollTop + box.clientHeight) {
      box.scrollTo({ top: row.offsetTop - box.clientHeight / 2 + row.offsetHeight / 2, behavior: "smooth" });
    }
  }, [current]);
  return (
    <div className="flex min-h-0 flex-col rounded-2xl bg-white p-3 shadow-[var(--shadow-pill)]" data-target="trial:steps">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-bold text-ink-2">Robo requests</span>
        <span className="num text-[12px] text-muted">
          {trial.steps_used ?? 0} of {trial.max_steps ?? 0} control steps
        </span>
      </div>
      <ol ref={list} className="scroll-soft relative min-h-0 flex-1 space-y-0.5 overflow-y-auto pr-1">
        {steps.map((s, i) => (
          <li key={s.index}>
            <button
              type="button"
              onClick={() => onSeek(s.t_start)}
              className={`flex w-full items-start gap-2 rounded-[10px] px-2 py-1.5 text-left transition ${i === current ? "bg-agent-soft" : "hover:bg-page-2"}`}
            >
              <span className={`num w-5 shrink-0 pt-px text-right text-[12px] font-bold ${i === current ? "text-agent-ink" : "text-faint"}`}>{s.index}</span>
              <span className="min-w-0 flex-1">
                {s.message && <span className="mb-0.5 block text-[12px] leading-snug text-ink-2 italic">{s.message}</span>}
                <span className={`block truncate font-label text-[12px] ${s.ok ? "text-ink" : "text-fail-ink"}`} title={s.action}>
                  {s.action}
                </span>
                <span className="block truncate text-[12px] leading-snug text-muted" title={s.result}>
                  {s.result}
                </span>
              </span>
              <span className="num shrink-0 pt-px text-[11px] text-faint">{fmtNum(s.t_start, 1)} s</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

function ForceChart({ trial, t }: { trial: TrialRun; t: number }) {
  const [ref, { w: width, h: height }] = useSize<HTMLDivElement>();
  const force = trial.force ?? [];
  const duration = Math.max(trial.video_info?.duration_s ?? force.at(-1)?.[0] ?? 1, 0.5);
  const peak = Math.max(trial.metrics?.max_contact_force_n ?? 0, ...force.map(([, f]) => f));
  const top = Math.max(1, Math.ceil(peak * 1.25));
  const shown = force.filter(([time]) => time <= t + 1e-6);
  const color = trial.verdict === "pass" ? COLOR.pass : trial.verdict === "fail" ? COLOR.fail : COLOR.neutral;
  return (
    <div className="flex min-h-0 min-w-0 flex-col rounded-2xl bg-white p-3 shadow-[var(--shadow-pill)]" data-target="trial:force">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-bold text-ink-2">Contact force</span>
        <span className="num text-[12px] text-muted">peak {fmtNum(peak, 1)} N</span>
      </div>
      <div ref={ref} className="min-h-0 flex-1 overflow-hidden">
        <TrendChart
          series={[{ points: shown, color, area: true }]}
          width={width}
          height={Math.max(60, Math.min(160, height))}
          xDomain={[0, duration]}
          yDomain={[0, top]}
          yTicks={[0, top]}
          formatY={(v) => `${fmtNum(v)} N`}
        />
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-[12px] text-muted">{label}</span>
      <span className="num text-[14px] font-semibold text-ink">{value}</span>
    </span>
  );
}

function Header({ trial, trials, onPick }: { trial: TrialRun; trials: TrialRun[]; onPick: (id: string) => void }) {
  const verdict = verdictOf(trial);
  const running = trial.status === "running";
  const note = recordedNote(trial);
  const metrics = trial.metrics ?? {};
  return (
    <div className="shrink-0 rounded-2xl bg-white px-4 py-3 shadow-[var(--shadow-pill)]" data-target="trial:verdict">
      {/* The pane switcher floats over the top right corner, so this line keeps clear of it. */}
      <div className="flex max-w-[calc(100%-340px)] min-h-7 flex-wrap items-center gap-2">
        <Gavel className="h-4 w-4 text-muted" />
        <span className="text-[12px] font-bold tracking-widest text-muted uppercase">Robo Use · independent test</span>
        {trials.length > 1 &&
          trials.map((other, i) => {
            const v = verdictOf(other);
            const active = other.id === trial.id;
            return (
              <button
                key={other.id}
                type="button"
                onClick={() => onPick(other.id)}
                className={`num inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-semibold transition ${
                  active ? "bg-ink text-white" : "bg-tile text-ink-2 hover:bg-track"
                }`}
              >
                #{i + 1} · v{other.version} · {v.label}
              </button>
            );
          })}
      </div>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {running ? (
          <span className="flex items-center gap-2 text-[24px] leading-tight font-bold text-agent-ink">
            <LoaderCircle className="h-5 w-5 animate-spin" /> Running
          </span>
        ) : (
          <span className={`num text-[26px] leading-tight font-bold ${TONE_TEXT[verdict.tone]}`}>
            {verdict.label}
            {trial.status !== "failed" && typeof trial.reward === "number" && <span className="text-[16px] font-semibold"> · reward {fmtReward(trial.reward)}</span>}
          </span>
        )}
        <span className="text-[15px] font-semibold text-ink">{trial.task_title}</span>
        <span className="min-w-0 text-[13px] text-muted">{[designLine(trial.design), `v${trial.version}`].filter(Boolean).join(" · ")}</span>
      </div>
      <p className="mt-1 text-[14px] leading-snug text-ink-2">{running ? trial.detail : trial.summary ?? trial.detail}</p>
      {running ? (
        <ol aria-label="Trial progress" className="mt-2 flex flex-wrap gap-1.5 text-[12px] font-semibold">
          {STAGES.filter((s) => s.id !== "agent" || trial.requested_harness === "claude-code").map((s, i, shown) => {
            const at = shown.findIndex((x) => x.id === trial.stage);
            const tone = i < at ? "bg-ok-soft text-ok-ink" : i === at ? "bg-agent-soft text-agent-ink" : "bg-tile text-muted";
            return (
              <li key={s.id} className={`rounded-full px-3 py-1 ${tone}`}>
                {s.label}
              </li>
            );
          })}
        </ol>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <ValidityChip validity={trial.validity} />
          {trial.status !== "failed" && (
            <>
              <Fact label="Steps" value={`${trial.steps_used ?? 0} / ${trial.max_steps ?? 0}`} />
              {typeof trial.wall_s === "number" && <Fact label="Trial" value={`${fmtNum(trial.wall_s, 1)} s`} />}
              {metrics.max_contact_force_n !== undefined && <Fact label="Peak contact" value={`${fmtNum(metrics.max_contact_force_n, 1)} N`} />}
              {metrics.safety_events !== undefined && <Fact label="Safety events" value={fmtNum(metrics.safety_events)} />}
            </>
          )}
          {trial.status !== "failed" && (
            <span className="ml-auto flex items-center gap-1.5">
              <span className="inline-flex h-7 items-center rounded-full bg-tile px-3 text-[12px] font-semibold text-ink-2">{HARNESS_LABEL[trial.harness] ?? trial.harness}</span>
              {trial.status === "recorded" && <span className="inline-flex h-7 items-center rounded-full bg-agent-soft px-3 text-[12px] font-semibold text-agent-ink">Recorded</span>}
            </span>
          )}
        </div>
      )}
      {(note || (trial.status === "done" && trial.detail)) && (
        <p className="mt-1.5 text-[12px] leading-snug text-muted" title={trial.detail}>
          {note ?? trial.detail}
          {note && trial.recorded?.reason ? ` ${trial.recorded.reason}` : ""}
        </p>
      )}
    </div>
  );
}

function Empty() {
  const product = useSession((s) => s.product);
  const built = useSession((s) => !!s.cad?.glb_url);
  const sendPrompt = useSource((s) => s.sendPrompt);
  const ready = product === "gripper" && built;
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
      <span className="flex h-16 w-16 items-center justify-center rounded-[20px] bg-tile text-faint">
        <Gavel className="h-8 w-8" strokeWidth={1.6} />
      </span>
      <p className="text-[18px] font-semibold text-ink-2">No Robo Use trial yet</p>
      <p className="max-w-md text-[15px] text-muted">
        Robo Use is an independent robotics benchmark: it puts the built gripper in its own physics, writes a task from your brief and judges where the
        cube ends up.
      </p>
      {ready && (
        <button
          type="button"
          onClick={() => void sendPrompt("Test it in Robo Use")}
          className="mt-1 inline-flex h-9 items-center gap-2 rounded-full bg-ink px-4 text-[14px] font-semibold text-white shadow-[var(--shadow-pill)]"
        >
          <Gavel className="h-4 w-4" /> Test it in Robo Use
        </button>
      )}
    </div>
  );
}

export function TrialView() {
  const order = useSession((s) => s.trialOrder);
  const all = useSession((s) => s.trials);
  const pick = useTrialPane();
  const trials = useMemo(() => order.map((id) => all[id]).filter(Boolean), [order, all]);
  const trial = shownTrial({ trials: all, trialOrder: order }, pick);
  const video = useRef<HTMLVideoElement>(null);
  const duration = trial?.video_info?.duration_s || trial?.ee_path?.at(-1)?.[0] || 1;
  const playback = usePlayback(video, duration, trial ? `${trial.id}:${trial.status}` : "");
  const [videoError, setVideoError] = useState(false);
  const url = assetUrl(trial?.video_url);
  useEffect(() => setVideoError(false), [url]);
  const size = trial?.video_info?.size;
  const [gridRef, wide, gridStyle] = useTrialGrid(size && size[1] ? size[0] / size[1] : 4 / 3);
  if (!trial) return <Empty />;

  const steps = trial.steps ?? [];
  const current = stepAt(steps, playback.t);
  const finished = trial.status === "done" || trial.status === "recorded";
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-y-auto p-4" data-target="trial">
      <Header trial={trial} trials={trials} onPick={(id) => pick.select(id, order.at(-1) ?? null)} />
      {finished ? (
        <div ref={gridRef} className={`grid flex-1 grid-cols-1 gap-3 ${wide ? "min-h-0" : ""}`} style={gridStyle}>
          <div className="flex min-w-0 flex-col gap-2">
            <div className={`relative overflow-hidden rounded-2xl bg-[#dcdcd9] ${wide ? "min-h-0 flex-1" : "aspect-[4/3]"}`} data-target="trial:video">
              {url && !videoError ? (
                <video
                  key={url}
                  ref={video}
                  src={url}
                  muted
                  playsInline
                  autoPlay
                  loop
                  preload="auto"
                  onClick={playback.toggle}
                  onError={() => setVideoError(true)}
                  onLoadedMetadata={(e) => (e.currentTarget.playbackRate = playback.clock.current.speed)}
                  aria-label="Robo Use trial recording"
                  className="absolute inset-0 h-full w-full cursor-pointer object-contain"
                />
              ) : (
                <div className="flex h-full items-center justify-center p-4 text-center text-[14px] text-muted">
                  {videoError ? "The recording could not be loaded. The steps, the path and the force still show the trial." : "This trial has no recording."}
                </div>
              )}
              <span className="num pointer-events-none absolute top-2.5 left-2.5 rounded-full bg-white/90 px-2.5 py-1 text-[12px] font-semibold text-ink-2 shadow-[var(--shadow-pill)]">
                Robo Use video · {steps[current] ? `step ${steps[current].index}` : "start"}
              </span>
            </div>
            <StepTrack
              trial={trial}
              duration={duration}
              t={playback.t}
              current={current}
              playing={playback.playing}
              onSeek={playback.seek}
              onToggle={playback.toggle}
              onSpeed={playback.setSpeed}
            />
          </div>
          <div className="relative min-h-[280px] min-w-0 overflow-hidden rounded-2xl bg-white shadow-[var(--shadow-pill)]" data-target="trial:path">
            <PathScene trial={trial} clock={playback.clock} />
            <span className="pointer-events-none absolute top-2.5 left-2.5 rounded-full bg-white/90 px-2.5 py-1 text-[12px] font-semibold text-ink-2 shadow-[var(--shadow-pill)]">
              Hand path · AnyBuild stage
            </span>
          </div>
          <StepList trial={trial} current={current} onSeek={playback.seek} />
          <ForceChart trial={trial} t={playback.t} />
        </div>
      ) : (
        <div className="flex min-h-48 flex-1 flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-line p-6 text-center">
          {trial.status === "running" ? (
            <>
              <LoaderCircle className="h-8 w-8 animate-spin text-agent" />
              <p className="max-w-md text-[15px] text-muted">The video, the robo requests and the hand's path appear here when the trial finishes.</p>
            </>
          ) : (
            <>
              <CircleX className="h-8 w-8 text-faint" strokeWidth={1.8} />
              <p className="text-[16px] font-semibold text-ink-2">No trial ran</p>
              <p className="max-w-md text-[14px] text-muted">
                {trial.verdict === "refused"
                  ? "Change the design, a wider jaw or longer fingers, or the object in the brief, then test again."
                  : "Robo Use stopped before a trial; the line above says why."}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
