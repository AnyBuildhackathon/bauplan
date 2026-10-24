"""Integration availability without exposing credentials or making billable API calls."""

from __future__ import annotations

import asyncio
import os
import time

from pai_agent.env import claude_enabled
from pai_agent.freecad_run import find_freecadcmd, gui_mode, rpc_available
from pai_agent.tools.blender import find_blender
from pai_agent.tools.isaac import _connection, ssh_setting

_gpu_cache: tuple[tuple[str, ...], float, dict] | None = None
_gpu_lock = asyncio.Lock()


async def isaac_connection() -> dict:
    """A bounded, read-only SSH/nvidia-smi probe, cached for 15 seconds across viewers."""
    global _gpu_cache
    config = tuple(ssh_setting(name) for name in ("HOST", "PORT", "USER", "KEY"))
    host = config[0]
    if not host:
        return {"host": None, "gpu": None, "state": "offline", "detail": "GPU SSH host is not configured."}
    async with _gpu_lock:
        if _gpu_cache and _gpu_cache[0] == config and time.monotonic() < _gpu_cache[1]:
            return _gpu_cache[2]
        result = {"host": host, "gpu": None, "state": "offline", "detail": "GPU SSH or nvidia-smi is unavailable."}
        process = None
        try:
            ssh, _, _ = _connection()
            # Use the job's accept-new policy without changing the user's known_hosts file.
            command = [ssh[0], "-o", "UserKnownHostsFile=/dev/null", *ssh[1:], "nvidia-smi --query-gpu=name --format=csv,noheader"]
            process = await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), 5)
            gpu = stdout.decode("utf-8", errors="replace").strip().splitlines()
            if process.returncode == 0 and gpu:
                result = {"host": host, "gpu": gpu[0][:120], "state": "live", "detail": "SSH connected; GPU identified by nvidia-smi."}
        except (OSError, ValueError, TimeoutError):
            pass
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
        _gpu_cache = (config, time.monotonic() + 15, result)
        return result


def partner_statuses(events: list[dict]) -> list[dict]:
    def configured(name: str) -> bool:
        return bool(os.environ.get(name, "").strip())

    def partner(id: str, label: str, state: str, detail: str) -> dict:
        return {"id": id, "label": label, "state": state, "detail": detail}

    api_hint = " Credentials configured; authentication and quota are checked on use."
    claude = claude_enabled()
    jamie = configured("JAMIE_MCP_TOKEN")
    reson8 = configured("RESON8_API_KEY")
    eleven = configured("ELEVENLABS_API_KEY")
    freecad = bool(find_freecadcmd()) or (gui_mode() != "off" and rpc_available())
    blender = bool(find_blender())
    rows = [
        partner("claude", "Claude", "live" if claude else "mock", "Engineering orchestration." + api_hint if claude else "Scripted build: Claude is disabled or its API key is absent."),
        partner("jamie", "Jamie", "live" if jamie else "mock", "Meeting transcripts, notes and tasks." + api_hint if jamie else "Fixture meetings and a local task outbox; Jamie is not connected."),
        partner("reson8", "Reson8", "live" if reson8 else "offline", "Realtime speech recognition." + api_hint if reson8 else "No Reson8 key; browser speech recognition is the fallback."),
        partner("elevenlabs", "ElevenLabs", "live" if eleven else "offline", "Mechanic's spoken replies." + api_hint if eleven else "No ElevenLabs key; Mechanic replies with text."),
        partner("freecad", "FreeCAD", "live" if freecad else "offline", "Local FreeCAD is available for CAD generation." if freecad else "FreeCAD is unavailable; CadQuery is the fallback."),
        partner("blender", "Blender", "live" if blender else "offline", "Local Blender is available for studio rendering." if blender else "Blender is unavailable; a recorded still is the fallback."),
    ]
    # Runtime fallbacks take precedence over configured credentials / installed tools.
    names = {"jamie_requirements": "jamie", "jamie_search": "jamie", "jamie_meeting": "jamie", "jamie_create_tasks": "jamie", "jamie_note": "jamie", "cad_frame": "freecad", "cad_part": "freecad", "blender_render": "blender"}
    latest: dict[str, dict] = {}
    cad_source = None
    for event in events:
        if event.get("type") == "tool" and event.get("name") in names and event.get("ms") is not None:
            latest[names[event["name"]]] = event
        if event.get("type") == "cad":
            cad_source = event.get("source")
        if event.get("type") == "jamie" and event.get("status") == "error":
            latest["jamie"] = {"status": "error"}
    if cad_source == "cadquery":
        latest["freecad"] = {"status": "offline"}
    for row in rows:
        if latest.get(row["id"], {}).get("status") in {"error", "offline"}:
            row.update(state="offline", detail=f"The latest {row['label']} call failed or used its offline fallback.")
    return rows
