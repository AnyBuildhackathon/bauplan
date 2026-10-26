"""The `anybuild-gripper` Robo Use backend: the tabletop scene with an AnyBuild gripper in place of the built-in one.

Robo Use finds it through the `robouse.backends` entry point. A task names it with `backend: anybuild-gripper` and
carries the exported hand's MJCF in `anybuild_hand`, so the task folder holds everything its episode needs.
Everything else (scenario, goals, safety rules, skills, scoring) is the tabletop backend's.

Robo Use 0.6.1 has no hook to swap the tabletop gripper, so while the base class builds its model, its scene builder
is wrapped to put the AnyBuild hand in (Hand.scene_xml). The package pins robouse==0.6.1 and its tests check that seam.
The base class also treats the finger joints as slides: reset() puts the hinges back to fully open, and observe()
reports `gripper_open` from the angles.
"""

from __future__ import annotations

import contextlib
from dataclasses import replace

from robouse.backends.tabletop import backend as tabletop
from robouse.backends.tabletop.backend import TabletopBackend

from anybuild_robouse.hand import Hand

GRIP_DOC = (
    "dx/dy/dz: gripper velocity, about 1 cm per unit per step; grip: the servo's position target, +1 closed, "
    "-1 fully open, values in between turn it part way (opening angle = full angle * (1 - grip) / 2)"
)


@contextlib.contextmanager
def _scene_with(hand: Hand):
    build = tabletop.build_xml
    tabletop.build_xml = lambda scenario: hand.scene_xml(build(scenario))
    try:
        yield
    finally:
        tabletop.build_xml = build


class AnyBuildGripperBackend(TabletopBackend):
    name = "anybuild-gripper"
    robot_name = "anybuild-gripper"

    def __init__(self, spec: dict):
        text = spec.get("anybuild_hand")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("an anybuild-gripper task needs `anybuild_hand`: the MJCF that AnyBuild exported for the gripper")
        self.hand = Hand(text)
        with _scene_with(self.hand):
            super().__init__(spec)
        self.action_spec = replace(self.action_spec, doc=GRIP_DOC)
        m = self.model
        self._fingers = [
            (m.jnt_qposadr[m.joint(name).id], m.jnt_dofadr[m.joint(name).id], top)
            for name, top in (("fl", self.hand.open_rad), ("fr", self.hand.follower_angle(self.hand.open_rad)))
        ]

    def reset(self, seed: int) -> None:
        super().reset(seed)
        # The base class wrote its slider travel (0.05) into fl and fr; they are hinges, so they start fully open.
        for qpos, dof, top in self._fingers:
            self.data.qpos[qpos] = top
            self.data.qvel[dof] = 0.0
        self._mj.mj_forward(self.model, self.data)

    def opening(self) -> float:
        """0 closed (the grip surfaces meet), 1 fully open."""

        share = [float(self.data.qpos[qpos]) / top for qpos, _dof, top in self._fingers]
        return min(1.0, max(0.0, sum(share) / len(share)))

    def observe(self) -> dict:
        out = super().observe()
        out["gripper_open"] = round(self.opening(), 3)
        return out
