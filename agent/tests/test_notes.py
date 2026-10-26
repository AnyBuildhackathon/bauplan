"""Studio notes (U6): the script lines the FreeCAD harness records per part, the notes a message carries,
what Mechanic reads from them, the markings, and the offline read-back. No network, no key, mock mode.

Run with: cd agent && uv run --with pytest pytest tests/test_notes.py
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import struct
import zlib
from pathlib import Path

import pytest

from pai_agent import notes
from pai_agent.paths import AGENT_ROOT
from pai_agent.state import BuildState


def _harness():
    spec = importlib.util.spec_from_file_location("part_harness_under_test", AGENT_ROOT / "freecad" / "part_harness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STAND = '''import math
W = P.get("width_mm", 60.0)
# The base plate, with two screw holes
base = Part.makeBox(W, 40, 5)
for x in (10, 50):
    base = base.cut(Part.makeCylinder(2, 10, Vector(x, 20, -1)))
lip = Part.makeBox(W, 4, 12, Vector(0, 0, 5))
base = base.fuse(lip)

def rest(height):
    slab = Part.makeBox(W, 5, height)
    slab.rotate(Vector(0, 0, 0), Vector(1, 0, 0), -25)
    return slab

back = rest(80)
back.translate(Vector(0, 30, 5))
parts = {}
parts["Base plate"] = base
parts["Back rest"] = back
parts["Base plate"] = parts["Base plate"].cut(Part.makeBox(4, 4, 4))
for i in range(2):
    parts["Foot " + str(i)] = Part.makeCylinder(5, 2, Vector(10 + 40 * i, 20, -2))
parts.update({"Pin": Part.makeCylinder(1, 9)})
'''


def test_the_harness_names_the_lines_that_build_each_part() -> None:
    harness = _harness()
    gripper = (AGENT_ROOT / "freecad" / "library" / "gripper.py").read_text(encoding="utf-8")
    names = ["Palm", "Gear L", "Finger L", "Servo"]
    lines = harness._part_lines(gripper, names, {"palm", "flange", "servo"})
    # The palm from its box to the wrist flange fused on, then its entry in `parts`.
    assert lines["Palm"] == [[68, 79], [86, 86]]
    # A gear is its function and the entry that calls it; a finger also takes the bar() it is made of.
    assert lines["Gear L"] == [[29, 37], [87, 87]]
    assert lines["Finger L"] == [[40, 56], [89, 89]]
    assert lines["Servo"] == [[81, 83], [93, 93]]

    lines = harness._part_lines(STAND, ["Base plate", "Back rest", "Foot 0", "Foot 1", "Pin"], {"base", "lip", "back"})
    # The comment above the base counts; the later cut builds on the entry before it.
    assert lines["Base plate"] == [[3, 8], [18, 18], [20, 20]]
    # The back rest: the function that makes it and its own lines (only blank lines between them), its entry.
    assert lines["Back rest"] == [[10, 16], [19, 19]]
    # Parts added under a computed name get the loop that adds them.
    assert lines["Foot 0"] == lines["Foot 1"] == [[21, 22]]
    assert lines["Pin"] == [[23, 23]]
    assert harness._part_lines("shape = Part.makeBox(1, 2, 3)\n", ["Part"], {"shape"}) == {"Part": [[1, 1]]}


def test_freecad_rows_carry_their_lines(tmp_path) -> None:
    from pai_agent.cad_script import run_script
    from pai_agent.freecad_run import find_freecadcmd

    if find_freecadcmd() is None:
        pytest.skip("freecadcmd is not installed")
    build = run_script(STAND, {"width_mm": 60.0}, tmp_path, "part-stand")
    rows = {row["name"]: row["lines"] for row in build.parts}
    assert rows["Base plate"] == [[3, 8], [18, 18], [20, 20]]
    assert rows["Back rest"] == [[10, 16], [19, 19]]
    assert rows["Pin"] == [[23, 23]]


def _png(width: int = 2, height: int = 2) -> bytes:
    raw = b"".join(b"\x00" + b"\xff\x80\x00" * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _bench(tmp_path: Path) -> BuildState:
    """A phone stand on the bench: the base plate placed turned by 90 degrees about Z, a bought phone as a load."""

    state = BuildState(session_id="s1", directory=tmp_path)
    state.product = "generic"
    state.spec = {
        "name": "Phone stand",
        "parts": [
            {"id": "base", "name": "Base plate", "kind": "printed", "position_mm": [0.0, 0.0, 2.5], "rotation_deg": [0.0, 0.0, 90.0], "params": {"width_mm": 60.0}},
            {"id": "phone", "name": "Phone", "kind": "external"},
        ],
    }
    state.built = {
        "base": {
            "name": "Base plate",
            "script": STAND,
            "bbox_mm": [0.0, 0.0, 0.0, 60.0, 40.0, 5.0],
            "params": {"width_mm": 72.0},
            "parts": [{"name": "Base plate", "lines": [[3, 8], [18, 18], [20, 20]]}, {"name": "Back rest", "lines": [[10, 16], [19, 19]]}],
        }
    }
    state.assembly = {
        "bodies": [
            {"name": "Base plate", "part_id": "base", "kind": "printed"},
            {"name": "Back rest", "part_id": "base", "kind": "printed"},
            {"name": "Phone", "part_id": "phone", "kind": "external"},
            {"name": "ISO 4762 M3x8", "part_id": "m3-screws", "holder": "base", "kind": "hardware"},
        ]
    }
    # The person moved the base's width slider to 72 mm (U7's user values).
    state.user_params = {"base": {"width_mm": 72.0}}
    state.cad_builds = 7
    state.versions = [{"n": 1, "build": 5}, {"n": 2, "build": 7}]
    state.surface = {"limits": {"thickness": 0.88}}
    return state


def test_notes_are_checked(tmp_path) -> None:
    state = _bench(tmp_path)
    assert notes.accept(None, state) == []
    for bad, message in (
        ({"kind": "poem"}, "kind must be one of"),
        ({"kind": "selection", "point_mm": [1, 2, 3]}, "node is required"),
        ({"kind": "measure", "a": {"point_mm": [0, 0, 0]}, "b": {}}, "b.point_mm is required"),
        ({"kind": "selection", "node": "Base plate", "point_mm": [1, 2]}, "three numbers"),
        ({"kind": "selection", "node": "Base plate", "point_mm": [1, 2, float("nan")]}, "must be a number"),
        ({"kind": "markup", "image": "markup-1.png"}, "uploaded to this session"),
        ({"kind": "markup", "image": "../secret.png"}, "uploaded to this session"),
        ({"kind": "spot", "check": "colour", "value": 1, "part": "x", "at_mm": [0, 0, 0]}, "check must be one of"),
        ({"kind": "param", "value": 3}, "name is required"),
        ({"kind": "selection", "node": "x", "point_mm": [0, 0, 0], "build": 2.5}, "whole number"),
    ):
        with pytest.raises(ValueError, match=message):
            notes.accept([bad], state)
    with pytest.raises(ValueError, match="At most 8"):
        notes.accept([{"kind": "param", "name": "a", "value": 1}] * 9, state)


def test_a_selection_names_its_script_lines_and_the_point_in_its_own_frame(tmp_path) -> None:
    state = _bench(tmp_path)
    # The browser names the node as GLTFLoader does (spaces as underscores).
    [note] = notes.accept([{"kind": "selection", "node": "Base_plate", "part": "Base plate", "point_mm": [-10.0, 5.0, 5.0], "normal": [0, 0, 2], "build": 7}], state)
    assert note["part_id"] == "base"
    assert note["script"] == "part-base.py"
    assert note["lines"] == [[3, 8], [18, 18], [20, 20]]
    assert note["normal"] == [0.0, 0.0, 1.0]
    # Placed turned by 90 degrees about Z with its box centre (30, 20, 2.5) on (0, 0, 2.5): back into the script's frame.
    assert note["local_mm"] == [35.0, 30.0, 5.0]
    assert note["built_as"] == {"build": 7, "current": True, "version": 2, "now": 7, "now_version": 2}

    [screw, phone] = notes.accept(
        [{"kind": "selection", "node": "ISO_4762_M3x8", "point_mm": [0, 0, 0]}, {"kind": "selection", "node": "Phone", "point_mm": [0, 9, 60]}], state
    )
    assert (screw["part_id"], screw["holder"], screw.get("script")) == ("m3-screws", "base", None)
    assert (phone["part_kind"], phone.get("lines")) == ("external", None)
    # Picked in the assembly tree, a part comes without a point.
    [tree] = notes.accept([{"kind": "selection", "node": "Back rest", "part": "Back rest"}], state)
    assert tree["point_mm"] is None and "local_mm" not in tree and tree["lines"] == [[10, 16], [19, 19]]
    assert notes._line(state, tree, 0, False) == "Selection: Back rest (printed part base). Its script part-base.py builds it in lines 10-16, 19 (below)."
    # A click on the face the section view cut is a point inside the part.
    [inside] = notes.accept([{"kind": "selection", "node": "Base plate", "part": "Base plate", "point_mm": [-20, 0, 2], "normal": [1, 0, 0], "cut": True}], state)
    assert "The person clicked inside it, on the face the section view cut, at (-20.0, 0.0, 2.0) mm" in notes._line(state, inside, 0, False)
    # Clicked on the exploded model: the point is where the part sits assembled, and Mechanic is told how it looked.
    [apart] = notes.accept([{"kind": "selection", "node": "Base plate", "part": "Base plate", "point_mm": [-20, 0, 2], "exploded": 0.6}], state)
    assert notes._line(state, apart, 0, False).endswith(
        "The studio showed the model exploded 60 %, each part pulled out the way it goes on; the points are where the parts sit assembled."
    )
    assert notes.read_back(state, [apart]).startswith("I read your notes:\n\n- Base plate, part-base.py lines 3-8, 18, 20 at (-20.0, 0.0, 2.0) mm, seen exploded 60 %")
    [whole] = notes.accept([{"kind": "selection", "node": "Base plate", "exploded": 0}], state)
    assert "exploded" not in whole or whole["exploded"] is None


def test_mechanic_reads_each_note_with_the_code_and_an_older_build_said_plainly(tmp_path) -> None:
    state = _bench(tmp_path)
    (tmp_path / "markup-1.png").write_bytes(_png())
    attached = notes.accept(
        [
            {"kind": "selection", "node": "Back rest", "part": "Back rest", "point_mm": [12.0, 30.0, 40.0], "normal": [0, 1, 0], "build": 7},
            {"kind": "measure", "a": {"point_mm": [0, 0, 0], "part": "Base plate", "normal": [0, 0, 1]}, "b": {"point_mm": [0, 30, 40], "part": "Back rest", "normal": [0, 1, 0]}, "build": 7},
            {
                "kind": "markup",
                "image": "markup-1.png",
                "build": 5,
                "version": 1,
                "view": {"tab": "cad", "camera": [0.5, -0.6, 0.6], "explode": 0.4, "section": {"axis": "x", "at_mm": 12.04, "keep": "below"}, "surface": {"check": "thickness", "limit": 1.2}},
            },
            {"kind": "spot", "check": "thickness", "value": 0.62, "part": "Back_rest", "part_id": "base", "at_mm": [10.5, 22, 40.1], "limit": 1.2, "critical": True, "build": 7},
            {"kind": "param", "name": "base.width_mm", "label": "Base plate · width", "value": 72, "unit": "mm", "min": 30, "max": 120, "build": 7},
        ],
        state,
    )
    text = notes.describe(state, "Make this thicker", attached)
    assert text.startswith("Make this thicker\n\nStudio notes the person attached")
    lines = text.splitlines()
    assert any(line.startswith("1. Selection: Back rest (printed part base). The person clicked the face pointing to the back at (12.0, 30.0, 40.0) mm") for line in lines)
    assert "Its script part-base.py builds it in lines 10-16, 19 (below). On the current model (version 2)." in text
    assert "2. Measurement: 50.0 mm from Base plate at (0.0, 0.0, 0.0) mm to Back rest at (0.0, 30.0, 40.0) mm: dx 0.0, dy 30.0, dz 40.0 mm, 53.1° from the horizontal; the two faces stand at 90° to each other." in text
    assert "3. Marking 1, the picture number 1 after this text (markup-1.png): drawn on the CAD tab, seen from the front, the right and above, perspective, exploded 40 %" in text
    assert "cut through X at 12.0 mm, the part above it taken away" in text
    assert "coloured by wall thickness at 1.2 mm" in text
    assert "Taken on build 5 (version 1), an older model than the one on the bench now (build 7, version 2): check what changed before you act on it." in text
    assert "4. Surface spot: wall thickness 0.62 mm on Back rest at (10.5, 22.0, 40.1) mm, past the 1.2 mm limit the colour layer showed (your own limit is 0.88 mm)." in text
    # The person's own slider value, against the one Mechanic designed in the spec.
    assert "5. Parameter: Base plate · width (base.width_mm) is 72 mm, a value the person set with its slider; you designed it at 60 mm; its slider runs 30 to 120 mm." in text
    # The code of the selected part follows, numbered like the file.
    assert "part-base.py, the lines that build Back rest:\n```python\n  10  def rest(height):" in text
    assert "  19  parts[\"Back rest\"] = back\n```" in text

    [image] = notes.images(state, attached)
    assert image["type"] == "image" and base64.b64decode(image["source"]["data"]) == _png()
    # No words, only notes: Mechanic is told so.
    assert notes.describe(state, "", attached[:1]).startswith("(No words: only the notes below.)")

    said = notes.read_back(state, attached)
    assert said.startswith("I read your notes:\n\n- Back rest, part-base.py lines 10-16, 19, the face pointing to the back at (12.0, 30.0, 40.0) mm\n")
    assert "- Your marking on the CAD view, cut through X at 12.0 mm (on an older build)\n" in said
    assert said.endswith("Offline I can only read them back. With Claude connected I change the design right there.")


def test_a_parameter_without_a_spec_value_takes_its_declared_default(tmp_path) -> None:
    state = _bench(tmp_path)
    state.product = "drone"
    state.part = {"name": "Clip", "template": None, "script": 'PARAMS = {"gap_mm": {"value": 4.0, "min": 2.0, "max": 8.0, "unit": "mm"}}\nshape = Part.makeBox(P["gap_mm"], 5, 5)\n'}
    state.user_params = {"clip": {"gap_mm": 5.5}}
    [note] = notes.accept([{"kind": "param", "name": "gap_mm", "label": "Gap", "value": 5.5, "unit": "mm"}], state)
    assert (note["default"], note["user_set"]) == (4.0, True)
    state.part = {"name": "Gripper", "template": "gripper", "script": ""}
    [note] = notes.accept([{"kind": "param", "name": "finger_length_mm", "label": "Finger length", "value": 70, "unit": "mm"}], state)
    assert note["default"] == 70.0 and "user_set" not in note


def test_markings_are_pngs_kept_in_the_session(tmp_path) -> None:
    state = _bench(tmp_path)
    data = notes.decode_png("data:image/png;base64," + base64.b64encode(_png()).decode())
    assert notes.store_markup(state, data) == "markup-1.png"
    assert notes.store_markup(state, data) == "markup-2.png"
    assert (tmp_path / "markup-2.png").read_bytes() == _png()
    for raw, message in (("not base64!", "not valid base64"), (base64.b64encode(b"GIF89a....").decode(), "must be a PNG"), (base64.b64encode(_png(5000, 1)).decode(), "at most 4096")):
        with pytest.raises(ValueError, match=message):
            notes.decode_png(raw)


def test_old_markings_leave_the_history_but_the_newest_stay() -> None:
    from pai_agent.tools.view import drop_old_images

    def picture(n: int) -> dict:
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": str(n)}}

    messages = [{"role": "user", "content": [{"type": "text", "text": "look " + str(n)}, picture(n)]} for n in range(5)]
    drop_old_images(messages)
    kept = [block["source"]["data"] for message in messages for block in message["content"] if block["type"] == "image"]
    assert kept == ["2", "3", "4"]
    assert messages[0]["content"][1] == {"type": "text", "text": "(An older marking the person drew was shown here.)"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("PAI_FORCE_MOCK", "1")
    monkeypatch.setenv("PAI_WARM", "0")
    monkeypatch.setattr("pai_agent.session.SESSIONS_DIR", tmp_path)
    monkeypatch.setattr("pai_agent.app.SESSIONS_DIR", tmp_path)
    from pai_agent.app import app

    with TestClient(app) as test_client:
        yield test_client, app


def _settled(app) -> None:
    session = app.state.session
    if session.task is not None:
        asyncio.run_coroutine_threadsafe(asyncio.wait_for(asyncio.shield(session.task), 30), session.task.get_loop()).result(35)


def test_a_message_with_notes_reaches_the_chat_and_offline_mechanic_reads_them_back(client) -> None:
    test_client, app = client
    upload = test_client.post("/api/notes/markup", json={"image_base64": base64.b64encode(_png()).decode()})
    assert upload.status_code == 200
    body = upload.json()
    session_id = app.state.session.state.session_id
    assert body == {"ok": True, "name": "markup-1.png", "url": "/files/" + session_id + "/markup-1.png"}
    assert test_client.get(body["url"]).content == _png()
    assert test_client.post("/api/notes/markup", json={"image_base64": "x"}).status_code == 400
    assert test_client.post("/api/notes/markup", content=b"{}", headers={"content-type": "text/plain"}).status_code in (415, 422)

    sent = test_client.post(
        "/api/prompt",
        json={"text": "", "notes": [{"kind": "markup", "image": "markup-1.png", "view": {"tab": "modell"}}, {"kind": "param", "name": "arm_length_mm", "label": "Arm length", "value": 40, "unit": "mm"}]},
    )
    assert sent.status_code == 200 and sent.json()["status"] == "started"
    _settled(app)
    chat = [event for event in app.state.session.bus.events if event.get("type") == "chat"]
    user = next(event for event in chat if event["role"] == "user")
    assert user["text"] == ""
    assert [note["kind"] for note in user["notes"]] == ["markup", "param"]
    assert user["notes"][0]["url"] == "/files/" + session_id + "/markup-1.png"
    reply = next(event for event in chat if event["role"] == "agent")
    assert reply["text"] == "I read your notes:\n\n- Your marking on the Model view\n- Arm length at 40 mm\n\nOffline I can only read them back. With Claude connected I change the design right there."
    # Words alone still need words; a broken note says what is wrong.
    assert test_client.post("/api/prompt", json={"text": " "}).status_code == 400
    bad = test_client.post("/api/prompt", json={"text": "this", "notes": [{"kind": "spot", "check": "overhang", "part": "x", "at_mm": [0, 0, 0]}]})
    assert bad.status_code == 400 and bad.json()["detail"] == "value is required."
