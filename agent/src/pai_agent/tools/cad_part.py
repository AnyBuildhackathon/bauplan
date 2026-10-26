"""General CAD: any part from a description, as a FreeCAD Python script Claude writes.

The agent passes a description and parameters, and optionally the script itself.
Without a script, Claude writes one. The script runs headless and sandboxed
(pai_agent.cad_script); when FreeCAD reports an error, Claude gets the script and
the error back and writes a fixed version, up to three attempts. Without an API
key, named templates from agent/freecad/library stand in for the writer.

A script declares its parameters in PARAMS (pai_agent.part_params): value, range, step,
unit, label and group each. They become the CAD tab's sliders, and the values the user
sets there stay with the part when Mechanic changes or rewrites it.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pai_agent import part_params, settings
from pai_agent.agents import CAD_ROLE, AgentRun
from pai_agent.cad_script import DENSITY_G_CM3, ScriptFailed, ScriptRejected, freecad_unavailable, run_block, run_script, run_script_cached
from pai_agent.context import Ctx
from pai_agent.env import claude_enabled
from pai_agent.fasteners import hardware
from pai_agent.part_params import ParamsError
from pai_agent.paths import AGENT_ROOT, REPO_ROOT

log = logging.getLogger(__name__)

LIBRARY_DIR = AGENT_ROOT / "freecad" / "library"
MAX_ATTEMPTS = 3
# Several parts can be written by their CAD agents at once; FreeCAD builds and the assembly go one at a time.
_BUILD = asyncio.Lock()

# Templates: a known script plus its parameters' defaults and ranges.
LIBRARY = {
    "gripper": {
        "file": "gripper.py",
        "keywords": ("gripper", "greifer", "claw", "jaw"),
        "params": {
            "finger_length_mm": (70.0, 45.0, 110.0),
            "jaw_opening_mm": (76.0, 30.0, 110.0),
            "finger_thickness_mm": (6.0, 4.0, 10.0),
            "pad_thickness_mm": (3.0, 1.5, 6.0),
        },
        # Label, group and step of each; with the defaults and ranges above they are the template's PARAMS.
        "labels": {
            "finger_length_mm": ("Finger length", "Fingers", 1.0),
            "jaw_opening_mm": ("Jaw opening", "Jaw", 1.0),
            "finger_thickness_mm": ("Finger thickness", "Fingers", 0.5),
            "pad_thickness_mm": ("Pad thickness", "Fingers", 0.5),
        },
    },
}

_CONTRACT = """You write FreeCAD Python that builds one physical part or a small assembly.
Rules:
- Units are millimetres, Z is up. Build everything in its assembled position.
- Available without import: Part, App (FreeCAD), Vector (FreeCAD.Vector), math, P, the parameter values,
  and H, the standard parts the request lists (empty when it lists none).
  You may also `import math`, `import FreeCAD`, `import Part`. Nothing else can be imported.
- No file access, no exports, no getattr/eval/exec/open, no dunder attributes. The harness exports for you.
- Start the script with PARAMS, which declares every parameter a person may tune, as plain data written out:
  PARAMS = {
      "width_mm": {"value": 60.0, "min": 30.0, "max": 120.0, "step": 1.0, "unit": "mm", "label": "Width", "group": "Body"},
      "wall_mm": {"value": 2.0, "min": 1.2, "max": 4.0, "step": 0.2, "unit": "mm", "label": "Wall", "group": "Body"},
      "slots": {"type": "integer", "value": 3, "min": 0, "max": 8, "label": "Vent slots", "group": "Vents"},
      "feet": {"value": True, "label": "Feet recesses", "group": "Base"},
      "mount": {"value": "screw", "options": ["screw", "clip"], "label": "Mount", "group": "Base"},
  }
  value is the default (the request's value when it gives one), min and max the range in which the part still builds
  and makes sense, step the slider step, label a short name, group the feature it shapes. A True/False value is a switch,
  options make a choice. Declare every parameter the request lists, and only parameters the script uses.
- Read them as P["width_mm"]: P holds each declared parameter's value to build with (its default, or what Mechanic or the
  user set) and the fixed inputs the request names. Reading any other name from P fails.
- Prefer Part.makeBox, makeCylinder, makeCone, makeSphere, makeTorus, extrude of Part.Face(Part.makePolygon([...closed list])),
  fuse, cut, common, translate, rotate, makeFillet on simple solids. Keep boolean operations under about 150.
- At the end set either `shape = <solid>` or `parts = {"Name": solid, ...}` for an assembly.
  Optional: colors = {"Name": "#rrggbb"}, materials = {"Name": "TPU"} (PLA, PETG, ABS, ASA, NYLON, TPU, ALUMINIUM, STEEL),
  reference = ["Name", ...] for bought parts that are shown but not printed (a servo, a PCB).
- Every part must be a closed solid with positive volume.
Answer with one ```python code block and nothing else."""


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message[:160]}


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or "part")[:40]


def library_script(name: str) -> str:
    return (LIBRARY_DIR / LIBRARY[name]["file"]).read_text(encoding="utf-8")


def template_params(name: str) -> dict:
    """A library template's PARAMS, checked: its scripts predate the contract and read P with defaults."""

    entry = LIBRARY[name]
    raw = {}
    for key, (default, low, high) in entry["params"].items():
        label, group, step = entry["labels"][key]
        raw[key] = {"value": default, "min": low, "max": high, "step": step, "unit": "mm", "label": label, "group": group}
    return part_params.check(raw)


def _template_for(args: dict) -> str | None:
    template = str(args.get("template") or "").strip().lower()
    if template in LIBRARY:
        return template
    text = (str(args.get("name", "")) + " " + str(args.get("description", ""))).lower()
    for key, entry in LIBRARY.items():
        if any(word in text for word in entry["keywords"]):
            return key
    return None


def _values(raw: object) -> dict:
    """Parameter values by name: numbers as floats, True/False for a switch, text for a choice; anything else is left out."""

    out: dict = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                value = value.get("value")
            if isinstance(value, bool):
                out[str(key)] = value
                continue
            try:
                out[str(key)] = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                if isinstance(value, str) and value.strip():
                    out[str(key)] = value.strip()
    return out


def _slider_params(values: dict, entries: dict | None, editable: list[str] | None = None) -> dict:
    """The CAD tab's params: the part's declared ones (its PARAMS or a template's), else half to double each mm value."""

    if entries is not None:
        return part_params.payload(entries, values)
    names = editable if editable is not None else [k for k in values if k.endswith("_mm")]
    payload = {}
    for name in names:
        value = values.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        low, high = sorted((round(value * 0.5, 1), round(value * 2.0, 1)))
        payload[name] = {"value": round(value, 2), "min": low, "max": max(high, round(value + 1.0, 1)), "unit": "mm"}
    return payload


@dataclass
class _Plan:
    """One build of a script: P, the CAD tab's params, PARAMS for the harness, and what became of the user's values."""

    values: dict
    sliders: dict
    contract: object | None = None
    declared: bool = False
    user: dict = field(default_factory=dict)
    overridden: dict = field(default_factory=dict)
    dropped: dict = field(default_factory=dict)


def _plan(
    script: str,
    template: str | None,
    params: dict,
    user: dict,
    inputs: dict,
    previous: dict | None = None,
    written: bool = False,
    editable: list[str] | None = None,
) -> _Plan:
    """What the script builds with: its declared defaults, then Mechanic's values, then the user's, plus the fixed inputs.

    Raises ParamsError when PARAMS or Mechanic's values do not fit; a script the CAD agent wrote must declare PARAMS."""

    found = part_params.declaration(script)
    if found is None and written:
        raise ParamsError(["Start the script with PARAMS, declaring every parameter it reads from P, as the rules show."])
    entries, contract = found if found is not None else (template_params(template) if template else None, None)
    if entries is not None:
        resolved = part_params.resolve(entries, params, user)
        sliders = part_params.payload(resolved.entries, resolved.values)
        return _Plan({**resolved.values, **inputs}, sliders, contract, True, resolved.user, resolved.overridden, resolved.dropped)
    # A script from before the contract: Mechanic's values are its parameters, the user's win, the slider ranges are estimated
    # (the last build's, so they do not drift with every move; a declared payload belongs to a script this is not).
    applied = {name: value for name, value in user.items() if name in params}
    values = {**params, **applied}
    estimated = previous if previous and not any("type" in slider for slider in previous.values()) else None
    sliders = {name: dict(slider) for name, slider in (estimated or _slider_params(values, None, editable)).items()}
    for name, slider in sliders.items():
        value = values.get(name, slider["value"])
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            slider["value"] = round(value, 2)
    overridden = {name: params[name] for name, value in applied.items() if params[name] != value}
    dropped = {name: "the part has no parameter " + name + " any more" for name in user if name not in params}
    return _Plan({**values, **inputs}, sliders, user=applied, overridden=overridden, dropped=dropped)


def _extract_code(text: str) -> str:
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    return (match.group(1) if match else text).strip() + "\n"


def _write_script(
    description: str,
    params: dict,
    previous: str | None,
    error: str | None,
    context: str = "",
    run=None,
    inputs: dict | None = None,
    user: dict | None = None,
) -> str:
    """The CAD sub-agent writes a script; with a previous script and its error, it writes the fix."""

    from pai_agent.agents import create_message

    # The template's simulation data (joints, tool, collision) is not part of the script contract, so the example stops before it.
    example = library_script("gripper").split("# Kinematics for simulation exports")[0].rstrip() + "\n"
    prompt = (
        context
        + "Part to build: " + description + "\nParameters (declare each in PARAMS, its value as the default; lengths in mm): " + repr(params) + "\n"
        + ("The user set these with the CAD sliders; keep each as a parameter whose range includes its value: " + repr(user) + "\n" if user else "")
        + ("Fixed inputs in P (read them, never declare them): " + repr(inputs) + "\n" if inputs else "")
        + "\nHere is a working example of the modelling style (a robot gripper; it predates PARAMS and reads P with defaults):\n```python\n"
        + example + "```\n"
    )
    if previous is not None:
        prompt += "\nYour last script failed.\n```python\n" + previous + "```\nError:\n" + str(error) + "\nWrite the corrected full script."
    config = settings.current()
    response = create_message(
        config["subagent_model"],
        config["subagent_effort"],
        max_tokens=16000,
        system=_CONTRACT,
        messages=[{"role": "user", "content": prompt}],
    )
    if run is not None:
        run.count(response)
    text = "".join(str(getattr(block, "text", "")) for block in response.content if getattr(block, "type", None) == "text")
    return _extract_code(text)


def _tree(name: str, parts: list[dict], standard: list[dict]) -> list[dict]:
    children = []
    for part in parts:
        label = part["name"] + (" (bought)" if part.get("reference") else "")
        children.append({"id": _slug(part["name"]), "label": label, "children": []})
    return [{"id": _slug(name), "label": name, "children": children + hardware.tree_nodes(_slug(name), standard)}]


def _product_context(state, part: dict) -> str:
    """What the script writer needs to know about the rest of the product, so the parts fit."""

    spec = state.spec
    lines = [
        "Product: " + spec["name"] + ". " + spec["function"],
        "Assembly frame: millimetres, Z up, the product stands on Z = 0, centred on X = Y = 0, -Y is the front.",
        "Build this part where it sits in the assembly, as its description says.",
        "position_mm is the centre of a part's bounding box: " + ("this part is moved so its centre sits at " + str(part["position_mm"]) + "." if part.get("position_mm") else "this part has none, so it stays exactly where you build it."),
        "Its envelope is about " + " x ".join(f"{v:g}" for v in part["size_mm"]) + " mm (X x Y x Z); the build is checked against it.",
        "The other parts:",
    ]
    for other in spec["parts"]:
        if other["id"] == part["id"]:
            continue
        line = "- " + other["name"] + " (" + other["kind"] + ")"
        info = state.built.get(other["id"])
        if info:
            line += ", built, bbox " + str([round(v) for v in info["bbox_mm"]])
        elif other.get("size_mm"):
            line += ", about " + " x ".join(f"{v:g}" for v in other["size_mm"]) + " mm"
        if other.get("position_mm"):
            line += " centred at " + str(other["position_mm"])
        if other.get("description"):
            line += ": " + other["description"]
        lines.append(line)
    return "\n".join(lines) + "\n\n"


def _template_envelope(template: str | None, params: dict) -> list[float] | None:
    """The outer size of a library template from its parameters, for the CadQuery stand-in."""

    if template != "gripper":
        return None
    finger = params.get("finger_thickness_mm", 6.0) + params.get("pad_thickness_mm", 3.0)
    return [params.get("jaw_opening_mm", 76.0) + 2 * finger + 16.0, 30.0, params.get("finger_length_mm", 70.0) + 45.0]


def _block_script(size: list[float], center: list[float] | None) -> str:
    """The last resort after failed attempts: a plain block of the part's envelope, so the build goes on."""

    cx, cy, cz = center or (0.0, 0.0, size[2] / 2.0)
    return (
        "# Simplified block: the generated script failed, this keeps the assembly buildable.\n"
        f"shape = Part.makeBox({size[0]:g}, {size[1]:g}, {size[2]:g}, Vector({cx - size[0] / 2:g}, {cy - size[1] / 2:g}, {cz - size[2] / 2:g}))\n"
    )


async def cad_part(ctx: Ctx, args: dict) -> dict:
    spec_part = None
    if ctx.state.product == "generic" and ctx.state.spec:
        from pai_agent.spec import find_part

        spec_part = find_part(ctx.state.spec, str(args.get("part_id") or args.get("name") or ""), "printed")
        if spec_part is None or spec_part["kind"] != "printed":
            printed = ", ".join(p["id"] for p in ctx.state.spec["parts"] if p["kind"] == "printed")
            return _fail("part_id must be a printed part of the spec: " + printed + ".")
        args = {
            **args,
            "name": spec_part["name"],
            "description": args.get("description") or spec_part["description"],
            "material": args.get("material") or spec_part["material"],
            "params": {**spec_part["params"], **(args.get("params") or {})},
        }
    name = str(args.get("name") or "").strip() or "Part"
    description = str(args.get("description") or "").strip()
    material = str(args.get("material") or "PLA").strip().upper()
    if material.replace("ALUMINUM", "ALUMINIUM") not in DENSITY_G_CM3:
        return _fail("material must be one of " + ", ".join(sorted(DENSITY_G_CM3)) + ".")
    params = _values(args.get("params"))
    # A spec part keeps its standard parts in the spec; fasteners passed here replace them there too.
    raw = args.get("fasteners")
    if raw is None and spec_part is not None:
        raw = spec_part.get("fasteners")
    fasteners, problems = hardware.normalize(raw, name)
    if problems:
        return {**_fail("The fasteners have " + str(len(problems)) + " problem(s): " + " | ".join(problems)), "problems": problems}
    if spec_part is not None and args.get("fasteners") is not None:
        if fasteners:
            spec_part["fasteners"] = fasteners
        else:
            spec_part.pop("fasteners", None)
    # A spec part only uses a template when it asks for one by name; keywords in its description do not count.
    template = _template_for(args) if spec_part is None or args.get("template") else None
    script = str(args.get("script") or "").strip() or None
    if script is None and template is not None and (args.get("template") or not claude_enabled()):
        script = library_script(template)
    if script is None and not claude_enabled():
        return _fail("Writing a new part script needs Claude (ANTHROPIC_API_KEY). Known templates: " + ", ".join(LIBRARY) + ".")
    if script is None and not description:
        return _fail("description is required when no script or template is given.")
    inputs: dict = {}
    if ctx.state.product == "gripper":
        from pai_agent.tools.gripper import servo_params

        # The chosen servo decides the pocket, whoever wrote the script: fixed inputs in P, never parameters.
        inputs = servo_params(ctx.state)
    params = {k: v for k, v in params.items() if k not in inputs}
    # The user's values for this part win over the script's defaults and Mechanic's values, except the ones Mechanic takes over.
    part_key = spec_part["id"] if spec_part else _slug(name)
    replace = set(part_params.names(args.get("replace_user_values")))
    user = {k: v for k, v in (ctx.state.user_params.get(part_key) or {}).items() if k not in replace}
    plan = None
    if script is not None:
        # A template's script declares its parameters in LIBRARY; any other script declares its own or none.
        own = template if template is not None and script == library_script(template) else None
        try:
            plan = _plan(script, own, params, user, inputs, args.get("_sliders"), editable=args.get("editable"))
        except ParamsError as exc:
            return {**_fail("The parameters do not fit the script: " + str(exc)), "problems": exc.problems}

    stem = "part-" + _slug(spec_part["id"] if spec_part else name)
    directory = Path(ctx.state.directory)
    expected = spec_part["size_mm"] if spec_part else None
    context = (_product_context(ctx.state, spec_part) if spec_part else "") + hardware.describe(fasteners)
    passed_script = bool(args.get("script"))
    attempts: list[dict] = []
    build = None
    error = None
    fallback = False
    cached = False
    block_source = None
    agent = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if freecad_unavailable(None):
            # No FreeCAD on this machine: no script can build, so no CAD agent is paid to write one; the envelope stands in below.
            error = error or "freecadcmd is not installed, so generated parts cannot be built on this machine."
            break
        if script is None or attempt > 1:
            if not claude_enabled():
                break
            if agent is None:
                config = settings.current()
                agent = AgentRun(ctx, "cad", CAD_ROLE["label"], config["subagent_model"], config["subagent_effort"], "FreeCAD script for " + name)
            await agent.emit("running", "writes the script" if attempt == 1 else "fixes the script, attempt " + str(attempt))
            await _progress(ctx, ("CAD agent writes the FreeCAD script for " + name if attempt == 1 else "CAD agent fixes the script, attempt " + str(attempt)))
            try:
                script = await asyncio.to_thread(
                    _write_script, description or name, params, script if attempt > 1 else None, error, context, agent, inputs, user
                )
            except Exception as exc:
                log.exception("script writer failed")
                await agent.emit("error", str(exc)[:160])
                return _fail("Claude could not write the script: " + str(exc))
            plan = None
        await _progress(ctx, "freecadcmd builds " + name + (" (attempt " + str(attempt) + ")" if attempt > 1 else ""))
        if agent is not None:
            await agent.use("freecad", "FreeCAD builds " + name)
        try:
            if plan is None:
                # The CAD agent's own script: its PARAMS goes back to it like a FreeCAD error when it does not fit.
                plan = _plan(script, None, params, user, inputs, written=True)
            async with _BUILD:
                build, cached = await asyncio.to_thread(
                    run_script_cached, script, plan.values, directory, stem, material, expected_mm=expected, fasteners=fasteners, contract=plan.contract
                )
            attempts.append({"attempt": attempt, "ok": True, **({"cached": True} if cached else {})})
            if agent is not None:
                agent.called("freecad", {"detail": name + " built" + (" (cached)" if cached else "")})
            break
        except (ScriptRejected, ScriptFailed, ValueError) as exc:
            error = str(exc)
            attempts.append({"attempt": attempt, "ok": False, "error": error[:300]})
            if agent is not None:
                agent.called("freecad", {"ok": False, "error": error.splitlines()[0][:160] if error else "FreeCAD failed"})
            await _progress(ctx, "Attempt " + str(attempt) + " failed: " + error.splitlines()[0][:90])
    if agent is not None:
        outcome = "built" if build is not None else "failed"
        await agent.emit("done" if build is not None else "error", name + " " + outcome + " after " + str(len(attempts)) + " FreeCAD run(s)")
    if build is None and spec_part is not None and not passed_script:
        # Never leave a live build without geometry: a plain block of the envelope stands in, clearly marked.
        failed_script = script
        script = _block_script(spec_part["size_mm"], spec_part.get("position_mm"))
        try:
            # The block keeps the standard parts and their holes; one it buries is reported, not fatal.
            async with _BUILD:
                build = await asyncio.to_thread(run_script, script, {**params, **inputs}, directory, stem, material, fasteners=fasteners, strict=False)
            fallback = True
            attempts.append({"attempt": len(attempts) + 1, "ok": True, "fallback": True})
        except (ScriptRejected, ScriptFailed, ValueError):
            script = failed_script
    envelope = spec_part["size_mm"] if spec_part is not None else _template_envelope(template, plan.values if plan else params)
    if build is None and envelope and freecad_unavailable(error):
        # FreeCAD is missing or stuck: CadQuery stands in with the envelope, so the run never stops at CAD.
        try:
            build = await asyncio.to_thread(run_block, envelope, spec_part.get("position_mm") if spec_part else None, directory, stem, material, fasteners)
            fallback = True
            block_source = "cadquery"
            attempts.append({"attempt": len(attempts) + 1, "ok": True, "fallback": True, "source": "cadquery"})
        except Exception as exc:
            log.warning("CadQuery block failed: %s", exc)
    if build is None:
        return {
            **_fail("The part script failed " + str(len(attempts)) + " time(s). Last error: " + str(error)),
            "attempts": attempts,
            "script": script,
        }

    state = ctx.state
    if plan is None or (fallback and block_source is None):
        # A stand-in block reads no parameters (FreeCAD's after failed scripts, or CadQuery's before any script ran):
        # the numbers stay as they were, with estimated sliders. CadQuery standing in for a known script keeps its sliders.
        plan = _plan("", None, params, user, inputs, args.get("_sliders"), editable=args.get("editable"))
    sliders = plan.sliders
    # What this build used stays the user's; values Mechanic took over are its own now, and ones a rewritten script
    # no longer has are gone. A stand-in block says nothing about the script, so it drops nothing.
    mine = user if fallback else plan.user
    if mine:
        state.user_params[part_key] = dict(mine)
    else:
        state.user_params.pop(part_key, None)
    # Each standard part carries its price per piece like a pick, so the assembly cost and the bill of materials agree.
    standard = [hardware.price(row) for row in build.hardware]
    state.part = {
        "name": name,
        "description": description,
        "material": material,
        "script": script,
        "params": plan.values,
        "template": template,
        "sliders": sliders,
        # Whether the sliders come from a declaration (the script's PARAMS or a template's), not an estimate.
        "declared": plan.declared,
        "parts": build.parts,
        "mass_g": build.mass_g,
        "bbox_mm": build.bbox_mm,
        # Joints, tool frame and collision shapes of a template that can be simulated (pai_agent/mjcf_export.py).
        "sim": build.sim,
        "fasteners": fasteners,
        "hardware": standard,
    }
    state.frame_mass_g = build.mass_g
    state.stl_path = build.stl.relative_to(REPO_ROOT).as_posix()
    generated = bool(args.get("_generated", template is None or passed_script)) and not fallback
    if spec_part is not None:
        state.built[spec_part["id"]] = {
            **state.part,
            "parts": [{**row, "material": row.get("material") or material} for row in build.parts],
            "attempts": len(attempts),
            "generated": generated,
            "fallback": fallback,
            "last_error": error if fallback else None,
        }
        state.assembly_stale = True
        state.bom = None
    state.cad_builds += 1
    n = state.cad_builds
    session = state.session_id

    def url(path: Path) -> str:
        return "/files/" + session + "/" + path.name + "?build=" + str(n)

    await ctx.emit(
        {
            "type": "cad",
            "source": block_source or "freecad",
            "tree": _tree(name, build.parts, standard),
            "params": sliders,
            "glb_url": url(build.glb),
            "stl_url": url(build.stl),
            "step_url": url(build.step),
            "view_png_url": None,
            "script_url": url(directory / (stem + ".py")),
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
    if spec_part is not None:
        # The part goes into the assembly right away, so the model grows part by part.
        from pai_agent.tools.product import ensure_assembly

        async with _BUILD:
            await ensure_assembly(ctx)
    else:
        # A part on its own (the gripper) is its build: a surface check of it follows the new shape.
        from pai_agent.tools.surface import refresh_surface

        await refresh_surface(ctx)
    size = build.bbox_mm
    dims = " x ".join(f"{size[i + 3] - size[i]:.0f}" for i in range(3))
    detail = "FreeCAD headless, " + f"{build.mass_g:.1f}" + " g " + material + ", " + dims + " mm"
    if block_source == "cadquery":
        detail = "FreeCAD unavailable (" + str(error or "").splitlines()[0][:80] + "): CadQuery block for " + name
    elif fallback:
        detail = "Simplified block for " + name + " after " + str(len(attempts) - 1) + " failed script(s)"
    elif cached:
        detail += ", reused the identical FreeCAD build"
    elif len(attempts) > 1:
        detail += ", fixed after " + str(len(attempts) - 1) + " failed attempt(s)"
    extra = {}
    if fallback:
        extra = {
            "fallback": True,
            "last_error": str(error)[:400],
            "note": "The script failed every attempt, so a plain block of the envelope stands in. Call cad_part again with a simpler description or your own script.",
        }
        if block_source == "cadquery":
            extra["note"] = "FreeCAD is not available on this machine or did not answer, so CadQuery built a plain block of the envelope. Its mass is the solid block's."
    if cached:
        extra["cached"] = True
    if standard:
        detail += ", " + str(len(standard)) + " standard part" + ("s" if len(standard) > 1 else "")
        keys = ("name", "designation", "hole", "hole_d_mm", "radial_gap_mm", "mass_g", "unit_price_eur", "price_source")
        extra["hardware"] = [{key: row[key] for key in keys} for row in standard]
    if build.hardware_warnings:
        extra["hardware_warnings"] = build.hardware_warnings
    extra.update(_user_report(state, part_key, plan, fallback))
    return {
        **extra,
        "ok": True,
        "detail": detail,
        "source": block_source or "freecad",
        "name": name,
        "mass_g": build.mass_g,
        "volume_mm3": build.volume_mm3,
        "bbox_mm": build.bbox_mm,
        "params": {k: v for k, v in plan.values.items() if k not in inputs},
        "parts": [{k: p[k] for k in ("name", "volume_mm3", "mass_g", "material", "reference", "bbox_mm")} for p in build.parts],
        "stl_path": state.stl_path,
        "attempts": attempts,
    }


def _user_report(state, part_key: str, plan: _Plan, fallback: bool = False) -> dict:
    """What Mechanic reads about the user's values: the ones this part keeps, Mechanic's values they replaced, and any
    that no longer fit."""

    out: dict = {}
    if state.user_params.get(part_key):
        out["user_values"] = dict(state.user_params[part_key])
        out["user_values_note"] = part_params.USER_NOTE
    if plan.overridden and not fallback:
        out["overridden_by_user"] = dict(plan.overridden)
    if plan.dropped and not fallback:
        out["dropped_user_values"] = dict(plan.dropped)
        out["dropped_note"] = "These values the user set no longer fit the part, so it uses the script's own; tell the user."
    return out


async def rebuild_part(ctx: Ctx, changes: dict) -> dict:
    """A slider moved in the CAD tab: run the same script with the user's new value, no Claude needed.

    The value is the user's from now on (state.user_params), so it stays when Mechanic changes or rewrites the part."""

    part = ctx.state.part
    if not part:
        return _fail("No generated part to rebuild.")
    values = {}
    for key, raw in changes.items():
        slider = part["sliders"].get(key)
        if slider is None:
            raise ValueError(key + " is not a parameter of this part.")
        value = part_params.coerce(key, slider, raw)
        part_params.in_range(key, slider, value)
        values[key] = value
    part_key = _slug(part["name"])
    before = part_params.remember(ctx.state, part_key, values) if values else None
    result = await cad_part(
        ctx,
        {
            "name": part["name"],
            "description": part["description"],
            "material": part["material"],
            "script": part["script"],
            "params": dict(part["params"]),
            "fasteners": part.get("fasteners") or [],
            "_sliders": {key: dict(value) for key, value in part["sliders"].items()},
        },
    )
    if result.get("ok") is False and before is not None:
        part_params.restore(ctx.state, part_key, before)
    return result


async def _progress(ctx: Ctx, detail: str) -> None:
    await ctx.emit({"type": "tool", "name": "cad_part", "status": "running", "detail": detail})
