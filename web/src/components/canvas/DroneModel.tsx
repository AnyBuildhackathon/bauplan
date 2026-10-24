// Procedural whoop, sized like the build: the frame from the CAD parameters (hub,
// arms and motor pads as frame_build.py draws them), 1102 motors, 40 mm propellers
// and the chosen battery at its real size. Every part is a named anchor so `point`
// and `draw` events can find it on screen. Units are metres, y is up, front is -z.
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { useAnchor } from "./anchors";

const CORNERS: { key: string; corner: string; angle: number; dir: 1 | -1 }[] = [
  { key: "motor_front_left", corner: "front_left", angle: (-3 * Math.PI) / 4, dir: 1 },
  { key: "motor_front_right", corner: "front_right", angle: -Math.PI / 4, dir: -1 },
  { key: "motor_rear_left", corner: "rear_left", angle: (3 * Math.PI) / 4, dir: -1 },
  { key: "motor_rear_right", corner: "rear_right", angle: Math.PI / 4, dir: 1 },
];

const AGENT = new THREE.Color("#ff8a3d");

/** Material that glows orange while the agent talks about the part it belongs to. */
function useGlowMaterial(color: string, opts: { metalness?: number; roughness?: number; opacity?: number } = {}) {
  return useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color,
        metalness: opts.metalness ?? 0.1,
        roughness: opts.roughness ?? 0.55,
        transparent: opts.opacity !== undefined,
        opacity: opts.opacity ?? 1,
        emissive: AGENT,
        emissiveIntensity: 0,
      }),
    [color, opts.metalness, opts.roughness, opts.opacity],
  );
}

function Glow({ material, on }: { material: THREE.MeshStandardMaterial; on: boolean }) {
  useFrame(({ clock }) => {
    const target = on ? 0.16 + 0.12 * Math.sin(clock.elapsedTime * 5) : 0;
    material.emissiveIntensity += (target - material.emissiveIntensity) * 0.15;
  });
  return null;
}

function Anchor({ name, radius, children, position }: { name: string; radius: number; children?: ReactNode; position?: [number, number, number] }) {
  const ref = useAnchor(name, radius);
  return (
    <group ref={ref} position={position}>
      {children}
    </group>
  );
}

function Propeller({ dir, spin, radius, material }: { dir: 1 | -1; spin: number; radius: number; material: THREE.Material }) {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.y += dir * spin * dt;
  });
  return (
    <group ref={ref}>
      {[0, 1, 2].map((i) => (
        <group key={i} rotation={[0, (i * Math.PI * 2) / 3, 0]}>
          {/* an elliptical blade, pitched a little */}
          <mesh position={[radius * 0.52, 0, 0]} rotation={[0.22 * dir, 0, 0]} scale={[radius * 0.5, 1, radius * 0.15]} material={material} castShadow>
            <cylinderGeometry args={[1, 1, 0.0007, 28]} />
          </mesh>
        </group>
      ))}
      <mesh material={material}>
        <cylinderGeometry args={[0.0035, 0.0035, 0.004, 16]} />
      </mesh>
    </group>
  );
}

export interface DroneModelProps {
  /** Centre to motor shaft, metres. */
  arm: number;
  /** Frame plate thickness, metres. */
  thickness: number;
  /** Battery pack length, width, height in metres. */
  battery: [number, number, number];
  propDiameter: number;
  /** Canonical part keys the agent is talking about right now. */
  highlight: Set<string>;
  /** Propeller speed in rad/s. */
  spin?: number;
}

const HUB_R = 0.02;
const ARM_W = 0.006;
const PAD_R = 0.006;
const MOTOR_R = 0.007;
const MOTOR_H = 0.0136;

export function DroneModel({ arm, thickness, battery, propDiameter, highlight, spin = 0 }: DroneModelProps) {
  const frameMat = useGlowMaterial("#ff8a3d", { roughness: 0.5 });
  const motorMat = useGlowMaterial("#b9bec6", { metalness: 0.75, roughness: 0.3 });
  const statorMat = useMemo(() => new THREE.MeshStandardMaterial({ color: "#1c1d21", roughness: 0.5 }), []);
  const propMat = useGlowMaterial("#e9edf3", { roughness: 0.35, opacity: 0.9 });
  const fcMat = useGlowMaterial("#1d2433", { roughness: 0.45 });
  const chipMat = useMemo(() => new THREE.MeshStandardMaterial({ color: "#5d6675", metalness: 0.5, roughness: 0.4 }), []);
  const batteryMat = useGlowMaterial("#2b2e35", { roughness: 0.35 });
  const labelMat = useMemo(() => new THREE.MeshStandardMaterial({ color: "#f2b33d", roughness: 0.4 }), []);
  const strapMat = useMemo(() => new THREE.MeshStandardMaterial({ color: "#16171a", roughness: 0.8 }), []);

  const hl = (k: string) => highlight.has(k);
  const motorsOn = hl("motors") || CORNERS.some((m) => hl(m.key));
  const propsOn = hl("propellers") || CORNERS.some((m) => hl(`propeller_${m.corner}`));
  const corners = CORNERS.map((c) => ({ ...c, x: arm * Math.cos(c.angle), z: arm * Math.sin(c.angle) }));
  const [bl, bw, bh] = battery;
  const top = thickness / 2;
  const fcY = top + 0.004;
  const batteryY = fcY + 0.003 + bh / 2;

  return (
    <group>
      <Glow material={frameMat} on={hl("frame")} />
      <Glow material={motorMat} on={motorsOn} />
      <Glow material={propMat} on={propsOn} />
      <Glow material={fcMat} on={hl("flight_controller")} />
      <Glow material={batteryMat} on={hl("battery")} />

      <Anchor name="frame" radius={arm + PAD_R}>
        <mesh material={frameMat} castShadow receiveShadow>
          <cylinderGeometry args={[HUB_R, HUB_R, thickness, 48]} />
        </mesh>
        {corners.map((m) => (
          <group key={m.key}>
            <mesh material={frameMat} position={[m.x / 2, 0, m.z / 2]} rotation={[0, -m.angle, 0]} castShadow receiveShadow>
              <boxGeometry args={[arm, thickness, ARM_W]} />
            </mesh>
            <mesh material={frameMat} position={[m.x, 0, m.z]} castShadow receiveShadow>
              <cylinderGeometry args={[PAD_R, PAD_R, thickness, 32]} />
            </mesh>
          </group>
        ))}
      </Anchor>

      {corners.map((m) => (
        <Anchor key={m.key} name={m.key} radius={0.01} position={[m.x, top + MOTOR_H / 2, m.z]}>
          <mesh material={statorMat} position={[0, -MOTOR_H / 2 + 0.0015, 0]} castShadow>
            <cylinderGeometry args={[MOTOR_R, MOTOR_R, 0.003, 24]} />
          </mesh>
          <mesh material={motorMat} position={[0, 0.0015, 0]} castShadow>
            <cylinderGeometry args={[MOTOR_R * 0.95, MOTOR_R, MOTOR_H - 0.003, 24]} />
          </mesh>
          <Anchor name={`propeller_${m.corner}`} radius={propDiameter / 2} position={[0, MOTOR_H / 2 + 0.002, 0]}>
            <Propeller dir={m.dir} spin={spin} radius={propDiameter / 2} material={propMat} />
          </Anchor>
        </Anchor>
      ))}
      {/* group anchors resolve to a representative motor and prop */}
      <Anchor name="motors" radius={0.012} position={[corners[1].x, top + MOTOR_H / 2, corners[1].z]} />
      <Anchor name="propellers" radius={propDiameter / 2} position={[corners[0].x, top + MOTOR_H + 0.002, corners[0].z]} />

      <Anchor name="flight_controller" radius={0.016} position={[0, fcY, 0]}>
        <mesh material={fcMat} castShadow>
          <boxGeometry args={[0.029, 0.0016, 0.029]} />
        </mesh>
        <mesh material={chipMat} position={[0, 0.0014, 0]}>
          <boxGeometry args={[0.007, 0.0012, 0.007]} />
        </mesh>
        {[-1, 1].map((s) => (
          <mesh key={s} material={chipMat} position={[s * 0.009, 0.0012, 0.009]}>
            <boxGeometry args={[0.004, 0.001, 0.003]} />
          </mesh>
        ))}
      </Anchor>

      <Anchor name="battery" radius={Math.max(bl, bw) / 2} position={[0, batteryY, 0]}>
        <mesh material={batteryMat} castShadow>
          <boxGeometry args={[bw, bh, bl]} />
        </mesh>
        <mesh material={labelMat} position={[0, 0, -bl * 0.12]}>
          <boxGeometry args={[bw * 1.01, bh * 1.01, bl * 0.42]} />
        </mesh>
        <mesh material={strapMat}>
          <boxGeometry args={[bw + 0.0012, bh + 0.0012, 0.008]} />
        </mesh>
      </Anchor>
    </group>
  );
}
