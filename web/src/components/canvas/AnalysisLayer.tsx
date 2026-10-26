// The surface checks over the live model (Model and CAD tabs): each checked part's sampled surface
// from analysis.glb lies on its own node of the model, so it follows the explode, the hidden parts
// and the camera, coloured by the check the view bar's Surface menu picked against its limit, while
// the part's own faces step aside and its edges stay on top. With the Select tool a click reads the
// value under the pointer into the legend (the picked spot, events/analysis.ts).
import { useLoader, useThree } from "@react-three/fiber";
import { Component, Suspense, useEffect, useLayoutEffect, useMemo, type ReactNode } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { isCritical, isCurrent, limitOf, shade, SHADES, useAnalysisLayer } from "../../events/analysis";
import { useSession } from "../../events/store";
import type { AnalysisCheck, AnalysisCheckInfo } from "../../events/types";
import { assetUrl } from "../../lib/api";
import { useUi } from "../../lib/ui";
import { keptByCut } from "../studio/frame";

/** A layer that cannot load leaves the model as it is. */
class Quiet extends Component<{ children: ReactNode; resetKey: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.failed) this.setState({ failed: false });
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

interface Layer {
  mesh: THREE.Mesh;
  target: THREE.Object3D;
  part: string;
  partId: string | null;
  /** From the node's frame to the build's mm, Z up. */
  toMm: THREE.Matrix4;
  /** Each triangle's area in mm². */
  areas: Float32Array;
}

function triangleAreas(geometry: THREE.BufferGeometry, mmPerUnit: number): Float32Array {
  const position = geometry.getAttribute("position");
  const out = new Float32Array(position.count / 3);
  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  for (let i = 0; i < out.length; i++) {
    a.fromBufferAttribute(position, 3 * i);
    b.fromBufferAttribute(position, 3 * i + 1).sub(a);
    c.fromBufferAttribute(position, 3 * i + 2).sub(a);
    out[i] = (b.cross(c).length() / 2) * mmPerUnit * mmPerUnit;
  }
  return out;
}

/** The colour layer of the current surface check on `root`, the model the studio shows from `modelUrl`. */
export function AnalysisLayer({ root, modelUrl }: { root: THREE.Object3D; modelUrl: string }) {
  const analysis = useSession((s) => s.analysis);
  const check = useAnalysisLayer((s) => s.check);
  const info = check ? analysis?.checks[check] : undefined;
  const url = assetUrl(analysis?.glb_url ?? null);
  if (!check || !info || !url || !isCurrent(analysis, modelUrl)) return null;
  return (
    <Quiet resetKey={url}>
      <Suspense fallback={null}>
        <Overlay key={url} root={root} url={url} check={check} info={info} />
      </Suspense>
    </Quiet>
  );
}

function Overlay({ root, url, check, info }: { root: THREE.Object3D; url: string; check: AnalysisCheck; info: AnalysisCheckInfo }) {
  const gltf = useLoader(GLTFLoader, url);
  const limit = useAnalysisLayer((s) => limitOf(check, info, s.limits));
  const { camera, gl, raycaster } = useThree();

  // One mesh per checked part, each on the model node of the same name.
  const layers = useMemo(() => {
    const out: Layer[] = [];
    gltf.scene.traverse((o) => {
      if (!(o instanceof THREE.Mesh)) return;
      const target = root.getObjectByName(o.name);
      if (!target) return;
      const geometry = (o.geometry as THREE.BufferGeometry).clone();
      geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(geometry.getAttribute("position").count * 3), 3));
      // The faces sit a hair behind the part's edges, so the CAD tab's lines stay crisp on the colours.
      const material = new THREE.MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 0.72, metalness: 0, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.name = o.name + " surface check";
      mesh.userData.analysisLayer = true;
      mesh.castShadow = true;
      const toMm = new THREE.Matrix4();
      const rows = o.userData.to_mm as number[] | undefined;
      if (rows?.length === 16) toMm.set(...(rows as Parameters<THREE.Matrix4["set"]>));
      const areas = triangleAreas(geometry, Number(o.userData.mm_per_unit) || 1);
      out.push({ mesh, target, part: o.name, partId: (o.userData.part_id as string | undefined) ?? null, toMm, areas });
    });
    return out;
  }, [gltf, root]);

  // The layer goes onto its parts and their own faces step aside; both come back when it goes.
  useLayoutEffect(() => {
    const restore: (() => void)[] = [];
    for (const layer of layers) {
      const own = layer.target instanceof THREE.Mesh ? [layer.target] : layer.target.children.filter((c): c is THREE.Mesh => c instanceof THREE.Mesh && !c.userData.analysisLayer);
      for (const mesh of own) {
        const materials = (Array.isArray(mesh.material) ? mesh.material : [mesh.material]) as THREE.Material[];
        const shown = materials.map((m) => m.visible);
        materials.forEach((m) => (m.visible = false));
        restore.push(() => materials.forEach((m, i) => (m.visible = shown[i])));
      }
      layer.target.add(layer.mesh);
      restore.push(() => layer.target.remove(layer.mesh));
    }
    return () => restore.forEach((undo) => undo());
  }, [layers]);
  useEffect(
    () => () =>
      layers.forEach((layer) => {
        layer.mesh.geometry.dispose();
        (layer.mesh.material as THREE.Material).dispose();
      }),
    [layers],
  );
  // Every check run has its own URL: the loader's cache lets go of this one when the layer goes.
  useEffect(() => () => useLoader.clear(GLTFLoader, url), [url]);

  // Every corner takes its triangle's colour for this check and limit; the legend gets the critical area.
  useEffect(() => {
    const colour = new THREE.Color();
    let mm2 = 0;
    for (const layer of layers) {
      const geometry = layer.mesh.geometry;
      const values = geometry.getAttribute(info.attribute.toLowerCase());
      const colours = geometry.getAttribute("color") as THREE.BufferAttribute;
      for (let i = 0; i < colours.count; i++) {
        // A part this check did not measure keeps the plain grey.
        if (values) shade(check, values.getX(i), info, limit, colour);
        else colour.set(SHADES.plain);
        colours.setXYZ(i, colour.r, colour.g, colour.b);
        if (values && i % 3 === 0 && isCritical(check, values.getX(i), info, limit)) mm2 += layer.areas[i / 3];
      }
      colours.needsUpdate = true;
    }
    useAnalysisLayer.setState({ area: { check, limit, mm2 } });
  }, [layers, check, info, limit]);

  // A click with the Select tool, not a drag of the camera, reads the value under the pointer.
  useEffect(() => {
    const el = gl.domElement;
    let down: { x: number; y: number } | null = null;
    const onDown = (e: PointerEvent) => {
      if (e.button === 0) down = { x: e.clientX, y: e.clientY };
    };
    const onUp = (e: PointerEvent) => {
      const click = down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5;
      down = null;
      if (!click || useUi.getState().tool !== "select") return;
      const r = el.getBoundingClientRect();
      raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
      const shown = layers.filter((layer) => visible(layer.mesh));
      // With the section on, what the cut took away is not under the pointer.
      const hit = raycaster.intersectObjects(shown.map((layer) => layer.mesh), false).find(keptByCut);
      const layer = hit && shown.find((l) => l.mesh === hit.object);
      const values = layer?.mesh.geometry.getAttribute(info.attribute.toLowerCase());
      if (!hit || !layer || !values || hit.faceIndex == null) return;
      const value = values.getX(hit.faceIndex * 3);
      const at = layer.mesh.worldToLocal(hit.point.clone()).applyMatrix4(layer.toMm);
      const round = (v: number) => Math.round(v * 10) / 10;
      useAnalysisLayer.getState().pick({ check, part: layer.part, partId: layer.partId, value, atMm: [round(at.x), round(at.y), round(at.z)], critical: isCritical(check, value, info, limit) });
    };
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointerup", onUp);
    return () => {
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointerup", onUp);
    };
  }, [layers, gl, camera, raycaster, check, info, limit]);

  return null;
}

function visible(o: THREE.Object3D | null): boolean {
  for (; o; o = o.parent) if (!o.visible) return false;
  return true;
}
