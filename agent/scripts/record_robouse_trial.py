"""Records the Robo Use trials that robouse_trial shows when Robo Use cannot run (agent/data/robouse/recorded/).

    cd agent && uv run python scripts/record_robouse_trial.py            # the example trial
    cd agent && uv run python scripts/record_robouse_trial.py --story    # every design of the 400 g cube story

Both need the bridge's environment (cd anybuild-robouse && uv sync); --story also needs FreeCAD.

The example runs the bridge's example hand, AnyBuild's gripper template at its default sizes with the MG996R and
printed TPU pads (the design the gripper mock story ends with), on the mock story's brief: the 66 mm, 200 g can as
a cube to put in the bowl.

--story plays the mock story "Gripper that puts a 400 g cube into a bowl" (mock_gripper.py) with the real Robo Use,
once for each fix its question offers, and keeps every trial that ran: version 1, which Robo Use fails, and each
fixed design. They are the designs the offline story builds, so its verdicts come from these recordings there.

Each recording is `robouse tasks check` with both trials kept (the video at 960 x 720), copied without this
machine's paths, next to the design and brief it ran on. PAI_ROBOUSE_BIN names another anybuild-robouse.
"""

from __future__ import annotations

import argparse
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
STORY = "Gripper that puts a 400 g cube into a bowl"
# What robouse_trial reads from a trial folder; the rest (agent logs, the server log) stays out. Of the no-op
# control only its reward counts.
KEEP = {
    "oracle": ("result.json", "config.json", "episode/result.json", "episode/trace.jsonl", "episode/physics.jsonl", "episode/frames.jsonl",
               "artifacts/recording.mp4", "artifacts/recording_index.json"),
    "noop": ("result.json", "config.json", "episode/result.json"),
}


def _copy_trial(source: Path, target: Path, harness: str, task: str) -> None:
    for rel in KEEP[harness]:
        if (source / rel).is_file():
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / rel, target / rel)
    config = json.loads((target / "config.json").read_text(encoding="utf-8"))
    # The task folder and the agent's workspace were temporary folders on the recording machine.
    config["task_path"] = "tasks/" + task
    config["workspace"] = ""
    (target / "config.json").write_text(json.dumps(config, indent=1) + "\n", encoding="utf-8")


def _write(target: Path, kept: Path, task: str, report: dict, design: dict) -> None:
    """One recording: both kept trials of `robouse tasks check`, its report and the design it ran on."""

    shutil.rmtree(target, ignore_errors=True)
    for harness in ("oracle", "noop"):
        for trial in sorted((kept / harness).glob("*")):
            _copy_trial(trial, target / harness / trial.name, harness, task)
    (target / "check.json").write_text(json.dumps({**report, "task_dir": "tasks/" + task}, indent=1) + "\n", encoding="utf-8")
    (target / "design.json").write_text(json.dumps(design, indent=1) + "\n", encoding="utf-8")


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
        _write(target, work / "check", RECORDED_TASK, report, _design())
    trial, validity = read_recorded()
    print(f"{RECORDED_TASK}: reward {trial['reward']:g}, reference {validity['reference']:g}, no-op {validity['noop']:g}, "
          f"valid {validity['valid']}, {trial['steps_used']} steps, {len(trial['steps'])} robo requests -> {target}")
    return target


# The 400 g cube story.


def _story_design(state, goal: str) -> dict:
    servo, pads = state.selected["servo"], state.selected["pads"]
    return {
        "hand": "the gripper template built in FreeCAD by the 400 g cube story: " + servo["name"] + ", " + pads["name"],
        "template": "gripper",
        "servo_id": servo["id"],
        "pads_id": pads["id"],
        "params": dict(state.part["params"]),
        "brief": {"object_mass_g": state.brief["object_mass_g"], "object_width_mm": state.brief["object_width_mm"], "goal": goal},
        "story": STORY,
        "recorded_on": date.today().isoformat(),
    }


async def record_story() -> list[Path]:
    """Plays the story once per fix with the real bridge and keeps each trial as it finishes."""

    from pai_agent import mock_gripper
    from pai_agent.bus import EventBus
    from pai_agent.context import Ctx
    from pai_agent.paths import SESSIONS_DIR
    from pai_agent.state import BuildState
    from pai_agent.tools import registry

    if robouse_cli()[0] is None:
        raise SystemExit(robouse_cli()[1])
    saved: dict[str, Path] = {}
    trial_tool = registry.TOOLS["robouse_trial"]

    async def recording(ctx, args: dict) -> dict:
        result = await trial_tool(ctx, args)
        if result.get("status") != "done" or result.get("harness") != "oracle":
            raise SystemExit("Robo Use did not run this trial (" + str(result.get("status")) + "): " + str(result.get("detail")))
        kept = Path(ctx.state.directory) / str(result["id"]) / "check"
        oracle = next((kept / "oracle").glob("*"))
        task = oracle.name.split("__oracle__")[0]
        state = ctx.state
        length = float(state.part["params"]["finger_length_mm"])
        target = RECORDED_DIR / f"{task}--{state.selected['servo']['id']}--{state.selected['pads']['id']}--fingers-{length:g}mm"
        report = {"valid": bool(result["validity"]["valid"]), "check": list(result["validity"]["report"])}
        _write(target, kept, task, report, _story_design(state, str(args.get("goal") or "bowl")))
        saved[target.name] = target
        print(f"{target.name}: verdict {result['verdict']}, reward {result['reward']:g} -> {target}")
        return result

    from pai_agent.tools import blender

    registry.TOOLS["robouse_trial"] = recording
    # FreeCAD builds the part, as the stand-in needs its real kinematics; the render is not part of a trial.
    registry.find_blender = blender.find_blender = lambda: None
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    fixes: list[str] | None = None
    picks: list[str | None] = [None]
    while picks:
        pick = picks.pop(0)
        asked: list[dict] = []

        async def ask(question: dict, pick=pick, asked=asked) -> str:
            # The first question offers the fixes; any later one (a second round, what now) takes its default.
            asked.append(question)
            ids = [option["id"] for option in question["options"]]
            return pick if len(asked) == 1 and pick in ids else str(question.get("default_id") or ids[0])

        with tempfile.TemporaryDirectory(dir=SESSIONS_DIR) as tmp:
            ctx = Ctx(EventBus(), BuildState("record-story", Path(tmp)), auto_steps=False, asker=ask)
            ctx.state.requests.append(STORY)
            ctx.trigger, ctx.label = "chat", STORY
            await mock_gripper.run_gripper_mock(ctx, STORY)
        if fixes is None:
            if not asked:
                raise SystemExit("the story asked for no fix: version 1 passed Robo Use")
            fixes = [option["id"] for option in asked[0]["options"]]
            picks = [fix for fix in fixes if fix != asked[0].get("default_id")]
    registry.TOOLS["robouse_trial"] = trial_tool
    return list(saved.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--story", action="store_true", help="record the designs of the 400 g cube story's fix loop")
    if parser.parse_args().story:
        asyncio.run(record_story())
    else:
        asyncio.run(record())
    sys.exit(0)
