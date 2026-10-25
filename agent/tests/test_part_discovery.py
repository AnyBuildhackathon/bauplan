"""Part discovery that scales: several pages of one product, the fields a build needs, any currency,
a library that learns, visible confidence with an exploration switch, and the distributor APIs.

The distributor responses in tests/fixtures/distributors/ are recorded samples shaped like the
official Digi-Key v4, Nexar supSearch and Mouser v1 schemas; their numbers are illustrative only.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from pai_agent import currency, distributors, learned_parts, settings, web_parts
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools.physics import compute
from pai_agent.tools.registry import call_tool

FIXTURES = Path(__file__).parent / "fixtures" / "distributors"
SHOP = "https://www.dfrobot.com/product-1752.html"
MAKER = "https://pixycam.com/pixy2/"
SHEET = "https://docs.pixycam.com/wiki/doku.php?id=wiki:v2:pixy2_datasheet.pdf"


def pixy(**changes) -> dict:
    """A vision sensor assembled from the shop listing, the maker page and the datasheet."""

    answer = {
        "found": True,
        "name": "Pixy2 CMUcam5 smart vision sensor",
        "manufacturer": "Charmed Labs",
        "mpn": "Pixy2",
        "url": SHOP,
        "shop": "DFRobot",
        "price": 64.90,
        "currency": "USD",
        "pack_qty": 1,
        "sources": [
            {"url": SHOP, "kind": "shop", "manufacturer": "Charmed Labs", "mpn": "Pixy2 (SEN0265)"},
            {"url": MAKER, "kind": "maker", "manufacturer": "Charmed Labs", "mpn": "Pixy2"},
            {"url": SHEET, "kind": "datasheet", "manufacturer": "Charmed Labs", "mpn": "Pixy2"},
        ],
        "specs": {
            "mass_g": {"value": [10, "g"], "source": MAKER, "read": "stated"},
            "length_mm": {"value": [38, "mm"], "source": SHEET, "read": "drawing"},
            "width_mm": {"value": [42, "mm"], "source": SHEET, "read": "drawing"},
            "height_mm": {"value": [15, "mm"], "source": SHEET, "read": "drawing"},
            "fov_deg": {"value": [80, "deg"], "source": SHOP, "read": "stated"},
            "resolution_px": {"value": [[1296, 976], "px"], "source": SHOP, "read": "stated"},
            "fps": {"value": [60, "fps"], "source": MAKER, "read": "stated"},
        },
        "note": "Pixy2 from DFRobot, numbers from the maker page and datasheet.",
    }
    answer.update(changes)
    return answer


class Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _ctx() -> Ctx:
    return Ctx(Bus(), BuildState(session_id="t", directory=Path(tempfile.mkdtemp())), auto_steps=False)


# --- 1. several pages of one exact product ------------------------------------------------------


def test_one_part_from_shop_maker_page_and_datasheet_each_number_with_its_source():
    part, problems = web_parts.validate("sensor", pixy(), today="2026-10-25", require=["fov_deg", "resolution_px", "fps"])
    assert problems == []
    assert part["id"] == "web-charmed-labs-pixy2" and part["mpn"] == "Pixy2"
    assert part["fields"]["mass_g"] == {"source": MAKER, "read": "stated", "confidence": "sourced"}
    assert part["fields"]["length_mm"]["confidence"] == "derived" and part["fields"]["length_mm"]["source"] == SHEET
    assert part["fields"]["fov_deg"]["source"] == SHOP
    assert part["resolution_px"] == [1296, 976] and part["size_mm"] == [38.0, 42.0, 15.0]
    assert {s["kind"] for s in part["sources"]} == {"shop", "maker", "datasheet"}
    assert all(s["checked"] == "2026-10-25" for s in part["sources"])
    assert part["confidence"] == "derived"  # two dimensions were read off the drawing


def test_a_source_naming_another_model_refuses_the_part():
    answer = pixy()
    answer["sources"][2] = {"url": SHEET, "kind": "datasheet", "manufacturer": "Charmed Labs", "mpn": "Pixy (CMUcam5, first generation)"}
    part, problems = web_parts.validate("sensor", answer)
    assert part is None
    assert any("names Pixy (CMUcam5" in p and "every source must be the same product" in p for p in problems)


def test_a_source_naming_another_maker_refuses_the_part():
    answer = pixy()
    answer["sources"][1] = {"url": MAKER, "kind": "maker", "manufacturer": "Arducam", "mpn": "Pixy2"}
    part, problems = web_parts.validate("sensor", answer)
    assert part is None and any("the maker Arducam" in p for p in problems)


def test_a_number_from_a_page_not_among_the_sources_is_refused():
    answer = pixy()
    answer["specs"]["mass_g"] = {"value": [10, "g"], "source": "https://forum.example.com/pixy-weight", "read": "stated"}
    part, problems = web_parts.validate("sensor", answer)
    assert part is None and any("not among the sources" in p for p in problems)


def test_several_pages_without_a_part_number_are_refused():
    part, problems = web_parts.validate("sensor", pixy(mpn=""))
    assert part is None and any("no part number" in p for p in problems)


# --- 2. required fields per need ----------------------------------------------------------------


def test_only_the_critical_fields_are_required_unless_the_build_asks_for_more():
    answer = pixy()
    for key in ("fov_deg", "resolution_px", "fps", "length_mm", "width_mm", "height_mm"):
        del answer["specs"][key]
    part, problems = web_parts.validate("sensor", answer)
    assert problems == [] and part["mass_g"] == 10.0 and "size_mm" not in part
    _part, problems = web_parts.validate("sensor", answer, require=["fov_deg", "fps"])
    assert "fov_deg is not on any of its pages." in problems and "fps is not on any of its pages." in problems


def test_a_motor_without_kv_or_size_passes_and_the_3d_model_draws_them_in_proportion():
    from pai_agent.part_models.web import spec_for

    motor = {
        "found": True, "name": "Example 1404 motor", "url": "https://store.example.com/1404", "price": 18, "currency": "EUR",
        "specs": {"mass_g": [9.6, "g"], "thrust_g": [418, "g"], "bench_voltage_v": [16.8, "V"], "bench_power_w": [221.8, "W"], "cells_max": [4, "S"]},
    }
    part, problems = web_parts.validate("motor", motor)
    assert problems == [] and "kv" not in part and "diameter_mm" not in part
    spec = spec_for({**part, "kv": None, "mount_diameter_mm": 9})
    assert "diameter_mm" not in spec["dims"] and spec["estimate"]["diameter_mm"] > 0


def test_unknown_required_fields_are_refused_before_any_search():
    result = asyncio.run(web_parts.discover("camera", "chase camera", require=["fov_deg", "dynamic_range_db"]))
    assert result["ok"] is False and "dynamic_range_db" in result["error"] and "fov_deg" in result["error"]


# --- 3. any currency at the day's ECB rate -------------------------------------------------------


def test_sek_converts_at_the_ecb_rate():
    answer = pixy(price=699, currency="SEK")
    part, problems = web_parts.validate("sensor", answer)
    assert problems == []
    assert part["unit_price_eur"] == round(699 / 11.1310, 2)
    assert part["price_rate"]["currency"] == "SEK" and "ECB reference rates of 2026-10-23" in part["price_rate"]["source"]
    assert "offline, built in" in part["price_rate"]["source"]


def test_unknown_and_unpublished_currencies_are_refused_with_a_reason():
    _part, problems = web_parts.validate("sensor", pixy(currency="XYZ"))
    assert any("Unknown currency XYZ" in p for p in problems)
    _part, problems = web_parts.validate("sensor", pixy(currency="RUB"))
    assert any("publishes no reference rate for RUB" in p for p in problems)
    _part, problems = web_parts.validate("sensor", pixy(currency="kr"))
    assert any("not an ISO 4217" in p for p in problems)


def test_the_ecb_file_is_fetched_once_a_day_and_cached(monkeypatch, tmp_path):
    calls = []

    def fetch():
        calls.append(1)
        return "2026-10-24", {"USD": 1.12, "SEK": 11.2}

    monkeypatch.setattr(currency, "_fetch", fetch)
    currency.reset()
    eur, info = currency.to_eur(112, "USD", today="2026-10-25")
    assert eur == pytest.approx(100) and info["source"] == "ECB reference rates of 2026-10-24"
    currency.reset()  # a new process the same day reads the cached file
    currency.to_eur(11.2, "SEK", today="2026-10-25")
    assert len(calls) == 1
    currency.reset()

    def down():
        raise OSError("offline")

    monkeypatch.setattr(currency, "_fetch", down)
    _eur, info = currency.to_eur(1, "USD", today="2026-10-26")
    assert info["source"] == "ECB reference rates of 2026-10-24 (offline, last fetched)"


# --- 5. the library that learns -----------------------------------------------------------------


def test_a_validated_part_persists_and_the_same_product_merges(monkeypatch):
    first, _ = web_parts.validate("sensor", pixy(), today="2026-10-20")
    stored = web_parts.add(first)
    learned_parts.reset()  # a new process
    assert [p["id"] for p in learned_parts.all_parts("sensor")] == [stored["id"]]
    again = pixy(name="Pixy2 (Charmed Labs) vision sensor", url="https://www.robotshop.com/products/pixy2", shop="RobotShop", price=59.0)
    again["sources"] = [{"url": "https://www.robotshop.com/products/pixy2", "kind": "shop", "manufacturer": "Charmed Labs Inc.", "mpn": "PIXY2"}] + again["sources"]
    second, problems = web_parts.validate("sensor", again, today="2026-10-25")
    assert problems == []
    merged = web_parts.add(second)
    parts = learned_parts.all_parts("sensor")
    assert len(parts) == 1 and merged["id"] == stored["id"]
    urls = {s["url"] for s in parts[0]["sources"]}
    assert SHOP in urls and "https://www.robotshop.com/products/pixy2" in urls
    assert parts[0]["checked"] == "2026-10-25"


def test_a_need_found_once_is_answered_from_the_library_without_searching(monkeypatch):
    monkeypatch.setattr(web_parts, "enabled", lambda: True)
    calls = []

    def ask(request, deadline):
        calls.append(request)
        return json.dumps(pixy())

    monkeypatch.setattr(web_parts, "_ask_claude", ask)
    need = "vision sensor that tracks a 6 mm fly, at least 60 fps"
    first = asyncio.run(web_parts.discover("sensor", need, require=["fov_deg", "fps"]))
    assert first["ok"] and first["from"] == "web" and len(calls) == 1
    learned_parts.reset()
    again = asyncio.run(web_parts.discover("sensor", need, require=["fov_deg", "fps"]))
    assert again["ok"] and again["from"] == "learned library" and len(calls) == 1
    by_number = asyncio.run(web_parts.discover("sensor", "smart camera", query="Pixy2", require=["fps"]))
    assert by_number["from"] == "learned library" and len(calls) == 1
    # A need the learned part cannot answer (no latency on its pages) searches again.
    asyncio.run(web_parts.discover("sensor", "smart camera", query="Pixy2", require=["latency_ms"]))
    assert len(calls) == 2


def test_learned_parts_show_in_both_tools_and_picks_are_counted(monkeypatch):
    part, _ = web_parts.validate("camera", {**pixy(), "name": "Pixy2 camera"}, require=["fov_deg"])
    web_parts.add(part)
    ctx = _ctx()
    listed = asyncio.run(call_tool(ctx, "parts_search", {"category": "camera", "query": "pixy2"}))
    assert listed["parts"][0]["id"] == part["id"] and listed["parts"][0]["confidence"] == "derived"
    asyncio.run(call_tool(ctx, "parts_search", {"category": "camera", "select_id": part["id"]}))
    assert learned_parts.get(part["id"])["used"] == 1
    event = [e for e in ctx.bus.events if e.get("type") == "part"][-1]
    assert event["confidence"] == "derived" and event["fields"]["fov_deg"] == {"confidence": "sourced", "source": SHOP}
    assert {s["kind"] for s in event["sources"]} == {"shop", "maker", "datasheet"}


def test_the_review_script_lists_shows_and_prunes(tmp_path):
    estimated = {**pixy(), "mpn": "Pixy2.1", "sources": None}
    estimated["specs"] = {**pixy()["specs"], "latency_ms": {"value": [30, "ms"], "read": "estimated", "basis": "typical for USB cameras"}}
    del estimated["sources"]
    a, _ = web_parts.validate("sensor", pixy())
    b, problems = web_parts.validate("sensor", estimated, allow_estimated=True)
    assert problems == []
    web_parts.add(a)
    web_parts.add(b)
    script = Path(__file__).parents[1] / "scripts" / "learned_parts.py"
    env = dict(os.environ)

    def run(*args):
        return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, env=env, check=False)

    listing = run("list")
    assert a["id"] in listing.stdout and b["id"] in listing.stdout and "estimated (latency_ms)" in listing.stdout
    shown = run("show", a["id"])
    assert MAKER in shown.stdout and "fov_deg" in shown.stdout
    dry = run("prune", "--estimated")
    assert "would be removed" in dry.stdout and b["id"] in dry.stdout
    assert run("prune", "--estimated", "--yes").returncode == 0
    learned_parts.reset()
    assert [p["id"] for p in learned_parts.all_parts()] == [a["id"]]


# --- 6. confidence and the exploration switch ---------------------------------------------------


def _with_estimate():
    answer = pixy()
    answer["specs"]["latency_ms"] = {"value": [30, "ms"], "read": "estimated", "basis": "typical for USB cameras"}
    return answer


def test_estimates_are_left_out_unless_exploration_is_on():
    part, problems = web_parts.validate("sensor", _with_estimate())
    assert problems == [] and "latency_ms" not in part and part["left_out"] == ["latency_ms"] and part["estimated"] == []
    part, problems = web_parts.validate("sensor", _with_estimate(), allow_estimated=True)
    assert problems == [] and part["latency_ms"] == 30.0
    assert part["confidence"] == "estimated" and part["estimated"] == ["latency_ms"]
    assert part["fields"]["latency_ms"] == {"source": None, "read": "estimated", "confidence": "estimated", "basis": "typical for USB cameras"}


def test_a_needed_field_may_be_estimated_only_in_exploration_and_a_critical_one_never():
    answer = _with_estimate()
    _part, problems = web_parts.validate("sensor", answer, require=["latency_ms"])
    assert "latency_ms is required and may not be an estimate." in problems
    part, problems = web_parts.validate("sensor", answer, require=["latency_ms"], allow_estimated=True)
    assert problems == [] and part["estimated"] == ["latency_ms"]
    answer["specs"]["mass_g"] = {"value": [10, "g"], "read": "estimated", "basis": "looks light"}
    _part, problems = web_parts.validate("sensor", answer, allow_estimated=True)
    assert "mass_g is required and may not be an estimate." in problems


def test_estimated_learned_parts_stay_out_of_real_builds(monkeypatch):
    part, _ = web_parts.validate("camera", _with_estimate(), allow_estimated=True)
    web_parts.add(part)
    assert web_parts.found_parts("camera") == []
    ctx = _ctx()
    refused = asyncio.run(call_tool(ctx, "parts_search", {"category": "camera", "select_id": part["id"]}))
    assert refused["ok"] is False
    settings.update({"allow_estimated": True})
    assert [p["id"] for p in web_parts.found_parts("camera")] == [part["id"]]
    picked = asyncio.run(call_tool(ctx, "parts_search", {"category": "camera", "select_id": part["id"]}))
    assert picked["ok"] is True
    assert settings.public()["allow_estimated"] is True


def test_the_exploration_switch_reads_the_environment(monkeypatch):
    assert web_parts.allow_estimated() is False
    monkeypatch.setenv("PAI_ALLOW_ESTIMATED", "1")
    assert web_parts.allow_estimated() is True


def test_metrics_say_when_they_rest_on_estimates():
    camera, _ = web_parts.validate("camera", _with_estimate(), allow_estimated=True)
    settings.update({"allow_estimated": True})
    web_parts.add(camera)
    ctx = _ctx()
    for category, part_id in (("motor", "betafpv-1104-5500kv"), ("propeller", "gemfan-d63-3"), ("battery", "betafpv-lava-4s-550"), ("flight_controller", "betafpv-cube-2-4s-30a"), ("frame", "betafpv-pavo25-v2"), ("camera", camera["id"])):
        assert asyncio.run(call_tool(ctx, "parts_search", {"category": category, "select_id": part_id}))["ok"]
    metrics = compute(ctx.state)
    assert any("Pixy2" in line and "latency_ms" in line for line in metrics["estimated_inputs"])
    asyncio.run(call_tool(ctx, "physics_calc", {}))
    event = [e for e in ctx.bus.events if e.get("type") == "metrics"][-1]
    assert event["estimated_inputs"] == metrics["estimated_inputs"]


def test_mission_event_lists_estimates(monkeypatch):
    from pai_agent.tools import mission

    camera, _ = web_parts.validate("camera", _with_estimate(), allow_estimated=True)
    state = BuildState(session_id="t", directory=Path(tempfile.mkdtemp()))
    state.selected = {"camera": camera}
    ctx = Ctx(Bus(), state, auto_steps=False)
    outcome = {"mission": "chase", "capture_s": 3.0, "caught": 5, "flies": 5, "detect_range_m": 4.0, "sensing_delay_ms": 60.0}
    monkeypatch.setattr(mission, "run", lambda frame, name, gains: outcome)
    monkeypatch.setattr(mission, "passes", lambda outcome, limit: True)
    monkeypatch.setattr(mission, "_summary", lambda *a: "ok")
    monkeypatch.setattr(mission, "_why", lambda *a: "ok")
    monkeypatch.setattr(mission, "_ensure_row", lambda state, name, entry: {"id": "chase_time", "limit": 10})
    monkeypatch.setattr(mission, "_limit", lambda row: 10.0)
    frame = {"parts": {"camera": camera["id"]}, "geo": {"arm_length_mm": 40.0}, "camera": {"assumed": ["fps"]}}
    results = asyncio.run(mission.fly_missions(ctx, [{"mission": "chase"}], {}, {"total_mass_g": 100.0}, frame))
    assert results[0]["estimated_inputs"] == ["Pixy2 CMUcam5 smart vision sensor: latency_ms", "camera defaults: fps"]
    event = [e for e in ctx.bus.events if e.get("type") == "mission"][-1]
    assert event["estimated_inputs"] == results[0]["estimated_inputs"]


# --- 7. distributor APIs ------------------------------------------------------------------------


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_digikey_response_maps_to_catalog_fields():
    [item] = distributors.parse_digikey(_fixture("digikey_keyword.json"))
    assert item["manufacturer"] == "Arducam" and item["mpn"] == "B0165" and item["price"] == 41.37 and item["currency"] == "EUR"
    assert item["datasheet_url"].endswith("B0165.pdf") and item["stock"] == 112
    assert item["specs"]["resolution_px"] == [[1280, 800], "px"]
    assert item["specs"]["fps"] == [120.0, "fps"] and item["specs"]["voltage_v"] == [3.3, "V"]
    assert item["specs"]["length_mm"] == [24.0, "mm"] and item["specs"]["width_mm"] == [24.0, "mm"]


def test_nexar_response_maps_to_catalog_fields():
    [item] = distributors.parse_nexar(_fixture("nexar_supsearch.json"))
    assert item["url"].startswith("https://octopart.com/") and item["price"] == 41.05 and item["currency"] == "EUR"
    assert item["specs"]["mass_g"] == [3.0, "g"] and item["specs"]["fps"] == [120.0, "fps"]
    assert item["specs"]["resolution_px"] == [[1280, 800], "px"] and item["stock"] == 340


def test_mouser_response_maps_to_catalog_fields():
    [item] = distributors.parse_mouser(_fixture("mouser_keyword.json"))
    assert item["price"] == 41.15 and item["currency"] == "EUR" and item["stock"] == 228
    assert item["specs"]["mass_g"] == [4.5, "g"]  # from UnitWeightKg
    assert item["url"].startswith("https://www.mouser.de/")


def test_the_same_part_at_three_distributors_is_one_candidate_and_disagreements_drop_the_number():
    items = distributors.parse_digikey(_fixture("digikey_keyword.json")) + distributors.parse_nexar(_fixture("nexar_supsearch.json")) + distributors.parse_mouser(_fixture("mouser_keyword.json"))
    [one] = distributors.combine(items)
    assert [l["distributor"] for l in one["listings"]] == ["Digi-Key", "Nexar", "Mouser"]
    assert one["specs"]["mass_g"] == [3.0, "g"]  # Nexar's; Mouser's unit weight is not compared
    disagreeing = json.loads(json.dumps(items))
    disagreeing[2]["specs"]["fps"] = [60.0, "fps"]
    [other] = distributors.combine(disagreeing)
    assert "fps" not in other["specs"] and any(c.startswith("fps:") for c in other["conflicts"])


def _configured(monkeypatch):
    for name, value in (("DIGIKEY_CLIENT_ID", "dk-id-123"), ("DIGIKEY_CLIENT_SECRET", "dk-secret-456"), ("NEXAR_CLIENT_ID", "nx-id-789"), ("NEXAR_CLIENT_SECRET", "nx-secret-012"), ("MOUSER_API_KEY", "mouser-key-345")):
        monkeypatch.setenv(name, value)
    calls = []

    def http(method, url, headers, body=None, timeout=15.0):
        calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if url == distributors.DIGIKEY_TOKEN_URL:
            return {"access_token": "dk-token", "expires_in": 599, "token_type": "Bearer"}
        if url == distributors.NEXAR_TOKEN_URL:
            return {"access_token": "nx-token", "expires_in": 86400, "token_type": "Bearer"}
        if url == distributors.DIGIKEY_SEARCH_URL:
            return _fixture("digikey_keyword.json")
        if url == distributors.NEXAR_GRAPHQL_URL:
            return _fixture("nexar_supsearch.json")
        if url.startswith(distributors.MOUSER_SEARCH_URL):
            return _fixture("mouser_keyword.json")
        raise AssertionError(url)

    monkeypatch.setattr(distributors, "_http", http)
    return calls


def test_adapters_send_the_documented_requests_and_cache_tokens_and_results(monkeypatch):
    calls = _configured(monkeypatch)
    found = distributors.search("camera", "OV9281 camera module")
    assert found["used"] == ["Digi-Key", "Nexar", "Mouser"] and len(found["candidates"]) == 1
    digikey = next(c for c in calls if c["url"] == distributors.DIGIKEY_SEARCH_URL)
    assert digikey["headers"]["Authorization"] == "Bearer dk-token" and digikey["headers"]["X-DIGIKEY-Client-Id"] == "dk-id-123"
    assert json.loads(digikey["body"]) == {"Keywords": "OV9281 camera module", "Limit": 4, "Offset": 0}
    token = next(c for c in calls if c["url"] == distributors.NEXAR_TOKEN_URL)
    assert b"scope=supply.domain" in token["body"] and b"grant_type=client_credentials" in token["body"]
    graphql = json.loads(next(c for c in calls if c["url"] == distributors.NEXAR_GRAPHQL_URL)["body"])
    assert "supSearch" in graphql["query"] and graphql["variables"] == {"q": "OV9281 camera module", "limit": 4}
    mouser = next(c for c in calls if c["url"].startswith(distributors.MOUSER_SEARCH_URL))
    assert json.loads(mouser["body"])["SearchByKeywordRequest"]["keyword"] == "OV9281 camera module"
    count = len(calls)
    distributors.search("camera", "OV9281 camera module")
    assert len(calls) == count  # a day's results come from the cache
    distributors.search("camera", "IMX219 camera module")
    assert sum(1 for c in calls if c["url"] in (distributors.DIGIKEY_TOKEN_URL, distributors.NEXAR_TOKEN_URL)) == 2  # tokens reused


def test_no_credential_reaches_an_error_or_a_log(monkeypatch, caplog):
    _configured(monkeypatch)

    def failing(method, url, headers, body=None, timeout=15.0):
        raise distributors.DistributorError(distributors.scrub("HTTP 401: bad key mouser-key-345 for " + url))

    monkeypatch.setattr(distributors, "_http", failing)
    with caplog.at_level("DEBUG"):
        found = distributors.search("camera", "OV9281")
    text = json.dumps(found) + caplog.text
    for secret in ("dk-id-123", "dk-secret-456", "nx-id-789", "nx-secret-012", "mouser-key-345"):
        assert secret not in text
    assert any("Mouser" in n for n in found["notes"])


def test_mouser_daily_budget_is_kept(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(distributors.Mouser.budget, "per_day", 2)
    monkeypatch.setenv("DIGIKEY_CLIENT_ID", "")
    monkeypatch.setenv("NEXAR_CLIENT_ID", "")
    for word in ("a1", "b2"):
        assert distributors.search("camera", word)["used"] == ["Mouser"]
    blocked = distributors.search("camera", "c3")
    assert blocked["used"] == [] and "1,000" not in blocked["notes"][0] and "2 calls a day" in blocked["notes"][0]


def test_without_credentials_the_distributors_are_skipped():
    assert distributors.configured() == []
    assert distributors.search("camera", "OV9281") == {"candidates": [], "used": [], "notes": []}


def test_a_complete_distributor_part_needs_no_web_search(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(web_parts, "_ask_claude", lambda request, deadline: pytest.fail("no web search expected"))
    result = asyncio.run(web_parts.discover("camera", "global shutter camera for a fly chase", query="OV9281 camera module", require=["fps", "resolution_px"]))
    assert result["ok"] and result["from"] == "distributors"
    part = result["part"]
    assert part["mpn"] == "B0165" and part["fps"] == 120.0 and part["resolution_px"] == [1280, 800]
    assert {s.get("distributor") for s in part["sources"]} == {"Digi-Key", "Nexar", "Mouser"}
    assert part["fields"]["mass_g"]["source"].startswith("https://octopart.com/")


def test_an_incomplete_distributor_part_is_completed_from_its_datasheet(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(web_parts, "enabled", lambda: True)
    seen = {}
    sheet = "https://www.arducam.com/downloads/datasheet/B0165.pdf"

    def ask(request, deadline):
        seen["prompt"] = request["messages"][0]["content"]
        seen["tools"] = [t["type"] for t in request["tools"]]
        return json.dumps({
            "found": True, "name": "Arducam B0165 OV9281 camera", "manufacturer": "Arducam", "mpn": "B0165",
            "url": "https://www.arducam.com/product/b0165/", "shop": "Arducam", "price": 399, "currency": "SEK",
            "sources": [{"url": "https://www.arducam.com/product/b0165/", "kind": "maker", "manufacturer": "Arducam", "mpn": "B0165"},
                        {"url": sheet, "kind": "datasheet", "manufacturer": "Arducam", "mpn": "B0165"}],
            "specs": {"mass_g": {"value": [3, "g"], "source": sheet, "read": "stated"}, "fov_deg": {"value": [80, "°"], "source": sheet, "read": "stated"}},
        })

    monkeypatch.setattr(web_parts, "_ask_claude", ask)
    result = asyncio.run(web_parts.discover("camera", "global shutter camera that sees a fly", query="OV9281 camera module", require=["fov_deg", "fps", "latency_ms"]))
    # latency_ms is on no page: refused in a real build, with the exploration hint.
    assert result["ok"] is False and "latency_ms" in result["error"] and "Exploration mode" in result["error"]
    assert "Arducam B0165" in seen["prompt"] and any(t.startswith("web_fetch_") for t in seen["tools"])
    result = asyncio.run(web_parts.discover("camera", "global shutter camera that sees a fly", query="OV9281 camera module", require=["fov_deg", "fps"]))
    assert result["ok"] and result["from"] == "web"
    part = result["part"]
    assert part["fov_deg"] == 80.0 and part["fps"] == 120.0  # fps from the distributors, fov from the datasheet
    assert part["fields"]["fps"]["source"].startswith("https://www.digikey.de/") and part["fields"]["fov_deg"]["source"] == sheet
    assert part["unit_price_eur"] == round(399 / 11.1310, 2)
    assert {"Digi-Key", "Nexar", "Mouser"} <= {s.get("distributor") for s in part["sources"]}


def test_pages_that_disagree_with_the_distributors_refuse_the_part(monkeypatch):
    candidates = distributors.combine(distributors.parse_digikey(_fixture("digikey_keyword.json")))
    answer = {
        "found": True, "name": "Arducam B0165", "manufacturer": "Arducam", "mpn": "B0165", "url": "https://www.arducam.com/product/b0165/", "price": 40, "currency": "EUR",
        "sources": [{"url": "https://www.arducam.com/product/b0165/", "kind": "maker", "manufacturer": "Arducam", "mpn": "B0165"}],
        "specs": {"mass_g": {"value": [3, "g"], "source": "https://www.arducam.com/product/b0165/", "read": "stated"}, "fps": {"value": [60, "fps"], "source": "https://www.arducam.com/product/b0165/", "read": "stated"}},
    }
    part, problems = web_parts.validate("camera", web_parts.with_candidate(answer, candidates, "camera"))
    assert part is None and any("fps: the pages say 60, Digi-Key lists 120" in p for p in problems)


# --- found in the live build ------------------------------------------------------------------


def test_a_fuzzy_distributor_hit_is_not_taken_as_the_part(monkeypatch):
    _configured(monkeypatch)
    backshell = _fixture("mouser_keyword.json")
    part = backshell["SearchResults"]["Parts"][0]
    part.update({"Manufacturer": "Hirose Connector", "ManufacturerPartNumber": "HDB-CTF(50)", "Description": "D-Sub Backshells", "ProductAttributes": []})
    monkeypatch.setattr(distributors, "PROVIDERS", [distributors.Mouser()])
    monkeypatch.setattr(distributors, "_http", lambda *a, **k: backshell)
    monkeypatch.setattr(web_parts, "enabled", lambda: False)
    result = asyncio.run(web_parts.discover("vtx", "digital video transmitter for HDZero", query="HDZero whoop VTX"))
    assert result["ok"] is False and result["search"]["distributor_matches"] == 0


def test_a_vtx_power_in_milliwatts():
    vtx = {"found": True, "name": "VTX", "url": "https://shop.example.com/vtx", "price": 30, "currency": "EUR", "specs": {"mass_g": [4.5, "g"], "power_mw": [200, "mW"]}}
    part, problems = web_parts.validate("vtx", vtx)
    assert problems == [] and part["power_mw"] == 200.0


def test_a_co_branded_part_with_the_same_part_number_is_the_same_product():
    answer = pixy(name="RunCam HDZero Nano 90 camera", manufacturer="HDZero", mpn="Nano 90")
    answer["sources"] = [
        {"url": SHOP, "kind": "shop", "manufacturer": "RunCam", "mpn": "HDZero Nano 90"},
        {"url": MAKER, "kind": "maker", "manufacturer": "HDZero", "mpn": "Nano 90"},
        {"url": SHEET, "kind": "datasheet", "manufacturer": "HDZero", "mpn": "Nano 90"},
    ]
    part, problems = web_parts.validate("camera", answer)
    assert problems == [] and part["manufacturer"] == "HDZero"


def test_a_stated_horizontal_view_gives_the_diagonal_as_derived():
    answer = pixy()
    answer["specs"].pop("fov_deg")
    answer["specs"]["fov_h_deg"] = {"value": [70.8, "°"], "source": MAKER, "read": "stated"}
    answer["specs"] = {k: v for k, v in answer["specs"].items() if not k.endswith("_mm")}
    part, problems = web_parts.validate("camera", answer, require=["fov_deg"])
    assert problems == []
    assert part["fov_deg"] == round(70.8 * 5 / 4, 1)
    assert part["fields"]["fov_deg"] == {"read": "computed", "from": ["fov_h_deg"], "confidence": "derived"}
    assert part["confidence"] == "derived"


def test_the_search_cost_is_visible(monkeypatch):
    monkeypatch.setattr(web_parts, "enabled", lambda: True)
    usage = {"input_tokens": 120000, "output_tokens": 4000, "cache_read_tokens": 0, "cache_write_tokens": 0, "searches": 7, "fetches": 3}
    monkeypatch.setattr(web_parts, "_ask_claude", lambda request, deadline: (json.dumps(pixy()), usage))
    monkeypatch.setattr(web_parts, "model_name", lambda: "claude-sonnet-5-5")
    result = asyncio.run(call_tool(_ctx(), "parts_search", {"category": "camera", "web": True, "need": "a camera that sees a fly", "require": ["fov_deg"]}))
    cost = result["web_find"]["search"]["cost"]
    assert cost == {"searches": 7, "page_reads": 3, "input_tokens": 120000, "output_tokens": 4000, "usd": round((120000 * 2.0 + 4000 * 10.0) / 1e6 + 0.07, 4)}
    assert "7 searches, 3 page reads, $0.35" in result["detail"]
