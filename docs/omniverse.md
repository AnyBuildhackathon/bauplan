# Omniverse experiments

For the drone demo, AnyBuild exports the current product from CAD through Blender to USD and runs finished experiments on an NVIDIA RTX machine over plain SSH (RunPod or NVIDIA Brev).
The Mac runs the app and USD export; Isaac Sim and Isaac Lab run on the GPU pod.
The fourth canvas tab, **Omniverse**, shows a completed MP4, measured values, result JSON, and a learning curve for training.
There is no live streaming dependency.

## Local start

```bash
cd agent
PAI_FORCE_MOCK=1 FREECAD_GUI=off PORT=8113 uv run physical-ai-agent
```

In a second terminal:

```bash
cd web
BACKEND_URL=http://localhost:8113 npm run dev -- --port 5193 --host 127.0.0.1
```

Open `http://127.0.0.1:5193/?live&tab=omniverse&mute`.
Ask Mechanic **“Test 8 m/s wind gusts with a 10 g camera in Omniverse.”**, **“Test hover stability in Omniverse.”**, or **“Train the reference quadcopter in Isaac Lab.”**
The tab's controls send the same chat requests.
With an Anthropic key, Claude selects these tools through the existing tool loop.
In mock mode, these requests go through the same tool registry without an LLM call.

## Recorded fallback

Until a pod is configured, the app displays **Waiting for pod** and a clearly labelled **Recorded demo**.
A failed connection, export, remote timeout or invalid returned artifact also selects the recorded fallback and explains the failure.
The recording is an eight-second browser replay of the existing local simulation visualization, with an in-video provenance label.
The accompanying wind values and learning curve are synthetic fixture data, not Isaac measurements or proof that the current CAD product passed.
Requested conditions and fixed recorded conditions are displayed separately.
Recorded values must never trigger claims about the current product or automatic design changes.
The fixed wind fixture describes drone v1: 36.7 g before payload, 10 g added payload, and 46.7 g total test mass.
The displayed assembly weight follows the same selected version as the key numbers panel; fixture values remain fixed when that selection changes.
Live results report `assembly_mass_g` before added payload and `total_mass_g` including it.

`agent/runs/fallback/omniverse.json` is the canonical fixture.
Its public copy and video under `web/public/demo/` support the static deployment with `?demo&tab=omniverse` and no backend.
The backend serves its copy through `/files/fallback/omniverse.mp4` and `/files/fallback/omniverse.json`.
Replace both copies with an actual pod recording and verified matching metadata when one is available; preserve the recorded label.

## Prepare a pod

Use an Ubuntu 22.04+ NVIDIA RTX host or an Isaac Sim container with sufficient disk space, at least 16 GB VRAM, and a driver compatible with Isaac Sim 5.1.
The installer checks `nvidia-smi`; it does not install or alter the NVIDIA driver.
From a checkout on the GPU host (root, or a user with sudo):

```bash
RUN_ON_POD=1 bash runpod/setup.sh
```

The one-shot script installs system rendering dependencies, Python 3.11 in `~/.venvs/anybuild-isaac`, Isaac Sim 5.1.0, Isaac Lab v2.3.0, RSL-RL, TensorBoard, and the video encoder.
It performs a bounded headless Kit startup and propagates errors.
An existing Isaac Lab checkout must match the pinned tag; setup does not reset or overwrite another checkout.
The versions follow NVIDIA's [Isaac Lab pip installation instructions](https://isaac-sim.github.io/IsaacLab/v2.3.0/source/setup/installation/pip_installation.html).
The training entry point follows the [v2.3.0 RSL-RL script](https://github.com/isaac-sim/IsaacLab/blob/v2.3.0/scripts/reinforcement_learning/rsl_rl/train.py).

Set connection variables in the Mac backend's environment, then restart that backend:

| Variable | Default and purpose |
| --- | --- |
| `ISAAC_SSH_HOST` | Required for live jobs; unset selects the recorded demo. |
| `ISAAC_SSH_PORT` | `22`; use the pod's exposed SSH port. |
| `ISAAC_SSH_USER` | `root`. |
| `ISAAC_SSH_KEY` | `~/.ssh/id_ed25519`; path only, never key contents. |
| `ISAAC_TIMEOUT_S` | `300` for tests, `900` for training; allowed range 30-1800 seconds. |

The legacy `RUNPOD_SSH_*` names remain supported aliases; `ISAAC_SSH_*` takes precedence.
No provider API is used.
In an Isaac Sim container, expose the GPU and graphics capabilities (including Vulkan) and run the same setup command; the pinned stack uses its own Python environment.

SSH uses batch authentication, an eight-second connection timeout, keepalives, and first-use host-key acceptance.
No credentials are returned to the browser or written to source files.
Every job uploads to its own `/tmp/anybuild-<id>` directory and downloads only that job's files.
The remote GNU `timeout` terminates the process group and escalates after 15 seconds, even after an SSH disconnect.
Transfers have separate deadlines; a local timeout or cancellation also kills and reaps the local SSH/SCP process.
Remote logs remain in the job's `job.log` for diagnosis; the UI shows a concise error without dumping remote output.
Remove job directories on the pod once their artifacts are no longer needed.

## Agent tools

| Tool | Arguments | Result |
| --- | --- | --- |
| `product_usd` | None; requires selected parts and a built CAD frame. | Portable ZIP containing `product.usda`, `assembly.usdc`, and `assembly.json`. |
| `isaac_test` | `scenario`: `wind`, `payload`, or `hover`; optional `wind_m_s` (0-20), `payload_g` (0-500), `duration_s` (2-20). | MP4, JSON, hover error, peak tilt, drift, mass, and pass/fail when live. |
| `isaac_train` | Optional `iterations` (1-1000, default 100), `num_envs` (1-256, default 64). | MP4 training rollout, TensorBoard reward curve, and summary values. |

During a live job, normal SSE events report `export`, `upload`, `execute`, and `download` stages with a visible progress message.
The test defaults to 6 m/s for the wind scenario, 10 g for the payload scenario, and eight seconds.
Both wind and payload can be specified in the same test.
The runner automatically exports and uploads the current product before starting either type of live job.
`isaac_lab_train` and `isaac_sim_render` remain aliases for older clients.
`isaac_lab_status` returns the latest session result; jobs now return completed artifacts without polling.
The APIs use the existing `POST /api/prompt`, `GET /api/events`, and session-scoped `/files/` endpoints.

## Product export and test model

The exporter reuses the Blender studio's CAD frame, motors, propellers, battery and flight controller, without its camera, lights or floor.
The mesh layer uses metres and Z up.
Each part group carries `mass_kg` custom metadata; the manifest lists all 11 component instances, their USD paths, their masses, and the selected motors' maximum thrust.
A physics wrapper references the mesh layer and gives the assembly a single rigid body with its total mass in kilograms.
The returned ZIP keeps relative USD references portable.

The pod loads that USD into Isaac Sim/PhysX and applies convex collision approximations to its meshes.
The hover controller uses position and attitude PD feedback with thrust capped by the selected motors.
Wind is a ramped gust using a constant projected area, drag coefficient 1.1, and air density 1.225 kg/m³.
Added payload changes centred mass; it does not model a camera's shape, offset centre of gravity, or structural mounting.
This is a simplified rigid-body experiment, not CFD, a structural simulation, or flight certification.
The current assembly exporter and controller support the drone demo geometry; other product types need their own assembly builders and experiment controllers.
The Omniverse tab is hidden for the robot gripper and other generated parts, and backend tools reject unsupported products before replay or SSH.
The gripper keeps its MuJoCo lift-and-shake test in the Simulation tab.

A live test passes when altitude stays at least 0.15 m, peak tilt stays below 45 degrees, and maximum lateral drift stays below 0.5 m.
The hover target is 0.5 m.
The first observed failure wind value is one point in a transient run, not a certified wind limit.

## Reference training

`isaac_train` runs **Isaac-Quadcopter-Direct-v0**, Isaac Lab's stock Crazyflie task.
It trains the reference robot, not the CAD-exported product.
The uploaded USD remains the product context; it is not substituted for the task's articulated robot.
Reward samples come from the current job's TensorBoard log and the video is a rollout captured during training.
A short bounded run is a training demonstration, not a converged flight policy.

## Verification

```bash
cd agent
uv run python -m unittest discover -s tests -v
SMOKE_PORT=8113 uv run python scripts/smoke_omniverse.py
```

The smoke script expects the mock backend already running on port 8113.
It checks chat dispatch, SSE provenance, separate recorded/requested conditions, and playable MP4 plus JSON downloads in one run.
The fake SSH runner checks uploads, isolated remote commands, returned artifacts, timeout/failure fallback, argument validation and shell-injection rejection.
The frontend check is `cd web && npm run build`.
Real GPU execution still requires the pod; passing mock and transport checks does not validate Isaac installation or simulated flight behavior.
