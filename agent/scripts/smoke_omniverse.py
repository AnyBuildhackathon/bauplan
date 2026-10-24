"""One mock HTTP/SSE smoke run against the already running backend on port 8113."""

import json
import os
import urllib.request

base = "http://127.0.0.1:" + os.environ.get("SMOKE_PORT", "8113")
with urllib.request.urlopen(base + "/api/health", timeout=5) as response:
    assert json.load(response)["mode"] == "mock", "Start the backend with PAI_FORCE_MOCK=1"
request = urllib.request.Request(base + "/api/prompt", data=json.dumps({"text": "Test 8 m/s wind gusts with a 10 g camera in Omniverse."}).encode(), headers={"Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=5) as response:
    assert json.load(response)["status"] == "started"
with urllib.request.urlopen(base + "/api/events", timeout=10) as response:
    for line in response:
        if not line.startswith(b"data: "):
            continue
        event = json.loads(line[6:])
        if event.get("type") == "omniverse" and event.get("status") == "recorded":
            assert event["source"] == "recorded"
            assert event["requested"]["wind_m_s"] == 8
            assert event["requested"]["payload_g"] == 10
            assert event["parameters"]["wind_m_s"] == 6
            assert not event["product_tested"]
            break
    else:
        raise AssertionError("No recorded Omniverse result arrived")
for name in ("video_url", "json_url"):
    with urllib.request.urlopen(base + event[name], timeout=5) as response:
        data = response.read()
        assert response.status == 200 and len(data) > 32
        if name == "video_url":
            assert b"ftyp" in data[:32]
        else:
            assert "test" in json.loads(data)
print("PASS: chat -> tool dispatch -> SSE recorded provenance -> MP4 + JSON artifacts")
