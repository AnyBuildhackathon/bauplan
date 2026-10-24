// The 3D canvases: the drone model (Modell and Render tabs) and trajectory replays
// (Simulation and Video tabs). Lighting is built locally, nothing loads from the web.
import { ContactShadows, Environment, Grid, Lightformer, Line, OrbitControls } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Suspense, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useSession } from "../../events/store";
import type { Run } from "../../events/store";
import { useAssembly, useHighlight } from "../../lib/hooks";
import { AnchorScope } from "./anchors";
import { HeroDrone, useDroneUrl } from "./HeroDrone";
import { sampleAt, simClock } from "./simClock";

function useSpin() {
  const sim = useSession((s) => s.steps.simulation.status);
  const training = useSession((s) => s.steps.training.status);
  return sim === "running" || training === "running" ? 40 : 0;
}

const MODEL_TARGET = new THREE.Vector3(0, 0.012, 0);
const MODEL_DISTANCE = new THREE.Vector3(0.15, 0.13, 0.17).distanceTo(MODEL_TARGET);

/** Pulls the camera back on narrow canvases so the whole drone stays in frame. */
function FitModelWidth() {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  useLayoutEffect(() => {
    const aspect = size.width / Math.max(1, size.height);
    const dist = Math.min(0.45, MODEL_DISTANCE * Math.max(1, 1.05 / aspect));
    const dir = camera.position.clone().sub(MODEL_TARGET).normalize();
    camera.position.copy(MODEL_TARGET).addScaledVector(dir, dist);
  }, [camera, size.width, size.height]);
  return null;
}

export function ModelScene({ look }: { look: "modell" | "render" }) {
  const build = useAssembly();
  const url = useDroneUrl();
  const highlight = useHighlight();
  const spin = useSpin();
  const render = look === "render";
  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      camera={{ position: [0.15, 0.13, 0.17], fov: 30, near: 0.005, far: 10 }}
      gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }}
    >
      <AnchorScope primary>
        <FitModelWidth />
        <ambientLight intensity={render ? 0.25 : 0.7} />
        <hemisphereLight args={["#ffffff", "#d9d6e8", render ? 0.3 : 0.6]} />
        <directionalLight
          position={[0.4, 0.8, 0.3]}
          intensity={render ? 1.6 : 1.8}
          castShadow
          shadow-mapSize={[1024, 1024]}
          shadow-camera-near={0.1}
          shadow-camera-far={3}
          shadow-camera-left={-0.15}
          shadow-camera-right={0.15}
          shadow-camera-top={0.15}
          shadow-camera-bottom={-0.15}
        />
        {/* Metal and clear-coat parts need something to reflect, in both looks. */}
        <Environment resolution={256} environmentIntensity={render ? 1 : 0.75}>
          <Lightformer form="rect" intensity={3} position={[0, 2, 0]} rotation={[Math.PI / 2, 0, 0]} scale={[3, 3, 1]} />
          <Lightformer form="rect" intensity={1.6} color="#ffd9bf" position={[-2.5, 0.6, 0.5]} rotation={[0, Math.PI / 2, 0]} scale={[2, 1.4, 1]} />
          <Lightformer form="rect" intensity={1.2} color="#cfe0ff" position={[2.5, 0.4, -0.5]} rotation={[0, -Math.PI / 2, 0]} scale={[2, 1.4, 1]} />
          <Lightformer form="ring" intensity={2} position={[0, 0.8, 2.4]} scale={1.2} />
        </Environment>
        {/* The pack hangs under the frame; lift the drone so it stands on it. */}
        <group position={[0, build.battery[2] + 0.0028, 0]}>
          <Suspense fallback={null}>
            <HeroDrone url={url} battery={build.battery} highlight={highlight} spin={spin} />
          </Suspense>
        </group>
        <ContactShadows position={[0, 0, 0]} opacity={render ? 0.55 : 0.35} scale={0.35} blur={2.4} far={0.12} resolution={512} />
        <OrbitControls
          makeDefault
          autoRotate
          autoRotateSpeed={render ? 1.1 : 0.55}
          enablePan={false}
          minDistance={0.09}
          maxDistance={0.45}
          target={[0, 0.012, 0]}
          maxPolarAngle={Math.PI / 2.08}
        />
      </AnchorScope>
    </Canvas>
  );
}

/** three.js is y-up; trajectories are z-up. */
const toScene = (x: number, y: number, z: number) => new THREE.Vector3(x, z, -y);
const DRONE_SCALE = 5;
/** The MuJoCo hover target (simulate.py climbs to 0.5 m). */
const TARGET_Z = 0.5;

function FlyingDrone({ run, color }: { run: Run; color: string }) {
  // Each replay shows the battery that run actually flew with.
  const build = useAssembly(run.seq);
  const url = useDroneUrl();
  const highlight = useHighlight();
  const ref = useRef<THREE.Group>(null);
  useFrame(() => {
    const g = ref.current;
    if (!g) return;
    const { p, v } = sampleAt(run.trajectory, simClock.t);
    const pos = toScene(p[0], p[1], p[2]);
    g.position.set(pos.x, pos.y + 0.03, pos.z);
    // Lean into the motion like a real quad does.
    g.rotation.z = THREE.MathUtils.clamp(-v[0] * 0.35, -0.5, 0.5);
    g.rotation.x = THREE.MathUtils.clamp(-v[1] * 0.35, -0.5, 0.5);
  });
  const spin = run.result === "pass" ? 60 : 45;
  return (
    <group ref={ref}>
      <group scale={DRONE_SCALE}>
        <Suspense fallback={null}>
          <HeroDrone url={url} battery={build.battery} highlight={highlight} spin={spin} />
        </Suspense>
      </group>
      <pointLight color={color} intensity={0.4} distance={0.8} position={[0, -0.05, 0]} />
    </group>
  );
}

/** A small pill label drawn into a texture, so it needs no DOM inside the canvas. */
function LabelSprite({ text, position }: { text: string; position: [number, number, number] }) {
  const texture = useMemo(() => {
    const scale = 3;
    const c = document.createElement("canvas");
    const ctx = c.getContext("2d")!;
    const font = `600 ${13 * scale}px "Inter Tight", sans-serif`;
    ctx.font = font;
    const w = Math.ceil(ctx.measureText(text).width + 20 * scale);
    const h = 24 * scale;
    c.width = w;
    c.height = h;
    ctx.font = font;
    ctx.fillStyle = "rgba(255,255,255,0.94)";
    ctx.beginPath();
    ctx.roundRect(0, 0, w, h, h / 2);
    ctx.fill();
    ctx.fillStyle = "#45454b";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 10 * scale, h / 2 + scale);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 4;
    return { t, aspect: w / h };
  }, [text]);
  return (
    <sprite position={position} scale={[0.12 * texture.aspect, 0.12, 1]}>
      <spriteMaterial map={texture.t} transparent depthWrite={false} />
    </sprite>
  );
}

/** Scene-space box that every compared run fits in, so before and after share one framing. */
export function trajectoryBounds(runs: Run[]): THREE.Box3 {
  const box = new THREE.Box3();
  for (const r of runs) for (const [, x, y, z] of r.trajectory) box.expandByPoint(toScene(x, y, z));
  // Always show the ground and the 1 m target ring.
  box.expandByPoint(new THREE.Vector3(-0.3, 0, -0.3));
  box.expandByPoint(new THREE.Vector3(0.3, TARGET_Z + 0.2, 0.3));
  return box;
}

const VIEW_DIR = new THREE.Vector3(0.62, 0.34, 0.9).normalize();

function FitCamera({ bounds }: { bounds: THREE.Box3 }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  useLayoutEffect(() => {
    const center = bounds.getCenter(new THREE.Vector3());
    const radius = bounds.getBoundingSphere(new THREE.Sphere()).radius * 1.08;
    const vfov = THREE.MathUtils.degToRad(camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * (size.width / Math.max(1, size.height)));
    const dist = radius / Math.sin(Math.min(vfov, hfov) / 2);
    camera.position.copy(center).addScaledVector(VIEW_DIR, dist);
    camera.near = Math.max(0.05, dist - radius * 3);
    camera.far = dist + radius * 4;
    camera.lookAt(center);
    camera.updateProjectionMatrix();
  }, [bounds, camera, size.width, size.height]);
  return null;
}

export function SimScene({
  run,
  primary,
  color,
  bounds,
  showTarget = true,
}: {
  run: Run;
  primary: boolean;
  color: string;
  /** Shared framing; defaults to this run alone. */
  bounds?: THREE.Box3;
  showTarget?: boolean;
}) {
  const path = useMemo(() => run.trajectory.map(([, x, y, z]) => toScene(x, y, z).add(new THREE.Vector3(0, 0.03, 0))), [run]);
  const ground = useMemo(() => path.map((p) => new THREE.Vector3(p.x, 0.002, p.z)), [path]);
  const box = useMemo(() => bounds ?? trajectoryBounds([run]), [bounds, run]);
  return (
    <Canvas dpr={[1, 2]} camera={{ fov: 34 }} gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }}>
      <FitCamera bounds={box} />
      <AnchorScope primary={primary}>
        <ambientLight intensity={0.75} />
        <hemisphereLight args={["#ffffff", "#d9d6e8", 0.6]} />
        <directionalLight position={[2, 4, 2]} intensity={1.6} />
        <Grid
          position={[0, 0, 0]}
          args={[10, 10]}
          cellSize={0.25}
          cellThickness={0.8}
          cellColor="#d9d8e2"
          sectionSize={1}
          sectionThickness={1.2}
          sectionColor="#bdbcca"
          fadeDistance={9}
          fadeStrength={1.5}
          infiniteGrid
        />
        {showTarget && (
          <group position={[0, TARGET_Z + 0.03, 0]}>
            <mesh rotation={[Math.PI / 2, 0, 0]}>
              <torusGeometry args={[0.22, 0.004, 8, 64]} />
              <meshBasicMaterial color="#1f1f1f" transparent opacity={0.35} />
            </mesh>
            <LabelSprite text="Target 50 cm" position={[-0.22, 0.07, 0]} />
          </group>
        )}
        <Line points={path} color={color} lineWidth={3} transparent opacity={0.9} />
        <Line points={ground} color={color} lineWidth={1.5} transparent opacity={0.25} dashed dashSize={0.05} gapSize={0.04} />
        <FlyingDrone run={run} color={color} />
      </AnchorScope>
    </Canvas>
  );
}
