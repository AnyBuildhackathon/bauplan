"""An AnyBuild hand (the MJCF file AnyBuild's agent/src/pai_agent/mjcf_export.py writes) for Robo Use's tabletop scene.

The exported hand is in the tool frame (metres, grasp point at the origin, fingers pointing down, closing along y),
with one hinge the servo drives through a position actuator and one hinge geared to it by a joint equality.

The tabletop backend expects its own gripper: a body `hand` at the tool point under a free joint welded to a mocap
target, finger bodies `finger_l` and `finger_r` on joints `fl` and `fr`, and position actuators whose control runs
from 0 (closed) to FINGER_OPEN (0.05, fully open). `Hand.scene_xml` puts the AnyBuild hand in its place: the driven
joint and its body become `fl` and `finger_l`, the geared one `fr` and `finger_r`, the servo's control is rescaled so
that 0 closes and FINGER_OPEN opens fully with the same stiffness and torque at the joint, collision shapes join the
gripper's collision class, and every other name gets the prefix `anybuild_`. The joints stay hinges, in radians.

`Hand.reach` measures the hand with MuJoCo: how wide it opens, at which angle it closes on an object of a given
width, and how far the fingers reach below the tool point, which the task generator needs for its reference solution.
"""

from __future__ import annotations

import copy
import itertools
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import cached_property
from importlib.resources import files

import numpy as np

FINGER_OPEN = 0.05  # robouse.backends.tabletop.scene.FINGER_OPEN, checked by the tests
MOVING = {"contype": "1", "conaffinity": "7"}  # the tabletop scene's class for objects and the gripper
PREFIX = "anybuild_"


class HandError(ValueError):
    """The MJCF is not a hand the tabletop scene can hold; the message says why."""


def example_hand() -> str:
    """The MJCF of AnyBuild's gripper template at its default sizes, with an MG996R servo and printed TPU pads."""

    return files("anybuild_robouse").joinpath("data/example_hand.xml").read_text(encoding="utf-8")


def _floats(text: str | None, count: int, what: str) -> list[float]:
    try:
        values = [float(v) for v in (text or "").split()]
    except ValueError:
        values = []
    if len(values) != count:
        raise HandError(what + " must be " + str(count) + " numbers, not " + repr(text) + ".")
    return values


def _hinge(body: ET.Element, label: str) -> ET.Element:
    joints = body.findall("joint")
    if len(joints) != 1 or joints[0].get("type", "hinge") != "hinge" or not joints[0].get("name"):
        raise HandError(label + " body " + repr(body.get("name")) + " must have exactly one named hinge joint.")
    return joints[0]


@dataclass
class Joint:
    name: str
    body: str
    range_rad: tuple[float, float]
    ref_rad: float


class Hand:
    """A parsed, checked AnyBuild hand."""

    def __init__(self, text: str):
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise HandError("The hand is not valid XML: " + str(exc)) from exc
        if root.tag != "mujoco":
            raise HandError("The hand must be an MJCF file whose root element is <mujoco>.")
        compiler = root.find("compiler")
        if compiler is not None and compiler.get("angle", "degree") != "degree":
            raise HandError("The hand must give its angles in degrees, as the tabletop scene does.")
        bodies = root.findall("worldbody/body")
        if len(bodies) != 1:
            raise HandError("The hand's <worldbody> must hold exactly one body, the hand.")
        actuators = list(root.find("actuator") if root.find("actuator") is not None else [])
        if len(actuators) != 1 or actuators[0].tag != "position" or not actuators[0].get("joint"):
            raise HandError("The hand needs exactly one actuator: a <position> servo on a joint.")
        gear = (actuators[0].get("gear") or "1").split()
        if gear[0] not in ("1", "1.0") or any(v not in ("0", "0.0") for v in gear[1:]) or not actuators[0].get("kp"):
            raise HandError("The servo must act on its joint directly (gear 1) and give its stiffness (kp).")
        couplings = root.findall("equality/joint")
        if len(couplings) != 1:
            raise HandError("The hand needs exactly one joint equality: the finger geared to the driven one.")
        self.text = text
        self.root = root
        self.body = bodies[0]
        self.servo = actuators[0]
        self.coupling = couplings[0]
        children = {_hinge(child, "Finger").get("name"): child for child in self.body.findall("body")}
        driver, follower = self.servo.get("joint"), self.coupling.get("joint1")
        if driver not in children or follower not in children or self.coupling.get("joint2") != driver or follower == driver:
            raise HandError("The servo must drive one finger body of the hand, and the equality gear another one to it.")
        poly = _floats(self.coupling.get("polycoef", "0 1 0 0 0"), 5, "The equality's polycoef")
        if poly[0] != 0 or poly[1] <= 0 or any(poly[2:]):
            raise HandError("The geared finger must follow the driven one in proportion (polycoef 0 ratio 0 0 0).")
        self.ratio = poly[1]
        self.driver = self._joint(children[driver])
        self.follower = self._joint(children[follower])
        low, high = self.driver.range_rad
        ctrl = _floats(self.servo.get("ctrlrange"), 2, "The servo's ctrlrange")
        if low != 0 or not math.isclose(ctrl[0], 0.0, abs_tol=1e-9) or not math.isclose(ctrl[1], high, rel_tol=1e-4):
            raise HandError("The driven joint must open from 0 (closed), and the servo's ctrlrange must span its range.")
        texts = {t.get("name"): t.get("data", "") for t in root.findall("custom/text")}
        self.servo_name = texts.get("anybuild_servo", "servo")
        self.pads_name = texts.get("anybuild_pads", "pads")

    @staticmethod
    def _joint(body: ET.Element) -> Joint:
        joint = _hinge(body, "Finger")
        low, high = (math.radians(v) for v in _floats(joint.get("range"), 2, "Joint " + repr(joint.get("name")) + " range"))
        return Joint(str(joint.get("name")), str(body.get("name")), (low, high), math.radians(float(joint.get("ref", "0"))))

    @property
    def open_rad(self) -> float:
        return self.driver.range_rad[1]

    @property
    def holding_torque_nm(self) -> float:
        return max(abs(v) for v in _floats(self.servo.get("forcerange"), 2, "The servo's forcerange"))

    def follower_angle(self, driver_angle: float) -> float:
        """The geared finger's angle: it follows the driven one in proportion, from the pose the parts are built in."""

        return self.follower.ref_rad + self.ratio * (driver_angle - self.driver.ref_rad)

    # ---- the tabletop scene ----------------------------------------------------------------------------------------

    def scene_xml(self, scene: str) -> str:
        """The tabletop scene's MJCF with this hand in place of the built-in gripper."""

        world = ET.fromstring(scene)
        worldbody = world.find("worldbody")
        old = worldbody.find("body[@name='hand']") if worldbody is not None else None
        if old is None:
            raise HandError("The scene has no body named hand to replace.")
        names = {
            "body": {self.body.get("name"): "hand", self.driver.body: "finger_l", self.follower.body: "finger_r"},
            "joint": {self.driver.name: "fl", self.follower.name: "fr"},
        }
        hand = copy.deepcopy(self.body)
        for element in hand.iter():
            kind = element.tag if element.tag in ("body", "joint") else None
            name = element.get("name")
            if kind and name in names[kind]:
                element.set("name", names[kind][name])
            elif name and not (element.tag == "site" and name == "tcp"):
                element.set("name", PREFIX + name)
            if element.tag == "body":
                element.set("gravcomp", "1")
            if element.tag == "geom":
                if element.get("mesh"):
                    element.set("mesh", PREFIX + element.get("mesh"))
                if (element.get("contype"), element.get("conaffinity")) != ("0", "0"):
                    element.attrib.update(MOVING)
        hand.set("pos", old.get("pos", "0 0 0"))
        # The scene's own free joint (welded to the mocap target) and its wrist camera, if the task has one, stay.
        kept = [child for child in old if child.tag in ("freejoint", "camera")]
        for index, child in enumerate(kept):
            hand.insert(index, child)
        worldbody.insert(list(worldbody).index(old), hand)
        worldbody.remove(old)

        asset = world.find("asset")
        if asset is None:
            asset = ET.SubElement(world, "asset")
        for mesh in self.root.findall("asset/mesh"):
            mesh = copy.deepcopy(mesh)
            mesh.set("name", PREFIX + mesh.get("name", ""))
            asset.append(mesh)

        contact = world.find("contact")
        if contact is None:
            contact = ET.SubElement(world, "contact")
        for exclude in list(contact):
            if {exclude.get("body1"), exclude.get("body2")} & {"finger_l", "finger_r"}:
                contact.remove(exclude)
        for exclude in self.root.findall("contact/exclude"):
            body1, body2 = (names["body"].get(exclude.get(k), PREFIX + str(exclude.get(k))) for k in ("body1", "body2"))
            ET.SubElement(contact, "exclude", {"body1": body1, "body2": body2})

        equality = world.find("equality")
        if equality is None:
            equality = ET.SubElement(world, "equality")
        coupling = copy.deepcopy(self.coupling)
        coupling.attrib.update({"name": PREFIX + self.coupling.get("name", "gears"), "joint1": "fr", "joint2": "fl"})
        equality.append(coupling)

        # The base backend sets every control to FINGER_OPEN * (1 - grip) / 2, so the servo is the only actuator, and
        # its control maps 0 .. FINGER_OPEN onto the driven joint's range with the same stiffness and torque.
        gear = FINGER_OPEN / self.open_rad
        kp = float(self.servo.get("kp", "1"))
        actuator = world.find("actuator")
        if actuator is None:
            actuator = ET.SubElement(world, "actuator")
        for child in list(actuator):
            actuator.remove(child)
        torque = self.holding_torque_nm
        ET.SubElement(
            actuator,
            "position",
            {
                "name": PREFIX + self.servo.get("name", "servo"),
                "joint": "fl",
                "gear": f"{gear:.6g}",
                "kp": f"{kp / gear**2:.6g}",
                "ctrlrange": f"0 {FINGER_OPEN:g}",
                "forcerange": f"{-torque / gear:.6g} {torque / gear:.6g}",
            },
        )

        texts = self.root.findall("custom/text")
        if texts:
            custom = world.find("custom")
            if custom is None:
                custom = ET.SubElement(world, "custom")
            for text in texts:
                custom.append(copy.deepcopy(text))
        return ET.tostring(world, encoding="unicode")

    # ---- measurements ----------------------------------------------------------------------------------------------

    @cached_property
    def _model(self):
        import mujoco

        model = mujoco.MjModel.from_xml_string(self.text)
        return model, mujoco.MjData(model)

    def _boxes(self, body: str, angle: float, grip_only: bool = False) -> list[np.ndarray]:
        """The corners (8 x 3, tool frame) of each collision box of a body, with the driven joint at `angle`."""

        import mujoco

        model, data = self._model
        mujoco.mj_resetData(model, data)
        data.qpos[model.jnt_qposadr[model.joint(self.driver.name).id]] = angle
        data.qpos[model.jnt_qposadr[model.joint(self.follower.name).id]] = self.follower_angle(angle)
        mujoco.mj_kinematics(model, data)
        bid = model.body(body).id
        boxes = []
        for g in range(model.ngeom):
            if model.geom_bodyid[g] != bid or model.geom_type[g] != mujoco.mjtGeom.mjGEOM_BOX:
                continue
            if model.geom_contype[g] == 0 and model.geom_conaffinity[g] == 0:
                continue
            if grip_only and model.geom_priority[g] <= 0:
                continue
            rot = data.geom_xmat[g].reshape(3, 3)
            signs = np.array(list(itertools.product((-1.0, 1.0), repeat=3)))
            boxes.append(data.geom_xpos[g] + (signs * model.geom_size[g]) @ rot.T)
        return boxes

    def _corners(self, angle: float, grip_only: bool) -> tuple[np.ndarray, np.ndarray]:
        """All corners of the fingers' collision boxes at a driven-joint angle, (driver side, follower side)."""

        sides = []
        for body in (self.driver.body, self.follower.body):
            boxes = self._boxes(body, angle, grip_only)
            if not boxes:
                raise HandError("Finger body " + repr(body) + " has no collision boxes" + (" on its grip surfaces." if grip_only else "."))
            sides.append(np.concatenate(boxes))
        return sides[0], sides[1]

    def ceiling_m(self, half_width_m: float | None = None) -> float:
        """How far above the tool point the hand itself (palm, servo) starts: an object between the fingers stops there.
        With `half_width_m`, only the parts over a square object of that half width, centred under the tool point."""

        lowest = math.inf
        for corners in self._boxes(str(self.body.get("name")), self.open_rad):
            low, high = corners.min(axis=0), corners.max(axis=0)
            if half_width_m is None or (low[0] < half_width_m and high[0] > -half_width_m and low[1] < half_width_m and high[1] > -half_width_m):
                lowest = min(lowest, float(low[2]))
        return lowest

    def jaw_m(self, angle: float) -> float:
        """The gap between the grip surfaces along the closing axis (y) at a driven-joint angle."""

        left, right = self._corners(angle, grip_only=True)
        if left[:, 1].mean() > right[:, 1].mean():
            left, right = right, left
        return float(right[:, 1].min() - left[:, 1].max())

    def grip_angle(self, width_m: float) -> float:
        """The driven-joint angle at which the grip surfaces close to `width_m`."""

        low, high = 0.0, self.open_rad
        if not self.jaw_m(high) > width_m:
            raise HandError(f"The gripper opens {self.jaw_m(high) * 1000:.1f} mm, not wider than {width_m * 1000:.1f} mm.")
        for _ in range(40):
            mid = (low + high) / 2.0
            low, high = (mid, high) if self.jaw_m(mid) < width_m else (low, mid)
        return (low + high) / 2.0

    def reach_m(self, low: float, high: float, grip_only: bool = False) -> float:
        """How far the fingers (or only their grip surfaces) reach below the tool point, over driven-joint angles."""

        depth = 0.0
        for angle in np.linspace(low, high, 25):
            left, right = self._corners(float(angle), grip_only)
            depth = max(depth, -float(min(left[:, 2].min(), right[:, 2].min())))
        return depth
