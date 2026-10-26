"""MuJoCo MJCF for a gripper built from a FreeCAD template: its parts, the joints they turn on, the servo that drives them.

The template declares its kinematics next to its parts (agent/freecad/library/gripper.py), and the part harness
passes them on as `sim` (PartBuild.sim, state.part["sim"]):
- `joints`: one entry per moving body, keyed by its name: the parts it carries, its hinge (`pivot_mm`, `axis`,
  `range_deg`, and `ref_deg`, the angle the parts are built at), and either `drive` (the bought part that turns it,
  the servo) or `follows` and `ratio` (geared to another joint, from the pose the parts are built in);
- `tool`: the grasp point (`point_mm`), the direction the fingers point (`approach`) and close (`closing`);
- `collision`: boxes per part where its bounding box fits badly, an empty list for a part that never touches anything;
  every other part collides as its bounding box;
- `grip_surfaces`: the parts that touch the object; the pads' catalog friction applies to them.

hand_mjcf writes one self-contained MJCF file: every part's STL inline as a mesh that is shown but does not collide,
the collision boxes, each body's mass and centre of mass from CAD (the servo's mass from the catalog) with the
inertia of the parts' bounding boxes, the hinges, the gears as a stiff joint equality, and the servo as a position actuator
on the joint it drives. The servo pushes with its holding torque (HOLD_FRACTION of the stall torque, as in the grip
calculation) from 3 degrees off target, and turns 60 degrees in 0.2 s, the usual rating of these hobby servos.

Frame: the tool frame in metres. The origin is the grasp point, the fingers point down (-z) and close along y, as
Robo Use's tabletop gripper does. The root body `hand` has no joint, so the file loads on its own as a hand fixed in
space; a scene puts it under its own free joint or weld.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from xml.sax.saxutils import quoteattr

import numpy as np

from pai_agent.cad_script import PartBuild
from pai_agent.mesh_export import read_stl_vertices
from pai_agent.tools.gripper import GRAVITY, HOLD_FRACTION

SATURATION_RAD = math.radians(3.0)
SPEED_RAD_S = math.radians(60.0) / 0.2
DAMPING_RATIO = 0.7
PRINTED_FRICTION = 0.4  # printed plastic on cardboard or painted metal; the grip surfaces take the pads' friction
# Meshing gears barely give, but with MuJoCo's default softness the finger the gears turn would yield to the servo's
# torque by over ten degrees: a time constant of two 2 ms steps and a hard impedance, as Menagerie's grippers use.
GEAR_STIFFNESS = 'solref="0.004 1" solimp="0.95 0.99 0.001"'
MODEL = "anybuild-gripper"


class ExportError(ValueError):
    """The build cannot become a simulation model; the message says what is missing."""


def _f(*values: float) -> str:
    return " ".join(f"{0.0 if abs(float(v)) < 1e-12 else float(v):.6g}" for v in values)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "part"


def _rgba(color: str | None, alpha: float = 1.0) -> str:
    text = (color or "").lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", text):
        return _f(0.7, 0.7, 0.72, alpha)
    own = int(text[6:], 16) / 255.0 if len(text) == 8 else 1.0
    return _f(*(int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4)), alpha * own)


def _unit(vector, label: str) -> np.ndarray:
    v = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(v)) if v.shape == (3,) else 0.0
    if norm < 1e-9:
        raise ExportError(label + " must be a non-zero [x, y, z] vector.")
    return v / norm


def tool_frame(tool: dict) -> tuple[np.ndarray, np.ndarray]:
    """(rotation, origin in mm): p_tool = rotation @ (p_cad - origin) / 1000. Fingers point to -z, they close along y."""

    approach = _unit(tool.get("approach"), "tool.approach")
    closing = _unit(tool.get("closing"), "tool.closing")
    closing = closing - float(closing @ approach) * approach
    y = _unit(closing, "tool.closing, apart from its part along tool.approach,")
    z = -approach
    rotation = np.array([np.cross(y, z), y, z])
    origin = np.asarray(tool.get("point_mm"), dtype=float)
    if origin.shape != (3,):
        raise ExportError("tool.point_mm must be [x, y, z] in mm.")
    return rotation, origin


def _quat(matrix: np.ndarray) -> list[float]:
    """Rotation matrix to a unit quaternion (w, x, y, z)."""

    m = matrix
    trace = float(m[0, 0] + m[1, 1] + m[2, 2])
    if trace > 0:
        s = 2.0 * math.sqrt(trace + 1.0)
        q = [0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s]
    else:
        i = int(np.argmax([m[0, 0], m[1, 1], m[2, 2]]))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = 2.0 * math.sqrt(max(1e-12, 1.0 + m[i, i] - m[j, j] - m[k, k]))
        q = [0.0, 0.0, 0.0, 0.0]
        q[0] = (m[k, j] - m[j, k]) / s
        q[1 + i] = 0.25 * s
        q[1 + j] = (m[j, i] + m[i, j]) / s
        q[1 + k] = (m[k, i] + m[i, k]) / s
    if q[0] < 0:
        q = [-v for v in q]
    return [float(v) for v in q]


def _yaw(degrees: float) -> np.ndarray:
    a = math.radians(degrees)
    return np.array([[math.cos(a), -math.sin(a), 0.0], [math.sin(a), math.cos(a), 0.0], [0.0, 0.0, 1.0]])


def _box_inertia(mass_kg: float, size_m: np.ndarray) -> np.ndarray:
    sx, sy, sz = (max(float(v), 1e-4) for v in size_m)
    return np.diag([sy * sy + sz * sz, sx * sx + sz * sz, sx * sx + sy * sy]) * mass_kg / 12.0


def _check(parts: list[dict], sim: dict | None) -> tuple[dict, str]:
    """Validates the template's kinematics; returns (joints, the name of the joint the servo drives)."""

    if not sim or not sim.get("joints") or not sim.get("tool"):
        raise ExportError("This build declares no joints and tool frame, so it cannot be simulated. The gripper template declares them.")
    names = {row["name"] for row in parts}
    if len({_slug(name) for name in names}) != len(names):
        raise ExportError("Two parts have names that differ only in case or punctuation; rename one.")
    joints = sim["joints"]
    seen: set[str] = set()
    drivers = []
    for key, joint in joints.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(key)) or key == "hand":
            raise ExportError("Joint names must be lower-case identifiers other than 'hand', not " + repr(key) + ".")
        if joint.get("type", "hinge") != "hinge":
            raise ExportError("joints[" + repr(key) + "]: only hinge joints are supported.")
        if not joint.get("parts"):
            raise ExportError("joints[" + repr(key) + "] carries no parts, so nothing would move.")
        for part in joint["parts"]:
            if part not in names:
                raise ExportError("joints[" + repr(key) + "] carries " + repr(part) + ", which is not a built part.")
            if part in seen:
                raise ExportError(repr(part) + " is carried by two joints.")
            seen.add(part)
        low, high = (float(v) for v in joint.get("range_deg") or (0.0, 0.0))
        if not high > low:
            raise ExportError("joints[" + repr(key) + "].range_deg must be [low, high] with high > low.")
        if "drive" in joint:
            if joint["drive"] not in names:
                raise ExportError("joints[" + repr(key) + "] is driven by " + repr(joint["drive"]) + ", which is not a built part.")
            drivers.append(key)
        elif joint.get("follows") not in joints or joint.get("follows") == key:
            raise ExportError("joints[" + repr(key) + "] needs `drive` (a part) or `follows` (another joint).")
        elif "drive" not in joints[joint["follows"]]:
            raise ExportError("joints[" + repr(key) + "] follows " + repr(joint["follows"]) + ", which no servo drives.")
    if len(drivers) != 1:
        raise ExportError("Exactly one joint must name the servo as its `drive`; found " + str(len(drivers)) + ".")
    return joints, drivers[0]


def servo_dynamics(servo: dict) -> dict:
    """The servo as a joint actuator: holding torque, stiffness, damping (its speed) and the gear train's inertia."""

    torque = float(servo["stall_torque_kgcm"]) * GRAVITY / 100.0 * HOLD_FRACTION
    kp = torque / SATURATION_RAD
    damping = torque / SPEED_RAD_S
    return {"torque_nm": torque, "kp": kp, "damping": damping, "armature": (damping / (2.0 * DAMPING_RATIO)) ** 2 / kp}


def _mesh(vertices_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """STL triangle soup to shared vertices and faces, without degenerate triangles."""

    unique, index = np.unique(np.round(vertices_m, 7), axis=0, return_inverse=True)
    faces = index.reshape(-1, 3)
    keep = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    return unique, faces[keep]


def hand_mjcf(parts: list[dict], sim: dict | None, mesh_dir: Path, servo: dict, pads: dict, model: str = MODEL) -> str:
    """The MJCF text of the built gripper (see the module docstring). `parts` are the build's rows, their STLs in mesh_dir."""

    joints, driver = _check(parts, sim)
    assert sim is not None
    rotation, origin = tool_frame(sim["tool"])
    collision = sim.get("collision") or {}
    grip = set(sim.get("grip_surfaces") or [])
    friction = float(pads.get("friction", 1.0))
    drive_part = joints[driver]["drive"]

    def to_tool(point_mm) -> np.ndarray:
        return rotation @ (np.asarray(point_mm, dtype=float) - origin) / 1000.0

    body_of = {part: key for key, joint in joints.items() for part in joint.get("parts") or []}
    bodies: dict[str, dict] = {"hand": {"pos": np.zeros(3), "parts": []}}
    for key, joint in joints.items():
        bodies[key] = {"pos": to_tool(joint["pivot_mm"]), "parts": []}
    for row in parts:
        bodies[body_of.get(row["name"], "hand")]["parts"].append(row)

    assets: list[str] = []
    xml: dict[str, list[str]] = {}
    for key, body in bodies.items():
        lines: list[str] = []
        masses = []
        for row in body["parts"]:
            m = (float(servo["mass_g"]) if row["name"] == drive_part else float(row["mass_g"])) / 1000.0
            box = np.asarray(row["bbox_mm"], dtype=float)
            com = np.asarray(row.get("com_mm") or (box[:3] + box[3:]) / 2.0, dtype=float)
            masses.append((m, to_tool(com), rotation @ _box_inertia(m, (box[3:] - box[:3]) / 1000.0) @ rotation.T))
        mass = sum(m for m, _com, _own in masses)
        if mass > 0:
            center = sum(m * com for m, com, _own in masses) / mass
            inertia = np.zeros((3, 3))
            for m, com, own in masses:
                d = com - center
                inertia += own + m * (float(d @ d) * np.eye(3) - np.outer(d, d))
            full = (inertia[0, 0], inertia[1, 1], inertia[2, 2], inertia[0, 1], inertia[0, 2], inertia[1, 2])
            lines.append(f'<inertial pos="{_f(*(center - body["pos"]))}" mass="{mass:.6g}" fullinertia="{_f(*full)}"/>')
        if key == "hand":
            lines.append('<site name="tcp" pos="0 0 0" size="0.004" rgba="1 0 0 0"/>')
        for row in body["parts"]:
            slug = _slug(row["name"])
            vertices, faces = _mesh(np.array([to_tool(v) for v in read_stl_vertices(mesh_dir / row["stl"])]) - body["pos"])
            assets.append(
                f'<mesh name="{slug}" vertex="{_f(*vertices.ravel())}" face="{" ".join(str(int(i)) for i in faces.ravel())}"/>'
            )
            lines.append(f'<geom name="{slug}" type="mesh" mesh="{slug}" rgba="{_rgba(row.get("color"))}" contype="0" conaffinity="0" group="2" mass="0"/>')
            shapes = collision.get(row["name"])
            if shapes is None:
                box = np.asarray(row["bbox_mm"], dtype=float)
                shapes = [{"type": "box", "center_mm": list((box[:3] + box[3:]) / 2.0), "half_mm": list((box[3:] - box[:3]) / 2.0)}]
            surface = (
                f'friction="{_f(friction, 0.005, 0.0001)}" condim="4" priority="1"'
                if row["name"] in grip
                else f'friction="{_f(PRINTED_FRICTION, 0.005, 0.0001)}"'
            )
            for index, shape in enumerate(shapes):
                if shape.get("type", "box") != "box":
                    raise ExportError("collision[" + repr(row["name"]) + "]: only boxes are supported.")
                orient = rotation @ _yaw(float(shape.get("yaw_deg", 0.0)))
                center = to_tool(shape["center_mm"]) - body["pos"]
                half = np.abs(np.asarray(shape["half_mm"], dtype=float)) / 1000.0
                lines.append(
                    f'<geom name="{slug}_c{index}" type="box" pos="{_f(*center)}" quat="{_f(*_quat(orient))}" size="{_f(*half)}" '
                    f'{surface} rgba="{_rgba(row.get("color"), 0.4)}" group="3" mass="0"/>'
                )
        xml[key] = lines

    dynamics = servo_dynamics(servo)
    children = []
    for key, joint in joints.items():
        axis = rotation @ _unit(joint.get("axis"), "joints[" + repr(key) + "].axis")
        low, high = (float(v) for v in joint["range_deg"])
        ref = float(joint.get("ref_deg", low))
        drive = f' damping="{dynamics["damping"]:.6g}" armature="{dynamics["armature"]:.6g}"' if key == driver else ""
        children.append(
            f'<body name="{key}" pos="{_f(*bodies[key]["pos"])}">\n'
            f'        <joint name="{key}" type="hinge" axis="{_f(*axis)}" range="{_f(low, high)}" ref="{ref:.6g}"{drive}/>\n'
            + "".join("        " + line + "\n" for line in xml[key])
            + "      </body>"
        )
    # The hand's own parts never collide with each other. MuJoCo filters a body against its parent only when the
    # parent can move, which a hand fixed in space cannot, so the pairs are listed.
    own = ["hand", *joints]
    excludes = [f'<exclude body1="{a}" body2="{b}"/>' for i, a in enumerate(own) for b in own[i + 1 :]]
    couplings = [
        f'<joint name="{key}_gears" joint1="{key}" joint2="{joint["follows"]}" polycoef="0 {float(joint.get("ratio", 1.0)):.6g} 0 0 0" {GEAR_STIFFNESS}/>'
        for key, joint in joints.items()
        if "follows" in joint
    ]
    low, high = (math.radians(float(v)) for v in joints[driver]["range_deg"])
    torque = dynamics["torque_nm"]
    note = servo["name"] + ", " + pads["name"]
    return (
        f'<mujoco model="{model}">\n'
        f"  <!-- AnyBuild gripper, exported from its FreeCAD build: {note.replace('--', '-')}.\n"
        "       Tool frame in metres: grasp point at the origin, fingers along -z, closing along y. -->\n"
        '  <compiler angle="degree"/>\n'
        "  <asset>\n" + "".join("    " + line + "\n" for line in assets) + "  </asset>\n"
        "  <worldbody>\n"
        '    <body name="hand">\n'
        + "".join("      " + line + "\n" for line in xml["hand"])
        + "".join("      " + child + "\n" for child in children)
        + "    </body>\n"
        "  </worldbody>\n"
        "  <contact>\n" + "".join("    " + line + "\n" for line in excludes) + "  </contact>\n"
        "  <equality>\n" + "".join("    " + line + "\n" for line in couplings) + "  </equality>\n"
        "  <actuator>\n"
        f'    <position name="servo" joint="{driver}" kp="{dynamics["kp"]:.6g}" ctrlrange="{_f(low, high)}" forcerange="{_f(-torque, torque)}"/>\n'
        "  </actuator>\n"
        "  <custom>\n"
        f'    <text name="anybuild_servo" data={quoteattr(str(servo["name"]))}/>\n'
        f'    <text name="anybuild_pads" data={quoteattr(str(pads["name"]))}/>\n'
        "  </custom>\n"
        "</mujoco>\n"
    )


def write_hand(build: PartBuild, servo: dict, pads: dict, path: Path) -> Path:
    """Writes the built gripper as one MJCF file (its meshes inline) and returns the path."""

    text = hand_mjcf(build.parts, build.sim, build.stl.parent, servo, pads)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
