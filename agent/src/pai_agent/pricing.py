"""Where a bought part's price comes from: a live provider, the catalog sample, or an estimate.

Live shop prices are a separate module (issue #8, agent/tools/parts_search*). It plugs in
here with register_provider(fn): fn(item) gets the picked part (name, category, query)
and returns {"unit_price_eur", "shop", "url"} or None. The first provider that answers
wins and the price is marked live; without one the catalog sample or the estimate stays.
"""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)

Provider = Callable[[dict], dict | None]
_PROVIDERS: list[Provider] = []


def register_provider(provider: Provider) -> None:
    if provider not in _PROVIDERS:
        _PROVIDERS.append(provider)


def price(item: dict) -> dict:
    """The item with price_source set: live when a provider answers, else what it came with."""

    for provider in _PROVIDERS:
        try:
            quote = provider(item)
        except Exception:
            log.exception("price provider failed")
            continue
        if quote and quote.get("unit_price_eur") is not None:
            return {**item, **{k: quote[k] for k in ("unit_price_eur", "shop", "url") if k in quote}, "price_source": "live"}
    return item
