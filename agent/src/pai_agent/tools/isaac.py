"""Isaac Lab and Isaac Sim over SSH. Offline runs serve agent/runs/fallback."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

from pai_agent.context import Ctx
from pai_agent.env import pace_seconds
from pai_agent.paths import FALLBACK_DIR, FALLBACK_TRAINING

_REWARD = re.compile(
    r"(?:Mean reward|mean_reward|Episode_Reward/mean)[^\d\-]*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_ITERATION = re.compile(r"(?:Iteration|iteration)\s*[:= ]\s*(\d+)")


def _configured() -> bool:
    return bool(os.environ.get("RUNPOD_SSH_HOST", "").strip())


def _ssh_base() -> list[str]:
    host = os.environ["RUNPOD_SSH_HOST"].strip()
    port = os.environ.get("RUNPOD_SSH_PORT", "").strip() or "22"
    user = os.environ.get("RUNPOD_SSH_USER", "").strip() or "root"
    key = os.environ.get("RUNPOD_SSH_KEY", "").strip()
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=8",
        "-p",
        port,
    ]
    if key:
        command.extend(["-i", key])
    command.append(user + "@" + host)
    return command


def _scp_base() -> list[str]:
    port = os.environ.get("RUNPOD_SSH_PORT", "").strip() or "22"
    key = os.environ.get("RUNPOD_SSH_KEY", "").strip()
    command = ["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-P", port]
    if key:
        command.extend(["-i", key])
    return command


def _remote(path: str) -> str:
    user = os.environ.get("RUNPOD_SSH_USER", "").strip() or "root"
    host = os.environ["RUNPOD_SSH_HOST"].strip()
    return user + "@" + host + ":" + path


def _run(command: list[str], script: str, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=script,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _load_fallback() -> dict | None:
    if not FALLBACK_TRAINING.is_file():
        return None
    payload = json.loads(FALLBACK_TRAINING.read_text(encoding="utf-8"))
    video_name = str(payload.get("video") or "")
    video_path = FALLBACK_DIR / video_name if video_name else None
    video_url = None
    if video_path is not None and video_path.is_file():
        video_url = "/files/fallback/hover.mp4"
    return {
        "curve": payload.get("curve") or [],
        "video_url": video_url,
        "task": payload.get("task") or "Isaac-Quadcopter-Direct-v0",
    }


async def _emit_curve(ctx: Ctx, status: str, curve: list, video_url: str | None, final: bool) -> None:
    step = curve[-1][0] if curve else 0
    reward = curve[-1][1] if curve else 0
    await ctx.emit(
        {
            "type": "training",
            "status": status,
            "step": step,
            "reward": reward,
            "curve": curve if final else curve,
            "video_url": video_url if final else None,
        }
    )


async def _serve_fallback(ctx: Ctx, detail: str) -> dict:
    fallback = _load_fallback()
    if fallback is None:
        await ctx.emit(
            {
                "type": "training",
                "status": "offline",
                "step": 0,
                "reward": 0,
                "curve": [],
                "video_url": None,
            }
        )
        return {
            "ok": True,
            "status": "offline",
            "served": False,
            "detail": detail + " Kein Fallback unter agent/runs/fallback.",
        }
    curve = fallback["curve"]
    paced = curve if len(curve) <= 6 else curve[:: max(1, len(curve) // 6)]
    if curve and paced[-1] != curve[-1]:
        paced = [*paced, curve[-1]]
    for index, _point in enumerate(paced):
        last = index == len(paced) - 1
        prefix = curve if last else [item for item in curve if item[0] <= paced[index][0]]
        await _emit_curve(
            ctx,
            "done" if last else "running",
            prefix,
            fallback["video_url"],
            last,
        )
        delay = pace_seconds()
        if delay:
            await asyncio.sleep(delay)
    final_reward = curve[-1][1] if curve else 0
    return {
        "ok": True,
        "status": "offline",
        "served": True,
        "detail": detail,
        "training_status": "done",
        "final_reward": final_reward,
        "video_url": fallback["video_url"],
        "task": fallback["task"],
    }


def _parse_curve(log_text: str) -> list[list[float]]:
    iterations = [int(match) for match in _ITERATION.findall(log_text)]
    rewards = [float(match) for match in _REWARD.findall(log_text)]
    curve = []
    for index, reward in enumerate(rewards):
        step = iterations[index] if index < len(iterations) else index * 10
        curve.append([step, round(reward, 4)])
    return curve


def _start_script(job_id: str) -> str:
    return f"""
set -eu
RUN="$HOME/pai-runs/{job_id}"
mkdir -p "$RUN"
cd "$HOME/IsaacLab"
export OMNI_KIT_ACCEPT_EULA=YES
nohup uv run --extra isaacsim isaaclab train \\
  --rl_library rsl_rl \\
  --task Isaac-Quadcopter-Direct-v0 \\
  --headless \\
  --video \\
  --video_length 200 \\
  > "$RUN/train.log" 2>&1 < /dev/null &
echo $! > "$RUN/pid"
echo "$RUN"
"""


def _status_script(job_id: str) -> str:
    return f"""
set -eu
RUN="$HOME/pai-runs/{job_id}"
if [ ! -f "$RUN/pid" ]; then
  echo PAI_STATUS missing
  exit 0
fi
pid=$(cat "$RUN/pid")
if kill -0 "$pid" 2>/dev/null; then
  echo PAI_STATUS running
else
  echo PAI_STATUS exited
fi
echo PAI_LOG_BEGIN
tail -n 80 "$RUN/train.log" 2>/dev/null || true
echo PAI_LOG_END
echo PAI_VIDEO_BEGIN
find "$HOME/IsaacLab/logs" "$RUN" -name '*.mp4' -type f 2>/dev/null | head -n 5
echo PAI_VIDEO_END
"""


async def isaac_lab_train(ctx: Ctx, args: dict) -> dict:
    del args
    if not _configured():
        return await _serve_fallback(
            ctx,
            "RunPod ist nicht konfiguriert. Fallback-Lauf wird abgespielt.",
        )
    job_id = os.urandom(6).hex()
    try:
        completed = _run(_ssh_base() + ["bash", "-s"], _start_script(job_id), timeout=25)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return await _serve_fallback(ctx, "SSH zum Pod ist fehlgeschlagen (" + str(exc) + ").")
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip()[-400:]
        return await _serve_fallback(ctx, "Der Pod hat den Job nicht gestartet. " + tail)
    ctx.state.isaac_job_id = job_id
    await ctx.emit(
        {
            "type": "training",
            "status": "queued",
            "step": 0,
            "reward": 0,
            "curve": [],
            "video_url": None,
        }
    )
    detail = "Job " + job_id + " auf dem Pod gestartet"
    return {
        "ok": True,
        "status": "ok",
        "served": False,
        "detail": detail,
        "job_id": job_id,
        "training_status": "queued",
    }


async def isaac_lab_status(ctx: Ctx, args: dict) -> dict:
    job_id = str(args.get("job_id") or ctx.state.isaac_job_id or "").strip()
    if not _configured():
        return await _serve_fallback(ctx, "RunPod ist nicht konfiguriert.")
    if not re.fullmatch(r"[a-f0-9]+", job_id):
        message = "Keine gültige job_id."
        return {"ok": False, "error": message, "detail": message}
    try:
        completed = _run(_ssh_base() + ["bash", "-s"], _status_script(job_id), timeout=25)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "status": "error", "error": str(exc), "detail": str(exc)}
    text = completed.stdout or ""
    if "PAI_STATUS missing" in text:
        message = "Job " + job_id + " liegt nicht auf dem Pod."
        return {"ok": False, "error": message, "detail": message}
    running = "PAI_STATUS running" in text
    log = _between(text, "PAI_LOG_BEGIN", "PAI_LOG_END")
    curve = _parse_curve(log)
    videos = [
        line.strip()
        for line in _between(text, "PAI_VIDEO_BEGIN", "PAI_VIDEO_END").splitlines()
        if line.strip().endswith(".mp4")
    ]
    video_url = None
    if videos and not running:
        local_video = _copy_video(videos[0], ctx.state.directory, job_id)
        if local_video is not None:
            ctx.state.training_video = str(local_video)
            video_url = "/files/" + ctx.state.session_id + "/" + local_video.name
    status = "running" if running else "done"
    step = curve[-1][0] if curve else 0
    reward = curve[-1][1] if curve else 0
    await ctx.emit(
        {
            "type": "training",
            "status": status,
            "step": step,
            "reward": reward,
            "curve": curve,
            "video_url": video_url,
        }
    )
    detail = "Job " + job_id + " " + status
    return {
        "ok": True,
        "status": "ok",
        "detail": detail,
        "job_id": job_id,
        "training_status": status,
        "final_reward": reward,
        "video_url": video_url,
    }


async def isaac_sim_render(ctx: Ctx, args: dict) -> dict:
    del ctx, args
    if not _configured():
        return {
            "ok": True,
            "status": "offline",
            "detail": "Isaac Sim ist offline. RUNPOD_SSH_HOST fehlt, und auf dem Mac liegt keine RTX.",
        }
    return {
        "ok": True,
        "status": "offline",
        "detail": "Der Pod ist gesetzt, der Render-Kanal schreibt das Video über isaac_lab_train --video.",
    }


def _between(text: str, start: str, end: str) -> str:
    if start not in text or end not in text:
        return ""
    return text.split(start, 1)[1].split(end, 1)[0]


def _copy_video(remote_path: str, directory: Path, job_id: str) -> Path | None:
    if not re.fullmatch(r"[A-Za-z0-9_./+-]+", remote_path):
        return None
    local = directory / (job_id + ".mp4")
    command = _scp_base() + [_remote(remote_path), str(local)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    if completed.returncode != 0 or not local.is_file():
        return None
    return local
