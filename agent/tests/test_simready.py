"""SimReady objects, offline: the license gate, the verified fetch and its cache, USD to MJCF and GLB,
the container decomposition, search, the scene_object tool and the HTTP endpoints.

Run with: cd agent && uv run --extra simready --with pytest pytest tests/test_simready.py

No network and no keys: the packages come from a local mirror the tests build from
tests/fixtures/simready (two small text USD packages packed and hashed the way NVIDIA packs them:
a tray, a container in metres with Z up, and a block in centimetres with Y up), and the cache and
the index live in the test's temporary directory. Without the simready extra (usd-core, trimesh,
coacd) the conversion tests skip; the license, cache, search and endpoint tests still run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import struct
import time
from pathlib import Path

import pytest

from pai_agent import simready
from pai_agent.simready import fetch, index

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "simready"
TRAY, BLOCK, CHEST = "test_kitchenware_tray_a01", "test_toy_block_a01", "test_storage_chest_a01"
# Only in the index, as a package too large to fetch on first use.
BIG = "test_crate_big_a01"
LICENSE_TEXT = (
    "Attribution 4.0 International\n\n"
    "Creative Commons Attribution 4.0 International Public License\n\n"
    "(A shortened stand-in for the legal code every SimReady package ships.)\n"
)

needs_usd = pytest.mark.skipif(bool(simready.missing("convert")), reason="needs the simready extra (usd-core, trimesh)")
needs_coacd = pytest.mark.skipif(bool(simready.missing("convert", "decompose")), reason="needs the simready extra (coacd)")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pack(root: Path, licenses: dict[str, str] | None = None) -> Path:
    """A mirror laid out like the dataset: the fixture files, generated PNGs, the bill of materials, the packaging file."""

    from PIL import Image

    for source in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        asset = source.name
        dest = root / asset
        shutil.copytree(source, dest)
        usd = dest / "simready_usd"
        root_name = next(p.name for p in usd.iterdir() if p.suffix in (".usd", ".usda"))
        thumbs = usd / ".thumbs" / "256x256"
        thumbs.mkdir(parents=True)
        Image.new("RGBA", (512, 512), (230, 160, 40, 255)).save(thumbs / f"{root_name}_transparent.png")
        Image.new("RGB", (512, 512), (20, 20, 20)).save(thumbs / f"{root_name}.png")
        textures = usd / "Textures"
        textures.mkdir()
        image = Image.new("RGB", (2, 1))
        image.putpixel((0, 0), (0, 200, 0))
        image.putpixel((1, 0), (0, 0, 200))
        image.save(textures / "t_tray_alb.png")
        # A real package also carries MDL sources and texture previews; a fetch never needs them.
        (usd / "source_assets").mkdir()
        (usd / "source_assets" / "OmniPBR.mdl").write_text("mdl 1.6;\n", encoding="utf-8")
        (textures / ".thumbs").mkdir()
        image.save(textures / ".thumbs" / "t_tray_alb.png.png")
        items = [
            {"relative_path": f.relative_to(dest).as_posix(), "size": f.stat().st_size, "hash": {"sha256": _sha(f)}}
            for f in sorted(usd.rglob("*"))
            if f.is_file()
        ]
        meta = dest / ".metadata"
        meta.mkdir()
        bom = meta / "com.nvidia.simready.packaging.bom.json"
        bom.write_text(json.dumps({"format_version": "1.0", "items": items}, indent=2), encoding="utf-8")
        (meta / "com.nvidia.simready.root_usds.json").write_text(json.dumps({"format_version": "1.0", "entries": [f"simready_usd/{root_name}"]}), encoding="utf-8")
        (meta / "LICENSE.txt").write_text(LICENSE_TEXT, encoding="utf-8")
        packaging = {
            "format_version": "1.0",
            "package_id": f"simready.test.{asset}",
            "license": (licenses or {}).get(asset, "CC-BY-4.0"),
            "metadata": [{"name": bom.name, "hash": {"sha256": _sha(bom)}}],
        }
        (dest / "com.nvidia.simready.packaging.json").write_text(json.dumps(packaging, indent=2), encoding="utf-8")
    return root


def write_index(mirror: Path, path: Path) -> Path:
    rows = []
    for asset, title, cls, size, mass in ((TRAY, "Tray", "tray", [120.0, 80.0, 40.0], 210.0), (BLOCK, "Toy block", "toy block", [40.0, 40.0, 40.0], 50.0)):
        bom = json.loads((mirror / asset / fetch.BOM).read_text(encoding="utf-8"))["items"]
        thumb = next(i for i in bom if i["relative_path"].endswith("_transparent.png"))
        rows.append(
            {
                "id": asset,
                "title": title,
                "category": "Test",
                "class": cls,
                "doc": "a test object",
                "size_mm": size,
                "mass_g": mass,
                "thumb": [thumb["relative_path"], thumb["size"], thumb["hash"]["sha256"]],
                "download_mb": 0.1,
            }
        )
    rows.append({"id": BIG, "title": "Crate", "category": "Test", "class": "crate", "doc": "", "size_mm": [600.0, 400.0, 300.0], "mass_g": 2000.0, "thumb": None, "download_mb": 1500.0})
    path.write_text(json.dumps({"dataset": simready.REPO_ID, "revision": simready.REVISION, "objects": rows}), encoding="utf-8")
    return path


class Counting(fetch.MirrorSource):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.calls: list[str] = []

    def get(self, path: str, dest: Path) -> None:
        self.calls.append(path)
        super().get(path, dest)


@pytest.fixture
def env(tmp_path, monkeypatch):
    mirror = pack(tmp_path / "mirror")
    monkeypatch.setenv("PAI_SIMREADY_MIRROR", str(mirror))
    monkeypatch.setenv("PAI_SIMREADY_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("PAI_SIMREADY_INDEX", str(write_index(mirror, tmp_path / "index.json")))
    return mirror


def _no_partials(tmp_path: Path) -> list[str]:
    return [p.name for p in (tmp_path / "cache").rglob("*") if ".partial" in p.name]


# ---------------------------------------------------------------- fetch: license, hashes, cache


def test_fetch_verifies_every_file_and_the_second_fetch_is_the_cache(env, tmp_path):
    source = Counting(env)
    package = fetch.fetch(TRAY, source=source)
    files = {p.relative_to(package.folder).as_posix() for p in package.folder.rglob("*") if p.is_file()}
    assert "simready_usd/sm_test_kitchenware_tray_a01_01.usda" in files and "simready_usd/payloads/base.usda" in files
    assert "simready_usd/Textures/t_tray_alb.png" in files and ".metadata/LICENSE.txt" in files
    # No MDL sources, no texture previews, and one thumbnail of the two renders: the transparent one.
    assert not any(f.startswith("simready_usd/source_assets/") or "/Textures/.thumbs/" in f for f in files)
    assert package.thumbnail == "simready_usd/.thumbs/256x256/sm_test_kitchenware_tray_a01_01.usda_transparent.png"
    assert "simready_usd/.thumbs/256x256/sm_test_kitchenware_tray_a01_01.usda.png" not in files
    assert package.license == "CC-BY-4.0" and package.root == "simready_usd/sm_test_kitchenware_tray_a01_01.usda"
    assert source.calls[0] == f"{TRAY}/{fetch.PACKAGING}", "the license is read before anything else"

    again = Counting(env)
    started = time.perf_counter()
    cached = fetch.fetch(TRAY, source=again)
    assert time.perf_counter() - started < 1.0
    assert again.calls == [], "a cached package needs no download"
    assert cached.folder == package.folder and cached.digest() == package.digest()
    assert _no_partials(tmp_path) == []


def test_a_package_under_another_license_is_refused_before_its_files_are_fetched(tmp_path, monkeypatch):
    mirror = pack(tmp_path / "mirror", licenses={BLOCK: "CC-BY-NC-4.0"})
    monkeypatch.setenv("PAI_SIMREADY_CACHE", str(tmp_path / "cache"))
    source = Counting(mirror)
    with pytest.raises(fetch.LicenseError, match="CC-BY-NC-4.0"):
        fetch.fetch(BLOCK, source=source)
    assert source.calls == [f"{BLOCK}/{fetch.PACKAGING}"]
    assert not fetch.package_dir(BLOCK).exists() and _no_partials(tmp_path) == []
    # The same spelling NVIDIA's USD metadata uses ("CC-BY 4.0") reads as CC BY 4.0; ShareAlike does not.
    assert fetch.normalize_license("CC-BY 4.0") == fetch.normalize_license("cc by 4.0") == "CC-BY-4.0"
    assert fetch.normalize_license("CC-BY-SA-4.0") != "CC-BY-4.0"


def test_a_license_text_that_is_not_cc_by_is_refused(env):
    (env / TRAY / fetch.LICENSE_TEXT).write_text("Attribution-NonCommercial 4.0 International\n", encoding="utf-8")
    with pytest.raises(fetch.LicenseError):
        fetch.fetch(TRAY)


def test_a_changed_file_is_refused_and_nothing_half_written_stays(env, tmp_path):
    texture = env / TRAY / "simready_usd" / "Textures" / "t_tray_alb.png"
    texture.write_bytes(texture.read_bytes() + b"x")
    with pytest.raises(fetch.IntegrityError, match="t_tray_alb.png"):
        fetch.fetch(TRAY)
    assert fetch.cached_package(TRAY) is None and _no_partials(tmp_path) == []
    assert not [p for p in (tmp_path / "cache").rglob("*") if p.is_dir() and TRAY in p.name]


def test_a_changed_bill_of_materials_is_refused(env):
    bom = env / TRAY / fetch.BOM
    bom.write_text(bom.read_text(encoding="utf-8").replace('"format_version": "1.0"', '"format_version": "1.1"'), encoding="utf-8")
    with pytest.raises(fetch.IntegrityError, match="bill of materials"):
        fetch.fetch(TRAY)


def test_the_hub_source_waits_out_rate_limits_retries_cut_bodies_and_keeps_the_token_home(tmp_path, monkeypatch):
    """Hugging Face's resolve endpoint, played by a local server: 429 first, then a body cut short, then the file via a redirect."""

    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    body = b"0123456789" * 100
    seen: list[tuple[str, str | None]] = []
    answers = iter(("rate-limited", "cut-short", "redirect"))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def do_GET(self) -> None:
            seen.append((self.path, self.headers.get("Authorization")))
            if self.path.endswith("/missing.bin"):
                self.send_response(404)
                self.end_headers()
                return
            if self.path.startswith("/cdn/"):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            answer = next(answers)
            if answer == "rate-limited":
                self.send_response(429)
                self.send_header("RateLimit", '"resolvers";r=0;t=0')
                self.end_headers()
            elif answer == "cut-short":
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body[:300])
                self.close_connection = True
            else:
                self.send_response(302)
                self.send_header("Location", "/cdn/file.bin")
                self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("HF_ENDPOINT", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("HF_TOKEN", "hf_test_token")
        monkeypatch.setattr(fetch.time, "sleep", lambda seconds: None)
        source = fetch.HubSource()
        source.get("asset_a01/simready_usd/file.bin", tmp_path / "file.bin")
        assert (tmp_path / "file.bin").read_bytes() == body
        resolve = f"/datasets/{simready.REPO_ID}/resolve/{simready.REVISION}/asset_a01/simready_usd/file.bin"
        assert [path for path, _ in seen] == [resolve, resolve, resolve, "/cdn/file.bin"]
        # The token goes to Hugging Face, never along the redirect to the CDN.
        assert [auth for _, auth in seen] == ["Bearer hf_test_token"] * 3 + [None]
        with pytest.raises(fetch.FetchError, match="is not in"):
            source.get("asset_a01/missing.bin", tmp_path / "missing.bin")
        assert not list(tmp_path.glob("*.download-*")), "no half-written download stays"
    finally:
        server.shutdown()
        server.server_close()


def test_ids_and_package_paths_stay_inside_the_cache():
    for bad in ("../etc", "a/b", "", "x" * 200, ".hidden"):
        with pytest.raises(fetch.SimReadyError):
            fetch.check_id(bad)
    for bad in ("../../.ssh/id_rsa", "/etc/passwd", "simready_usd/../../x", "a\\b"):
        with pytest.raises(fetch.IntegrityError):
            fetch.safe_relative(bad)


# ---------------------------------------------------------------- reading the USD


@needs_usd
def test_units_up_axis_mass_and_semantics_come_out_in_si(env):
    from pai_agent.simready import convert

    _, meta = convert.prepare(fetch.fetch(BLOCK))
    # A 4 cm block in centimetres with Y up: 40 mm, standing on Z = 0 with Z up.
    assert meta["size_mm"] == [40.0, 40.0, 40.0]
    assert meta["bbox_m"][0][2] == pytest.approx(0.0, abs=1e-9) and meta["bbox_m"][1][2] == pytest.approx(0.04)
    assert meta["mass_kg"] == pytest.approx(0.05)
    assert meta["com_m"] == pytest.approx([0.0, 0.0, 0.02], abs=1e-9)
    # The rigid body's MassAPI wins; 0.1333 kg cm2 is 1.333e-5 kg m2.
    inertia = meta["inertia_kg_m2"]
    assert [inertia[i][i] for i in range(3)] == pytest.approx([1.3333334e-5] * 3, rel=1e-5)
    assert "rigid body" in meta["mass_source"]
    assert meta["wikidata"] == {"class": "toy block", "qcode": "Q1435765"}
    assert meta["groups"][0]["friction"] == pytest.approx(0.8), "dynamic friction, the lower coefficient"
    assert meta["grasps"] == [{"id": "1_1", "pos": pytest.approx([0.0, 0.0, 0.04], abs=1e-9)}]
    assert meta["visuals"][0]["rgba"] == pytest.approx([0.2, 0.4, 0.9, 1.0], abs=1e-3)
    assert meta["cavity_mm"] == 0.0


@needs_usd
def test_the_mujoco_variant_is_read_and_each_material_keeps_its_colour(env):
    from pai_agent.simready import convert

    _, meta = convert.prepare(fetch.fetch(TRAY))
    # The PhysX variant is the default selection and says 9.99 kg; the MuJoCo variant says 0.21 kg.
    assert meta["mass_kg"] == pytest.approx(0.21) and meta["maxhullvert"] == 128
    assert meta["size_mm"] == [120.0, 80.0, 40.0]
    assert meta["groups"][0]["friction"] == pytest.approx(0.45)
    colours = sorted(tuple(v["rgba"]) for v in meta["visuals"])
    # The outside's constant red, and the inside's texture (green where its texture coordinates point).
    assert colours == [pytest.approx((0.0, 0.784, 0.0, 1.0), abs=1e-3), pytest.approx((0.8, 0.1, 0.1, 1.0), abs=1e-3)]
    assert [g["id"] for g in meta["grasps"]] == ["1_1", "1_2"]
    # The tray holds water 36 mm deep over most of its box: a container.
    assert meta["cavity_mm"] == pytest.approx(36.0, abs=1.0) and meta["cavity_share"] > 0.5


@needs_usd
def test_several_rigid_bodies_add_up_into_one(env):
    from pai_agent.simready import convert

    _, meta = convert.prepare(fetch.fetch(CHEST))
    # 1 kg at x = -50 mm and 3 kg at x = +50 mm, each 0.001 kg m2 about its own centre.
    assert meta["mass_kg"] == pytest.approx(4.0)
    assert meta["com_m"] == pytest.approx([0.025, 0.0, 0.02], abs=1e-9)
    inertia = meta["inertia_kg_m2"]
    assert [inertia[i][i] for i in range(3)] == pytest.approx([0.002, 0.0095, 0.0095], rel=1e-6)
    assert "2 rigid bodies" in meta["mass_source"] and any("2 rigid bodies merged" in w for w in meta["warnings"])
    assert meta["size_mm"] == [140.0, 40.0, 40.0] and len(meta["groups"][0]["hulls"]) == 2


@needs_usd
def test_a_convex_object_becomes_one_hull_that_mujoco_compiles_with_the_usd_mass(env):
    import mujoco

    from pai_agent.simready import convert

    body = convert.to_mjcf(BLOCK, name="block")
    assert body.meta["collision"]["method"] == "hull" and body.meta["collision"]["parts"] == 1
    model = mujoco.MjModel.from_xml_string(body.standalone(), body.assets())
    assert model.body("block").mass[0] == pytest.approx(0.05)
    assert model.body("block").ipos == pytest.approx([0.0, 0.0, 0.02], abs=1e-6)
    collide = [g for g in range(model.ngeom) if model.geom_contype[g]]
    assert len(collide) == 1 and model.geom_friction[collide[0]][0] == pytest.approx(0.8)
    assert model.nsite == 1 and model.njnt == 1, "a grasp site and a free joint"
    assert "by NVIDIA" in body.standalone() and "CC BY 4.0" in body.standalone()
    stl = next(path for name, path in body.files.items() if "hull" in name)
    assert b"CC BY 4.0" in stl.read_bytes()[:80], "the STL header carries the attribution"


def _drop(container, block_xml) -> float:
    """Lowest point of the block after 3 s, dropped from 10 cm onto the fixed container."""

    import mujoco
    import numpy as np

    from pai_agent.simready import convert

    xml, assets = convert.scene_xml([container, block_xml])
    model = mujoco.MjModel.from_xml_string(xml, assets)
    data = mujoco.MjData(model)
    while data.time < 3.0:
        mujoco.mj_step(model, data)
    visual = next(g for g in range(model.ngeom) if model.geom_bodyid[g] == model.body("block").id and model.geom_group[g] == 2)
    mesh = model.geom_dataid[visual]
    vertices = model.mesh_vert[model.mesh_vertadr[mesh]:model.mesh_vertadr[mesh] + model.mesh_vertnum[mesh]]
    world = vertices @ data.geom_xmat[visual].reshape(3, 3).T + data.geom_xpos[visual]
    return float(np.min(world[:, 2]))


@needs_coacd
def test_a_container_is_decomposed_so_a_dropped_block_lands_inside(env):
    from pai_agent.simready import convert

    block = convert.to_mjcf(BLOCK, name="block", pos=(0.0, 0.0, 0.1))
    hull = convert.to_mjcf(TRAY, name="tray", collision="hull", free=False)
    auto = convert.to_mjcf(TRAY, name="tray", free=False)
    assert auto.meta["collision"]["method"] == "coacd" and auto.meta["collision"]["parts"] >= 3
    assert "CoACD" in " ".join(auto.meta["changes"]) and "CoACD" in auto.meta["attribution"]
    # One hull is a lid over the cavity: the block stays on top, at the rim (40 mm).
    assert _drop(hull, block) > 0.035
    # Convex parts follow the walls: the block reaches the floor of the tray (4 mm).
    assert _drop(auto, block) < 0.012


@needs_usd
def test_a_decomposition_that_fails_falls_back_to_hulls_with_a_warning(env, monkeypatch):
    import subprocess

    from pai_agent.simready import convert

    def too_slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1.0)

    monkeypatch.setattr(convert.subprocess, "run", too_slow)
    body = convert.to_mjcf(TRAY, name="tray", collision="decompose")
    assert body.meta["collision"]["method"] == "hull"
    assert any("longer than" in w and "lid" in w for w in body.meta["warnings"])


# ---------------------------------------------------------------- GLB


def _glb(path: Path) -> dict:
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20:20 + length])


def _png_size(path: Path, gltf: dict, image: dict) -> tuple[int, int]:
    """Width and height of a PNG embedded in the GLB's binary chunk."""

    data = path.read_bytes()
    json_length = struct.unpack_from("<I", data, 12)[0]
    binary = data[20 + json_length + 8:]
    view = gltf["bufferViews"][image["bufferView"]]
    png = binary[view.get("byteOffset", 0):view.get("byteOffset", 0) + view["byteLength"]]
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])


def _extent(gltf: dict) -> list[float]:
    low = [min(gltf["accessors"][p["attributes"]["POSITION"]]["min"][i] for m in gltf["meshes"] for p in m["primitives"]) for i in range(3)]
    high = [max(gltf["accessors"][p["attributes"]["POSITION"]]["max"][i] for m in gltf["meshes"] for p in m["primitives"]) for i in range(3)]
    return [top - bottom for top, bottom in zip(high, low)]


@needs_usd
def test_glb_through_blender_has_its_textures_and_metres(env, monkeypatch):
    from pai_agent.simready import convert
    from pai_agent.tools.blender import find_blender

    if not find_blender():
        pytest.skip("Blender is not installed")
    # A texture over the limit is scaled down: here the 2 x 1 px texture against a 1 px limit.
    monkeypatch.setattr(convert, "GLB_TEXTURE_PX", 1)
    path, info = convert.to_glb(TRAY)
    gltf = _glb(path)
    assert info["method"] == "blender" and info["textured"] is True
    assert gltf["images"] and any("baseColorTexture" in m.get("pbrMetallicRoughness", {}) for m in gltf["materials"])
    assert info["textures_resized"] >= 1 and "scaled down to at most 1 px" in info["change"]
    assert {_png_size(path, gltf, image) for image in gltf["images"]} == {(1, 1)}
    # Y up in metres: 120 mm wide, 40 mm high, 80 mm deep.
    assert _extent(gltf) == pytest.approx([0.12, 0.04, 0.08], abs=1e-4)
    assert "NVIDIA" in gltf["asset"]["copyright"] and "CC BY 4.0" in gltf["asset"]["copyright"]
    assert [n["name"] for n in gltf["nodes"]] == ["tray_mesh"], "one node per mesh, no USD scopes or instances"


@needs_usd
def test_glb_without_blender_keeps_the_shape_in_its_base_colours(env, monkeypatch):
    from pai_agent.simready import convert

    monkeypatch.setattr("pai_agent.tools.blender.find_blender", lambda: None)
    path, info = convert.to_glb(BLOCK)
    gltf = _glb(path)
    assert info["method"] == "trimesh" and info["textured"] is False and "untextured" in info["change"]
    assert _extent(gltf) == pytest.approx([0.04, 0.04, 0.04], abs=1e-4)
    assert gltf["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"][:3] == pytest.approx([0.2, 0.4, 0.9], abs=0.01)
    assert "CC BY 4.0" in gltf["asset"]["copyright"]


# ---------------------------------------------------------------- search


def test_search_matches_words_singulars_and_prefixes(env):
    assert [row["id"] for row in index.search("tray")[0]] == [TRAY]
    assert [row["id"] for row in index.search("Toy BLOCKS")[0]] == [BLOCK]
    assert [row["id"] for row in index.search("blo")[0]] == [BLOCK], "three letters match as a prefix"
    assert index.search("tray block")[0] == [], "every word must match"
    rows, total = index.search("", limit=2)
    assert total == 3 and [row["id"] for row in rows] == [BIG, TRAY], "an empty query lists the catalogue by id"
    public = index.public(index.get(BLOCK))
    assert public["thumbnail_url"] == f"/api/objects/{BLOCK}/thumbnail" and public["mass_estimated"] is True
    assert public["download_mb"] == 0.1
    assert public["license"] == "CC-BY-4.0" and public["source"] == simready.source_tag()


def test_the_shipped_index_lists_the_pinned_library():
    data = json.loads(index.INDEX_PATH.read_text(encoding="utf-8"))
    assert data["revision"] == simready.REVISION and data["license"] == "CC-BY-4.0"
    rows = data["objects"]
    assert len(rows) == data["count"] == 2575 and not data["excluded"] and not data["failed"]
    assert all(len(row["size_mm"]) == 3 and row["thumb"] and row["mass_g"] for row in rows)
    by_id = {row["id"]: row for row in rows}
    # The bowl's declared extents are inflated by a rotated part (173 mm); the index measured its points.
    assert by_id["kitchenware_bowl_b01"]["size_mm"][0] == pytest.approx(129.9, abs=0.2) and by_id["kitchenware_bowl_b01"]["size_measured"]
    assert by_id["food_produce_banana_a01"]["class"] == "banana" and by_id["kitchenware_pan_a01"]["class"] == "frying pan"


def test_search_in_the_shipped_index_ranks_the_class_first(monkeypatch):
    monkeypatch.delenv("PAI_SIMREADY_INDEX", raising=False)
    assert "banana" in index.search("bananas")[0][0]["class"]
    assert index.search("frying pan")[0][0]["class"] == "frying pan"
    assert index.search("zzzz-nothing")[0] == []


# ---------------------------------------------------------------- the tool


def _ctx(tmp_path: Path):
    from pai_agent.bus import EventBus
    from pai_agent.context import Ctx
    from pai_agent.state import BuildState

    return Ctx(EventBus(), BuildState("objects", tmp_path / "session"), auto_steps=False)


@needs_coacd
def test_scene_object_places_a_container_and_a_payload_with_attribution(env, tmp_path, monkeypatch):
    import mujoco

    from pai_agent.tools.registry import call_tool

    monkeypatch.setattr("pai_agent.tools.blender.find_blender", lambda: None)
    ctx = _ctx(tmp_path)
    tray = asyncio.run(call_tool(ctx, "scene_object", {"query": "trays", "role": "target", "reason": "the gripper puts the block in it"}))
    block = asyncio.run(call_tool(ctx, "scene_object", {"id": BLOCK, "role": "payload", "position_mm": [0, 0, 100]}))
    assert tray["ok"] and block["ok"], (tray, block)
    assert "CoACD" in tray["detail"] and "SimReady estimate" in block["detail"]
    events = [e for e in ctx.bus.events if e["type"] == "object"]
    assert [e["id"] for e in events] == [TRAY, BLOCK]
    event = events[0]
    contract = ("id", "title", "wikidata", "size_mm", "mass_g", "mass_estimated", "friction", "glb_url", "thumbnail_url", "mjcf_url", "license", "attribution", "changes", "source")
    assert all(key in event for key in contract)
    assert event["wikidata"] == {"class": "tray", "qcode": "Q613972"} and event["mass_estimated"] is True
    assert event["license"] == "CC-BY-4.0" and event["source"] == simready.source_tag()
    assert event["collision"]["method"] == "coacd" and event["role"] == "target"
    for words in ("by NVIDIA", "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/", simready.asset_url(TRAY), "Changed by AnyBuild"):
        assert words in event["attribution"]
    assert any("CoACD" in c for c in event["changes"]) and any("GLB" in c for c in event["changes"])
    assert event["thumbnail_url"] == f"/api/objects/{TRAY}/thumbnail"
    # The files the event names are in the session, flat, for /files/.
    session = Path(ctx.state.directory)
    for url in (event["mjcf_url"], event["glb_url"]):
        assert url.startswith("/files/objects/") and (session / url.split("/")[-1].split("?")[0]).is_file()
    model = mujoco.MjModel.from_xml_path(str(session / f"simready-{TRAY}.xml"))
    assert model.body(TRAY).mass[0] == pytest.approx(0.21)
    # position_mm is the centre of the object's box: the block's origin is 20 mm under it.
    placed = [e for e in ctx.bus.events if e["type"] == "object"][1]
    assert placed["position_mm"] == [0.0, 0.0, 100.0] and placed["origin_mm"] == pytest.approx([0.0, 0.0, 80.0])
    assert set(ctx.state.objects) == {TRAY, BLOCK} and ctx.state.objects[BLOCK]["role"] == "payload"
    gone = asyncio.run(call_tool(ctx, "scene_object", {"id": BLOCK, "remove": True}))
    assert gone["ok"] and set(ctx.state.objects) == {TRAY}
    assert [e for e in ctx.bus.events if e["type"] == "object"][-1] == {"type": "object", "id": BLOCK, "removed": True}


def test_scene_object_refuses_a_download_over_the_limit_and_names_smaller_matches(env, tmp_path, monkeypatch):
    from pai_agent.tools.registry import call_tool

    ctx = _ctx(tmp_path)
    by_id = asyncio.run(call_tool(ctx, "scene_object", {"id": BIG}))
    assert by_id["ok"] is False and "1500 MB download" in by_id["error"] and "PAI_SIMREADY_MAX_MB" in by_id["error"]
    by_query = asyncio.run(call_tool(ctx, "scene_object", {"query": "crate"}))
    assert by_query["ok"] is False and BIG in by_query["error"]
    assert not [e for e in ctx.bus.events if e["type"] == "object"] and fetch.cached_package(BIG) is None
    if simready.missing("convert"):
        return
    # With the limit raised the guard lets it through, and the fetch is what fails: it is not in the mirror.
    monkeypatch.setenv("PAI_SIMREADY_MAX_MB", "2000")
    raised = asyncio.run(call_tool(ctx, "scene_object", {"id": BIG}))
    assert raised["ok"] is False and "not in the SimReady mirror" in raised["error"]


def test_scene_object_without_the_extra_says_how_to_install_it(env, tmp_path, monkeypatch):
    from pai_agent.tools.registry import call_tool

    monkeypatch.setattr(simready, "missing", lambda *needs: ["usd-core"])
    result = asyncio.run(call_tool(_ctx(tmp_path), "scene_object", {"query": "tray"}))
    assert result["ok"] is False and "uv sync --extra simready" in result["error"]


def test_scene_object_without_a_match_asks_for_a_plainer_word(env, tmp_path):
    from pai_agent.tools.registry import call_tool

    result = asyncio.run(call_tool(_ctx(tmp_path), "scene_object", {"query": "unicorn"}))
    assert result["ok"] is False and "No SimReady object matches" in result["error"]


# ---------------------------------------------------------------- HTTP


def test_objects_endpoints_search_and_serve_a_cached_thumbnail(env):
    from fastapi.testclient import TestClient

    from pai_agent.app import app

    client = TestClient(app)
    found = client.get("/api/objects", params={"q": "tray"}).json()
    assert found["ok"] and found["total"] == 1 and found["source"] == simready.source_tag()
    item = found["items"][0]
    assert item["id"] == TRAY and item["license"] == "CC-BY-4.0" and item["wikidata"]["class"] == "tray"
    image = client.get(item["thumbnail_url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/webp"
    from PIL import Image
    import io

    assert Image.open(io.BytesIO(image.content)).size == (fetch.THUMB_PX, fetch.THUMB_PX)
    shutil.rmtree(env)  # the second request is the cache, whatever happens to the source
    assert client.get(item["thumbnail_url"]).status_code == 200
    assert client.get("/api/objects/not_an_object/thumbnail").status_code == 404
    assert client.get("/api/objects/" + BLOCK + "/thumbnail").status_code == 503, "not cached and the mirror is gone"
    assert client.get("/api/objects", params={"limit": 0}).status_code == 400
