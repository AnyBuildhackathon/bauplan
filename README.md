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

## Mock Mode

Without `ANTHROPIC_API_KEY`, mock mode walks through the entire story using the same tools that Claude calls.
The kickoff meeting builds version 1: specifications from Jamie, warning about the FunFly 4S, a flight simulation pushed to the ground by a downdraft gust in MuJoCo, battery swap to the Lava 1S 550, frame in FreeCAD, studio render in Blender, bill of materials, order tasks, and attaching the version to the meeting.
The review meeting builds version 2: mascot Mechanic asks clarifying questions when contradictions occur, resolves "last week's motor" via Jamie, swaps the motor and battery, and writes the difference back as a note.
Sending an additional prompt in the same session does not trigger a rebuild.
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
The script `agent/freecad/frame_build.py` produces STL, STEP, GLB, and `frame.FCStd` files.
If FreeCAD is absent or the script fails, CadQuery generates the same geometry.
`POST /api/cad/params` recalculates the frame with adjusted dimensions, and `POST /api/cad/open` opens the model inside the FreeCAD application.
Generated files are served from `/files/{session}/`.

If the FreeCAD GUI is running with the [freecad-mcp](https://github.com/neka-nat/freecad-mcp) add-on RPC server on `127.0.0.1:9875`, `cad_frame` constructs the frame visibly inside the open window: hub, four arms with motor mounts, boreholes, and export steps, capturing a viewport snapshot (`view_png_url`).
The chat panel reflects each step as "FreeCAD: Arm 2 of 4".
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

The `blender_render` tool searches for Blender at `/Applications/Blender.app/Contents/MacOS/Blender` and renders the entire assembled drone headless in a virtual studio: the genuine frame STL alongside motors, propellers, flight controller, and the selected battery at real physical scale, positioned on an infinity curve with softbox lights (EEVEE, 1600 x 900):

```bash
blender -b -P agent/blender/studio.py -- frame.stl studio-v1.png assembly.json
```

The file `assembly.json` specifies `arm_mm`, `thickness_mm`, `prop_mm`, and `battery_mm` dimensions; when absent, version 1 defaults apply.
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
| `ANTHROPIC_API_KEY` | Leave empty for mock mode, never committing secrets to the repository. |
| `ANTHROPIC_MODEL` | Claude model identifier defaulting to `claude-sonnet-5-5`. |
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
