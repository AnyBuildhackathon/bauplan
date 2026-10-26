"""SolidCraft's URDF in MuJoCo: the MJCF with what a URDF cannot hold put back, and the run that checks it.

`mjcf_from_urdf` has MuJoCo read the URDF SolidCraft exported (`solidcraft.export_robot`) and write MJCF with
mj_saveLastXML, then puts back what a URDF cannot hold:
- URDF is a tree, so SolidCraft leaves out each joint that closes a loop. The MJCF keeps that joint as a MuJoCo
  joint with its value and limits, on a frame of the joint's first part at the joint's origin, and an equality
  weld fixes the second part to that frame; a ball joint closes with an equality connect. A single connect would
  only pin a point: it cannot hold a slider, such as the actuator stroke that closes most actuator loops, and it
  holds a hinge only while the loop stays planar.
- Motion links (gears, racks, mirrored parts) become equality joint couplings with the same ratio.
- qpos0 is the design as built: each joint's `ref` is its SolidCraft value, so values read as in SolidCraft.
- Loops and couplings are stiff, as in Menagerie's grippers; the parts of the mechanism do not collide with each
  other (SolidCraft without contact sets), only with what a scene adds.

`check_mjcf` then drives the joints the design's motion study keys, in MuJoCo with gravity off, and compares every
part with where SolidCraft's study puts it, the loop gaps, the couplings, every joint's travel, and every link's
mass against SolidCraft's `measure`.
"""

from __future__ import annotations

import itertools
import math
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from pai_agent.solidcraft import VERSION, Robot, link_names, mj_name

DEG = math.pi / 180.0
# The frame that carries a loop joint in MuJoCo, as SolidCraft's URDF gives an in-between link: a token mass.
_LOOP_MASS = 1e-6
_LOOP_INERTIA = 1e-12
# Joints that close loops and gears barely give: a time constant of two 2 ms steps and a hard impedance.
_STIFF = {"solref": "0.004 1", "solimp": "0.95 0.99 0.001"}
# The parts of the mechanism collide with what a scene adds (contype 1, conaffinity 1), not with each other.
_CONTYPE, _CONAFFINITY = "2", "1"
# Joint types that move; the relations (parallel, angle, point on plane ...) become fixed joints in a URDF.
_MOVING = {"revolute", "slider", "cylindrical", "pin_slot", "planar", "ball"}
# Tolerances of the MuJoCo check.
MASS_TOLERANCE = 0.01
POSE_TOLERANCE_MM = 0.1
LOOP_TOLERANCE_MM = 0.01
MOVED_DEG, MOVED_MM = 0.5, 0.05


def _norm(name: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _unit(value: dict) -> float:
    """SolidCraft's unit of a joint value to SI: degrees to radians, millimetres to metres."""

    return DEG if value.get("unit") == "deg" else 1e-3


def _f(*values: float) -> str:
    return " ".join(f"{0.0 if abs(float(v)) < 1e-15 else float(v):.10g}" for v in values)


def _z_to(axis: np.ndarray) -> np.ndarray:
    """The quaternion that turns +z onto axis."""

    a = axis / np.linalg.norm(axis)
    c = float(a[2])
    if c > 1.0 - 1e-12:
        return np.array([1.0, 0.0, 0.0, 0.0])
    if c < -1.0 + 1e-12:
        return np.array([0.0, 1.0, 0.0, 0.0])
    q = np.array([1.0 + c, -a[1], a[0], 0.0])
    return q / np.linalg.norm(q)


def mjcf_from_urdf(robot: Robot, mjcf: Path) -> dict:
    """MuJoCo's MJCF of SolidCraft's URDF with the loops closed, the motion links coupled and qpos0 as built.

    Returns what it did: the loops it closed and left open, the couplings, and MuJoCo's joints and bodies.
    """

    import mujoco

    sc_joints = {_norm(row["name"]): row for row in robot.joints.get("joints") or []}
    by_id = {int(row["id"]): row for row in robot.joints.get("joints") or []}
    occurrence_link = link_names(robot.components)

    tree = ET.parse(robot.urdf)
    extension = ET.SubElement(tree.getroot(), "mujoco")
    ET.SubElement(extension, "compiler", {"discardvisual": "false", "fusestatic": "false", "strippath": "false"})
    with tempfile.TemporaryDirectory(prefix="pai-mjcf-") as tmp:
        work = Path(tmp)
        for mesh in robot.meshes:
            shutil.copyfile(mesh, work / mesh.name)
        tree.write(work / "robot.urdf", encoding="unicode")
        model = mujoco.MjModel.from_xml_path(str(work / "robot.urdf"))
        mujoco.mj_saveLastXML(str(work / "raw.xml"), model)
        root = ET.parse(work / "raw.xml").getroot()

    bodies = {mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b): b for b in range(model.nbody)}
    body_by_norm = {_norm(name): name for name in bodies}
    elements = {element.get("name"): element for element in root.iter("body")}

    # The pose the design is in: every URDF joint at its SolidCraft value (one value per URDF joint).
    data = mujoco.MjData(model)
    asbuilt: dict[str, float] = {}
    for j in range(model.njnt):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j)
        row = sc_joints.get(_norm(name))
        if row and len(row.get("values") or []) == 1:
            asbuilt[name] = float(row["values"][0]["value"]) * _unit(row["values"][0])
            data.qpos[model.jnt_qposadr[j]] = asbuilt[name]
    mujoco.mj_kinematics(model, data)
    if any(abs(v) > 1e-12 for v in asbuilt.values()):
        # qpos0 becomes that pose: each body sits where the design has it, each joint's ref is its value.
        for name, b in bodies.items():
            if b == 0 or name not in elements:
                continue
            parent = model.body_parentid[b]
            rotation = data.xmat[parent].reshape(3, 3)
            inverse, quat = np.zeros(4), np.zeros(4)
            mujoco.mju_negQuat(inverse, data.xquat[parent])
            mujoco.mju_mulQuat(quat, inverse, data.xquat[b])
            elements[name].set("pos", _f(*(rotation.T @ (data.xpos[b] - data.xpos[parent]))))
            elements[name].set("quat", _f(*quat))
        for element in root.iter("joint"):
            if element.get("name") in asbuilt:
                element.set("ref", _f(asbuilt[element.get("name")]))

    equality = ET.SubElement(root, "equality")
    loops = [match.group(1) for text in robot.warnings for match in [re.match(r"joint `(.+)` closes a loop", text)] if match]
    closed, open_loops, joint_names = [], [], {}
    for loop in loops:
        row = sc_joints.get(_norm(loop))
        first = body_by_norm.get(_norm(occurrence_link.get(int(row["a"]), ""))) if row else None
        second = body_by_norm.get(_norm(occurrence_link.get(int(row["b"]), ""))) if row else None
        if row is None or first is None or second is None:
            open_loops.append({"joint": loop, "why": "its parts are not links of the URDF"})
            continue
        b = bodies[first]
        rotation = data.xmat[b].reshape(3, 3)
        origin = rotation.T @ (np.array(row["frame_a"]["origin"], dtype=float) / 1000.0 - data.xpos[b])
        axis = rotation.T @ np.array(row["frame_a"].get("z") or [0.0, 0.0, 1.0], dtype=float)
        name = mj_name(row["name"])
        kinds = {"revolute": ("hinge",), "slider": ("slide",), "cylindrical": ("hinge", "slide")}.get(row["type"])
        if kinds:
            frame = ET.SubElement(elements[first], "body", {"name": "loop_" + name, "pos": _f(*origin), "quat": _f(*_z_to(axis))})
            ET.SubElement(frame, "inertial", {"pos": "0 0 0", "mass": _f(_LOOP_MASS), "diaginertia": _f(_LOOP_INERTIA, _LOOP_INERTIA, _LOOP_INERTIA)})
            for index, kind in enumerate(kinds):
                value = row["values"][index]
                joint = name if index == len(kinds) - 1 else f"{name}_dof{index + 1}"
                attrs = {"name": joint, "type": kind, "axis": "0 0 1", "ref": _f(float(value["value"]) * _unit(value))}
                if value.get("limits"):
                    attrs.update(range=_f(*(float(v) * _unit(value) for v in value["limits"])), limited="true")
                ET.SubElement(frame, "joint", attrs)
                joint_names[(int(row["id"]), index)] = joint
            # The weld point is the frame's origin, on the joint's axis: the frame's own turn or slide stays free.
            ET.SubElement(equality, "weld", {"name": "loop " + row["name"], "body1": second, "body2": "loop_" + name, **_STIFF})
        elif row["type"] == "rigid":
            ET.SubElement(equality, "weld", {"name": "loop " + row["name"], "body1": first, "body2": second, **_STIFF})
        elif row["type"] == "ball":
            ET.SubElement(equality, "connect", {"name": "loop " + row["name"], "body1": first, "body2": second, "anchor": _f(*origin), **_STIFF})
        else:
            open_loops.append({"joint": loop, "why": f"a {row['type']} joint that closes a loop has no MuJoCo form here yet"})
            continue
        closed.append({"joint": row["name"], "type": row["type"], "parts": [first, second]})

    for j in range(model.njnt):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j)
        row = sc_joints.get(_norm(name))
        if row and len(row.get("values") or []) == 1:
            joint_names[(int(row["id"]), 0)] = name
    couplings, uncoupled = [], []
    for link in robot.joints.get("links") or []:
        a, b = by_id.get(int(link["a"])), by_id.get(int(link["b"]))
        ia, ib = int(link.get("ia") or 0), int(link.get("ib") or 0)
        first, second = joint_names.get((int(link["a"]), ia)), joint_names.get((int(link["b"]), ib))
        label = f"{a['name'] if a else link['a']} drives {b['name'] if b else link['b']}"
        if "ratio" not in link or first is None or second is None or a is None or b is None:
            why = "a cam's table is not a ratio" if "lift" in link else "one of its joints has more than one value"
            uncoupled.append({"link": label, "why": why})
            continue
        ka, kb = _unit(a["values"][ia]), _unit(b["values"][ib])
        ratio = float(link["ratio"]) * kb / ka
        # Both joints start at their values as built (their refs), where b = ratio * a + offset already holds.
        ET.SubElement(equality, "joint", {"name": "link " + label, "joint1": second, "joint2": first, "polycoef": _f(0.0, ratio, 0.0, 0.0, 0.0), **_STIFF})
        couplings.append({"link": label, "ratio": round(float(link["ratio"]), 6), "unit": f"{b['values'][ib].get('unit')} per {a['values'][ia].get('unit')}"})
    if not len(equality):
        root.remove(equality)

    for geom in root.iter("geom"):
        if geom.get("contype") == "0" and geom.get("conaffinity") == "0":
            continue
        geom.set("contype", _CONTYPE)
        geom.set("conaffinity", _CONAFFINITY)
    root.insert(
        0,
        ET.Comment(
            " MuJoCo's reading of SolidCraft's URDF export (solidcraft-cli " + VERSION + "), by AnyBuild: loops closed with equality constraints, "
            "motion links as joint couplings, qpos0 as built, no collisions between the mechanism's own parts. "
        ),
    )
    ET.indent(root)
    mjcf.write_text(ET.tostring(root, encoding="unicode") + "\n", encoding="utf-8")
    final = mujoco.MjModel.from_xml_path(str(mjcf))
    return {
        "loops_closed": closed,
        "loops_open": open_loops,
        "couplings": couplings,
        "uncoupled": uncoupled,
        "urdf_joints": [mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j) for j in range(model.njnt)],
        "joints": [mujoco.mj_id2name(final, mujoco.mjtObj.mjOBJ_JOINT, j) for j in range(final.njnt)],
        "bodies": final.nbody - 1,
        "equalities": final.neq,
    }


# --- The MuJoCo check --------------------------------------------------------------------------------------------


def _occurrence_masses(properties: dict, occurrence_link: dict[int, str]) -> dict[str, dict]:
    """SolidCraft's mass and centre of mass per URDF link, from component.properties of the root."""

    out: dict[str, dict] = {}
    for body in properties.get("bodies") or []:
        if body.get("mass_g") is None:
            continue
        path = body.get("path") or [0]
        link = occurrence_link.get(int(path[-1]), "base_link")
        row = out.setdefault(link, {"mass_g": 0.0, "moment": np.zeros(3)})
        row["mass_g"] += float(body["mass_g"])
        row["moment"] += float(body["mass_g"]) * np.array(body["center_of_mass"], dtype=float)
    return out


def check_mjcf(robot: Robot, mjcf: Path, converted: dict) -> dict:
    """Runs the MJCF in MuJoCo: the as-built pose, every link's mass, and the motion study driven through.

    The study's keyed joints follow their keys through an equality per joint (gravity off), and each sample is
    compared with SolidCraft's own poses at that step. Returns the numbers and pass/fail per criterion.
    """

    import mujoco

    occurrence_link = link_names(robot.components)
    by_id = {int(row["id"]): row for row in robot.joints.get("joints") or []}
    root = ET.parse(mjcf).getroot()
    drivers = []
    for key in (robot.study or {}).get("keys") or []:
        row = by_id.get(int(key["joint"]))
        if row is None:
            continue
        index = int(key.get("index") or 0)
        name = mj_name(row["name"]) if len(row["values"]) == 1 else None
        if name is None or name not in converted["joints"]:
            continue
        # motion.list gives the key values in SolidCraft's own units: radians for angles, millimetres for distances.
        scale = 1.0 if row["values"][index].get("unit") == "deg" else 1e-3
        drivers.append({"joint": name, "points": [(float(s), float(v) * scale) for s, v in key["points"]]})
    equality = root.find("equality")
    if equality is None:
        equality = ET.SubElement(root, "equality")
    for driver in drivers:
        ET.SubElement(equality, "joint", {"name": "drive " + driver["joint"], "joint1": driver["joint"], "polycoef": "0 0 0 0 0", **_STIFF})
    assets = {mesh.name: mesh.read_bytes() for mesh in robot.meshes}
    model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"), assets)
    model.opt.gravity[:] = 0.0
    model.opt.timestep = 0.001
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    # Damping near critical for each joint's own inertia, so a joint the study does not key settles too.
    model.dof_damping[:] = 2.0 * (2.0 * math.pi * 5.0) * model.dof_M0

    names = {mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b): b for b in range(model.nbody)}
    by_norm = {_norm(name): name for name in names}
    links = {}
    for occurrence, link in occurrence_link.items():
        if _norm(link) in by_norm:
            links[occurrence] = by_norm[_norm(link)]

    # Masses and the as-built pose against SolidCraft.
    expected = _occurrence_masses(robot.properties, occurrence_link)
    masses, worst_mass, worst_com = [], 0.0, 0.0
    for link, row in sorted(expected.items()):
        name = by_norm.get(_norm(link))
        if name is None or row["mass_g"] <= 0:
            continue
        b = names[name]
        mj = float(model.body_mass[b]) * 1000.0
        error = abs(mj - row["mass_g"]) / row["mass_g"]
        worst_mass = max(worst_mass, error)
        com = row["moment"] / row["mass_g"]
        worst_com = max(worst_com, float(np.linalg.norm(data.xipos[b] * 1000.0 - com)))
        masses.append({"link": name, "mujoco_g": round(mj, 4), "solidcraft_g": round(row["mass_g"], 4), "error_pct": round(error * 100.0, 4)})
    measured = float((robot.measure.get("total") or {}).get("mass_g") or 0.0)
    loop_bodies = {name for name in names if name.startswith("loop_")}
    total = sum(float(model.body_mass[b]) for name, b in names.items() if name not in loop_bodies) * 1000.0
    total_error = abs(total - measured) / measured if measured > 0 else 0.0

    # Each loop's two points that must stay together, in their own bodies' frames: a weld holds body2's origin where
    # it sits in body1's frame as built, a connect its anchor.
    loop_points = []
    for e in range(model.neq):
        if model.eq_type[e] not in (mujoco.mjtEq.mjEQ_WELD, mujoco.mjtEq.mjEQ_CONNECT):
            continue
        if not str(mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_EQUALITY, e)).startswith("loop "):
            continue
        b1, b2 = int(model.eq_obj1id[e]), int(model.eq_obj2id[e])
        r1, r2 = data.xmat[b1].reshape(3, 3), data.xmat[b2].reshape(3, 3)
        point = data.xpos[b2] if model.eq_type[e] == mujoco.mjtEq.mjEQ_WELD else data.xpos[b1] + r1 @ model.eq_data[e, 0:3]
        loop_points.append((b1, b2, r1.T @ (point - data.xpos[b1]), r2.T @ (point - data.xpos[b2])))
    couples = []
    for e in range(model.neq):
        name = str(mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_EQUALITY, e))
        if model.eq_type[e] == mujoco.mjtEq.mjEQ_JOINT and name.startswith("link "):
            a1, a2 = model.jnt_qposadr[int(model.eq_obj1id[e])], model.jnt_qposadr[int(model.eq_obj2id[e])]
            couples.append((a1, a2, float(model.eq_data[e, 1]), model.qpos0[a1], model.qpos0[a2]))

    def gaps() -> float:
        worst = 0.0
        for b1, b2, on1, on2 in loop_points:
            first = data.xpos[b1] + data.xmat[b1].reshape(3, 3) @ on1
            second = data.xpos[b2] + data.xmat[b2].reshape(3, 3) @ on2
            worst = max(worst, float(np.linalg.norm(first - second)) * 1000.0)
        return worst

    loop_gap = gaps()
    coupling_error = 0.0
    lo, hi = data.qpos.copy(), data.qpos.copy()
    deviation = 0.0
    samples = (robot.motion or {}).get("samples") or []
    if drivers and samples:
        equalities = {d["joint"]: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_EQUALITY, "drive " + d["joint"]) for d in drivers}
        addresses = {d["joint"]: model.jnt_qposadr[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, d["joint"])] for d in drivers}

        def target(points, step):
            if step <= points[0][0]:
                return points[0][1]
            for (s0, v0), (s1, v1) in itertools.pairwise(points):
                if s0 <= step <= s1:
                    return v1 if s1 == s0 else v0 + (v1 - v0) * (step - s0) / (s1 - s0)
            return points[-1][1]

        def go(step: float, ramp: float, hold: float) -> None:
            start = {d["joint"]: float(data.qpos[addresses[d["joint"]]]) for d in drivers}
            ramp_steps, hold_steps = max(1, int(ramp / model.opt.timestep)), int(hold / model.opt.timestep)
            for i in range(ramp_steps + hold_steps):
                t = min(1.0, (i + 1) / ramp_steps)
                for d in drivers:
                    goal = target(d["points"], step)
                    a = addresses[d["joint"]]
                    model.eq_data[equalities[d["joint"]], 0] = start[d["joint"]] + (goal - start[d["joint"]]) * t - model.qpos0[a]
                mujoco.mj_step(model, data)

        def poses() -> dict[int, tuple[np.ndarray, np.ndarray]]:
            return {occ: (data.xipos[names[link]].copy(), data.xmat[names[link]].reshape(3, 3).copy()) for occ, link in links.items()}

        go(samples[0]["step"], 0.3, 0.3)
        base = poses()
        reference = {_occurrence_id(robot.components, row["occurrence"]): row["pose"] for row in samples[0]["positions"]}
        for sample in samples:
            go(sample["step"], 0.15, 0.15)
            lo, hi = np.minimum(lo, data.qpos), np.maximum(hi, data.qpos)
            loop_gap = max(loop_gap, gaps())
            for a1, a2, ratio, q1, q2 in couples:
                coupling_error = max(coupling_error, abs((data.qpos[a1] - q1) - ratio * (data.qpos[a2] - q2)))
            now = poses()
            for row in sample["positions"]:
                occurrence = _occurrence_id(robot.components, row["occurrence"])
                if occurrence not in base or occurrence not in reference:
                    continue
                deviation = max(deviation, _pose_error(reference[occurrence], row["pose"], base[occurrence], now[occurrence]))

    travel = []
    for j in range(model.njnt):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j)
        a = model.jnt_qposadr[j]
        hinge = model.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE
        span = float(hi[a] - lo[a]) / (DEG if hinge else 1e-3)
        travel.append({"joint": name, "unit": "deg" if hinge else "mm", "travel": round(span, 3), "moved": span >= (MOVED_DEG if hinge else MOVED_MM)})
    # Every SolidCraft joint that moves must be a MuJoCo joint (a URDF chain names its first steps <joint>_dof1, ...);
    # a ball or rigid joint that closes a loop is its equality instead.
    moving = [row for row in robot.joints.get("joints") or [] if row.get("type") in _MOVING and not row.get("suppressed")]
    present = set(converted["joints"]) | {mj_name(row["joint"]) for row in converted["loops_closed"] if row["type"] in ("ball", "rigid")}
    absent = [row["name"] for row in moving if mj_name(row["name"]) not in present]
    driven = bool(drivers and samples)
    checks = {
        "all_joints": not absent and not converted["loops_open"],
        "loops_closed": not converted["loops_open"] and loop_gap <= LOOP_TOLERANCE_MM,
        "mass_within_1pct": worst_mass <= MASS_TOLERANCE and total_error <= MASS_TOLERANCE,
        "as_built": worst_com <= POSE_TOLERANCE_MM,
        "follows_study": driven and deviation <= POSE_TOLERANCE_MM,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "missing_joints": absent,
        "study": (robot.study or {}).get("name"),
        "drivers": [d["joint"] for d in drivers],
        "samples": len(samples) if driven else 0,
        "deviation_mm": round(deviation, 6),
        "loop_gap_mm": round(loop_gap, 6),
        "coupling_error": round(coupling_error, 9),
        "travel": travel,
        "masses": masses,
        "mass_error_pct": round(worst_mass * 100.0, 4),
        "total_mass_g": {"mujoco": round(total, 4), "solidcraft": round(measured, 4), "error_pct": round(total_error * 100.0, 4)},
        "com_error_mm": round(worst_com, 6),
    }


def _occurrence_id(components: list[dict], name: str) -> int | None:
    for component in components:
        for occurrence in component.get("occurrences") or []:
            if occurrence["name"] == name:
                return int(occurrence["id"])
    return None


def _pose_error(reference: dict, pose: dict, base: tuple[np.ndarray, np.ndarray], now: tuple[np.ndarray, np.ndarray]) -> float:
    """How far, in mm, MuJoCo moved a part from where SolidCraft moved it, since the study's first sample.

    Four points ride on the part (its centre of mass and 20 mm from it along each axis), so a wrong turn
    shows as much as a wrong shift.
    """

    r0 = np.column_stack([reference["x"], reference["y"], reference["z"]])
    t0 = np.array(reference["origin"], dtype=float) / 1000.0
    r1 = np.column_stack([pose["x"], pose["y"], pose["z"]])
    t1 = np.array(pose["origin"], dtype=float) / 1000.0
    x0, m0 = base
    x1, m1 = now
    worst = 0.0
    for offset in (np.zeros(3), np.array([0.02, 0.0, 0.0]), np.array([0.0, 0.02, 0.0]), np.array([0.0, 0.0, 0.02])):
        point = x0 + offset
        solidcraft = r1 @ (r0.T @ (point - t0)) + t1
        mujoco_point = m1 @ (m0.T @ (point - x0)) + x1
        worst = max(worst, float(np.linalg.norm(solidcraft - mujoco_point)) * 1000.0)
    return worst
