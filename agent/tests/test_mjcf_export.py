"""MJCF export of the gripper: joints from the template, the tool frame, collision shapes and the catalog servo.

Run with: cd agent && uv run --with pytest pytest tests/test_mjcf_export.py
The FreeCAD tests build the real template (skipped without freecadcmd); the rest use a gripper of plain boxes.
The same file compiles under MuJoCo 3.3.0 in anybuild-robouse's tests, which run the bundled example_hand.xml.
"""

from __future__ import annotations

import itertools
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np
import pytest

from pai_agent import cache, cad_script
from pai_agent.assembly import box_triangles, write_stl
from pai_agent.cad_script import PartBuild, run_script, run_script_cached
from pai_agent.freecad_run import find_freecadcmd
from pai_agent.mjcf_export import ExportError, hand_mjcf, servo_dynamics, tool_frame
from pai_agent.paths import REPO_ROOT
from pai_agent.tools.cad_part import LIBRARY, library_script
from pai_agent.tools.gripper import GRAVITY, HOLD_FRACTION, gripper_catalog

CATALOG = {part["id"]: part for part in gripper_catalog()["parts"]}
SERVO, PADS = CATALOG["towerpro-mg996r"], CATALOG["pads-tpu-printed"]
EXAMPLE = REPO_ROOT / "anybuild-robouse" / "src" / "anybuild_robouse" / "data" / "example_hand.xml"
needs_freecad = pytest.mark.skipif(find_freecadcmd() is None, reason="freecadcmd is not installed")

# A gripper of boxes in the template's frame (mm, fingers along +Y): a base and the servo, two fingers on hinges, two pads.
BOXES = {
    "Base": ([60.0, 20.0, 10.0], (0.0, -10.0, 0.0), "#c9ccd3"),
    "Servo": ([20.0, 20.0, 20.0], (0.0, -30.0, 0.0), "#3b5bdb"),
    "Finger L": ([6.0, 50.0, 6.0], (-20.0, 25.0, 0.0), "#e7e8ec"),
    "Finger R": ([6.0, 50.0, 6.0], (20.0, 25.0, 0.0), "#e7e8ec"),
    "Pad L": ([2.0, 20.0, 6.0], (-16.0, 40.0, 0.0), "#2b2d33"),
    "Pad R": ([2.0, 20.0, 6.0], (16.0, 40.0, 0.0), "#2b2d33"),
}
SIM = {
    "joints": {
        "finger_l": {"parts": ["Finger L", "Pad L"], "pivot_mm": [-20.0, 0.0, 0.0], "axis": [0, 0, 1], "range_deg": [0.0, 20.0], "ref_deg": 20.0, "drive": "Servo"},
        "finger_r": {"parts": ["Finger R", "Pad R"], "pivot_mm": [20.0, 0.0, 0.0], "axis": [0, 0, -1], "range_deg": [0.0, 20.0], "ref_deg": 20.0, "follows": "finger_l", "ratio": 1.0},
    },
    "tool": {"point_mm": [0.0, 40.0, 0.0], "approach": [0, 1, 0], "closing": [1, 0, 0]},
    "grip_surfaces": ["Pad L", "Pad R"],
}


def _box_build(directory: Path) -> list[dict]:
    rows = []
    for index, (name, (size, center, color)) in enumerate(BOXES.items()):
        stl = "box-" + str(index) + ".stl"
        write_stl(directory / stl, box_triangles(size, center, [[1, 0, 0], [0, 1, 0], [0, 0, 1]]))
        low = [c - s / 2 for c, s in zip(center, size)]
        high = [c + s / 2 for c, s in zip(center, size)]
        volume = size[0] * size[1] * size[2]
        rows.append({"name": name, "stl": stl, "bbox_mm": low + high, "com_mm": list(center), "volume_mm3": volume, "mass_g": round(volume / 1000 * 1.24, 2), "color": color, "reference": name == "Servo", "material": "PLA"})
    return rows


def _model(text: str):
    model = mujoco.MjModel.from_xml_string(text)
    return model, mujoco.MjData(model)


def _text(model, name: str) -> str:
    index = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_TEXT, name)
    start = model.text_adr[index]
    return bytes(model.text_data[start : start + model.text_size[index] - 1]).decode()


def _set(model, data, angle: float) -> None:
    for name in ("finger_l", "finger_r"):
        data.qpos[model.jnt_qposadr[model.joint(name).id]] = angle
    mujoco.mj_kinematics(model, data)


def _jaw_mm(model, data, angle: float) -> float:
    """Gap between the pads' collision boxes along the closing axis (y)."""

    _set(model, data, angle)
    sides = []
    for geom in ("pad_l_c0", "pad_r_c0"):
        g = model.geom(geom).id
        rot = data.geom_xmat[g].reshape(3, 3)
        sides.append([data.geom_xpos[g] + rot @ (np.array(s) * model.geom_size[g]) for s in itertools.product((-1, 1), repeat=3)])
    return 1000.0 * (min(p[1] for p in sides[1]) - max(p[1] for p in sides[0]))


def test_tool_frame_points_the_fingers_down_and_closes_along_y() -> None:
    rotation, origin = tool_frame(SIM["tool"])
    assert rotation @ np.array([0.0, 1.0, 0.0]) == pytest.approx([0.0, 0.0, -1.0])
    assert rotation @ np.array([1.0, 0.0, 0.0]) == pytest.approx([0.0, 1.0, 0.0])
    assert np.linalg.det(rotation) == pytest.approx(1.0)
    assert list(origin) == [0.0, 40.0, 0.0]


def test_box_gripper_exports_joints_coupling_servo_and_pads(tmp_path) -> None:
    rows = _box_build(tmp_path)
    text = hand_mjcf(rows, SIM, tmp_path, SERVO, PADS)
    model, data = _model(text)
    assert [model.body(i).name for i in range(model.nbody)] == ["world", "hand", "finger_l", "finger_r"]
    assert model.site("tcp").id >= 0 and list(model.site_pos[model.site("tcp").id]) == [0.0, 0.0, 0.0]
    # The finger pivots sit 40 mm above the tool point, 20 mm to each side along the closing axis.
    assert model.body_pos[model.body("finger_l").id] == pytest.approx([0.0, -0.02, 0.04])
    assert model.body_pos[model.body("finger_r").id] == pytest.approx([0.0, 0.02, 0.04])
    left = model.joint("finger_l")
    assert model.jnt_range[left.id] == pytest.approx([0.0, math.radians(20.0)])
    assert model.qpos0[left.qposadr[0]] == pytest.approx(math.radians(20.0))
    assert model.neq == 1 and model.eq_type[0] == mujoco.mjtEq.mjEQ_JOINT
    assert model.eq_data[0][:5] == pytest.approx([0.0, 1.0, 0.0, 0.0, 0.0])
    # The servo: MG996R holding torque at the joint, position control over the joint's range.
    torque = SERVO["stall_torque_kgcm"] * GRAVITY / 100.0 * HOLD_FRACTION
    assert model.nu == 1 and model.actuator_trnid[0][0] == left.id
    assert model.actuator_forcerange[0] == pytest.approx([-torque, torque])
    assert model.actuator_ctrlrange[0] == pytest.approx([0.0, math.radians(20.0)])
    assert model.actuator_gainprm[0][0] == pytest.approx(servo_dynamics(SERVO)["kp"])
    assert model.dof_damping[left.dofadr[0]] == pytest.approx(torque / math.radians(300.0))
    # Mass from CAD, the servo's from the catalog.
    base = next(row for row in rows if row["name"] == "Base")["mass_g"]
    assert model.body_mass[model.body("hand").id] == pytest.approx((base + SERVO["mass_g"]) / 1000.0)
    # Pads: the catalog friction decides the contact (priority), with torsional friction; other parts printed plastic.
    pad = model.geom("pad_l_c0").id
    assert model.geom_friction[pad][0] == pytest.approx(PADS["friction"])
    assert model.geom_priority[pad] == 1 and model.geom_condim[pad] == 4
    assert model.geom_friction[model.geom("finger_l_c0").id][0] == pytest.approx(0.4)
    # Meshes are shown, not collided with; collision boxes are hidden (group 3).
    mesh = model.geom("pad_l").id
    assert model.geom_contype[mesh] == 0 and model.geom_conaffinity[mesh] == 0 and model.geom_group[mesh] == 2
    assert model.geom_group[pad] == 3 and model.geom_contype[pad] == 1
    assert [_text(model, name) for name in ("anybuild_servo", "anybuild_pads")] == [SERVO["name"], PADS["name"]]
    assert model.nexclude == 3  # the hand's three bodies never collide with each other


def test_meshes_sit_where_the_collision_boxes_are(tmp_path) -> None:
    model, data = _model(hand_mjcf(_box_build(tmp_path), SIM, tmp_path, SERVO, PADS))
    mujoco.mj_forward(model, data)
    for name in ("base", "servo", "finger_l", "pad_r"):
        mesh, box = model.geom(name).id, model.geom(name + "_c0").id
        assert data.geom_xpos[mesh] == pytest.approx(data.geom_xpos[box], abs=1e-6)


def test_the_servo_closes_both_fingers_through_the_gears(tmp_path) -> None:
    model, data = _model(hand_mjcf(_box_build(tmp_path), SIM, tmp_path, SERVO, PADS))
    left, right = (model.jnt_qposadr[model.joint(n).id] for n in ("finger_l", "finger_r"))
    data.ctrl[0] = 0.0
    for _ in range(250):  # 0.5 s
        mujoco.mj_step(model, data)
    assert math.degrees(data.qpos[left]) == pytest.approx(0.0, abs=0.5)
    assert math.degrees(data.qpos[right]) == pytest.approx(math.degrees(data.qpos[left]), abs=0.2)


def test_export_refuses_builds_without_kinematics(tmp_path) -> None:
    rows = _box_build(tmp_path)
    with pytest.raises(ExportError, match="no joints"):
        hand_mjcf(rows, None, tmp_path, SERVO, PADS)
    two = {**SIM, "joints": {**SIM["joints"], "finger_r": {**SIM["joints"]["finger_r"], "drive": "Servo"}}}
    with pytest.raises(ExportError, match="Exactly one joint"):
        hand_mjcf(rows, two, tmp_path, SERVO, PADS)
    missing = {**SIM, "joints": {**SIM["joints"], "finger_r": {**SIM["joints"]["finger_r"], "parts": ["Finger X"]}}}
    with pytest.raises(ExportError, match="not a built part"):
        hand_mjcf(rows, missing, tmp_path, SERVO, PADS)
    empty = {**SIM, "joints": {**SIM["joints"], "finger_r": {**SIM["joints"]["finger_r"], "parts": []}}}
    with pytest.raises(ExportError, match="carries no parts"):
        hand_mjcf(rows, empty, tmp_path, SERVO, PADS)
    named = {**SIM, "joints": {"hand": SIM["joints"]["finger_l"]}}
    with pytest.raises(ExportError, match="other than 'hand'"):
        hand_mjcf(rows, named, tmp_path, SERVO, PADS)


def test_cached_builds_keep_the_kinematics(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setenv("PAI_CACHE", "1")
    out = tmp_path / "out"
    out.mkdir()
    calls = []

    def fake_run(source, params, out_dir, stem, material="PLA", expected_mm=None):
        calls.append(stem)
        for name in (stem + ".stl", stem + ".step", stem + ".glb", stem + "-0.stl"):
            (out_dir / name).write_bytes(b"x")
        row = {"name": "Part", "stl": stem + "-0.stl", "bbox_mm": [0, 0, 0, 1, 1, 1], "mass_g": 1.0}
        return PartBuild([row], [0, 0, 0, 1, 1, 1], 1.0, 1.0, out_dir / (stem + ".stl"), out_dir / (stem + ".step"), out_dir / (stem + ".glb"), SIM)

    monkeypatch.setattr(cad_script, "run_script", fake_run)
    first, cached = run_script_cached("shape = 1", {}, out, "part-a")
    again, cached_again = run_script_cached("shape = 1", {}, out, "part-b")
    assert (cached, cached_again, calls) == (False, True, ["part-a"])
    assert first.sim == again.sim == SIM


def _template_build(tmp_path: Path) -> PartBuild:
    params = {key: default for key, (default, _low, _high) in LIBRARY["gripper"]["params"].items()}
    params.update({"servo_length_mm": SERVO["length_mm"], "servo_width_mm": SERVO["width_mm"], "servo_height_mm": SERVO["height_mm"], "servo_shaft_offset_mm": SERVO["shaft_offset_mm"]})
    return run_script(library_script("gripper"), params, tmp_path, "gripper")


@needs_freecad
def test_template_declares_its_kinematics_and_exports_a_working_hand(tmp_path) -> None:
    build = _template_build(tmp_path)
    assert set(build.sim) == {"joints", "tool", "collision", "grip_surfaces"}
    model, data = _model(hand_mjcf(build.parts, build.sim, tmp_path, SERVO, PADS))
    close = model.jnt_range[model.joint("finger_l").id][1]
    # Open, the pads stand 76 mm apart (jaw_opening_mm); at angle 0 the pad tips meet on the centre line.
    assert _jaw_mm(model, data, close) == pytest.approx(76.0, abs=0.05)
    assert _jaw_mm(model, data, 0.0) == pytest.approx(0.0, abs=0.05)
    assert math.degrees(close) == pytest.approx(29.62, abs=0.01)


@needs_freecad
def test_plain_scripts_build_without_kinematics(tmp_path) -> None:
    build = run_script("shape = Part.makeBox(20, 20, 5)\n", {}, tmp_path, "plate")
    assert build.sim is None


@needs_freecad
def test_bundled_example_hand_matches_the_exporter(tmp_path) -> None:
    """anybuild-robouse ships the exported template (scripts/export_gripper_mjcf.py --example); it must stay current."""

    build = _template_build(tmp_path)
    fresh = ET.fromstring(hand_mjcf(build.parts, build.sim, tmp_path, SERVO, PADS))
    shipped = ET.fromstring(EXAMPLE.read_text(encoding="utf-8"))
    pairs = list(zip(fresh.iter(), shipped.iter(), strict=True))
    for new, old in pairs:
        assert (new.tag, sorted(new.attrib)) == (old.tag, sorted(old.attrib))
        for key, value in new.attrib.items():
            if new.tag == "mesh" and key in ("vertex", "face"):
                continue  # tessellation may differ between FreeCAD versions
            try:
                assert [float(v) for v in value.split()] == pytest.approx([float(v) for v in old.attrib[key].split()], rel=1e-3, abs=1e-6), (new.tag, key)
            except ValueError:
                assert value == old.attrib[key], (new.tag, key)
