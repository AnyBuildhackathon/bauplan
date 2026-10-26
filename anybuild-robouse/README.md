# anybuild-robouse

Robo Use benchmark tasks for grippers designed in AnyBuild.
[Robo Use](https://github.com/benchflow-ai/robouse) turns robotics benchmarks into tasks for coding agents: the agent drives a simulated robot through the `robo` command, and an episode server judges the physical end state.
This package lets that benchmark use a gripper AnyBuild just designed, so an independent judge checks whether the design really picks the object up.

It has three parts:

- A Robo Use backend, `anybuild-gripper`, registered through the `robouse.backends` entry point: Robo Use's tabletop scene with the AnyBuild hand in place of its built-in gripper.
- A task generator: from AnyBuild's gripper brief (object mass and width) and the exported hand, a task folder that asks to put a cube of that size and mass into a bowl or onto a pad, with a reference solution.
- A headless trial runner: `robouse tasks check` (reference solution scores 1, no-op control scores 0) and single trials that report reward, verdict, the trial folder and its video.

It runs in its own virtual environment, because Robo Use pins MuJoCo 3.3.0 while AnyBuild's backend uses 3.17.0.
It depends on `robouse[sim]==0.6.1` only; the `llm` extra would pull a proprietary LiteLLM component.

## Run it

```bash
cd anybuild-robouse && uv sync                      # Python 3.11 to 3.13, installs robouse[sim]==0.6.1
uv run anybuild-robouse task --example --mass-g 200 --width-mm 66 --out runs/tasks
uv run anybuild-robouse trial runs/tasks/anybuild-gripper-cube-66mm-200g-in-bowl --harness oracle --out runs/trials
uv run pytest                                       # about a minute, no model calls
```

`task` writes the folder and runs `robouse tasks check` on it; `--no-check` skips that.
`check TASK` runs the check alone.
`trial` prints one JSON object:

```json
{
  "task": "anybuild-gripper-cube-66mm-200g-in-bowl",
  "harness": "oracle",
  "reward": 1.0,
  "verdict": "pass",
  "outcome": "done",
  "steps": 242,
  "wall_s": 10.6,
  "metrics": {"success": 1, "safety_events": 0, "max_contact_force_n": 9.98},
  "trial_dir": "runs/trials/anybuild-gripper-cube-66mm-200g-in-bowl__oracle__94e367",
  "video": "runs/trials/anybuild-gripper-cube-66mm-200g-in-bowl__oracle__94e367/artifacts/recording.mp4",
  "exception": null
}
```

`metrics` holds all of Robo Use's episode metrics; three are shown.
`--record-size 1280x720` renders the video larger than the default 320 x 320.

`--harness noop` runs the negative control.
`--harness claude-code` (or `codex`, `gemini-cli`) lets a coding agent drive the gripper; it runs a model on your account, so it starts only when `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` (`OPENAI_API_KEY` or `~/.codex/auth.json`, `GEMINI_API_KEY`) is set.
A trial folder is Robo Use's: the video, the trace, the physics log, the signed verdict and the metrics.

## Your own design

`--example` uses the bundled hand: AnyBuild's gripper template at its default sizes with an MG996R servo and printed TPU pads.
Export any other build from AnyBuild (needs FreeCAD):

```bash
cd agent && uv run python scripts/export_gripper_mjcf.py --servo towerpro-sg90 --pads pads-silicone --param finger_length_mm=80 --out /tmp/hand.xml
cd anybuild-robouse && uv run anybuild-robouse task --hand /tmp/hand.xml --brief brief.json --out runs/tasks
```

`brief.json` is AnyBuild's gripper brief, `{"object_mass_g": 200, "object_width_mm": 66}`, optionally with `"goal": "pad"`.
A brief the hand cannot grasp is refused with the reason: an object wider than the gripper opens, or one too short for the pads to reach down its side.
A design that is too weak still makes a valid task folder, but its own reference solution fails, and `check` says so: that is the benchmark finding a design flaw.

## How it works

The hand is the MJCF file `agent/src/pai_agent/mjcf_export.py` writes from a FreeCAD build: the template's parts as meshes, collision boxes, the finger hinges, the gears as a joint equality and the servo as a position actuator limited to its holding torque.
Its frame is the tool frame: the grasp point at the origin, the fingers pointing down, closing along y.
The task carries the whole file in `task.md` (`robouse.anybuild_hand`), so a task folder runs anywhere, under `robouse run` as well as under this CLI.

`AnyBuildGripperBackend` is Robo Use's `TabletopBackend` with the hand swapped in (`Hand.scene_xml`): the driven finger becomes `finger_l` on joint `fl`, the geared one `finger_r` on `fr`, and the servo's control is rescaled so that Robo Use's grip command (0 closed to 0.05 open) spans the hinge's range with the same stiffness and torque.
Robo Use 0.6.1 has no hook for swapping the gripper, so the backend wraps the tabletop scene builder while its base class builds the model; the version is pinned and the tests check that seam.

The reference solution is a list of `robo` commands computed from the scene and the hand.
Its grasp height keeps the fingertips off the table while they swing shut and keeps the cube's top clear of the servo, which hangs beside the finger roots.

## Licenses

This package is MIT, like AnyBuild.
It imports Robo Use (Apache-2.0, with parts under MIT and CC BY 4.0) as a dependency and copies none of its code; a generated task's instruction includes Robo Use's shared `robo` usage text from `robouse.core.prompts`.
