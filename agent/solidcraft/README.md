# SolidCraft in AnyBuild

[SolidCraft](https://github.com/tangency-labs/solidcraft) is open-source parametric CAD in Rust with a feature timeline, joints, motion links, motion studies and a URDF export.
With `PAI_CAD_ENGINE=solidcraft`, Mechanic builds parts that move on joints in it (`solidcraft_part`) and turns them into a robot description that runs in MuJoCo (`export_urdf`).
FreeCAD stays the default engine and keeps the printed parts of a product spec.

## Install

```bash
bash agent/scripts/setup_solidcraft.sh
```

The script downloads `solidcraft-cli` 0.23.0 from SolidCraft's GitHub release, checks its SHA-256, and keeps the CLI and its licence texts in `~/.cache/anybuild/solidcraft/0.23.0` (`SOLIDCRAFT_DIR` names another folder, `SOLIDCRAFT_CLI` another binary).
On macOS it thins the universal binary to the Mac's own architecture (about 100 MB).
Nothing of SolidCraft is linked into AnyBuild or shipped with it; AnyBuild runs the CLI as a separate program.
Without it, both tools answer `ok: false` with the install hint.

## What is in this folder

| Path | What | Origin |
| --- | --- | --- |
| `skills/solidcraft-modeling/` | `SKILL.md` and `reference.md`: how to build a part with SolidCraft's commands, their shapes and traps | SolidCraft, unchanged |
| `skills/solidcraft-mechanisms/` | `SKILL.md` and `reference.md`: components, joints, motion links, loops and motion studies | SolidCraft, unchanged |
| `library/chebyshev-motion-trace.json` | The Chebyshev four-bar linkage, SolidCraft's example `examples/chebyshev-motion-trace.json` (template `four_bar`) | SolidCraft, unchanged |
| `library/two-finger-gripper.json` | A two-finger gripper on meshing gears with a motion study (template `two_finger_gripper`) | AnyBuild |
| `LICENSE-SolidCraft` | SolidCraft's MIT licence text | SolidCraft |

The SolidCraft files are copies of tag `v0.23.0` (commit `7770f8982de8bf00cabfe421b7f563b34c7af90f`), Copyright (c) 2026 SolidCraft contributors, used under the MIT License (SolidCraft is MIT OR Apache-2.0); the licence text is in `LICENSE-SolidCraft`.
The CAD agent that writes SolidCraft scripts reads both skills as its instructions (`agent/src/pai_agent/tools/solidcraft_part.py`).
They were written for SolidCraft's MCP tools; AnyBuild's own rules, which come first in those instructions, say how they apply to a whole script.

## How a design runs

- `solidcraft.py` checks a script (only commands that model, assemble, move and measure, none that names a path) and runs it with `solidcraft-cli` in a scratch folder with a scrubbed environment, on macOS inside `sandbox-exec`.
  A build gives STEP, STL, one STL per body, a GLB, the `.solidcraft` design (it opens in SolidCraft with its timeline), the script and SolidCraft's picture.
- `export_robot` writes SolidCraft's URDF; `solidcraft_mjcf.py` has MuJoCo turn it into MJCF and puts back what a URDF cannot hold: each joint that closes a loop (an equality weld fixes it, an equality connect for a ball joint), the motion links as joint couplings, and the pose as built.
- `check_mjcf` drives the design's motion study in MuJoCo and compares every part with SolidCraft's own poses, the loop gaps, the couplings, each joint's travel and each link's mass against SolidCraft's `measure`.
- `agent/scripts/record_solidcraft_fixtures.py` records the exports the offline tests run on (`agent/tests/fixtures/solidcraft/`).
