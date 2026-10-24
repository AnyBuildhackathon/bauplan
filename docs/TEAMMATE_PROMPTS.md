# AnyBuild: prompts for the teammate's agents

Setup once:

```bash
gh repo clone AnyBuildhackathon/bauplan && cd bauplan
git worktree add ../bauplan-train   -b ansorjon/train   origin/main
git worktree add ../bauplan-stress  -b ansorjon/stress  origin/main
git worktree add ../bauplan-guide   -b ansorjon/guide   origin/main
git worktree add ../bauplan-firmware -b ansorjon/firmware origin/main
git worktree add ../bauplan-prices  -b ansorjon/prices  origin/main
```

Open one Claude Code session per folder and paste the matching prompt.
Each prompt starts with the same shared block.

---

## Shared block (paste at the top of every prompt)

```
You work on AnyBuild (repo AnyBuildhackathon/bauplan), a general engineering agent for the Agentic AI Hack Berlin today: the team's Jamie meetings set requirements, Claude designs the product through tool use (FreeCAD, Blender, MuJoCo), and the dashboard analyses it. The drone is the demo product; a second product is being added by another agent.
Read AGENTS.md and docs/PLAN.md first, then docs/events.md (SSE event contract) and agent/src/pai_agent/tools/registry.py (how agent tools register).
Rules: English only in UI and docs. Stay in your own new files; do not restyle the UI (the captain owns design) and do not edit agent/src/pai_agent/tools/jamie.py, the Omniverse/Isaac code, the general CAD code or the AnyBuild rename work, which other agents own. If you must touch a shared file (registry.py, events.md, a canvas tab), keep the change minimal and say so in the PR description. Never commit keys or .env files.
Run the backend with PORT=<your backend port> and the web with `npm run dev -- --port <your web port>` and BACKEND_URL=http://localhost:<your backend port>; use mock mode (PAI_FORCE_MOCK=1) unless told otherwise.
Work in small steps, commit with plain messages, open one PR into main when it works, and say what to click to see it. Feature freeze is 16:00.
```

---

## 1. Training in 1,024 browser simulations (worktree bauplan-train, ports 8121/5201)

```
Task: add training to AnyBuild that runs 1,024 physics simulations in the browser and shows it live.
- Use MuJoCo WASM (@mujoco/mujoco) in Web Workers (cores minus one) and an evolution strategy: 64 candidates x 16 generations = 1,024 rollouts.
- What is trained depends on the product: for the drone, the hover/flight controller gains (stay level and hold position for 10 s); for a legged or gripper product later, its gait or grip parameters. Build a small interface so the product supplies the model (MJCF), the parameters and the fitness function.
- Build the MJCF from the current product's parts and masses (the backend already computes them; read them from the SSE events or add a small endpoint).
- UI: in the Simulation tab, a grid of 16 small simulations, a counter up to 1,024, a fitness curve climbing, and the best result replayed large. Emit the existing `training` SSE event shape (see docs/events.md) so Bolzen and the panel can react.
- Add an agent tool `train_in_browser` in a new module so Bolzen can start it from chat ("train it").
Done when: in mock mode, asking Bolzen to train starts the run, the grid and curve animate, and the final values land in the panel.
```

## 2. Stress test with randomized physics (worktree bauplan-stress, ports 8122/5202)

```
Task: add a stress test that runs the best trained result in 50 randomized worlds and reports a robustness score, e.g. "Survived 47/50".
- Randomize per run: mass +-15 %, motor strength -25..0 %, friction or wind gusts (for the drone: gusts up to 6 m/s), sensor noise.
- Reuse the browser MuJoCo workers from the training module (coordinate with that branch; if it is not merged yet, build against a small interface and a stub).
- UI: a compact result card with the score, the worst failure replayed, and one sentence from Bolzen explaining the weakest point. Emit an SSE event documented in docs/events.md.
- Agent tool `stress_test` in a new module.
Done when: after training, "stress test it" in chat shows the score and the worst-case replay.
```

## 3. Build guide with exploded 3D view (worktree bauplan-guide, ports 8123/5203)

```
Task: turn the bill of materials into a step-by-step build guide with an exploded 3D view.
- Claude writes the steps as a validated structure (step number, title, instructions, part ids to highlight, tools, minutes); deterministic code renders them. Part ids must match the 3D model anchors listed in docs/events.md (frame, motor_front_left, ...).
- UI: a "Build guide" view opened from the bill-of-materials panel; per step the 3D model explodes and the step's parts are highlighted, with next/back.
- Agent tool `build_guide` in a new module; emit an SSE event documented in docs/events.md.
Done when: in mock mode, opening the guide walks through all steps with the right parts highlighted.
```

## 4. Firmware and wiring (worktree bauplan-firmware, ports 8124/5204)

```
Task: generate the firmware and wiring for the built product.
- For the drone: a Betaflight CLI configuration for the chosen flight controller (motor order, rates and the trained controller gains); for an Arduino-based product: an .ino sketch. Deterministic templates filled from the product data, Claude only fills the explanation.
- A wiring table (component, pin, wire color) generated from the parts.
- UI: a "Download firmware" button and the wiring table next to the build guide entry in the bill-of-materials panel.
- Agent tool `firmware` in a new module; emit an SSE event documented in docs/events.md.
Done when: in mock mode, the download produces a valid config file and the wiring table matches the parts.
```

## 5. Live parts prices (worktree bauplan-prices, ports 8125/5205)

```
Task: replace the fixed sample prices with live prices and buy links found on the web.
- New module agent/src/pai_agent/tools/parts_search.py: Claude with the web search tool finds each bill-of-materials part at real shops (EU first), returns price, currency, shop, URL and availability, with a short cache and the fixed catalog as fallback when search fails or no key is set.
- The bill of materials shows "live" vs "catalog" per line and the total updates.
Done when: with ANTHROPIC_API_KEY set, the bill of materials shows live prices and links; without it, the catalog prices with a "catalog" label.
```
