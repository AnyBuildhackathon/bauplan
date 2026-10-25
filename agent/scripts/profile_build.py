"""Times the three stage flows end to end and per tool, from the SSE stream.

Starts its own mock backend on PROFILE_PORT (default 8102) unless PROFILE_BASE points at a running one
(then the run uses whatever mode that server is in, so a live server profiles a live build).

    cd agent && uv run python scripts/profile_build.py            # mock
    cd agent && PROFILE_BASE=http://127.0.0.1:8100 uv run python scripts/profile_build.py drone

Flows: drone (reference drone, then a typed change), gripper (robot gripper from a request),
stand (phone stand from scratch). Prints the wall time of each flow and the slowest tools.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
GRIPPER = "Design a robot gripper for our arm that picks up a 200 g soda can, 66 mm wide. Keep it under 150 g and 30 €."
STAND = "Design a phone stand for my desk that holds my phone for video calls, under 150 g and 6 € in parts."
FLOWS = ("drone", "gripper", "stand")


def _request(base: str, path: str, body: dict | None = None, timeout: float = 30) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, headers={"content-type": "application/json"}, method="GET" if body is None else "POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read() or b"{}")


def _wait_idle(base: str, limit_s: float) -> None:
    deadline = time.time() + limit_s
    # The run starts as a task after the request returns; give it a beat to report busy.
    time.sleep(0.3)
    while time.time() < deadline:
        if not _request(base, "/api/health").get("busy"):
            return
        time.sleep(0.2)
    raise SystemExit("The run did not finish within " + str(limit_s) + " s.")


class Recorder:
    def __init__(self, base: str) -> None:
        self.events: list[tuple[float, dict]] = []
        Thread(target=self._consume, args=(base,), daemon=True).start()

    def _consume(self, base: str) -> None:
        with urllib.request.urlopen(base + "/api/events", timeout=600) as response:
            for line in response:
                text = line.decode("utf-8").strip()
                if text.startswith("data: "):
                    self.events.append((time.perf_counter(), json.loads(text[6:])))

    def tools_since(self, index: int) -> dict[str, list[float]]:
        # A tool reports running once at the start and again for progress; the next other status ends it.
        open_at: dict[str, float] = {}
        spent: dict[str, list[float]] = defaultdict(list)
        for at, event in self.events[index:]:
            if event.get("type") != "tool":
                continue
            name = str(event.get("name"))
            if event.get("status") == "running":
                open_at.setdefault(name, at)
            elif name in open_at:
                spent[name].append(at - open_at.pop(name))
        return spent


def run_flow(base: str, recorder: Recorder, flow: str) -> dict:
    _request(base, "/api/reset", {})
    time.sleep(0.3)
    start_index = len(recorder.events)
    started = time.perf_counter()
    if flow == "drone":
        _request(base, "/api/library/micro-drone/open", {})
        _wait_idle(base, 600)
        _request(base, "/api/prompt", {"text": "Make it fly 10 minutes."})
    elif flow == "gripper":
        _request(base, "/api/prompt", {"text": GRIPPER})
    else:
        _request(base, "/api/prompt", {"text": STAND})
    _wait_idle(base, 600)
    total = time.perf_counter() - started
    spent = recorder.tools_since(start_index)
    errors = [e for _, e in recorder.events[start_index:] if e.get("type") == "tool" and e.get("status") == "error"]
    return {"flow": flow, "seconds": round(total, 2), "tools": {k: round(sum(v), 2) for k, v in spent.items()}, "errors": [e.get("name") + ": " + str(e.get("detail")) for e in errors]}


def _start_server(port: str) -> subprocess.Popen:
    env = os.environ.copy()
    env.update({"PAI_FORCE_MOCK": "1", "DEMO_PACE_S": "0", "PAI_ASK_TIMEOUT_S": "0", "PORT": port})
    for key in list(env):
        if key.startswith("RUNPOD_") or key in {"ANTHROPIC_API_KEY"}:
            env.pop(key, None)
    log_path = Path(os.environ.get("TMPDIR", "/tmp")) / "pai-agent-profile.log"
    process = subprocess.Popen(["uv", "run", "physical-ai-agent"], cwd=ROOT, env=env, start_new_session=True, stdout=log_path.open("w"), stderr=subprocess.STDOUT)
    base = "http://127.0.0.1:" + port
    for _ in range(300):
        try:
            _request(base, "/api/health", timeout=1)
            return process
        except OSError:
            if process.poll() is not None:
                raise SystemExit("Server exited, see " + str(log_path))
            time.sleep(0.1)
    raise SystemExit("Server did not start, see " + str(log_path))


def main() -> None:
    flows = [f for f in sys.argv[1:] if f in FLOWS] or list(FLOWS)
    base = os.environ.get("PROFILE_BASE", "").rstrip("/")
    process = None
    if not base:
        port = os.environ.get("PROFILE_PORT", "8102")
        boot = time.perf_counter()
        process = _start_server(port)
        base = "http://127.0.0.1:" + port
        print(f"server up in {time.perf_counter() - boot:.2f} s")
    try:
        recorder = Recorder(base)
        time.sleep(0.3)
        results = [run_flow(base, recorder, flow) for flow in flows]
    finally:
        if process is not None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # The open event stream keeps uvicorn waiting for connections to close.
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    for result in results:
        print(f"\n{result['flow']}: {result['seconds']:.2f} s")
        for name, seconds in sorted(result["tools"].items(), key=lambda item: -item[1])[:8]:
            print(f"  {name:<20} {seconds:6.2f} s")
        for error in result["errors"]:
            print("  error " + error)
    out = os.environ.get("PROFILE_JSON")
    if out:
        Path(out).write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
