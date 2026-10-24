# AnyBuild Hackathon Day Plan

This plan organizes the team execution for the {Tech: Europe} Agentic AI Hack Berlin on 2026-10-24.
The primary goal is demonstrating an autonomous physical-AI engineering agent on stage.

## Architecture Principle

Claude writes a validated spec, deterministic code builds the model.
The agent reasons about requirements, hardware catalogs, and physics constraints to output schema-validated specifications.
Deterministic compilers, parametric CAD engines, and physics simulators consume that specification to generate 3D models and run rollouts.

## Tool Stack

The architecture combines engineering software, physical simulation, AI models, and presentation clients:

- AI reasoning: Anthropic Claude Sonnet with tool use for engineering decision-making and reconciliation.
- Meeting intelligence: Jamie MCP for recording ingestion, requirement extraction, notes back, and task management.
- Speech processing: Reson8 for realtime streaming speech-to-text, plus browser speech synthesis or ElevenLabs TTS.
- Parametric CAD: FreeCAD with `freecad-mcp` for live interactive building in GUI, falling back to headless `freecadcmd` and CadQuery.
- Photorealistic rendering: Blender with EEVEE headless rendering for studio product presentations.
- Fast physics simulation: MuJoCo for aerodynamics and downdraft gust stability evaluation.
- In-browser physics: MuJoCo WASM (`@mujoco/mujoco`) with Web Workers for parallel rollouts without GPU dependencies (quick check: 1,024 simulations in seconds live on stage).
- High-fidelity GPU simulation: NVIDIA Isaac Sim 6.2 and Isaac Lab 3.0 on a RunPod RTX 4090 for deep controller policy training in the GPU cloud (feeds firmware, with recorded fallback).
- Backend server: FastAPI and Uvicorn running on Python 3.12 with Server-Sent Events.
- Frontend dashboard: React, Vite, Tailwind CSS, Zustand, and React Three Fiber.
- Desktop wrapper: Tauri 2 for native macOS presentation.
- Deployment: Vercel for hosted static fixture playback at https://anybuild-demo.vercel.app.

## Workstreams and Ownership

The team divides responsibilities across the captain, the teammate, and the agent workspace:

- Visual Design and Stage Direction
  - Owner: Captain
  - Responsibilities: Overall application visual design (styling, layout, Bevel design tokens, visual polish), stage presentation, on-site live API credentials, and live demo delivery.
  - Rule for agents: Autonomous worker agents must not make visual design changes beyond what their assigned functional task strictly requires.

- Workstream 1: Browser Simulation, Build Guides, and Live Sourcing
  - Owner: Ansorjon Juraev (@TheWingTheWong)
  - Directories: `web/src/components/`, `agent/src/pai_agent/tools/parts_search*.py`, and `agent/src/pai_agent/tools/build_guide*.py`
  - Reference: Ready-to-paste prompts and worktree port pairs are documented in docs/TEAMMATE_PROMPTS.md.
  - Responsibilities:
    - Two-tier training architecture: 1,024 parallel browser simulations using MuJoCo WASM and Web Workers for a fast stage check in seconds, complementing cloud GPU Isaac Lab training.
    - Browser stress test with randomized physics evaluating gait and flight survival across 50 trials with varied friction, mass, and motor torque (reusing the browser MuJoCo workers).
    - Step-by-step build guide with interactive exploded 3D model view highlighting components per step.
    - Firmware generation (.ino Arduino sketch download or Betaflight CLI) using Isaac Lab trained controller gains when available, then the browser-tuned gains, then Betaflight default gains, plus hardware wiring table.
    - Live component web prices and purchasing links.
    - Stretch goal: Sketch image input integration.

- Workstream 2: General Physical AI, Agent Pipeline, Cloud Simulation, and Translations
  - Owner: Batu / Agent Workspace
  - Directories: `agent/src/pai_agent/tools/cad.py`, `agent/src/pai_agent/freecad_run.py`, `agent/src/pai_agent/jamie_client.py`, `agent/src/pai_agent/voice.py`, `runpod/`, `docs/`, `web/`, and `desktop/`
  - Responsibilities:
    - General CAD generation where Claude writes FreeCAD Python scripts for arbitrary product geometries.
    - A second demonstration product validating generalizability beyond drones.
    - Code implementation for live Jamie MCP client and live Reson8 streaming STT (credentials entered on site by captain).
    - English UI translation task (translating Mechanic spoken dialogue, agent chat messages, and web labels, setting default `RESON8_LANGUAGE=en`).
    - Project rebranding from Bauplan to AnyBuild across codebase and UI text.
    - NVIDIA Omniverse and Isaac Sim training on RunPod RTX 4090 for deep policy training feeding real firmware parameters, with fallback video playback.
    - Technical documentation, architecture maintenance, and demo video recording.

## Integration Points

Clear integration points connect modules across the codebase without merge conflicts:

- Agent Tool Registry (`agent/src/pai_agent/tools/registry.py`): Central registration where new tool modules (`parts_search`, `build_guide`, `firmware`, general CAD) register their schemas and async dispatch handlers.
- SSE Event Contract (`docs/events.md`): Authoritative wire format contract for event payloads (`training`, `sim`, `bom`, `build_step`, `cad`, `tool`, `chat`); all new event types coordinate through this schema.
- Canvas Tabs (`web/src/components/canvas/`): 3D canvas viewport tabs (`Model`, `CAD`, `Simulation`) connecting the Three.js exploded model viewer, the FreeCAD generated geometry, and the browser MuJoCo WASM rollout grid.

## Day Timeline to Submission

The hackathon takes place on 2026-10-24 in Berlin:

- Until 12:00: Environment setup, repository clones, and configuring on-site credentials for Jamie, Reson8, and Anthropic.
- 12:00 - 16:00: All workstreams build in parallel with small pull requests into main (Omniverse and RunPod included in this window, switching to recorded fallback if the pod is not stable by 14:00).
- 16:00: Feature freeze across all active branches.
- 16:00 - 17:30: Record 2-minute demo video alongside README and technical documentation completion.
- 17:30 - 18:30: Two rehearsals of the 5-minute presentation and make the repository public.
- 18:30: Project submission (deadline 19:00).
- 20:00: Live demo presentations on the main stage projector.

## Submission Requirements and Judging Criteria

Submissions are evaluated on their performance as an autonomous agentic system:

- Submission deliverables: Public GitHub repository link, recorded video walkthrough, demo URL, and technical architecture summary.
- Autonomous agency: The system must execute multi-step engineering loops without human micromanagement.
- Real engineering tool use: The agent must operate genuine CAD software and physics engines rather than generating text hallucinated answers.
- Sponsor integration depth: Deep native use of Jamie MCP meeting data, Reson8 streaming audio, and Anthropic Claude tool calling.
- Stage presentation readiness: High-contrast projector readability, clear spoken dialogue with mascot Mechanic, and fast deterministic fallbacks.
