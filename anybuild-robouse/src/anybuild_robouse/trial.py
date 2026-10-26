"""Runs Robo Use on an AnyBuild task, headless: `robouse tasks check` and single trials, through Robo Use's own CLI.

A trial's result is the reward (1 when the episode server judged the goal reached), a verdict, the trial folder and
its video (artifacts/recording.mp4). The reference solution (`oracle`) and the no-op control (`noop`) need no
credentials. An agent harness such as `claude-code` runs a real model on the owner's account, so it starts only when
that harness's credentials are present.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FREE_HARNESSES = ("oracle", "noop")
# What each agent harness logs in with (robouse doctor lists the same); other harnesses check their own.
CREDENTIALS = {
    "claude-code": (("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"), ()),
    "codex": (("OPENAI_API_KEY",), ("~/.codex/auth.json",)),
    "gemini-cli": (("GEMINI_API_KEY",), ()),
}


class TrialError(RuntimeError):
    """The trial could not start or did not produce a result."""


def _robouse(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "robouse.cli", *args], capture_output=capture, text=True, check=False)


def missing_credentials(harness: str) -> str | None:
    """Why an agent harness cannot run here, or None."""

    if harness in FREE_HARNESSES or harness not in CREDENTIALS:
        return None
    names, paths = CREDENTIALS[harness]
    if any(os.environ.get(name) for name in names) or any(Path(path).expanduser().is_file() for path in paths):
        return None
    return harness + " needs " + " or ".join(list(names) + list(paths)) + "; it runs a model on your account."


def check(task_dir: Path, keep_trials: Path | None = None) -> tuple[bool, str]:
    """`robouse tasks check`: the schema, the reference solution scores 1 and the no-op control 0. (valid, report)."""

    args = ["tasks", "check", str(task_dir)]
    if keep_trials is not None:
        args += ["--keep-trials", str(keep_trials)]
    done = _robouse(*args)
    report = (done.stdout + done.stderr).strip()
    return done.returncode == 0 and report.splitlines()[-1:] == ["valid"], report


def run(
    task_dir: Path, harness: str, out: Path, model: str | None = None, timeout: float | None = None, record_size: str | None = None
) -> dict:
    """One trial; returns reward, verdict, outcome, steps, the trial folder and its video (record_size "WxH", else 320x320)."""

    why = missing_credentials(harness)
    if why:
        raise TrialError(why)
    args = ["run", "--task", str(task_dir), "--harness", harness, "--out", str(out)]
    if model:
        args += ["--model", model]
    if timeout:
        args += ["--timeout", str(timeout)]
    if record_size:
        args += ["--record-size", record_size]
    done = _robouse(*args)
    try:
        result = json.loads(done.stdout[done.stdout.index("{") :])
    except ValueError as exc:
        raise TrialError("robouse run printed no result: " + (done.stderr or done.stdout).strip()[-800:]) from exc
    trial = Path(out) / str(result["trial"])
    episode_path = trial / "episode" / "result.json"
    episode = json.loads(episode_path.read_text()) if episode_path.is_file() else {}
    video = trial / "artifacts" / "recording.mp4"
    reward = float(result.get("reward") or 0.0)
    return {
        "task": Path(task_dir).name,
        "harness": harness,
        "reward": reward,
        "verdict": "error" if result.get("exception") else ("pass" if reward >= 1.0 else "fail"),
        "outcome": result.get("outcome"),
        "steps": result.get("steps"),
        "wall_s": result.get("wall_s"),
        "metrics": episode.get("metrics"),
        "trial_dir": str(trial),
        "video": str(video) if video.is_file() else None,
        "exception": result.get("exception"),
    }
