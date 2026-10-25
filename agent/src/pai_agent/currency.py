"""Prices in any currency, converted to euros at the day's ECB reference rate.

The European Central Bank publishes its euro reference rates for about 30 currencies once per
working day (https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml). `rates` fetches that
file at most once per calendar day and keeps it in `agent/runs/cache/ecb_rates.json`. Offline it
uses the last fetched file, else the rates of 2026-10-23 recorded below, and says which in
`source`. A code that is not an ISO 4217 code, or one the ECB publishes no rate for, is refused
with the reason: no rate is guessed.
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import xml.etree.ElementTree as ET
from datetime import date
from urllib.request import Request, urlopen

from pai_agent.paths import RUNS_DIR

log = logging.getLogger(__name__)

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
CACHE_PATH = RUNS_DIR / "cache" / "ecb_rates.json"
TIMEOUT_S = 6.0
# The ECB file of 2026-10-23, used only when the file cannot be fetched and none was fetched before.
FALLBACK_DATE = "2026-10-23"
FALLBACK = {
    "USD": 1.1193, "JPY": 175.51, "CZK": 24.327, "DKK": 7.4748, "GBP": 0.83728, "HUF": 366.73, "PLN": 4.3945, "RON": 5.3492,
    "SEK": 11.1310, "CHF": 0.9227, "ISK": 136.20, "NOK": 10.4665, "TRY": 55.6715, "AUD": 1.5939, "BRL": 5.6485, "CAD": 1.5665,
    "CNY": 7.4660, "HKD": 8.7793, "IDR": 20268.06, "ILS": 3.4939, "INR": 106.2720, "KRW": 1482.46, "MXN": 21.0226, "MYR": 4.5729,
    "NZD": 1.9682, "PHP": 71.235, "SGD": 1.4310, "THB": 37.771, "ZAR": 18.5777,
}
# ISO 4217 codes in circulation that the ECB does not publish (a shop may still quote them); refused with this reason.
UNPUBLISHED = {"RUB", "AED", "SAR", "TWD", "VND", "UAH", "ARS", "CLP", "COP", "PEN", "EGP", "NGN", "KES", "PKR", "BDT", "QAR", "KWD", "BGN", "HRK"}

_MEMO: dict = {}


class CurrencyError(ValueError):
    pass


def ssl_context() -> ssl.SSLContext:
    """The operating system's certificate store (truststore, installed with httpx2), else Python's own.

    A python.org Python on macOS has no CA bundle of its own until its certificate script runs."""

    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # truststore missing or unsupported here
        return ssl.create_default_context()


def _fetch() -> tuple[str, dict[str, float]]:
    """(ECB date, {code: units per euro}) from the ECB's daily file."""

    request = Request(ECB_URL, headers={"User-Agent": "AnyBuild currency"})
    with urlopen(request, timeout=TIMEOUT_S, context=ssl_context()) as response:
        root = ET.fromstring(response.read())
    stamp = ""
    found: dict[str, float] = {}
    for cube in root.iter():
        if cube.get("time"):
            stamp = cube.get("time")
        if cube.get("currency") and cube.get("rate"):
            found[cube.get("currency")] = float(cube.get("rate"))
    if not found:
        raise ValueError("no rates in the ECB file")
    return stamp, found


def rates(today: str | None = None) -> dict:
    """{"date", "rates" (EUR included), "source"}: today's ECB rates, else the last known ones, said so."""

    today = today or date.today().isoformat()
    if _MEMO.get("fetched") == today:
        return _MEMO["value"]
    cached = None
    try:
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = None
    if cached and cached.get("fetched") == today and cached.get("rates"):
        value = {"date": cached["date"], "rates": {"EUR": 1.0, **cached["rates"]}, "source": "ECB reference rates of " + cached["date"]}
    else:
        try:
            stamp, found = _fetch()
            try:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                CACHE_PATH.write_text(json.dumps({"fetched": today, "date": stamp, "rates": found}), encoding="utf-8")
            except OSError as exc:
                log.warning("ECB rates not cached: %s", exc)
            value = {"date": stamp, "rates": {"EUR": 1.0, **found}, "source": "ECB reference rates of " + stamp}
        except Exception as exc:  # offline or the ECB is down: the last known rates, labelled
            log.info("ECB rates not fetched: %s", exc)
            if cached and cached.get("rates"):
                value = {"date": cached["date"], "rates": {"EUR": 1.0, **cached["rates"]}, "source": "ECB reference rates of " + cached["date"] + " (offline, last fetched)"}
            else:
                value = {"date": FALLBACK_DATE, "rates": {"EUR": 1.0, **FALLBACK}, "source": "ECB reference rates of " + FALLBACK_DATE + " (offline, built in)"}
    _MEMO.update({"fetched": today, "value": value})
    return value


def to_eur(amount: float, code: str, today: str | None = None) -> tuple[float, dict]:
    """(amount in EUR, {"currency", "rate", "date", "source"}); CurrencyError says why a code is refused."""

    code = str(code or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise CurrencyError(repr(code) + " is not an ISO 4217 currency code.")
    table = rates(today)
    rate = table["rates"].get(code)
    if rate is None:
        if code in UNPUBLISHED:
            raise CurrencyError("The ECB publishes no reference rate for " + code + ", so the price cannot be converted to EUR.")
        raise CurrencyError("Unknown currency " + code + ": not among the ECB's reference rates.")
    return float(amount) / rate, {"currency": code, "rate": rate, "date": table["date"], "source": table["source"]}


def reset() -> None:
    """Forget today's rates in this process (tests)."""

    _MEMO.clear()
