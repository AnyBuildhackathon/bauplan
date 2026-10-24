// The test stage the 3D views stand on: a glossy pale-blue floor with thin cyan grid
// lines out to a hazy sky, soft contact shadows, and plywood props for the tests.
// Everything scales with the product, so a 70 mm drone and a 300 mm fan both read.
import { ContactShadows, Grid, MeshReflectorMaterial } from "@react-three/drei";
import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";

const ZENITH = "#86c1e8";
const SKY = "#b4d9f1";
const HAZE = "#d8ecf8";
const HORIZON = "#eaf5fb";
const FLOOR = "#d6e8f2";
const CELL = "#9fd9ec";
const SECTION = "#46bddf";
const PLYWOOD = "#d8b98f";

/** The nearest 1, 2 or 5 times a power of ten. */
function niceStep(x: number): number {
  const p = 10 ** Math.floor(Math.log10(x));
  const m = x / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

/** Grid spacing for a product of `size` metres: a major cell about its size, finer cells inside. */
export function stageGrid(size: number) {
  const major = niceStep(size * 0.7);
  const lead = Math.round(major / 10 ** Math.floor(Math.log10(major)));
  return { major, minor: major / (lead === 2 ? 4 : 5) };
}

const fmtLength = (m: number) => (m >= 1 ? `${+m.toFixed(2)} m` : m >= 0.01 ? `${+(m * 100).toFixed(1)} cm` : `${+(m * 1000).toFixed(1)} mm`);

export function usePrefersReducedMotion() {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

/** Vertical sky gradient as an equirect background: light blue overhead, hazy at the horizon. */
function useSkyTexture() {
  const texture = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = 4;
    c.height = 512;
    const ctx = c.getContext("2d")!;
    const g = ctx.createLinearGradient(0, 0, 0, c.height);
    g.addColorStop(0, ZENITH);
    g.addColorStop(0.43, SKY);
    g.addColorStop(0.485, HAZE);
    g.addColorStop(0.5, HORIZON);
    g.addColorStop(1, HORIZON);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, c.width, c.height);
    const t = new THREE.CanvasTexture(c);
    t.mapping = THREE.EquirectangularReflectionMapping;
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }, []);
  useEffect(() => () => texture.dispose(), [texture]);
  return texture;
}

/** A scale bar lying on the floor along one major grid cell: |—— 5 cm ——|. */
function ScaleMark({ length, position }: { length: number; position: [number, number, number] }) {
  const map = useMemo(() => {
    const w = 512;
    const h = 128;
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const ctx = c.getContext("2d")!;
    ctx.strokeStyle = "#1d7f9f";
    ctx.fillStyle = "#1d7f9f";
    ctx.lineWidth = 6;
    ctx.lineCap = "round";
    const y = 92;
    ctx.beginPath();
    ctx.moveTo(4, y);
    ctx.lineTo(w - 4, y);
    ctx.moveTo(4, y - 18);
    ctx.lineTo(4, y + 18);
    ctx.moveTo(w - 4, y - 18);
    ctx.lineTo(w - 4, y + 18);
    ctx.stroke();
    ctx.font = `700 54px "Inter Tight", sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    ctx.fillText(fmtLength(length), w / 2, y - 18);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 8;
    return t;
  }, [length]);
  useEffect(() => () => map.dispose(), [map]);
  return (
    <mesh position={position} rotation={[-Math.PI / 2, 0, 0]} renderOrder={2}>
      <planeGeometry args={[length, length / 4]} />
      <meshBasicMaterial map={map} transparent depthWrite={false} toneMapped={false} polygonOffset polygonOffsetFactor={-4} />
    </mesh>
  );
}

/** Fine plywood grain, shared by every prop. */
function usePlywood() {
  const material = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = 256;
    c.height = 256;
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = PLYWOOD;
    ctx.fillRect(0, 0, 256, 256);
    for (let i = 0; i < 70; i++) {
      const y = (i * 37.3) % 256;
      ctx.strokeStyle = `rgba(${140 + (i % 5) * 8}, ${100 + (i % 3) * 6}, 60, ${0.08 + (i % 4) * 0.03})`;
      ctx.lineWidth = 1 + (i % 3);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.bezierCurveTo(80, y + ((i % 7) - 3) * 3, 170, y - ((i % 5) - 2) * 4, 256, y + ((i % 3) - 1) * 2);
      ctx.stroke();
    }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    return new THREE.MeshStandardMaterial({ map: t, roughness: 0.78, metalness: 0 });
  }, []);
  useEffect(() => () => {
    material.map?.dispose();
    material.dispose();
  }, [material]);
  return material;
}

/** A wedge ramp: `size` is [length, height, width], it rises along +X. */
function rampGeometry([l, h, w]: [number, number, number]) {
  const shape = new THREE.Shape();
  shape.moveTo(-l / 2, 0);
  shape.lineTo(l / 2, 0);
  shape.lineTo(l / 2, h);
  shape.closePath();
  const g = new THREE.ExtrudeGeometry(shape, { depth: w, bevelEnabled: false });
  g.translate(0, 0, -w / 2);
  return g;
}

export interface StageProp {
  kind: "ramp" | "box";
  /** Floor position [x, z] in metres. */
  at: [number, number];
  /** [length, height, width] in metres. */
  size: [number, number, number];
  /** Turn about the vertical axis, radians. */
  yaw?: number;
}

function Prop({ prop, material }: { prop: StageProp; material: THREE.Material }) {
  const [l, h, w] = prop.size;
  const geometry = useMemo(
    () => (prop.kind === "ramp" ? rampGeometry([l, h, w]) : new THREE.BoxGeometry(l, h, w).translate(0, h / 2, 0)),
    [prop.kind, l, h, w],
  );
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <mesh geometry={geometry} material={material} position={[prop.at[0], 0, prop.at[1]]} rotation={[0, prop.yaw ?? 0, 0]} castShadow />;
}

/** Plywood set dressing behind the product: a ramp and a crate, sized to the product. */
export function stageObstacles(size: number, center: [number, number] = [0, 0]): StageProp[] {
  const [x, z] = center;
  return [
    { kind: "ramp", at: [x - size * 3.6, z - size * 3.4], size: [size * 1.6, size * 0.4, size * 0.9], yaw: 0.6 },
    { kind: "box", at: [x + size * 0.4, z - size * 4.6], size: [size * 0.6, size * 0.6, size * 0.6], yaw: 0.35 },
  ];
}

export interface GridStageProps {
  /** Rough product size in metres; drives grid spacing, fog and shadow reach. */
  size: number;
  /** Where the shadows and the scale mark gather, [x, z]. */
  center?: [number, number];
  /** Width of the area that gets contact shadows, metres (default 4 x size). */
  shadowArea?: number;
  /** How high above the floor something still casts a shadow (default 1.5 x size). */
  shadowReach?: number;
  shadowOpacity?: number;
  /** Mirror reflections in the floor; off renders one pass less. */
  reflections?: boolean;
  /** Hemisphere sky light plus a key and a fill; scenes with their own rig pass false. */
  lights?: boolean;
  obstacles?: StageProp[];
  /** Show the scale bar on the floor. */
  scaleMark?: boolean;
}

export function GridStage({
  size,
  center = [0, 0],
  shadowArea,
  shadowReach,
  shadowOpacity = 0.5,
  reflections = true,
  lights = true,
  obstacles = [],
  scaleMark = true,
}: GridStageProps) {
  const sky = useSkyTexture();
  const plywood = usePlywood();
  const { major, minor } = stageGrid(size);
  const fogNear = size * 5;
  const fogFar = size * 26;
  const floorSize = fogFar * 4;
  // Lift the overlays by a hair of the product size so nothing z-fights with the floor.
  const lift = size * 0.002;
  // The scale bar lies along the major line just in front of the product (cameras look
  // from +x +z), starting at a grid crossing so it spans exactly one major cell.
  const markX = Math.round(center[0] / major) * major;
  const markZ = (Math.round(center[1] / major) + Math.max(1, Math.ceil((size * 0.75) / major))) * major;
  return (
    <>
      <primitive attach="background" object={sky} />
      <fog attach="fog" args={[HORIZON, fogNear, fogFar]} />
      {lights && (
        <>
          <hemisphereLight args={["#f2f9ff", "#9fb8c7", 1.1]} />
          <directionalLight position={[size * 6, size * 12, size * 5]} intensity={1.5} />
          <directionalLight position={[-size * 8, size * 5, -size * 6]} intensity={0.45} color="#d9ecff" />
        </>
      )}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[center[0], 0, center[1]]} renderOrder={-1}>
        <planeGeometry args={[floorSize, floorSize]} />
        {reflections ? (
          <MeshReflectorMaterial
            color={FLOOR}
            roughness={0.85}
            metalness={0.05}
            resolution={512}
            blur={[320, 90]}
            mixBlur={1}
            mixStrength={0.9}
            mixContrast={1}
            depthScale={0.6}
            minDepthThreshold={0.2}
            maxDepthThreshold={1.2}
            mirror={0}
          />
        ) : (
          <meshStandardMaterial color={FLOOR} roughness={0.55} metalness={0.05} />
        )}
      </mesh>
      <Grid
        position={[center[0], lift, center[1]]}
        args={[1, 1]}
        cellSize={minor}
        cellThickness={0.7}
        cellColor={CELL}
        sectionSize={major}
        sectionThickness={1.15}
        sectionColor={SECTION}
        fadeDistance={fogFar * 0.85}
        fadeStrength={1.6}
        infiniteGrid
      />
      <ContactShadows
        position={[center[0], lift * 2, center[1]]}
        scale={shadowArea ?? size * 4}
        far={shadowReach ?? size * 1.5}
        opacity={shadowOpacity}
        blur={2.2}
        resolution={512}
        color="#29465a"
      />
      {scaleMark && <ScaleMark length={major} position={[markX + major / 2, lift * 3, markZ + major * 0.14]} />}
      {obstacles.map((p, i) => (
        <Prop key={i} prop={p} material={plywood} />
      ))}
    </>
  );
}
