"""Live shop prices for bill-of-materials lines.

Claude with Anthropic's server-side web search finds each part at a real shop (EU first)
and returns price, currency, shop, URL and availability. Results sit in a short in-memory
cache. Without ANTHROPIC_API_KEY, or when a search fails, the line keeps its catalog price
and is labelled "catalog".
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from pai_agent.env import load_env, model_name

log = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, dict | None]] = {}
_CACHE_TTL_S = 900.0
_FAILED_TTL_S = 60.0
_TIMEOUT_S = 45.0
# A live price far away from the catalog sample is usually a multipack or a different part.
_MAX_RATIO = 4.0

_SYSTEM = (
    "You find current retail prices for drone parts. Use web search. "
    "Prefer shops that ship within the EU (Germany first), then the official manufacturer store. "
    "Pick the exact part, not a similar one. When the shop sells a multipack, give the price per piece "
    "and the pack size. Answer with one JSON object and nothing else."
)

_ANSWER = (
    '{"found": true, "price": 19.99, "currency": "EUR", "price_eur": 19.99, "pack_qty": 1, '
    '"shop": "Example Shop", "url": "https://...", "availability": "in_stock"}'
)


def live_prices_enabled() -> bool:
    load_env()
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _version(model: str) -> tuple[str, float]:
    match = re.match(r"claude-([a-z]+)-(\d+)(?:-(\d))?(?:\b|-)", model)
    if not match:
        return "", 0.0
    minor = match.group(3) or "0"
    return match.group(1), float(match.group(2) + "." + minor)


def _web_search_tool(model: str) -> dict:
    family, version = _version(model)
    # The dynamic-filtering variant needs Opus or Sonnet 4.6 and later (or Fable/Mythos).
    modern = family in {"fable", "mythos"} or (family in {"opus", "sonnet"} and version >= 4.6)
    kind = "web_search_20260209" if modern else "web_search_20250305"
    return {
        "type": kind,
        "name": "web_search",
        "max_uses": 4,
        "user_location": {"type": "approximate", "city": "Berlin", "country": "DE", "timezone": "Europe/Berlin"},
    }


def _request(item: dict, model: str) -> dict:
    hint = item.get("shop") or ""
    prompt = (
        "Part: " + item["name"] + "\n"
        + "Quantity needed: " + str(item["qty"]) + "\n"
        + ("Catalog shop hint: " + hint + "\n" if hint else "")
        + "Catalog sample price per piece: " + f"{float(item['unit_price_eur']):.2f}" + " EUR\n\n"
        + "Find where to buy it now. Return price (per piece, in the shop's currency), currency (ISO code), "
        + "price_eur (per piece converted to EUR), pack_qty, shop, url (the product page), and availability "
        + "(in_stock, out_of_stock or unknown). If you cannot find this exact part, return {\"found\": false}.\n"
        + "Shape: " + _ANSWER
    )
    request = {
        "model": model,
        "max_tokens": 4000,
        "system": _SYSTEM,
        "tools": [_web_search_tool(model)],
        "messages": [{"role": "user", "content": prompt}],
    }
    family, version = _version(model)
    if version >= 4.6:
        request["output_config"] = {"effort": "low"}
    return request


def _ask_claude(request: dict, deadline: float) -> str:
    """One blocking search conversation; returns the final text. Runs in a worker thread."""

    import anthropic

    client = anthropic.Anthropic(max_retries=0)
    messages = list(request["messages"])
    text = ""
    # Long searches pause the turn; send the partial answer back so the server continues it.
    for _round in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        response = client.messages.create(**{**request, "messages": messages}, timeout=remaining)
        text = "".join(str(block.text) for block in response.content if getattr(block, "type", None) == "text")
        if response.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": [block.model_dump(exclude_none=True) for block in response.content]}]
    return text


def _parse(text: str) -> dict | None:
    """The last JSON object in the answer; prose or a code fence around it is fine."""

    decoder = json.JSONDecoder()
    found = None
    end = 0
    for start in [index for index, char in enumerate(text) if char == "{"]:
        if start < end:
            continue
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            found = value
    return found


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clean(answer: dict | None, item: dict) -> dict | None:
    """A usable live quote, or None when it should fall back to the catalog."""

    if not answer or answer.get("found") is False:
        return None
    url = str(answer.get("url") or "").strip()
    if not re.match(r"^https?://[^\s/]+\.[^\s/]+", url):
        return None
    currency = str(answer.get("currency") or "").strip().upper()[:3] or "EUR"
    price = _number(answer.get("price"))
    price_eur = _number(answer.get("price_eur"))
    if price_eur is None and currency == "EUR":
        price_eur = price
    if price_eur is None:
        return None
    catalog = float(item["unit_price_eur"])
    if catalog > 0 and not (catalog / _MAX_RATIO <= price_eur <= catalog * _MAX_RATIO):
        return None
    availability = str(answer.get("availability") or "unknown").strip().lower()
    if availability not in {"in_stock", "out_of_stock", "unknown"}:
        availability = "unknown"
    try:
        pack_qty = max(1, int(answer.get("pack_qty") or 1))
    except (TypeError, ValueError):
        pack_qty = 1
    return {
        "unit_price_eur": round(price_eur, 2),
        "price": round(price if price is not None else price_eur, 2),
        "currency": currency,
        "pack_qty": pack_qty,
        "shop": str(answer.get("shop") or "").strip()[:60] or url.split("/")[2],
        "url": url,
        "availability": availability,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


async def find_price(item: dict) -> dict | None:
    """Live quote for one BOM line, from the cache when it is fresh."""

    key = item["name"].strip().lower()
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached is not None:
        stored_at, quote = cached
        if now - stored_at < (_CACHE_TTL_S if quote else _FAILED_TTL_S):
            return quote
    quote = None
    try:
        deadline = time.monotonic() + _TIMEOUT_S
        text = await asyncio.wait_for(asyncio.to_thread(_ask_claude, _request(item, model_name()), deadline), _TIMEOUT_S)
        quote = _clean(_parse(text), item)
        if quote is None:
            log.info("no usable live price for %s", item["name"])
    except Exception as exc:
        log.warning("live price search failed for %s: %s", item["name"], exc)
    _CACHE[key] = (time.monotonic(), quote)
    return quote


def unit_price_eur(part: dict) -> float:
    """The fresh cached live price per piece for this part, else its catalog price."""

    cached = _CACHE.get(part["name"].strip().lower())
    if cached is not None:
        stored_at, quote = cached
        if quote and time.monotonic() - stored_at < _CACHE_TTL_S:
            return float(quote["unit_price_eur"])
    return float(part["unit_price_eur"])


def catalog_line(item: dict) -> dict:
    return {**item, "price_source": "catalog", "currency": "EUR", "availability": "unknown"}


async def live_lines(items: list[dict]) -> list[dict]:
    """Every BOM line with a live quote where one was found, else its catalog price."""

    async def one(item: dict) -> dict:
        # The printed frame has no shop page to search.
        if not item.get("url"):
            return catalog_line(item)
        quote = await find_price(item)
        if quote is None:
            return catalog_line(item)
        return {**item, **quote, "catalog_price_eur": item["unit_price_eur"], "price_source": "live"}

    return list(await asyncio.gather(*(one(item) for item in items)))
