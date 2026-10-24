# AnyBuild Hackathon Day Plan

This plan organizes the team execution for the {Tech: Europe} Agentic AI Hack Berlin on 2026-10-24.
The primary goal is demonstrating an autonomous physical-AI engineering agent on stage.

## Tool Stack

The architecture combines engineering software, physical simulation, AI models, and presentation clients:

- AI reasoning: Anthropic Claude Sonnet with tool use for engineering decision-making and reconciliation.
- Meeting intelligence: Jamie MCP for recording ingestion, requirement extraction, notes back, and task management.
- Speech processing: Reson8 for realtime streaming speech-to-text, plus browser speech synthesis or ElevenLabs TTS.
- Parametric CAD: FreeCAD with `freecad-mcp` for live interactive building in GUI, falling back to headless `freecadcmd` and CadQuery.
- Photorealistic rendering: Blender with EEVEE headless rendering for studio product presentations.
- Fast physics simulation: MuJoCo for aerodynamics and downdraft gust stability evaluation.
- High-fidelity GPU simulation: NVIDIA Isaac Sim 6.2 and Isaac Lab 3.0 on a RunPod RTX 4090 for quadcopter reinforcement learning.
- Backend server: FastAPI and Uvicorn running on Python 3.12 with Server-Sent Events.
- Frontend dashboard: React, Vite, Tailwind CSS, Zustand, and React Three Fiber.
- Desktop wrapper: Tauri 2 for native macOS presentation.
- Deployment: Vercel for hosted static fixture playback at https://anybuild-demo.vercel.app.

## Workstreams and Ownership

Two team members develop the project concurrently using independent agent sessions:

- Workstream 1: Live Integrations, Parts Discovery, and Multimodal Inputs
  - Owner: Ansorjon Juraev (@TheWingTheWong)
  - Directories: `agent/src/pai_agent/tools/`, `agent/src/pai_agent/jamie_client.py`, `agent/src/pai_agent/voice.py`, and `web/src/components/chat/`
  - Responsibilities: Live Jamie MCP integration with on-site credentials, live Reson8 streaming speech-to-text integration, live parts search (`parts_search*.py`), and sketch image input (`sketch*.py` with chat upload UI).
- Workstream 2: General Physical AI, Simulation, Design System, and Deliverables
  - Owner: Batu / Agent Workspace
  - Directories: `agent/src/pai_agent/tools/cad.py`, `agent/src/pai_agent/freecad_run.py`, `runpod/`, `web/`, `desktop/`, and `docs/`
  - Responsibilities: General CAD generation where Claude writes FreeCAD Python scripts for arbitrary parts, a second demonstration product, AnyBuild UI renaming and Bevel visual polish, NVIDIA Omniverse and Isaac Sim on RunPod, technical documentation, and stage demo video recording.

## Parallel Development Interfaces

Clear interfaces prevent merge conflicts while both sides build concurrently:

- Tool Registry: `agent/src/pai_agent/tools/registry.py` is the single integration point where new tool definitions (`parts_search`, `sketch`, general CAD) register their schemas and async execution handlers.
- SSE Event Contract: `docs/events.md` defines the authoritative JSON event stream wire contract; new event types or fields are coordinated in PR descriptions before client consumption.

## Day Timeline to Submission

The hackathon takes place on 2026-10-24 in Berlin:

- 09:00 - 10:00: Team kickoff, problem framing, and repository structure setup.
- 10:00 - 12:30: Core agent tools, FreeCAD parametric build pipeline, and MuJoCo simulation harness.
- 12:30 - 14:30: Jamie MCP integration, requirement extraction, timeline wire contracts, and Reson8 speech connection.
- 14:30 - 16:30: Frontend dashboard polish, Three.js 3D viewport tabs, Bevel design tokens, and mock story recording.
- 16:30 - 17:45: RunPod RTX 4090 Isaac Lab training setup, fallback recording generation, and desktop packaging.
- 17:45 - 18:30: End-to-end rehearsal, code freeze, and submission completion.
- 18:30: Project submission deadline.
- 19:00: Opt-in deadline for live stage demos.
- 20:00: Live demo presentations on the main stage projector.

## Submission Requirements and Judging Criteria

Submissions are evaluated on their performance as an autonomous agentic system:

- Submission deliverables: Public GitHub repository link, recorded video walkthrough, demo URL, and technical architecture summary.
- Autonomous agency: The system must execute multi-step engineering loops without human micromanagement.
- Real engineering tool use: The agent must operate genuine CAD software and physics engines rather than generating text hallucinated answers.
- Sponsor integration depth: Deep native use of Jamie MCP meeting data, Reson8 streaming audio, and Anthropic Claude tool calling.
- Stage presentation readiness: High-contrast projector readability, clear spoken dialogue with mascot Bolzen, and fast deterministic fallbacks.
