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

- Workstream 1: Frontend, 3D Canvas, and Desktop Client
  - Lead: Ansorjon Juraev (@TheWingTheWong)
  - Directories: `web/` and `desktop/`
  - Responsibilities: Bevel UI design system, React Three Fiber model viewers, Jamie timeline component, Bolzen voice chat, and Tauri bundle.
- Workstream 2: Agent Backend, Tool Integrations, and Physical AI Pipeline
  - Lead: Batu / Agent Workspace
  - Directories: `agent/` and `docs/`
  - Responsibilities: FastAPI application, SSE event publisher, Claude tool loop, MuJoCo physics simulation, FreeCAD connector, and Jamie MCP client.
- Workstream 3: GPU Cloud Infrastructure and Isaac Sim Training
  - Shared ownership
  - Directories: `runpod/` and `agent/src/pai_agent/tools/isaac.py`
  - Responsibilities: RunPod pod provisioning, Isaac Lab quadcopter training, policy checkpointing, and fallback video recording.

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
