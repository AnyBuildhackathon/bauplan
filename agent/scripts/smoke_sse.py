"""One pass of the mock story over the SSE stream: kickoff builds v1, the review builds v2. Not a suite."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
PORT = os.environ.get("SMOKE_PORT", "8101")
BASE = "http://127.0.0.1:" + PORT
STEPS = ("meeting", "teile", "cad", "render", "simulation", "stueckliste")


def main() -> None:
    if _healthy():
        raise SystemExit("Port " + PORT + " antwortet schon. Den alten Server zuerst stoppen.")
    env = os.environ.copy()
    env["PAI_FORCE_MOCK"] = "1"
    env["DEMO_PACE_S"] = "0"
    env["PAI_ASK_TIMEOUT_S"] = "0"
    env["PORT"] = PORT
    for key in list(env):
        if key.startswith("RUNPOD_") or key in {"ANTHROPIC_API_KEY", "JAMIE_MCP_TOKEN"}:
            env.pop(key, None)
    log_path = Path(os.environ.get("TMPDIR", "/tmp")) / "pai-agent-smoke.log"
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
        holder: dict[str, str | None] = {"error": None}

        def consume() -> None:
            try:
                request = urllib.request.Request(BASE + "/api/events")
                with urllib.request.urlopen(request, timeout=180) as response:
                    while True:
                        line = response.readline()
                        if not line:
                            break
                        text = line.decode("utf-8").strip()
                        if not text.startswith("data: "):
                            continue
                        events.append(json.loads(text[6:]))
                        if _done(events):
                            break
            except Exception as exc:
                holder["error"] = str(exc)

        thread = Thread(target=consume, daemon=True)
        thread.start()
        time.sleep(0.2)
        ignored = _post_json("/api/webhooks/jamie", {"event": "recording.uploaded"})
        if ignored.get("status") != "ignored":
            raise SystemExit("Fremdes Ereignis wurde nicht ignoriert: " + str(ignored))
        kickoff = json.loads((ROOT / "data" / "webhooks" / "meeting-ended.json").read_text(encoding="utf-8"))
        review = json.loads((ROOT / "data" / "webhooks" / "review-ended.json").read_text(encoding="utf-8"))
        _post("/api/webhooks/jamie", kickoff)
        deadline = time.time() + 300
        while time.time() < deadline and not any(e.get("type") == "version" for e in events):
            time.sleep(0.2)
        live = _post_json("/api/webhooks/jamie", {"event": "meeting.started", "meeting_id": review["meeting_id"], "title": review["title"]})
        if live.get("status") != "live":
            raise SystemExit("Review wurde nicht live: " + str(live))
        while time.time() < deadline:
            state = _post_json("/api/webhooks/jamie", review)
            if state.get("status") == "started":
                break
            time.sleep(0.2)
        thread.join(timeout=300)
        if holder["error"]:
            raise SystemExit(holder["error"])
        if not _done(events):
            raise SystemExit("Geschichte unvollständig. Letzte Typen: " + _tail(events) + "\n" + _log_tail(log_path))
        _assert_story(events)
    finally:
        _stop(process)
        log_file.close()
    print(_summary(events))


def _done(events: list[dict]) -> bool:
    versions = [i for i, event in enumerate(events) if event.get("type") == "version"]
    if len(versions) < 2:
        return False
    # The run ends with Bolzen's summary after the second version.
    return any(event.get("type") == "chat" and event.get("role") == "agent" for event in events[versions[1] + 1 :]) and any(
        event.get("type") == "step" and event.get("id") == "stueckliste" and event.get("status") == "done" for event in events[versions[1] + 1 :]
    )


def _assert_story(events: list[dict]) -> None:
    sims = [event for event in events if event.get("type") == "sim"]
    if [event["result"] for event in sims] != ["fail", "pass", "pass"]:
        raise SystemExit("Läufe sollten fail, pass, pass sein: " + str([event["result"] for event in sims]))
    gust_low = min(point[3] for point in sims[0]["trajectory"] if point[0] >= 1.6)
    if gust_low > 0.2:
        raise SystemExit("Der schwere Lauf fängt die Böe ab: " + str(gust_low))
    if sims[1]["trajectory"][-1][3] < 0.35:
        raise SystemExit("Der leichte Lauf schwebt nicht.")
    steps = _latest_steps(events)
    if not all(steps.get(step) == "done" for step in STEPS):
        raise SystemExit("Schritte offen: " + str(steps))
    requirements: dict[str, dict] = {}
    for event in events:
        if event.get("type") == "requirement":
            requirements[event["id"]] = event
    if set(requirements) != {"budget", "flight_time", "weight", "hover", "printable"}:
        raise SystemExit("Vorgaben unvollständig: " + str(sorted(requirements)))
    if not all(item["met"] is True for item in requirements.values()):
        raise SystemExit("Nicht alle Vorgaben sind grün: " + str({k: v["met"] for k, v in requirements.items()}))
    flight = requirements["flight_time"]
    if "10" not in flight["text"] or not flight.get("changed_from") or flight.get("meeting_title") != "Review 1":
        raise SystemExit("Die Flugzeit aus dem Review fehlt: " + str(flight))
    if not all(item.get("speaker") and item.get("time") for item in requirements.values()):
        raise SystemExit("Zitate ohne Person oder Uhrzeit.")
    questions = [event for event in events if event.get("type") == "question"]
    if not questions or questions[-1]["status"] != "answered" or questions[-1]["answer_id"] != "new":
        raise SystemExit("Die Rückfrage zum Widerspruch fehlt: " + str(questions[-1:]))
    versions = [event for event in events if event.get("type") == "version"]
    first, second = versions[0], versions[1]
    if first["weight_g"] > 50 or first["price_eur"] > 120 or first["flight_time_min"] < 8:
        raise SystemExit("v1 verfehlt das Kickoff: " + str(first))
    if second["weight_g"] > 50 or second["price_eur"] > 120 or second["flight_time_min"] < 10:
        raise SystemExit("v2 verfehlt das Review: " + str(second))
    keys = {item["key"] for item in second["diff"]}
    if not {"weight_g", "flight_time_min", "price_eur", "part:battery"} <= keys:
        raise SystemExit("Differenz unvollständig: " + str(sorted(keys)))
    metrics = [event for event in events if event.get("type") == "metrics"][-1]
    if metrics["weight_g"] != second["weight_g"] or metrics["price_eur"] != second["price_eur"]:
        raise SystemExit("Kennzahlen und Version weichen ab.")
    bom = [event for event in events if event.get("type") == "bom"][-1]
    if abs(bom["total_eur"] - second["price_eur"]) > 0.01 or sum(1 for item in bom["items"] if item.get("category") != "filament") != 8:
        raise SystemExit("Stückliste passt nicht zur Version: " + str(bom["total_eur"]))
    weight = round(sum(item["weight_g"] * item["qty"] for item in bom["items"]), 1)
    if abs(weight - second["weight_g"]) > 0.15:
        raise SystemExit("Gewicht der Stückliste weicht ab: " + str(weight))
    plans = [event for event in events if event.get("type") == "print"]
    if len(plans) != 2 or plans[-1]["parts"][0]["id"] != "frame" or not plans[-1]["totals"]["filament_g"] > 0:
        raise SystemExit("Print plan per version missing: " + str([plan.get("totals") for plan in plans]))
    if plans[-1]["source"] == "estimate" and any(row["gcode_url"] for row in plans[-1]["parts"]):
        raise SystemExit("An estimate must not offer G-code.")
    if not any(item.get("category") == "filament" for item in bom["items"]):
        raise SystemExit("The bill of materials has no filament line.")
    guides = [event for event in events if event.get("type") == "build_guide"]
    if [guide["version"] for guide in guides] != [1, 2] or not all(guide["steps"] for guide in guides):
        raise SystemExit("Build guide missing for v1 and v2: " + str([guide["version"] for guide in guides]))
    if not any(second["parts"]["battery"] in step["items"] for step in guides[1]["steps"]):
        raise SystemExit("The v2 build guide does not name the v2 battery: " + second["parts"]["battery"])
    firmware = [event for event in events if event.get("type") == "firmware"]
    if len(firmware) != 2 or firmware[-1]["kind"] != "betaflight" or not firmware[-1]["content"].rstrip().endswith("save"):
        raise SystemExit("Firmware per version missing: " + str([event.get("filename") for event in firmware]))
    wired = " ".join(row["component"] + " " + row["connects_to"] for row in firmware[-1]["wiring"])
    electrical = [second["parts"][category] for category in ("motor", "battery", "flight_controller")]
    if not all(name in wired for name in electrical):
        raise SystemExit("Wiring does not match the parts: " + str(electrical))
    parts = {}
    warnings = 0
    for event in events:
        if event.get("type") == "part":
            warnings += len(event["warnings"])
            if not event.get("considered"):
                parts[event["category"]] = event
    if any(not item.get("why") for item in parts.values()):
        raise SystemExit("Teil ohne Warum: " + str([k for k, v in parts.items() if not v.get("why")]))
    if parts["battery"]["why"]["meeting_title"] != "Review 1":
        raise SystemExit("Der Akkutausch zitiert nicht das Review.")
    if warnings < 2:
        raise SystemExit("Warnungen aus früheren Meetings fehlen.")
    tasks = [event for event in events if event.get("type") == "tasks"][-1]
    if len(tasks["items"]) != 8 or not all(task["assignee"] and task["due"] for task in tasks["items"]):
        raise SystemExit("Aufgaben pro Person fehlen: " + str(tasks))
    jamie = {event.get("action") for event in events if event.get("type") == "jamie"}
    needed = {"upsert_template", "requirements", "search", "get_meeting", "create_tasks", "update_tasks", "create_tag", "add_tag_to_meetings", "note"}
    if not needed <= jamie:
        raise SystemExit("Jamie-Aktionen fehlen: " + str(sorted(needed - jamie)))
    meetings = {}
    for event in events:
        if event.get("type") == "meeting":
            meetings[event["id"]] = event
    if meetings["kickoff-drohne-2026-10-24"]["version"] != 1 or meetings["review-drohne-2026-10-24"]["version"] != 2:
        raise SystemExit("Versionen hängen nicht an ihren Meetings.")
    cad = [event for event in events if event.get("type") == "cad"][-1]
    if cad.get("source") not in {"freecad", "cadquery"} or not cad.get("tree") or not cad.get("params"):
        raise SystemExit("CAD unvollständig.")
    for key in ("glb_url", "stl_url", "step_url"):
        _fetch(cad[key], 100)
    renders = [event for event in events if event.get("type") == "render"]
    if not renders or not renders[-1].get("png_url"):
        raise SystemExit("Render fehlt.")
    _fetch(renders[-1]["png_url"], 32)
    if not any(event.get("type") == "point" and event.get("target") == "battery" for event in events):
        raise SystemExit("Der Zeiger trifft den Akku nicht.")


def _latest_steps(events: list[dict]) -> dict[str, str]:
    found = {}
    for event in events:
        if event.get("type") == "step":
            found[event["id"]] = event["status"]
    return found


def _summary(events: list[dict]) -> str:
    versions = [event for event in events if event.get("type") == "version"]
    rows = [
        "v" + str(v["n"]) + " " + str(v["weight_g"]) + " g, " + str(v["flight_time_min"]) + " min, " + str(v["price_eur"]) + " €"
        for v in versions
    ]
    return "mock ok: " + " | ".join(rows) + ", " + str(len(events)) + " events"


def _tail(events: list[dict]) -> str:
    steps = _latest_steps(events)
    sims = [event.get("result") for event in events if event.get("type") == "sim"]
    versions = [event.get("n") for event in events if event.get("type") == "version"]
    return str(steps) + " sims=" + str(sims) + " versions=" + str(versions)


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
            raise SystemExit("Server starb beim Start:\n" + _log_tail(log_path))
        if _healthy():
            return
        time.sleep(0.2)
    raise SystemExit("Server wurde nicht gesund.\n" + _log_tail(log_path))


def _log_tail(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[-2000:]


def _post(path: str, payload: dict) -> None:
    body = _post_json(path, payload)
    if body.get("status") != "started" or body.get("mode") != "mock":
        raise SystemExit("Prompt abgelehnt: " + str(body))


def _post_json(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch(path: str, minimum: int) -> None:
    if not str(path).startswith("/files/"):
        raise SystemExit("Datei-URL liegt nicht unter /files: " + str(path))
    with urllib.request.urlopen(BASE + path.split("?", 1)[0], timeout=10) as response:
        data = response.read()
    if len(data) < minimum:
        raise SystemExit("Datei zu klein: " + path)


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)


if __name__ == "__main__":
    main()
