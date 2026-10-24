"""One pass of the stress test in mock mode, with this script playing the dashboard tab. Not a suite.

The kickoff builds v1, then "stress test it" queues the drone's 50 worlds for the browser: a client
claims them, a second client is refused, the outcomes go back in batches, and the backend scores
them (default gains, since nothing was trained). Then a training run leaves gains in its final
`training` event and the next stress test flies those. Last, a stress test nobody claims fails.
The worlds' physics run in the browser (web/src/sim); the outcomes here are made up from each
world's gust, so this checks the protocol and the scoring, not MuJoCo.
"""

from __future__ import annotations

import os

os.environ.setdefault("SMOKE_PORT", "8101")

import json  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from smoke_train import EXPORTED, PORT, _backlog, _expect_status, _healthy, _post, _stop, _wait_events, _wait_healthy  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if _healthy():
        raise SystemExit("Port " + PORT + " already answers. Stop the old server first.")
    env = os.environ.copy()
    env.update({"PAI_FORCE_MOCK": "1", "DEMO_PACE_S": "0", "PAI_ASK_TIMEOUT_S": "0", "PORT": PORT, "PAI_TRAIN_CLAIM_TIMEOUT_S": "3"})
    for key in list(env):
        if key.startswith("RUNPOD_") or key in {"ANTHROPIC_API_KEY", "JAMIE_MCP_TOKEN"}:
            env.pop(key, None)
    log_path = Path(os.environ.get("TMPDIR", "/tmp")) / "pai-agent-smoke-stress.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            ["uv", "run", "physical-ai-agent"], cwd=ROOT, env=env, start_new_session=True, stdout=log_file, stderr=subprocess.STDOUT
        )
        try:
            _wait_healthy(process, log_path)
            kickoff = json.loads((ROOT / "data" / "webhooks" / "meeting-ended.json").read_text(encoding="utf-8"))
            _post("/api/webhooks/jamie", kickoff)
            _wait_events(lambda events: any(e.get("type") == "version" for e in events), timeout=300)
            first = _stress(1, fly=True)
            _assert_default(first)
            _train()
            second = _stress(2, fly=True)
            _assert_trained(second)
            _unclaimed()
        finally:
            _stop(process)
    print(
        "stress ok: claim, refuse, batches, scoring · default "
        + str(first["survived"])
        + "/50, trained "
        + str(second["survived"])
        + "/50 · "
        + second["explanation"]
    )


def _prompt_when_idle(text: str) -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        # The previous run still closes out after its last event; the prompt waits for it.
        if _post("/api/prompt", {"text": text}).get("status") == "started":
            return
        time.sleep(0.3)
    raise SystemExit("Prompt never started: " + text)


def _outcome(world: dict) -> dict:
    """Made-up readouts: drift grows with the gust, so the gustiest worlds are lost."""

    drift = round(0.07 * world["gust_mps"] * world["motor_scale"] ** -1 * 0.8, 3)
    trajectory = [[round(k * 0.05, 3), 0.0, 0.0, 1.0] for k in range(201)]
    return {"i": world["i"], "metrics": {"crashed": False, "drift_m": drift, "low_z_m": 0.93, "tail_z_m": 0.98}, "trajectory": trajectory}


def _stress(run: int, fly: bool) -> dict:
    _prompt_when_idle("stress test it")
    events = _wait_events(lambda es: any(e.get("type") == "stress" and e["run"] == run for e in es))
    queued = [e for e in events if e.get("type") == "stress" and e["run"] == run][0]
    if queued["status"] != "queued" or queued.get("source") != "browser" or not queued.get("job_id") or queued["spec"].get("product") != "drone":
        raise SystemExit("Stress test was not queued for the browser: " + json.dumps(queued)[:400])
    if not fly:
        return queued
    job = queued["job_id"]
    claim = _post("/api/stress/" + job + "/claim", {"client": "tab-a"})
    worlds = claim["worlds"]
    if len(worlds) != 50 or claim["gains"] != queued["gains"] or claim["spec"] != queued["spec"]:
        raise SystemExit("Claim did not return the job: " + json.dumps(claim)[:400])
    _expect_status(409, "/api/stress/" + job + "/claim", {"client": "tab-b"})
    _expect_status(409, "/api/stress/" + job + "/progress", {"client": "tab-b", "status": "running", "results": []})
    # In completion order, like the pool: odd worlds first.
    ordered = worlds[0::2] + worlds[1::2]
    for start in range(0, 50, 5):
        _post("/api/stress/" + job + "/progress", {"client": "tab-a", "status": "running", "results": [_outcome(w) for w in ordered[start : start + 5]]})
    _post("/api/stress/" + job + "/progress", {"client": "tab-a", "status": "done"})
    events = _wait_events(lambda es: _done(es, run), timeout=30)
    stress = [e for e in events if e.get("type") == "stress" and e["run"] == run]
    if not any(e["status"] == "running" and 0 < e["done"] < 50 for e in stress):
        raise SystemExit("No progress events while the worlds came in.")
    final = stress[-1]
    _assert_final(final, events)
    _expect_status(409, "/api/stress/" + job + "/progress", {"client": "tab-a", "status": "running", "results": []})
    return final


def _done(events: list[dict], run: int) -> bool:
    finished = [i for i, e in enumerate(events) if e.get("type") == "stress" and e["run"] == run and e["status"] in {"done", "failed"}]
    return bool(finished) and any(e.get("type") == "chat" and e.get("role") == "agent" for e in events[finished[-1] + 1 :])


def _assert_final(final: dict, events: list[dict]) -> None:
    if final["status"] != "done":
        raise SystemExit("Stress test did not finish: " + final["explanation"])
    if final["total"] != 50 or [w["i"] for w in final["worlds"]] != list(range(1, 51)):
        raise SystemExit("Expected worlds 1..50 in order.")
    if final["survived"] != sum(1 for w in final["worlds"] if w["pass"]):
        raise SystemExit("Score and worlds disagree.")
    for w in final["worlds"]:
        if not (-15.01 <= w["mass_pct"] <= 15.01 and -25.01 <= w["motor_pct"] <= 0 and 0 <= w["gust_mps"] <= 6):
            raise SystemExit("World outside the randomization ranges: " + str(w))
        if w["pass"] != (w["drift_m"] <= 0.35) or (not w["pass"] and w["reason"] != "drifted"):
            raise SystemExit("World scored wrong: " + str(w))
    worst = final["worst"]
    if not worst or len(worst["trajectory"]) < 50:
        raise SystemExit("Worst world has no replay.")
    if worst["margin"] != min(w["margin"] for w in final["worlds"]):
        raise SystemExit("Worst world is not the lowest margin.")
    if any(w["margin"] > 0 for w in final["worlds"] if not w["pass"]):
        raise SystemExit("A lost world has a positive margin.")
    if final["survived"] < final["total"] and (worst["pass"] or final["weakest"] not in {"gust", "motor", "mass", "noise"}):
        raise SystemExit("Weakest point or worst world wrong: " + str(final["weakest"]))
    if not final["explanation"]:
        raise SystemExit("Bolzen's sentence is missing.")
    tools = [e for e in events if e.get("type") == "tool" and e.get("name") == "stress_test"]
    if not tools or tools[-1]["status"] != "ok" or "Survived" not in tools[-1]["detail"]:
        raise SystemExit("stress_test tool did not finish ok: " + str(tools[-1:]))


def _assert_default(final: dict) -> None:
    if final["policy"] != "default" or final["gains"]["kp_xy"] != 0.35:
        raise SystemExit("Without training the default gains should fly: " + str(final["gains"]))


def _train() -> None:
    _prompt_when_idle("train it")
    events = _wait_events(lambda es: any(e.get("type") == "training" and e.get("status") == "queued" for e in es))
    job = [e for e in events if e.get("type") == "training" and e.get("status") == "queued"][-1]["job_id"]
    _post("/api/training/" + job + "/claim", {"client": "tab-a"})
    _post("/api/training/" + job + "/progress", {"client": "tab-a", "status": "done", "step": 1024, "generation": 16, "best_score": 80.0, "gains": EXPORTED})
    _wait_events(lambda es: any(e.get("type") == "step" and e.get("id") == "training" and e.get("status") == "done" for e in es))


def _assert_trained(final: dict) -> None:
    want = {k: v for k, v in EXPORTED.items() if not isinstance(v, dict)}
    if final["policy"] != "trained" or final["gains"] != want:
        raise SystemExit("The stress test should fly the trained gains: " + str(final["gains"]))


def _unclaimed() -> None:
    queued = _stress(3, fly=False)
    events = _wait_events(lambda es: _done(es, 3), timeout=30)
    final = [e for e in events if e.get("type") == "stress" and e["run"] == 3][-1]
    if final["status"] != "failed" or "dashboard" not in final["explanation"]:
        raise SystemExit("An unclaimed stress test should fail: " + json.dumps(final)[:300])
    _expect_status(409, "/api/stress/" + queued["job_id"] + "/claim", {"client": "tab-late"})
    if len(_backlog()) == 0:
        raise SystemExit("Backlog vanished.")


if __name__ == "__main__":
    main()
