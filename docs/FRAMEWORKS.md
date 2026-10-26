# Frameworks and tools

This is the stack AnyBuild is built on, with the versions locked in the repository on 2026-10-24 and their licenses.
Library versions come from `agent/uv.lock`, `web/package-lock.json`, `desktop/package-lock.json` and `desktop/src-tauri/Cargo.lock`.
External applications are not bundled; they are installed separately and called at runtime.
AnyBuild's own code is MIT licensed (see [LICENSE](../LICENSE)); third-party models and adapted code are listed in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## AI models and partner services

| Service | Version or model | Role in AnyBuild | Terms |
| --- | --- | --- | --- |
| Anthropic Claude Opus 5.5 | `claude-opus-5-5` | Orchestrator: plans the build, writes specs, decides fixes, reviews sub-agent reports. | Anthropic API terms |
| Anthropic Claude Sonnet 5.5 | `claude-sonnet-5-5` | Sub-agents: FreeCAD scripts, parts, checks, pricing. | Anthropic API terms |
| Anthropic Claude Haiku 5.5 | `claude-haiku-5-5` | Learning-mode explanations. | Anthropic API terms |
| Anthropic server-side web search | `web_search` tool | Live shop prices for the bill of materials. | Anthropic API terms |
| Google Gemini Live | `gemini-3.8-live` (Vertex and AI Studio) | Mechanic's only voice: native speech conversation, barge-in and calls to Claude engineering tools; Fenrir voice. | Google Cloud / Gemini API terms |
| Reson8 | Realtime speech-to-text | Push-to-talk dictation. | Reson8 terms |

## Backend (`agent/`, Python 3.12, managed by uv)

| Package | Version | License | Role |
| --- | --- | --- | --- |
| anthropic | 2.2.0 | Apache-2.0 | Claude Messages API with tool use, adaptive thinking and effort. |
| fastapi | 0.162.0 | MIT | HTTP API and SSE stream. |
| starlette | 1.9.0 | BSD-3-Clause | ASGI toolkit under FastAPI, access-gate middleware. |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI server. |
| pydantic | 2.14.1 | MIT | Request models. |
| websockets | 17.3 | BSD-3-Clause | Backend Gemini Live WebSocket connection. |
| httpx2 | 2.16.0 | BSD-3-Clause | HTTP client for Reson8. |
| mujoco | 3.17.0 | Apache-2.0 | Rigid-body physics: hover, push, drop and grip tests. |
| cadquery | 2.8.0 | Apache-2.0 | CAD fallback when FreeCAD is missing. |
| cadquery-ocp | 7.9.3.1.1 | Apache-2.0 (bindings), OpenCascade under LGPL-2.1 with exception | OpenCascade geometry kernel for CadQuery. |
| numpy | 2.5.4 | BSD-3-Clause and others | Numerics for the simulations and meshes. |
| hatchling | build only | MIT | Package build backend. |

The optional extra `simready` (`uv sync --extra simready`) adds what the SimReady objects need:

| Package | Version | License | Role |
| --- | --- | --- | --- |
| usd-core | 26.11 | LicenseRef-TOST-1.0 (Pixar's Apache-2.0 variant) | Reads the SimReady USD packages: meshes, materials, physics and semantics. |
| coacd | 1.0.14 | MIT | Convex decomposition of containers for MuJoCo. |
| trimesh | 5.2.0 | MIT | Convex hulls and the GLB written without Blender. |
| huggingface_hub | 2.3.0 | Apache-2.0 | Lists the dataset for the index builder and finds a saved Hugging Face login. |

Tests run with pytest (`agent/tests/`) and standalone smoke scripts (`agent/scripts/smoke_*.py`).

## Robo Use bridge (`anybuild-robouse/`, its own uv environment)

Versions from `anybuild-robouse/uv.lock`.
It has its own environment because Robo Use pins an older MuJoCo than the backend.

| Package | Version | License | Role |
| --- | --- | --- | --- |
| robouse (`sim` extra only) | 0.6.1 | Apache-2.0 AND MIT AND CC-BY-4.0 | Robo Use: the tabletop scene, the episode server that judges trials, `robouse tasks check` and the agent harnesses. The `llm` extra, which pulls a proprietary LiteLLM component, is not installed. |
| mujoco | 3.3.0 | Apache-2.0 | Physics of the Robo Use trials, pinned by robouse. |
| pyyaml | 6.0.3 | MIT | Writes the generated tasks' `task.md`. |

## Engineering applications (installed separately)

| Application | Version used | License | Role |
| --- | --- | --- | --- |
| FreeCAD | 1.1 | LGPL-2.1-or-later | Parametric CAD: visible build in the GUI or headless `freecadcmd`. |
| freecad-mcp add-on | main branch | MIT | XML-RPC server inside the FreeCAD GUI on port 9875. |
| Blender | 5.x (tested with 5.2.3) | GPL-2.0-or-later | Headless studio renders (Cycles with Metal GPU, or EEVEE) and USD export. |
| NVIDIA Isaac Sim | 5.1.0 | NVIDIA Isaac Sim license terms | Drone wind, payload and hover experiments on a GPU host. |
| NVIDIA Isaac Lab | 2.3.0 | BSD-3-Clause | Reference Crazyflie training (`Isaac-Quadcopter-Direct-v0`) with RSL-RL. |
| PrusaSlicer / OrcaSlicer | Optional installed CLI, not pinned | AGPL-3.0 | Slice print-ready parts; mesh estimates when absent. |
| SparkBench | Commit `6dd9237`, pinned in `agent/scripts/setup_sparkbench.sh` | MIT | `circuit_design`: ESP32 and Raspberry Pi Pico circuits with real pins, KiCad schematic, MicroPython firmware run in its simulator, acceptance tests. Runs headless in Node.js through `agent/sparkbench/bridge.ts` and tsx 4.23.15 (MIT). |
| SolidCraft (`solidcraft-cli`) | 0.23.0, pinned in `agent/scripts/setup_solidcraft.sh` | MIT OR Apache-2.0 | With `PAI_CAD_ENGINE=solidcraft`: `solidcraft_part` builds parts and mechanisms from command scripts (timeline, joints, motion links, motion studies), `export_urdf` writes their URDF, which MuJoCo turns into MJCF. |
| Tailscale Funnel | current | Tailscale terms | Publishes the local backend over HTTPS for the public web app. |

AnyBuild calls these applications as separate processes and does not link or redistribute them.

## Web dashboard (`web/`, Node.js)

| Package | Version | License | Role |
| --- | --- | --- | --- |
| react, react-dom | 19.2.9 | MIT | UI framework. |
| vite | 8.3.5 | MIT | Dev server and build. |
| @vitejs/plugin-react | 6.1.2 | MIT | React support for Vite. |
| typescript | 5.9.3 | Apache-2.0 | Type checking. |
| three | 0.186.1 | MIT | 3D rendering of the model, CAD and simulation replays. |
| @react-three/fiber | 9.8.2 | MIT | React renderer for Three.js. |
| @react-three/drei | 10.7.9 | MIT | Three.js helpers (controls, environment, GLTF loading). |
| @mujoco/mujoco | 3.17.0 | Apache-2.0 | MuJoCo WebAssembly for browser training and stress tests. |
| zustand | 5.0.16 | MIT | Event store that folds SSE events into UI state. |
| motion | 14.6.0 | MIT | Animations. |
| tailwindcss, @tailwindcss/vite | 4.3.3 | MIT | Styling. |
| lucide-react | 1.61.0 | ISC | Icons. |
| react-markdown | 10.1.0 | MIT | Markdown in chat messages. |
| remark-gfm | 4.0.1 | MIT | GitHub-flavored Markdown tables and lists. |
| @playwright/test | 1.64.1 | Apache-2.0 | End-to-end tests (`web/e2e/`). |

Fonts (Inter Tight, Chivo Mono and Caveat) load at runtime from Google Fonts under the SIL Open Font License 1.1 and are not stored in the repository.

## Mac app (`desktop/`)

| Package | Version | License | Role |
| --- | --- | --- | --- |
| tauri (Rust crate) | 2.12.5 | Apache-2.0 OR MIT | Native macOS window around the dashboard. |
| tauri-plugin-localhost | 2.4.0 | Apache-2.0 OR MIT | Serves the bundled dashboard on localhost. |
| @tauri-apps/cli | 2.12.4 | Apache-2.0 OR MIT | Build and dev commands. |

## Hosting

| Service | Role |
| --- | --- |
| Vercel | Hosts the static web app at https://anybuild-demo.vercel.app. |
| Tailscale Funnel | HTTPS tunnel to the live backend on the team's Mac. |
| GPU host (RunPod or NVIDIA Brev) | Optional Isaac Sim and Isaac Lab runs over SSH. |
