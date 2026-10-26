"""solidcraft_part and export_urdf: parts and mechanisms built in SolidCraft, and their robot description.

`PAI_CAD_ENGINE=solidcraft` gives Mechanic these two tools (orchestrator.py); FreeCAD stays the default engine
and keeps the printed parts of a product spec (cad_part). solidcraft_part builds a part or a mechanism from a
SolidCraft command script: a library template (agent/solidcraft/library: the Chebyshev four-bar from
SolidCraft's examples and AnyBuild's two-finger gripper), a script Mechanic passes, or one the CAD agent writes
from the description. The CAD agent works from SolidCraft's own skills, solidcraft-modeling and
solidcraft-mechanisms (MIT, copied unchanged into agent/solidcraft/skills); when SolidCraft reports an error,
the script goes back to it with the error, up to three attempts. The files land in the session
(`solidcraft.build`), the `cad` event shows the design with its parameters as sliders, and SolidCraft's picture
of it reaches Claude as an image next to the JSON. A slider runs the same script followed by the new value as one
parameter change, as moving it in SolidCraft does, no Claude needed: the timeline rebuilds and the joints follow.

export_urdf turns the last design into SolidCraft's URDF and MuJoCo's MJCF with its loops closed, then runs the
MJCF through the design's motion study and checks it (`solidcraft.export_robot`, `solidcraft_mjcf`).
Without solidcraft-cli both tools answer ok false with the install hint.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from pathlib import Path

from pai_agent import settings, solidcraft, solidcraft_mjcf
from pai_agent.agents import CAD_ROLE, AgentRun
from pai_agent.cad_script import DENSITY_G_CM3
from pai_agent.context import Ctx
from pai_agent.env import claude_enabled
from pai_agent.tools.view import IMAGE

log = logging.getLogger(__name__)

# The tools Mechanic gets only when SolidCraft is the CAD engine.
NAMES = frozenset({"solidcraft_part", "export_urdf"})
MAX_ATTEMPTS = 3
LIBRARY = {
    "four_bar": {
        "file": "chebyshev-motion-trace.json",
        "name": "Chebyshev linkage",
        "keywords": ("four-bar", "four bar", "4-bar", "fourbar", "linkage", "chebyshev"),
    },
    "two_finger_gripper": {
        "file": "two-finger-gripper.json",
        "name": "Two-finger gripper",
        "keywords": ("gripper", "two-finger", "two finger", "claw"),
    },
}
# At most this many sliders; a design's favourite parameters come first.
MAX_SLIDERS = 8
_PLAIN = re.compile(r"^\s*-?\d+(\.\d+)?\s*(mm|deg)?\s*$")

SCHEMA = {
    "name": "solidcraft_part",
    "description": (
        "Builds a part or a mechanism in SolidCraft, parametric CAD with a feature timeline, joints, motion links and motion studies. "
        "Use it for anything with parts that move on joints (a gripper, a linkage, an arm, a leg, a hinge, a slide) and when someone asks for SolidCraft. "
        "Without script, a CAD agent writes SolidCraft's command script from description and params, using SolidCraft's own modelling and mechanism skills; "
        "when SolidCraft reports an error the script is fixed and retried up to 3 times. "
        "You may pass script yourself ({\"commands\": [{\"command\": ..., \"params\": {...}}]}, the commands SolidCraft's interface runs; no file commands). "
        "template four_bar (the Chebyshev linkage from SolidCraft's examples) or two_finger_gripper (two fingers on meshing gears) builds a tested design. "
        "params sets the script's parameters by name, in mm or degrees. "
        "Returns mass and volume for the material, the bounding box, the bodies of each part, the joints and motion links, the motion studies, "
        "the parameters that became sliders and SolidCraft's picture of the design; the CAD tab shows it with STEP and STL. "
        "Then export_urdf writes its robot description and runs it in MuJoCo."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string", "description": "What it is for, its parts, the joints between them and the key dimensions."},
            "params": {"type": "object", "description": "Parameter values by name, in mm or degrees, e.g. {\"jaw_opening\": 60}. Favourite parameters become sliders."},
            "material": {"type": "string", "enum": sorted(DENSITY_G_CM3)},
            "template": {"type": "string", "enum": list(LIBRARY)},
            "script": {"type": "object", "description": "A SolidCraft command script: {\"commands\": [...]}."},
        },
        "required": ["name"],
    },
}

EXPORT_SCHEMA = {
    "name": "export_urdf",
    "description": (
        "The robot description of the last SolidCraft design: SolidCraft's URDF (one link per part with its mesh, mass and inertia, one joint per joint) "
        "and MJCF for MuJoCo with what a URDF cannot hold put back: each joint that closes a loop (closed with an equality), the motion links "
        "(gears, mirrored parts) as joint couplings, and the pose as built. Then it runs the MJCF in MuJoCo through the design's motion study and "
        "checks that every joint is there and moves, the loops stay closed, every part follows SolidCraft's own study, and every part's mass matches "
        "SolidCraft's measure within 1 %. effort (N m or N) and velocity (rad/s or m/s) are the joint limits written into the URDF; "
        "leave them out for SolidCraft's defaults."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "effort": {"type": "number", "minimum": 0},
            "velocity": {"type": "number", "minimum": 0},
        },
    },
}

_CONTRACT = """You write a SolidCraft command script that builds one part or one mechanism.
SolidCraft is parametric CAD. The script is the list of commands its own interface runs:
{"commands": [{"command": "parameters.add", "params": {"name": "w", "expression": "60 mm"}}, ...]}.
AnyBuild runs it headless with solidcraft-cli VERSION, then assigns the material, measures, exports and draws it itself.
Rules:
- Millimetres and degrees, Z up, -Y is the front. Centre the design on X = Y = 0.
- Start with parameters.add for every key dimension and every value in the parameters you are given, under exactly those names.
  Mark the ones a person would tune with "favorite": true; they become sliders. Use parameter names in expressions
  ("w/2 - wall"), so the design follows them; a plain number never does.
- Name every body (body_name) and feature.
- A mechanism: one component per part that moves on its own (component.create, its bodies, then component.activate root),
  occurrence.ground for the base, joints by world point and axis on both sides with flip true, joint.motion_link or joint.gear
  for parts that move together, and one motion.study that keys the driving joint through its working range:
  AnyBuild drives that study in MuJoCo to check the exported robot.
- Only commands that model, assemble, move and measure: no file, document, view, render or canvas commands, nothing with a path.
- The command shapes, the sketch plane axes, the ids and the traps are in SolidCraft's skills below. They were written for
  SolidCraft's MCP tools (batch, execute, measure, screenshot); here you write the whole command list at once, and when a
  command fails you get SolidCraft's error and write the corrected full script. The tool names (batch, execute, measure,
  screenshot, set_parameter, inspect_design, body_topology, skill_reference) are not commands: a parameter change is
  parameters.change, a measurement inspect.measure.
Answer with one ```json code block that holds {"commands": [...]}, and nothing else."""


def _fail(message: str, **extra) -> dict:
    return {"ok": False, "error": message, "detail": message[:160], **extra}


def _slug(name: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "part")[:40]


def library_script(name: str) -> dict:
    return json.loads((solidcraft.LIBRARY_DIR / LIBRARY[name]["file"]).read_text(encoding="utf-8"))


def _template_for(args: dict) -> str | None:
    template = str(args.get("template") or "").strip().lower()
    if template in LIBRARY:
        return template
    text = (str(args.get("name", "")) + " " + str(args.get("description", ""))).lower()
    for key, entry in LIBRARY.items():
        if any(word in text for word in entry["keywords"]):
            return key
    return None


def _numbers(raw: object) -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                value = value.get("value")
            try:
                out[str(key)] = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
    return out


def _positive(args: dict, key: str) -> float | None:
    value = args.get(key)
    if value is None:
        return None
    number = float(value)
    if not number > 0:
        raise ValueError(key + " must be a positive number.")
    return number


def skills() -> str:
    """SolidCraft's skills, as the CAD agent reads them: each SKILL.md with its reference."""

    parts = []
    for skill in ("solidcraft-modeling", "solidcraft-mechanisms"):
        folder = solidcraft.SKILLS_DIR / skill
        parts.append(f"# SolidCraft skill {skill} (SKILL.md)\n\n" + (folder / "SKILL.md").read_text(encoding="utf-8"))
        parts.append(f"# SolidCraft skill {skill} (reference.md)\n\n" + (folder / "reference.md").read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def _system() -> list[dict]:
    example = json.dumps(library_script("two_finger_gripper"), indent=1)
    text = (
        _CONTRACT.replace("VERSION", solidcraft.VERSION)
        + "\n\nA working AnyBuild script, a two-finger gripper on meshing gears with a motion study:\n```json\n"
        + example
        + "\n```\n\nSolidCraft's skills follow (MIT, Copyright (c) 2026 SolidCraft contributors).\n\n"
        + skills()
    )
    # The same long instructions for every part and every fix: cached.
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _extract_json(text: str) -> str:
    match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start >= 0 and end > start else text.strip()


def _write_script(description: str, params: dict, previous: str | None, error: str | None, run=None) -> str:
    """The CAD agent writes a SolidCraft script; with a previous script and its error, it writes the fix."""

    from pai_agent.agents import create_message

    prompt = "Design to build: " + description + "\nParameters: " + json.dumps(params) + "\n"
    if previous is not None:
        prompt += "\nYour last script failed in SolidCraft.\n```json\n" + previous + "\n```\nError:\n" + str(error) + "\nWrite the corrected full script."
    config = settings.current()
    response = create_message(
        config["subagent_model"],
        config["subagent_effort"],
        max_tokens=16000,
        system=_system(),
        messages=[{"role": "user", "content": prompt}],
    )
    if run is not None:
        run.count(response)
    text = "".join(str(getattr(block, "text", "")) for block in response.content if getattr(block, "type", None) == "text")
    return _extract_json(text)


def _sliders(parameters: list[dict]) -> dict:
    """The CAD tab's sliders: the design's favourite parameters that are plain lengths or angles, else all such."""

    plain = [row for row in parameters if row.get("source", "user") == "user" and row.get("unit") in ("mm", "deg") and _PLAIN.match(str(row.get("expression", "")))]
    chosen = [row for row in plain if row.get("favorite")] or plain
    out = {}
    for row in chosen[:MAX_SLIDERS]:
        value = float(row["value"])
        if row["unit"] == "mm":
            low, high = round(value * 0.5, 1), round(max(value * 2.0, value + 1.0), 1)
        else:
            low, high = max(-360.0, value - 90.0), min(360.0, value + 90.0)
        out[row["name"]] = {"value": round(value, 3), "min": low, "max": high, "unit": row["unit"]}
    return out


def _tree(build: solidcraft.Build) -> list[dict]:
    """The design, one node per component with its bodies; bodies of the root sit right under the design."""

    children = []
    for component in build.components:
        if component.get("parent") is None:
            continue
        bodies = [{"id": _slug(component["name"] + "-" + body), "label": body, "children": []} for body in component.get("bodies") or []]
        children.append({"id": _slug(component["name"]), "label": component["name"], "children": bodies})
    owned = {body for component in build.components if component.get("parent") is not None for body in component.get("bodies") or []}
    children += [{"id": _slug(body["name"]), "label": body["name"], "children": []} for body in build.bodies if body["name"] not in owned]
    return [{"id": _slug(build.name), "label": build.name, "children": children}]


def _joint_rows(build: solidcraft.Build) -> list[dict]:
    names = {}
    for component in build.components:
        for occurrence in component.get("occurrences") or []:
            names[int(occurrence["id"])] = component["name"] if component.get("parent") is not None else "the design"
    names[0] = "the design"
    rows = []
    for joint in build.joints:
        rows.append(
            {
                "name": joint["name"],
                "type": joint["type"],
                "parts": [names.get(int(joint["a"]), str(joint["a"])), names.get(int(joint["b"]), str(joint["b"]))],
                "values": [
                    {"name": v.get("name"), "value": round(float(v.get("value") or 0.0), 4), "unit": v.get("unit"), "limits": v.get("limits")}
                    for v in joint.get("values") or []
                ],
            }
        )
    return rows


def _link_rows(build: solidcraft.Build) -> list[dict]:
    by_id = {int(joint["id"]): joint["name"] for joint in build.joints}
    rows = []
    for link in build.links:
        row = {"drives": by_id.get(int(link["a"]), link["a"]), "follows": by_id.get(int(link["b"]), link["b"])}
        if "ratio" in link:
            row["ratio"] = link["ratio"]
        if link.get("coupling"):
            row["coupling"] = link["coupling"].get("type")
        rows.append(row)
    return rows


async def solidcraft_part(ctx: Ctx, args: dict) -> dict:
    material = str(args.get("material") or "PLA").strip().upper().replace("ALUMINUM", "ALUMINIUM")
    if material not in DENSITY_G_CM3:
        return _fail("material must be one of " + ", ".join(sorted(DENSITY_G_CM3)) + ".")
    why = solidcraft.missing()
    if why:
        message = f"SolidCraft is not installed on this machine: {why}. {solidcraft.INSTALL_HINT}"
        return _fail(message, next="Say in one sentence that SolidCraft is not installed here; build the part with cad_part in FreeCAD instead.")
    name = str(args.get("name") or "").strip()
    description = str(args.get("description") or "").strip()
    params = _numbers(args.get("params"))
    template = _template_for(args)
    script = args.get("script") or None
    rebuild = bool(args.get("_rebuild"))
    # A library template builds as it is; Claude writes or fixes every other script.
    from_library = False
    if script is None and template is not None and (args.get("template") or not claude_enabled()):
        script = library_script(template)
        name = name or LIBRARY[template]["name"]
        from_library = True
    if script is None and not claude_enabled():
        return _fail("Writing a SolidCraft script needs Claude (ANTHROPIC_API_KEY). Templates: " + ", ".join(LIBRARY) + ".")
    if script is None and not description:
        return _fail("description is required when no script or template is given.")
    if script is not None and params:
        # A parameter the script does not have is a wrong call, not a script to fix.
        try:
            solidcraft.with_params(solidcraft.check_script(script), params)
        except ValueError as exc:
            return _fail(str(exc))
        except solidcraft.ScriptRejected:
            pass
    name = name or "Part"
    stem = "solidcraft-" + _slug(name)
    directory = Path(ctx.state.directory)
    attempts: list[dict] = []
    build = None
    commands: list[dict] | None = None
    error = None
    agent = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if script is None or attempt > 1:
            if rebuild or not claude_enabled():
                break
            from_library = False
            if agent is None:
                config = settings.current()
                agent = AgentRun(ctx, "cad", CAD_ROLE["label"], config["subagent_model"], config["subagent_effort"], "SolidCraft script for " + name)
            await agent.emit("running", "writes the script" if attempt == 1 else "fixes the script, attempt " + str(attempt))
            await _progress(ctx, "solidcraft_part", ("CAD agent writes the SolidCraft script for " + name if attempt == 1 else "CAD agent fixes the script, attempt " + str(attempt)))
            previous = None if script is None else (script if isinstance(script, str) else json.dumps(script, indent=1))
            try:
                script = await asyncio.to_thread(_write_script, description or name, params, previous, error, agent)
            except Exception as exc:
                log.exception("SolidCraft script writer failed")
                await agent.emit("error", str(exc)[:160])
                return _fail("Claude could not write the script: " + str(exc))
        await _progress(ctx, "solidcraft_part", "SolidCraft builds " + name + (" (attempt " + str(attempt) + ")" if attempt > 1 else ""))
        if agent is not None:
            await agent.use("solidcraft", "SolidCraft builds " + name)
        try:
            commands = solidcraft.check_script(script)
            built = solidcraft.with_params(commands, params) if params else commands
            build = await asyncio.to_thread(solidcraft.build, built, material, DENSITY_G_CM3[material], directory, stem, name)
            attempts.append({"attempt": attempt, "ok": True})
            if agent is not None:
                agent.called("solidcraft", {"detail": name + " built"})
            break
        except (solidcraft.ScriptRejected, solidcraft.SolidCraftFailed, ValueError) as exc:
            error = str(exc)
            attempts.append({"attempt": attempt, "ok": False, "error": error[:300]})
            if agent is not None:
                agent.called("solidcraft", {"ok": False, "error": error[:160]})
            await _progress(ctx, "solidcraft_part", "Attempt " + str(attempt) + " failed: " + error[:90])
    if agent is not None:
        await agent.emit("done" if build is not None else "error", name + (" built" if build is not None else " failed") + " after " + str(len(attempts)) + " SolidCraft run(s)")
    if build is None or commands is None:
        return _fail(
            "The SolidCraft script failed " + str(len(attempts)) + " time(s). Last error: " + str(error),
            attempts=attempts,
            script=script if isinstance(script, (dict, str)) else None,
        )

    state = ctx.state
    sliders = copy.deepcopy(args.get("_sliders")) or _sliders(build.parameters)
    values = {row["name"]: float(row["value"]) for row in build.parameters}
    for key, slider in sliders.items():
        slider["value"] = round(values.get(key, slider["value"]), 3)
    state.cad_builds += 1
    n = state.cad_builds
    generated = bool(args.get("_generated", not from_library))
    state.solidcraft = {
        "name": name,
        "design": build.name,
        "description": description,
        "material": material,
        "script": {"commands": commands},
        "params": params,
        "template": template,
        "stem": stem,
        "sliders": sliders,
        "assigned": build.assigned,
        "studies": [{"name": row["name"], "steps": row.get("steps")} for row in build.studies],
        "mass_g": build.mass_g,
        "bbox_mm": build.bbox_mm,
        "cad_build": n,
        "generated": generated,
        "files": {kind: path.name for kind, path in build.files.items()},
    }
    session = state.session_id

    def url(kind: str) -> str | None:
        path = build.files.get(kind)
        return "/files/" + session + "/" + path.name + "?build=" + str(n) if path else None

    await ctx.emit(
        {
            "type": "cad",
            "source": "solidcraft",
            "tree": _tree(build),
            "params": sliders,
            "glb_url": url("glb"),
            "stl_url": url("stl"),
            "step_url": url("step"),
            "view_png_url": None,
            "script_url": url("script"),
            "design_url": url("design"),
            "part": {
                "name": name,
                "material": material,
                "mass_g": build.mass_g,
                "bbox_mm": build.bbox_mm,
                "attempts": len(attempts),
                "generated": generated,
            },
        }
    )
    size = build.bbox_mm
    dims = " x ".join(f"{size[i + 3] - size[i]:.0f}" for i in range(3))
    parts = [component["name"] for component in build.components if component.get("parent") is not None]
    detail = f"SolidCraft {solidcraft.VERSION}, {build.mass_g:.1f} g {material}, {dims} mm"
    if build.joints:
        detail += f", {len(parts)} parts on {len(build.joints)} joint{'s' if len(build.joints) != 1 else ''}"
    if len(attempts) > 1:
        detail += ", fixed after " + str(len(attempts) - 1) + " failed attempt(s)"
    result = {
        "ok": True,
        "detail": detail,
        "source": "solidcraft",
        "name": name,
        "design": build.name,
        "material": material,
        "mass_g": build.mass_g,
        "volume_mm3": build.volume_mm3,
        "bbox_mm": build.bbox_mm,
        "parts": [
            {"name": component["name"], "bodies": component.get("bodies") or [], "grounded": any(o.get("grounded") for o in component.get("occurrences") or [])}
            for component in build.components
            if component.get("parent") is not None
        ],
        "bodies": [
            {**{k: body[k] for k in ("name", "component", "mass_g", "volume_mm3", "material")}, "bbox_mm": [round(v, 2) for v in body["bbox_mm"]]}
            for body in build.bodies
        ],
        "joints": _joint_rows(build),
        "motion_links": _link_rows(build),
        "motion_studies": [{"name": row["name"], "steps": row.get("steps")} for row in build.studies],
        "sliders": sliders,
        "attempts": attempts,
        "picture": "SolidCraft's iso view of the design as built" if "png" in build.files else None,
    }
    if build.warnings:
        result["warnings"] = build.warnings
    if build.joints:
        result["next"] = "Look at the picture; then export_urdf writes the robot description and runs it in MuJoCo."
    if "png" in build.files:
        import base64

        result[IMAGE] = base64.b64encode(build.files["png"].read_bytes()).decode("ascii")
    return result


async def rebuild_solidcraft(ctx: Ctx, changes: dict) -> dict:
    """A slider moved in the CAD tab: the same script with the new value, no Claude needed."""

    design = ctx.state.solidcraft
    if not design:
        return _fail("No SolidCraft design to rebuild.")
    params = dict(design["params"])
    for key, value in _numbers(changes).items():
        slider = design["sliders"].get(key)
        if slider is None:
            raise ValueError(key + " is not a parameter of this design.")
        if not slider["min"] <= value <= slider["max"]:
            raise ValueError(key + " must be between " + str(slider["min"]) + " and " + str(slider["max"]) + ".")
        params[key] = value
    return await solidcraft_part(
        ctx,
        {
            "name": design["name"],
            "description": design["description"],
            "material": design["material"],
            "script": design["script"],
            "params": params,
            "_sliders": design["sliders"],
            "_generated": design["generated"],
            "_rebuild": True,
        },
    )


def is_current(state) -> bool:
    """Whether the newest CAD build is the SolidCraft design, so its sliders and its STEP belong to the CAD tab."""

    return bool(state.solidcraft) and state.solidcraft.get("cad_build") == state.cad_builds


async def export_urdf(ctx: Ctx, args: dict) -> dict:
    design = ctx.state.solidcraft
    if not design:
        return _fail("No SolidCraft design yet: build the mechanism with solidcraft_part first.")
    why = solidcraft.missing()
    if why:
        message = f"SolidCraft is not installed on this machine: {why}. {solidcraft.INSTALL_HINT}"
        return _fail(message, next="Say in one sentence that SolidCraft is not installed here.")
    try:
        effort, velocity = _positive(args, "effort"), _positive(args, "velocity")
    except (TypeError, ValueError) as exc:
        return _fail(str(exc) if isinstance(exc, ValueError) else "effort and velocity must be numbers.")
    commands = design["script"]["commands"]
    if design["params"]:
        commands = solidcraft.with_params(commands, design["params"])
    extra = solidcraft.material_commands(design["material"], DENSITY_G_CM3[design["material"]], design["assigned"])
    study = design["studies"][0] if design["studies"] else None
    directory = Path(ctx.state.directory)
    stem = design["stem"] + "-robot"
    mjcf = directory / (stem + ".mjcf.xml")
    try:
        await _progress(ctx, "export_urdf", "SolidCraft writes the URDF of " + design["name"])
        robot = await asyncio.to_thread(solidcraft.export_robot, commands, extra, directory, stem, effort, velocity, study)
        await _progress(ctx, "export_urdf", "MuJoCo reads the URDF; AnyBuild closes its loops")
        converted = await asyncio.to_thread(solidcraft_mjcf.mjcf_from_urdf, robot, mjcf)
        await _progress(ctx, "export_urdf", "MuJoCo drives " + (study["name"] if study else "nothing: the design has no motion study"))
        report = await asyncio.to_thread(solidcraft_mjcf.check_mjcf, robot, mjcf, converted)
    except solidcraft.SolidCraftFailed as exc:
        return _fail("SolidCraft could not export the design: " + str(exc))
    except ValueError as exc:
        # MuJoCo raises ValueError for a model it cannot compile.
        return _fail("MuJoCo could not read the exported robot: " + str(exc))
    session = ctx.state.session_id
    urdf_joints = set(converted["urdf_joints"])
    loops = {row["joint"] for row in converted["loops_closed"]} | {row["joint"] for row in converted["loops_open"]}
    travel = {row["joint"]: row for row in report["travel"]}
    joints = []
    for joint in robot.joints.get("joints") or []:
        name = solidcraft.mj_name(joint["name"])
        moved = travel.get(name)
        row = {
            "name": joint["name"],
            "type": joint["type"],
            "in_urdf": name in urdf_joints,
            "in_mujoco": name in converted["joints"] or joint["name"] in {r["joint"] for r in converted["loops_closed"]},
            "closes_loop": joint["name"] in loops,
        }
        if moved:
            row["travel"] = {"value": moved["travel"], "unit": moved["unit"]}
        joints.append(row)
    checks = report["checks"]
    passed = report["passed"]
    loop_text = ""
    if converted["loops_closed"]:
        loop_text = " closes " + ", ".join(row["joint"] for row in converted["loops_closed"]) + f" (gap {_mm(report['loop_gap_mm'])})"
    summary = (
        f"{design['design']}: URDF with {len(urdf_joints)} of {len(joints)} joints, MJCF with {len(converted['joints'])} MuJoCo joints"
        + (";" + loop_text if loop_text else "")
        + (f"; MuJoCo drove {report['study']} and every part stayed within {max(report['deviation_mm'], 0.001):.3f} mm of SolidCraft" if checks["follows_study"] else "")
        + f"; masses within {report['mass_error_pct']:.2f} % of SolidCraft's measure."
    )
    failed = [key for key, ok in checks.items() if not ok]
    warnings = list(robot.warnings) + [
        "No drives: a URDF carries none, so the MJCF has no actuators"
        + (f"; put the motor on {', '.join(report['drivers'])}" if report["drivers"] else "")
        + ".",
        "Each part collides as the convex hull of its mesh; a concave part (a cup, a slot) needs a convex decomposition first.",
    ]
    warnings += [f"Loop {row['joint']} is not closed: {row['why']}." for row in converted["loops_open"]]
    warnings += [f"Motion link {row['link']} is not coupled: {row['why']}." for row in converted["uncoupled"]]
    if not report["study"]:
        warnings.append("The design has no motion study, so MuJoCo did not drive it; add one that keys the driving joint.")

    def url(path: Path) -> str:
        return "/files/" + session + "/" + path.name

    return {
        "ok": True,
        "result": "pass" if passed else "fail",
        "detail": ("pass: " if passed else "fail (" + ", ".join(failed) + "): ") + summary,
        "design": design["design"],
        "files": {"urdf": url(robot.urdf), "mjcf": url(mjcf), "meshes": [url(path) for path in robot.meshes]},
        "joints": joints,
        "loops_closed": converted["loops_closed"],
        "couplings": converted["couplings"],
        "checks": checks,
        "study": report["study"],
        "drivers": report["drivers"],
        "samples": report["samples"],
        "deviation_mm": report["deviation_mm"],
        "loop_gap_mm": report["loop_gap_mm"],
        "coupling_error": report["coupling_error"],
        "masses": report["masses"],
        "total_mass_g": report["total_mass_g"],
        "warnings": warnings,
        "next": "Say in one sentence whether the robot passed: the joints, the loop, the mass; name a failed check first.",
    }


def _mm(value: float) -> str:
    return "under 0.001 mm" if value < 0.001 else f"{value:.3f} mm"


async def _progress(ctx: Ctx, tool: str, detail: str) -> None:
    await ctx.emit({"type": "tool", "name": tool, "status": "running", "detail": detail})
