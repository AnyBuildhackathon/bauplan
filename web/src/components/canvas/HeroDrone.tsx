// The hero drone as FreeCAD built it (agent/freecad/frame_build.py): the GLB from the latest
// `cad` event, or the recorded v1 build before the first one. Every scene target from
// docs/events.md is a node in the file, so `point` and `draw` find the real part. Props spin
// about their shafts, a part glows while the agent talks about it, and a battery the agent is
// still weighing is scaled from the size baked into the file. Units are metres, y is up, the
// nose is -z.
import { useFrame, useLoader } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { useSession } from "../../events/store";
import { assetUrl } from "../../lib/api";
import { useAnchor } from "./anchors";
import { ExplodeLayer, useExplodeHover, type PieceSpec } from "./explode";

/** The reference drone shown before the first CAD event. */
export const DEFAULT_DRONE_URL = `${import.meta.env.BASE_URL}models/hero-drone.glb`;

const CORNERS = ["front_left", "front_right", "rear_left", "rear_right"] as const;
/** Spin seen from above, +1 counter-clockwise; matches the blade pitch in the file. */
const SPIN: Record<(typeof CORNERS)[number], 1 | -1> = { front_left: -1, front_right: 1, rear_left: 1, rear_right: -1 };
const NODES = ["frame", "canopy", "camera", "flight_controller", "battery", "battery_strap", "antenna", ...CORNERS.flatMap((c) => [`motor_${c}`, `propeller_${c}`])];
const AGENT = new THREE.Color("#ff8a3d");

/** Hover names and the few pills an exploded drone shows (one per kind of part). */
const PIECES: Record<string, { name: string; label: string }> = {
  frame: { name: "Frame", label: "Frame" },
  canopy: { name: "Canopy", label: "Canopy" },
  camera: { name: "FPV camera", label: "" },
  flight_controller: { name: "Flight controller", label: "Flight controller" },
  battery: { name: "Battery", label: "Battery" },
  battery_strap: { name: "Battery strap", label: "" },
  antenna: { name: "Receiver antenna", label: "Antenna" },
  ...Object.fromEntries(
    CORNERS.flatMap((c, i) => [
      [`motor_${c}`, { name: `Motor ${c.replace("_", " ")}`, label: i === 0 ? "Motors ×4" : "" }],
      [`propeller_${c}`, { name: `Propeller ${c.replace("_", " ")}`, label: i === 0 ? "Propellers ×4" : "" }],
    ]),
  ),
};

/** The drone GLB to show: the latest FreeCAD build, else the recorded one. */
export function useDroneUrl(): string {
  const cad = useSession((s) => s.cad);
  return (cad && !cad.part && assetUrl(cad.glb_url)) || DEFAULT_DRONE_URL;
}

export interface HeroDroneProps {
  url: string;
  /** The battery to show, length, width, height in metres. */
  battery: [number, number, number];
  /** Canonical part keys the agent is talking about right now. */
  highlight: Set<string>;
  /** Propeller speed in rad/s. */
  spin?: number;
  /** The Model tab: parts follow the explode slider and answer hover. */
  explodable?: boolean;
}

interface Part {
  node: THREE.Object3D;
  materials: THREE.MeshStandardMaterial[];
}

function Anchor({ name, radius, position }: { name: string; radius: number; position: THREE.Vector3 }) {
  const ref = useAnchor(name, radius);
  return <group ref={ref} position={position} />;
}

/** Centre and radius of a node's meshes, in the drone's own frame. */
function bounds(root: THREE.Object3D, node: THREE.Object3D): { center: THREE.Vector3; radius: number } {
  root.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(node);
  const inverse = root.matrixWorld.clone().invert();
  box.applyMatrix4(inverse);
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  return { center: sphere.center, radius: sphere.radius };
}

export function HeroDrone(props: HeroDroneProps) {
  const gltf = useLoader(GLTFLoader, props.url);
  // A CadQuery fallback writes the bare frame; the recorded build stands in for the drone then.
  if (!gltf.scene.getObjectByName("motor_front_left") && props.url !== DEFAULT_DRONE_URL) {
    return <HeroDrone {...props} url={DEFAULT_DRONE_URL} />;
  }
  return <Drone {...props} source={gltf.scene} />;
}

function Drone({ source, battery, highlight, spin = 0, explodable = false }: HeroDroneProps & { source: THREE.Group }) {
  const { root, parts, baked } = useMemo(() => {
    const root = source.clone(true);
    const parts = new Map<string, Part>();
    for (const name of NODES) {
      const node = root.getObjectByName(name);
      if (!node) continue;
      const materials: THREE.MeshStandardMaterial[] = [];
      node.traverse((o) => {
        if (!(o instanceof THREE.Mesh)) return;
        // Props are children of their motor; they glow with the props, not the motor.
        let owner: THREE.Object3D | null = o;
        while (owner && !NODES.includes(owner.name)) owner = owner.parent;
        if (owner !== node) return;
        const material = (o.material as THREE.MeshStandardMaterial).clone();
        material.emissive = AGENT.clone();
        material.emissiveIntensity = 0;
        if (material.transparent) material.depthWrite = false;
        o.material = material;
        o.castShadow = true;
        o.receiveShadow = !material.transparent;
        materials.push(material);
      });
      parts.set(name, { node, materials });
    }
    const size = parts.get("battery")?.node.userData.size_mm as number[] | undefined;
    const baked: [number, number, number] = size?.length === 3 ? [size[0] / 1000, size[1] / 1000, size[2] / 1000] : [0.068, 0.0155, 0.0067];
    return { root, parts, baked };
  }, [source]);

  useEffect(
    () => () => {
      for (const part of parts.values()) for (const m of part.materials) m.dispose();
    },
    [parts],
  );

  // The file holds the pack it was built with; a pack still being weighed is scaled to size.
  const [bl, bw, bh] = battery;
  const scale = useMemo(() => new THREE.Vector3(bw / baked[1], bh / baked[2], bl / baked[0]), [bl, bw, bh, baked]);
  useEffect(() => {
    const pack = parts.get("battery")?.node;
    if (pack) pack.scale.copy(scale);
    const strap = parts.get("battery_strap")?.node;
    const fits = Math.abs(scale.x - 1) < 0.02 && Math.abs(scale.y - 1) < 0.02 && Math.abs(scale.z - 1) < 0.02;
    if (strap) strap.visible = fits;
  }, [parts, scale]);

  const anchors = useMemo(() => {
    const out: { name: string; center: THREE.Vector3; radius: number }[] = [];
    for (const name of ["frame", "flight_controller", "battery", ...CORNERS.flatMap((c) => [`motor_${c}`, `propeller_${c}`])]) {
      const part = parts.get(name);
      if (!part) continue;
      const { center, radius } = bounds(root, part.node);
      out.push({ name, center, radius: name.startsWith("motor_") ? radius * 0.7 : radius });
    }
    const find = (n: string) => out.find((a) => a.name === n);
    const motor = find("motor_front_right");
    const prop = find("propeller_front_left");
    if (motor) out.push({ ...motor, name: "motors" });
    if (prop) out.push({ ...prop, name: "propellers" });
    return out;
    // The battery anchor follows the scaled pack.
  }, [root, parts, scale]);

  const specs = useMemo<PieceSpec[]>(
    () => [...parts].map(([key, part]) => ({ node: part.node, key, isBase: key === "frame", ...(PIECES[key] ?? { name: key, label: "" }) })),
    [parts],
  );
  const hovered = useExplodeHover((s) => (explodable ? s.key : null));

  const hl = (k: string) => highlight.has(k);
  const glow: [string[], boolean][] = [
    [["frame", "canopy"], hl("frame")],
    [CORNERS.map((c) => `motor_${c}`), hl("motors") || CORNERS.some((c) => hl(`motor_${c}`))],
    [CORNERS.map((c) => `propeller_${c}`), hl("propellers") || CORNERS.some((c) => hl(`propeller_${c}`))],
    [["flight_controller"], hl("flight_controller")],
    [["battery", "battery_strap"], hl("battery")],
  ];

  useFrame(({ clock }, dt) => {
    const pulse = 0.16 + 0.12 * Math.sin(clock.elapsedTime * 5);
    for (const [names, on] of glow) {
      const target = on ? pulse : 0;
      for (const name of names) {
        for (const m of parts.get(name)?.materials ?? []) m.emissiveIntensity += (target - m.emissiveIntensity) * 0.15;
      }
    }
    for (const m of (hovered && parts.get(hovered)?.materials) || []) m.emissiveIntensity = 0.3;
    if (!spin) return;
    for (const c of CORNERS) {
      const prop = parts.get(`propeller_${c}`)?.node;
      if (prop) prop.rotation.y += SPIN[c] * spin * dt;
    }
  });

  return (
    <group>
      {explodable ? (
        <ExplodeLayer root={root} specs={specs}>
          <primitive object={root} />
        </ExplodeLayer>
      ) : (
        <primitive object={root} />
      )}
      {anchors.map((a) => (
        <Anchor key={a.name} name={a.name} radius={a.radius} position={a.center} />
      ))}
    </group>
  );
}
