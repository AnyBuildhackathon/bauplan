"""Offline check for live BOM prices: stubs the Claude web search and checks merge, fallback, cache and deadline.

Run: cd agent && uv run python scripts/check_live_prices.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from pai_agent.tools import parts_search

ITEMS = [
    {"name": "BetaFPV 1102 22000KV", "qty": 4, "unit_price_eur": 4.99, "weight_g": 2.79, "shop": "BetaFPV", "url": "https://betafpv.com/a"},
    {"name": "Gemfan 1635-3 40 mm", "qty": 4, "unit_price_eur": 0.95, "weight_g": 0.6, "shop": "Gemfan", "url": "https://gemfan.example/b"},
    {"name": "BetaFPV Lava 1S 550mAh 75C", "qty": 1, "unit_price_eur": 6.49, "weight_g": 14.0, "shop": "BetaFPV", "url": "https://betafpv.com/c"},
    {"name": "Gedruckter Whoop-Rahmen PLA", "qty": 1, "unit_price_eur": 1.8, "weight_g": 9.0, "shop": "Werkstatt", "url": ""},
]

ANSWERS = {
    # A live EUR price from a German shop, wrapped in prose around the JSON.
    "BetaFPV 1102 22000KV": 'Found it.\n{"found": true, "price": 5.49, "currency": "EUR", "price_eur": 5.49, "pack_qty": 4, '
    '"shop": "FPV24", "url": "https://www.fpv24.com/de/betafpv/1102", "availability": "in_stock"}',
    # A pack price passed off as per piece: far off the catalog, so it falls back.
    "Gemfan 1635-3 40 mm": '{"found": true, "price": 12.0, "currency": "EUR", "price_eur": 12.0, "shop": "X", "url": "https://x.example/p"}',
    # A USD price with a converted EUR value.
    "BetaFPV Lava 1S 550mAh 75C": '{"found": true, "price": 7.99, "currency": "USD", "price_eur": 7.35, "pack_qty": 4, '
    '"shop": "BetaFPV", "url": "https://betafpv.com/products/lava", "availability": "unknown"}',
}

calls: list[str] = []


def fake_ask(request: dict, deadline: float) -> str:
    text = request["messages"][0]["content"]
    name = text.splitlines()[0].removeprefix("Part: ")
    calls.append(name)
    assert request["tools"][0]["name"] == "web_search", request["tools"]
    return ANSWERS[name]


async def main() -> None:
    os.environ["ANTHROPIC_API_KEY"] = "stub"
    assert parts_search.live_prices_enabled()

    assert parts_search._web_search_tool("claude-sonnet-5-5")["type"] == "web_search_20260209"
    assert parts_search._web_search_tool("claude-opus-4-6")["type"] == "web_search_20260209"
    assert parts_search._web_search_tool("claude-haiku-4-5")["type"] == "web_search_20250305"
    assert "output_config" not in parts_search._request(ITEMS[0], "claude-haiku-4-5")

    fenced = 'Prices {per piece} below.\n```json\n{"found": true, "price": 1, "meta": {"a": 1}}\n```'
    assert parts_search._parse(fenced) == {"found": True, "price": 1, "meta": {"a": 1}}
    assert parts_search._parse("no json here") is None

    # A search whose deadline has passed sends no request.
    request = parts_search._request(ITEMS[0], "claude-sonnet-5-5")
    assert parts_search._ask_claude(request, time.monotonic() - 1) == ""

    parts_search._ask_claude = fake_ask
    lines = await parts_search.live_lines(ITEMS)
    by_name = {line["name"]: line for line in lines}
    motor = by_name["BetaFPV 1102 22000KV"]
    assert motor["price_source"] == "live" and motor["unit_price_eur"] == 5.49 and motor["shop"] == "FPV24", motor
    assert motor["catalog_price_eur"] == 4.99 and motor["availability"] == "in_stock"
    assert by_name["Gemfan 1635-3 40 mm"]["price_source"] == "catalog"
    assert by_name["Gemfan 1635-3 40 mm"]["unit_price_eur"] == 0.95
    lava = by_name["BetaFPV Lava 1S 550mAh 75C"]
    assert lava["price_source"] == "live" and lava["unit_price_eur"] == 7.35 and lava["currency"] == "USD", lava
    frame = by_name["Gedruckter Whoop-Rahmen PLA"]
    assert frame["price_source"] == "catalog" and "Gedruckter Whoop-Rahmen PLA" not in calls

    # A second build inside the cache window searches nothing again.
    before = len(calls)
    await parts_search.live_lines(ITEMS)
    assert len(calls) == before, calls

    # Metric recomputes take the cached live price per piece, else the catalog one.
    assert parts_search.unit_price_eur({"name": "BetaFPV 1102 22000KV", "unit_price_eur": 4.99}) == 5.49
    assert parts_search.unit_price_eur({"name": "Gemfan 1635-3 40 mm", "unit_price_eur": 0.95}) == 0.95
    assert parts_search.unit_price_eur({"name": "Gedruckter Whoop-Rahmen PLA", "unit_price_eur": 1.8}) == 1.8

    # A failing search falls back to the catalog line.
    parts_search._CACHE.clear()

    def broken(request: dict, deadline: float) -> str:
        raise RuntimeError("network down")

    parts_search._ask_claude = broken
    lines = await parts_search.live_lines(ITEMS[:1])
    assert lines[0]["price_source"] == "catalog" and lines[0]["unit_price_eur"] == 4.99
    assert parts_search.unit_price_eur({"name": "BetaFPV 1102 22000KV", "unit_price_eur": 4.99}) == 4.99
    print(json.dumps({"ok": True, "searched": sorted(set(calls))}))


if __name__ == "__main__":
    asyncio.run(main())
