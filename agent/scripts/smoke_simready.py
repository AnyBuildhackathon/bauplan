"""Checks SimReady objects against the real dataset (network): the banana in the pan, the license gate, the cache, the GLB.

    cd agent && uv run --extra simready python scripts/smoke_simready.py

It fetches the banana and the frying pan from Hugging Face (about 3 MB into the SimReady cache),
drops the banana 80 mm above the pan's centre in MuJoCo for 3 s, once with the pan as one
convex hull (the banana lies on the hull's lid, above 25 mm) and once decomposed by CoACD (the
banana lies in the pan, under 15 mm). Then it checks that a second fetch comes from the cache in
under a second, that a package declaring another license is refused (the banana's own packaging
file with its license changed, in a local mirror), and that the GLB has its textures in metres.
PAI_SIMREADY_CACHE points the cache somewhere else; the first run of CoACD on the pan takes 20 to
40 s, later runs read its parts from the cache.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path

import mujoco
import numpy as np

from pai_agent.simready import convert, fetch

BANANA, PAN = "food_produce_banana_a01", "kitchenware_pan_a01"
failures: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("ok   " if condition else "FAIL ") + message, flush=True)
    if not condition:
        failures.append(message)


def banana_low_point(pan_collision: str) -> tuple[float, dict]:
    """The banana's lowest point (metres) after 3 s, dropped from 80 mm above the fixed pan's centre."""

    pan = convert.to_mjcf(PAN, name="pan", collision=pan_collision, free=False)
    banana = convert.to_mjcf(BANANA, name="banana", pos=(0.0, 0.0, 0.08))
    xml, assets = convert.scene_xml([pan, banana])
    model = mujoco.MjModel.from_xml_string(xml, assets)
    data = mujoco.MjData(model)
    while data.time < 3.0:
        mujoco.mj_step(model, data)
    body = model.body("banana").id
    visual = next(g for g in range(model.ngeom) if model.geom_bodyid[g] == body and model.geom_group[g] == 2)
    mesh = model.geom_dataid[visual]
    vertices = model.mesh_vert[model.mesh_vertadr[mesh]:model.mesh_vertadr[mesh] + model.mesh_vertnum[mesh]]
    world = vertices @ data.geom_xmat[visual].reshape(3, 3).T + data.geom_xpos[visual]
    return float(world[:, 2].min()), pan.meta["collision"]


def glb_json(path: Path) -> dict:
    data = path.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20:20 + length])


def main() -> int:
    print(f"cache: {fetch.cache_root()}", flush=True)
    for asset in (BANANA, PAN):
        started = time.perf_counter()
        package = fetch.fetch(asset)
        print(f"     {asset}: {len(package.files)} files verified in {time.perf_counter() - started:.1f} s", flush=True)
        started = time.perf_counter()
        fetch.fetch(asset)
        again = time.perf_counter() - started
        check(again < 1.0, f"second fetch of {asset} from the cache in {again * 1000:.1f} ms")

    low, info = banana_low_point("hull")
    check(info["method"] == "hull" and low > 0.025, f"pan as one convex hull: the banana rests {low * 1000:.1f} mm up, on the hull's lid (above 25 mm)")
    low, info = banana_low_point("auto")
    check(
        info["method"] == "coacd" and low < 0.015,
        f"pan decomposed by CoACD into {info['parts']} parts ({info.get('seconds', 0):.1f} s, cavity {info['cavity_mm']} mm): the banana rests {low * 1000:.1f} mm up, in the pan (under 15 mm)",
    )

    # The banana's real package with only its declared license changed, fetched into an empty cache.
    scratch = Path(tempfile.mkdtemp(prefix="simready-license-"))
    cache = os.environ.get("PAI_SIMREADY_CACHE")
    try:
        copy = scratch / "mirror" / BANANA
        shutil.copytree(fetch.package_dir(BANANA), copy)
        packaging = copy / fetch.PACKAGING
        declared = json.loads(packaging.read_text(encoding="utf-8"))
        packaging.write_text(json.dumps({**declared, "license": "CC-BY-NC-4.0"}), encoding="utf-8")
        os.environ["PAI_SIMREADY_CACHE"] = str(scratch / "cache")
        try:
            fetch.fetch(BANANA, source=fetch.MirrorSource(scratch / "mirror"))
            check(False, "a package declaring CC-BY-NC-4.0 is refused")
        except fetch.LicenseError as exc:
            check(not fetch.package_dir(BANANA).exists(), f"a package declaring CC-BY-NC-4.0 is refused: {exc}")
    finally:
        if cache is None:
            os.environ.pop("PAI_SIMREADY_CACHE", None)
        else:
            os.environ["PAI_SIMREADY_CACHE"] = cache
        shutil.rmtree(scratch, ignore_errors=True)

    path, info = convert.to_glb(BANANA)
    gltf = glb_json(path)
    low = np.min([gltf["accessors"][p["attributes"]["POSITION"]]["min"] for m in gltf["meshes"] for p in m["primitives"]], axis=0)
    high = np.max([gltf["accessors"][p["attributes"]["POSITION"]]["max"] for m in gltf["meshes"] for p in m["primitives"]], axis=0)
    size = [round(float(v), 4) for v in high - low]
    textures = [m.get("pbrMetallicRoughness", {}).get("baseColorTexture") is not None and "normalTexture" in m for m in gltf["materials"]]
    check(info["textured"] and all(textures) and len(gltf.get("images", [])) >= 2, f"GLB through {info['method']} with base colour, metallic-roughness and normal textures ({path.stat().st_size // 1024} kB)")
    check(np.allclose(size, [0.116, 0.0316, 0.1622], atol=0.002), f"GLB in metres, Y up: {size} m")
    check("CC BY 4.0" in gltf["asset"].get("copyright", ""), "GLB carries the CC BY 4.0 attribution")
    thumb = fetch.thumbnail(BANANA)
    check(thumb.is_file() and thumb.suffix == ".webp", f"thumbnail cached as {thumb.name}")
    print("all checks passed" if not failures else f"{len(failures)} check(s) failed", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
