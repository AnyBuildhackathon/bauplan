"""HTTP/SSE smoke against a mock orchestrator; ISAAC_LIVE=1 requires real GPU artifacts.

For live verification, build a drone in the backend before running this script.
"""

import json
import os
import urllib.request

base = "http://127.0.0.1:" + os.environ.get("SMOKE_PORT", "8113")
live = os.environ.get("ISAAC_LIVE") == "1"
with urllib.request.urlopen(base + "/api/health", timeout=5) as response:
    assert json.load(response)["mode"] == "mock", "Start the backend with PAI_FORCE_MOCK=1"
request = urllib.request.Request(base + "/api/prompt", data=json.dumps({"text": "Test 8 m/s wind gusts with a 10 g camera in Omniverse."}).encode(), headers={"Content-Type": "application/json"})
with urllib.request.urlopen(base + "/api/events", timeout=600 if live else 10) as response:
    sent = False
    for line in response:
        if not line.startswith(b"data: "):
            continue
        event = json.loads(line[6:])
        if event.get("type") == "replayed" and not sent:
            with urllib.request.urlopen(request, timeout=5) as started:
                assert json.load(started)["status"] == "started"
            sent = True
            continue
        if not sent:
            continue
        if event.get("type") == "omniverse" and event.get("status") in {"done", "recorded"}:
            assert event["source"] == ("live" if live else "recorded"), event["detail"]
            assert event["requested"]["wind_m_s"] == 8
            assert event["requested"]["payload_g"] == 10
            if live:
                assert event["status"] == "done" and event["product_tested"]
                assert event["parameters"]["wind_m_s"] == 8
                assert event["metrics"]["assembly_mass_g"] > 0
                assert abs(event["metrics"]["total_mass_g"] - event["metrics"]["assembly_mass_g"] - 10) < 0.001
            else:
                assert event["parameters"]["wind_m_s"] == 6
                assert not event["product_tested"]
            break
    else:
        raise AssertionError("No completed Omniverse result arrived")
for name in ("video_url", "json_url"):
    with urllib.request.urlopen(base + event[name], timeout=5) as response:
        data = response.read()
        assert response.status == 200 and len(data) > 32
        if name == "video_url":
            assert b"ftyp" in data[:32]
        else:
            result = json.loads(data)
            if live:
                assert result.get("source") == "live"
            else:
                assert "test" in result
print("PASS: chat -> tool dispatch -> SSE " + ("live GPU" if live else "recorded") + " provenance -> MP4 + JSON artifacts")
