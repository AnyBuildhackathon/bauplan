# Architecture

AnyBuild turns a request, a hand sketch or a recorded team meeting into a checked physical product: printed parts in CAD, bought parts with prices, engineering checks, a physics test, a studio render and a bill of materials.
This document explains the components, how data flows between them, how Claude plans and delegates the work, and how the dashboard follows along over one event stream.
The wire format is specified in [events.md](events.md), every endpoint and event is indexed in [API.md](API.md), and every agent tool is described in [TOOLS.md](TOOLS.md).

## Components

```mermaid
flowchart LR
    subgraph Inputs
        U[Chat and voice<br/>typed or spoken]
        S[Hand sketch photo]
        J[Jamie meetings<br/>webhooks and MCP]
    end

    subgraph Web["web/ (React, Three.js, MuJoCo WASM)"]
        UI[Dashboard<br/>chat, timeline, Model, CAD, Simulation]
        BT[Browser training and stress<br/>1,024 MuJoCo worlds]
    end

    subgraph Backend["agent/ (FastAPI, Python 3.12)"]
        API[HTTP API and access gate]
        SES[Session<br/>one bench, build state, versions]
        ORC[Orchestrator<br/>Claude Opus 5.5]
        SUB[Sub-agents<br/>Claude Sonnet 5.5]
        GLV[Gemini Live gateway<br/>WS /api/voice/live]
        REG[Tool registry<br/>51 tools]
        BUS[Event bus<br/>SSE fan-out]
    end

    subgraph External["Engineering tools and services"]
        FC[FreeCAD<br/>GUI over freecad-mcp or headless]
        CQ[CadQuery fallback]
        BL[Blender<br/>Cycles and EEVEE]
        MJ[MuJoCo]
        IS[Isaac Sim and Isaac Lab<br/>GPU host over SSH]
        JM[Jamie MCP]
        R8[Reson8 STT]
        GL[Gemini Live<br/>Vertex gemini-3.8-live]
        WS[Claude web search<br/>live shop prices]
    end

    U --> UI
    S --> UI
    J --> API
    UI -- "POST /api/*" --> API
    API --> SES
    SES --> ORC
    SES --> VOX
    ORC -- delegate --> SUB
    ORC --> REG
    SUB --> REG
    REG --> FC
    REG --> CQ
    REG --> BL
    REG --> MJ
    REG --> IS
    REG --> JM
    REG --> WS
    REG --> BUS
    GLV <--> GL
    BUS -- "GET /api/events (SSE)" --> UI
    UI -- "token" --> R8
    UI <-- "PCM WebSocket" --> GLV
    BT -- "claim and progress" --> API
```

| Component | Where | Role |
| --- | --- | --- |
| HTTP API | `agent/src/pai_agent/app.py` | FastAPI routes, CORS, the access gate (`access.py`), the SSE stream and static file serving. |
| Session | `agent/src/pai_agent/session.py` | The single bench: starts runs, holds the `BuildState` (`state.py`), versions (`versions.py`), open questions and order tasks, and refuses a second build while one runs. |
| Orchestrator | `agent/src/pai_agent/orchestrator.py` | The Claude tool-use loop with Mechanic's system prompt; without `ANTHROPIC_API_KEY` it runs the scripted mock stories through the same tools. |
| Sub-agents | `agent/src/pai_agent/agents.py` | Bounded jobs on a smaller model: CAD scripts, parts, checks, pricing. |
| Tool registry | `agent/src/pai_agent/tools/registry.py` | One schema list and one dispatch for Claude and the mock, with per-tool timeouts (`timeouts.py`). |
| Event bus | `agent/src/pai_agent/bus.py` | In-memory fan-out; a late subscriber gets the backlog, then a `replayed` marker, then live events. |
| Voice | `agent/src/pai_agent/gemini_live.py`, `voice.py` | The Gemini Live gateway (Mechanic's only voice) and Reson8 token vending. |
| Engineering core | `spec.py`, `analysis.py`, `analysis_more.py`, `rigid_sim.py`, `grip_sim.py`, `assembly.py` | Spec validation, closed-form checks, MuJoCo rigid-body tests and the assembly model. |
| CAD runners | `freecad_run.py`, `cad_script.py`, `agent/freecad/` | FreeCAD in the open window over `freecad-mcp`, headless `freecadcmd` in a sandbox, CadQuery as the last fallback. |
| Rendering | `agent/blender/studio.py`, `tools/blender.py` | Headless Blender studio renders of the assembled GLB. |
| Jamie client | `agent/src/pai_agent/jamie_client.py`, `meetings.py` | Streamable HTTP MCP client with a local fixture and outbox fallback. |
| Library and community | `references.py`, `community.py`, `agent/data/references/`, `agent/data/community/` | Known reference builds, saved projects, the published feed and remixes. |
| Cache and warm-up | `cache.py`, `warm.py` | Reuse identical FreeCAD and Blender results and pre-load slow imports at start. |
| Dashboard | `web/src/` | React 19 app: the Zustand store (`events/store.ts`) folds SSE events into UI state; Three.js renders the model, CAD and simulation replays. |
| Mac app | `desktop/` | Tauri 2 window around the same dashboard. |
| GPU experiments | `runpod/`, `tools/isaac.py`, `tools/usd.py` | USD export, Isaac Sim tests and Isaac Lab training on a remote GPU host, see [omniverse.md](omniverse.md). |

## Data flow of one build

1. A request arrives as `POST /api/prompt` (typed or spoken), `POST /api/sketch` (photo), `POST /api/library/{id}/open` (reference), `POST /api/community/{id}/remix` (remix) or `POST /api/webhooks/jamie` (a meeting ended).
2. `app_control.py` answers pure dashboard commands ("show me the CAD", "pull it apart") at once with `ui_control` calls, without a model call.
3. Everything else starts a run in the session; the HTTP call returns immediately with `status: started`.
4. The orchestrator writes one short sentence per step, then calls tools; every tool result is also published as events (`tool`, `cad`, `sim`, `requirement`, `metrics`, `bom`, and more).
5. When a check fails, the orchestrator changes a parameter with `cad_update` or swaps a part, and every check that ran before runs again.
6. The run ends with a render, a bill of materials, and for meeting-driven builds a version attached to the meeting with the difference written back to Jamie.
7. The dashboard never polls: it renders whatever the event stream says, so a reconnecting client replays the backlog onto an empty state.

```mermaid
sequenceDiagram
    participant User
    participant Web as Dashboard
    participant API as FastAPI
    participant Orc as Orchestrator (Opus)
    participant Sub as Sub-agents (Sonnet)
    participant Tools as FreeCAD / MuJoCo / Blender
    participant Jamie

    User->>Web: "Design a phone stand under 6 euros"
    Web->>API: POST /api/prompt
    API-->>Web: {status: started}
    API->>Orc: run_prompt
    Orc->>Tools: product_spec (validated by spec.py)
    par CAD agents, one per printed part
        Orc->>Sub: cad_part script
        Sub->>Tools: freecadcmd (sandboxed)
    end
    Orc->>Sub: delegate parts (part_pick)
    Orc->>Sub: delegate checks (check_*, simulate_assembly)
    Sub-->>Orc: report with pass and fail
    Orc->>Tools: cad_update on a failed check
    Orc->>Tools: blender_render, bom_build
    Orc->>Jamie: version_commit, jamie_create_tasks
    Tools-->>Web: SSE events (cad, sim, requirement, metrics, bom, version)
```

## Orchestrator and sub-agents

Claude works like a lead engineer with a small team.
The orchestrator (Claude Opus 5.5 by default, effort `high`, configurable up to `max`) plans the build, writes the spec, decides the fixes and reviews every report.
It delegates bounded jobs to sub-agents on a smaller model (Claude Sonnet 5.5 by default), each with only the tools its job needs:

| Sub-agent | Tools | Job |
| --- | --- | --- |
| CAD agent | FreeCAD script writer behind `cad_part` | Writes one printed part's FreeCAD Python; several parts run side by side. |
| Parts agent | `part_pick` | Binds every bought part to a catalog entry, or an honest estimate marked as such. |
| Analysis agent | `assemble`, `check_totals`, `check_tip_over`, `check_deflection`, `check_torque`, `check_runtime`, `simulate_assembly` | Runs every check the requirements name with honest loads and reports pass or fail with numbers. |
| Pricing agent | `part_pick`, `bom_build` | Builds and prices the bill of materials and swaps estimates for catalog parts where one fits. |

With delegation on, `part_pick`, `simulate_assembly` and the `check_*` tools belong to the sub-agents and the orchestrator reaches them through the `delegate` tool (`DELEGATED` in `tools/registry.py`).
Known gap: `check_power`, `check_thermal` and `check_rollover` are in `DELEGATED` but not in the analysis agent's tool list, so with delegation on neither agent can call them; `PAI_DELEGATION=0` makes them available to the orchestrator.
Every agent streams as an `agent` event with role, model, effort, job, status, rounds, tokens and cost, and shows up as its own card in the chat.
Models, effort and delegation are set with `PAI_ORCHESTRATOR_MODEL`, `PAI_ORCHESTRATOR_EFFORT`, `PAI_SUBAGENT_MODEL`, `PAI_SUBAGENT_EFFORT` and `PAI_DELEGATION`, or at runtime from the settings button in the top bar (`/api/settings`).
A third, fast model (Claude Haiku 5.5, `ANTHROPIC_VOICE_MODEL`) only writes the learning-mode explanations, and it may only use numbers that are in the facts it was given.

### Honesty rules

The orchestrator prompt forbids claiming a pass, a price or a number that a tool did not produce.
Prices carry a `price_source` of `live`, `catalog` or `estimate`, and the dashboard marks each one.
Recorded GPU results say `source: recorded` and are never presented as a test of the current product.
When a generated CAD script fails three times, a plain block stands in and is clearly marked, so a live build never ends without geometry.

## Any product: the generic flow

AnyBuild builds whatever physical product a team describes; the drone and the robot gripper are worked examples with their own flows.
For any other product Claude drives the bench through these tools:

1. `product_spec`: Claude writes the spec (function, requirements each with the check that judges it and a limit, and every printed part, bought part and external load); `agent/src/pai_agent/spec.py` validates it and lists every problem at once until it is right.
2. `cad_part` per printed part: Claude writes the FreeCAD script, `freecadcmd` builds it headless and sandboxed, and the geometry is checked against the part's envelope; failed scripts go back to Claude with the error.
3. `part_pick` per bought part: catalog parts from `agent/data/catalogs/` (hobby electronics, motors, fans, pumps, batteries, servos, hardware, plus the drone and gripper catalogs), or an honest estimate; live shop prices plug in through `pai_agent.pricing.register_provider`.
4. `assemble`: one model with mass, cost, centre of mass, size and footprint, and warnings for parts that float.
5. Checks against the requirements: `check_totals`, `check_tip_over`, `check_deflection`, `check_torque`, `check_runtime`, `check_power`, `check_thermal`, `check_rollover`, and `simulate_assembly` (a MuJoCo push or drop test of the whole assembly, replayed with the real model in the Simulation tab).
6. On a fail Claude changes a parameter with `cad_update` (rebuild, reassemble and rerun every check) or swaps a part, and says why.
7. `blender_render` and `bom_build`, then optionally `build_guide` and `firmware`.

The math behind each check is in `agent/src/pai_agent/analysis.py`, `analysis_more.py` and `rigid_sim.py`.
The dashboard renders any product from the spec and the check results: requirement rows with the measured value, key-number cards, the assembly tree, per-part parameter sliders in the CAD tab (moving one reruns the checks without a model call), the before and after MuJoCo replay, and a bill of materials with sample, estimated and live prices marked.

### Starting points

- **From scratch:** any typed or spoken description.
- **From a sketch:** `POST /api/sketch` stores the photo, `sketch_to_spec` reads it with Claude vision (every dimension with value, unit and confidence), and the orchestrator continues with `product_spec`.
- **From a reference:** the library (`agent/data/references/`) holds known products with their real parts; loading one rebuilds it through the same tools, then the user changes it in the chat.
- **From the community:** a published project is remixed on a fresh bench with a link back to the original.
- **From a meeting:** a Jamie `meeting.ended` webhook builds from that meeting's requirements.

The library (`GET /api/library`) lists the micro FPV drone first and the robot gripper second, both built by their own code, then the reference builds and the projects users saved with `POST /api/library`.
Each saved or reference build is one `reference.json` with the spec, the picks and the checks, one FreeCAD script per printed part, and a studio render as thumbnail.
A reference is rebuilt and rechecked through the same tools without a key, and the user then changes it in the chat, for example "make it hold a 480 g tablet", and live Claude reworks it.
The community feed (`GET /api/community`) shows published projects with render, author, key numbers and remix count, searchable and sorted by new or popular.
Publishing shares the bench with its spec, parts, CAD files, renders and versions; a remix opens a published project on a fresh bench with a link back to the original, and publishing the remix counts toward the original's remixes.
`agent/scripts/seed_community.py` seeds the feed from the library builds with their real numbers.

## The robot gripper worked example

The second built-in product is a parametric two-finger robot gripper, chosen because it has moving parts, a real physics question (does it hold the object while the arm moves?) and a parts choice that changes the CAD.
`product_brief` turns the request into checks, `catalog_search` picks servo, pads, hardware and driver from `agent/data/catalogs/gripper.json`, `grip_calc` computes finger force and grip safety, `simulate_grip` lifts and shakes the object in MuJoCo, and `cad_part` builds the gripper from `agent/freecad/library/gripper.py` with the servo pocket sized for the chosen servo, then `blender_render` and `bom_build`.
In the mock, the SG90 servo drops the can and the MG996R holds it.

## The drone worked example and Jamie loop

The stage demo builds a 1S 2-inch toothpick FPV drone from two recorded meetings.
It arrives at a real reference build, the toothpick from Mediocre Nerd's video "Build a Micro FPV Drone for $59": Twiglet 2" carbon frame, 1103 15000KV motors, Gemfan 2020 four-blade props, Caddx Ant camera, BetaFPV Matrix 1S 5in1 V2 AIO, canopy with battery holder, M1.4 bolts and a 1S pack.
Each is a bill-of-materials line with its mass, its shop price checked on 2026-10-24 and the product page of that exact part (`agent/data/parts.json`).
The kickoff meeting builds version 1: requirements from Jamie, a warning from an earlier workshop note about the FunFly 4S battery, a MuJoCo hover test that a downdraft gust pushes to the ground, the swap to the Tattu R-Line 1S 550, the frame in FreeCAD, the studio render in Blender, the bill of materials, order tasks and the version attached to the meeting (47.2 g, 8.5 min, 117.38 EUR).
The review meeting builds version 2: Mechanic asks which flight time counts when the review contradicts the kickoff, swaps to the BetaFPV LAVA II 1S 680 for 10 minutes, and writes the difference back to Jamie as a note (48.4 g, 10.4 min, 117.60 EUR).

Jamie is the sensory backbone of this loop:

- `jamie_templates` creates the summary templates "Hardware-Anforderungen" and "Drohnen-Review".
- `jamie_requirements` reads the template fields with quote, speaker and timestamp, then the meeting's requirement list, then transcript sentences.
- `jamie_search` surfaces warnings from earlier meetings before a part is chosen.
- `jamie_meeting` reads a review: changed requirements, contradictions with earlier meetings, and part complaints, resolving "last week" to meetings 4 to 10 days earlier.
- `ask_user` lets Mechanic ask the room a multiple-choice question when meetings contradict each other.
- `version_commit` writes the design difference back as a note and tags the meeting with `drohne` and `drohne-v{n}`.
- `jamie_create_tasks` creates one order task per bill-of-materials line with an assignee and due date; ticking a part as ordered in the dashboard ticks the task in Jamie.

With `JAMIE_MCP_TOKEN`, calls go live to `https://mcp.meetjamie.ai/mcp`; without it, or when a live call fails, the same methods answer from the fixture meetings in `agent/data/meetings/` and writes go to the session outbox `jamie_outbox.json`.
The dashboard looks the same in both modes; chat cards say "local outbox" when offline.

## CAD pipeline

```mermaid
flowchart TD
    A[cad_frame or cad_part] --> B{FreeCAD window with<br/>freecad-mcp on :9875?}
    B -- yes --> C[Build visibly, stage by stage,<br/>then export and snapshot]
    B -- no or timeout --> D{freecadcmd installed?}
    D -- yes --> E[Headless run in a fresh temp dir,<br/>import allowlist, sandbox-exec, 60 s timeout]
    D -- no or failure --> F[CadQuery fallback]
    C --> G[STEP, STL, GLB, FCStd,<br/>mass and bounding box]
    E --> G
    F --> G
    G --> H[cad event: Model and CAD tabs]
```

- `cad_frame` builds the full drone from `agent/freecad/frame_build.py`: the Twiglet carbon X-frame (weighed by FreeCAD at carbon-plate density), 1103 motors, Gemfan 2020 props, the AIO flight controller, the canopy and camera from downloaded open models, battery, strap and antenna, each its own GLB node with PBR materials.
- `cad_part` builds any part from a description: Claude writes FreeCAD Python, the script is checked before it runs (only `FreeCAD`, `Part` and `math` imports, no file access), runs headless in a fresh temp directory without the backend's environment, and on macOS `sandbox-exec` blocks network access and writes outside that directory.
  A failed script returns to Claude with the error, up to three attempts.
- Identical inputs reuse earlier results from `agent/runs/cache/` (`PAI_CACHE=0` turns that off).
- In the open FreeCAD window, `cad_frame` builds stage by stage (frame, motors, propellers, flight controller, canopy and camera, battery and strap, antenna), exports, and captures a viewport snapshot; the chat shows each stage, and a step that does not answer within 12 seconds falls back to headless `freecadcmd`.

### Drone model and studio render

The Twiglet carbon X-frame is a unibody plate with rounded arms, motor pads and lightening slots; FreeCAD weighs it at carbon-plate density (5.2 g against the 5.3 g listing) and that mass replaces the catalog figure.
The canopy and the camera are downloaded open models of the real parts, used 1:1 from `agent/freecad/parts/` (DLQFPV's toothpick canopy, CC BY 4.0, and Youfu's Caddx Ant Lite, CC0); no openly licensed model exists of the frame, motors, props or AIO board, so those are remodeled from published dimensions (see [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)).
The GLB carries real materials: a generated 2x2 twill carbon weave under a clear coat, black anodized motor bells with copper windings, clear grey polycarbonate props, a green solder-mask board with chips and passives, and black TPU for the canopy.
The build writes `frame.FCStd` (the assembly), `frame.step` and `frame.stl` (the X-frame), `drone.step` (the assembly) and `frame.glb` (one node per scene target), which the Model and CAD tabs show.
`blender_render` renders that GLB headless on a workbench scene like the reference photo of the build: a green cutting mat with a 10 mm grid, an overhead panel, a desk lamp and a rim light, path-traced in Cycles (Metal GPU when available) at 1600 x 900.
Without a GLB (the CadQuery fallback) the studio places simple parts around the frame STL in EEVEE, and without Blender the recorded still is served.
- `POST /api/cad/params` reruns the same script with new slider values without a model call, and `POST /api/cad/open` opens the current model in the FreeCAD app.

## Simulation and training

- **Closed-form checks** (`analysis.py`, `analysis_more.py`): totals, tip-over angle and push, beam deflection and stress safety, torque margin, battery runtime, power headroom, enclosure temperature and vehicle roll-over.
- **MuJoCo on the backend:** `simulate_drone` (hover with a downdraft gust), `simulate_assembly` (push or drop test of any assembly as one rigid body with the real centre of mass) and `simulate_grip` (lift and shake for the gripper).
- **MuJoCo in the browser:** `train_in_browser` tunes the controller across 1,024 simulations (64 candidates over 16 generations, evolution strategy) and `stress_test` flies the result in 50 randomized worlds; the backend queues the job, one dashboard tab claims it through `/api/training/*` or `/api/stress/*`, and progress returns as `training` and `stress` events.
- **NVIDIA Isaac Sim and Isaac Lab:** `product_usd` exports the assembly as USD, `isaac_test` runs wind, payload or hover experiments and `isaac_train` trains the reference Crazyflie task on a GPU host over SSH; without a host, a clearly labelled recorded result stands in.

## Voice loop

Gemini Live is Mechanic's only voice; without it Mechanic answers in text.
The backend proxies native audio through Vertex AI with gcloud user OAuth or AI Studio with a server-only key.
Gemini calls Claude for engineering and the existing app controls for navigation, and its own transcription of both sides feeds the chat and logbook; Reson8 is not part of the voice conversation.
Gemini output plays through Web Audio and drives the mascot's lip-sync.
Mechanic speaks only inside a voice conversation the person started with **Talk** in the chat input: he answers them, plus at most one short line when a build finishes, and never narrates build progress.
See [realtime voice](GEMINI_LIVE.md) for configuration, protocol, transcript ownership and measured latency.

```text
mic -16 kHz PCM-> WS /api/voice/live -> Gemini Live (gemini-3.8-live, Fenrir) -> 24 kHz PCM -> Web Audio + lip-sync
                                             +-> input and output transcription -> chat and logbook
                                             +-> engineer / control_app / product_state -> Claude and the dashboard
```

- **Listening:** Gemini Live's voice detection and transcription hear the conversation.
- **Push-to-talk dictation:** with `RESON8_API_KEY`, the browser streams 16 kHz PCM to Reson8's Realtime endpoint while the key is held, with a short-lived token from `POST /api/voice/token` and a phrase list for the domain vocabulary (`PHRASES` in `voice.py`); the API key never leaves the backend.
- **Speaking:** only Gemini Live speaks, natively, with the prebuilt voice `Fenrir` (`GEMINI_LIVE_VOICE` overrides it); chat lines, mascot bubbles and questions are never read aloud.
- **Persona:** Mechanic is self-assured and witty, may swear mildly when it fits, never at the person, and stays honest: no claimed pass, price or number that a tool did not produce.
- **Lip-sync:** `useSpeech` in `web/src/lib/speech.ts` measures the audio level every frame and drives the mascot's mouth while Mechanic speaks.
- **Barge-in:** Gemini's voice detection interrupts Mechanic the moment the person talks.
- Fallbacks: without Reson8, push-to-talk uses the browser's Web Speech recognition; without Gemini Live there is no voice conversation, and Mechanic answers typed messages in text.

## Event stream

The backend publishes every state change as one JSON object on `GET /api/events`.
Every stream starts with `reset`, then the backlog, then a `replayed` marker, then live events, with `: keepalive` comments every 15 seconds.
The web store (`web/src/events/store.ts`) folds events into UI state.
The 33 event types and their payloads are listed in [API.md](API.md#server-sent-events) and specified in [events.md](events.md#sse-events).

## Mock mode and fallbacks

Every external dependency has a fallback, so the full workflow runs on a laptop without keys:

| Missing | Fallback |
| --- | --- |
| `ANTHROPIC_API_KEY` | Scripted mock stories (`mock_story.py`, `mock_product.py`, `mock_gripper.py`, `mock_categories.py`) call the same tools with the same events. |
| `JAMIE_MCP_TOKEN` | Fixture meetings in `agent/data/meetings/` and the local outbox `jamie_outbox.json`. |
| `RESON8_API_KEY` | Push-to-talk uses browser Web Speech recognition; typing always works. |
| Gemini Live (`GOOGLE_CLOUD_PROJECT` with gcloud, or `GEMINI_API_KEY`) | Mechanic stays silent and shows text; the microphone still dictates. |
| FreeCAD window | Headless `freecadcmd`, then CadQuery. |
| Blender | The recorded still `agent/runs/fallback/render.png`. |
| GPU host for Isaac | A recorded, clearly labelled result. |
| Live shop prices | Catalog sample prices with their check date, or marked estimates. |

## Security model of the public backend

The public web app on Vercel talks to the backend on the team's Mac through Tailscale Funnel.
`ANYBUILD_ACCESS_CODE` gates every route except `GET /api/health` and `POST /api/access`; sessions are bearer tokens or an `HttpOnly` cookie valid for 24 hours.
Wrong codes are rate limited per IP, and builds, speech, speech-to-text tokens, CAD recomputes and explanations have hourly limits per session and per IP.
State-changing calls without a typed body require `Content-Type: application/json`, and CORS allows only localhost, the Mac app and the Vercel deployments.
Generated CAD scripts run sandboxed as described above, and `/files/` serves only single path segments inside the session directory.

## Repository layout

| Path | Contents |
| --- | --- |
| `agent/src/pai_agent/` | Backend package: API, session, orchestrator, sub-agents, engineering core, voice. |
| `agent/src/pai_agent/tools/` | The 51 agent tools, see [TOOLS.md](TOOLS.md). |
| `agent/freecad/` | FreeCAD build scripts, the part harness, parametric library parts and downloaded part models. |
| `agent/blender/` | The Blender studio scene script. |
| `agent/data/` | Part catalogs, reference builds, community seeds, meeting fixtures, webhook samples, the sample sketch. |
| `agent/scripts/` | Smoke tests, the demo recorder, profiling and seeding scripts. |
| `agent/tests/` | Pytest unit tests. |
| `web/src/` | Dashboard: `events/` (store, SSE source, types), `components/`, `views/`, `sim/` (MuJoCo WASM). |
| `web/e2e/` | Playwright end-to-end tests. |
| `desktop/` | Tauri 2 Mac app. |
| `runpod/` | Isaac Sim and Isaac Lab setup and job scripts. |
| `docs/` | This documentation. |
