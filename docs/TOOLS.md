# Agent tools

Claude builds products by calling tools; it never invents a number that a tool did not compute.
The backend registers 51 tools in `agent/src/pai_agent/tools/registry.py`, with one schema list (`SCHEMAS`) and one dispatch (`call_tool`) shared by Claude and the offline mock.
This document lists every tool with its inputs, what it returns and emits, and the external software behind it.
The inputs below are generated from `SCHEMAS`; "(required)" marks required fields.
Event payloads are specified in [events.md](events.md#tools), and the step each tool lights up on the dashboard is in `_STEP` in the registry.

## External software and services behind the tools

| Software or service | Used by | How it is called | Fallback without it |
| --- | --- | --- | --- |
| **Anthropic Claude** (Opus 5.5, Sonnet 5.5, Haiku 5.5) | Orchestrator, sub-agents, `cad_part` script writing, `sketch_to_spec` (vision), `bom_build` live prices (server-side web search), learning-mode explanations | Anthropic Python SDK, Messages API with tool use, adaptive thinking and effort | Scripted mock stories through the same tools |
| **FreeCAD 1.1** | `cad_frame`, `cad_part`, `cad_update`, `POST /api/cad/open` | GUI over the [freecad-mcp](https://github.com/neka-nat/freecad-mcp) XML-RPC add-on on port 9875, or headless `freecadcmd` in a sandbox | CadQuery (frame) or a marked placeholder block (generated parts) |
| **CadQuery 2.8** (OpenCascade) | `cad_frame` fallback | Python library | None needed |
| **Blender 5** | `blender_render`, `product_usd` | Headless `blender -b -P agent/blender/studio.py` (Cycles with Metal GPU, or EEVEE) | Recorded still `agent/runs/fallback/render.png` |
| **MuJoCo 3.17** | `simulate_drone`, `simulate_assembly`, `simulate_grip` on the backend; `train_in_browser`, `stress_test` in the browser | Python bindings; `@mujoco/mujoco` WebAssembly in the dashboard | None needed |
| **NVIDIA Isaac Sim 5.1 and Isaac Lab 2.3** | `isaac_test`, `isaac_train` and aliases | SSH to a GPU host prepared by `runpod/setup.sh`, job script `runpod/isaac_job.py` | Recorded, clearly labelled result |
| **Jamie MCP** | All `jamie_*` tools, `requirements_accept`, `version_commit` | Streamable HTTP MCP client (`jamie_client.py`) with a bearer token | Fixture meetings and local outbox `jamie_outbox.json` |
| **Reson8** | Voice input (not a tool) | Browser WebSocket with a short-lived token from the backend | Browser Web Speech recognition |
| **Gemini Live** | Mechanic's only voice (not a tool) | Native realtime audio through `WS /api/voice/live` | Silent, text only |
| **Betaflight and Arduino** | `firmware` | Deterministic templates filled from the chosen parts | None needed |

## Product definition

| Tool | Inputs | Returns and emits | Behind it |
| --- | --- | --- | --- |
| `product_spec` | `name` (required): string; `function` (required): string; `quote`: string; `requirements` (required): array; `assemblies`: array; `parts` (required): array | Validates the full spec of any product (`spec.py`) and lists every problem at once until it is right; emits `product` and `requirement` rows. | Python validation |
| `product_brief` | `product` (required): `drone` or `gripper`; `object_mass_g`, `object_width_mm`, `max_weight_g`, `budget_eur`: number; `quote`: string | Starts a drone or gripper build and turns the request into requirement checks. | Python |
| `sketch_to_spec` | `sketch`: string (file name); `note`: string | Reads a hand-sketch photo: a validated spec, every dimension with value, unit and confidence, what was unreadable, and a summary; emits `sketch`. | Claude vision |
| `reference_load` | `id`: string | Without `id` lists the reference builds. With `id` and no live key, loads the saved build onto the bench. With a live key, returns the spec and parts (`request`) and does not replay the saved run. | `agent/data/references/` |
| `delegate` | `agent` (required): `parts`, `checks` or `pricing`; `task` (required): string | Runs a sub-agent with only its tools and returns its report, tool calls, tokens and cost; emits `agent`. | Claude Sonnet 5.5 |

## CAD and assembly

| Tool | Inputs | Returns and emits | Behind it |
| --- | --- | --- | --- |
| `cad_part` | `name` (required): string; `description`: string; `params`: object; `material`: `PLA`, `PETG`, `ABS`, `ASA`, `NYLON`, `TPU`, `ALUMINIUM` or `STEEL`; `template`: `gripper`; `script`: string | STEP, STL and GLB, volume, mass for the material and bounding box; Claude writes the FreeCAD script from the description and fixes it from FreeCAD's error, up to three attempts; emits `cad`. | FreeCAD headless, sandboxed |
| `cad_frame` | `arm_length_mm`, `thickness_mm`, `motor_spacing_mm` (all required): number | The full drone assembly: `frame.FCStd`, STEP, STL and a GLB with one node per scene part and PBR materials, plus the FreeCAD mass of the carbon frame; emits `cad` stage by stage when the GUI is open. | FreeCAD GUI or headless, CadQuery fallback |
| `cad_update` | `part_id` (required): string; `params` (required): object | Rebuilds one printed part from the same script, reassembles, and reruns every check that ran before; returns the new results. | FreeCAD headless |
| `assemble` | `placements`: object | One model with mass, cost, centre of mass, size and footprint, and warnings such as floating parts. | Python mesh math in `assembly.py` and `mesh_export.py` |
| `product_usd` | none | Exports the current drone assembly as USD with per-part masses in kilograms. | Blender |

## Parts and pricing

| Tool | Inputs | Returns and emits | Behind it |
| --- | --- | --- | --- |
| `part_pick` | `part_id` (required): string; `query`, `category`, `select_id`, `reason`: string; `estimate`: object | Searches every catalog or binds a part; when nothing fits, an estimate marked as estimated; emits `part`. | `agent/data/catalogs/`, `pricing.register_provider` |
| `parts_search` | `category` (required): enum; `query`, `select_id`, `reason`: string; `because`: enum | Drone catalog search; every hit carries `jamie_notes`, what earlier meetings said about the part; emits `part` with quote and warnings. | `agent/data/parts.json`, Jamie |
| `catalog_search` | `category` (required): `servo`, `pads`, `hardware` or `driver`; `query`, `select_id`, `reason`: string | Gripper catalog search and selection. | `agent/data/catalogs/gripper.json` |
| `bom_build` | none | The bill of materials with quantities, unit prices, weights, shop links and `price_source`; with `ANTHROPIC_API_KEY` it searches live shop prices (EU first); emits `bom` and `metrics`. | Claude server-side web search (`tools/parts_search.py`) |

## Engineering checks

Each check judges one kind of requirement and emits a `requirement` row with the measured value and pass or fail.
With delegation on (the default), these tools belong to the analysis sub-agent.

| Tool | Inputs | Returns | Behind it |
| --- | --- | --- | --- |
| `check_totals` | none | Mass without external loads, cost (filament plus bought parts) and size against the limits. | `analysis.py` |
| `check_tip_over` | `push_height_mm`: number | Centre of mass, tip angle about the weakest footprint edge, and the horizontal push that tips it. | `analysis.py` |
| `check_deflection` | `part_id`, `span_mm`, `width_mm`, `thickness_mm`, `load_n` (all required); `support`: `cantilever` or `simple` | Beam deflection and stress safety (needs 2x, printed plastic at 60 % strength). | `analysis.py` |
| `check_torque` | `actuator_part_id` (required): string; `required_torque_nm`, `lever_mm`, `force_n`, `load_mass_g`: number | Torque margin with usable torque at 70 % of stall for a servo, 80 % for a stepper, 50 % for a DC motor. | `analysis.py` |
| `check_runtime` | `battery_part_id` (required): string; `loads` (required): array | Battery runtime from 80 % of the battery energy, duty cycles and controller sleep power. | `analysis.py` |
| `check_power` | `supply_part_id` (required): string; `loads` (required): array | Power headroom of a supply or battery, regulators at 85 %, and runtime for a battery. | `analysis_more.py` |
| `check_thermal` | `enclosure_part_id` (required): string; `power_w`, `wall_mm`, `vents_mm2`, `ambient_c`, `component_limit_c`: number; `heat_part_ids`, `fan_part_ids`, `bbox_mm`: array | Inside temperature of a closed case from convection, vents and fans, against the wall material and component limits. | `analysis_more.py` |
| `check_rollover` | `track_mm`, `wheelbase_mm`, `com_height_mm`, `speed_mps`, `turn_radius_m`: number | Static stability factor and the lateral g a vehicle rolls at, against a turn. | `analysis_more.py` |

Known gap: with delegation on, `check_power`, `check_thermal` and `check_rollover` are hidden from the orchestrator but not in the analysis agent's tool list, so they are only reachable with `PAI_DELEGATION=0`.

## Simulation and training

| Tool | Inputs | Returns and emits | Behind it |
| --- | --- | --- | --- |
| `simulate_assembly` | `mode`: `push` or `drop`; `force_n`, `drop_height_mm`: number; `push_point_mm`: array | Push test (settles within the stability limit or tips) or drop test (peak load in g) of the whole assembly as one rigid body; emits `sim` with the trajectory for the replay. | MuJoCo (`rigid_sim.py`) |
| `simulate_drone` | none | Drone hover with a downdraft gust: pass when it holds the hover, fail when too heavy; emits `sim`. | MuJoCo |
| `physics_calc` | none | Drone mass, thrust-to-weight, estimated flight time and price from the chosen parts; emits `metrics`. | Python |
| `grip_calc` | none | Gripper finger force, holding force with pad friction and safety factor (needs 2x). | Python |
| `simulate_grip` | none | The pads squeeze, the arm lifts 15 cm and shakes; pass when the object stays within 10 mm; emits `sim`. | MuJoCo (`grip_sim.py`) |
| `train_in_browser` | none | Tunes the controller in 1,024 MuJoCo simulations (64 candidates over 16 generations, evolution strategy) in the open dashboard and returns the best gains and score; emits `training`. | MuJoCo WebAssembly in the browser |
| `stress_test` | `gains`: object | Flies the best controller in 50 randomized worlds (mass, motor strength, gusts, sensor noise) and returns the robustness score and the weakest point; emits `stress`. | MuJoCo WebAssembly in the browser |
| `isaac_test` | `scenario`: `wind`, `payload` or `hover`; `wind_m_s`, `payload_g`, `duration_s`: number | Video and JSON measurements of the exported drone in Isaac Sim, or a recorded illustrative result; emits `omniverse`. | NVIDIA Isaac Sim over SSH |
| `isaac_train` | `iterations`, `num_envs`: integer | Video and learning curve of Isaac Lab's reference Crazyflie task (`Isaac-Quadcopter-Direct-v0`), not the CAD product; emits `omniverse`. | NVIDIA Isaac Lab over SSH |
| `isaac_lab_train` | none | Alias for `isaac_train`. | Isaac Lab |
| `isaac_sim_render` | none | Alias for `isaac_test` with the wind scenario. | Isaac Sim |
| `isaac_lab_status` | `job_id`: string | The latest Omniverse result or progress. | Isaac Sim and Lab |

See [omniverse.md](omniverse.md) for the GPU host setup, the experiment contract and the limitations.

## Output: render, bill of materials, guide, firmware

| Tool | Inputs | Returns and emits | Behind it |
| --- | --- | --- | --- |
| `blender_render` | none | A path-traced studio PNG of the assembled model on a workbench scene, one per version; emits `render`. | Blender headless |
| `build_guide` | `steps` (required): array | The step-by-step build guide: which scene parts each step uses, tools and minutes; emits `build_guide`. | Claude writes it, the code checks coverage |
| `firmware` | `explanation`: string | A Betaflight CLI configuration (motor order, rates, trained PID gains) for a drone or an Arduino sketch for a servo product, plus the wiring table; emits `firmware`. | Deterministic templates |

## Jamie meeting loop

| Tool | Inputs | Returns and emits | Behind it |
| --- | --- | --- | --- |
| `jamie_templates` | none | Creates the summary templates "Hardware-Anforderungen" and "Drohnen-Review" (`upsert_template`); emits `jamie`. | Jamie MCP |
| `jamie_requirements` | `meeting_id`: string | The kickoff requirements, each with quote, speaker and time; emits `requirement`. | Jamie MCP (`get_meeting`, transcript) |
| `jamie_search` | `query` (required): string | Earlier meetings that mention a part, for warnings. | Jamie MCP (`search_meetings`) |
| `jamie_meeting` | `meeting_id` (required): string | A finished review: changed requirements, conflicts with earlier meetings, and part complaints resolved to the meeting they refer to. | Jamie MCP |
| `requirements_accept` | `meeting_id` (required): string; `ids`: array | Accepts some or all requirements of a meeting into the build. | Jamie MCP |
| `ask_user` | `question`, `options`, `default_id` (all required) | Asks the room and waits for a click, speech or text; the default applies after `PAI_ASK_TIMEOUT_S`; emits `question`. | Dashboard |
| `version_commit` | `meeting_id`: string | Attaches the version to its meeting, writes the difference as a note and tags the meeting `drohne-v{n}`; emits `version`. | Jamie MCP (`create_tag`, `add_tag_to_meetings`) |
| `jamie_create_tasks` | `meeting_id`: string | One order or print task per BOM line with a person and due date; replaced parts are closed; emits `tasks`. | Jamie MCP (`create_tasks`, `update_tasks`) |

## Dashboard and mascot

| Tool | Inputs | Returns and emits | Behind it |
| --- | --- | --- | --- |
| `ui_control` | `control` (required): string; `open`: boolean; `value`: any; `part`: string; `versions`: array; `say`: string | Mechanic operates a real dashboard control in front of the audience (tabs, views, panels, explode slider, compare versions, settings); emits `ui`. | Dashboard |
| `ui_point_at` | `target` (required): scene name; `label`: string | The 3D pointer flies to a part; emits `point`. | Dashboard |
| `ui_draw` | `kind` (required): `halo`, `arrow`, `circle` or `note`; `target` (required); `text` (required) | Draws an annotation on a scene part; emits `draw`. | Dashboard |
| `mascot_say` | `state` (required): expression; `say` (required): string | Mechanic changes expression and says one short sentence; emits `mascot`. | Dashboard |

Scene target names and control names are listed in [events.md](events.md#scene-targets).

## Safety review

| Tool | Inputs | Returns and emits | Behind it |
| --- | --- | --- | --- |
| `safety_check` | `context`: string; `findings`: array of findings with severity, title, reason, rule and fix | Returns sorted findings, top finding, disclaimer and next action; emits `safety` with product, label, findings and summary before ordering. | Python rules over the build and optional Claude findings; advisory, not certification |

## Print preparation

| Tool | Inputs | Returns and emits | Behind it |
| --- | --- | --- | --- |
| `print_prep` | `orientation`: `flat`, `upright` or `as_modeled`; `orientations`: per-part orientation map | Emits `print` with printability warnings, per-part and total time, filament and cost; provides G-code when sliced and adds filament to the BOM. Otherwise returns explicitly labelled mesh estimates. | PrusaSlicer or OrcaSlicer CLI, else NumPy mesh calculations |
