"""Tool schemas and the single dispatch both Claude and the mock use."""

from __future__ import annotations

from pai_agent.context import Ctx
from pai_agent.requirements import refresh_requirements
from pai_agent.scene import DRAW_KINDS, MASCOT_STATES, PART_CATEGORIES, TARGETS
from pai_agent.freecad_run import find_freecadcmd
from pai_agent.tools.blender import blender_render, find_blender
from pai_agent.tools.bom import bom_build
from pai_agent.tools.cad import cad_frame
from pai_agent.tools.cad_part import cad_part
from pai_agent.tools.gripper import catalog_search, grip_calc, product_brief, simulate_grip
from pai_agent.tools.isaac import isaac_lab_status, isaac_lab_train, isaac_sim_render, isaac_test, isaac_train, ssh_setting
from pai_agent.tools.usd import product_usd
from pai_agent.jamie_client import live_enabled
from pai_agent.tools.ask import ask_user
from pai_agent.tools.jamie import (
    jamie_create_tasks,
    jamie_meeting,
    jamie_requirements,
    jamie_search,
    jamie_templates,
    requirements_accept,
    version_commit,
)
from pai_agent.tools.parts import parts_search
from pai_agent.tools.physics import physics_calc
from pai_agent.tools.simulate import simulate_drone
from pai_agent.tools.ui import mascot_say, ui_draw, ui_point_at

TOOLS = {
    "jamie_templates": jamie_templates,
    "jamie_requirements": jamie_requirements,
    "jamie_search": jamie_search,
    "jamie_meeting": jamie_meeting,
    "requirements_accept": requirements_accept,
    "ask_user": ask_user,
    "version_commit": version_commit,
    "parts_search": parts_search,
    "physics_calc": physics_calc,
    "simulate_drone": simulate_drone,
    "cad_frame": cad_frame,
    "cad_part": cad_part,
    "product_brief": product_brief,
    "catalog_search": catalog_search,
    "grip_calc": grip_calc,
    "simulate_grip": simulate_grip,
    "isaac_lab_train": isaac_lab_train,
    "isaac_lab_status": isaac_lab_status,
    "isaac_sim_render": isaac_sim_render,
    "isaac_test": isaac_test,
    "isaac_train": isaac_train,
    "product_usd": product_usd,
    "blender_render": blender_render,
    "bom_build": bom_build,
    "jamie_create_tasks": jamie_create_tasks,
    "ui_point_at": ui_point_at,
    "ui_draw": ui_draw,
    "mascot_say": mascot_say,
}

_STEP = {
    "jamie_requirements": "meeting",
    "jamie_meeting": "meeting",
    "parts_search": "teile",
    "physics_calc": "teile",
    "cad_frame": "cad",
    "cad_part": "cad",
    "product_brief": "meeting",
    "catalog_search": "teile",
    "grip_calc": "teile",
    "simulate_grip": "simulation",
    "blender_render": "render",
    "isaac_sim_render": "render",
    "simulate_drone": "simulation",
    "isaac_lab_train": "training",
    "isaac_train": "training",
    "isaac_lab_status": "training",
    "bom_build": "stueckliste",
    "jamie_create_tasks": "stueckliste",
}

SCHEMAS = [
    {
        "name": "product_usd",
        "description": "Drone only: export the current CAD product through Blender as a portable USD assembly with per-part masses in kilograms. Build CAD and select all parts first.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "isaac_test",
        "description": "Drone only: test the current exported product in NVIDIA Isaac Sim on an SSH GPU host. Returns a completed video and JSON measurements for wind gusts, added payload or hover stability. Without a working host, returns an explicitly recorded illustrative demo whose numbers do not describe this request.",
        "input_schema": {"type": "object", "properties": {
            "scenario": {"type": "string", "enum": ["wind", "payload", "hover"]},
            "wind_m_s": {"type": "number", "minimum": 0, "maximum": 20},
            "payload_g": {"type": "number", "minimum": 0, "maximum": 500},
            "duration_s": {"type": "number", "minimum": 2, "maximum": 20},
        }},
    },
    {
        "name": "isaac_train",
        "description": "Drone only: train Isaac Lab's reference Crazyflie task Isaac-Quadcopter-Direct-v0 on an SSH GPU host. Returns video and learning curve. This trains the stock reference robot, not the CAD product. Recorded fallback is illustrative, never a fresh training result.",
        "input_schema": {"type": "object", "properties": {
            "iterations": {"type": "integer", "minimum": 1, "maximum": 1000},
            "num_envs": {"type": "integer", "minimum": 1, "maximum": 256},
        }},
    },
    {
        "name": "jamie_templates",
        "description": "Creates the Jamie summary templates Hardware-Anforderungen and Drohnen-Review (upsert_template). Once per session.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "jamie_requirements",
        "description": "Reads the kickoff requirements from Jamie, each with quote, person and time. Without meeting_id, the newest kickoff.",
        "input_schema": {"type": "object", "properties": {"meeting_id": {"type": "string"}}},
    },
    {
        "name": "jamie_search",
        "description": "Searches earlier Jamie meetings (search_meetings), for example for a part, to find warnings.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "jamie_meeting",
        "description": "Reads a finished review: changed requirements, conflicts with earlier meetings, and complaints about parts. A complaint about 'last week' is already resolved to the part from that earlier meeting (refers_to).",
        "input_schema": {
            "type": "object",
            "properties": {"meeting_id": {"type": "string"}},
            "required": ["meeting_id"],
        },
    },
    {
        "name": "requirements_accept",
        "description": "Accepts requirements from a meeting into the build. ids picks some, omitting ids takes all. On conflicts, ask_user first.",
        "input_schema": {
            "type": "object",
            "properties": {"meeting_id": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["meeting_id"],
        },
    },
    {
        "name": "ask_user",
        "description": "Asks the room and waits for a click, speech or text. With no answer, default_id applies after a short wait.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}, "label": {"type": "string"}},
                        "required": ["id", "label"],
                    },
                },
                "default_id": {"type": "string"},
            },
            "required": ["question", "options", "default_id"],
        },
    },
    {
        "name": "version_commit",
        "description": "Closes a version: hangs it on the meeting it came from, computes the difference from the last version, writes that note to Jamie and tags the meeting.",
        "input_schema": {"type": "object", "properties": {"meeting_id": {"type": "string"}}},
    },
    {
        "name": "parts_search",
        "description": "Searches the curated catalog. Every hit includes jamie_notes, what earlier meetings said about the part. select_id chooses the part; because names the requirement or 'complaint'; reason is your one-sentence reason. Prices are samples.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": list(PART_CATEGORIES)},
                "query": {"type": "string"},
                "select_id": {"type": "string"},
                "because": {"type": "string", "enum": ["budget", "flight_time", "weight", "hover", "printable", "complaint"]},
                "reason": {"type": "string"},
            },
            "required": ["category"],
        },
    },
    {
        "name": "physics_calc",
        "description": "Computes mass, thrust-to-weight, estimated flight time and sample price from the chosen parts.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "simulate_drone",
        "description": "MuJoCo hover test. Mass and peak thrust come from the chosen parts. fail means too heavy, pass means it holds the hover.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cad_frame",
        "description": "Builds the parametric frame in FreeCAD, otherwise in CadQuery. Writes STL, STEP and GLB. arm_length_mm is the distance from the center to the motor shaft. motor_spacing_mm is the bolt-circle diameter of the motor screws. On the 1102 that is 6.6.",
        "input_schema": {
            "type": "object",
            "properties": {
                "arm_length_mm": {"type": "number"},
                "thickness_mm": {"type": "number"},
                "motor_spacing_mm": {"type": "number"},
            },
            "required": ["arm_length_mm", "thickness_mm", "motor_spacing_mm"],
        },
    },
    {
        "name": "cad_part",
        "description": (
            "General CAD for any part or small assembly (a mount, an enclosure, a gripper, a bracket). "
            "Builds it headless in FreeCAD from a Python script and returns STEP, STL and GLB, volume, mass for the material and the bounding box. "
            "Without script, Claude writes the script from description and params, and when FreeCAD reports an error it is fixed and retried up to 3 times. "
            "You may pass script yourself: FreeCAD Python that sets `shape` or `parts` = {name: solid}; Part, App, Vector, math and P (the params) are predefined, "
            "nothing else can be imported, no file access. template 'gripper' uses the tested robot gripper script. "
            "For the gripper, the servo pocket follows the chosen servo automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string", "description": "What the part is for, its features and key dimensions."},
                "params": {"type": "object", "description": "Dimensions in mm, e.g. {\"width_mm\": 60}. They become sliders in the CAD tab."},
                "material": {"type": "string", "enum": ["PLA", "PETG", "ABS", "ASA", "NYLON", "TPU", "ALUMINIUM", "STEEL"]},
                "template": {"type": "string", "enum": ["gripper"]},
                "script": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "product_brief",
        "description": (
            "Starts a build for a product and turns the request into requirement checks. product is drone or gripper. "
            "For the gripper pass object_mass_g, object_width_mm, optionally max_weight_g and budget_eur, and quote, the user's sentence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product": {"type": "string", "enum": ["drone", "gripper"]},
                "object_mass_g": {"type": "number"},
                "object_width_mm": {"type": "number"},
                "max_weight_g": {"type": "number"},
                "budget_eur": {"type": "number"},
                "quote": {"type": "string"},
            },
            "required": ["product"],
        },
    },
    {
        "name": "catalog_search",
        "description": "Searches the gripper parts catalog (servo, pads, hardware, driver). select_id chooses a part, reason is your one-line reason. Prices are samples.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["servo", "pads", "hardware", "driver"]},
                "query": {"type": "string"},
                "select_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["category"],
        },
    },
    {
        "name": "grip_calc",
        "description": "Gripper numbers from the chosen parts and the CAD finger length: finger force, holding force with pad friction, safety factor against the object weight (needs 2x), weight and sample price.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "simulate_grip",
        "description": "MuJoCo grip test: the pads squeeze the object with the finger force, the arm lifts it 15 cm and shakes it. pass means it stays within 10 mm, fail means it slips or drops.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "isaac_lab_train",
        "description": "Compatibility alias for isaac_train. Returns a completed reference Crazyflie training result or an explicitly recorded illustrative fallback.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "isaac_lab_status",
        "description": "Return the latest Omniverse session result or progress. New jobs return finished artifacts without polling.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
        },
    },
    {
        "name": "isaac_sim_render",
        "description": "Compatibility alias for isaac_test with the default wind scenario. Use isaac_test to specify experiment conditions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "blender_render",
        "description": "Renders the current STL in headless Blender as a studio PNG. Without Blender the tool stays offline and returns the recorded still.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "bom_build",
        "description": "Builds the bill of materials from the chosen parts, including the STL path.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "jamie_create_tasks",
        "description": "Creates one order or print task per bill-of-materials line, with a person and a due date on the meeting. Unchanged parts keep their task. Replaced parts are closed.",
        "input_schema": {"type": "object", "properties": {"meeting_id": {"type": "string"}}},
    },
    {
        "name": "ui_point_at",
        "description": "The pointer flies to a scene part or a UI element. A catalog motor sits four times in the scene; for the motor type use motor_front_left.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "enum": list(TARGETS)},
                "label": {"type": "string"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "ui_draw",
        "description": "Draws a halo, arrow, circle or note on a target in the 3D scene.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(DRAW_KINDS)},
                "target": {"type": "string", "enum": list(TARGETS)},
                "text": {"type": "string"},
            },
            "required": ["kind", "target", "text"],
        },
    },
    {
        "name": "mascot_say",
        "description": "Mechanic changes expression and says one short sentence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "enum": list(MASCOT_STATES)},
                "say": {"type": "string"},
            },
            "required": ["state", "say"],
        },
    },
]


def _running_detail(name: str, args: dict) -> str:
    if name == "parts_search":
        return (str(args.get("category", "")) + " " + str(args.get("query", ""))).strip()
    if name == "ui_point_at":
        return str(args.get("target", ""))
    if name == "ui_draw":
        return (str(args.get("kind", "")) + " " + str(args.get("target", ""))).strip()
    if name == "mascot_say":
        return str(args.get("state", ""))
    if name == "jamie_search":
        return str(args.get("query", ""))
    if name == "cad_part":
        return str(args.get("name", ""))
    if name in {"catalog_search", "product_brief"}:
        return (str(args.get("category") or args.get("product") or "") + " " + str(args.get("query", ""))).strip()
    if name == "cad_frame":
        try:
            return "Arm " + f"{float(args.get('arm_length_mm')):g}" + " mm"
        except (TypeError, ValueError):
            return ""
    return ""


async def _advance(ctx: Ctx, name: str, result: dict, started: bool) -> None:
    step = _STEP.get(name)
    if step is None or not ctx.auto_steps:
        return
    if started:
        await ctx.step(step, "running")
        return
    if result.get("ok") is False:
        await ctx.step(step, "failed")
        return
    if name in {"simulate_drone", "simulate_grip"}:
        await ctx.step("simulation", "done" if result.get("result") == "pass" else "failed")
    elif name == "grip_calc" and float(result.get("safety_factor") or 0) >= 2:
        await ctx.step("teile", "done")
    elif name == "physics_calc" and float(result.get("thrust_to_weight") or 0) >= 1.8:
        await ctx.step("teile", "done")
    elif name in {"isaac_lab_train", "isaac_train"}:
        if result.get("status") in {"done", "recorded"}:
            await ctx.step("training", "done")
        elif result.get("status") == "offline":
            await ctx.step("training", "failed")
    elif name == "isaac_lab_status" and result.get("training_status") == "done":
        await ctx.step("training", "done")
    elif name == "jamie_create_tasks":
        await ctx.step("stueckliste", "done")
    elif name in {"blender_render", "isaac_sim_render", "cad_frame", "cad_part", "product_brief", "jamie_requirements", "jamie_meeting"}:
        await ctx.step(step, "done")


async def call_tool(ctx: Ctx, name: str, args: dict | None) -> dict:
    payload = dict(args or {})
    function = TOOLS.get(name)
    if function is None:
        message = "Unknown tool: " + name
        await ctx.emit({"type": "tool", "name": name, "status": "error", "detail": message})
        return {"ok": False, "error": message}
    await ctx.emit(
        {"type": "tool", "name": name, "status": "running", "detail": _running_detail(name, payload)}
    )
    await _advance(ctx, name, {}, started=True)
    try:
        result = await function(ctx, payload)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    status = "error"
    if result.get("ok") is not False:
        status = str(result.get("status", "ok"))
        if status not in {"connected", "running", "ok", "error", "offline"}:
            status = "ok"
    detail = str(result.get("detail") or result.get("error") or "")
    await ctx.emit({"type": "tool", "name": name, "status": status, "detail": detail})
    await _advance(ctx, name, result, started=False)
    if result.get("ok") is not False:
        await refresh_requirements(ctx)
    return result


async def emit_connections(publish) -> None:
    host = ssh_setting("HOST")
    isaac_status = "connected" if host else "offline"
    isaac_detail = "GPU SSH is configured" if host else "Waiting for pod: GPU SSH is not configured"
    if find_blender():
        blender_status = "connected"
        blender_detail = "Blender can render headless."
    else:
        blender_status = "offline"
        blender_detail = "Blender is not installed."
    if find_freecadcmd():
        cad_detail = "FreeCAD on this machine. CadQuery stays the fallback."
    else:
        cad_detail = "CadQuery on this machine. freecadcmd is missing."
    jamie_detail = "Jamie MCP live" if live_enabled() else "Local meetings and outbox. JAMIE_MCP_TOKEN is missing."
    rows = (
        ("jamie_requirements", "connected", jamie_detail),
        ("parts_search", "connected", "Catalog agent/data/parts.json"),
        ("simulate_drone", "connected", "MuJoCo on this machine"),
        ("cad_frame", "connected", cad_detail),
        ("cad_part", "connected" if find_freecadcmd() else "offline", "Generated parts, headless and sandboxed" if find_freecadcmd() else "freecadcmd is missing"),
        ("blender_render", blender_status, blender_detail),
        ("isaac_lab_train", isaac_status, isaac_detail),
        ("isaac_sim_render", isaac_status, isaac_detail),
    )
    for name, status, detail in rows:
        await publish({"type": "tool", "name": name, "status": status, "detail": detail})


if {schema["name"] for schema in SCHEMAS} != set(TOOLS):
    raise RuntimeError("Tool schemas and functions have drifted apart.")
