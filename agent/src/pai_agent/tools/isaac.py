"""Bounded, isolated Isaac jobs over SSH, with explicit recorded provenance."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import subprocess
import uuid
from pathlib import Path

from pai_agent.context import Ctx
from pai_agent.paths import FALLBACK_DIR, REPO_ROOT
from pai_agent.tools.usd import export_product

TASK = "Isaac-Quadcopter-Direct-v0"
_RUNNER = REPO_ROOT / "runpod/isaac_job.py"


def ssh_setting(name: str, default: str = "") -> str:
    """Provider-neutral settings, with the original RunPod variables as aliases."""
    return (os.environ.get("ISAAC_SSH_" + name) or os.environ.get("RUNPOD_SSH_" + name) or default).strip()


def _number(value, low: float, high: float, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}.")
    return number


def _parameters(mode: str, args: dict) -> dict:
    if mode == "train":
        return {"task": TASK, "iterations": int(_number(args.get("iterations", 100), 1, 1000, "iterations")),
                "num_envs": int(_number(args.get("num_envs", 64), 1, 256, "num_envs"))}
    scenario = args.get("scenario", "wind")
    if scenario not in {"wind", "payload", "hover"}:
        raise ValueError("scenario must be wind, payload or hover.")
    return {"scenario": scenario,
            "wind_m_s": _number(args.get("wind_m_s", 6 if scenario == "wind" else 0), 0, 20, "wind_m_s"),
            "payload_g": _number(args.get("payload_g", 10 if scenario == "payload" else 0), 0, 500, "payload_g"),
            "duration_s": _number(args.get("duration_s", 8), 2, 20, "duration_s")}


def _connection() -> tuple[list[str], list[str], str]:
    host = ssh_setting("HOST")
    user = ssh_setting("USER", "root")
    port = ssh_setting("PORT", "22")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", host) or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*", user):
        raise ValueError("Invalid GPU SSH host or user.")
    _number(port, 1, 65535, "SSH port")
    if not port.isdigit():
        raise ValueError("SSH port must be an integer.")
    key = str(Path(ssh_setting("KEY", "~/.ssh/id_ed25519")).expanduser())
    options = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8",
               "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2", "-i", key]
    target = user + "@" + host
    return ["ssh", *options, "-p", port, target], ["scp", *options, "-P", port], target


async def _command(command: list[str], timeout: float, script: str | None = None) -> None:
    process = await asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE if script is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.communicate(script.encode() if script is not None else None), timeout)
        if process.returncode:
            raise RuntimeError(f"{Path(command[0]).name} failed (exit {process.returncode}). Check pod setup and job logs.")
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise


async def _fallback(ctx: Ctx, mode: str, requested: dict, reason: str) -> dict:
    fixture = json.loads((FALLBACK_DIR / "omniverse.json").read_text(encoding="utf-8"))[mode]
    result = {**fixture, "type": "omniverse", "mode": mode, "status": "recorded", "source": "recorded",
              "requested": requested, "detail": reason + " GPU not connected; nothing was measured.",
              "video_url": "/files/fallback/omniverse.mp4", "json_url": "/files/fallback/omniverse.json"}
    ctx.state.omniverse_result = result
    await ctx.emit(result)
    return {"ok": True, **result}


def _validate_result(result: dict, mode: str, directory: Path) -> None:
    if not isinstance(result, dict) or result.get("mode") != mode or result.get("source") != "live" or result.get("status") != "done":
        raise ValueError("The pod returned an invalid job result.")
    if not isinstance(result.get("metrics"), dict) or not result["metrics"]:
        raise ValueError("The pod returned no measured values.")
    required = {"final_reward", "iterations", "parallel_envs"} if mode == "train" else {"hover_rmse_m", "max_tilt_deg", "max_drift_m"}
    if not required.issubset(result["metrics"]) or (mode == "test" and not isinstance(result.get("passed"), bool)):
        raise ValueError("The pod returned an incomplete result.")
    if mode == "train" and not result.get("curve"):
        raise ValueError("The pod returned no learning curve.")
    curve = result.get("curve", [])
    if not isinstance(curve, list) or any(
        not isinstance(point, list) or len(point) != 2
        or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in point)
        for point in curve
    ):
        raise ValueError("The pod returned an invalid learning curve.")
    for value in result["metrics"].values():
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("The pod returned invalid measured values.")
    video = directory / "result.mp4"
    if not video.is_file() or video.stat().st_size < 32:
        raise ValueError("The pod returned no valid MP4 recording.")
    with video.open("rb") as handle:
        if b"ftyp" not in handle.read(32):
            raise ValueError("The pod returned no valid MP4 recording.")


async def _job(ctx: Ctx, mode: str, args: dict) -> dict:
    if ctx.state.product != "drone" or (ctx.state.stl_path and Path(ctx.state.stl_path).name.startswith("part-")):
        message = "Omniverse hover tests and Crazyflie training support the drone only. Use simulate_grip for the gripper lift-and-shake test."
        return {"ok": False, "error": message, "detail": message}
    try:
        params = _parameters(mode, args)
    except (ValueError, TypeError, OverflowError) as exc:
        return {"ok": False, "error": str(exc), "detail": str(exc)}
    if not ssh_setting("HOST"):
        return await _fallback(ctx, mode, params, "Waiting for pod: GPU SSH is not configured.")
    job_id = uuid.uuid4().hex[:12]
    directory = ctx.state.directory / ("isaac-" + job_id)
    directory.mkdir(parents=True)
    remote = "/tmp/anybuild-" + job_id
    ctx.state.isaac_job_id = job_id
    running = {"type": "omniverse", "mode": mode, "status": "running", "source": "live", "requested": params,
               "stage": "export", "detail": "Exporting the current product to USD with per-part masses.",
               "metrics": {}, "curve": [], "video_url": None, "json_url": None}
    ctx.state.omniverse_result = running
    await ctx.emit(running)

    async def progress(stage: str, detail: str) -> None:
        event = {**running, "stage": stage, "detail": detail}
        ctx.state.omniverse_result = event
        await ctx.emit(event)

    try:
        ssh, scp, target = _connection()
        spec = await asyncio.to_thread(export_product, ctx.state, directory)
        request = {"mode": mode, "parameters": params, "product": spec}
        (directory / "request.json").write_text(json.dumps(request), encoding="utf-8")
        seconds = int(_number(os.environ.get("ISAAC_TIMEOUT_S", 900 if mode == "train" else 300), 30, 1800, "ISAAC_TIMEOUT_S"))
        await progress("upload", "Uploading the USD product to the GPU host over SSH.")
        await _command([*ssh, "bash", "-s"], 15, f"set -eu\nmkdir -p {remote}\n")
        inputs = [str(directory / name) for name in ("request.json", "product.usda", "assembly.usdc", "assembly.json")]
        await _command([*scp, *inputs, str(_RUNNER), target + ":" + remote + "/"], 60)
        await progress("execute", f"Running headless {'reference training' if mode == 'train' else 'product physics'} on the GPU. Deadline: {seconds} seconds.")
        # timeout also bounds the remote process if SSH disconnects or the local task is cancelled.
        script = f'''set -eu
export OMNI_KIT_ACCEPT_EULA=YES
export ACCEPT_EULA=Y
cd {remote}
test -x "$HOME/.venvs/anybuild-isaac/bin/python" || {{ echo "Run runpod/setup.sh first" >&2; exit 2; }}
timeout --signal=TERM --kill-after=15s {seconds}s "$HOME/.venvs/anybuild-isaac/bin/python" isaac_job.py > job.log 2>&1
'''
        await _command([*ssh, "bash", "-s"], seconds + 30, script)
        await progress("download", "Downloading the completed MP4 and measured result JSON.")
        await _command([*scp, target + ":" + remote + "/result.json", target + ":" + remote + "/result.mp4", str(directory) + "/"], 60)
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
        _validate_result(result, mode, directory)
        # Serve flat, session-scoped artifact paths using the existing file endpoint.
        for suffix in ("json", "mp4"):
            (directory / ("result." + suffix)).replace(ctx.state.directory / (job_id + "." + suffix))
        result.update({"type": "omniverse", "requested": params, "job_id": job_id,
                       "video_url": f"/files/{ctx.state.session_id}/{job_id}.mp4",
                       "json_url": f"/files/{ctx.state.session_id}/{job_id}.json"})
        ctx.state.omniverse_result = result
        if mode == "train":
            ctx.state.training_video = str(ctx.state.directory / (job_id + ".mp4"))
        await ctx.emit(result)
        return {"ok": True, **result}
    except (TimeoutError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        reason = "GPU job timed out." if isinstance(exc, TimeoutError) else str(exc)
        return await _fallback(ctx, mode, params, reason + " Job " + job_id + ".")


async def isaac_test(ctx: Ctx, args: dict) -> dict:
    return await _job(ctx, "test", args)


async def isaac_train(ctx: Ctx, args: dict) -> dict:
    return await _job(ctx, "train", args)


# Existing clients retain their tool names, but now receive completed artifacts.
isaac_lab_train = isaac_train
isaac_sim_render = isaac_test


async def isaac_lab_status(ctx: Ctx, args: dict) -> dict:
    del args
    result = ctx.state.omniverse_result
    if result is None:
        return {"ok": True, "status": "offline", "detail": "No Omniverse job has run in this session."}
    await ctx.emit(result)
    return {"ok": True, **result}
