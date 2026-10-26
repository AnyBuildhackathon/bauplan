"""Robo Use trials: an independent benchmark drives the built gripper and judges the end state.

Robo Use (robouse 0.6.1) turns robotics tasks into tests that a policy runs through the `robo` command; its
episode server judges the physical end state, not what the policy says. The bridge package `anybuild-robouse`
(next to `agent/`, in its own uv environment because Robo Use pins MuJoCo 3.3.0) loads AnyBuild's gripper as a
Robo Use backend and writes the task from the gripper brief: put a cube of the brief's width and mass in a bowl.

`robouse_trial` exports the built gripper as MJCF (`pai_agent.mjcf_export`), writes the task
(`anybuild-robouse task`), runs `robouse tasks check` (the scripted reference solution must score 1, the no-op
control 0) and, only when asked and logged in, one trial with Claude Code as the policy under a time limit.
The trial folder becomes one `trial` event: reward, verdict, the video copied flat into the session's files, the
step track from the episode trace, and the hand's path and contact force from the physics log.

Without the Robo Use environment, or when a step fails, a trial recorded with the same tools
(`agent/data/robouse/recorded/`) stands in as `status: recorded`. It says why and whether it is this design;
unless it is, nothing in it describes this build.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shutil
import signal
import uuid
from bisect import bisect_left
from pathlib import Path

from pai_agent.context import Ctx
from pai_agent.paths import DATA_DIR, REPO_ROOT
from pai_agent.versions import bench_version

RECORDED_DIR = DATA_DIR / "robouse" / "recorded"
# The recorded trial: the gripper mock story's final design (MG996R, printed TPU pads, the template's sizes) and brief.
RECORDED_TASK = "anybuild-gripper-cube-66mm-200g-in-bowl"
# Robo Use's default is the backend's 320 x 320; this reads on a projector and stays near 150 kB for a pick and place.
RECORD_SIZE = "960x720"
HARNESSES = ("oracle", "claude-code")
GOALS = ("bowl", "pad")
# What Claude Code logs in with (robouse doctor checks the same).
CREDENTIALS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
TASK_TIMEOUT_S = 60.0
# `robouse tasks check` runs the reference solution and the no-op control, about 15 s on a quiet machine.
CHECK_TIMEOUT_S = 240.0
AGENT_TIMEOUT_S = 600.0
AGENT_TIMEOUT_MAX_S = 900.0
# Robo Use's scene, verifier and video around an agent's own time limit.
AGENT_OVERHEAD_S = 120.0
# The robo requests the runner itself sends; they are not the policy's steps.
_RUNNER_OPS = {"status"}
# Within these the trace counts a hand move as a lift (mostly up) and the object as resting.
_MOVE_M = 0.005

_TRIAL = re.compile(r"\brobo[\s-]?use\b|\bindependent(?:ly)?\s+(?:test|check|judge|benchmark)", re.IGNORECASE)
_CLAUDE_CODE = re.compile(r"\bclaude[\s-]?code\b", re.IGNORECASE)


class Unavailable(RuntimeError):
    """Robo Use cannot run this trial here; the message says why, and a recorded trial stands in."""


class Refused(ValueError):
    """The task generator refused the brief for this gripper (it cannot take the object at all); the message says why."""


def wants_trial(text: str) -> bool:
    """'Test it in Robo Use', 'an independent test': the offline demo's way to ask for robouse_trial."""

    return bool(_TRIAL.search(text))


def robouse_cli() -> tuple[Path | None, str]:
    """The `anybuild-robouse` command and, when there is none, why.

    PAI_ROBOUSE_BIN names it (`off` turns Robo Use off); otherwise the bridge's own uv environment
    (`cd anybuild-robouse && uv sync`), else the command on PATH (`uv tool install`)."""

    raw = os.environ.get("PAI_ROBOUSE_BIN", "").strip()
    if raw.lower() == "off":
        return None, "Robo Use is turned off here (PAI_ROBOUSE_BIN=off)."
    if raw:
        path = Path(raw).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return path, ""
        return None, "PAI_ROBOUSE_BIN points to " + raw + ", which is not a program."
    bundled = REPO_ROOT / "anybuild-robouse" / ".venv" / "bin" / "anybuild-robouse"
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return bundled, ""
    found = shutil.which("anybuild-robouse")
    if found:
        return Path(found), ""
    return None, "Robo Use is not installed here (cd anybuild-robouse && uv sync)."


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for the bridge's own interpreter: AnyBuild's virtual environment and Python path stay out."""

    env = {k: v for k, v in os.environ.items() if k not in {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT"}}
    env.update(extra or {})
    return env


async def _run(command: list[str], cwd: Path, timeout: float, extra_env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Runs one bridge command in its own process group, so a timeout or Stop also ends the trial's episode server and agent."""

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(cwd),
        env=_env(extra_env),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        _kill(process)
        await process.wait()
        raise
    return process.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _kill(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        process.kill()


def _payload(out: str) -> dict:
    """The one JSON object a bridge command prints."""

    start = out.find("{")
    if start < 0:
        raise ValueError("no JSON")
    value = json.loads(out[start:])
    if not isinstance(value, dict):
        raise ValueError("not an object")
    return value


def _problem(err: str, out: str) -> str:
    text = (err.strip() or out.strip()).splitlines()
    return text[-1].removeprefix("anybuild-robouse: ").strip()[:300] if text else "no output"


def export_hand(state, path: Path) -> None:
    """Writes the built gripper as one MJCF file with the bridge's exporter; Unavailable says why it cannot."""

    try:
        from pai_agent.mjcf_export import ExportError, hand_mjcf
    except ImportError as exc:
        raise Unavailable("This AnyBuild has no MuJoCo export of the gripper yet (pai_agent.mjcf_export).") from exc
    part = state.part or {}
    if not part.get("sim"):
        raise Unavailable("This build declares no joints to simulate: the gripper template does, a part from a custom script does not.")
    servo, pads = state.selected.get("servo"), state.selected.get("pads")
    if not servo or not pads or not state.stl_path:
        raise Unavailable("The gripper needs its servo, its pads and a CAD build before Robo Use can load it.")
    try:
        text = hand_mjcf(part["parts"], part["sim"], (REPO_ROOT / state.stl_path).parent, servo, pads)
    except (ExportError, OSError, KeyError, TypeError, ValueError) as exc:
        raise Unavailable("The gripper could not be exported to MuJoCo: " + str(exc)) from exc
    path.write_text(text, encoding="utf-8")


async def write_task(cli: Path, hand: Path, brief: dict, out: Path, work: Path) -> Path:
    """`anybuild-robouse task`: the task folder for this hand and brief. Refused when the hand cannot take the object."""

    (work / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
    code, out_text, err = await _run(
        [str(cli), "task", "--hand", str(hand), "--brief", str(work / "brief.json"), "--out", str(out), "--no-check"], work, TASK_TIMEOUT_S
    )
    if code == 2:
        raise Refused(_problem(err, out_text))
    try:
        folder = Path(_payload(out_text)["task_dir"])
    except (KeyError, ValueError) as exc:
        raise RuntimeError("anybuild-robouse task failed: " + _problem(err, out_text)) from exc
    if code != 0 or not (folder / "task.md").is_file():
        raise RuntimeError("anybuild-robouse task failed: " + _problem(err, out_text))
    return folder


async def run_check(cli: Path, task: Path, keep: Path, work: Path) -> dict:
    """`robouse tasks check` with both trials kept under `keep` (oracle/, noop/); returns its report.

    The report is valid only when the schema holds, the reference solution scores 1 and the no-op control 0. A gripper
    too weak for the object makes a valid task folder whose reference solution fails: the benchmark finding the flaw."""

    code, out, err = await _run(
        [str(cli), "check", str(task), "--keep-trials", str(keep)], work, CHECK_TIMEOUT_S, {"ROBOUSE_RECORD_SIZE": RECORD_SIZE}
    )
    try:
        report = _payload(out)
    except ValueError as exc:
        raise RuntimeError("robouse tasks check failed: " + _problem(err, out)) from exc
    if code not in (0, 1) or "valid" not in report:
        raise RuntimeError("robouse tasks check failed: " + _problem(err, out))
    return report


async def run_agent(cli: Path, task: Path, harness: str, out: Path, work: Path, timeout_s: float) -> Path:
    """`robouse run` with an agent harness, within `timeout_s` for the agent; returns the trial folder."""

    # Exit 1 is a trial that raised: it still has its folder, and result.json says what happened.
    _code, text, err = await _run(
        [str(cli), "trial", str(task), "--harness", harness, "--out", str(out), "--timeout", f"{timeout_s:g}", "--record-size", RECORD_SIZE],
        work,
        timeout_s + AGENT_OVERHEAD_S,
    )
    try:
        folder = Path(_payload(text)["trial_dir"])
    except (KeyError, ValueError) as exc:
        raise RuntimeError(harness + " trial failed: " + _problem(err, text)) from exc
    if not (folder / "result.json").is_file():
        raise RuntimeError(harness + " trial failed: " + _problem(err, text))
    return folder


# Reading a trial folder (docs/events.md, trial). The same code reads live trials and the recorded one.


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _vec(value) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 3:
        return None
    numbers = [_num(v) for v in value]
    return [round(v, 4) for v in numbers] if all(v is not None for v in numbers) else None  # type: ignore[misc]


def _g(value) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


class _Clock:
    """Env step to video time. The video runs only while the simulator steps, so frames.jsonl, which names the env step
    each frame shows, maps one to the other; without a video the clock is simulated time."""

    def __init__(self, frames: list[dict], fps: float, duration: float, dt: float) -> None:
        pairs = sorted((int(f["i"]), int(f["step"])) for f in frames if _num(f.get("i")) is not None and _num(f.get("step")) is not None)
        self.frames = [i for i, _ in pairs]
        self.steps = [s for _, s in pairs]
        self.fps = fps if fps > 0 else 30.0
        self.duration = duration
        self.dt = dt if dt > 0 else 0.02

    def at(self, step: int) -> float:
        if not self.steps:
            return round(step * self.dt, 3)
        k = bisect_left(self.steps, step)
        if k >= len(self.steps):
            return round(self.duration, 3)
        return round(self.frames[k] / self.fps, 3)


def action_text(req: dict) -> str:
    """A robo request as the command line that sends it."""

    op = str(req.get("op") or "")
    if op == "move_to":
        pos = req.get("pos") or []
        text = "robo move-to " + " ".join(_g(v) for v in pos if _num(v) is not None)
        return text + (" --grip " + _g(req["grip"]) if _num(req.get("grip")) is not None else "")
    if op == "grip":
        return "robo grip " + _g(req.get("value", 0)) + (" --steps " + str(int(req["steps"])) if _num(req.get("steps")) is not None else "")
    if op == "act":
        action = " ".join(_g(v) for v in req.get("action") or [] if _num(v) is not None)
        repeat = int(_num(req.get("repeat")) or 1)
        return "robo act " + action + (" --repeat " + str(repeat) if repeat > 1 else "")
    if op == "observe":
        return "robo observe" + (" --image" if req.get("image") else "")
    if op == "skill":
        return " ".join(["robo skill", str(req.get("name") or ""), *(str(a) for a in req.get("args") or [])]).strip()
    if op in {"done", "give_up"}:
        text = str(req.get("text") or "").strip()
        return "robo " + op.replace("_", "-") + (' "' + text + '"' if text else "")
    return "robo " + op.replace("_", "-")


def _result_text(op: str, resp: dict, state: dict, result: dict) -> str:
    if resp.get("ok") is False:
        return "error: " + str(resp.get("error") or "rejected")[:160]
    if op in {"done", "give_up"}:
        return "episode " + str(result.get("outcome") or "finished")
    bits = []
    if op == "move_to" and "reached" in result:
        bits.append("reached" if result.get("reached") else f"stopped {(_num(result.get('distance')) or 0) * 1000:.0f} mm short")
    hand = _vec(state.get("hand_pos"))
    if hand:
        bits.append("hand at " + ", ".join(f"{v:.3f}" for v in hand) + " m")
    opening = _num(state.get("gripper_open"))
    if opening is not None:
        bits.append(f"open {opening * 100:.0f} %")
    if "holding" in state:
        held = [str(name) for name in state.get("holding") or []]
        bits.append("holding " + (", ".join(held) if held else "nothing"))
    return " · ".join(bits) or "ok"


def _messages(folder: Path) -> dict[int, str]:
    """An agent's own words before each robo request, by trace line (ATIF steps name the trace lines they sent)."""

    out: dict[int, str] = {}
    for step in _json(folder / "agent" / "trajectory.json").get("steps") or []:
        if not isinstance(step, dict) or step.get("source") != "agent":
            continue
        lines = ((step.get("extra") or {}).get("video") or {}).get("trace_lines")
        text = str(step.get("message") or "").strip()
        if text and isinstance(lines, list) and lines and _num(lines[0]) is not None:
            out[int(lines[0]) - 1] = text[:600]
    return out


def read_trial(folder: Path) -> dict:
    """The trial event's fields from one Robo Use trial folder (result.json, config.json, episode/, artifacts/)."""

    result = _json(folder / "result.json")
    if not result:
        raise ValueError("no result.json in " + folder.name)
    config = _json(folder / "config.json")
    episode = result.get("episode") or _json(folder / "episode" / "result.json")
    index = _json(folder / "artifacts" / "recording_index.json")
    video = folder / "artifacts" / "recording.mp4"
    metrics = {k: round(v, 4) for k, v in ((k, _num(v)) for k, v in (episode.get("metrics") or {}).items()) if v is not None}
    harness = str(config.get("harness") or (result.get("agent_info") or {}).get("name") or "oracle")
    reward = _num(((result.get("verifier_result") or {}).get("rewards") or {}).get("reward")) or 0.0
    duration = _num(index.get("duration_s")) or 0.0
    clock = _Clock(_jsonl(folder / "episode" / "frames.jsonl"), _num(index.get("fps")) or 30.0, duration, metrics.get("control_dt_s", 0.02))
    messages = _messages(folder) if harness not in {"oracle", "noop"} else {}

    steps: list[dict] = []
    before = 0
    for line, row in enumerate(_jsonl(folder / "episode" / "trace.jsonl")):
        req = row.get("req") if isinstance(row.get("req"), dict) else {}
        op = str(req.get("op") or "")
        if not op or op in _RUNNER_OPS:
            continue
        resp = row.get("resp") if isinstance(row.get("resp"), dict) else {}
        result_ = resp.get("result") if isinstance(resp.get("result"), dict) else {}
        state = result_.get("state") if isinstance(result_.get("state"), dict) else {}
        after = int(_num(row.get("steps")) or before)
        objects = state.get("objects") if isinstance(state.get("objects"), dict) else {}
        steps.append(
            {
                "index": len(steps) + 1,
                "op": op,
                "action": action_text(req),
                "result": _result_text(op, resp, state, result_),
                "ok": resp.get("ok") is not False,
                "t_start": clock.at(before),
                "t_end": clock.at(after),
                "env_steps": [before, after],
                "hand_pos": _vec(state.get("hand_pos")),
                "gripper_open": _num(state.get("gripper_open")),
                "holding": [str(n) for n in state.get("holding") or []] if "holding" in state else None,
                "objects": {str(k): _vec(v.get("pos")) for k, v in objects.items() if isinstance(v, dict)},
                "message": messages.get(line),
                "_state": state,
                "_req": req,
            }
        )
        before = max(before, after)

    ee_path, force = [], []
    for row in _jsonl(folder / "episode" / "physics.jsonl"):
        step, ee = _num(row.get("i")), _vec(row.get("ee"))
        if step is None or ee is None:
            continue
        t = clock.at(int(step))
        ee_path.append([t, *ee])
        f = _num(row.get("f"))
        if f is not None:
            force.append([t, round(f, 3)])

    meta = (config.get("metadata") or {}).get("anybuild") or {}
    brief = meta.get("brief") or {}
    scene = _scene(steps)
    trial = {
        "robouse_trial": str(result.get("trial_name") or folder.name),
        "task_id": str(result.get("task_name") or episode.get("task") or ""),
        "harness": harness,
        "reward": round(reward, 3),
        "success": bool(episode.get("success")),
        "outcome": episode.get("outcome"),
        "steps_used": int(_num(episode.get("steps_used")) or 0),
        "max_steps": int(_num(episode.get("max_steps")) or 0),
        "wall_s": _num(result.get("wall_time_s")),
        "metrics": metrics,
        "agent_text": str(episode.get("agent_text") or "")[:300],
        "exception": _exception(result.get("exception_info")),
        "video": video if video.is_file() and video.stat().st_size > 0 else None,
        "video_info": {"fps": clock.fps, "duration_s": duration, "size": index.get("size") or episode.get("video_size")},
        "steps": steps,
        "ee_path": ee_path,
        "force": force,
        "scene": scene,
        "design": {
            "servo": meta.get("servo"),
            "pads": meta.get("pads"),
            "opening_mm": _num(meta.get("opening_mm")),
            "object_mass_g": _num(brief.get("object_mass_g")),
            "object_width_mm": _num(brief.get("object_width_mm")),
            "goal": brief.get("goal") or "bowl",
        },
        "provenance": {k: v for k, v in (config.get("provenance") or {}).items() if k in {"robouse", "mujoco"}},
        "ran_at": result.get("started_at"),
    }
    trial["analysis"] = analyse(steps, scene)
    return trial


def _exception(info) -> str | None:
    if not info:
        return None
    if isinstance(info, dict):
        info = info.get("exception_message") or info.get("message") or info.get("exception_type") or info
    return str(info)[:300]


def _scene(steps: list[dict]) -> dict:
    """The object, its sampled path (its place after every request) and the target, from the trace's states."""

    first = next((s["_state"] for s in steps if s["_state"].get("objects")), {})
    objects = first.get("objects") or {}
    name, obj = next(iter(objects.items()), (None, None))
    target_name, target = next(iter((first.get("fixtures") or {}).items()), (None, None))
    scene: dict = {"object": None, "target": None}
    if name and isinstance(obj, dict):
        path = []
        for s in steps:
            pos = s["objects"].get(name)
            if pos:
                path.append([s["t_end"], *pos])
        if path and not (steps[0]["holding"] or []):
            path.insert(0, [0.0, *path[0][1:]])
        scene["object"] = {"name": name, "kind": obj.get("kind"), "color": obj.get("color"), "size_m": _vec(obj.get("size")), "path": path}
    if target_name and isinstance(target, dict):
        scene["target"] = {
            "name": target_name,
            "kind": target.get("kind"),
            "pos": _vec(target.get("pos")) or [0.0, 0.0, 0.0],
            "floor_z": _num(target.get("floor_z")),
            "rim_z": _num(target.get("rim_z")),
            "inner_diameter_m": _num(target.get("inner_diameter")),
            "size_m": [_num(v) for v in target.get("size")] if isinstance(target.get("size"), list) else None,
        }
    return scene


def analyse(steps: list[dict], scene: dict) -> dict:
    """What the trace shows happened to the object: held or not, slip in the lift, where it fell, where it ended."""

    obj = (scene.get("object") or {}).get("name")
    out = {"held": False, "lift_slip_mm": None, "dropped": None, "released": False, "distance_mm": None}
    if not obj:
        return out
    offset = None
    slip = 0.0
    for k, s in enumerate(steps):
        hand, pos = s["hand_pos"], s["objects"].get(obj)
        held = obj in (s["holding"] or [])
        if held and offset is None and hand and pos:
            out["held"] = True
            offset = hand[2] - pos[2]
            continue
        if offset is None or out["dropped"] or out["released"]:
            continue
        before = steps[k - 1]["hand_pos"]
        if s["op"] == "grip" and (_num(s["_req"].get("value")) or 0) < 0:
            out["released"] = True
            continue
        if not hand or not before:
            continue
        rise = hand[2] - before[2]
        across = math.hypot(hand[0] - before[0], hand[1] - before[1])
        if held and pos and rise > _MOVE_M and rise > across:
            slip = max(slip, (hand[2] - pos[2]) - offset)
        if not held and s["holding"] is not None:
            out["dropped"] = "lift" if rise > max(across, _MOVE_M) else "lowering" if -rise > max(across, _MOVE_M) else "carry"
    if out["held"]:
        out["lift_slip_mm"] = round(max(0.0, slip) * 1000.0, 1)
    target = scene.get("target")
    final = next((s["objects"].get(obj) for s in reversed(steps) if s["objects"].get(obj)), None)
    if target and final:
        out["distance_mm"] = round(math.hypot(final[0] - target["pos"][0], final[1] - target["pos"][1]) * 1000.0, 0)
    return out


def check_validity(report: dict, keep: Path) -> tuple[dict, Path | None]:
    """Validity from `robouse tasks check` and its kept trials: {reference, noop, valid, report}, and the reference trial's folder."""

    rewards: dict[str, float | None] = {}
    folders: dict[str, Path] = {}
    for harness in ("oracle", "noop"):
        folder = next((p for p in sorted((keep / harness).glob("*")) if (p / "result.json").is_file()), None)
        result = _json(folder / "result.json") if folder else {}
        rewards[harness] = _num(((result.get("verifier_result") or {}).get("rewards") or {}).get("reward"))
        if folder:
            folders[harness] = folder
    lines = report.get("check") if isinstance(report.get("check"), list) else []
    validity = {"reference": rewards["oracle"], "noop": rewards["noop"], "valid": bool(report.get("valid")), "report": [str(l) for l in lines][:12]}
    return validity, folders.get("oracle")


def verdict(trial: dict, validity: dict | None) -> str:
    """pass or fail on the trial's own reward; invalid when the no-op control scored, so the task tests nothing."""

    if validity and (validity.get("noop") or 0) >= 1:
        return "invalid"
    return "pass" if trial["reward"] >= 1.0 else "fail"


_WHO = {"oracle": "The reference solution", "claude-code": "Claude Code", "noop": "The no-op control"}


def summary(trial: dict, outcome: str, gripper: str = "this gripper") -> str:
    """One sentence on what happened, from the trace, for the card and for Mechanic; `gripper` names the hand it ran with."""

    who = _WHO.get(trial["harness"], trial["harness"])
    design = trial["design"]
    goal = "in the bowl" if design.get("goal") != "pad" else "on the pad"
    target = "the bowl" if design.get("goal") != "pad" else "the pad"
    a = trial["analysis"]
    peak = trial["metrics"].get("max_contact_force_n")
    if outcome == "invalid":
        return "Not counted: the no-op control scores too, so this task does not test the gripper."
    if outcome == "pass":
        tail = f", {a['lift_slip_mm']:.1f} mm slip in the lift" if a.get("lift_slip_mm") is not None else ""
        tail += f", peak contact {peak:.1f} N" if peak is not None else ""
        return f"{who} put the cube {goal} with {gripper} in {trial['steps_used']} of {trial['max_steps']} steps{tail}."
    prefix = f"Even the reference solution fails with {gripper}: " if trial["harness"] == "oracle" else who + " failed: "
    where = f", {a['distance_mm'] / 10:.0f} cm from the middle of {target}" if a.get("distance_mm") is not None else ""
    if a.get("dropped"):
        slip = a.get("lift_slip_mm") or 0
        start = f"the cube slipped {slip:.1f} mm in the fingers during the lift and" if slip >= 0.5 else "the cube"
        return f"{prefix}{start} fell out during the {a['dropped']}{where}."
    if not a.get("held"):
        return f"{prefix}the fingers never held the cube."
    if trial["max_steps"] and trial["steps_used"] >= trial["max_steps"]:
        return f"{prefix}the step budget ran out ({trial['steps_used']} of {trial['max_steps']}) before the cube was {goal}."
    return f"{prefix}the cube ended outside {target}{where}."


def public(trial: dict) -> dict:
    """The trial without the folder's internals: steps without their raw request and state."""

    steps = [{k: v for k, v in s.items() if not k.startswith("_")} for s in trial["steps"]]
    return {**{k: v for k, v in trial.items() if k not in {"video", "steps"}}, "steps": steps}


# The recorded stand-in.


def _recorded_design() -> dict:
    return _json(RECORDED_DIR / RECORDED_TASK / "design.json")


def matches_recorded(state, goal: str) -> bool:
    """True when the bench holds the design and brief the recorded trial ran with: same servo, pads, sizes and object."""

    design = _recorded_design()
    part = state.part or {}
    brief = design.get("brief") or {}
    if state.product != "gripper" or part.get("template") != "gripper" or not design:
        return False
    if (state.selected.get("servo") or {}).get("id") != design.get("servo_id") or (state.selected.get("pads") or {}).get("id") != design.get("pads_id"):
        return False
    params = part.get("params") or {}
    for key, value in (design.get("params") or {}).items():
        mine = _num(params.get(key))
        if mine is None or abs(mine - float(value)) > 0.05:
            return False
    mine = state.brief or {}
    return (
        goal == brief.get("goal", "bowl")
        and abs((_num(mine.get("object_mass_g")) or 0.0) - float(brief.get("object_mass_g", 0))) < 0.5
        and abs((_num(mine.get("object_width_mm")) or 0.0) - float(brief.get("object_width_mm", 0))) < 0.5
    )


def read_recorded() -> tuple[dict, dict]:
    """The recorded reference trial and its validity check."""

    folder = RECORDED_DIR / RECORDED_TASK
    validity, oracle = check_validity(_json(folder / "check.json"), folder)
    if oracle is None:
        raise ValueError("the recorded trial is missing")
    return read_trial(oracle), validity


# The tool.


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message}


def _bench_design(state, goal: str) -> dict:
    brief = state.brief or {}
    return {
        "servo": (state.selected.get("servo") or {}).get("name"),
        "pads": (state.selected.get("pads") or {}).get("name"),
        "opening_mm": _num(((state.part or {}).get("params") or {}).get("jaw_opening_mm")),
        "object_mass_g": _num(brief.get("object_mass_g")),
        "object_width_mm": _num(brief.get("object_width_mm")),
        "goal": goal,
    }


def _title(goal: str) -> str:
    return "Put the cube " + ("in the bowl" if goal == "bowl" else "on the pad")


def _copy_video(ctx: Ctx, video: Path | None, tid: str) -> str | None:
    if video is None:
        return None
    shutil.copyfile(video, Path(ctx.state.directory) / (tid + ".mp4"))
    return f"/files/{ctx.state.session_id}/{tid}.mp4"


def _event(ctx: Ctx, base: dict, trial: dict, validity: dict | None, status: str, detail: str, recorded: dict | None = None) -> dict:
    outcome = verdict(trial, validity)
    # A recorded trial of another design ran with AnyBuild's example gripper, never with the one on the bench.
    gripper = "AnyBuild's example gripper" if recorded and not recorded["matches_build"] else "this gripper"
    return {
        **base,
        **public(trial),
        "status": status,
        "stage": None,
        "task_title": _title(trial["design"].get("goal") or "bowl"),
        "verdict": outcome,
        "summary": summary(trial, outcome, gripper),
        "validity": validity,
        "video_url": _copy_video(ctx, trial["video"], base["id"]),
        "detail": detail,
        "recorded": recorded,
        "error": None,
    }


def _design_text(design: dict) -> str:
    """'TowerPro MG996R servo, printed TPU finger pads, 76 mm jaw, 66 mm 200 g cube'."""

    pads = str(design.get("pads") or "")
    # "Printed TPU finger pads" reads "printed TPU finger pads" mid-sentence; an acronym keeps its case.
    pieces = [str(design.get("servo") or ""), pads[:1].lower() + pads[1:] if pads[1:2].islower() else pads]
    if design.get("opening_mm") is not None:
        pieces.append(f"{design['opening_mm']:g} mm jaw")
    if design.get("object_width_mm") is not None and design.get("object_mass_g") is not None:
        pieces.append(f"{design['object_width_mm']:g} mm {design['object_mass_g']:g} g cube")
    return ", ".join(p for p in pieces if p)


def _answer(event: dict, next_step: str) -> dict:
    """What the model reads: the verdict and the numbers, not the paths and series the dashboard draws."""

    keys = ("id", "status", "harness", "verdict", "reward", "outcome", "steps_used", "max_steps", "wall_s", "summary", "detail", "validity", "analysis", "design", "recorded", "error")
    metrics = {k: v for k, v in (event.get("metrics") or {}).items() if k in {"max_contact_force_n", "safety_events", "path_length_m"}}
    return {"ok": True, **{k: event.get(k) for k in keys if k in event}, "metrics": metrics, "next": next_step}


async def _recorded(ctx: Ctx, base: dict, reason: str, goal: str) -> dict:
    try:
        trial, validity = await asyncio.to_thread(read_recorded)
    except (OSError, ValueError) as exc:
        message = reason + " The recorded trial could not be read either: " + str(exc)
        await ctx.emit({**base, "status": "failed", "stage": None, "detail": message, "error": message})
        return _fail(message)
    same = matches_recorded(ctx.state, goal)
    version = trial["provenance"].get("robouse")
    detail = (
        reason
        + " Nothing ran now: this trial was recorded earlier with Robo Use"
        + (" " + str(version) if version else "")
        + (" on this same design (" if same else " on AnyBuild's example gripper (")
        + _design_text(trial["design"])
        + (")." if same else "), not on this build.")
    )
    event = _event(ctx, base, trial, validity, "recorded", detail, {"matches_build": same, "reason": reason})
    await ctx.emit(event)
    told = "the same design as the bench" if same else "a different design, so none of its numbers describe this build"
    return _answer(
        event,
        "This is a recorded trial of " + told + ". Say in one sentence that Robo Use did not run now and why; do not quote its numbers as this build's.",
    )


async def robouse_trial(ctx: Ctx, args: dict) -> dict:
    state = ctx.state
    harness = str(args.get("harness") or "oracle").strip()
    goal = str(args.get("goal") or "bowl").strip()
    if harness not in HARNESSES:
        return _fail("harness must be one of " + ", ".join(HARNESSES) + ".")
    if goal not in GOALS:
        return _fail("goal must be one of " + ", ".join(GOALS) + ".")
    try:
        timeout_s = min(AGENT_TIMEOUT_MAX_S, max(60.0, float(args.get("timeout_s") or AGENT_TIMEOUT_S)))
    except (TypeError, ValueError):
        return _fail("timeout_s must be a number of seconds.")
    if state.product != "gripper" or not state.part:
        return _fail("Robo Use tests a built gripper: run product_brief for the gripper, its parts and cad_part with template gripper first.")
    mass, width = (_num((state.brief or {}).get(key)) for key in ("object_mass_g", "object_width_mm"))
    if not mass or not width or mass <= 0 or width <= 0:
        return _fail("The gripper brief needs object_mass_g and object_width_mm: run product_brief for the gripper first.")

    tid = "trial-" + uuid.uuid4().hex[:12]
    base = {"type": "trial", "id": tid, "requested_harness": harness, "version": bench_version(state)}
    cli, why = robouse_cli()
    if cli is None:
        return await _recorded(ctx, base, why, goal)

    work = Path(state.directory) / tid
    work.mkdir(parents=True, exist_ok=True)
    running = {**base, "status": "running", "harness": harness, "task_title": _title(goal), "design": _bench_design(state, goal), "validity": None}

    async def stage(name: str, detail: str) -> None:
        await ctx.emit({**running, "stage": name, "detail": detail})

    notes: list[str] = []
    try:
        await stage("export", "Exporting the built gripper to MuJoCo: its meshes, finger hinges, gears and the servo's holding torque.")
        await asyncio.to_thread(export_hand, state, work / "hand.xml")
        brief = {"object_mass_g": mass, "object_width_mm": width, "goal": goal}
        await stage("task", "Writing the Robo Use task from the brief: " + _title(goal).lower() + ".")
        task = await write_task(cli, work / "hand.xml", brief, work / "tasks", work)
        await stage("check", "robouse tasks check: the scripted reference solution must score 1, doing nothing 0.")
        report = await run_check(cli, task, work / "check", work)
        validity, reference = check_validity(report, work / "check")
        if reference is None:
            raise RuntimeError("robouse tasks check kept no reference trial.")
        shown = reference
        if harness == "claude-code":
            if not validity["valid"]:
                notes.append("Claude Code did not run: the task is not valid for this gripper, so an agent's result would not count.")
            elif not any(os.environ.get(name) for name in CREDENTIALS):
                notes.append("Claude Code did not run: it needs " + " or ".join(CREDENTIALS) + " and runs a model on your account.")
            else:
                await stage("agent", f"Claude Code drives the gripper through robo, at most {timeout_s / 60:g} min.")
                shown = await run_agent(cli, task, harness, work / "agent", work, timeout_s)
        trial = await asyncio.to_thread(read_trial, shown)
    except Refused as exc:
        message = "Robo Use cannot pose this task for this gripper: " + str(exc)
        event = {**running, "status": "failed", "stage": None, "verdict": "refused", "summary": message, "detail": message, "error": message}
        await ctx.emit(event)
        return _answer(event, "The design cannot take the object at all. Name the reason, then change the design (opening, finger length) or the brief.")
    except TimeoutError:
        return await _recorded(ctx, base, "Robo Use took longer than its time limit.", goal)
    except OSError as exc:
        return await _recorded(ctx, base, "Robo Use could not start: " + str(exc) + ".", goal)
    except (RuntimeError, ValueError) as exc:
        return await _recorded(ctx, base, str(exc), goal)

    ran = {"oracle": "the reference solution", "claude-code": "Claude Code"}.get(trial["harness"], trial["harness"])
    version = trial["provenance"].get("robouse")
    detail = " ".join(["Robo Use" + (" " + str(version) if version else "") + " ran " + ran + " on this build.", *notes])
    event = _event(ctx, base, trial, validity, "done", detail)
    await ctx.emit(event)
    outcome = event["verdict"]
    if outcome == "pass":
        next_step = "Name the verdict and the reward in one sentence; the Simulation tab's Robo Use pane shows the video."
    elif outcome == "invalid":
        next_step = "Say the task is not counted (the no-op control scores) and do not judge the design on it."
    else:
        next_step = "Name the cause in one sentence from summary and analysis, then propose a fix (a stronger servo, longer or wider pads, a smaller object) and test again."
    return _answer(event, next_step)


async def run_trial_mock(ctx: Ctx, text: str = "") -> None:
    """'Test it in Robo Use' without a key: the same tool, with Mechanic's lines around it. Claude Code drives the
    gripper only when the prompt names it, and only where its credentials are set."""

    from pai_agent.tools.registry import call_tool

    state = ctx.state
    if state.product != "gripper" or not state.part:
        await call_tool(ctx, "mascot_say", {"state": "erklaert", "say": "Robo Use needs a built gripper first."})
        await ctx.chat(
            "agent",
            "Robo Use tests a gripper AnyBuild has built, in its own physics. Ask me for one first, "
            "like 'Design a robot gripper that picks up a 200 g soda can, 66 mm wide', then ask again.",
        )
        return
    brief = state.brief or {}
    await call_tool(ctx, "mascot_say", {"state": "denkt", "say": "An outside judge. Let's see what it says."})
    await ctx.chat(
        "agent",
        f"Independent test in Robo Use: its own MuJoCo scene, a task written from your brief (put the {brief.get('object_width_mm', 66):g} mm, "
        f"{brief.get('object_mass_g', 200):g} g cube in the bowl), judged on where the cube ends up. The scripted reference solution has to score 1 and doing nothing 0.",
    )
    result = await call_tool(ctx, "robouse_trial", {"harness": "claude-code"} if _CLAUDE_CODE.search(text) else {})
    if result.get("ok") is False:
        await call_tool(ctx, "mascot_say", {"state": "besorgt", "say": "Robo Use could not run."})
        await ctx.chat("agent", "Robo Use could not run: " + str(result.get("error")))
        return
    outcome = result.get("verdict")
    if result.get("status") == "recorded":
        await call_tool(ctx, "mascot_say", {"state": "erklaert", "say": "A recorded run. Nothing ran just now."})
        if (result.get("recorded") or {}).get("matches_build"):
            line = "Robo Use did not run on this machine, so this is the trial recorded earlier on this same design. " + str(result.get("summary") or "")
        else:
            line = "Robo Use did not run on this machine, and the recorded trial is of AnyBuild's example gripper, so it does not judge this build."
        await ctx.chat("agent", line)
        return
    mood = {"pass": "freut_sich", "fail": "besorgt"}.get(str(outcome), "erklaert")
    say = {"pass": "Robo Use says it works.", "fail": "Robo Use found a flaw.", "refused": "It cannot even take the cube."}.get(str(outcome), "Not counted.")
    await call_tool(ctx, "mascot_say", {"state": mood, "say": say})
    await ctx.chat("agent", str(result.get("summary") or result.get("detail") or ""))


SCHEMA = {
    "name": "robouse_trial",
    "description": (
        "Independent test of the built gripper in Robo Use, a robotics benchmark whose own MuJoCo scene and episode server judge the end state. "
        "Exports the gripper from its CAD (meshes, finger hinges, gears, the servo's holding torque), writes the task from the brief "
        "(put the brief's cube in a bowl, or on a pad), and checks it: the scripted reference solution must score 1 and doing nothing 0. "
        "harness oracle (default) shows the reference solution's trial; claude-code also lets Claude Code drive the gripper through Robo Use's robo command, "
        "taking minutes and running a model on the account, so use it only when the user asks for an agent to drive it. "
        "Call it after cad_part built the gripper from its template. Returns verdict (pass, fail, invalid, refused), reward, a one-sentence summary, "
        "the analysis (held, lift_slip_mm, dropped, distance_mm) and status: recorded means Robo Use did not run now and a recorded trial stands in."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "harness": {"type": "string", "enum": list(HARNESSES)},
            "goal": {"type": "string", "enum": list(GOALS)},
            "timeout_s": {"type": "number", "minimum": 60, "maximum": AGENT_TIMEOUT_MAX_S, "description": "Claude Code's time limit, default 600 s."},
        },
    },
}
