# AnyBuild

AnyBuild is a physical-AI engineering agent for drone design.
The project was originally named Bauplan and code references still reflect that name in places.
It is built for the {Tech: Europe} Agentic AI Hack Berlin on 2026-10-24.
Partners include Jamie, Reson8, and Anthropic.
Live demos take place on a projector at 20:00, with an opt-in deadline at 19:00.

## Product and Stage Demo Story

Team meetings recorded with Jamie define the engineering requirements.
Claude uses tools to design and validate a drone inside real engineering applications.
FreeCAD builds the frame visibly in an open window, with headless FreeCAD and CadQuery fallbacks.
Blender renders the assembled drone in a virtual studio environment.
MuJoCo simulates drone flight stability against wind gusts.
AnyBuild extracts real measurements: CAD weight, thrust-to-weight ratio, flight time, stability pass/fail, and bill of materials cost.
Jamie serves as the project backbone.
The meeting timeline attaches every drone version to its originating meeting.
Every part links to a specific quote naming the speaker, timestamp, and meeting title.
Earlier meeting notes surface as warnings before part selection.
Contradictions between meetings trigger user questions from mascot Bolzen before building.
The agent creates the Jamie templates "Hardware-Anforderungen" and "Drohnen-Review" automatically.
When a meeting ends, AnyBuild rebuilds the drone and posts differences back to Jamie as notes.
Jamie tags mark drone versions on meetings.
Order tasks with assignees and due dates appear in Jamie.
Realtime speech-to-text uses Reson8 to speak with mascot Bolzen in the chat.
Bolzen answers using browser speech synthesis or ElevenLabs.
Offline fallbacks run the complete workflow when API keys are absent.
The stage demo begins with a kickoff meeting recording that builds drone version 1.
During kickoff, the agent catches warnings about the FunFly 4S motor, fails an initial downdraft test in MuJoCo, and switches to the Lava 1S 550 pack.
A live review follows requesting 15 minutes of flight time and noting that last week's motor was too loud.
Bolzen asks for clarification on flight time requirements and resolves the motor reference.
AnyBuild rebuilds to version 2, showing metrics differences, quotes, warnings, and updated order tasks.
A public static demo is available at https://anybuild-demo.vercel.app.

## Repository Map

The repository is structured into five main directories:

- `agent/`: Python backend, Claude tool definitions, physics simulation, CAD generation, and Jamie client.
  - `agent/src/pai_agent/app.py`: FastAPI application server, SSE event stream, and webhook endpoints.
  - `agent/src/pai_agent/session.py`: Session orchestrator managing events, tool execution, and mock flow.
  - `agent/src/pai_agent/mock_story.py`: Deterministic fallback mock runner for version 1 and version 2 builds.
  - `agent/src/pai_agent/orchestrator.py`: Claude tool-use execution loop.
  - `agent/src/pai_agent/tools/`: Tool definitions for CAD, MuJoCo simulation, Blender, Jamie, BOM, and UI interaction.
  - `agent/src/pai_agent/freecad_run.py`: FreeCAD MCP RPC connector and headless fallback execution.
  - `agent/src/pai_agent/jamie_client.py`: Streamable HTTP client for the Jamie MCP server.
  - `agent/src/pai_agent/voice.py`: Reson8 STT token management and ElevenLabs TTS audio synthesis.
  - `agent/scripts/smoke_sse.py`: End-to-end SSE mock verification script.
  - `agent/scripts/record_demo.py`: Demo run recorder creating static playback fixtures.
- `web/`: Vite, React, and Three.js frontend dashboard.
  - `web/src/App.tsx`: Top-level application layout containing chat, timeline, canvas, and panels.
  - `web/src/events/store.ts`: Zustand event store for SSE updates, metric tracking, and version state.
  - `web/src/events/source.ts`: SSE stream consumer and demo playback controller.
  - `web/src/events/types.ts`: TypeScript interfaces for the wire protocol.
  - `web/src/components/chat/`: Bolzen sidebar chat with audio controls and speech recognition.
  - `web/src/components/timeline/`: Jamie meeting timeline showing kickoff and review milestones.
  - `web/src/components/canvas/`: 3D canvas tabs for model visualization, CAD views, and simulation.
  - `web/src/components/panels/`: Compact requirement checklist and four primary metrics.
  - `web/src/views/`: Primary views including workbench, logbook, and training tabs.
- `desktop/`: Tauri 2 native desktop application wrapper.
  - `desktop/src-tauri/`: Tauri Rust backend configuration and window lifecycle handlers.
  - `desktop/package.json`: Build commands for native macOS app bundles.
- `docs/`: Technical specifications.
  - `docs/events.md`: Authoritative wire format contract for HTTP and SSE communication.
- `runpod/`: Cloud GPU infrastructure scripts.
  - `runpod/setup.sh`: Setup script for NVIDIA Isaac Sim 6.2 and Isaac Lab 3.0 on an RTX 4090 pod.

## Running Locally

Run backend and frontend in separate terminals.

### Backend

The backend requires Python 3.12 and `uv`.
Port 8100 is the default backend port.

```bash
cd agent && uv run physical-ai-agent
```

### Frontend

The web dashboard requires Node.js.
Port 5180 is the default frontend port.

```bash
cd web && npm install && npm run dev
```

If the port is occupied or needs explicit specification, pass flags:

```bash
cd web && npm run dev -- --port 5180 --host 127.0.0.1
```

### Desktop Application

The Tauri 2 application bundles the web dashboard into a native macOS window.

```bash
cd desktop && npm install && npm run dev
```

### Mock Mode and Webhook Triggers

Without an Anthropic key, the backend runs in mock mode automatically.
Trigger the kickoff build via webhook:

```bash
curl -s -X POST http://127.0.0.1:8100/api/webhooks/jamie -H 'content-type: application/json' --data @agent/data/webhooks/meeting-ended.json
```

Trigger the review build via webhook:

```bash
curl -s -X POST http://127.0.0.1:8100/api/webhooks/jamie -H 'content-type: application/json' --data @agent/data/webhooks/review-ended.json
```

Reset the session state to start over:

```bash
curl -s -X POST http://127.0.0.1:8100/api/reset -H 'content-type: application/json'
```

### Smoke Test

Verify the backend and SSE mock pipeline with the standalone smoke script.

```bash
cd agent && uv run python scripts/smoke_sse.py
```

### Demo URL Parameters

The frontend accepts URL parameters to control playback and view states:

- `?demo`: Plays the recorded mock session from static fixtures without requiring a backend.
- `?live`: Forces connection to the live backend server.
- `?mute`: Disables audio synthesis playback on initial load.
- `?speed=N`: Multiplies playback speed in demo mode (for example `?speed=2`).
- `?seek=MARKER`: Jumps directly to a named event marker in demo playback.
- `?end`: Renders the final completed state immediately in demo mode.
- `?autoplay`: Starts demo playback automatically upon page load.
- `?view=werkbank|training|logbuch`: Sets the active main view.
- `?tab=modell|cad|simulation`: Selects the initial 3D canvas tab.
- `?bom`: Opens the Bill of Materials drawer on startup.
- `?lesson=STEP`: Opens the learning modal for a specific step identifier.

## SSE Event Contract

The wire format contract is defined exclusively in `docs/events.md`.
All clients and backend tools must adhere to that specification.

### HTTP Endpoints

- `POST /api/prompt`: Sends user messages to the agent session.
- `GET /api/events`: Subscribes to the Server-Sent Events stream.
- `POST /api/reset`: Resets session state, event history, and timeline.
- `POST /api/webhooks/jamie`: Receives Jamie meeting lifecycle webhooks.
- `POST /api/answer`: Submits answers to mascot Bolzen's clarification questions.
- `POST /api/tasks/{id}`: Toggles status of parts ordering tasks.
- `POST /api/cad/params`: Recomputes frame parameters dynamically.
- `POST /api/cad/open`: Launches FreeCAD GUI with the current CAD file.
- `GET /api/voice`: Returns speech-to-text and text-to-speech capabilities.
- `POST /api/voice/token`: Generates short-lived Reson8 STT authorization tokens.
- `POST /api/voice/speak`: Produces audio streams via ElevenLabs TTS.
- `GET /api/health`: Reports server status and mock mode flag.
- `GET /files/{bucket}/{name}`: Serves generated CAD assets, renders, and videos.

### SSE Event Types

The event stream emits typed JSON objects:
- `reset`: Clears all client-side session state.
- `replayed`: Delimits backlog replay from live streaming events.
- `step`: Notifies workflow step transitions (`meeting`, `teile`, `cad`, `render`, `simulation`, `training`, `stueckliste`).
- `chat`: Carries user or agent chat utterances.
- `tool`: Updates tool connection and execution status.
- `requirement`: Conveys requirement definitions, quotes, and validation status.
- `metrics`: Updates the four core metrics (weight, thrust-to-weight, flight time, BOM cost).
- `sim`: Delivers simulation flight trajectory points and pass/fail results.
- `cad`: Emits generated CAD file links, parameter ranges, and scene trees.
- `render`: Provides studio render image URLs.
- `draw`: Overlays visual annotations and guides on 3D scenes.
- `bom`: Publishes the full bill of materials with prices and weights.
- `mascot`: Changes Bolzen's expression state and dialogue bubble.
- `jamie`: Records Jamie API actions and fallback outbox writes.
- `meeting`: Updates meeting entries on the timeline.
- `version`: Attaches completed drone builds to timeline meetings.
- `part`: Announces chosen or considered hardware parts with quotes and warnings.
- `question`: Prompts the user with multiple-choice decisions during contradictions.
- `tasks`: Transmits order task checklists associated with meetings.
- `point`: Directs the 3D pointer indicator to specific model elements.
- `training`: Streams reinforcement learning curves and status from Isaac Lab.

## Environment Variables

Configure environment variables in `agent/.env` or the operating system shell.
Existing shell variables take precedence over `agent/.env`.
Never commit `.env` files or secret keys to the repository.

- `ANTHROPIC_API_KEY`: Activates live Claude tool execution; when unset, the mock story runs.
- `ANTHROPIC_MODEL`: Specifies the Claude model identifier; defaults to `claude-sonnet-5-5`.
- `PAI_FORCE_MOCK`: Set to `1` to force mock story execution even when an API key is present.
- `DEMO_PACE_S`: Introduces pause delays between steps in seconds; defaults to `0`.
- `PORT`: Configures the backend HTTP listening port; defaults to `8100`.
- `JAMIE_MCP_TOKEN`: Bearer token for live Jamie MCP API calls; falls back to local data and outbox when omitted.
- `JAMIE_MCP_URL`: Target endpoint URL for Jamie MCP; defaults to `https://mcp.meetjamie.ai/mcp`.
- `JAMIE_WEBHOOK_SECRET`: Secret token validated against incoming Jamie webhook requests.
- `RESON8_API_KEY`: API key for generating live Reson8 speech-to-text tokens.
- `RESON8_LANGUAGE`: Language code for Reson8 speech-to-text; defaults to `de`.
- `ELEVENLABS_API_KEY`: API key for Bolzen speech generation through ElevenLabs.
- `ELEVENLABS_VOICE_ID`: Custom voice identifier for ElevenLabs audio output.
- `ELEVENLABS_MODEL`: Model identifier for ElevenLabs voice generation; defaults to `eleven_multilingual_v2`.
- `FREECAD_GUI`: Determines FreeCAD execution mode (`auto` connects to open window, `launch` starts app, `off` forces headless).
- `FREECAD_MCP_URL`: Target URL of the FreeCAD MCP RPC server; defaults to `http://127.0.0.1:9875`.
- `PAI_ASK_TIMEOUT_S`: Seconds Bolzen waits for question input before adopting default option; defaults to `20`.
- `RUNPOD_SSH_HOST`: Hostname or IP address of the RunPod GPU pod for Isaac Sim.
- `RUNPOD_SSH_PORT`: SSH port for connecting to RunPod; defaults to `22`.
- `RUNPOD_SSH_USER`: SSH username for RunPod pod; defaults to `root`.
- `RUNPOD_SSH_KEY`: File path to the private SSH key used for RunPod authentication.
- `SMOKE_PORT`: Port assigned to the temporary test server during smoke runs; defaults to `8101`.
- `VITE_API_BASE`: Backend API base URL override for desktop builds.
- `BACKEND_URL`: Proxy destination for Vite development server; defaults to `http://localhost:8100`.

## Integrations and Current State

- Claude tool use: Fully implemented for autonomous drone parameter calculation, part selection, and task execution; mock runner substitutes live calls when keys are missing.
- FreeCAD: Interactive CAD modeling via `freecad-mcp` RPC on port 9875; automatic fallback chain descends to headless `freecadcmd`, then CadQuery.
- Blender: Headless photorealistic studio rendering using EEVEE; falls back to static still render asset if Blender is not installed.
- MuJoCo: Physics-based aerodynamics and downdraft gust stability tests; evaluates altitude thresholds and produces 3D trajectory data.
- Jamie MCP: Connects via Streamable HTTP; writes to local session outbox `jamie_outbox.json` and loads fixture meetings when unauthenticated or offline.
- Reson8: Realtime streaming speech-to-text; vends short-lived session tokens from backend; falls back to browser Web Speech API.
- Tauri app: Desktop wrapper in `desktop/` providing a native macOS window for the web dashboard.
- Vercel static demo: Hosted static deployment at `https://anybuild-demo.vercel.app` replaying recorded event runs without backend dependencies.

## User Interface Guidelines

- The user interface is strictly in German.
- Visual styling follows the Bevel design system with rounded card surfaces, subtle borders, and soft drop shadows.
- Maintain high projector readability on stage using dark ink text variants (`--color-agent-ink`, `--color-ok-ink`, `--color-fail-ink`) and tabular numbers.
- Keep the display uncluttered with essentials only: chat on the left, at most three canvas tabs (`Modell`, `CAD`, `Simulation`), a thin Jamie timeline, and one compact panel with requirement checks and four key numbers.

## Planned Next Work

- Rename remaining user interface elements and repository paths from Bauplan to AnyBuild.
- Connect NVIDIA Omniverse and Isaac Sim on RunPod RTX 4090 to load drone USD files, execute wind tests, run Isaac Lab training, and stream results to a dedicated tab.
- Switch Jamie MCP and Reson8 STT to live production credentials once on-site keys are provided.

## Team Workflow

This project is developed concurrently by two teammates using their own Claude Code sessions on separate machines: Ansorjon Juraev (GitHub user TheWingTheWong) and this agent workspace.
Adhere strictly to the following collaboration rules:

- Work on one dedicated git branch per task.
- Keep pull requests small, focused, and directed into `main`.
- Always pull and rebase against `main` before beginning new implementation.
- Never commit secrets, API keys, or `.env` files.
- Do not reformat or clean up code in files outside your active task scope.
- Coordinate shared files (such as `docs/events.md` and primary layout components) in pull request descriptions.
