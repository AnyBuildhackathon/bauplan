"""One pass of the stress test over the SSE stream: the kickoff builds v1, then "stress test it". Not a suite."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from threading import Thread

from smoke_sse import _healthy, _log_tail, _post, _stop, _tail, _wait_healthy

ROOT = Path(__file__).resolve().parents[1]
PORT = os.environ.get("SMOKE_PORT", "8101")
BASE = "http://127.0.0.1:" + PORT


def main() -> None:
    if _healthy():
        raise SystemExit("Port " + PORT + " already answers. Stop the old server first.")
    env = os.environ.copy()
    env.update({"PAI_FORCE_MOCK": "1", "DEMO_PACE_S": "0", "PAI_ASK_TIMEOUT_S": "0", "PORT": PORT})
    for key in list(env):
        if key.startswith("RUNPOD_") or key in {"ANTHROPIC_API_KEY", "JAMIE_MCP_TOKEN"}:
            env.pop(key, None)
    log_path = Path(os.environ.get("TMPDIR", "/tmp")) / "pai-agent-smoke-stress.log"
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        ["uv", "run", "physical-ai-agent"],
        cwd=ROOT,
        env=env,
        start_new_session=True,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    events: list[dict] = []
    try:
        _wait_healthy(process, log_path)

        def consume() -> None:
            with urllib.request.urlopen(BASE + "/api/events", timeout=300) as response:
                while True:
                    line = response.readline()
                    if not line:
                        break
                    text = line.decode("utf-8").strip()
                    if text.startswith("data: "):
                        events.append(json.loads(text[6:]))
                        if _stress_done(events):
                            break

        thread = Thread(target=consume, daemon=True)
        thread.start()
        time.sleep(0.2)
        kickoff = json.loads((ROOT / "data" / "webhooks" / "meeting-ended.json").read_text(encoding="utf-8"))
        _post("/api/webhooks/jamie", kickoff)
        deadline = time.time() + 300
        while time.time() < deadline and not any(e.get("type") == "version" for e in events):
            time.sleep(0.2)
        while time.time() < deadline:
            # The kickoff run still closes out after its version; the prompt waits for it.
            started = _prompt("stress test it")
            if started.get("status") == "started":
                break
            time.sleep(0.3)
        thread.join(timeout=300)
        if not _stress_done(events):
            raise SystemExit("Stress test incomplete. Last types: " + _tail(events) + "\n" + _log_tail(log_path))
        _assert_stress(events)
    finally:
        _stop(process)
        log_file.close()
    final = [e for e in events if e.get("type") == "stress"][-1]
    print("Survived " + str(final["survived"]) + "/" + str(final["total"]) + " · " + final["explanation"])


def _prompt(text: str) -> dict:
    request = urllib.request.Request(
        BASE + "/api/prompt",
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _stress_done(events: list[dict]) -> bool:
    finished = [i for i, e in enumerate(events) if e.get("type") == "stress" and e.get("status") == "done"]
    return bool(finished) and any(e.get("type") == "chat" and e.get("role") == "agent" for e in events[finished[-1] + 1 :])


def _assert_stress(events: list[dict]) -> None:
    stress = [e for e in events if e.get("type") == "stress"]
    final = stress[-1]
    if final["total"] != 50 or len(final["worlds"]) != 50:
        raise SystemExit("Expected 50 worlds: " + str(len(final["worlds"])))
    if final["survived"] != sum(1 for w in final["worlds"] if w["pass"]):
        raise SystemExit("Score and worlds disagree.")
    if not any(e["status"] == "running" and 0 < e["done"] < 50 for e in stress):
        raise SystemExit("No progress events while the worlds ran.")
    for w in final["worlds"]:
        if not (-15.01 <= w["mass_pct"] <= 15.01 and -25.01 <= w["motor_pct"] <= 0 and 0 <= w["gust_mps"] <= 6):
            raise SystemExit("World outside the randomization ranges: " + str(w))
    worst = final["worst"]
    if not worst or len(worst["trajectory"]) < 50:
        raise SystemExit("Worst world has no replay.")
    if worst["margin"] != min(w["margin"] for w in final["worlds"]):
        raise SystemExit("Worst world is not the lowest margin.")
    if not final["explanation"]:
        raise SystemExit("Bolzen's sentence is missing.")
    if final["survived"] < final["total"] and final["weakest"] not in {"gust", "motor", "mass", "noise"}:
        raise SystemExit("Weakest point missing: " + str(final["weakest"]))
    tools = [e for e in events if e.get("type") == "tool" and e.get("name") == "stress_test"]
    if not tools or tools[-1]["status"] != "ok" or "Survived" not in tools[-1]["detail"]:
        raise SystemExit("stress_test tool did not finish ok: " + str(tools[-1:]))


if __name__ == "__main__":
    main()
