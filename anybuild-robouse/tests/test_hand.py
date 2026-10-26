"""The AnyBuild hand in Robo Use's tabletop scene: MuJoCo 3.3.0 loads it, the swap keeps the scene's contract, and the
backend drives the hinges.

Run with: cd anybuild-robouse && uv run pytest
"""

from __future__ import annotations

import math
import re

import mujoco
import numpy as np
import pytest
from robouse.backends import backend_class
from robouse.backends.tabletop import scene as tabletop_scene
from robouse.backends.tabletop.scene import FINGER_OPEN, HAND_HOME, build_xml

from anybuild_robouse import hand as hand_module
from anybuild_robouse.backend import AnyBuildGripperBackend
from anybuild_robouse.hand import Hand, HandError, example_hand

SCENARIO = {
    "id": "unit",
    "objects": [{"name": "cube", "kind": "box", "color": "red", "pos": [-0.13, -0.06], "size": [0.02, 0.02, 0.02]}],
    "fixtures": [{"name": "bowl", "kind": "bowl", "pos": [0.12, 0.1], "radius": 0.07}],
    "goals": [{"type": "in", "obj": "cube", "container": "bowl"}],
}


@pytest.fixture(scope="module")
def hand() -> Hand:
    return Hand(example_hand())


def test_robouse_runs_the_pinned_mujoco() -> None:
    assert mujoco.__version__ == "3.3.0"
    assert hand_module.FINGER_OPEN == tabletop_scene.FINGER_OPEN


def test_the_entry_point_finds_the_backend() -> None:
    assert backend_class("anybuild-gripper") is AnyBuildGripperBackend


def test_example_hand_loads_under_mujoco_3_3(hand) -> None:
    model = mujoco.MjModel.from_xml_string(example_hand())
    assert [model.body(i).name for i in range(model.nbody)] == ["world", "hand", "finger_l", "finger_r"]
    assert (model.nmesh, model.nu, model.neq) == (8, 1, 1)
    assert (hand.driver.name, hand.follower.name, hand.ratio) == ("finger_l", "finger_r", 1.0)
    assert (hand.servo_name, hand.pads_name) == ("TowerPro MG996R servo", "Printed TPU finger pads")
    assert hand.holding_torque_nm == pytest.approx(0.7 * 9.4 * 9.80665 / 100.0, rel=1e-4)


def test_hand_measures_match_the_cad(hand) -> None:
    assert math.degrees(hand.open_rad) == pytest.approx(29.62, abs=0.01)
    assert hand.jaw_m(hand.open_rad) * 1000 == pytest.approx(76.0, abs=0.05)  # jaw_opening_mm
    assert hand.jaw_m(0.0) * 1000 == pytest.approx(0.0, abs=0.05)  # the pad tips meet
    assert hand.jaw_m(hand.grip_angle(0.04)) * 1000 == pytest.approx(40.0, abs=0.01)
    # Open, the finger caps end 15.75 + 4.5 mm below the tool point; swinging shut they dip lower.
    assert hand.reach_m(hand.open_rad, hand.open_rad) * 1000 == pytest.approx(20.25, abs=0.01)
    assert hand.reach_m(0.0, hand.open_rad) > hand.reach_m(hand.open_rad, hand.open_rad)
    # The servo hangs beside the finger roots, from 23.55 mm above the tool point; a 16 mm object passes beside it.
    assert hand.ceiling_m() * 1000 == pytest.approx(23.55, abs=0.01)
    assert hand.ceiling_m(0.008) > hand.ceiling_m(0.033)
    with pytest.raises(HandError, match="opens 76.0 mm"):
        hand.grip_angle(0.08)


def test_the_swap_keeps_the_scene_contract(hand) -> None:
    text = hand.scene_xml(build_xml(SCENARIO))
    model = mujoco.MjModel.from_xml_string(text)
    names = {model.body(i).name for i in range(model.nbody)}
    assert {"hand", "finger_l", "finger_r", "mocap", "obj_cube", "fx_bowl"} <= names
    assert model.jnt_type[model.joint("hand_free").id] == mujoco.mjtJoint.mjJNT_FREE
    for joint in ("fl", "fr"):
        assert model.jnt_type[model.joint(joint).id] == mujoco.mjtJoint.mjJNT_HINGE
    assert model.body_pos[model.body("hand").id] == pytest.approx(HAND_HOME)
    # The stock gripper's geoms are gone; the AnyBuild ones carry the prefix, and the tool point keeps its name.
    geoms = {model.geom(i).name for i in range(model.ngeom)}
    assert not {"palm", "wrist", "finger_l", "finger_r"} & geoms
    assert {"anybuild_palm", "anybuild_pad_l_c0", "anybuild_servo_c0"} <= geoms
    assert model.site("tcp").id >= 0
    # The mocap weld stays, and the gears join it.
    kinds = sorted(int(t) for t in model.eq_type)
    assert kinds == sorted([int(mujoco.mjtEq.mjEQ_WELD), int(mujoco.mjtEq.mjEQ_JOINT)])
    # One actuator: control 0 .. FINGER_OPEN spans the hinge's range with the servo's own stiffness and torque.
    assert model.nu == 1 and model.actuator_trnid[0][0] == model.joint("fl").id
    gear = model.actuator_gear[0][0]
    assert model.actuator_ctrlrange[0] == pytest.approx([0.0, FINGER_OPEN])
    assert FINGER_OPEN / gear == pytest.approx(hand.open_rad, rel=1e-5)
    servo = mujoco.MjModel.from_xml_string(example_hand())
    assert model.actuator_gainprm[0][0] * gear**2 == pytest.approx(servo.actuator_gainprm[0][0], rel=1e-4)
    assert model.actuator_forcerange[0][1] * gear == pytest.approx(hand.holding_torque_nm, rel=1e-4)
    # Collision boxes take the scene's gripper class; meshes still collide with nothing.
    pad, mesh = model.geom("anybuild_pad_l_c0").id, model.geom("anybuild_pad_l").id
    assert (model.geom_contype[pad], model.geom_conaffinity[pad]) == (1, 7)
    assert (model.geom_contype[mesh], model.geom_conaffinity[mesh]) == (0, 0)


def test_backend_opens_the_hinges_and_reports_the_opening() -> None:
    backend = AnyBuildGripperBackend({"id": "unit", "anybuild_hand": example_hand(), "scenario": SCENARIO})
    backend.reset(0)
    model, data = backend.model, backend.data
    left, right = (model.jnt_qposadr[model.joint(n).id] for n in ("fl", "fr"))
    assert data.qpos[left] == pytest.approx(backend.hand.open_rad)
    assert data.qpos[right] == pytest.approx(backend.hand.open_rad)
    state = backend.observe()
    assert state["gripper_open"] == 1.0
    assert state["hand_pos"] == pytest.approx(HAND_HOME, abs=1e-3)
    for _ in range(15):  # close in the air: about 0.3 s
        backend.step([0.0, 0.0, 0.0, 1.0])
    assert backend.observe()["gripper_open"] == pytest.approx(0.0, abs=0.02)
    assert data.qpos[left] == pytest.approx(data.qpos[right], abs=math.radians(0.2))
    for _ in range(15):
        backend.step([0.0, 0.0, 0.0, 0.0])  # half open
    assert backend.observe()["gripper_open"] == pytest.approx(0.5, abs=0.02)
    assert "opening angle" in backend.action_spec.doc and "10 cm" not in backend.action_spec.doc
    backend.close()


def test_backend_holds_a_cube_centred_between_the_fingers() -> None:
    """The gears keep both fingers at the same angle under the servo's torque, so the cube stays centred."""

    backend = AnyBuildGripperBackend({"id": "unit", "anybuild_hand": example_hand(), "scenario": SCENARIO})
    backend.reset(0)

    def go(target, grip):
        for _ in range(150):
            delta = np.asarray(target) - backend.hand_pos()
            if np.linalg.norm(delta) < 0.002:
                break
            backend.step(list(np.clip(delta * 10, -1, 1)) + [grip])

    go([-0.13, -0.06, 0.12], -1.0)
    go([-0.13, -0.06, 0.025], -1.0)
    for _ in range(25):
        backend.step([0.0, 0.0, 0.0, 1.0])
    go([-0.13, -0.06, 0.12], 1.0)
    state = backend.observe()
    assert state["holding"] == ["cube"]
    assert state["objects"]["cube"]["pos"][:2] == pytest.approx([-0.13, -0.06], abs=0.002)
    model, data = backend.model, backend.data
    left, right = (data.qpos[model.jnt_qposadr[model.joint(n).id]] for n in ("fl", "fr"))
    assert math.degrees(abs(left - right)) < 0.5
    backend.close()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda t: t.replace('<compiler angle="degree"/>', '<compiler angle="radian"/>'), "degrees"),
        (lambda t: re.sub(r"<actuator>.*</actuator>", "<actuator/>", t, flags=re.S), "exactly one actuator"),
        (lambda t: re.sub(r"<equality>.*</equality>", "<equality/>", t, flags=re.S), "exactly one joint equality"),
        (lambda t: t.replace('polycoef="0 1 0 0 0"', 'polycoef="0 1 0.5 0 0"'), "in proportion"),
        (lambda t: t.replace('range="0 29.624" ref="29.624" damping', 'range="5 29.624" ref="29.624" damping'), "open from 0"),
        (lambda t: t.replace('<position name="servo"', '<position name="servo" gear="2"'), "gear 1"),
        (lambda t: "<robot/>", "<mujoco>"),
    ],
)
def test_hands_the_scene_cannot_hold_are_refused(change, message) -> None:
    with pytest.raises(HandError, match=message):
        Hand(change(example_hand()))


def test_a_task_without_a_hand_is_refused() -> None:
    with pytest.raises(ValueError, match="anybuild_hand"):
        AnyBuildGripperBackend({"id": "unit", "scenario": SCENARIO})
