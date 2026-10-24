// Projects named 3D anchors to screen space every frame, so the pointer and the
// drawings stay glued to a part while the drone rotates or flies.
import { useFrame, useThree } from "@react-three/fiber";
import { createContext, useContext, useEffect, useId, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { dropAnchors, writeAnchor } from "../../lib/targets";

interface AnchorEntry {
  object: THREE.Object3D;
  radius: number;
}

type AnchorMap = Map<string, AnchorEntry>;

const AnchorContext = createContext<AnchorMap | null>(null);

export function useAnchor(name: string, radius: number) {
  const map = useContext(AnchorContext);
  const ref = useRef<THREE.Group>(null);
  useEffect(() => {
    if (!map || !ref.current) return;
    map.set(name, { object: ref.current, radius });
    return () => {
      map.delete(name);
    };
  }, [map, name, radius]);
  return ref;
}

const world = new THREE.Vector3();
const edge = new THREE.Vector3();
const right = new THREE.Vector3();

function Projector({ map, owner }: { map: AnchorMap; owner: string }) {
  const { camera, gl } = useThree();
  useEffect(() => () => dropAnchors(owner), [owner]);
  useFrame(() => {
    const rect = gl.domElement.getBoundingClientRect();
    const shown = rect.width > 0 && rect.height > 0 && gl.domElement.isConnected;
    right.setFromMatrixColumn(camera.matrixWorld, 0).normalize();
    for (const [name, { object, radius }] of map) {
      object.getWorldPosition(world);
      const worldScale = object.getWorldScale(edge).x;
      edge.copy(world).addScaledVector(right, radius * worldScale);
      world.project(camera);
      edge.project(camera);
      const x = rect.left + ((world.x + 1) / 2) * rect.width;
      const y = rect.top + ((1 - world.y) / 2) * rect.height;
      const ex = rect.left + ((edge.x + 1) / 2) * rect.width;
      const ey = rect.top + ((1 - edge.y) / 2) * rect.height;
      const inside = x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
      writeAnchor(name, {
        x,
        y,
        r: Math.max(10, Math.hypot(ex - x, ey - y)),
        visible: shown && inside && world.z > -1 && world.z < 1,
        clip: rect,
        owner,
      });
    }
  });
  return null;
}

/** Wrap a scene's content; with `primary` its anchors become the pointer's targets. */
export function AnchorScope({ primary, children }: { primary: boolean; children: ReactNode }) {
  const map = useMemo<AnchorMap>(() => new Map(), []);
  const owner = useId();
  return (
    <AnchorContext.Provider value={map}>
      {children}
      {primary && <Projector map={map} owner={owner} />}
    </AnchorContext.Provider>
  );
}
