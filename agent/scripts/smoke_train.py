"""One pass of the browser-training protocol in mock mode, with this script playing the dashboard tab. Not a suite.

"train it" queues a job; a client claims it, a second client is refused, two progress posts and a
done post land as `training` events, and the agent reports the gains. A gripper build queues a
gripper job from its servo and pads. Then a job nobody claims fails with `no_browser`, and a
claimed job that goes quiet fails with `browser_gone`.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = os.environ.get("SMOKE_PORT", "8109")
BASE = "http://127.0.0.1:" + PORT
GAINS = {"kp_z": 16.5, "ki_z": 10.3, "kd_z": 5.2, "kp_xy": 9.9, "kd_xy": 4.4, "kp_att": 118.0, "kd_att": 13.5}
EXPORTED = {**GAINS, "kp_att": 0.001406, "kd_att": 0.0001607, "roll": {"p": 51, "i": 90}, "pitch": {"p": 53, "i": 95}}
METRICS = {"rms_error_cm": 2.9, "max_tilt_deg": 12.9, "survived_s": 10.0, "crashed": False, "held": True}


def main() -> None:
    if _healthy():
        raise SystemExit("Port " + PORT + " already answers. Stop the old server first.")
    env = os.environ.copy()
    env.update({"PAI_FORCE_MOCK": "1", "DEMO_PACE_S": "0", "PORT": PORT, "PAI_TRAIN_CLAIM_TIMEOUT_S": "2", "PAI_TRAIN_STALL_S": "2"})
    for key in list(env):
        if key.startswith("RUNPOD_") or key in {"ANTHROPIC_API_KEY"}:
            env.pop(key, None)
    log_path = Path(os.environ.get("TMPDIR", "/tmp")) / "pai-agent-smoke-train.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            ["uv", "run", "physical-ai-agent"], cwd=ROOT, env=env, start_new_session=True, stdout=log_file, stderr=subprocess.STDOUT
        )
        try:
            _wait_healthy(process, log_path)
            _trained()
            _gripper()
            _unclaimed()
            _stalled()
        finally:
            _stop(process)
    print("train ok: drone claim, refuse, progress, done with gains; gripper spec from the build; no_browser and browser_gone fail cleanly")


def _trained() -> None:
    _prompt("train it")
    job = _wait_job(lambda j: j["status"] == "queued")
    spec = job["spec"]
    if spec.get("product") != "drone" or not spec.get("mass_g") or not spec.get("thrust_g") or job["rollouts_total"] != 1024:
        raise SystemExit("Queued job is incomplete: " + json.dumps(job))
    job_id = job["job_id"]
    claim = _post("/api/training/" + job_id + "/claim", {"client": "tab-a"})
    if claim.get("population") != 64 or claim.get("generations") != 16:
        raise SystemExit("Claim did not return the run size: " + str(claim))
    _expect_status(409, "/api/training/" + job_id + "/claim", {"client": "tab-b"})
    _expect_status(409, "/api/training/" + job_id + "/progress", {"client": "tab-b", "status": "running"})
    for generation, score in ((1, 31.9), (2, 43.3)):
        _post("/api/training/" + job_id + "/progress", {"client": "tab-a", "status": "running", "step": 64 * generation, "generation": generation, "best_score": score, "best_params": GAINS, "best_metrics": METRICS})
    _post("/api/training/" + job_id + "/progress", {"client": "tab-a", "status": "done", "step": 1024, "generation": 16, "best_score": 78.2, "best_params": GAINS, "best_metrics": METRICS, "gains": EXPORTED})
    _expect_status(409, "/api/training/" + job_id + "/progress", {"client": "tab-a", "status": "running"})
    events = _wait_events(lambda evs: any(e.get("type") == "chat" and "1,024 simulations" in e.get("text", "") for e in evs))
    training = [e for e in events if e.get("type") == "training" and e.get("job_id") == job_id]
    if [e["status"] for e in training] != ["queued", "running", "running", "done"]:
        raise SystemExit("Training events out of order: " + str([e["status"] for e in training]))
    final = training[-1]
    if any("gains" in e for e in training[:-1]) or final.get("gains") != EXPORTED:
        raise SystemExit("Only the done event should carry the exported gains: " + json.dumps(final.get("gains")))
    if final["best_params"] != GAINS or final["curve"] != [[64, 31.9], [128, 43.3], [1024, 78.2]] or final["step"] != 1024 or final["reward"] != 78.2:
        raise SystemExit("Final training event is wrong: " + json.dumps(final))
    steps = [e["status"] for e in events if e.get("type") == "step" and e.get("id") == "training"]
    if steps[-2:] != ["running", "done"]:
        raise SystemExit("Training step did not finish: " + str(steps))
    tool = [e for e in events if e.get("type") == "tool" and e.get("name") == "train_in_browser"]
    if not tool or tool[-1]["status"] != "ok":
        raise SystemExit("train_in_browser did not end ok: " + str(tool[-1:]))
    latest = _get("/api/training/browser")["job"]
    if latest["status"] != "done" or latest["best_params"] != GAINS or latest.get("gains") != EXPORTED:
        raise SystemExit("GET /api/training/browser misses the gains: " + json.dumps(latest))


def _gripper() -> None:
    _reset()
    # The gripper mock picks its parts before CAD, so the spec is real even where FreeCAD is missing.
    _prompt("Build a gripper that lifts a 200 g part, 66 mm wide")
    _wait_events(lambda evs: any(e.get("type") == "sim" and e.get("kind") == "grip" and e.get("result") == "pass" for e in evs), timeout=60)
    deadline = time.time() + 60
    while time.time() < deadline and _post("/api/prompt", {"text": "train it"}).get("status") != "started":
        time.sleep(0.3)
    job = _wait_job(lambda j: j["status"] == "queued" and j["product"] == "gripper")
    spec = job["spec"]
    if spec.get("nominal") or spec.get("payload_g") != 200 or not 4.0 < spec.get("max_force_n", 0) < 5.0 or spec.get("friction") != 0.8:
        raise SystemExit("Gripper spec does not come from the build: " + json.dumps(spec))
    _post("/api/training/" + job["job_id"] + "/claim", {"client": "tab-a"})
    grasp = {"squeeze": 0.368, "grip_force_n": 2.19, "ramp_ms": 265, "settle_ms": 1, "lift_ms": 416, "cycle_ms": 681}
    metrics = {"slip_mm": 5.4, "force_n": 2.19, "cycle_s": 0.68, "crashed": False, "held": True}
    _post("/api/training/" + job["job_id"] + "/progress", {"client": "tab-a", "status": "done", "step": 1024, "generation": 16, "best_score": 62.1, "best_params": {"squeeze": 0.368}, "best_metrics": metrics, "gains": grasp})
    _wait_events(lambda evs: any(e.get("type") == "chat" and "2.2 N per finger" in e.get("text", "") for e in evs))


def _unclaimed() -> None:
    _reset()
    _prompt("train it")
    job = _wait_job(lambda j: j["status"] == "failed", timeout=15)
    if job.get("error") != "no_browser":
        raise SystemExit("An unclaimed job should fail with no_browser: " + json.dumps(job))


def _stalled() -> None:
    _reset()
    _prompt("train it")
    job = _wait_job(lambda j: j["status"] == "queued")
    _post("/api/training/" + job["job_id"] + "/claim", {"client": "tab-a"})
    job = _wait_job(lambda j: j["status"] == "failed", timeout=15)
    if job.get("error") != "browser_gone":
        raise SystemExit("A silent claimed job should fail with browser_gone: " + json.dumps(job))
    _expect_status(409, "/api/training/" + job["job_id"] + "/progress", {"client": "tab-a", "status": "running"})


def _wait_job(ready, timeout: float = 20) -> dict:
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        job = _get("/api/training/browser")["job"]
        if job and ready(job):
            return job
        time.sleep(0.1)
    raise SystemExit("Job never got there: " + json.dumps(job))


def _wait_events(ready, timeout: float = 20) -> list[dict]:
    deadline = time.time() + timeout
    events: list[dict] = []
    while time.time() < deadline:
        events = _backlog()
        if ready(events):
            return events
        time.sleep(0.2)
    raise SystemExit("Events never arrived. Last types: " + str([e.get("type") for e in events[-12:]]))


def _backlog() -> list[dict]:
    """The events published so far: the stream's backlog up to its `replayed` marker."""

    events = []
    with urllib.request.urlopen(BASE + "/api/events", timeout=10) as response:
        while True:
            line = response.readline().decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            if event.get("type") == "replayed":
                return events
            events.append(event)


def _prompt(text: str) -> None:
    body = _post("/api/prompt", {"text": text})
    if body.get("status") != "started" or body.get("mode") != "mock":
        raise SystemExit("Prompt refused: " + str(body))


def _reset() -> None:
    _post("/api/reset", {})


def _expect_status(code: int, path: str, payload: dict) -> None:
    try:
        _post(path, payload)
    except urllib.error.HTTPError as exc:
        if exc.code == code:
            return
        raise SystemExit(path + " answered " + str(exc.code) + ", expected " + str(code))
    raise SystemExit(path + " succeeded, expected HTTP " + str(code))


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(BASE + path, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _healthy() -> bool:
    try:
        with urllib.request.urlopen(BASE + "/api/health", timeout=1) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _wait_healthy(process: subprocess.Popen, log_path: Path) -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        if process.poll() is not None:
            raise SystemExit("Server died on start:\n" + log_path.read_text(encoding="utf-8", errors="replace")[-2000:])
        if _healthy():
            return
        time.sleep(0.2)
    raise SystemExit("Server did not become healthy.")


def _stop(process: subprocess.Popen) -> None:
    import signal

    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)


if __name__ == "__main__":
    main()
