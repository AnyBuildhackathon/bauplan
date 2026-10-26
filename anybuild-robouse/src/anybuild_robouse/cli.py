"""anybuild-robouse: Robo Use tasks and trials for grippers designed in AnyBuild.

    anybuild-robouse task --hand hand.xml --brief brief.json --out tasks/    write a task, then `robouse tasks check` it
    anybuild-robouse task --example --mass-g 200 --width-mm 66 --out tasks/  the same with the bundled example hand
    anybuild-robouse check tasks/<id>                                        reference solution 1, no-op control 0, valid
    anybuild-robouse trial tasks/<id> --harness oracle --out runs/          one headless trial: reward, verdict, video

Every command prints one JSON object. `trial --harness claude-code` (or codex, gemini-cli) runs a real model on the
owner's account and starts only when that harness's credentials are set.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from anybuild_robouse import trial as trials
from anybuild_robouse.hand import HandError, example_hand
from anybuild_robouse.task import GOALS, Brief, TaskError, write_task


def _print(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def _task(a: argparse.Namespace) -> int:
    if bool(a.hand) == bool(a.example):
        raise TaskError("give --hand HAND.xml (exported by AnyBuild) or --example")
    hand = example_hand() if a.example else Path(a.hand).read_text(encoding="utf-8")
    data: dict = json.loads(Path(a.brief).read_text(encoding="utf-8")) if a.brief else {}
    for key, value in (("object_mass_g", a.mass_g), ("object_width_mm", a.width_mm), ("goal", a.goal)):
        if value is not None:
            data[key] = value
    folder = write_task(Path(a.out), hand, Brief.from_dict(data), a.id)
    payload: dict = {"task_dir": str(folder)}
    code = 0
    if not a.no_check:
        valid, report = trials.check(folder)
        payload.update({"valid": valid, "check": report.splitlines()})
        code = 0 if valid else 1
    _print(payload)
    return code


def _check(a: argparse.Namespace) -> int:
    valid, report = trials.check(Path(a.task), Path(a.keep_trials) if a.keep_trials else None)
    _print({"task_dir": a.task, "valid": valid, "check": report.splitlines()})
    return 0 if valid else 1


def _trial(a: argparse.Namespace) -> int:
    result = trials.run(Path(a.task), a.harness, Path(a.out), a.model, a.timeout, a.record_size)
    _print(result)
    return 1 if result["exception"] else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="anybuild-robouse", description="Robo Use tasks and trials for grippers designed in AnyBuild")
    sub = ap.add_subparsers(dest="cmd", required=True)
    tk = sub.add_parser("task", help="write a task from a design brief and the exported hand, then check it")
    tk.add_argument("--hand", metavar="HAND.xml", help="the gripper's MJCF, from agent/scripts/export_gripper_mjcf.py")
    tk.add_argument("--example", action="store_true", help="use the bundled example hand (MG996R, printed TPU pads)")
    tk.add_argument("--brief", metavar="BRIEF.json", help="AnyBuild's gripper brief: object_mass_g, object_width_mm, goal")
    tk.add_argument("--mass-g", type=float, help="object mass in grams (overrides the brief)")
    tk.add_argument("--width-mm", type=float, help="object width in mm (overrides the brief)")
    tk.add_argument("--goal", choices=GOALS, help="put the cube in a bowl (default) or on a pad")
    tk.add_argument("--id", help="task id and folder name (default from the brief)")
    tk.add_argument("--out", required=True, help="folder to write the task folder into")
    tk.add_argument("--no-check", action="store_true", help="skip `robouse tasks check`")
    ck = sub.add_parser("check", help="`robouse tasks check`: schema, reference solution 1, no-op control 0")
    ck.add_argument("task", help="task folder")
    ck.add_argument("--keep-trials", metavar="DIR", help="keep the check's two trials in this folder")
    tr = sub.add_parser("trial", help="run one trial headless and report reward, verdict, trial folder and video")
    tr.add_argument("task", help="task folder")
    tr.add_argument("--harness", default="oracle", help="oracle (default), noop, or an agent harness such as claude-code")
    tr.add_argument("--model", help="model for an agent harness (default: the harness's)")
    tr.add_argument("--timeout", type=float, help="agent wall-clock limit in seconds (default: the task's)")
    tr.add_argument("--record-size", metavar="WxH", help="video size, e.g. 1280x720 (default: 320x320)")
    tr.add_argument("--out", required=True, help="run folder; the trial goes to OUT/<task>__<harness>__<id>/")
    a = ap.parse_args(argv)
    try:
        return {"task": _task, "check": _check, "trial": _trial}[a.cmd](a)
    except (TaskError, HandError, trials.TrialError, OSError, json.JSONDecodeError) as exc:
        print("anybuild-robouse: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
