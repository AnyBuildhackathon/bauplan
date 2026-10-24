# AnyBuild

Autonomous physical-AI engineering agent for developing physical products.
The backend in `agent/` decides each step, and the web dashboard in `web/` visualizes the process.
The event contract between them is documented in `docs/events.md`.
The team hackathon roadmap, timeline, and workstreams are documented in `docs/PLAN.md`.

## Getting Started

Start the backend with one command, which will listen on `http://127.0.0.1:8100`:

```bash
cd agent && uv run physical-ai-agent
```

`uv` downloads Python 3.12 and installs dependencies on first run.
The dashboard is the Vite application in `web/` listening on `http://127.0.0.1:5180`:

```bash
cd web && npm install && npm run dev
```

If the development server needs explicit host and port arguments:

```bash
cd web && npm run dev -- --port 5180 --host 127.0.0.1
```

## Any Product

AnyBuild builds whatever physical product you describe, not just the drone.
Type a request into the chat, for example:

```text
Design a phone stand for my desk that holds my phone for video calls. It must not tip when I tap the screen and the parts should cost under 6 euros.
```

Claude drives the whole bench through tool use:

1. `product_spec`: Claude writes the spec (function, requirements each with the check that judges it and a limit, and every printed part, bought part and external load); `agent/src/pai_agent/spec.py` validates it and answers all problems at once until it is right.
2. `cad_part` per printed part: Claude writes the FreeCAD script, `freecadcmd` builds it headless and sandboxed, and the geometry is checked against the part's envelope; failed scripts go back to Claude with the error, and after three failures a plain block stands in, clearly marked, so a live build never ends without geometry.
3. `part_pick` per bought part: catalog parts from `agent/data/catalogs/` (hobby electronics, motors, fans, pumps, batteries, servos, hardware, plus the drone and gripper catalogs), or an honest estimate marked as such; live shop prices plug in through `pai_agent.pricing.register_provider`.
4. `assemble`: one model with mass, cost, centre of mass, size and footprint, and warnings for parts that float.
5. The checks, each pass or fail against the requirements: `check_totals` (mass, cost, size), `check_tip_over` (centre of mass and tip angle or tipping push), `check_deflection` (beam estimate for arms, shelves and clips), `check_torque` (motor or servo sufficiency), `check_runtime` (battery life), and `simulate_assembly` (a MuJoCo push or drop test of the whole assembly, replayed with the real model in the Simulation tab).
6. On a fail Claude changes a parameter with `cad_update` (rebuild, reassemble and rerun every check) or swaps a part, and says why.
7. `blender_render` and `bom_build`.

The empty bench offers two starts that run the same flow.
"From a reference" loads a known product with all its real parts from the registry in `agent/data/references/`, rebuilt and rechecked through the same tools (no key needed), and then you change it in the chat, for example "make it hold a 480 g tablet", and live Claude reworks it.
"From scratch" takes any description.
The library (`GET /api/library`, `POST /api/library/{id}/open`, see `docs/events.md`) lists the micro FPV drone first and the robot gripper second, both built by their own code, then the reference builds and the projects users saved with `POST /api/library`: each is one `reference.json` with the spec, the picks and the checks, one FreeCAD script per printed part, and a studio render as thumbnail.

### Orchestrator and sub-agents

Claude works like a lead engineer with a small team.
The orchestrator (Claude Opus 5.5 by default, effort `high`, configurable up to `max`) plans the build, writes the spec, decides the fixes and reviews every report.
It delegates bounded jobs to sub-agents on a smaller model (Claude Sonnet 5.5 by default), each with only the tools its job needs: the CAD agent writes one part's FreeCAD script (several parts run side by side), the parts agent picks the bought parts, the analysis agent runs the checks and the MuJoCo test, and the pricing agent builds and prices the bill of materials.
Every agent shows up as its own card in the chat with model, effort, job, status, tokens and cost.
The models, the effort levels and delegation are set with `PAI_ORCHESTRATOR_MODEL`, `PAI_ORCHESTRATOR_EFFORT`, `PAI_SUBAGENT_MODEL`, `PAI_SUBAGENT_EFFORT` and `PAI_DELEGATION`, or at runtime with the sliders button in the top bar (`/api/settings`).

The dashboard renders any product from the spec and the check results: requirement rows with the measured value, four key-number cards, the assembly tree and per-part sliders in the CAD tab (moving one reruns the checks without a model call), the before/after MuJoCo replay, and a bill of materials with sample, estimated and live prices marked.
The drone and the gripper keep their own flows as special cases.
The math behind each check is in `agent/src/pai_agent/analysis.py` and `agent/src/pai_agent/rigid_sim.py`, the wire format in `docs/events.md`.

With a backend running, the dashboard opens in live mode with an empty bench; the top bar says whether Claude is live or the backend runs the scripted mock because `ANTHROPIC_API_KEY` is missing.
The recorded drone run plays only with `?demo` or when no backend answers, and says so.

## Mock Mode

Without `ANTHROPIC_API_KEY`, mock mode walks through the entire story using the same tools that Claude calls.
The story arrives at a real reference build, the 1S 2-inch toothpick from Mediocre Nerd's video "Build a Micro FPV Drone for $59": Twiglet 2" carbon frame, 1103 15000KV motors, Gemfan 2020 four-blade props, Caddx Ant camera, BetaFPV Matrix 1S 5in1 V2 AIO, canopy with battery holder, M1.4 bolts and a 1S pack, each a bill-of-materials line with its mass, sample price and shop link.
The kickoff meeting builds version 1: specifications from Jamie, warning about the FunFly 4S, a flight simulation pushed to the ground by a downdraft gust in MuJoCo, battery swap to the Tattu R-Line 1S 550, frame in FreeCAD, studio render in Blender, bill of materials, order tasks, and attaching the version to the meeting (47.2 g, 8.5 min, 113.64 €).
The review meeting builds version 2: mascot Mechanic asks which flight time counts when the review contradicts the kickoff, swaps to the BetaFPV LAVA II 1S 680 for 10 minutes, and writes the difference back as a note (48.4 g, 10.4 min, 115.12 €).
Sending an additional prompt in the same session does not trigger a rebuild.
A prompt asking for a phone stand plays the generic story through the same tools Claude uses: spec, two printed PETG parts from the phone stand reference build (`agent/data/references/phone-stand/`), rubber feet from the catalog, a tip-over check and MuJoCo push test that fail with a 60 mm base, the fix to a 110 mm base with every check passing, the Blender render and the bill of materials.
`POST /api/reset` resets the session to start over.
Setting `PAI_FORCE_MOCK=1` forces mock mode even when an Anthropic API key is configured.

Both builds can be triggered via Jamie webhooks when meetings conclude:

```bash
curl -s -X POST http://127.0.0.1:8100/api/webhooks/jamie \
  -H 'content-type: application/json' \
  --data @agent/data/webhooks/meeting-ended.json
curl -s -X POST http://127.0.0.1:8100/api/webhooks/jamie \
  -H 'content-type: application/json' \
  --data @agent/data/webhooks/review-ended.json
```

A `meeting.started` webhook sets the meeting state on the timeline to live and performs no build.
Without sending a webhook, the button next to the upcoming review on the timeline triggers the same action.
Other webhook events return `status: ignored` and take no action.

## Jamie Integration

Jamie serves as the project sensory backbone: every design version links to its originating meeting, and every component choice links back to the spoken sentence that justified it.
The `jamie_templates` tool automatically creates the templates "Hardware-Anforderungen" and "Drohnen-Review".
The `jamie_requirements` tool reads the template fields first with quote, speaker, and timestamp, then the meeting requirement list, and finally transcript sentences.
When selecting a part, warnings from earlier meetings surface, such as workshop notes regarding the FunFly motor.
The `jamie_meeting` tool reads a review: changed requirements, contradictions against previous meetings, and part complaints, resolving "last week" to meetings held 4 to 10 days earlier.
The `version_commit` tool writes the design difference back as a note and tags the meeting with `drohne` and `drohne-v{n}`.
The `jamie_create_tasks` tool creates order tasks per part with an assigned person and due date; marking a part as ordered in the bill of materials checks off the task in Jamie.

With `JAMIE_MCP_TOKEN` configured, requests go live to `https://mcp.meetjamie.ai/mcp` via Streamable HTTP with a bearer token.
Without a token, or if a live call fails, operations fall back to the fixture meetings in `agent/data/meetings/` and log writes to the session outbox `jamie_outbox.json`.
The user interface looks identical in both modes; chat cards indicate "local outbox" when running offline.

## CAD Frame and Studio Rendering

The `cad_frame` tool searches for `freecadcmd` under `/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd`.
The script `agent/freecad/frame_build.py` builds the whole drone, the 1S 2-inch toothpick of the reference build, from the frame parameters and the parts chosen so far.
The Twiglet carbon X-frame is a unibody plate with rounded arms, motor pads and lightening slots; FreeCAD weighs it at carbon-plate density (5.2 g against the 5.3 g listing) and that mass replaces the catalog figure.
The other parts sit around it at catalog size, each its own body and GLB node: 1103 motors with stator, windings, magnets and screws, Gemfan 2020 four-blade props, the AIO flight controller on standoffs with its wiring, the TPU canopy with the Caddx Ant and the antenna tube, the battery holder, the 1S pack strapped under the frame, and the antennas.
It writes `frame.FCStd` (the assembly), `frame.step` and `frame.stl` (the X-frame), `drone.step` (the assembly), and `frame.glb`, the assembly with one node per scene target and PBR materials, which the Model and CAD tabs show.
If FreeCAD is absent or the script fails, CadQuery generates the bare frame and the dashboard keeps showing the recorded drone.
`POST /api/cad/params` recalculates the frame with adjusted dimensions, and `POST /api/cad/open` opens the model inside the FreeCAD application.
Generated files are served from `/files/{session}/`.

If the FreeCAD GUI is running with the [freecad-mcp](https://github.com/neka-nat/freecad-mcp) add-on RPC server on `127.0.0.1:9875`, `cad_frame` constructs the drone visibly inside the open window with the same script, stage by stage (frame, motors, propellers, flight controller, canopy and camera, battery and strap, antenna), then exports and captures a viewport snapshot (`view_png_url`).
The chat panel reflects each step as "FreeCAD: Motors".
If the window does not answer or a step times out after 12 seconds, execution falls back to headless `freecadcmd`, and then CadQuery.
`FREECAD_GUI=launch` opens FreeCAD automatically if the window is absent, while `FREECAD_GUI=off` forces headless execution.

The FreeCAD add-on is not installed by this repository.
For a manual one-time setup on FreeCAD 1.1:

```bash
git clone https://github.com/neka-nat/freecad-mcp.git
mkdir -p "$HOME/Library/Application Support/FreeCAD/v1-1/Mod"
cp -R freecad-mcp/addon/FreeCADMCP "$HOME/Library/Application Support/FreeCAD/v1-1/Mod/FreeCADMCP"
```

Then in FreeCAD, open the `MCP Addon` workbench and select `Toggle Auto Start` so the RPC server launches automatically with the GUI on localhost.

The `blender_render` tool searches for Blender at `/Applications/Blender.app/Contents/MacOS/Blender` and renders the FreeCAD drone GLB headless in a virtual studio: a clear-coated carbon weave on the frame, see-through props, an infinity curve with a soft key, fill and two rim lights, path-traced in Cycles (Metal GPU when available) at 1600 x 900:

```bash
blender -b -P agent/blender/studio.py -- frame.stl studio-v1.png assembly.json
```

The file `assembly.json` names the `glb`; without one (the CadQuery fallback) it specifies `arm_mm`, `thickness_mm`, `prop_mm`, and `battery_mm`, and the studio places simple parts around the frame STL in EEVEE.
If Blender is missing, the tool status shows `offline` and the `render` event serves `agent/runs/fallback/render.png`.

## General CAD and the Robot Gripper

AnyBuild is not tied to the drone.
`cad_part` builds any part from a description: Claude writes FreeCAD Python for it, `freecadcmd` runs the script headless, and the tool returns STEP, STL and GLB with volume, mass for the chosen material and the bounding box.
When FreeCAD reports an error, Claude gets the script and the error back and fixes it, up to three attempts.
The script is checked before it runs (only `FreeCAD`, `Part` and `math` imports, no file access), runs in a fresh temp directory without the backend's environment and with a 60 s timeout, and on macOS `sandbox-exec` blocks network access and writes outside that directory.
The part shows up in the CAD tab like the drone frame, with its parameters as sliders, its bodies in the tree and a Script button that shows the generated code.
Moving a slider reruns the same script without a model call.
The harness is `agent/freecad/part_harness.py`, the runner `agent/src/pai_agent/cad_script.py`, the tool `agent/src/pai_agent/tools/cad_part.py`.

The second example product is a parametric two-finger robot gripper, chosen because it has moving parts, a real physics question (does it hold the object while the arm moves?) and a parts choice that changes the CAD.
Ask for it in the chat, for example with the "Robot gripper" example on the empty chat:

```text
Design a robot gripper for our arm that picks up a 200 g soda can, 66 mm wide. Keep it under 150 g and 30 €.
```

`product_brief` turns the request into checks, `catalog_search` picks servo, pads, hardware and driver from `agent/data/catalogs/gripper.json`, `grip_calc` computes finger force and grip safety, `simulate_grip` lifts and shakes the object in MuJoCo, `cad_part` builds the gripper from `agent/freecad/library/gripper.py` with the servo pocket sized for the chosen servo, then `blender_render` and `bom_build`.
Without `ANTHROPIC_API_KEY` the mock plays this story through the same tools: the SG90 drops the can, the MG996R holds it.
Check it without a network:

```bash
cd agent && uv run python scripts/smoke_cad_part.py
```

## Voice Integration

In the chat interface, press and hold the spacebar or microphone button to speak with mascot Mechanic and answer clarification questions.
With `RESON8_API_KEY`, [Reson8](https://docs.reson8.dev) transcribes speech in real time: the backend vends a short-lived token (`POST /api/voice/token`) and the browser streams 16 kHz PCM audio to `wss://api.reson8.dev/v1/speech-to-text/realtime`.
The API key stays securely on the backend.
Without an API key, the browser uses its native Web Speech recognition, falling back to text typing.
Mechanic speaks responses using the browser speech synthesis engine, or via ElevenLabs when `ELEVENLABS_API_KEY` is provided.
The speaker button in the chat header mutes audio output; loading with `?mute` starts muted.

## Environment Variables

Place environment variables in `agent/.env` or in the host operating system shell.
Do not commit `.env` files or secret keys to the repository.
Shell variables override values in `.env`.

| Variable | Description |
| --- | --- |
| `ANTHROPIC_API_KEY` | Leave empty for mock mode, never committing secrets to the repository. With a key, the bill of materials searches live shop prices, also in mock mode. |
| `ANTHROPIC_MODEL` | Orchestrator model when `PAI_ORCHESTRATOR_MODEL` is unset, defaulting to `claude-opus-5-5`. |
| `PAI_ORCHESTRATOR_MODEL` | Model of the orchestrator, defaulting to `ANTHROPIC_MODEL` or `claude-opus-5-5`. |
| `PAI_ORCHESTRATOR_EFFORT` | Orchestrator effort (`low`, `medium`, `high`, `xhigh`, `max`), defaulting to `high`. |
| `PAI_SUBAGENT_MODEL` | Model of the sub-agents (CAD scripts, parts, checks, pricing), defaulting to `claude-sonnet-5-5`. |
| `PAI_SUBAGENT_EFFORT` | Sub-agent effort, defaulting to `medium`. |
| `PAI_DELEGATION` | Set to `0` to let the orchestrator pick parts and run checks itself instead of delegating. |
| `PAI_FORCE_MOCK` | Set to `1` to force mock mode execution. |
| `DEMO_PACE_S` | Pause delay between agent workflow steps in seconds, defaulting to `0`. |
| `PORT` | Backend HTTP port, defaulting to `8100`. |
| `JAMIE_MCP_TOKEN` | Bearer token for live Jamie MCP API, leaving empty for local mock fixtures and outbox. |
| `JAMIE_MCP_URL` | Jamie MCP server URL defaulting to `https://mcp.meetjamie.ai/mcp`. |
| `JAMIE_WEBHOOK_SECRET` | Secret token verified against `X-Jamie-Secret` header or `?secret=` when tunneling requests. |
| `RESON8_API_KEY` | Reson8 API key for speech-to-text, leaving empty for browser speech recognition. |
| `RESON8_LANGUAGE` | Language code for Reson8 speech-to-text, defaulting to `en`. |
| `ELEVENLABS_API_KEY` | ElevenLabs API key for Mechanic speech synthesis, leaving empty for browser speech synthesis. |
| `ELEVENLABS_VOICE_ID` | Optional English voice identifier for ElevenLabs audio generation. |
| `FREECAD_GUI` | FreeCAD execution mode defaulting to `auto` (`auto` builds in open window, `launch` starts app, `off` forces headless). |
| `FREECAD_MCP_URL` | FreeCAD MCP RPC server URL defaulting to `http://127.0.0.1:9875`. |
| `PAI_ASK_TIMEOUT_S` | Seconds Mechanic waits for question response before choosing default option, defaulting to `20`. |
| `RUNPOD_SSH_HOST` | Hostname or IP for RunPod GPU instance, leaving empty for offline fallback fixtures. |
| `RUNPOD_SSH_PORT` | SSH port for RunPod pod, defaulting to `22`. |
| `RUNPOD_SSH_USER` | SSH username for RunPod pod, defaulting to `root`. |
| `RUNPOD_SSH_KEY` | File path to private SSH key for RunPod access. |

## Omniverse GPU experiments

For drones, the **Omniverse** tab runs wind, payload and hover experiments in NVIDIA Isaac Sim and reference Crazyflie training in Isaac Lab over SSH.
Blender exports the current CAD assembly as USD with per-part masses.
Without a working GPU pod, the app plays a clearly labelled recorded demo with synthetic fixture values.
See [Omniverse setup, tools, limitations and verification](docs/omniverse.md) for the full contract, including local ports 8113 and 5193.

## Smoke Test

Run the end-to-end SSE smoke test script:

```bash
cd agent && uv run python scripts/smoke_sse.py
```

The smoke test launches an isolated server instance on port 8101 (`SMOKE_PORT`), forces mock mode, and runs both kickoff and review flows through the SSE stream.

## Recorded session

The app opens in Live. `?demo` still replays a recorded mock run, so the numbers on that path match the backend.
After making changes to the story, component catalogs, or physics parameters, re-record the fixture:

```bash
cd agent && uv run python scripts/record_demo.py
```

This updates `web/src/events/recording.json` and copies CAD parts and render assets into `web/public/demo/run/`.
