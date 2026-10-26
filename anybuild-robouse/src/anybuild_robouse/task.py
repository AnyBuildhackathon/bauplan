"""Robo Use tasks from an AnyBuild design brief: put the object the gripper was designed for in a bowl, or on a pad.

AnyBuild's gripper brief names the object: `object_mass_g` and `object_width_mm` (the width the gripper must open
around). The task stands a cube of that width and mass on the tabletop scene, with a bowl (or a pad) to put it in,
and the gripper is the hand AnyBuild exported (the `anybuild_hand` MJCF, carried in task.md).

The reference solution (oracle/solve.sh) is a plain list of `robo` commands, computed from the scene and the hand:
above the cube with the fingers open, down to the grasp height, close, lift, over the target, down, open, up, done.
The grasp height keeps the fingertips off the table over the angles the fingers swing through before they meet the
cube, and keeps the cube's top off the palm and the servo; the grip surfaces must still reach a centimetre down the
cube's side. A brief the hand cannot grasp at all is refused with the reason. Whether the grasp holds is the point of the benchmark, so a weak design makes a valid
task whose reference solution fails: `robouse tasks check` then says so.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from robouse.backends.embodied import VERIFY_SH
from robouse.backends.tabletop.scene import HAND_HI
from robouse.core.prompts import ROBO_USAGE
from robouse.tasks import SCHEMA_VERSION, unwrap_markdown

from anybuild_robouse.hand import Hand, HandError

CUBE_XY = (-0.13, -0.06)
TARGET_XY = (0.12, 0.10)
BOWL_HEIGHT = 0.035  # the tabletop bowl's default wall height
BOWL_FLOOR = 0.006
CLEARANCE = 0.005  # fingertips above the table at the grasp
GRIP_OVERLAP = 0.01  # how far the grip surfaces must reach down the cube's side
OPEN_MARGIN = 0.004  # free space between the open fingers and the cube, both sides together
GOALS = ("bowl", "pad")


class TaskError(ValueError):
    """The brief cannot become a task for this hand; the message says why."""


@dataclass
class Brief:
    """The object a gripper is designed for, as AnyBuild's gripper brief has it, and where it should go."""

    object_mass_g: float
    object_width_mm: float
    goal: str = "bowl"

    @classmethod
    def from_dict(cls, data: dict) -> Brief:
        try:
            brief = cls(float(data["object_mass_g"]), float(data["object_width_mm"]), str(data.get("goal") or "bowl"))
        except (KeyError, TypeError, ValueError) as exc:
            raise TaskError("The brief needs object_mass_g and object_width_mm as numbers.") from exc
        if brief.object_mass_g <= 0 or brief.object_width_mm <= 0:
            raise TaskError("object_mass_g and object_width_mm must be positive.")
        if brief.goal not in GOALS:
            raise TaskError("goal must be one of " + ", ".join(GOALS) + ".")
        return brief


@dataclass
class Plan:
    """The scene and the reference solution's waypoints, in metres."""

    side: float
    density: float
    grip_angle: float
    approach_z: float
    grasp_z: float
    carry_z: float
    release_z: float
    open_mm: float
    reach_open_mm: float
    reach_max_mm: float
    ceiling_mm: float


def plan(hand: Hand, brief: Brief) -> Plan:
    side = brief.object_width_mm / 1000.0
    open_m = hand.jaw_m(hand.open_rad)
    if side > open_m - OPEN_MARGIN:
        raise TaskError(
            f"The cube is {side * 1000:.0f} mm wide, but this gripper opens {open_m * 1000:.1f} mm; it needs "
            f"{OPEN_MARGIN * 1000:.0f} mm to spare to reach around it."
        )
    try:
        angle = hand.grip_angle(side)
    except HandError as exc:
        raise TaskError(str(exc)) from exc
    reach = hand.reach_m(angle, hand.open_rad)
    grasp = max(side / 2.0, reach + CLEARANCE, side + CLEARANCE - hand.ceiling_m(side / 2.0 + CLEARANCE))
    pads = hand.reach_m(angle, angle, grip_only=True)
    if grasp - pads > side - GRIP_OVERLAP:
        raise TaskError(
            f"The lowest grasp this hand allows puts its tool point {grasp * 1000:.0f} mm up (fingertips off the table, the "
            f"cube's top under the palm and servo), where the pads touch only the top {max(0.0, side - (grasp - pads)) * 1000:.0f} mm "
            f"of the {side * 1000:.0f} mm cube; they need {GRIP_OVERLAP * 1000:.0f} mm."
        )
    reach_open = hand.reach_m(hand.open_rad, hand.open_rad)
    approach = side + reach_open + 0.03
    floor = BOWL_FLOOR if brief.goal == "bowl" else 0.0
    rim = BOWL_HEIGHT if brief.goal == "bowl" else 0.0
    carry = max(approach, rim + 0.02 + grasp)
    if carry > HAND_HI[2]:
        raise TaskError(f"Carrying the cube needs the hand {carry:.2f} m up; the scene allows {HAND_HI[2]:.2f} m.")
    return Plan(
        side=side,
        density=brief.object_mass_g / 1000.0 / side**3,
        grip_angle=angle,
        approach_z=approach,
        grasp_z=grasp,
        carry_z=carry,
        release_z=floor + 0.01 + grasp,
        open_mm=open_m * 1000.0,
        reach_open_mm=reach_open * 1000.0,
        reach_max_mm=hand.reach_m(0.0, hand.open_rad) * 1000.0,
        ceiling_mm=hand.ceiling_m() * 1000.0,
    )


def task_id(brief: Brief) -> str:
    target = "in-bowl" if brief.goal == "bowl" else "on-pad"
    return f"anybuild-gripper-cube-{brief.object_width_mm:g}mm-{brief.object_mass_g:g}g-{target}".replace(".", "p")


def scenario(brief: Brief, p: Plan, tid: str) -> dict:
    half = round(p.side / 2.0, 5)
    cube = {"name": "cube", "kind": "box", "color": "red", "pos": list(CUBE_XY), "size": [half] * 3, "density": round(p.density, 3)}
    if brief.goal == "bowl":
        radius = round(max(0.07, half * math.sqrt(2.0) + 0.02), 4)
        fixture = {"name": "bowl", "kind": "bowl", "pos": list(TARGET_XY), "radius": radius, "height": BOWL_HEIGHT, "color": "white"}
        goal = {"type": "in", "obj": "cube", "container": "bowl"}
    else:
        size = round(half + 0.02, 4)
        fixture = {"name": "target", "kind": "pad", "pos": list(TARGET_XY), "size": [size, size], "color": "green"}
        goal = {"type": "on_pad", "obj": "cube", "pad": "target", "full": True}
    return {"id": tid, "title": _title(brief), "objects": [cube], "fixtures": [fixture], "goals": [goal]}


def _title(brief: Brief) -> str:
    return "Put the cube " + ("in the bowl" if brief.goal == "bowl" else "on the green pad") + " with an AnyBuild gripper"


def _f(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")


def oracle_sh(brief: Brief, p: Plan) -> str:
    x0, y0 = CUBE_XY
    x1, y1 = TARGET_XY
    move = "robo move-to {x} {y} {z} --grip {g} --tol {tol} --max-steps 150"
    lines = [
        move.format(x=_f(x0), y=_f(y0), z=_f(p.approach_z), g=-1, tol=0.004),
        move.format(x=_f(x0), y=_f(y0), z=_f(p.grasp_z), g=-1, tol=0.002),
        "robo grip 1 --steps 25",
        move.format(x=_f(x0), y=_f(y0), z=_f(p.carry_z), g=1, tol=0.004),
        move.format(x=_f(x1), y=_f(y1), z=_f(p.carry_z), g=1, tol=0.004),
        move.format(x=_f(x1), y=_f(y1), z=_f(p.release_z), g=1, tol=0.003),
        "robo grip -1 --steps 20",
        move.format(x=_f(x1), y=_f(y1), z=_f(p.approach_z), g=-1, tol=0.006),
        'robo done "the cube is ' + ("in the bowl" if brief.goal == "bowl" else "on the pad") + '"',
    ]
    return (
        "#!/bin/bash\n"
        "# Reference solution: picks the cube up with the AnyBuild gripper and puts it down on the target, through `robo` only.\n"
        "# Written by anybuild-robouse from the scene and the hand: approach, grasp height, carry and release heights.\n"
        "set -euo pipefail\n" + "\n".join(lines) + "\n"
    )


def instruction(hand: Hand, brief: Brief, p: Plan) -> str:
    where = "into the white bowl" if brief.goal == "bowl" else "onto the green pad, entirely on it"
    rest = "resting on the bowl's floor" if brief.goal == "bowl" else "resting on the table, within the pad's square"
    fixtures = (
        "- `fixtures`: the `bowl`, with `pos`, `floor_z`, `rim_z` and `inner_diameter`."
        if brief.goal == "bowl"
        else "- `fixtures`: the `target` pad, a flat green square on the table, with `pos` and `size`."
    )
    return f"""# {_title(brief)}

A two-finger gripper designed in AnyBuild hangs over a table (a floating gripper, no arm). Its fingers swing on two meshing gears that one servo turns ({hand.servo_name}, {hand.pads_name}): they close along the y axis, and the pads tilt inward as they close. The camera looks at the table from the front: x points to the right, y away from the camera (toward the back of the table), z up; the table top is at z = 0.

**Goal:** Put the red cube ({brief.object_width_mm:g} mm on each side, {brief.object_mass_g:g} g) {where}. It is judged on the final state: the cube {rest}, and released (not touching the fingers).

## What `robo observe` shows

- `hand_pos`: the gripper's tool point (between the pad centres), metres. `gripper_open`: 0 = closed (the pad tips meet), 1 = fully open ({p.open_mm:.0f} mm between the pads). `holding`: names of objects touching the fingers.
- `objects`: the `cube`, with `kind`, `color`, `pos` (centre, metres), `size` (full x/y/z extent), `yaw_deg`, `half_height` (current half extent along z) and `tilt_deg` (0 = upright).
{fixtures}

## Gripper

The grip value is the servo's position target, not a hold command: +1 = closed, -1 = fully open, and values in between turn the servo part way (opening angle = full angle * (1 - G) / 2). On an object the servo pushes with up to its holding torque, {hand.holding_torque_nm:.2f} N m at the gear axle, so keep sending +1 to hold it. The fingertips reach {p.reach_open_mm:.0f} mm below the tool point when open and up to {p.reach_max_mm:.0f} mm while they swing shut; the table stops them. The palm and the servo start {p.ceiling_mm:.0f} mm above the tool point, so an object between the fingers that reaches that high stops the hand. `robo move-to X Y Z --grip G` applies G on every step of the move, starting with the first; without `--grip`, the last grip value is kept. `robo grip G --steps N` holds the hand still for N steps while applying G. The same values apply to the GRIP argument of `robo act`.

{ROBO_USAGE}"""


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str)


def write_task(out_dir: Path, hand_xml: str, brief: Brief, tid: str | None = None) -> Path:
    """Writes the task folder (task.md, oracle/solve.sh, verifier/test.sh) under out_dir and returns its path."""

    try:
        hand = Hand(hand_xml)
    except HandError as exc:
        raise TaskError(str(exc)) from exc
    p = plan(hand, brief)
    tid = tid or task_id(brief)
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", tid):
        raise TaskError("The task id must be lower-case letters, digits, dots, dashes and underscores.")
    meta = {
        "schema_version": SCHEMA_VERSION,
        "task": {"name": "anybuild/" + tid, "description": _title(brief)},
        "metadata": {
            "source_benchmark": "AnyBuild",
            "category": "manipulation",
            "difficulty": "medium",
            "tags": ["anybuild", "designed-gripper", "pick-place"],
            "anybuild": {
                "brief": {"object_mass_g": brief.object_mass_g, "object_width_mm": brief.object_width_mm, "goal": brief.goal},
                "servo": hand.servo_name,
                "pads": hand.pads_name,
                "opening_mm": round(p.open_mm, 1),
                "grip_angle_deg": round(math.degrees(p.grip_angle), 2),
            },
        },
        "agent": {"timeout_sec": 900},
        "verifier": {"timeout_sec": 120},
        "robouse": {
            "id": tid,
            "backend": "anybuild-gripper",
            "seed": 0,
            "max_steps": 800,
            "camera": "front",
            "skills": True,
            "success_mode": "final",
            "scenario": scenario(brief, p, tid),
            "anybuild_hand": hand_xml if hand_xml.endswith("\n") else hand_xml + "\n",
        },
    }
    folder = Path(out_dir) / tid
    (folder / "oracle").mkdir(parents=True, exist_ok=True)
    (folder / "verifier").mkdir(parents=True, exist_ok=True)
    frontmatter = yaml.dump(meta, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=10**6)
    if "---" in frontmatter:  # Robo Use splits task.md at the first two "---"
        raise TaskError("The hand or the brief contains '---', which would break task.md's frontmatter.")
    (folder / "task.md").write_text("---\n" + frontmatter + "---\n\n" + unwrap_markdown(instruction(hand, brief, p)), encoding="utf-8")
    for rel, body in (("oracle/solve.sh", oracle_sh(brief, p)), ("verifier/test.sh", VERIFY_SH)):
        (folder / rel).write_text(body, encoding="utf-8")
        (folder / rel).chmod(0o755)
    return folder
