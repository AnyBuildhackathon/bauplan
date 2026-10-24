"""Tools that operate the dashboard: the 3D pointer, drawings, the mascot and the app controls.

`ui_point_at` and `ui_draw` aim at named targets of the 3D scene (`scene.py`, mirrored in
docs/events.md), so Mechanic can point at the part that failed a check. `ui_control` presses a
real control (tabs, views, explode, compare, BOM): the dashboard flies a visible pointer to the
control and clicks it, so the audience sees what the agent does. `run_test` and `run_rebuild`
back the run buttons. Targets and controls are validated here and an unknown one returns an
error the model can correct.
"""

from __future__ import annotations

import asyncio
import itertools

from pai_agent.context import Ctx
from pai_agent.scene import CONTROLS, DRAW_KINDS, MASCOT_STATES, PART_TARGETS, TARGETS


def _bad_target(target: object) -> dict | None:
    if target not in TARGETS:
        message = "target must be one of " + ", ".join(TARGETS) + "."
        return {"ok": False, "error": message, "detail": message}
    return None


async def ui_point_at(ctx: Ctx, args: dict) -> dict:
    target = args.get("target")
    invalid = _bad_target(target)
    if invalid:
        return invalid
    label = str(args.get("label", ""))
    await ctx.emit({"type": "point", "target": target, "label": label})
    return {"ok": True, "detail": str(target)}


async def ui_draw(ctx: Ctx, args: dict) -> dict:
    kind = args.get("kind")
    target = args.get("target")
    if kind not in DRAW_KINDS:
        message = "kind must be halo, arrow, circle or note."
        return {"ok": False, "error": message, "detail": message}
    invalid = _bad_target(target)
    if invalid:
        return invalid
    text = str(args.get("text", ""))
    await ctx.emit({"type": "draw", "kind": kind, "target": target, "text": text})
    return {"ok": True, "detail": str(kind) + " " + str(target)}


async def mascot_say(ctx: Ctx, args: dict) -> dict:
    state = args.get("state")
    say = str(args.get("say", "")).strip()
    if state not in MASCOT_STATES:
        message = "state must be ruhig, denkt, erklaert, freut_sich or besorgt."
        return {"ok": False, "error": message, "detail": message}
    if not say:
        message = "say is missing."
        return {"ok": False, "error": message, "detail": message}
    await ctx.emit({"type": "mascot", "state": state, "say": say})
    return {"ok": True, "detail": str(state)}


# Long enough for the pointer to fly to the control and press it before a run starts.
_PRESS_S = 1.6
_ids = itertools.count(1)

_SAY = {
    "tab:model": "Here is the 3D model.",
    "tab:cad": "Here is the CAD.",
    "tab:simulation": "Here is the simulation.",
    "tab:omniverse": "Here is Omniverse.",
    "view:workbench": "Back to the workbench.",
    "view:library": "Here is the library.",
    "view:training": "Here is the training.",
    "view:logbook": "Here is the logbook.",
    "panel:bom": "Here is the bill of materials.",
    "panel:guide": "Here is the build guide.",
    "panel:compare": "Side by side.",
    "panel:settings": "Here are the settings.",
    "explode": "Pulling it apart.",
    "focus": "Look here.",
    "run:test": "Running the test again.",
    "run:rebuild": "Rebuilding it.",
}


def control_list() -> str:
    """The controls as prompt lines, for the orchestrator and the voice model."""

    lines = [f"- {control}: {text}" for control, text in CONTROLS.items()]
    lines.append("- library:{id}: open one library item; reference_load without id lists the ids")
    return "\n".join(lines)


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message}


def _check(ctx: Ctx, control: str, args: dict) -> dict | None:
    state = ctx.state
    if control.startswith("library:"):
        from pai_agent.references import list_references

        if control[8:] not in {row["id"] for row in list_references()}:
            return _fail("Unknown library item " + control[8:] + ". reference_load without id lists them.")
        return None
    if control not in CONTROLS:
        return _fail("control must be one of " + ", ".join(CONTROLS) + " or library:{id}.")
    if control == "tab:omniverse" and state.product != "drone":
        return _fail("Omniverse supports the drone only.")
    if control == "panel:bom" and args.get("open", True) and not state.bom:
        return _fail("There is no bill of materials yet.")
    if control == "panel:compare":
        numbers = [v["n"] for v in state.versions]
        if len(numbers) < 2:
            return _fail("Comparing needs two versions; there are " + str(len(numbers)) + ".")
        pair = args.get("versions") or numbers[-2:]
        if not isinstance(pair, list) or len(pair) != 2 or any(n not in numbers for n in pair) or pair[0] == pair[1]:
            return _fail("versions must be two different built versions out of " + ", ".join(str(n) for n in numbers) + ".")
    if control == "explode":
        try:
            value = float(args.get("value", 100))
        except (TypeError, ValueError):
            return _fail("value must be a number from 0 to 100.")
        if not 0 <= value <= 100:
            return _fail("value must be from 0 to 100.")
    if control.startswith("setting:") and not isinstance(args.get("value", True), bool):
        return _fail("value must be true or false.")
    if control == "focus":
        part = str(args.get("part") or "").strip()
        if not part:
            return _fail("focus needs part.")
        if state.product == "drone" and not state.part and part not in PART_TARGETS:
            return _fail("part must be one of " + ", ".join(PART_TARGETS) + ".")
    if control.startswith("run:") and not (state.selected or state.built or state.part):
        return _fail("Nothing is built yet.")
    return None


def _default_say(control: str, args: dict) -> str:
    name = control.split(":", 1)[-1].replace("_", " ")
    if control.startswith("panel:") and args.get("open") is False:
        return "Closing the " + {"bom": "bill of materials", "guide": "build guide", "compare": "comparison"}.get(name, name) + "."
    if control.startswith("setting:"):
        on = args.get("value", True) is not False
        if control == "setting:voice":
            return "Speaking again." if on else "Going quiet."
        return ("Turning on " if on else "Turning off ") + {"agents": "agent steps", "tools": "tool details", "jamie": "Jamie activity", "push to talk": "push-to-talk"}.get(name, name) + "."
    if control == "explode" and not float(args.get("value", 100) or 0):
        return "Putting it back together."
    if control.startswith("library:"):
        return "Opening it in the library."
    return _SAY.get(control, "")


def ui_event(control: str, args: dict) -> dict:
    event: dict = {"type": "ui", "id": "u" + str(next(_ids)), "control": control, "say": str(args.get("say") or "").strip() or _default_say(control, args)}
    if control.startswith("panel:"):
        event["open"] = bool(args.get("open", True))
    if control == "panel:compare":
        event["versions"] = args.get("versions")
    if control == "explode":
        event["value"] = round(float(args.get("value", 100)), 1)
    if control.startswith("setting:"):
        event["value"] = bool(args.get("value", True))
    if control == "focus":
        event["part"] = str(args["part"]).strip()
    return event


async def ui_control(ctx: Ctx, args: dict) -> dict:
    control = str(args.get("control") or "").strip()
    invalid = _check(ctx, control, args)
    if invalid:
        return invalid
    event = ui_event(control, args)
    if control == "panel:compare" and not event["versions"]:
        event["versions"] = [v["n"] for v in ctx.state.versions][-2:]
    await ctx.emit(event)
    if control == "run:test":
        await asyncio.sleep(_PRESS_S)
        return await run_test(ctx)
    if control == "run:rebuild":
        await asyncio.sleep(_PRESS_S)
        return await run_rebuild(ctx)
    return {"ok": True, "detail": control}


async def run_test(ctx: Ctx) -> dict:
    """The product's own MuJoCo test, the one the Simulation tab replays."""

    from pai_agent.tools.registry import call_tool

    state = ctx.state
    if state.product == "generic":
        stored = state.checks.get("stability", {}).get("args") if isinstance(state.checks.get("stability"), dict) else None
        return await call_tool(ctx, "simulate_assembly", dict(stored or {}))
    if state.product == "gripper":
        return await call_tool(ctx, "simulate_grip", {})
    return await call_tool(ctx, "simulate_drone", {})


async def run_rebuild(ctx: Ctx) -> dict:
    """Builds the CAD again from the current numbers, then reruns the numbers and the test."""

    from pai_agent.tools.registry import call_tool

    state = ctx.state
    if state.product == "generic":
        result = await call_tool(ctx, "assemble", {})
        if result.get("ok") is False:
            return result
        return await call_tool(ctx, "check_totals", {})
    if state.product == "gripper":
        from pai_agent.tools.cad_part import rebuild_part

        result = await rebuild_part(ctx, {})
        if result.get("ok") is False:
            return result
        await call_tool(ctx, "grip_calc", {})
        return await call_tool(ctx, "simulate_grip", {})
    from pai_agent.tools.cad import DEFAULT_PARAMS

    params = {**DEFAULT_PARAMS, **(state.cad_params or {})}
    result = await call_tool(ctx, "cad_frame", {k: params[k] for k in ("arm_length_mm", "thickness_mm", "motor_spacing_mm")})
    if result.get("ok") is False:
        return result
    await call_tool(ctx, "physics_calc", {})
    return await call_tool(ctx, "simulate_drone", {})
