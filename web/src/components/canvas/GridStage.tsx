// The floor the 3D views stand on. The test stage of the simulation replays: a glossy
// pale-blue floor with thin cyan grid lines out to a hazy sky, soft contact shadows, and
// plywood props for the tests. The studio (Model and CAD tabs): a calm CAD grid on the
// canvas's own paper, with the X axis in red and the Y axis in green through the origin.
// Everything scales with the product, so a 70 mm drone and a 300 mm fan both read, and the
// studio's Grid switch (lib/ui `studio.grid`) hides the lines of both.
import { ContactShadows, Grid, MeshReflectorMaterial } from "@react-three/drei";
import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";
import { useUi } from "../../lib/ui";

const ZENITH = "#86c1e8";
const SKY = "#b4d9f1";
const HAZE = "#d8ecf8";
const HORIZON = "#eaf5fb";
const FLOOR = "#d6e8f2";
const CELL = "#9fd9ec";
const SECTION = "#46bddf";
const PLYWOOD = "#d8b98f";
const MARK = "#1d7f9f";

/** The studio grid: lines a few shades darker than the canvas paper, axes in muted red and green. */
const STUDIO = { cell: "#9a9a92", section: "#7c7c74", axisX: "#cf5b52", axisY: "#4f9b67", mark: "#9a9a92" };

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

/** A scale bar lying on the floor along one major grid cell: |-- 5 cm --|. `metres` is its real length. */
function ScaleMark({ length, metres, position, color = MARK }: { length: number; metres: number; position: [number, number, number]; color?: string }) {
  const map = useMemo(() => {
    const w = 512;
    const h = 128;
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const ctx = c.getContext("2d")!;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
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
    ctx.fillText(fmtLength(metres), w / 2, y - 18);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 8;
    return t;
  }, [metres, color]);
  useEffect(() => () => map.dispose(), [map]);
  return (
    <mesh position={position} rotation={[-Math.PI / 2, 0, 0]} renderOrder={2}>
      <planeGeometry args={[length, length / 4]} />
      <meshBasicMaterial map={map} transparent depthWrite={false} toneMapped={false} polygonOffset polygonOffsetFactor={-4} />
    </mesh>
  );
}

const GRID_VERTEX = /* glsl */ `
  varying vec3 vWorld;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

// Lines of constant pixel width from the screen-space derivatives; fine lines fade out where
// they would crowd into moiré, and everything fades with the distance from the grid's centre.
const GRID_FRAGMENT = /* glsl */ `
  uniform float uMinor;
  uniform float uMajor;
  uniform float uFade;
  uniform vec2 uCenter;
  uniform vec3 uCell;
  uniform vec3 uSection;
  uniform vec3 uAxisX;
  uniform vec3 uAxisY;
  varying vec3 vWorld;

  float lines(vec2 coord, float width) {
    vec2 w = max(fwidth(coord), vec2(1e-6));
    vec2 d = abs(fract(coord - 0.5) - 0.5) / w / width;
    return 1.0 - min(min(d.x, d.y), 1.0);
  }
  float crowd(vec2 coord) {
    vec2 w = fwidth(coord);
    return 1.0 - smoothstep(0.18, 0.45, max(w.x, w.y));
  }
  float axis(float v, float width) {
    return 1.0 - min(abs(v) / max(fwidth(v), 1e-6) / width, 1.0);
  }
  vec4 over(vec4 top, vec4 under) {
    float a = top.a + under.a * (1.0 - top.a);
    return vec4((top.rgb * top.a + under.rgb * under.a * (1.0 - top.a)) / max(a, 1e-5), a);
  }

  void main() {
    vec2 p = vWorld.xz;
    vec4 c = vec4(uCell, lines(p / uMinor, 1.0) * 0.2 * crowd(p / uMinor));
    c = over(vec4(uSection, lines(p / uMajor, 1.2) * 0.34 * crowd(p / uMajor)), c);
    // CAD's Y axis runs along -z here (the model is turned Z-up to Y-up), the X axis along x.
    c = over(vec4(uAxisY, axis(p.x, 1.6) * 0.85), c);
    c = over(vec4(uAxisX, axis(p.y, 1.6) * 0.85), c);
    c.a *= 1.0 - smoothstep(uFade * 0.35, uFade, distance(p, uCenter));
    if (c.a < 0.002) discard;
    gl_FragColor = vec4(c.rgb, c.a);
  }
`;

/** The studio's CAD grid on the floor plane: minor and major cells, and the two axes through the origin. */
function StudioGrid({ minor, major, fade, center, y }: { minor: number; major: number; fade: number; center: [number, number]; y: number }) {
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: GRID_VERTEX,
        fragmentShader: GRID_FRAGMENT,
        transparent: true,
        depthWrite: false,
        uniforms: {
          uMinor: { value: 1 },
          uMajor: { value: 1 },
          uFade: { value: 1 },
          uCenter: { value: new THREE.Vector2() },
          uCell: { value: new THREE.Color(STUDIO.cell) },
          uSection: { value: new THREE.Color(STUDIO.section) },
          uAxisX: { value: new THREE.Color(STUDIO.axisX) },
          uAxisY: { value: new THREE.Color(STUDIO.axisY) },
        },
      }),
    [],
  );
  useEffect(() => () => material.dispose(), [material]);
  material.uniforms.uMinor.value = minor;
  material.uniforms.uMajor.value = major;
  material.uniforms.uFade.value = fade;
  (material.uniforms.uCenter.value as THREE.Vector2).set(center[0], center[1]);
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[center[0], y, center[1]]} material={material} renderOrder={1} raycast={() => null}>
      <planeGeometry args={[fade * 2.2, fade * 2.2]} />
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
  /** "stage": the glossy test stage of the simulation replays (default); "studio": the calm CAD grid of the Model and CAD tabs. */
  variant?: "stage" | "studio";
  /** Grid lines and the scale mark; defaults to the studio's Grid switch. */
  grid?: boolean;
  /** Metres per scene unit, for the scale mark: 1 for a scene in metres, 0.001 for one in millimetres. */
  unit?: number;
  /** Height of the floor in scene units (default 0). */
  floor?: number;
  /** Rough product size in scene units; drives grid spacing, fog and shadow reach. */
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

/** Where the scale bar lies: along the major line just in front of the product (cameras look
 * from +x +z), starting at a grid crossing so it spans exactly one major cell. */
function markAt(size: number, major: number, center: [number, number]): [number, number] {
  const x = Math.round(center[0] / major) * major;
  const z = (Math.round(center[1] / major) + Math.max(1, Math.ceil((size * 0.75) / major))) * major;
  return [x + major / 2, z + major * 0.14];
}

export function GridStage(props: GridStageProps) {
  const gridSwitch = useUi((s) => s.studio.grid);
  const lines = props.grid ?? gridSwitch;
  return props.variant === "studio" ? <StudioFloor {...props} lines={lines} /> : <TestStage {...props} lines={lines} />;
}

/** The studio: the canvas's own paper shows through, the CAD grid and soft contact shadows lie on it. */
function StudioFloor({ size, unit = 1, floor = 0, center = [0, 0], shadowArea, shadowReach, shadowOpacity = 0.5, lights = true, scaleMark = true, lines }: GridStageProps & { lines: boolean }) {
  const { major, minor } = stageGrid(size);
  // Lift the overlays by a hair of the product size so nothing z-fights with the floor.
  const lift = size * 0.002;
  const [markX, markZ] = markAt(size, major, center);
  return (
    <>
      {lights && (
        <>
          <hemisphereLight args={["#ffffff", "#cfcfc8", 1.1]} />
          <directionalLight position={[size * 6, size * 12, size * 5]} intensity={1.5} />
          <directionalLight position={[-size * 8, size * 5, -size * 6]} intensity={0.45} />
        </>
      )}
      {lines && <StudioGrid minor={minor} major={major} fade={size * 8} center={center} y={floor + lift} />}
      <ContactShadows
        position={[center[0], floor + lift * 2, center[1]]}
        scale={shadowArea ?? size * 4}
        far={shadowReach ?? size * 1.5}
        opacity={shadowOpacity * 0.8}
        blur={2.4}
        resolution={512}
        color="#1a1a18"
      />
      {lines && scaleMark && <ScaleMark length={major} metres={major * unit} color={STUDIO.mark} position={[markX, floor + lift * 3, markZ]} />}
    </>
  );
}

function TestStage({
  size,
  unit = 1,
  center = [0, 0],
  shadowArea,
  shadowReach,
  shadowOpacity = 0.5,
  reflections = true,
  lights = true,
  obstacles = [],
  scaleMark = true,
  lines,
}: GridStageProps & { lines: boolean }) {
  const sky = useSkyTexture();
  const plywood = usePlywood();
  const { major, minor } = stageGrid(size);
  const fogNear = size * 5;
  const fogFar = size * 26;
  const floorSize = fogFar * 4;
  // Lift the overlays by a hair of the product size so nothing z-fights with the floor.
  const lift = size * 0.002;
  const [markX, markZ] = markAt(size, major, center);
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
      {lines && (
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
      )}
      <ContactShadows
        position={[center[0], lift * 2, center[1]]}
        scale={shadowArea ?? size * 4}
        far={shadowReach ?? size * 1.5}
        opacity={shadowOpacity}
        blur={2.2}
        resolution={512}
        color="#29465a"
      />
      {lines && scaleMark && <ScaleMark length={major} metres={major * unit} position={[markX, lift * 3, markZ]} />}
      {obstacles.map((p, i) => (
        <Prop key={i} prop={p} material={plywood} />
      ))}
    </>
  );
}
