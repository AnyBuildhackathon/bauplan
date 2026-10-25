# AnyBuild

![AnyBuild workbench cube](docs/assets/anybuild-social.png)

**An engineering agent that develops physical products from what you ask for.**

AnyBuild takes what you ask for, typed in the chat or said by voice, and turns it into a checked design.
Claude plans the work like a lead engineer with a small team of sub-agents and drives real engineering software through tool use: FreeCAD builds the parts, MuJoCo tests them, Blender renders them, and a bill of materials prices every orderable part.
Every requirement comes from your own words and links back to them; a limit you did not give is marked as proposed by Mechanic, and every change builds a new version with its difference.
It targets diverse physical products, from a phone stand to a plant-watering robot; the micro FPV drone is the worked example of our stage demo.

- **Live app:** https://anybuild-demo.vercel.app (the real app on our live backend; the access code is shared with the jury separately).
- **Built at:** {Tech: Europe} Agentic AI Hack Berlin, 2026-10-24.
- **Partner technology:** Anthropic Claude, Reson8 (see [Partner technology](#partner-technology)).
- **Documentation:** [Architecture](docs/ARCHITECTURE.md), [API](docs/API.md), [Agent tools](docs/TOOLS.md), [Frameworks](docs/FRAMEWORKS.md), [Event contract](docs/events.md).

![The workbench: chat with Mechanic on the left, the assembled drone in the Model tab](docs/assets/screenshots/workbench-model.jpg)

| CAD tab: FreeCAD assembly, feature tree and live parameters | Simulation tab: MuJoCo hover test before and after a fix |
| --- | --- |
| ![CAD tab](docs/assets/screenshots/workbench-cad.jpg) | ![Simulation tab](docs/assets/screenshots/workbench-simulation.jpg) |

## What it does

- **Any product from a description or a sketch.** Type or say what you need, upload a photo of a hand sketch, start from a reference build, or remix a community project.
- **Spec with traceable requirements.** Claude writes a full product spec; every requirement names the check that judges it, its limit, and the words from your request it came from, or is marked as proposed by Mechanic.
- **Real CAD.** Claude writes FreeCAD Python for every printed part; FreeCAD builds it visibly in the open window or headless in a sandbox, with STEP, STL, GLB and a live feature tree and parameter sliders.
- **Real parts.** Bought parts come from curated catalogs with shop links and checked prices, or live shop prices through Claude web search; estimates are marked as estimates.
- **Engineering checks and physics.** Mass, cost, size, tip-over, deflection, torque, runtime, power, thermal and roll-over checks, plus MuJoCo push, drop, hover and grip tests replayed in 3D.
- **Fix loop.** When a check fails, Claude changes a dimension or swaps a part, rebuilds and reruns every check, and says why.
- **Versions.** Every change you ask for builds a new version with its difference in weight, price, parts and checks; an old version can be restored or compared.
- **Talk to Mechanic.** One button: press **Talk** and Mechanic greets you, then you just speak, and **End** turns him off; Gemini Live (`gemini-3.8-live`, voice Fenrir) is the whole voice agent: it listens, transcribes and speaks as Mechanic, with barge-in, while Claude handles engineering.
  Mechanic never narrates on his own: he answers you, plus one short line when a build finishes, and without Gemini Live he answers in text.
  [Setup and measured latency](docs/GEMINI_LIVE.md).
- **Orchestrator and sub-agents.** Claude Opus 5.5 plans and reviews; Claude Sonnet 5.5 sub-agents write CAD scripts in parallel, pick parts, run checks and price the bill of materials, each visible as its own card with tokens and cost.
- **Controller training in the browser.** 1,024 MuJoCo simulations tune the drone's or gripper's controller, and a 50-world stress test reports robustness; optional NVIDIA Isaac Sim and Isaac Lab runs on a GPU host.
- **Deliverables.** Studio render, bill of materials (CSV and order list per shop), step-by-step build guide, Betaflight or Arduino firmware with wiring table, and one ZIP with everything.
- **Library and community.** Reference builds of real products, saved projects, and a community feed to publish and remix builds.
- **Works offline.** Without API keys, a scripted mock runs the same tools and events, so every flow can be demonstrated on a laptop.

## How it works

```mermaid
flowchart LR
    V[Voice: Gemini Live] --> W
    W[Web dashboard<br/>React, Three.js] -->|HTTP| B[FastAPI backend]
    B -->|SSE event stream| W
    B --> O[Orchestrator<br/>Claude Opus 5.5]
    O -->|delegate| S[Sub-agents<br/>Claude Sonnet 5.5]
    O --> T[47 tools]
    S --> T
    T --> FC[FreeCAD]
    T --> MJ[MuJoCo]
    T --> BL[Blender]
    T --> PR[Catalogs and live prices]
    W <-->|PCM WebSocket| B
    B <-->|audio and Claude tool calls| G[Gemini Live]
```

1. A request arrives from the chat, a voice turn or a sketch upload.
2. Claude writes the spec from the request, and `spec.py` validates it until it is complete.
3. CAD sub-agents write one FreeCAD script per printed part, in parallel; FreeCAD builds them.
4. The parts agent picks the bought parts, the assembly is computed, and the analysis agent runs every check and the MuJoCo test.
5. On a failure the orchestrator changes the design and everything reruns.
6. Blender renders the result, the pricing agent builds the bill of materials, and the build is saved as the next version.
7. Every step is an event on one Server-Sent Events stream, which the dashboard renders live.

The details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); every tool is described in [docs/TOOLS.md](docs/TOOLS.md).

### For reviewers: where to look

Every backend module starts with a docstring that says what it does, where it sits in the pipeline and why it is built that way.
A good reading order:

| Question | Start here |
| --- | --- |
| How does one request become a checked product? | [One request through the code](docs/ARCHITECTURE.md#one-request-through-the-code), then `agent/src/pai_agent/orchestrator.py` |
| How does Claude call the tools, and how do sub-agents work? | `orchestrator._lead_loop`, `agents.py` (`ROLES`, `run_subagent`, `delegate`) |
| Where are the tools, and what does every call go through? | `agent/src/pai_agent/tools/registry.py` (`SCHEMAS`, `call_tool`), [docs/TOOLS.md](docs/TOOLS.md) |
| How is a spec validated and pass or fail decided? | `spec.py` (`validate_spec`), `requirements.py`, `tools/checks.py`, `analysis.py`, `rigid_sim.py` |
| How is generated CAD code kept safe? | `cad_script.py` (`check_script`, `run_script`), `tools/cad_part.py` |
| How does the voice agent hand work to Claude? | `gemini_live.py` (`execute`), `web/src/lib/geminiLive.ts`, [docs/GEMINI_LIVE.md](docs/GEMINI_LIVE.md) |
| Where do requirements come from, and how do versions work? | `requirements.py` (`attribute`), `tools/gripper.py` (`product_brief`), `versions.py` |
| How does the dashboard stay in sync? | `bus.py`, `web/src/events/source.ts`, `web/src/events/store.ts`, [docs/events.md](docs/events.md) |
| Why these design choices? | [Design decisions](docs/ARCHITECTURE.md#design-decisions) |
| What runs without keys? | [Mock mode and fallbacks](docs/ARCHITECTURE.md#mock-mode-and-fallbacks) |

## Partner technology

### Anthropic Claude

Claude is the engineer.
The orchestrator runs on Claude Opus 5.5 with adaptive thinking and a configurable effort level, and it drives the whole bench through 47 tools with the Messages API tool-use loop (`agent/src/pai_agent/orchestrator.py`).
It delegates bounded jobs to Claude Sonnet 5.5 sub-agents that see only the tools their job needs (`agent/src/pai_agent/agents.py`).
Claude writes the FreeCAD Python for every generated part and repairs it from FreeCAD's error messages, reads hand sketches with vision, and finds live shop prices with server-side web search.
Claude Haiku 5.5 writes the learning-mode explanations, using only numbers the tools produced.

### Reson8

Reson8 powers push-to-talk dictation.
The browser streams microphone audio to Reson8 with a short-lived token the backend vends (`POST /api/voice/token`), so the API key never reaches the browser, and a phrase list biases recognition toward engineering vocabulary such as Twiglet, Caddx, 1103, KV and MuJoCo.
Turn on **Push-to-talk** in Settings (for the current page; every load starts with the Talk button), hold the mic or the space bar, and the turn goes to the agent as text over Reson8's Realtime endpoint; Mechanic answers in text.
The browser's Web Speech recognition is the fallback without a Reson8 key.
The voice conversation (**Talk**) does not use Reson8: Gemini Live hears and transcribes it itself.

### Also used

Google Gemini Live provides Mechanic's only voice, native realtime audio through Vertex AI or AI Studio; [configuration and protocol](docs/GEMINI_LIVE.md).
FreeCAD, Blender, MuJoCo and NVIDIA Isaac Sim and Isaac Lab are the engineering tools Claude operates.
The full stack with versions and licenses is in [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md).

## Quick start

### Prerequisites

- macOS or Linux, with [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 on first run) and Node.js 20 or newer.
- Optional: [FreeCAD 1.1](https://www.freecad.org/) and [Blender](https://www.blender.org/) in `/Applications` for real CAD and renders; without them CadQuery and a recorded still stand in.
- Optional: Rust for the Mac app.
- Optional API keys in `agent/.env` (see [Configuration](#configuration)); without any key the scripted mock runs.

### Backend

```bash
cd agent && uv run physical-ai-agent
```

The backend listens on `http://127.0.0.1:8100`.

### Web dashboard

```bash
cd web && npm install && npm run dev
```

Open `http://127.0.0.1:5180`.
Vite proxies `/api` and `/files` to the backend; set `BACKEND_URL` to point it elsewhere.
If the port needs to be explicit: `npm run dev -- --port 5180 --host 127.0.0.1`.

### Mac app

```bash
cd web && npm install
cd ../desktop && npm install && npm run dev
```

`npm run build` in `desktop/` bundles `AnyBuild.app` (see [desktop/README.md](desktop/README.md)).

### Try it

Type into the chat, for example:

```text
Design a phone stand for my desk that holds my phone for video calls. It must not tip when I tap the screen and the parts should cost under 6 euros.
```

```text
Design a robot gripper for our arm that picks up a 200 g soda can, 66 mm wide. Keep it under 150 g and 30 €.
```

Or start from a reference build in the Library, upload a sketch, or build the drone from a request and then change it:

```text
I want to build a drone that hunts flies under 150 euros
```

```text
Make it fly 10 minutes.
```

In mock mode the first request builds drone version 1 to your budget; the change revises the flight-time requirement, swaps the battery and builds version 2 with its difference.
`curl -s -X POST http://127.0.0.1:8100/api/reset -H 'content-type: application/json'` starts over.

### Mock mode

Without `ANTHROPIC_API_KEY` and without a logged-in local Claude Code (see `PAI_LLM_PROVIDER`), the backend runs scripted stories through the same tools that Claude calls: the drone from a typed request and a typed change, the phone stand (a tip-over failure fixed by a wider base), the robot gripper (an SG90 servo that drops the can, replaced by an MG996R) and the reference builds.
The top bar says whether Claude runs on the API key, on the local subscription, or the mock runs.
`PAI_FORCE_MOCK=1` forces the mock even with a key.

### Real FreeCAD in the open window (optional)

With the [freecad-mcp](https://github.com/neka-nat/freecad-mcp) add-on, `cad_frame` builds the drone visibly in the FreeCAD window, stage by stage.
One-time setup on FreeCAD 1.1:

```bash
git clone https://github.com/neka-nat/freecad-mcp.git
mkdir -p "$HOME/Library/Application Support/FreeCAD/v1-1/Mod"
cp -R freecad-mcp/addon/FreeCADMCP "$HOME/Library/Application Support/FreeCAD/v1-1/Mod/FreeCADMCP"
```

Then open the `MCP Addon` workbench in FreeCAD and select `Toggle Auto Start`.
`FREECAD_GUI=launch` opens FreeCAD automatically; `FREECAD_GUI=off` forces headless runs.

## Configuration

Put settings in `agent/.env` or the shell; shell variables win.
Never commit `.env` files or keys.
Every variable is optional.

### Models and services

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Enables Claude; empty runs the local Claude Code subscription when logged in, else the mock. Also enables live shop prices. |
| `PAI_LLM_PROVIDER` | Where Claude runs: `auto` (default: the key, else a logged-in local Claude Code, else the mock), `api`, or `subscription` (Claude Code on this machine, billed to its plan; refused when `ANYBUILD_ACCESS_CODE` is set). Also in Settings. |
| `ANTHROPIC_MODEL` | Orchestrator model when `PAI_ORCHESTRATOR_MODEL` is unset (default `claude-opus-5-5`). |
| `PAI_ORCHESTRATOR_MODEL`, `PAI_ORCHESTRATOR_EFFORT` | Orchestrator model and effort (`low` to `max`, default `high`). |
| `PAI_SUBAGENT_MODEL`, `PAI_SUBAGENT_EFFORT` | Sub-agent model (default `claude-sonnet-5-5`) and effort (default `medium`). |
| `PAI_DELEGATION` | `0` lets the orchestrator do the sub-agents' jobs itself. |
| `ANTHROPIC_VOICE_MODEL` | Model for the learning-mode explanations (default `claude-haiku-5-5`). |
| `PAI_FORCE_MOCK` | `1` forces the mock even with a key. |
| `GEMINI_LIVE_PROVIDER`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GEMINI_API_KEY`, `GEMINI_LIVE_MODEL`, `GEMINI_LIVE_VOICE` | Mechanic's only voice, Gemini Live (default model `gemini-3.8-live`, voice `Fenrir`): Vertex with gcloud user OAuth or AI Studio with a server-only key; empty keeps Mechanic silent with text replies; see [voice setup](docs/GEMINI_LIVE.md). |
| `RESON8_API_KEY`, `RESON8_LANGUAGE`, `RESON8_CUSTOM_MODEL_ID` | Reson8 speech-to-text (default language `en`); empty uses browser speech recognition. |

### Parts discovery

When the curated library has no part that fits, `parts_search` and `part_pick` with `web` look in the learned library first, then the distributor APIs for electronics, then the web (the shop page, the maker page and the datasheet PDF of the same part number, each number with its own source).
Every part a build validates is kept in `agent/data/learned/parts.json` (local, gitignored), so the next build finds it at once; review it with `cd agent && uv run python scripts/learned_parts.py list` (`show ID`, `remove ID`, `prune --estimated --older-than DAYS --unused --yes`).
Prices in any currency convert at the day's ECB reference rate.

| Variable | Purpose |
| --- | --- |
| `PAI_ALLOW_ESTIMATED` | `1` is exploration mode (also in Settings): a part may carry clearly labelled estimates for non-critical numbers so a test build goes on. Default `0`: every part number is sourced. |
| `PAI_LEARNED_PARTS` | Path of the learned parts library (default `agent/data/learned/parts.json`). |
| `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET` | Digi-Key Product Information API v4. |
| `NEXAR_CLIENT_ID`, `NEXAR_CLIENT_SECRET` | Nexar Supply API (Octopart data). |
| `MOUSER_API_KEY` | Mouser Search API (30 calls a minute, 1,000 a day). |

#### Distributor APIs (optional)

Each distributor is searched only when its credentials are set; the app works without them.
Paste the values into `agent/.env` (copy `agent/.env.example`, which has empty lines for each), then restart the backend.
The parts library's tool status then names them, for example "web search on, Digi-Key, Mouser".

1. **Digi-Key**: open the [Digi-Key developer portal](https://developer.digikey.com) and sign in with a Digi-Key account. Go to Organizations and create one, open it, choose Production Apps, then Create Production App. Name it, enter any OAuth callback (for example `https://localhost`; the client-credentials flow does not use it) and tick the **Product Information V4** product. Open the app and copy its Client ID to `DIGIKEY_CLIENT_ID` and its Client Secret to `DIGIKEY_CLIENT_SECRET`.
2. **Nexar (Octopart)**: open the [Nexar portal](https://portal.nexar.com), sign up and create an app. Give it the **Supply** scope. On the app's Authorization tab copy the Client ID to `NEXAR_CLIENT_ID` and the Client Secret to `NEXAR_CLIENT_SECRET`. The secret is shown only once, so copy it when it appears; otherwise generate a new one.
3. **Mouser**: open the [Mouser Search API page](https://www.mouser.com/api-search/), log in to My Mouser and sign up for the Search API. The key is on the APIs page of your My Mouser account (and in the confirmation email); copy it to `MOUSER_API_KEY`.

Tokens are cached until they expire, results for a day, each provider stays inside its per-minute and per-day limits, and no credential is ever logged or printed.

### Engineering tools and runtime

| Variable | Purpose |
| --- | --- |
| `FREECAD_GUI` | `auto` (build in an open window), `launch` (start FreeCAD), `off` (headless only). |
| `FREECAD_MCP_URL` | freecad-mcp RPC server (default `http://127.0.0.1:9875`). |
| `ISAAC_SSH_HOST`, `ISAAC_SSH_PORT`, `ISAAC_SSH_USER`, `ISAAC_SSH_KEY`, `ISAAC_TIMEOUT_S` | GPU host for Isaac Sim and Isaac Lab (`RUNPOD_SSH_*` are accepted aliases); empty uses the recorded result. |
| `PAI_ASK_TIMEOUT_S` | Seconds Mechanic waits for an answer before taking the default (default `20`). |
| `PAI_TOOL_TIMEOUT_S`, `PAI_TIMEOUT_<TOOL>`, `PAI_MODEL_TIMEOUT_S`, `PAI_MODEL_ROUND_MAX_S` | Time limits per tool call, per silent model stream and per model round (see `agent/src/pai_agent/timeouts.py`). |
| `PAI_TRAIN_TIMEOUT_S`, `PAI_TRAIN_CLAIM_TIMEOUT_S`, `PAI_TRAIN_STALL_S` | Time limits for browser training jobs. |
| `PAI_SLICER` | Optional slicer executable path; `off` uses labelled estimates. |
| `PAI_CACHE` | `0` turns off reuse of identical FreeCAD and Blender results. |
| `PAI_WARM` | `0` skips warming slow imports at start. |
| `DEMO_PACE_S` | Pause between steps in seconds, for stage pacing (default `0`). |
| `PORT` | Backend port (default `8100`). |

### Public deployment

| Variable | Purpose |
| --- | --- |
| `ANYBUILD_ACCESS_CODE` | Access code for a public backend; when set, every route except `GET /api/health` needs a session from `POST /api/access`, and rate limits apply. |
| `ANYBUILD_CORS_ORIGINS` | Extra allowed browser origins, comma-separated. |
| `ANYBUILD_LIMIT_BUILDS`, `ANYBUILD_LIMIT_SPEECH`, `ANYBUILD_LIMIT_STT`, `ANYBUILD_LIMIT_CAD`, `ANYBUILD_LIMIT_EXPLAIN` | Hourly limits per session (defaults 20, 300, 60, 120, 120; each IP gets three times the per-session limit). |
| `VITE_API_BASE` | Backend URL baked into a web build (Vercel, Mac app). |
| `BACKEND_URL` | Backend the Vite dev server proxies to (default `http://localhost:8100`). |

## Public live deployment

The public web app at https://anybuild-demo.vercel.app is the real app: it talks to the live backend on the team's Mac, which runs Claude, FreeCAD, Blender, MuJoCo, Gemini Live and Reson8.
Tailscale Funnel publishes that backend over HTTPS, and an access code shared only with the team and the jury keeps strangers from spending the API credit.

On the Mac, start the backend with an access code (put real values in `agent/.env`, never in the repository):

```bash
cd agent && ANYBUILD_ACCESS_CODE=<code> uv run physical-ai-agent
```

Publish port 8100 through Tailscale Funnel; the backend is then reachable at `https://<machine>.<tailnet>.ts.net`:

```bash
tailscale funnel --bg 8100
```

Build the web app against that URL; on Vercel, set `VITE_API_BASE` as a build environment variable:

```bash
cd web && VITE_API_BASE=https://<machine>.<tailnet>.ts.net npm run build
```

On start the web app calls `GET /api/health`.
When the backend asks for a code, the app shows one field, "Enter access code", then the full app; when it does not answer, the app shows "Live backend offline, try again shortly" and retries.
The session token lasts 24 hours; changing `ANYBUILD_ACCESS_CODE` and restarting the backend signs everyone out.
Ten wrong codes from one IP within 15 minutes block that IP for the rest of the window, and builds, speech and Reson8 tokens have hourly limits, answered with HTTP 429 and a notice in the app.
All visitors share the one bench session on the Mac, as in a live demo.

Check the gate from any machine:

```bash
curl -s https://<machine>.<tailnet>.ts.net/api/health
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://<machine>.<tailnet>.ts.net/api/prompt
```

The first prints `"access": "required"`, the second `401`.

## Bench results

AnyBuild Bench measures how often the agent turns a product prompt into a valid, checked product.
`agent/bench/prompts.json` holds 20 prompts (drone variants, gripper, phone stand, desk lamp, desk fan, Pi enclosure, plant-watering robot, RC car, wall hook, cable organizer and more), each with the checks that judge it: the build finished, CAD geometry, a bill of materials, a render, and the requirements that must be met (`req:mass`, `req:tip_over`, `req:deflection`, ...).
The runner sends each prompt through the real flow (orchestrator, tools, checks) on its own fresh bench, in its own process, and records pass or fail per check, retries, time, tokens and cost:

```bash
cd agent && uv run python -m bench.run --limit 8 -j 2 --timeout 900 --budget 3600   # live, needs ANTHROPIC_API_KEY
cd agent && uv run python -m bench.run --mock                                        # mock: the recorded subset
```

`-j` limits how many prompts run at once, `--timeout` stops one prompt, `--budget` skips prompts that cannot start in time, `--only id,id` picks prompts.
Results go to `agent/bench/results/live.json` or `mock.json`; open them in the app under Settings → AnyBuild Bench results (or `?benchmark`), where "Open on bench" builds a prompt again.

| Run | Prompts | Valid products | Checks passed | Cost per product |
| --- | --- | --- | --- | --- |
| Mock (no Claude, no FreeCAD) | 5 of 20 | 1 of 5 | 31 of 36 | $0 |
| Live | not run yet | | | |

The mock row is **not a result of the live agent**: it replays the recorded mock stories for the five products the mock knows, on a machine without FreeCAD, where printed parts fall back to simplified CadQuery blocks and come out too heavy.
A live run with a key is the measurement that counts.

## Testing

```bash
cd agent && uv run --with pytest pytest tests          # unit tests
cd agent && uv run python scripts/smoke_sse.py         # drone request and change over SSE, mock mode, port 8101
cd agent && uv run python scripts/smoke_product.py     # any-product flow
cd agent && uv run python scripts/smoke_cad_part.py    # generated FreeCAD part, no network
cd agent && uv run python scripts/smoke_community.py   # publish and remix round trip
cd web && npm run typecheck && npm run e2e             # type check and Playwright flows
```

`E2E_LIVE=1 npm run e2e:live` runs the Playwright smoke against a backend with `ANTHROPIC_API_KEY`.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, one request through the code, orchestrator and sub-agents, CAD pipeline, simulation, voice loop, event stream, fallbacks, security, design decisions. |
| [docs/API.md](docs/API.md) | Every HTTP endpoint and SSE event, with auth and rate limits. |
| [docs/events.md](docs/events.md) | The authoritative wire format of every request, response and event. |
| [docs/TOOLS.md](docs/TOOLS.md) | All 54 agent tools with inputs, outputs and the software behind them. |
| [docs/GEMINI_LIVE.md](docs/GEMINI_LIVE.md) | The Gemini Live voice agent: configuration, protocol, transcripts and measured latency. |
| [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md) | Frameworks, services and applications with versions and licenses. |
| [docs/omniverse.md](docs/omniverse.md) | NVIDIA Isaac Sim and Isaac Lab experiments on a GPU host. |
| [docs/PLAN.md](docs/PLAN.md) | The hackathon day plan. |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Third-party models, adapted code and generated media. |

## Team

- Batuhan Caniberk ([BatuCani](https://github.com/BatuCani))
- Ansorjon Juraev ([TheWingTheWong](https://github.com/TheWingTheWong))

The project was first named Bauplan, and some package and path names still say so.

## License

AnyBuild is released under the [MIT License](LICENSE).
Third-party models and adapted code keep their own licenses, listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
