"""Tool schemas and the single dispatch both Claude and the mock use."""

from __future__ import annotations

from pai_agent.context import Ctx
from pai_agent.requirements import refresh_requirements
from pai_agent.scene import DRAW_KINDS, MASCOT_STATES, PART_CATEGORIES, TARGETS
from pai_agent.freecad_run import find_freecadcmd
from pai_agent.tools.blender import blender_render, find_blender
from pai_agent.tools.bom import bom_build
from pai_agent.tools.browser_train import train_in_browser
from pai_agent.tools.build_guide import SCHEMA as BUILD_GUIDE_SCHEMA, build_guide
from pai_agent.tools.cad import cad_frame
from pai_agent.tools.cad_part import cad_part
from pai_agent.tools.checks import check_deflection, check_runtime, check_tip_over, check_torque, check_totals, simulate_assembly
from pai_agent.tools.product import assemble, cad_update, part_pick, product_spec
from pai_agent.tools.reference import reference_load
from pai_agent.agents import delegate
from pai_agent.tools.gripper import catalog_search, grip_calc, product_brief, simulate_grip
from pai_agent.tools.firmware import firmware, refresh_after_training
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
from pai_agent.tools.stress import stress_test
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
    "stress_test": stress_test,
    "cad_frame": cad_frame,
    "cad_part": cad_part,
    "product_brief": product_brief,
    "product_spec": product_spec,
    "reference_load": reference_load,
    "delegate": delegate,
    "part_pick": part_pick,
    "assemble": assemble,
    "cad_update": cad_update,
    "check_totals": check_totals,
    "check_tip_over": check_tip_over,
    "check_deflection": check_deflection,
    "check_torque": check_torque,
    "check_runtime": check_runtime,
    "simulate_assembly": simulate_assembly,
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
    "build_guide": build_guide,
    "firmware": firmware,
    "jamie_create_tasks": jamie_create_tasks,
    "ui_point_at": ui_point_at,
    "ui_draw": ui_draw,
    "mascot_say": mascot_say,
    "train_in_browser": train_in_browser,
}

# With delegation on, these belong to the sub-agents; the orchestrator reaches them through delegate.
DELEGATED = {"part_pick", "check_totals", "check_tip_over", "check_deflection", "check_torque", "check_runtime", "simulate_assembly"}

_STEP = {
    "jamie_requirements": "meeting",
    "jamie_meeting": "meeting",
    "parts_search": "teile",
    "physics_calc": "teile",
    "cad_frame": "cad",
    "cad_part": "cad",
    "product_brief": "meeting",
    "product_spec": "meeting",
    "reference_load": "meeting",
    "part_pick": "teile",
    "assemble": "cad",
    "cad_update": "cad",
    "check_totals": "teile",
    "check_tip_over": "simulation",
    "check_deflection": "simulation",
    "check_torque": "simulation",
    "check_runtime": "simulation",
    "simulate_assembly": "simulation",
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
    "train_in_browser": "training",
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
        "name": "stress_test",
        "description": "Stress test: flies the best trained controller (default gains without a training result) in 50 randomized MuJoCo worlds in the open dashboard's browser, each with mass +-15 %, motor strength -25..0 %, a gust up to 6 m/s and sensor noise. Returns the robustness score (survived/total), the worst world and one sentence on the weakest point. Use it when someone asks to stress test the drone or how robust it is.",
        "input_schema": {
            "type": "object",
            "properties": {
                "gains": {"type": "object", "description": "Controller gains to test instead of the training result, in the training event's units (kp_z, ki_z, kd_z, kp_xy, kd_xy, kp_att, kd_att)."},
            },
        },
    },
    {
        "name": "cad_frame",
        "description": "Builds the parametric frame in FreeCAD, otherwise in CadQuery. Writes STL, STEP and GLB. arm_length_mm is the distance from the center to the motor shaft. motor_spacing_mm is the bolt-circle diameter of the motor screws. On the 1103 that is 6.6.",
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
        "name": "product_spec",
        "description": (
            "Starts a build for ANY physical product that is not the drone or the gripper (a phone stand, a desk fan, a plant-watering robot, a bike light mount). "
            "Pass the full spec: name, function, quote (the user's own sentence), requirements and parts. The code validates it and lists every problem; fix them and call again. "
            "Coordinates: millimetres, Z up, the product stands on Z = 0 centred on X = Y = 0, -Y is the front. "
            "printed parts are designed in FreeCAD by cad_part: give material, a precise description (shape, features, wall thickness, holes, where it sits in the assembly), "
            "size_mm (the envelope [x, y, z] the build is checked against) and params (the key dimensions in mm, they become sliders). "
            "position_mm is always the centre of a part's bounding box in the assembly; a printed part with it is moved there, one without it stays where its script builds it. "
            "bought parts are ordered: give category and query for the catalog; give size_mm and position_mm so they show in the model and count for the centre of mass. "
            "external parts are loads that are not part of the product (the phone it holds, the water in the tank): mass_g, position_mm (centre of mass) and size_mm. "
            "Each requirement names the check that judges it: mass (max g, product without loads), cost (max eur), size (max mm, largest side), "
            "tip_over (min deg tip angle, or min N push at the top), deflection (max mm, with part_id), torque (min x safety), runtime (min with unit min, h or days), "
            "stability (max deg tilt after the MuJoCo push), drop (max g peak load), printable (no limit). Keep it to six printed parts or fewer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "function": {"type": "string", "description": "What the product does, in one or two sentences."},
                "quote": {"type": "string", "description": "The user's request, word for word."},
                "requirements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string", "description": "Short and checkable, e.g. 'Weighs under 150 g'."},
                            "check": {"type": "string", "enum": ["mass", "cost", "size", "tip_over", "deflection", "torque", "runtime", "stability", "drop", "printable"]},
                            "max": {"type": "number"},
                            "min": {"type": "number"},
                            "unit": {"type": "string", "description": "g, eur, mm, deg, N, x, min, h or days."},
                            "part_id": {"type": "string"},
                            "quote": {"type": "string"},
                        },
                        "required": ["text", "check"],
                    },
                },
                "assemblies": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"}}, "required": ["name"]}},
                "parts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "kind": {"type": "string", "enum": ["printed", "bought", "external"]},
                            "qty": {"type": "integer"},
                            "assembly": {"type": "string"},
                            "description": {"type": "string"},
                            "material": {"type": "string", "enum": ["PLA", "PETG", "ABS", "ASA", "NYLON", "TPU", "ALUMINIUM", "STEEL"]},
                            "params": {"type": "object"},
                            "size_mm": {"type": "array", "items": {"type": "number"}},
                            "position_mm": {"type": "array", "items": {"type": "number"}},
                            "rotation_deg": {"type": "array", "items": {"type": "number"}},
                            "category": {"type": "string"},
                            "query": {"type": "string"},
                            "mass_g": {"type": "number"},
                        },
                        "required": ["name", "kind"],
                    },
                },
            },
            "required": ["name", "function", "requirements", "parts"],
        },
    },
    {
        "name": "delegate",
        "description": (
            "Hands a bounded job to a smaller sub-agent that has only the tools it needs and reports back. "
            "agent parts picks bought parts (part_pick), agent checks runs the checks and the MuJoCo test (check_*, simulate_assembly), "
            "agent pricing builds and prices the bill of materials (bom_build, part_pick). task says exactly what to do and what matters. "
            "The report, the tool calls, tokens and cost come back."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"agent": {"type": "string", "enum": ["parts", "checks", "pricing"]}, "task": {"type": "string"}},
            "required": ["agent", "task"],
        },
    },
    {
        "name": "reference_load",
        "description": (
            "Reference builds are known products with all their real parts. Without id it lists them; with id it loads one onto the bench: "
            "spec, printed parts from their tested scripts, the bought parts, the assembly, every check, the render and the bill of materials. "
            "Use it when the user wants to start from a known product, then change it as they ask."
        ),
        "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}},
    },
    {
        "name": "part_pick",
        "description": (
            "Chooses the bought part for a spec part. With query (and no select_id) it searches every catalog (hobby electronics, motors, fans, pumps, batteries, servos, hardware). "
            "select_id binds a catalog part (prices are samples to verify). When nothing fits, pass estimate {name, mass_g, unit_price_eur, and specs such as power_w, capacity_mah, voltage_v, stall_torque_nm} "
            "and it is marked as an estimated price. reason is your one-line reason. A swap after checks reruns them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "part_id": {"type": "string"},
                "query": {"type": "string"},
                "category": {"type": "string"},
                "select_id": {"type": "string"},
                "estimate": {"type": "object"},
                "reason": {"type": "string"},
            },
            "required": ["part_id"],
        },
    },
    {
        "name": "assemble",
        "description": (
            "Puts the built printed parts, the picked bought parts and the external loads together: one model with mass, cost, centre of mass, size and the footprint it stands on. "
            "cad_part already assembles after each part; call this to move parts with placements {part_id: {position_mm, rotation_deg}} (position_mm is the centre of the part's bounding box, rotation about that centre) "
            "and read warnings such as a part that floats."
        ),
        "input_schema": {"type": "object", "properties": {"placements": {"type": "object"}}},
    },
    {
        "name": "cad_update",
        "description": (
            "Changes the numbers of a built printed part (params, e.g. {\"depth_mm\": 110}): FreeCAD rebuilds it from the same script, the product is reassembled "
            "and every check that ran before runs again; the new results come back. Use it to fix a failed check, and say why."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"part_id": {"type": "string"}, "params": {"type": "object"}},
            "required": ["part_id", "params"],
        },
    },
    {
        "name": "check_totals",
        "description": "Mass (product without external loads), cost (printed parts at filament cost plus bought parts) and size against the mass, cost and size requirements.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_tip_over",
        "description": (
            "Centre of mass and tip-over stability: the tip angle about the weakest edge of the footprint and the horizontal push at push_height_mm (default the top) that tips it. "
            "Judges tip_over requirements."
        ),
        "input_schema": {"type": "object", "properties": {"push_height_mm": {"type": "number"}}},
    },
    {
        "name": "check_deflection",
        "description": (
            "Load estimate for a beam-like printed part (an arm, a shelf, a clip, a lip): span_mm, width_mm, thickness_mm of the section, load_n, "
            "support cantilever (fixed at one end, load at the tip) or simple (both ends, load in the middle). "
            "Gives deflection and the stress safety (needs 2x, printed plastic at 60 % strength). Judges deflection requirements."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "part_id": {"type": "string"},
                "span_mm": {"type": "number"},
                "width_mm": {"type": "number"},
                "thickness_mm": {"type": "number"},
                "load_n": {"type": "number"},
                "support": {"type": "string", "enum": ["cantilever", "simple"]},
            },
            "required": ["part_id", "span_mm", "width_mm", "thickness_mm", "load_n"],
        },
    },
    {
        "name": "check_torque",
        "description": (
            "Motor or servo torque sufficiency: actuator_part_id (a picked motor or servo), and required_torque_nm, or lever_mm with force_n or load_mass_g. "
            "Usable torque is 70 % of stall for a servo, 80 % for a stepper, 50 % for a DC motor. Judges torque requirements (safety factor)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "actuator_part_id": {"type": "string"},
                "required_torque_nm": {"type": "number"},
                "lever_mm": {"type": "number"},
                "force_n": {"type": "number"},
                "load_mass_g": {"type": "number"},
            },
            "required": ["actuator_part_id"],
        },
    },
    {
        "name": "check_runtime",
        "description": (
            "Battery runtime: battery_part_id (a picked battery) and loads [{part_id or name, power_w, duty}], duty the share of time the load is on; "
            "a picked controller with sleep_power_w sleeps the rest of the time. 80 % of the battery energy counts. Judges runtime requirements."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "battery_part_id": {"type": "string"},
                "loads": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"part_id": {"type": "string"}, "name": {"type": "string"}, "power_w": {"type": "number"}, "duty": {"type": "number"}},
                    },
                },
            },
            "required": ["battery_part_id", "loads"],
        },
    },
    {
        "name": "simulate_assembly",
        "description": (
            "MuJoCo test of the whole assembly as one rigid body (convex hull, real masses and centre of mass). "
            "mode push: it stands on the table and force_n (default 1 N) pushes for 0.3 s at push_point_mm (default the top) towards its weakest side; "
            "it passes when it settles within the stability limit (default 5 deg). mode drop: it falls from drop_height_mm (default 300) and reports the peak load in g. "
            "The run plays in the Simulation tab."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["push", "drop"]},
                "force_n": {"type": "number"},
                "push_point_mm": {"type": "array", "items": {"type": "number"}},
                "drop_height_mm": {"type": "number"},
            },
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
        "description": "Builds the bill of materials from the chosen parts, including the STL path. With ANTHROPIC_API_KEY set it searches live shop prices on the web; each line says price_source live or catalog.",
        "input_schema": {"type": "object", "properties": {}},
    },
    BUILD_GUIDE_SCHEMA,
    {
        "name": "firmware",
        "description": "Generates the firmware and wiring table from the chosen parts: a Betaflight CLI configuration for a drone (motor order, rates, trained PID gains, else defaults), an Arduino sketch for a servo product. Call it after bom_build. explanation is your one or two sentences for the team; the file itself comes from a fixed template.",
        "input_schema": {
            "type": "object",
            "properties": {
                "explanation": {"type": "string"},
            },
        },
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
    {
        "name": "train_in_browser",
        "description": "Trains the current product's controller in 1,024 MuJoCo simulations in the open dashboard (64 candidates x 16 generations, evolution strategy). For the drone: altitude PID and position and attitude PD gains that stay level and hold position for 10 s with a payload and a side gust. For the gripper: squeeze force, ramp, settle and lift time that hold the part through the lift and shake with the least force. Waits for the run and returns the best gains and score.",
        "input_schema": {"type": "object", "properties": {}},
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
    if name in {"cad_part", "cad_update", "part_pick"}:
        return str(args.get("part_id") or args.get("name") or "")
    if name == "product_spec":
        return str(args.get("name", ""))
    if name == "delegate":
        return str(args.get("agent", "")) + " agent"
    if name == "simulate_assembly":
        return str(args.get("mode") or "push") + " test"
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
    if name in {"simulate_drone", "simulate_grip", "simulate_assembly"}:
        await ctx.step("simulation", "done" if result.get("result") == "pass" else "failed")
    elif name in {"check_tip_over", "check_deflection", "check_torque", "check_runtime"}:
        await ctx.step("simulation", "done" if result.get("result") == "pass" else "failed")
    elif name == "check_totals":
        await ctx.step("teile", "done" if result.get("result") == "pass" else "failed")
    elif name == "grip_calc" and float(result.get("safety_factor") or 0) >= 2:
        await ctx.step("teile", "done")
    elif name == "physics_calc" and float(result.get("thrust_to_weight") or 0) >= 1.8:
        await ctx.step("teile", "done")
    elif name in {"isaac_lab_train", "isaac_train"}:
        if result.get("status") in {"done", "recorded"}:
            await ctx.step("training", "done")
        elif result.get("status") == "offline":
            await ctx.step("training", "failed")
    elif name == "train_in_browser" and result.get("training_status") == "done":
        await ctx.step("training", "done")
    elif name == "isaac_lab_status" and result.get("training_status") == "done":
        await ctx.step("training", "done")
    elif name == "jamie_create_tasks":
        await ctx.step("stueckliste", "done")
    elif name in {"blender_render", "isaac_sim_render", "cad_frame", "cad_part", "cad_update", "assemble", "product_brief", "product_spec", "reference_load", "part_pick", "jamie_requirements", "jamie_meeting"}:
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
        if name in {"train_in_browser", "isaac_train", "isaac_lab_train"}:
            await refresh_after_training(ctx)
        if name in {"version_commit", "bom_build"}:
            from pai_agent.versions import after_tool

            await after_tool(ctx, name, payload, result)
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
