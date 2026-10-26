// Preview images for the parts panel, rendered here from each part's own 3D model (PR #113's
// GLBs in web/public/models/parts), so a new model never needs a picture made for it. One
// offscreen renderer works through a queue of the cards that scroll into view, one model per
// frame, in the studio's light and three-quarter view; finished images stay for the session.
import { useEffect, useSyncExternalStore } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

/** CSS pixels of a preview; it renders at twice that. */
const SIZE = 168;
const VIEW = new THREE.Vector3(0.75, 0.62, 0.95).normalize();

/** Model URL to image URL; "" when the model would not load. */
const images = new Map<string, string>();
const listeners = new Set<() => void>();
const queue: string[] = [];
let working = false;
let renderer: THREE.WebGLRenderer | null = null;
let environment: THREE.Texture | null = null;

function setup(): THREE.WebGLRenderer {
  if (renderer && !renderer.getContext().isContextLost()) return renderer;
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(2);
  renderer.setSize(SIZE, SIZE, false);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  const pmrem = new THREE.PMREMGenerator(renderer);
  environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();
  return renderer;
}

function dispose(root: THREE.Object3D) {
  root.traverse((o) => {
    if (!(o instanceof THREE.Mesh)) return;
    o.geometry.dispose();
    for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
      for (const value of Object.values(m)) if (value instanceof THREE.Texture) value.dispose();
      m.dispose();
    }
  });
}

async function render(url: string): Promise<string> {
  const gl = setup();
  const gltf = await new GLTFLoader().loadAsync(url);
  const root = gltf.scene;
  // Part models are millimetres with Z up, like FreeCAD; three.js is Y up.
  root.rotation.x = -Math.PI / 2;
  root.updateMatrixWorld(true);
  const sphere = new THREE.Box3().setFromObject(root).getBoundingSphere(new THREE.Sphere());
  const scene = new THREE.Scene();
  scene.environment = environment;
  scene.environmentIntensity = 0.8;
  scene.add(root, new THREE.HemisphereLight("#ffffff", "#cfcfc8", 0.9));
  const key = new THREE.DirectionalLight("#ffffff", 1.6);
  key.position.set(3, 6, 4);
  scene.add(key);
  const radius = sphere.radius || 1;
  const camera = new THREE.PerspectiveCamera(30, 1, radius / 100, radius * 100);
  camera.position.copy(sphere.center).addScaledVector(VIEW, (radius / Math.sin(THREE.MathUtils.degToRad(15))) * 1.04);
  camera.lookAt(sphere.center);
  gl.render(scene, camera);
  const image = gl.domElement.toDataURL("image/webp", 0.92);
  dispose(root);
  return image;
}

async function work() {
  if (working) return;
  working = true;
  while (queue.length) {
    const url = queue.shift()!;
    if (images.has(url)) continue;
    try {
      images.set(url, await render(url));
    } catch {
      images.set(url, "");
    }
    listeners.forEach((l) => l());
    // One model per frame keeps the studio smooth while the panel fills.
    await new Promise((r) => requestAnimationFrame(r));
  }
  working = false;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The preview of a part model once rendered (null until then, "" when it failed); `wanted` queues it. */
export function usePartThumb(url: string, wanted: boolean): string | null {
  const image = useSyncExternalStore(subscribe, () => images.get(url) ?? null);
  useEffect(() => {
    if (!wanted || images.has(url) || queue.includes(url)) return;
    queue.push(url);
    void work();
  }, [url, wanted]);
  return image;
}
