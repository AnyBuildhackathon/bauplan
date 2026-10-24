// Assembly fly-in: when a live `cad` event brings a whole assembly, every top-level body
// starts pushed out along the line from the assembly centre to its own centre and springs
// into place, 60 ms after the one before. Loads (see-through) fade in last.
import { useFrame } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { MOTION } from "../../lib/motion";

type Flyer = { node: THREE.Object3D; home: THREE.Vector3; from: THREE.Vector3; delay: number; fade: THREE.Material[] };

/** Overshooting ease-out, a cheap spring. */
const spring = (k: number) => 1 + 2.2 * Math.pow(k - 1, 3) + 1.2 * Math.pow(k - 1, 2);

export function useAssemblyFlyIn(root: THREE.Object3D, radius: number, play: boolean) {
  const flyers = useRef<Flyer[]>([]);
  const start = useRef(0);

  useEffect(() => {
    flyers.current = [];
    // A single mesh (a fallback block) has nothing to assemble: it just appears.
    const bodies = root.children.filter((c) => c.type !== "LineSegments");
    if (!play || bodies.length < 2) return;
    root.updateMatrixWorld(true);
    const centre = new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3());
    const toLocal = root.getWorldQuaternion(new THREE.Quaternion()).invert();
    const list: Flyer[] = [];
    let solid = 0;
    for (const node of bodies) {
      const mats: THREE.Material[] = [];
      node.traverse((o) => {
        if (o instanceof THREE.Mesh) mats.push(o.material as THREE.Material);
      });
      const load = mats.length > 0 && mats.every((m) => m.transparent);
      const own = new THREE.Box3().setFromObject(node).getCenter(new THREE.Vector3());
      const dir = own.sub(centre);
      if (dir.lengthSq() < 1e-9) dir.set(0, 1, 0);
      dir.normalize().applyQuaternion(toLocal);
      const home = node.position.clone();
      list.push({
        node,
        home,
        from: load ? home.clone() : home.clone().addScaledVector(dir, radius * 1.4),
        delay: load ? -1 : solid++ * MOTION.flyStagger,
        fade: load ? mats : [],
      });
    }
    // Loads come in after the last solid part has landed.
    for (const f of list) if (f.delay < 0) f.delay = solid * MOTION.flyStagger + MOTION.flyPart * 0.6;
    for (const f of list) {
      f.node.position.copy(f.from);
      f.fade.forEach((m) => {
        m.userData.opacity ??= m.opacity;
        m.opacity = 0;
      });
    }
    flyers.current = list;
    start.current = 0;
    return () => {
      // Never leave a part stranded mid-flight when the model changes.
      for (const f of list) {
        f.node.position.copy(f.home);
        f.fade.forEach((m) => (m.opacity = m.userData.opacity ?? m.opacity));
      }
    };
  }, [root, radius, play]);

  useFrame(({ clock }) => {
    const list = flyers.current;
    if (!list.length) return;
    if (!start.current) start.current = clock.elapsedTime;
    const t = clock.elapsedTime - start.current;
    let done = true;
    for (const f of list) {
      const k = Math.min(1, Math.max(0, (t - f.delay) / MOTION.flyPart));
      if (k < 1) done = false;
      if (f.fade.length) f.fade.forEach((m) => (m.opacity = (m.userData.opacity ?? 1) * k));
      else f.node.position.lerpVectors(f.from, f.home, spring(k));
    }
    if (done) flyers.current = [];
  });
}
