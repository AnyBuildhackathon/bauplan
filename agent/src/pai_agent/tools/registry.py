"""Tool schemas and the single dispatch both Claude and the mock use."""

from __future__ import annotations

import asyncio
import time

from pai_agent import distributors
from pai_agent.context import Ctx
from pai_agent.timeouts import limit, timed_out
from pai_agent.requirements import refresh_requirements
from pai_agent.run_control import RunStopped
from pai_agent.scene import CONTROLS, DRAW_KINDS, MASCOT_STATES, PART_CATEGORIES, TARGETS
from pai_agent.freecad_run import find_freecadcmd
from pai_agent.tools.blender import blender_render, find_blender, recorded_still
from pai_agent.tools.bom import bom_build
from pai_agent.tools.browser_train import train_in_browser
from pai_agent.tools.build_guide import SCHEMA as BUILD_GUIDE_SCHEMA, build_guide
from pai_agent.tools.cad import cad_frame
from pai_agent.tools.cad_part import cad_part
from pai_agent.tools.checks import check_deflection, check_runtime, check_tip_over, check_torque, check_totals, simulate_assembly
from pai_agent.tools.checks_more import check_power, check_rollover, check_thermal
from pai_agent.tools.product import assemble, cad_update, part_pick, product_spec
from pai_agent.tools.reference import reference_load
from pai_agent.tools.sketch import sketch_to_spec
from pai_agent.agents import delegate
from pai_agent.tools.gripper import catalog_search, grip_calc, product_brief, simulate_grip
from pai_agent.tools.firmware import firmware, refresh_after_training
from pai_agent.tools.electronics import electronics_plan
from pai_agent.tools.safety import SCHEMA as SAFETY_SCHEMA, safety_check
from pai_agent.tools.isaac import isaac_lab_status, isaac_lab_train, isaac_sim_render, isaac_test, isaac_train, ssh_setting
from pai_agent.tools.usd import product_usd
from pai_agent.tools.ask import ask_user
from pai_agent.tools.parts import parts_search
from pai_agent.tools.parts_search import live_prices_enabled
from pai_agent.tools.optimize import optimize_apply, optimize_design
from pai_agent.tools.print_prep import print_prep
from pai_agent.tools.fem import fem_check, material_pick
from pai_agent.tools.physics import physics_calc
from pai_agent.drone_geometry import publish_geometry
from pai_agent.tools.mission import simulate_mission
from pai_agent.tools.simulate import simulate_drone
from pai_agent.tools.stress import stress_test
from pai_agent.tools.train_loop import train_controller
from pai_agent.tools.ui import mascot_say, ui_control, ui_draw, ui_point_at

TOOLS = {
    "ask_user": ask_user,
    "parts_search": parts_search,
    "physics_calc": physics_calc,
    "simulate_drone": simulate_drone,
    "simulate_mission": simulate_mission,
    "stress_test": stress_test,
    "train_controller": train_controller,
    "cad_frame": cad_frame,
    "cad_part": cad_part,
    "product_brief": product_brief,
    "product_spec": product_spec,
    "sketch_to_spec": sketch_to_spec,
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
    "check_power": check_power,
    "check_thermal": check_thermal,
    "check_rollover": check_rollover,
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
    "print_prep": print_prep,
    "material_pick": material_pick,
    "fem_check": fem_check,
    "build_guide": build_guide,
    "firmware": firmware,
    "electronics_plan": electronics_plan,
    "safety_check": safety_check,
    "ui_point_at": ui_point_at,
    "ui_draw": ui_draw,
    "mascot_say": mascot_say,
    "ui_control": ui_control,
    "train_in_browser": train_in_browser,
    "optimize_design": optimize_design,
    "optimize_apply": optimize_apply,
}

# With delegation on, these belong to the sub-agents; the orchestrator reaches them through delegate.
DELEGATED = {"part_pick", "check_totals", "check_tip_over", "check_deflection", "check_torque", "check_runtime", "check_power", "check_thermal", "check_rollover", "simulate_assembly"}

_STEP = {
    "parts_search": "teile",
    "physics_calc": "teile",
    "cad_frame": "cad",
    "cad_part": "cad",
    "product_brief": "meeting",
    "product_spec": "meeting",
    "sketch_to_spec": "meeting",
    "reference_load": "meeting",
    "part_pick": "teile",
    "assemble": "cad",
    "cad_update": "cad",
    "check_totals": "teile",
    "check_tip_over": "simulation",
    "check_deflection": "simulation",
    "check_torque": "simulation",
    "check_runtime": "simulation",
    "check_power": "simulation",
    "check_thermal": "simulation",
    "check_rollover": "simulation",
    "simulate_assembly": "simulation",
    "catalog_search": "teile",
    "grip_calc": "teile",
    "simulate_grip": "simulation",
    "blender_render": "render",
    "isaac_sim_render": "render",
    "simulate_drone": "simulation",
    "simulate_mission": "simulation",
    "train_controller": "training",
    "isaac_lab_train": "training",
    "isaac_train": "training",
    "isaac_lab_status": "training",
    "bom_build": "stueckliste",
    "print_prep": "stueckliste",
    "material_pick": "cad",
    "fem_check": "simulation",
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
        "name": "parts_search",
        "description": (
            "Searches the drone parts library: real parts from shop pages, each with its specs (motors with the maker's load table: thrust, current and power at 100 %, KV, size; "
            "propellers with diameter and pitch; packs 1S to 6S with voltage, capacity, C rating and size; flight controllers with mount and ESC rating; frames with wheelbase; cameras; video transmitters), "
            "the page the specs come from (source_url), the date checked and which fields are estimates. It spans 65 mm whoops to 5-inch racers. "
            "select_id chooses the part; because names the requirement it serves; reason is your one-sentence reason. "
            "web true with need (what the part must do, e.g. '2S 1103 motor, 140 g thrust') finds a real part when the library has nothing that fits: first the learned library "
            "(parts earlier builds found), then the distributor APIs for electronics (Digi-Key, Nexar/Octopart, Mouser, when set up; query is their search words), then the web, "
            "combining the shop page, the maker page and the datasheet of the same part number. Its numbers are validated (identity, units, plausible ranges); require lists the extra fields "
            "this build needs beyond the category's critical ones (a chase camera: fov_deg, resolution_px, fps). Each part and field says sourced, derived or estimated "
            "(estimates only in exploration mode, labelled). The find joins the library; select it with select_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": list(PART_CATEGORIES)},
                "query": {"type": "string"},
                "select_id": {"type": "string"},
                "because": {"type": "string", "enum": ["budget", "flight_time", "weight", "hover", "printable"]},
                "reason": {"type": "string"},
                "web": {"type": "boolean", "description": "Search shops on the web for a real part with real specs. Use it only when no library part fits."},
                "need": {"type": "string", "description": "With web: what the part must do and fit, with numbers."},
                "require": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "With web: fields this build needs stated on the part's pages, beyond the category's critical ones, e.g. [\"fov_deg\", \"resolution_px\", \"fps\"] for a camera that must see a fly.",
                },
            },
            "required": ["category"],
        },
    },
    {
        "name": "physics_calc",
        "description": (
            "Computes from the chosen parts' specs: mass, thrust-to-weight, flight time in hover, price, and the flight performance: top speed (thrust fading with airspeed along a measured prop curve, mass, a drag model, on the fresh pack and at the end of it), "
            "acceleration, time to 90 % of top speed, climb rate, turn rate and radius at half top speed, flip time, flight time at full speed and at full throttle on the sagging, draining pack, the inertia of the parts as placed. "
            "Every performance number is an estimate; assumptions lists what was assumed and warnings what does not fit (a pack whose C rating cannot feed the motors, an ESC under the motor current)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "simulate_drone",
        "description": "MuJoCo hover test. Mass and peak thrust come from the chosen parts. fail means too heavy, pass means it holds the hover.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "simulate_mission",
        "description": (
            "Mission tests in MuJoCo for the drone, built from the chosen parts: mass and inertia from every part at its place, thrust from the motors' load tables "
            "along a measured propeller curve on a pack that sags and drains, ground effect, motor lag from the prop size, body and rotor drag. "
            "speed_run: full throttle from a hover, top speed (km/h) and the time to reach it; judged on top_speed. "
            "turn: a 90° course change at 29 km/h, turn rate (°/s) and overshoot; judged on turn_rate. "
            "hold: hold a point at 1.5 m in 3 m/s gusting wind with a downdraft, worst drift (cm); judged on hold_error. "
            "chase: chase five flies that dart off every 0.5 to 0.9 s, capture within 12 cm, median capture time (s); the drone sees each fly only through its camera (field of view, pixels, frame rate, delay); judged on chase_time. "
            "Pick from the request: fast or racing means speed_run and turn, agile means turn, precise or steady means hold, hunting, catching or intercepting means chase (and speed_run and turn). "
            "Each mission is a requirement check: pass limit with the user's number and quote when they typed one; without a limit the row already set by product_brief is used, else Mechanic proposes one. "
            "Every result says why the build is limited, for the fix loop."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "missions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "mission": {"type": "string", "enum": ["speed_run", "turn", "hold", "chase"]},
                            "limit": {"type": "number", "description": "km/h for speed_run, °/s for turn, cm for hold, s for chase."},
                            "quote": {"type": "string", "description": "The user's own words the limit comes from, copied exactly."},
                            "proposed": {"type": "boolean"},
                        },
                        "required": ["mission"],
                    },
                },
            },
            "required": ["missions"],
        },
    },
    {
        "name": "train_controller",
        "description": (
            "Drone only, after simulate_mission passed every mission (the hardware check on the reference controller): trains the flight controller's seven gains "
            "(kp_z, ki_z, kd_z, kp_xy, kd_xy, kp_att, kd_att) on those same missions plus a hover, an evolution strategy in MuJoCo on the backend (no dashboard needed, about two minutes), "
            "then flies every mission again with the trained gains and runs the stress test with them on the same model. The trained result decides: pass needs every mission and 90 % of the stress worlds. "
            "Returns the reference and the trained number per mission, the stress score and next: on a pass the gains are the validated set firmware writes; "
            "on a fail go back to parts (swap a part or change a dimension), simulate_mission, then train_controller again; after two failed loops it says to ask_user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "population": {"type": "integer", "minimum": 4, "maximum": 32, "description": "Candidates per generation, default 8."},
                "generations": {"type": "integer", "minimum": 1, "maximum": 12, "description": "Default 5."},
            },
        },
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
            "Starts a drone or gripper build and turns the user's request into requirement checks. "
            "Drone: requirements lists budget (max €), flight_time (min minutes) and weight (max g), each with limit and quote, "
            "and for a mission test the user asked a number for: top_speed (min km/h), turn_rate (min °/s), hold_error (max cm), chase_time (max s). "
            "the user's own words copied exactly from their request (e.g. 'under 150 euros'). Take every number the user typed. "
            "When the user named no number for one you need, you may propose it with proposed true and your reason as quote; it shows as proposed by Mechanic. "
            "Hover and the printable frame are added automatically. Calling it again on a built drone revises the requirements and keeps the parts. "
            "Gripper: pass object_mass_g, object_width_mm, optionally max_weight_g and budget_eur, and quote, the user's sentence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product": {"type": "string", "enum": ["drone", "gripper"]},
                "requirements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "enum": ["budget", "flight_time", "weight", "top_speed", "turn_rate", "hold_error", "chase_time"]},
                            "limit": {"type": "number"},
                            "quote": {"type": "string"},
                            "proposed": {"type": "boolean"},
                        },
                        "required": ["id", "limit"],
                    },
                },
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
                            "check": {"type": "string", "enum": ["mass", "cost", "size", "tip_over", "deflection", "torque", "runtime", "stability", "drop", "printable", "power", "thermal", "rollover"]},
                            "max": {"type": "number"},
                            "min": {"type": "number"},
                            "unit": {"type": "string", "description": "g, eur, mm, deg, N, x, min, h or days."},
                            "part_id": {"type": "string"},
                            "quote": {"type": "string", "description": "The user's own words this requirement comes from, copied exactly from their request (e.g. 'under 150 euros')."},
                            "proposed": {"type": "boolean", "description": "true when the user named no limit for this and you propose one; quote then gives your one-line reason. Shown as proposed by Mechanic."},
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
        "name": "sketch_to_spec",
        "description": (
            "Use it when a sketch image is on the bench (the user uploaded one): Claude vision reads the photo of the hand sketch "
            "and returns spec (a validated product_spec), read (each dimension and label with value, unit and confidence), unreadable and summary. "
            "It does not start the build: say what you read and guessed, then call product_spec with spec. "
            "sketch is the file name from the user's message (sketch-1.png); note is what the user wrote with it."
        ),
        "input_schema": {"type": "object", "properties": {"sketch": {"type": "string"}, "note": {"type": "string"}}},
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
            "Chooses the bought part for a spec part. With query (and no select_id) it searches every catalog (hobby electronics, motors, fans, pumps, batteries, servos, hardware, "
            "and the maker library of real product pages: gearmotors, steppers, servos, motor and stepper drivers, ESP32, RP2040 and Arduino boards, IMU, distance and lidar sensors, "
            "LiPo and 18650 cells, chargers, regulators, wheels, casters, bearings, screws). web true with query (the need) finds a real part: the learned library first, then the distributor APIs "
            "for electronics (keywords are their search words, e.g. a part number), then the web (shop page, maker page and datasheet of the same part number), and validates its specs; "
            "require lists the fields this part must have stated (e.g. fov_deg, resolution_px, fps for a vision sensor). Then select it with select_id. "
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
                "web": {"type": "boolean", "description": "Search shops on the web for a real part with real specs when no catalog part fits."},
                "keywords": {"type": "string", "description": "With web: short distributor search words, e.g. a part number or 'OV9281 camera module'."},
                "require": {"type": "array", "items": {"type": "string"}, "description": "With web: fields that must be stated on the part's pages beyond mass_g, e.g. [\"fov_deg\", \"fps\"]."},
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
        "name": "check_power",
        "description": (
            "Power budget: supply_part_id (a picked supply with voltage_v and max_current_a, or a battery with c_rating and capacity_mah) and loads "
            "[{part_id or name, power_w or current_a, voltage_v, duty, peak_factor}]. Loads at another voltage go through a regulator at 85 %. "
            "Headroom is the supply current limit over the peak current; a battery supply also gives the runtime. Judges power (min headroom x) and runtime requirements."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "supply_part_id": {"type": "string"},
                "loads": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "part_id": {"type": "string"},
                            "name": {"type": "string"},
                            "power_w": {"type": "number"},
                            "current_a": {"type": "number"},
                            "voltage_v": {"type": "number"},
                            "duty": {"type": "number"},
                            "peak_factor": {"type": "number"},
                        },
                    },
                },
            },
            "required": ["supply_part_id", "loads"],
        },
    },
    {
        "name": "check_thermal",
        "description": (
            "Heat in a closed case: enclosure_part_id (the printed shell), power_w or heat_part_ids (picked parts with tdp_w or power_w), optional wall_mm, "
            "vents_mm2 (else the vents_mm2 parameter of a built part), ambient_c, component_limit_c (default 70). Every picked part with airflow_m3h counts as a fan. "
            "Natural convection h = 5 W/m2K on the outer area through the wall, plus air exchange through vents and fans; the inside temperature must stay under "
            "the wall material limit (PLA 55, PETG 75, ABS 95 °C) and the component limit. Judges thermal requirements (max °C)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "enclosure_part_id": {"type": "string"},
                "power_w": {"type": "number"},
                "heat_part_ids": {"type": "array", "items": {"type": "string"}},
                "fan_part_ids": {"type": "array", "items": {"type": "string"}},
                "bbox_mm": {"type": "array", "items": {"type": "number"}},
                "wall_mm": {"type": "number"},
                "vents_mm2": {"type": "number"},
                "ambient_c": {"type": "number"},
                "component_limit_c": {"type": "number"},
            },
            "required": ["enclosure_part_id"],
        },
    },
    {
        "name": "check_rollover",
        "description": (
            "Vehicle roll-over: track_mm and wheelbase_mm (else the track_mm and wheelbase_mm parameters of a built printed part), the centre of mass height from the "
            "assembly (or com_height_mm), and a turn: speed_mps on turn_radius_m. Static stability factor T / 2h is the lateral g it rolls at; the turn needs v^2 / (r g). "
            "Judges rollover requirements (min g lateral, or min deg side slope)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "track_mm": {"type": "number"},
                "wheelbase_mm": {"type": "number"},
                "com_height_mm": {"type": "number"},
                "speed_mps": {"type": "number"},
                "turn_radius_m": {"type": "number"},
            },
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
        "description": "Gripper numbers from the chosen parts and the CAD fingers: finger force at the pad tips (the fingers swing on their gears), holding force with pad friction, safety factor against the object weight (needs 2x), weight and sample price.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "simulate_grip",
        "description": "MuJoCo grip test with the CAD fingers swinging on their gears, driven by the servo: the pads close on the object, the arm lifts it 15 cm and shakes it, then the object is pulled with its weight once more. pass means it stays within 10 mm and holds twice its weight, fail means it slips or drops.",
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
    {
        "name": "print_prep",
        "description": "Makes every printed part print-ready after bom_build: slices each STL headless with PrusaSlicer or OrcaSlicer when installed (G-code per part for download), else estimates time and filament from the mesh and says 'estimate'. Returns print time, filament grams, support grams and cost per part and in total, and printability warnings (overhangs past 45 degrees and supports, walls under 0.8 mm, bed fit). With the user's 3D printer set it uses that printer's bed, nozzle and speed, picks each part's pose (auto: fits the bed, least support), warns about warping for the material on that printer (enclosure, part length) and materials it cannot print, and prices each printed part as filament on their printer. Adds a filament line to the bill of materials. orientation flat puts the smallest extent on the bed, upright the largest, as_modeled keeps the CAD pose, auto chooses; orientations sets it per part id. The pose sets the print direction fem_check judges the layers against.",
        "input_schema": {
            "type": "object",
            "properties": {
                "orientation": {"type": "string", "enum": ["auto", "flat", "upright", "as_modeled"]},
                "orientations": {"type": "object", "additionalProperties": {"type": "string", "enum": ["auto", "flat", "upright", "as_modeled"]}},
            },
        },
    },
    {
        "name": "material_pick",
        "description": (
            "Chooses the material of one printed part (part_id; the drone's printed frame needs none) from what it must survive: max_temp_c (the heat it sits in: "
            "next to motors, in a car, in the sun), outdoor (sun and rain), impact (crashes, drops), flex (bends on purpose: a clip, a bumper). "
            "With the user's 3D printer set it chooses only among the filaments that printer prints; material forces one of those. "
            "Returns the material, a one-sentence reason with the data sheet numbers (heat deflection, UV, impact), what was ruled out and why. "
            "The part's mass follows the new density and every check runs again. Say the reason to the user in one sentence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "part_id": {"type": "string"},
                "max_temp_c": {"type": "number"},
                "outdoor": {"type": "boolean"},
                "impact": {"type": "boolean"},
                "flex": {"type": "boolean"},
                "material": {"type": "string", "enum": ["PLA", "PETG", "ABS", "ASA", "NYLON", "TPU"]},
                "reason": {"type": "string"},
            },
        },
    },
    {
        "name": "fem_check",
        "description": (
            "FEM stress simulation of one printed part on its real CAD shape: gmsh meshes the STEP into quadratic tetrahedra, CalculiX solves it under its loads. "
            "The material is weakened for the print: modulus and strength scale with the plastic share of the section (walls solid, core at infill_pct, default 25 %), "
            "and the tension across the layers is judged against the interlayer strength along the print direction from print_prep. "
            "Without cases, the loads come from the spec: held on its lowest face, each external load near it pressing at its position with 2x its weight "
            "(else a 10 N press on top); for the drone frame (part_id frame) held at the stack, full motor thrust on all four mounts, and a crash on one motor at 10 g. "
            "cases overrides them: [{name, region, force_n: [fx, fy, fz]}] in N in the assembly frame (Z up, a weight is negative Z); region is {face: z_min...}, "
            "{near: [x, y, z] mm, radius_mm} or {box: [x0, y0, z0, x1, y1, z1]}; fixed is the held region the same way. "
            "Returns max von Mises stress, deflection, the safety factor (needs 2x unless the user set a strength requirement), which case governs and where. "
            "Judges the strength requirement, reruns after cad_update, and shows the stress-coloured part on the Simulation tab. On a fail, follow the hint and run it again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "part_id": {"type": "string"},
                "cases": {"type": "array", "items": {"type": "object"}},
                "fixed": {"type": "object"},
                "infill_pct": {"type": "number", "minimum": 5, "maximum": 100},
                "walls": {"type": "integer", "minimum": 1, "maximum": 10},
            },
        },
    },
    BUILD_GUIDE_SCHEMA,
    SAFETY_SCHEMA,
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
        "name": "electronics_plan",
        "description": (
            "Wiring diagram and power budget from the chosen parts: the supply (battery or USB), switch, regulator, controller, drivers and loads (motors, ESCs, pumps, servos, fans, LEDs, sensors) "
            "with pins, voltages and currents. Checks every part against its voltage and current rating (for example a 4S battery on a 1S controller, a bare LED on 5 V, a motor on a controller pin) "
            "and gives average and peak draw, headroom and the runtime on a battery. Call it after bom_build for any product with electronics. explanation is your one sentence for the team."
        ),
        "input_schema": {"type": "object", "properties": {"explanation": {"type": "string"}}},
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
        "name": "ui_control",
        "description": (
            "Operates the dashboard in front of the audience: the pointer flies to the real control, a short bubble says what happens, then it acts. "
            "Use it whenever someone asks to see or open something (show me the CAD, open the library, pull it apart, compare v1 and v2, open the bill of materials) "
            "and to show what you are talking about. control is one of: "
            + "; ".join(control + " (" + text + ")" for control, text in CONTROLS.items())
            + "; library:{id} opens one library item. say is the bubble, at most eight words. run:test and run:rebuild wait for the run and return its result."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "control": {"type": "string"},
                "open": {"type": "boolean", "description": "Panels: true opens, false closes. Default true."},
                "value": {"description": "explode: 0 to 100. setting:*: true or false."},
                "part": {"type": "string", "description": "focus: the part name or id."},
                "versions": {"type": "array", "items": {"type": "integer"}, "description": "panel:compare: the two version numbers."},
                "say": {"type": "string"},
            },
            "required": ["control"],
        },
    },
    {
        "name": "train_in_browser",
        "description": "Trains the current product's controller in 1,024 MuJoCo simulations in the open dashboard (64 candidates x 16 generations, evolution strategy). For the drone: altitude PID and position and attitude PD gains that stay level and hold position for 10 s with a payload and a side gust. For the gripper: squeeze force, ramp, settle and lift time that hold the part through the lift and shake with the least force. Waits for the run and returns the best gains and score.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


_OPTIMIZE_SCHEMAS = [
    {
        "name": "optimize_design",
        "description": (
            "Explores variants of the built drone for the user's goals: lighter, cheaper, longer_runtime, stronger. "
            "4 to 8 variant agents (Sonnet sub-agents, in parallel) each propose a battery and the frame's arm length and plate thickness; "
            "every variant runs the CadQuery frame mass, physics_calc's numbers, the MuJoCo gust test, the prop clearance and the keep limits. "
            "Returns every variant with pass/fail and the Pareto set; the chat shows them as a chart. keep holds the limits to keep, "
            "e.g. {\"min_flight_time_min\": 8}. Then let the user pick a point; do not build one unasked."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "goals": {"type": "array", "items": {"type": "string", "enum": ["lighter", "cheaper", "longer_runtime", "stronger"]}},
                "keep": {
                    "type": "object",
                    "properties": {
                        "min_flight_time_min": {"type": "number"},
                        "max_weight_g": {"type": "number"},
                        "max_price_eur": {"type": "number"},
                        "min_thrust_to_weight": {"type": "number"},
                        "min_arm_stiffness": {"type": "number"},
                    },
                },
                "count": {"type": "integer", "minimum": 4, "maximum": 8},
            },
            "required": ["goals"],
        },
    },
    {
        "name": "optimize_apply",
        "description": (
            "Builds one optimizer variant (variant is its letter, id the optimizer run; both default to the latest run's recommendation) "
            "through parts_search, cad_frame, physics_calc, simulate_drone, blender_render and bom_build, and commits it as the next version with its difference."
        ),
        "input_schema": {"type": "object", "properties": {"id": {"type": "string"}, "variant": {"type": "string"}}},
    },
]
SCHEMAS.extend(_OPTIMIZE_SCHEMAS)


def _running_detail(name: str, args: dict) -> str:
    if name == "parts_search":
        return (str(args.get("category", "")) + " " + str(args.get("query", ""))).strip()
    if name == "ui_point_at":
        return str(args.get("target", ""))
    if name == "ui_draw":
        return (str(args.get("kind", "")) + " " + str(args.get("target", ""))).strip()
    if name == "mascot_say":
        return str(args.get("state", ""))
    if name == "ui_control":
        return str(args.get("control", ""))
    if name in {"cad_part", "cad_update", "part_pick", "material_pick", "fem_check"}:
        return str(args.get("part_id") or args.get("name") or "")
    if name == "product_spec":
        return str(args.get("name", ""))
    if name == "sketch_to_spec":
        return str(args.get("sketch", ""))
    if name == "delegate":
        return str(args.get("agent", "")) + " agent"
    if name == "optimize_design":
        return ", ".join(str(goal) for goal in args.get("goals") or [])
    if name == "optimize_apply":
        return "variant " + str(args.get("variant") or "")
    if name == "simulate_assembly":
        return str(args.get("mode") or "push") + " test"
    if name == "simulate_mission":
        missions = args.get("missions") or []
        return ", ".join(str(m.get("mission") if isinstance(m, dict) else m) for m in missions if m)
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
    if name in {"simulate_drone", "simulate_grip", "simulate_assembly", "simulate_mission"}:
        await ctx.step("simulation", "done" if result.get("result") == "pass" else "failed")
    elif name in {"check_tip_over", "check_deflection", "check_torque", "check_runtime", "check_power", "check_thermal", "check_rollover", "fem_check"}:
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
    elif name == "train_controller":
        await ctx.step("training", "done" if result.get("result") == "pass" else "failed")
    elif name == "isaac_lab_status" and result.get("training_status") == "done":
        await ctx.step("training", "done")
    elif name in {"blender_render", "isaac_sim_render", "cad_frame", "cad_part", "cad_update", "assemble", "product_brief", "product_spec", "sketch_to_spec", "reference_load", "part_pick", "bom_build", "print_prep", "material_pick"}:
        await ctx.step(step, "done")


async def call_tool(ctx: Ctx, name: str, args: dict | None) -> dict:
    payload = dict(args or {})
    function = TOOLS.get(name)
    if function is None:
        message = "Unknown tool: " + name
        await ctx.emit({"type": "tool", "name": name, "status": "error", "detail": message})
        return {"ok": False, "error": message}
    # Pause and Stop take effect here, between tool calls, never inside one.
    await ctx.checkpoint()
    await ctx.emit(
        {"type": "tool", "name": name, "status": "running", "detail": _running_detail(name, payload)}
    )
    await _advance(ctx, name, {}, started=True)
    seconds = limit(name)
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(function(ctx, payload), seconds)
    except RunStopped:
        # A tool that runs tools (delegate) was stopped inside: its card ends too.
        await ctx.emit({"type": "tool", "name": name, "status": "error", "detail": "Stopped by the user"})
        raise
    except TimeoutError:
        # A stuck tool ends here with a message the room can read, not a frozen run.
        message = timed_out(name, seconds or 0)
        result = {"ok": False, "error": message, "detail": message, "timed_out": True}
        await ctx.chat("agent", message)
        if name == "blender_render":
            result = {**await recorded_still(ctx, message), "timed_out": True}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    status = "error"
    if result.get("ok") is not False:
        status = str(result.get("status", "ok"))
        if status not in {"connected", "running", "ok", "error", "offline"}:
            status = "ok"
    detail = str(result.get("detail") or result.get("error") or "")
    final = {"type": "tool", "name": name, "status": status, "detail": detail, "ms": round((time.perf_counter() - started) * 1000)}
    if result.get("timed_out"):
        final["timed_out"] = True
    if result.get("cached"):
        final["cached"] = True
    await ctx.emit(final)
    await _advance(ctx, name, result, started=False)
    if result.get("ok") is not False:
        await refresh_requirements(ctx)
        await publish_geometry(ctx)
        if name in {"train_in_browser", "isaac_train", "isaac_lab_train", "train_controller"}:
            await refresh_after_training(ctx)
        if name == "bom_build":
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
    rows = (
        ("parts_search", "connected", "Parts library with specs from shop pages" + (", web search on" if live_prices_enabled() else "") + "".join(", " + name for name in distributors.configured())),
        ("simulate_drone", "connected", "MuJoCo on this machine"),
        ("simulate_mission", "connected", "MuJoCo missions on this machine"),
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
