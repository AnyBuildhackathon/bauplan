"""General CAD: any part from a description, as a FreeCAD Python script Claude writes.

The agent passes a description and parameters, and optionally the script itself.
Without a script, Claude writes one. The script runs headless and sandboxed
(pai_agent.cad_script); when FreeCAD reports an error, Claude gets the script and
the error back and writes a fixed version, up to three attempts. Without an API
key, named templates from agent/freecad/library stand in for the writer.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from pai_agent.cad_script import DENSITY_G_CM3, ScriptFailed, ScriptRejected, run_script
from pai_agent.context import Ctx
from pai_agent.env import claude_enabled, model_name
from pai_agent.paths import AGENT_ROOT, REPO_ROOT

log = logging.getLogger(__name__)

LIBRARY_DIR = AGENT_ROOT / "freecad" / "library"
MAX_ATTEMPTS = 3

# Templates: a known script plus slider ranges for its parameters.
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
    },
}

_CONTRACT = """You write FreeCAD Python that builds one physical part or a small assembly.
Rules:
- Units are millimetres, Z is up. Build everything in its assembled position.
- Available without import: Part, App (FreeCAD), Vector (FreeCAD.Vector), math, and P, a dict of the parameters in mm.
  You may also `import math`, `import FreeCAD`, `import Part`. Nothing else can be imported.
- No file access, no exports, no getattr/eval/exec/open, no dunder attributes. The harness exports for you.
- Prefer Part.makeBox, makeCylinder, makeCone, makeSphere, makeTorus, extrude of Part.Face(Part.makePolygon([...closed list])),
  fuse, cut, common, translate, rotate, makeFillet on simple solids. Keep boolean operations under about 150.
- Read every dimension from P with a default, e.g. W = P.get("width_mm", 60.0).
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


def _slider_params(params: dict[str, float], template: str | None, editable: list[str] | None) -> dict:
    """Slider ranges for the CAD tab: the template's own, else half to double the value."""

    known = LIBRARY[template]["params"] if template else {}
    names = editable if editable is not None else (list(known) if known else [k for k in params if k.endswith("_mm")])
    payload = {}
    for name in names:
        if name not in params:
            continue
        value = params[name]
        if name in known:
            low, high = known[name][1], known[name][2]
        else:
            low, high = round(value * 0.5, 1), round(max(value * 2.0, value + 1.0), 1)
        payload[name] = {"value": round(value, 2), "min": low, "max": high, "unit": "mm"}
    return payload


def _extract_code(text: str) -> str:
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    return (match.group(1) if match else text).strip() + "\n"


def _write_script(description: str, params: dict, previous: str | None, error: str | None) -> str:
    """Asks Claude for a script; with a previous script and its error, asks for the fix."""

    import anthropic

    example = library_script("gripper")
    prompt = (
        "Part to build: " + description + "\nParameters P (mm): " + repr(params) + "\n\n"
        "Here is a working example of the style (a robot gripper):\n```python\n" + example + "```\n"
    )
    if previous is not None:
        prompt += "\nYour last script failed in FreeCAD.\n```python\n" + previous + "```\nError:\n" + str(error) + "\nWrite the corrected full script."
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model_name(),
        max_tokens=6000,
        system=_CONTRACT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(str(getattr(block, "text", "")) for block in response.content)
    return _extract_code(text)


def _tree(name: str, parts: list[dict]) -> list[dict]:
    children = []
    for part in parts:
        label = part["name"] + (" (bought)" if part.get("reference") else "")
        children.append({"id": _slug(part["name"]), "label": label, "children": []})
    return [{"id": _slug(name), "label": name, "children": children}]


async def cad_part(ctx: Ctx, args: dict) -> dict:
    name = str(args.get("name") or "").strip() or "Part"
    description = str(args.get("description") or "").strip()
    material = str(args.get("material") or "PLA").strip().upper()
    if material.replace("ALUMINUM", "ALUMINIUM") not in DENSITY_G_CM3:
        return _fail("material must be one of " + ", ".join(sorted(DENSITY_G_CM3)) + ".")
    params = _numbers(args.get("params"))
    template = _template_for(args)
    script = str(args.get("script") or "").strip() or None
    if script is None and template is not None and (args.get("template") or not claude_enabled()):
        script = library_script(template)
    if script is None and not claude_enabled():
        return _fail("Writing a new part script needs Claude (ANTHROPIC_API_KEY). Known templates: " + ", ".join(LIBRARY) + ".")
    if script is None and not description:
        return _fail("description is required when no script or template is given.")
    if template is not None:
        for key, (default, _low, _high) in LIBRARY[template]["params"].items():
            params.setdefault(key, default)
    if ctx.state.product == "gripper":
        from pai_agent.tools.gripper import servo_params

        # The chosen servo decides the pocket, whoever wrote the script.
        params.update(servo_params(ctx.state))

    stem = "part-" + _slug(name)
    directory = Path(ctx.state.directory)
    attempts: list[dict] = []
    build = None
    error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if script is None or attempt > 1:
            if not claude_enabled():
                break
            await _progress(ctx, ("Claude writes the FreeCAD script" if attempt == 1 else "Claude fixes the script, attempt " + str(attempt)))
            try:
                script = await asyncio.to_thread(_write_script, description or name, params, script if attempt > 1 else None, error)
            except Exception as exc:
                log.exception("script writer failed")
                return _fail("Claude could not write the script: " + str(exc))
        await _progress(ctx, "freecadcmd builds " + name + (" (attempt " + str(attempt) + ")" if attempt > 1 else ""))
        try:
            build = await asyncio.to_thread(run_script, script, params, directory, stem, material)
            attempts.append({"attempt": attempt, "ok": True})
            break
        except (ScriptRejected, ScriptFailed, ValueError) as exc:
            error = str(exc)
            attempts.append({"attempt": attempt, "ok": False, "error": error[:300]})
            await _progress(ctx, "Attempt " + str(attempt) + " failed: " + error.splitlines()[0][:90])
    if build is None:
        return {
            **_fail("The part script failed " + str(len(attempts)) + " time(s). Last error: " + str(error)),
            "attempts": attempts,
            "script": script,
        }

    state = ctx.state
    sliders = args.get("_sliders") or _slider_params(params, template, args.get("editable"))
    for key, slider in sliders.items():
        slider["value"] = round(params.get(key, slider["value"]), 2)
    state.part = {
        "name": name,
        "description": description,
        "material": material,
        "script": script,
        "params": params,
        "template": template,
        "sliders": sliders,
        "parts": build.parts,
        "mass_g": build.mass_g,
        "bbox_mm": build.bbox_mm,
    }
    state.frame_mass_g = build.mass_g
    state.stl_path = build.stl.relative_to(REPO_ROOT).as_posix()
    state.cad_builds += 1
    n = state.cad_builds
    session = state.session_id

    def url(path: Path) -> str:
        return "/files/" + session + "/" + path.name + "?build=" + str(n)

    await ctx.emit(
        {
            "type": "cad",
            "source": "freecad",
            "tree": _tree(name, build.parts),
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
                "generated": template is None or bool(args.get("script")),
            },
        }
    )
    size = build.bbox_mm
    dims = " x ".join(f"{size[i + 3] - size[i]:.0f}" for i in range(3))
    detail = "FreeCAD headless, " + f"{build.mass_g:.1f}" + " g " + material + ", " + dims + " mm"
    if len(attempts) > 1:
        detail += ", fixed after " + str(len(attempts) - 1) + " failed attempt(s)"
    return {
        "ok": True,
        "detail": detail,
        "source": "freecad",
        "name": name,
        "mass_g": build.mass_g,
        "volume_mm3": build.volume_mm3,
        "bbox_mm": build.bbox_mm,
        "parts": [{k: p[k] for k in ("name", "volume_mm3", "mass_g", "material", "reference", "bbox_mm")} for p in build.parts],
        "stl_path": state.stl_path,
        "attempts": attempts,
    }


async def rebuild_part(ctx: Ctx, changes: dict) -> dict:
    """A slider moved in the CAD tab: run the same script with the new numbers, no Claude needed."""

    part = ctx.state.part
    if not part:
        return _fail("No generated part to rebuild.")
    params = dict(part["params"])
    for key, value in _numbers(changes).items():
        slider = part["sliders"].get(key)
        if slider is None:
            raise ValueError(key + " is not a parameter of this part.")
        if not slider["min"] <= value <= slider["max"]:
            raise ValueError(key + " must be between " + str(slider["min"]) + " and " + str(slider["max"]) + ".")
        params[key] = value
    return await cad_part(
        ctx,
        {
            "name": part["name"],
            "description": part["description"],
            "material": part["material"],
            "script": part["script"],
            "params": params,
            "_sliders": {key: dict(value) for key, value in part["sliders"].items()},
        },
    )


async def _progress(ctx: Ctx, detail: str) -> None:
    await ctx.emit({"type": "tool", "name": "cad_part", "status": "running", "detail": detail})
