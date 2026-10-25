# AnyBuild

AnyBuild is a general physical-AI engineering agent for developing physical products.
It turns a typed or spoken request, with its requirements and constraints, into validated CAD models, physics simulations, and bills of materials.
The project was originally named Bauplan and code references still reflect that name in places.
It is built for the {Tech: Europe} Agentic AI Hack Berlin on 2026-10-24.
Partners include Jamie, Reson8, and Anthropic.
Live demos take place on a projector at 20:00, with an opt-in deadline at 19:00 and project submission at 18:30.
The team hackathon roadmap, timeline, and workstreams are documented in docs/PLAN.md.

## Product Concept

AnyBuild is designed as a universal physical-AI engineer for diverse hardware domains.
In the general workflow, the user describes any physical product in the chat and the agent autonomously specs, designs, simulates, and sources it.
The agent takes the requirements from the user's own words, labels any limit it proposes itself as proposed by Mechanic, and tracks design revisions over time.
Claude plans the engineering steps and invokes real domain software tools.
Parametric CAD tools build 3D components with exact geometric dimensions.
Physics and aerodynamic simulators validate real-world performance against environmental forces.
Rendering tools produce photorealistic studio visualizations for team review.
Bill of materials calculators price orderable parts and group the order by shop.
The voice agent is Gemini Live only: it listens, transcribes and speaks as mascot Mechanic inside a voice conversation the user starts, and without it Mechanic stays silent, showing text.
Reson8 speech-to-text powers push-to-talk dictation.
Offline fallbacks run the complete workflow when API keys are absent.

## Worked Demo Example: Drone Design

For the hackathon stage demonstration, AnyBuild implements a complete end-to-end worked example for racing drone design.
The current codebase implements drone-specific part catalogs, aerodynamic wind testing in MuJoCo, and a parametric quadcopter frame in FreeCAD.
The stage demo begins with a typed drone request that builds drone version 1 to the user's limits.
In the offline demo the agent first tries the FunFly 4S battery, fails an initial downdraft test in MuJoCo, and switches to the Tattu R-Line 1S 550 pack.
FreeCAD builds the frame visibly in an open window, with headless FreeCAD and CadQuery fallbacks.
Blender renders the assembled drone in a virtual studio environment.
MuJoCo simulates drone flight stability against wind gusts.
AnyBuild extracts real measurements: CAD weight, thrust-to-weight ratio, flight time, stability pass/fail, and bill of materials cost.
Every requirement and every part links to the words from the user's request behind it, or is marked as proposed by Mechanic.
A typed change such as "Make it fly 10 minutes" revises the requirement and swaps to the BetaFPV LAVA II 1S 680 pack.
AnyBuild rebuilds to version 2, showing metrics differences and quotes.
The public web app is at https://anybuild-demo.vercel.app and talks to the live backend.

## Repository Map

The repository is structured into five main directories:

- `agent/`: Python backend, Claude tool definitions, physics simulation, and CAD generation.
  - `agent/src/pai_agent/app.py`: FastAPI application server, SSE event stream, and HTTP endpoints.
  - `agent/src/pai_agent/session.py`: Session orchestrator managing events, tool execution, and mock flow.
  - `agent/src/pai_agent/mock_story.py`: Deterministic fallback mock runner for version 1 and version 2 drone builds from typed requests.
  - `agent/src/pai_agent/orchestrator.py`: Claude tool-use execution loop.
  - `agent/src/pai_agent/tools/`: Tool definitions for CAD, MuJoCo simulation, Blender, BOM, and UI interaction.
  - `agent/src/pai_agent/freecad_run.py`: FreeCAD MCP RPC connector and headless fallback execution.
  - `agent/src/pai_agent/voice.py`: Reson8 STT token management and voice capabilities.
  - `agent/scripts/smoke_sse.py`: End-to-end SSE mock verification script.
- `web/`: Vite, React, and Three.js frontend dashboard.
  - `web/src/App.tsx`: Top-level application layout containing chat, timeline, canvas, and panels.
  - `web/src/events/store.ts`: Zustand event store for SSE updates, metric tracking, and version state.
  - `web/src/events/source.ts`: SSE stream consumer.
  - `web/src/events/types.ts`: TypeScript interfaces for the wire protocol.
  - `web/src/components/chat/`: Mechanic sidebar chat with audio controls and speech recognition.
  - `web/src/components/canvas/`: 3D canvas tabs for model visualization, CAD views, and simulation.
  - `web/src/components/panels/`: Shared source pieces (quote citation); requirements and results are cards in the chat.
  - `web/src/views/`: Primary views including workbench, logbook, and training tabs.
- `desktop/`: Tauri 2 native desktop application wrapper.
  - `desktop/src-tauri/`: Tauri Rust backend configuration and window lifecycle handlers.
  - `desktop/package.json`: Build commands for native macOS app bundles.
- `docs/`: Technical specifications.
  - `docs/events.md`: Authoritative wire format contract for HTTP and SSE communication.
  - `docs/PLAN.md`: Day plan, workstream allocations, submission timeline, and tool stack.
  - `docs/TEAMMATE_PROMPTS.md`: Copy-paste task prompts and port configurations for teammate agent sessions.
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

### Mock Mode Triggers

Without an Anthropic key and without a logged-in local Claude Code (`PAI_LLM_PROVIDER=auto`, the default), the backend runs in mock mode automatically; `PAI_FORCE_MOCK=1` forces it.
Trigger the first drone build with a typed request:

```bash
curl -s -X POST http://127.0.0.1:8100/api/prompt -H 'content-type: application/json' --data '{"text":"Build a micro drone under 120 euros with at least 8 minutes of flight time, under 50 g."}'
```

Trigger the version 2 rebuild with a typed change:

```bash
curl -s -X POST http://127.0.0.1:8100/api/prompt -H 'content-type: application/json' --data '{"text":"Make it fly 10 minutes."}'
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

### URL Parameters

The frontend accepts URL parameters to set the initial view:

- `?mute`: Disables audio synthesis playback on initial load.
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
- `POST /api/reset`: Resets session state and event history.
- `POST /api/answer`: Submits answers to mascot Mechanic's clarification questions.
- `POST /api/cad/params`: Recomputes frame parameters dynamically.
- `POST /api/cad/open`: Launches FreeCAD GUI with the current CAD file.
- `GET /api/voice`: Returns speech-to-text capabilities and Gemini Live availability.
- `POST /api/voice/token`: Generates short-lived Reson8 STT authorization tokens.
- `WS /api/voice/live`: Gemini Live realtime voice conversation, Mechanic's only voice.
- `GET /api/health`: Reports server status and mock mode flag.
- `GET /files/{bucket}/{name}`: Serves generated CAD assets, renders, and videos.

### SSE Event Types

The event stream emits typed JSON objects:
- `reset`: Clears all client-side session state.
- `replayed`: Delimits backlog replay from live streaming events.
- `step`: Notifies workflow step transitions (`meeting`, `teile`, `cad`, `render`, `simulation`, `training`, `stueckliste`).
- `chat`: Carries user or agent chat utterances.
- `tool`: Updates tool connection and execution status.
- `requirement`: Conveys requirement definitions, the request quote or Mechanic's proposal (`source`), and validation status.
- `metrics`: Updates the four core metrics (weight, thrust-to-weight, flight time, BOM cost).
- `sim`: Delivers simulation flight trajectory points and pass/fail results.
- `cad`: Emits generated CAD file links, parameter ranges, and scene trees.
- `render`: Provides studio render image URLs.
- `draw`: Overlays visual annotations and guides on 3D scenes.
- `bom`: Publishes the full bill of materials with prices and weights.
- `mascot`: Changes Mechanic's expression state and dialogue bubble.
- `version`: Records each completed build with its trigger, numbers and difference from the last version.
- `part`: Announces chosen hardware parts with the request quote behind them.
- `question`: Prompts the user with multiple-choice decisions, for example a requirement the design cannot meet.
- `point`: Directs the 3D pointer indicator to specific model elements.
- `training`: Streams reinforcement learning curves and status from Isaac Lab, or from the 1,024 browser MuJoCo simulations (`source: "browser"`).

## Environment Variables

Configure environment variables in `agent/.env` or the operating system shell.
Existing shell variables take precedence over `agent/.env`.
Never commit `.env` files or secret keys to the repository.

- `ANTHROPIC_API_KEY`: Activates live Claude tool execution; when unset, the local Claude Code subscription runs if logged in (`PAI_LLM_PROVIDER`: `auto`, `api` or `subscription`), else the mock story.
- `ANTHROPIC_MODEL`: Specifies the orchestrator's Claude model identifier when `PAI_ORCHESTRATOR_MODEL` is unset; defaults to `claude-opus-5-5`.
- `PAI_FORCE_MOCK`: Set to `1` to force mock story execution even when an API key is present.
- `DEMO_PACE_S`: Introduces pause delays between steps in seconds; defaults to `0`.
- `PORT`: Configures the backend HTTP listening port; defaults to `8100`.
- `RESON8_API_KEY`: API key for generating live Reson8 speech-to-text tokens.
- `RESON8_LANGUAGE`: Language code for Reson8 speech-to-text; defaults to `de`.
- `GEMINI_LIVE_MODEL`: Gemini Live model for Mechanic's voice; defaults to `gemini-3.8-live`.
- `GEMINI_LIVE_VOICE`: Gemini Live prebuilt voice; defaults to `Fenrir`.
- `FREECAD_GUI`: Determines FreeCAD execution mode (`auto` connects to open window, `launch` starts app, `off` forces headless).
- `FREECAD_MCP_URL`: Target URL of the FreeCAD MCP RPC server; defaults to `http://127.0.0.1:9875`.
- `PAI_ASK_TIMEOUT_S`: Seconds Mechanic waits for question input before adopting default option; defaults to `20`.
- `PAI_TIMEOUT_<TOOL>`: Time limit in seconds for one tool call (for example `PAI_TIMEOUT_BLENDER_RENDER=60`), `0` for none; defaults per tool in `agent/src/pai_agent/timeouts.py`, `PAI_TOOL_TIMEOUT_S` (default `120`) for the rest.
- `PAI_MODEL_TIMEOUT_S`: Seconds a streamed orchestrator model round may go without any progress before the run stops with a message; defaults to `90`. `PAI_MODEL_ROUND_MAX_S` (default `600`) caps the whole round.
- `PAI_CACHE`: Set to `0` to turn off reusing identical FreeCAD and Blender results from `agent/runs/cache/`.
- `PAI_WARM`: Set to `0` to skip warming CadQuery, MuJoCo, the Anthropic SDK, FreeCAD and Blender at server start.
- `E2E_LIVE`: Set to `1` for the live Playwright smoke (`npm run e2e:live`), which needs `ANTHROPIC_API_KEY` on the backend.
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
- Reson8: Realtime streaming speech-to-text; vends short-lived session tokens from backend; falls back to browser Web Speech API.
- Tauri app: Desktop wrapper in `desktop/` providing a native macOS window for the web dashboard.
- Vercel: Hosts the web app at `https://anybuild-demo.vercel.app`, which talks to the live backend.

## User Interface Guidelines

- The user interface is strictly in English.
- The captain owns visual styling and design polish; agents must not make visual design changes beyond what their task requires.
- Visual styling follows the Bevel design system with rounded card surfaces, subtle borders, and soft drop shadows.
- Maintain high projector readability on stage using dark ink text variants (`--color-agent-ink`, `--color-ok-ink`, `--color-fail-ink`) and tabular numbers.
- Keep the display uncluttered with essentials only: chat on the left, at most three canvas tabs (`Model`, `CAD`, `Simulation`), partner status chips in the top bar, versions in the Logbook, and the requirement checks and three key numbers as cards in the chat.

## Planned Next Work

- Generalize beyond drones: generalize CAD generation for arbitrary product classes, expand hardware component catalogs, and support flexible multi-physics simulation domains.
- Integrate teammate modules: physics stress testing, step-by-step exploded build guide, and firmware download with wiring table.
- Rename remaining repository paths and package identifiers from Bauplan to AnyBuild. The user-visible name is already AnyBuild, and the interface and agent dialogue are already English.
- Connect NVIDIA Omniverse and Isaac Sim on RunPod RTX 4090 to load drone USD files, execute wind tests, run Isaac Lab training, and stream results to a dedicated tab.
- Switch Reson8 STT to live production credentials once on-site keys are provided.

## Team Workflow

This project is developed concurrently by two teammates using their own Claude Code sessions on separate machines: Ansorjon Juraev (GitHub user TheWingTheWong) and this agent workspace.
Adhere strictly to the following collaboration rules:

- Work on one dedicated git branch per task.
- Keep pull requests small, focused, and directed into `main`.
- Always pull and rebase against `main` before beginning new implementation.
- Never commit secrets, API keys, or `.env` files.
- Do not reformat or clean up code in files outside your active task scope.
- Coordinate shared files (such as `docs/events.md` and primary layout components) in pull request descriptions.

### Git Worktree Recipe

Use git worktrees to keep parallel tasks completely isolated without duplicate full clones.
Pre-configured worktrees, prompts, and port pairs for teammate tasks are listed in docs/TEAMMATE_PROMPTS.md.
Clone the repository once to your machine.
Before starting a new task, fetch the latest default branch:

```bash
git fetch origin main
```

Create a fresh worktree and branch for the task:

```bash
git worktree add ../bauplan-<task> -b <name>/<task> origin/main
```

Launch one independent Claude session inside that worktree directory.
Implement and test the changes within that worktree.
Push the branch and open a pull request directed into `main`.
After the pull request is merged, delete the branch and remove the worktree:

```bash
git worktree remove ../bauplan-<task>
```

### Port Allocation for Parallel Sessions

Parallel servers running across worktrees must use distinct ports to avoid bind collisions.
Assign each active worktree a unique port pair, such as 8102/5182 or 8103/5183.
Start the backend with an explicit `PORT`:

```bash
cd agent && PORT=8102 uv run physical-ai-agent
```

Start the web dashboard with `BACKEND_URL` and `--port`:

```bash
cd web && BACKEND_URL=http://localhost:8102 npm run dev -- --port 5182
```
