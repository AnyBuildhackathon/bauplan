// The drone pulled apart for the build guide: every scene part floats on its own
// offset from the frame, the parts of the current step glow orange, parts from earlier
// steps stay solid and parts still to come fade to ghosts. Sizes come from the build
// (useAssembly), units are metres, y is up, front is -z, as in DroneModel.
import { OrbitControls } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import type { Assembly } from "../../lib/hooks";

export type PartState = "current" | "done" | "later";

const CORNERS = [
  { corner: "front_left", angle: (-3 * Math.PI) / 4, dir: 1 },
  { corner: "front_right", angle: -Math.PI / 4, dir: -1 },
  { corner: "rear_left", angle: (3 * Math.PI) / 4, dir: -1 },
  { corner: "rear_right", angle: Math.PI / 4, dir: 1 },
] as const;

const LABELS: Record<string, string> = {
  frame: "Frame",
  flight_controller: "Flight controller",
  battery: "Battery",
  motor_front_left: "Motor front left",
  motor_front_right: "Motor front right",
  motor_rear_left: "Motor rear left",
  motor_rear_right: "Motor rear right",
  propeller_front_left: "Propeller front left",
  propeller_front_right: "Propeller front right",
  propeller_rear_left: "Propeller rear left",
  propeller_rear_right: "Propeller rear right",
};

const AGENT = new THREE.Color("#ff8a3d");
const HUB_R = 0.02;
const ARM_W = 0.006;
const PAD_R = 0.006;
const MOTOR_R = 0.007;
const MOTOR_H = 0.0136;

/** How far each kind of part floats away from the frame when fully exploded. */
const LIFT = { motor: 0.022, propeller: 0.05, flight_controller: 0.034, battery: 0.066 };
const SPREAD = { motor: 0.012, propeller: 0.02 };

/** A material whose glow and opacity ease towards the part's state every frame. */
function useStateMaterial(color: string, state: PartState, opts: { metalness?: number; roughness?: number } = {}) {
  const material = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color,
        metalness: opts.metalness ?? 0.1,
        roughness: opts.roughness ?? 0.55,
        transparent: true,
        emissive: AGENT,
        emissiveIntensity: 0,
      }),
    [color, opts.metalness, opts.roughness],
  );
  useFrame(({ clock }) => {
    const glow = state === "current" ? 0.28 + 0.14 * Math.sin(clock.elapsedTime * 4) : 0;
    const opacity = state === "later" ? 0.16 : 1;
    material.emissiveIntensity += (glow - material.emissiveIntensity) * 0.15;
    material.opacity += (opacity - material.opacity) * 0.15;
    material.depthWrite = material.opacity > 0.5;
  });
  return material;
}

/** Eases a group from the assembled position to its exploded one. */
function Floating({ to, explode, children }: { to: [number, number, number]; explode: number; children: ReactNode }) {
  const ref = useRef<THREE.Group>(null);
  const target = useMemo(() => new THREE.Vector3(), []);
  useFrame(() => {
    if (!ref.current) return;
    target.set(to[0] * explode, to[1] * explode, to[2] * explode);
    ref.current.position.lerp(target, 0.12);
  });
  return <group ref={ref}>{children}</group>;
}

/** An orange pill drawn into a texture, so it needs no DOM inside the canvas. */
function Label({ name, state, position }: { name: string; state: PartState; position: [number, number, number] }) {
  const text = LABELS[name] ?? name;
  const texture = useMemo(() => {
    const scale = 3;
    const c = document.createElement("canvas");
    const ctx = c.getContext("2d")!;
    const font = `700 ${13 * scale}px "Inter Tight", sans-serif`;
    ctx.font = font;
    const w = Math.ceil(ctx.measureText(text).width + 22 * scale);
    const h = 26 * scale;
    c.width = w;
    c.height = h;
    ctx.font = font;
    ctx.fillStyle = "#ff8a3d";
    ctx.beginPath();
    ctx.roundRect(0, 0, w, h, h / 2);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 11 * scale, h / 2 + scale);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 4;
    return { t, aspect: w / h };
  }, [text]);
  if (state !== "current") return null;
  return (
    <sprite position={position} scale={[0.028 * texture.aspect, 0.028, 1]} renderOrder={10}>
      <spriteMaterial map={texture.t} transparent depthTest={false} depthWrite={false} sizeAttenuation={false} toneMapped={false} />
    </sprite>
  );
}

function Frame({ arm, thickness, state }: { arm: number; thickness: number; state: PartState }) {
  const material = useStateMaterial("#ff8a3d", state, { roughness: 0.5 });
  return (
    <group>
      <mesh material={material}>
        <cylinderGeometry args={[HUB_R, HUB_R, thickness, 48]} />
      </mesh>
      {CORNERS.map((c) => {
        const x = arm * Math.cos(c.angle);
        const z = arm * Math.sin(c.angle);
        return (
          <group key={c.corner}>
            <mesh material={material} position={[x / 2, 0, z / 2]} rotation={[0, -c.angle, 0]}>
              <boxGeometry args={[arm, thickness, ARM_W]} />
            </mesh>
            <mesh material={material} position={[x, 0, z]}>
              <cylinderGeometry args={[PAD_R, PAD_R, thickness, 32]} />
            </mesh>
          </group>
        );
      })}
      <Label name="frame" state={state} position={[arm * 0.75, 0.006, arm * 0.75]} />
    </group>
  );
}

function Motor({ name, state }: { name: string; state: PartState }) {
  const bell = useStateMaterial("#b9bec6", state, { metalness: 0.75, roughness: 0.3 });
  const stator = useStateMaterial("#1c1d21", state, { roughness: 0.5 });
  return (
    <group>
      <mesh material={stator} position={[0, -MOTOR_H / 2 + 0.0015, 0]}>
        <cylinderGeometry args={[MOTOR_R, MOTOR_R, 0.003, 24]} />
      </mesh>
      <mesh material={bell} position={[0, 0.0015, 0]}>
        <cylinderGeometry args={[MOTOR_R * 0.95, MOTOR_R, MOTOR_H - 0.003, 24]} />
      </mesh>
      <Label name={name} state={state} position={[0, MOTOR_H, 0]} />
    </group>
  );
}

function Propeller({ name, state, radius, dir }: { name: string; state: PartState; radius: number; dir: 1 | -1 }) {
  const material = useStateMaterial("#e9edf3", state, { roughness: 0.35 });
  const ref = useRef<THREE.Group>(null);
  useFrame((_, dt) => {
    // Current propellers turn slowly, so their direction reads at a glance.
    if (ref.current && state === "current") ref.current.rotation.y += dir * 1.2 * dt;
  });
  return (
    <group>
      <group ref={ref}>
        {[0, 1, 2].map((i) => (
          <group key={i} rotation={[0, (i * Math.PI * 2) / 3, 0]}>
            <mesh position={[radius * 0.52, 0, 0]} rotation={[0.22 * dir, 0, 0]} scale={[radius * 0.5, 1, radius * 0.15]} material={material}>
              <cylinderGeometry args={[1, 1, 0.0007, 28]} />
            </mesh>
          </group>
        ))}
        <mesh material={material}>
          <cylinderGeometry args={[0.0035, 0.0035, 0.004, 16]} />
        </mesh>
      </group>
      <Label name={name} state={state} position={[0, 0.008, 0]} />
    </group>
  );
}

function FlightController({ state }: { state: PartState }) {
  const board = useStateMaterial("#1d2433", state, { roughness: 0.45 });
  const chip = useStateMaterial("#5d6675", state, { metalness: 0.5, roughness: 0.4 });
  return (
    <group>
      <mesh material={board}>
        <boxGeometry args={[0.029, 0.0016, 0.029]} />
      </mesh>
      <mesh material={chip} position={[0, 0.0014, 0]}>
        <boxGeometry args={[0.007, 0.0012, 0.007]} />
      </mesh>
      {/* the arrow that points forward */}
      <mesh material={chip} position={[0, 0.0012, -0.011]} rotation={[-Math.PI / 2, 0, 0]}>
        <coneGeometry args={[0.003, 0.005, 3]} />
      </mesh>
      <Label name="flight_controller" state={state} position={[0.02, 0.004, 0]} />
    </group>
  );
}

function Battery({ size, state }: { size: [number, number, number]; state: PartState }) {
  const body = useStateMaterial("#2b2e35", state, { roughness: 0.35 });
  const label = useStateMaterial("#f2b33d", state, { roughness: 0.4 });
  const [l, w, h] = size;
  return (
    <group>
      <mesh material={body}>
        <boxGeometry args={[w, h, l]} />
      </mesh>
      <mesh material={label} position={[0, 0, -l * 0.12]}>
        <boxGeometry args={[w * 1.01, h * 1.01, l * 0.42]} />
      </mesh>
      <Label name="battery" state={state} position={[w / 2 + 0.012, h, 0]} />
    </group>
  );
}

export interface ExplodedDroneProps {
  build: Assembly;
  /** State per scene part name; a part that is missing counts as done. */
  states: Record<string, PartState>;
  /** 0 is assembled, 1 is fully exploded. */
  explode: number;
}

export function ExplodedDrone({ build, states, explode }: ExplodedDroneProps) {
  const { arm, thickness, battery, propDiameter } = build;
  const state = (name: string): PartState => states[name] ?? "done";
  const top = thickness / 2;
  const fcY = top + 0.004;
  const batteryY = fcY + 0.003 + battery[2] / 2;
  return (
    <group>
      <Frame arm={arm} thickness={thickness} state={state("frame")} />
      {CORNERS.map((c) => {
        const x = arm * Math.cos(c.angle);
        const z = arm * Math.sin(c.angle);
        const out = (d: number): [number, number, number] => [Math.cos(c.angle) * d, 0, Math.sin(c.angle) * d];
        const motorOut = out(SPREAD.motor);
        const propOut = out(SPREAD.propeller);
        return (
          <group key={c.corner} position={[x, top + MOTOR_H / 2, z]}>
            <Floating to={[motorOut[0], LIFT.motor, motorOut[2]]} explode={explode}>
              <Motor name={`motor_${c.corner}`} state={state(`motor_${c.corner}`)} />
            </Floating>
            <group position={[0, MOTOR_H / 2 + 0.002, 0]}>
              <Floating to={[propOut[0], LIFT.propeller, propOut[2]]} explode={explode}>
                <Propeller name={`propeller_${c.corner}`} state={state(`propeller_${c.corner}`)} radius={propDiameter / 2} dir={c.dir} />
              </Floating>
            </group>
          </group>
        );
      })}
      <group position={[0, fcY, 0]}>
        <Floating to={[0, LIFT.flight_controller, 0]} explode={explode}>
          <FlightController state={state("flight_controller")} />
        </Floating>
      </group>
      <group position={[0, batteryY, 0]}>
        <Floating to={[0, LIFT.battery, 0]} explode={explode}>
          <Battery size={battery} state={state("battery")} />
        </Floating>
      </group>
    </group>
  );
}

export function ExplodedScene(props: ExplodedDroneProps) {
  return (
    <Canvas dpr={[1, 2]} camera={{ position: [0.17, 0.14, 0.18], fov: 30, near: 0.005, far: 10 }} gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }}>
      <ambientLight intensity={0.75} />
      <hemisphereLight args={["#ffffff", "#d9d6e8", 0.6]} />
      <directionalLight position={[0.4, 0.8, 0.3]} intensity={1.8} />
      <ExplodedDrone {...props} />
      <OrbitControls makeDefault autoRotate autoRotateSpeed={0.5} enablePan={false} minDistance={0.12} maxDistance={0.6} target={[0, 0.03, 0]} />
    </Canvas>
  );
}
