"""Records the Robo Use trial that robouse_trial shows when Robo Use cannot run (agent/data/robouse/recorded/).

    cd agent && uv run python scripts/record_robouse_trial.py    # needs the bridge's environment: cd anybuild-robouse && uv sync

It runs the bridge's example hand, AnyBuild's gripper template at its default sizes with the MG996R and printed
TPU pads (the design the gripper mock story ends with), on the mock story's brief: the 66 mm, 200 g can as a cube
to put in the bowl. It writes the task, runs `robouse tasks check` with both trials kept (the video at 960 x 720)
and copies what robouse_trial reads, without this machine's paths. PAI_ROBOUSE_BIN names another anybuild-robouse.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from pai_agent.tools.cad_part import LIBRARY
from pai_agent.tools.gripper import gripper_catalog, servo_params
from pai_agent.tools.robouse_trial import RECORDED_DIR, RECORDED_TASK, _payload, _run, read_recorded, robouse_cli, run_check

SERVO, PADS = "towerpro-mg996r", "pads-tpu-printed"
BRIEF = {"object_mass_g": 200.0, "object_width_mm": 66.0, "goal": "bowl"}
# What robouse_trial reads from a trial folder; the rest (agent logs, the server log) stays out. Of the no-op
# control only its reward counts.
KEEP = {
    "oracle": ("result.json", "config.json", "episode/result.json", "episode/trace.jsonl", "episode/physics.jsonl", "episode/frames.jsonl",
               "artifacts/recording.mp4", "artifacts/recording_index.json"),
    "noop": ("result.json", "config.json", "episode/result.json"),
}


def _copy_trial(source: Path, target: Path, harness: str) -> None:
    for rel in KEEP[harness]:
        if (source / rel).is_file():
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / rel, target / rel)
    config = json.loads((target / "config.json").read_text(encoding="utf-8"))
    # The task folder and the agent's workspace were temporary folders on the recording machine.
    config["task_path"] = "tasks/" + RECORDED_TASK
    config["workspace"] = ""
    (target / "config.json").write_text(json.dumps(config, indent=1) + "\n", encoding="utf-8")


def _design() -> dict:
    catalog = {part["id"]: part for part in gripper_catalog()["parts"]}
    params = {key: default for key, (default, _low, _high) in LIBRARY["gripper"]["params"].items()}
    params.update(servo_params(SimpleNamespace(selected={"servo": catalog[SERVO]})))
    return {
        "hand": "anybuild-robouse's example hand: the gripper template at its default sizes, " + catalog[SERVO]["name"] + ", " + catalog[PADS]["name"],
        "template": "gripper",
        "servo_id": SERVO,
        "pads_id": PADS,
        "params": params,
        "brief": BRIEF,
        "recorded_on": date.today().isoformat(),
    }


async def record() -> Path:
    cli, why = robouse_cli()
    if cli is None:
        raise SystemExit(why)
    with tempfile.TemporaryDirectory(prefix="pai-robouse-") as tmp:
        work = Path(tmp)
        command = [str(cli), "task", "--example", "--mass-g", f"{BRIEF['object_mass_g']:g}", "--width-mm", f"{BRIEF['object_width_mm']:g}",
                   "--goal", str(BRIEF["goal"]), "--out", str(work / "tasks"), "--no-check"]
        code, out, err = await _run(command, work, 60.0)
        if code:
            raise SystemExit("anybuild-robouse task failed: " + (err or out).strip())
        task = Path(_payload(out)["task_dir"])
        if task.name != RECORDED_TASK:
            raise SystemExit("unexpected task id " + task.name)
        report = await run_check(cli, task, work / "check", work)
        if not report.get("valid"):
            raise SystemExit("the example task is not valid:\n" + "\n".join(report.get("check") or []))
        target = RECORDED_DIR / RECORDED_TASK
        shutil.rmtree(target, ignore_errors=True)
        for harness in ("oracle", "noop"):
            for trial in sorted((work / "check" / harness).glob("*")):
                _copy_trial(trial, target / harness / trial.name, harness)
        (target / "check.json").write_text(json.dumps({**report, "task_dir": "tasks/" + RECORDED_TASK}, indent=1) + "\n", encoding="utf-8")
        (target / "design.json").write_text(json.dumps(_design(), indent=1) + "\n", encoding="utf-8")
    trial, validity = read_recorded()
    print(f"{RECORDED_TASK}: reward {trial['reward']:g}, reference {validity['reference']:g}, no-op {validity['noop']:g}, "
          f"valid {validity['valid']}, {trial['steps_used']} steps, {len(trial['steps'])} robo requests -> {target}")
    return target


if __name__ == "__main__":
    asyncio.run(record())
    sys.exit(0)
