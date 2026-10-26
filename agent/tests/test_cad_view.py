"""cad_view: Mechanic sees his own model.

A known product (a plate, an L-shaped bracket whose shelf hangs over by exactly 600 mm², a bought
box and a see-through load) goes through the real assembly and the real renderer in its own
process: one PNG of fixed size, a number per part, hide and only by name or id, a section with
its cut faces, the overhang in red with print_prep's area. The picture reaches Claude as an image
block on the Messages API, never inside the JSON text, and only the newest two stay in the
history. No network, no key; the mock runs stay as they were.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import struct
from types import SimpleNamespace

import numpy as np
import pytest

from pai_agent import assembly as asm
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools.view import IMAGE, _select, api_content, cad_view, drop_old_images, mcp_content
from pai_agent.view_render import grid_step, mesh_nodes, overhang, read_glb, read_meshes

# The bracket's outline in the XZ plane, counter-clockwise: a 4 mm post with a 20 mm shelf at its top.
L_OUTLINE = [(-20.0, 4.0), (-16.0, 4.0), (-16.0, 30.0), (4.0, 30.0), (4.0, 34.0), (-20.0, 34.0)]
L_FACES = [(0, 1, 2), (0, 2, 5), (2, 3, 4), (2, 4, 5)]


def _prism(outline, faces, y0: float, y1: float) -> list[tuple[float, float, float]]:
    """A closed prism of a counter-clockwise XZ outline from y0 to y1, every triangle wound outward."""

    front = [(x, y0, z) for x, z in outline]
    back = [(x, y1, z) for x, z in outline]
    triangles = []
    for a, b, c in faces:
        triangles += [front[a], front[b], front[c], back[a], back[c], back[b]]
    for i in range(len(outline)):
        j = (i + 1) % len(outline)
        triangles += [front[i], back[j], front[j], front[i], back[i], back[j]]
    return triangles


def _bench(tmp_path) -> Ctx:
    """The known product on a bench, assembled by assembly.build like any other."""

    asm.write_stl(tmp_path / "part-plate-0.stl", asm.box_triangles([40.0, 30.0, 4.0], (0.0, 0.0, 2.0), asm.rotation(None)))
    asm.write_stl(tmp_path / "part-bracket-0.stl", _prism(L_OUTLINE, L_FACES, -15.0, 15.0))
    spec = {
        "name": "Test bracket",
        "function": "Holds a load on a shelf.",
        "requirements": [],
        "assemblies": [],
        "parts": [
            {"id": "plate", "name": "Plate", "kind": "printed", "qty": 1, "material": "PLA"},
            {"id": "bracket", "name": "Bracket", "kind": "printed", "qty": 1, "material": "PLA"},
            {"id": "box", "name": "Battery box", "kind": "bought", "qty": 1, "size_mm": [10.0, 10.0, 10.0], "position_mm": [10.0, 0.0, 9.0]},
            {"id": "load", "name": "Load", "kind": "external", "qty": 1, "mass_g": 80.0, "size_mm": [16.0, 20.0, 10.0], "position_mm": [-6.0, 0.0, 39.0]},
        ],
    }
    built = {
        "plate": {"bbox_mm": [-20.0, -15.0, 0.0, 20.0, 15.0, 4.0], "material": "PLA", "params": {}, "parts": [{"name": "Plate", "stl": "part-plate-0.stl", "mass_g": 6.0, "material": "PLA", "reference": False}]},
        "bracket": {"bbox_mm": [-20.0, -15.0, 4.0, 4.0, 15.0, 34.0], "material": "PLA", "params": {}, "parts": [{"name": "Bracket", "stl": "part-bracket-0.stl", "mass_g": 7.4, "material": "PLA", "reference": False}]},
    }
    # A picked part without a catalog id keeps its box: no part model is looked up.
    picked = {"box": {"name": "Battery box", "mass_g": 20.0, "unit_price_eur": 3.0}}
    state = BuildState(session_id="t", directory=tmp_path, product="generic", spec=spec, built=built, picked=picked)
    state.assembly = asm.build(spec, built, picked, tmp_path)
    state.assembly_stale = False
    return Ctx(EventBus(), state, auto_steps=False)


def _view(ctx: Ctx, **args) -> dict:
    return asyncio.run(cad_view(ctx, args))


def _pixels(result: dict) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(base64.b64decode(result[IMAGE]))).convert("RGB")).astype(int)


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_a_known_part_comes_back_as_a_picture_of_fixed_size(tmp_path):
    ctx = _bench(tmp_path)
    result = _view(ctx)
    assert result["ok"] is True, result
    png = base64.b64decode(result[IMAGE])
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (1024, 768)
    # The newest picture also stays in the session.
    assert (tmp_path / "cad-view.png").read_bytes() == png
    assert result["views"] == ["iso", "front", "right", "top"]
    parts = {p["name"]: p for p in result["parts"]}
    assert [p["number"] for p in result["parts"]] == [1, 2, 3, 4]
    assert parts["Bracket"] == {"number": 2, "name": "Bracket", "id": "bracket", "kind": "printed", "color": "orange"}
    assert parts["Battery box"]["kind"] == "bought" and parts["Battery box"]["color"] == "blue"
    assert parts["Load"]["color"].endswith("see-through")
    assert result["size_mm"] == [40.0, 30.0, 44.0] and result["grid_mm"] == 5.0
    # Every part shows: the picture is not blank, the orange bracket is in it.
    pixels = _pixels(result)
    orange = (np.abs(pixels - np.array([255, 138, 61])) < 60).all(axis=2)
    assert orange.sum() > 2000
    assert IMAGE not in json.loads(api_content(result)[0]["text"])


def test_only_and_hide_take_names_ids_and_kinds(tmp_path):
    ctx = _bench(tmp_path)
    nodes = mesh_nodes(read_glb(tmp_path / "assembly.glb")[0])
    aliases = {body["name"]: [body["part_id"], body["kind"]] for body in ctx.state.assembly["bodies"]}
    chosen, unknown = _select(nodes, aliases, ["bracket", "Plate"], ["plate"])
    assert [node["name"] for node in chosen] == ["Bracket"] and unknown == []
    chosen, _unknown = _select(nodes, aliases, [], ["external", "bought"])
    assert [node["name"] for node in chosen] == ["Plate", "Bracket"]
    # A start of a name or a plural works when nothing matches exactly.
    assert [node["name"] for node in _select(nodes, aliases, ["brackets"], [])[0]] == ["Bracket"]
    wrong = _view(ctx, only=["wheel"])
    assert wrong["ok"] is False and "'wheel'" in wrong["error"] and "Plate, Bracket, Battery box, Load" in wrong["error"]
    assert _view(ctx, hide=["plate", "bracket", "box", "load"])["ok"] is False

    alone = _view(ctx, view="front", only=["bracket"])
    assert alone["ok"] is True and [p["name"] for p in alone["parts"]] == ["Bracket"]
    assert alone["hidden"] == ["Plate", "Battery box", "Load"]
    assert alone["size_mm"] == [24.0, 30.0, 30.0]


def test_a_section_takes_away_the_half_facing_the_camera(tmp_path):
    ctx = _bench(tmp_path)
    cut = _view(ctx, view="right", section={"axis": "x", "at_mm": 0})
    assert cut["ok"] is True, cut
    assert cut["section"]["removed"] == "x > 0 mm" and cut["views"] == ["right"]
    # The plate is cut through: its cut face is a darker shade of its light grey, the bracket behind stays orange.
    pixels = _pixels(cut)
    assert (np.abs(pixels - np.array([255, 138, 61])) < 60).all(axis=2).sum() > 2000
    assert _view(ctx, section={"axis": "x", "at_mm": 90})["ok"] is False
    assert _view(ctx, section={"axis": "x", "at_mm": 0}, color="overhang")["ok"] is False


def test_the_overhang_is_print_preps_and_shows_red(tmp_path):
    from pai_agent.tools.print_prep import analyse, orient, read_stl

    ctx = _bench(tmp_path)
    result = _view(ctx, color="overhang")
    assert result["ok"] is True, result
    assert result["views"] == ["iso_below"]
    assert result["overhang_cm2"] == {"Plate": 0.0, "Bracket": 6.0}
    assert result["print_pose"] == {"Plate": "as modelled", "Bracket": "as modelled"}
    # The same rule as print_prep on the same mesh.
    assert analyse(orient(read_stl(tmp_path / "part-bracket-0.stl"), "as_modeled")[0])["overhang_mm2"] == pytest.approx(600.0)
    pixels = _pixels(result)
    r, g, b = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    assert ((r > 120) & (r > 2.5 * g) & (r > 2.5 * b)).sum() > 1500
    # With a print plan, each part is judged in its print pose: the bracket on its side has no overhang.
    ctx.state.print_plan = {"parts": [{"id": "bracket", "orientation": "upright"}]}
    upright = _view(ctx, color="overhang", only=["bracket"])
    assert upright["print_pose"] == {"Bracket": "upright"} and upright["overhang_cm2"]["Bracket"] < 6.0


def test_a_single_part_is_judged_in_print_preps_pose_too(tmp_path):
    """A part built on its own (the gripper) is planned by print_prep as one STL, turned by that STL's size."""

    from pai_agent.mesh_export import stls_to_glb
    from pai_agent.tools.print_prep import analyse, orient, read_stl

    stl = tmp_path / "part-bracket.stl"
    asm.write_stl(stl, _prism(L_OUTLINE, L_FACES, -15.0, 15.0))
    stls_to_glb([("Bracket", stl, "#ff8a3d")], stl.with_suffix(".glb"))
    state = BuildState(session_id="t", directory=tmp_path, product="gripper")
    state.part = {"name": "Bracket", "parts": [{"name": "Bracket", "reference": False}]}
    state.stl_path = str(stl)
    ctx = Ctx(EventBus(), state, auto_steps=False)
    modelled = _view(ctx, color="overhang")
    assert modelled["print_pose"] == {"Bracket": "as modelled"} and modelled["overhang_cm2"] == {"Bracket": 6.0}
    # Flat lays its thinnest side (24 mm along X) on the bed: nothing hangs over, as print_prep counts it.
    state.print_plan = {"parts": [{"id": "body", "orientation": "flat"}]}
    flat = _view(ctx, color="overhang")
    assert flat["print_pose"] == {"Bracket": "flat"} and flat["overhang_cm2"] == {"Bracket": 0.0}
    assert analyse(orient(read_stl(stl), "flat")[0])["overhang_mm2"] == 0.0


def test_the_overhang_rule_counts_faces_that_face_down_off_the_bed():
    points = np.array(_prism(L_OUTLINE, L_FACES, -15.0, 15.0))
    faces = np.arange(len(points)).reshape(-1, 3)
    kind, area = overhang(points, faces, np.array([0.0, 0.0, 1.0]), 45.0, 4.0)
    assert area == pytest.approx(600.0)
    # The two triangles of the post's foot are on the bed, the two of the shelf's underside hang over.
    assert (kind == 2).sum() == 2 and (kind == 1).sum() == 2


def test_the_drone_glb_turns_into_freecads_frame(tmp_path):
    """glTF's metres with Y up and the nose at -Z become millimetres with Z up and the nose at +Y."""

    from pai_agent.mesh_export import stl_to_glb

    asm.write_stl(tmp_path / "cube.stl", asm.box_triangles([0.002, 0.002, 0.002], (0.0, 0.0, 0.0), asm.rotation(None)))
    stl_to_glb(tmp_path / "cube.stl", tmp_path / "plain.glb")
    document, blob = read_glb(tmp_path / "plain.glb")
    # The plain cube as a motor under a "drone" root, front left of the hub the way frame_build places it.
    document["nodes"] = [{"name": "drone", "children": [1]}, {"name": "motor_front_left", "mesh": 0, "translation": [-0.03, 0.002, -0.03]}]
    document["scenes"] = [{"nodes": [0]}]
    payload = json.dumps(document).encode()
    payload += b" " * (-len(payload) % 4)
    body = blob + b"\x00" * (-len(blob) % 4)
    chunks = struct.pack("<I4s", len(payload), b"JSON") + payload + struct.pack("<I4s", len(body), b"BIN\x00") + body
    (tmp_path / "frame.glb").write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)
    nodes = mesh_nodes(read_glb(tmp_path / "frame.glb")[0])
    assert [(node["name"], node["within"]) for node in nodes] == [("motor_front_left", ["drone"])]
    (mesh,) = read_meshes(tmp_path / "frame.glb", "gltf")
    centre = mesh["points"].mean(axis=0)
    assert centre == pytest.approx([-30.0, 30.0, 2.0])
    assert np.ptp(mesh["points"], axis=0) == pytest.approx([2.0, 2.0, 2.0])


def test_no_model_yet_says_what_to_build(tmp_path):
    ctx = Ctx(EventBus(), BuildState(session_id="t", directory=tmp_path), auto_steps=False)
    result = _view(ctx)
    assert result["ok"] is False and "cad_frame" in result["error"]
    assert _view(ctx, view="sideways")["ok"] is False
    assert _view(ctx, direction=[0, 0, 0])["ok"] is False


def test_the_picture_is_an_image_block_beside_the_json():
    from pai_agent.orchestrator import _results

    plain = {"ok": True, "detail": "1 part", "parts": [{"number": 1, "name": "Plate"}]}
    # Every other tool's result goes out exactly as before.
    assert api_content(plain) == json.dumps(plain, ensure_ascii=False, default=str)
    assert mcp_content(plain) == [{"type": "text", "text": json.dumps(plain, ensure_ascii=False, default=str)}]
    seen = {**plain, IMAGE: "iVBORw0KGgo="}
    (block,) = _results([SimpleNamespace(id="tu1")], [seen])
    text, image = block["content"]
    assert json.loads(text["text"]) == plain
    assert image == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}
    assert mcp_content(seen)[1] == {"type": "image", "data": "iVBORw0KGgo=", "mimeType": "image/png"}


def test_only_the_newest_two_pictures_stay_in_the_history():
    def turn(n: int) -> list[dict]:
        image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": str(n)}}
        return [
            {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{n}", "name": "cad_view", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{n}", "content": [{"type": "text", "text": "{}"}, image]}]},
        ]

    messages = [{"role": "user", "content": "Build a stand."}, *turn(1), *turn(2), *turn(3)]
    drop_old_images(messages)
    pictures = [[p for p in m["content"][0]["content"] if p["type"] == "image"] for m in messages[2::2]]
    assert [len(p) for p in pictures] == [0, 1, 1]
    assert messages[2]["content"][0]["content"][-1]["text"].startswith("(An older picture")
    drop_old_images(messages)
    assert [len([p for p in m["content"][0]["content"] if p["type"] == "image"]) for m in messages[2::2]] == [0, 1, 1]


def test_a_grid_square_is_a_round_size():
    assert [grid_step(v) for v in (40.0, 140.0, 900.0, 3.0)] == [5.0, 20.0, 200.0, 0.5]
