"""Distributor APIs for exact electronics specs: Digi-Key, Nexar (Octopart) and Mouser, each optional.

Each one is searched only when its credentials are set (agent/.env or the shell):

- Digi-Key Product Information API v4: `DIGIKEY_CLIENT_ID`, `DIGIKEY_CLIENT_SECRET` (OAuth2 client
  credentials from https://api.digikey.com/v1/oauth2/token, then the keyword search with the
  `X-DIGIKEY-Client-Id` header; prices in EUR for the German site).
- Nexar Supply (Octopart data): `NEXAR_CLIENT_ID`, `NEXAR_CLIENT_SECRET` (a client-credentials token
  from https://identity.nexar.com/connect/token with scope `supply.domain`, then `supSearch` on
  https://api.nexar.com/graphql).
- Mouser Search API: `MOUSER_API_KEY` (keyword search, at most 30 calls a minute and 1,000 a day).

A keyword search returns candidates in one shape: manufacturer, part number, description, the
distributor's product page, the datasheet URL, price, stock and the parametric data mapped to the
catalog's fields as [value, unit] pairs (dimensions, mass where given, voltage, current, power,
frame rate, field of view, resolution). The same part at several distributors becomes one candidate
with every listing as a source; two distributors that disagree on a number leave that number out.
`web_parts.discover` searches here before the generic web search for electronics.

Tokens live in memory until they expire, results are cached for a day in
`agent/runs/cache/distributors/`, each provider has a per-minute and per-day budget kept across
restarts, and no credential is ever logged, printed or returned: error text is scrubbed of them.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import deque
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pai_agent.currency import ssl_context
from pai_agent.env import load_env
from pai_agent.learned_parts import norm, same_maker
from pai_agent.paths import RUNS_DIR

log = logging.getLogger(__name__)

CACHE_DIR = RUNS_DIR / "cache" / "distributors"
RESULT_TTL_S = 24 * 3600.0
TIMEOUT_S = 15.0
# Distributors stock electronics; FPV hobby parts (props, frames, packs, whoop motors) are not there.
SKIP_CATEGORIES = {"propeller", "frame", "canopy", "battery", "hardware"}

DIGIKEY_TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
DIGIKEY_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"
NEXAR_TOKEN_URL = "https://identity.nexar.com/connect/token"
NEXAR_GRAPHQL_URL = "https://api.nexar.com/graphql"
MOUSER_SEARCH_URL = "https://api.mouser.com/api/v1/search/keyword"

NEXAR_QUERY = """query Search($q: String!, $limit: Int!) {
  supSearch(q: $q, limit: $limit, currency: "EUR", country: "DE") {
    results {
      part {
        mpn
        manufacturer { name }
        shortDescription
        octopartUrl
        bestDatasheet { url }
        totalAvail
        specs { attribute { name shortname } displayValue value units }
        sellers(authorizedOnly: true, limit: 4) {
          company { name }
          offers { clickUrl inventoryLevel moq prices { quantity price currency convertedPrice convertedCurrency } }
        }
      }
    }
  }
}"""


class DistributorError(Exception):
    pass


# --- HTTP, with every credential scrubbed from what can reach a log or a result ---------------


def _secrets() -> list[str]:
    load_env()
    names = ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET", "NEXAR_CLIENT_ID", "NEXAR_CLIENT_SECRET", "MOUSER_API_KEY")
    values = [os.environ.get(n, "").strip() for n in names]
    values += [token for token, _expiry in _TOKENS.values()]
    return [v for v in values if len(v) >= 4]


def scrub(text: str) -> str:
    for secret in _secrets():
        text = text.replace(secret, "***")
    return re.sub(r"(apiKey=)[^&\s]+", r"\1***", text)


def _http(method: str, url: str, headers: dict, body: bytes | None = None, timeout: float = TIMEOUT_S) -> dict:
    """One JSON request through urllib (which logs nothing); errors are DistributorError with scrubbed text."""

    request = Request(url, data=body, method=method, headers={"Accept": "application/json", "User-Agent": "AnyBuild parts", **headers})
    try:
        with urlopen(request, timeout=timeout, context=ssl_context()) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        raise DistributorError(scrub("HTTP " + str(exc.code) + (": " + detail if detail else ""))) from None
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise DistributorError(scrub(type(exc).__name__ + ": " + str(getattr(exc, "reason", exc))[:160])) from None


# --- budgets and caches -----------------------------------------------------------------------


class Budget:
    """At most per_minute calls in any minute and per_day calls per calendar day, the day count kept on disk."""

    def __init__(self, name: str, per_minute: int, per_day: int):
        self.name, self.per_minute, self.per_day = name, per_minute, per_day
        self.recent: deque[float] = deque()

    def _path(self):
        return CACHE_DIR / "usage.json"

    def _day(self) -> dict:
        try:
            return json.loads(self._path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def take(self) -> str | None:
        """None when a call may go now (and counts it), else why not."""

        now = time.monotonic()
        while self.recent and now - self.recent[0] > 60.0:
            self.recent.popleft()
        if len(self.recent) >= self.per_minute:
            return self.name + " allows " + str(self.per_minute) + " calls a minute; try again shortly."
        usage = self._day()
        today = date.today().isoformat()
        entry = usage.get(self.name) if isinstance(usage.get(self.name), dict) else {}
        count = int(entry.get("count", 0)) if entry.get("day") == today else 0
        if count >= self.per_day:
            return self.name + " allows " + str(self.per_day) + " calls a day; today's are used."
        self.recent.append(now)
        usage[self.name] = {"day": today, "count": count + 1}
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._path().write_text(json.dumps(usage), encoding="utf-8")
        except OSError:
            pass
        return None


_TOKENS: dict[str, tuple[str, float]] = {}


def _cached(provider: str, keyword: str) -> list[dict] | None:
    try:
        data = json.loads((CACHE_DIR / "results.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = data.get(provider + "|" + keyword.lower())
    if isinstance(entry, dict) and time.time() - float(entry.get("t", 0)) < RESULT_TTL_S:
        return entry.get("items")
    return None


def _store(provider: str, keyword: str, items: list[dict]) -> None:
    path = CACHE_DIR / "results.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[provider + "|" + keyword.lower()] = {"t": time.time(), "items": items}
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError as exc:
        log.info("distributor results not cached: %s", exc)


# --- parametric data to catalog fields ----------------------------------------------------------

_NUMBER = r"([-+]?\d+(?:[.,]\d+)?)"


def _range(text: str) -> bool:
    return bool(re.search(r"\d\s*(~|to|–|\.\.\.)\s*[-+]?\d", text))


def _value(text: str, units: dict[str, str]) -> list | None:
    """The first number with a unit from units ({page unit: catalog unit}), as [value, unit]; None for a range."""

    text = str(text or "").strip()
    if not text or _range(text):
        return None
    for match in re.finditer(_NUMBER + r"\s*([a-zA-Zµ°\"/]+)?", text):
        unit = (match.group(2) or "").strip()
        mapped = units.get(unit.lower()) if unit else units.get("")
        if mapped is not None:
            return [float(match.group(1).replace(",", ".")), mapped]
    return None


_MASS = {"g": "g", "gr": "g", "grams": "g", "kg": "kg", "mg": "mg", "oz": "oz", "lb": "lb", "lbs": "lb"}
_LEN = {"mm": "mm", "cm": "cm", "m": "m", '"': "in", "in": "in", "inch": "in", "inches": "in"}
_VOLT = {"v": "V", "vdc": "V", "mv": "mV"}
_AMP = {"a": "A", "ma": "mA", "µa": "mA"}
_WATT = {"w": "W", "mw": "mW", "kw": "kW"}

# (pattern on the parameter name, catalog field, units)
_PARAMS = [
    (r"^(unit |net |product )?weight|^mass", "mass_g", _MASS),
    (r"^length|overall length", "length_mm", _LEN),
    (r"^width|overall width", "width_mm", _LEN),
    (r"^height|thickness|height - seated", "height_mm", _LEN),
    (r"^diameter|outside diameter", "diameter_mm", _LEN),
    (r"voltage - supply|supply voltage|operating voltage|^voltage( - rated)?$|input voltage", "voltage_v", _VOLT),
    (r"current - supply|supply current|operating current|^current( - rated)?$|current consumption", "current_a", _AMP),
    (r"^power( - rated| - max| \(watts\))?$|power consumption|power dissipation", "power_w", _WATT),
    (r"frame rate|frames per second|^fps", "fps", {"fps": "fps", "hz": "fps", "": "fps"}),
    (r"field of view|angle of view|^fov|viewing angle", "fov_deg", {"°": "deg", "deg": "deg", "degrees": "deg", "": "deg"}),
    (r"^rpm|speed \(rpm\)|no load speed|^speed$", "rpm", {"rpm": "rpm", "": "rpm"}),
    (r"capacity", "capacity_mah", {"mah": "mAh", "ah": "Ah"}),
]


def _resolution(text: str) -> list | None:
    match = re.search(r"(\d{2,5})\s*(?:h|px|pixels)?\s*[x×*]\s*(\d{2,5})", str(text), re.I)
    return [int(match.group(1)), int(match.group(2))] if match else None


def _dimensions(text: str) -> dict:
    """ "1.38" L x 1.38" W (35.0mm x 35.0mm)" or "35 x 20 x 5 mm": length, width (and height) in mm."""

    text = str(text or "")
    inside = re.search(r"\(([^)]*mm[^)]*)\)", text)
    source = inside.group(1) if inside else text
    if "mm" not in source:
        return {}
    numbers = [float(n.replace(",", ".")) for n in re.findall(r"(\d+(?:[.,]\d+)?)", source)]
    out = {}
    for name, value in zip(("length_mm", "width_mm", "height_mm"), numbers[:3]):
        out[name] = [value, "mm"]
    return out


def map_params(params: dict[str, str], mass_kg: float | None = None) -> dict[str, list]:
    """Distributor parametric data ({name: text}) as catalog specs ({field: [value, unit]})."""

    specs: dict[str, list] = {}
    for name, text in params.items():
        label = str(name).strip().lower()
        if re.search(r"size\s*/\s*dimension|^dimensions?$|^size$", label):
            for field, value in _dimensions(text).items():
                specs.setdefault(field, value)
            continue
        if re.search(r"resolution|pixel array|active pixel|pixel count", label):
            pair = _resolution(text)
            if pair:
                specs.setdefault("resolution_px", [pair, "px"])
            continue
        for pattern, field, units in _PARAMS:
            if re.search(pattern, label):
                value = _value(text, units)
                if value is not None:
                    specs.setdefault(field, value)
                break
    if mass_kg and mass_kg > 0 and "mass_g" not in specs:
        specs["mass_g"] = [round(mass_kg * 1000.0, 4), "g"]
    return specs


def _price_number(text) -> float | None:
    """ "€1,23", "1.234,56 €", "$1,234.56", "€0,123" or 1.23 as a number."""

    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    raw = re.sub(r"[^\d.,]", "", str(text or ""))
    if not raw:
        return None
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
    elif raw.count(",") > 1:
        raw = raw.replace(",", "")
    elif "," in raw:
        # One comma is a decimal comma: Mouser's euro prices read "€0,123".
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _candidate(distributor: str, manufacturer, mpn, description, url, datasheet, price, currency, stock, params: dict, mass_kg=None) -> dict | None:
    if not (manufacturer and mpn and str(url or "").startswith(("http://", "https://"))):
        return None
    trimmed = {str(k)[:60]: str(v)[:120] for k, v in list(params.items())[:60] if v not in (None, "", "-")}
    return {
        "distributor": distributor,
        "manufacturer": str(manufacturer).strip(),
        "mpn": str(mpn).strip(),
        "description": str(description or "").strip()[:200],
        "url": str(url),
        "datasheet_url": str(datasheet) if str(datasheet or "").startswith(("http://", "https://")) else None,
        "price": price,
        "currency": currency,
        "stock": stock,
        "params": trimmed,
        "specs": map_params(trimmed, mass_kg),
    }


# --- the three providers ------------------------------------------------------------------------


class Provider:
    name = ""
    env: tuple[str, ...] = ()
    budget: Budget

    def configured(self) -> bool:
        load_env()
        return all(os.environ.get(name, "").strip() for name in self.env)

    def _env(self, name: str) -> str:
        return os.environ.get(name, "").strip()

    def search(self, keyword: str, limit: int) -> list[dict]:
        raise NotImplementedError


class DigiKey(Provider):
    name = "Digi-Key"
    env = ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET")
    budget = Budget("Digi-Key", 120, 1000)

    def _token(self) -> str:
        token = _TOKENS.get(self.name)
        if token and token[1] > time.time() + 30:
            return token[0]
        body = urlencode({"client_id": self._env("DIGIKEY_CLIENT_ID"), "client_secret": self._env("DIGIKEY_CLIENT_SECRET"), "grant_type": "client_credentials"}).encode()
        answer = _http("POST", DIGIKEY_TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, body)
        if not answer.get("access_token"):
            raise DistributorError("Digi-Key gave no access token.")
        _TOKENS[self.name] = (answer["access_token"], time.time() + float(answer.get("expires_in") or 600))
        return answer["access_token"]

    def search(self, keyword: str, limit: int) -> list[dict]:
        headers = {
            "Authorization": "Bearer " + self._token(),
            "X-DIGIKEY-Client-Id": self._env("DIGIKEY_CLIENT_ID"),
            "X-DIGIKEY-Locale-Site": "DE",
            "X-DIGIKEY-Locale-Language": "en",
            "X-DIGIKEY-Locale-Currency": "EUR",
            "Content-Type": "application/json",
        }
        answer = _http("POST", DIGIKEY_SEARCH_URL, headers, json.dumps({"Keywords": keyword, "Limit": limit, "Offset": 0}).encode())
        return parse_digikey(answer)


def parse_digikey(answer: dict) -> list[dict]:
    out = []
    seen = set()
    for product in list(answer.get("ExactMatches") or []) + list(answer.get("Products") or []):
        mpn = product.get("ManufacturerProductNumber")
        if not mpn or mpn in seen:
            continue
        seen.add(mpn)
        price = product.get("UnitPrice") or None
        for variation in product.get("ProductVariations") or []:
            breaks = [b for b in variation.get("StandardPricing") or [] if b.get("BreakQuantity") == 1]
            if breaks and not price:
                price = breaks[0].get("UnitPrice")
        params = {p.get("ParameterText"): p.get("ValueText") for p in product.get("Parameters") or [] if p.get("ParameterText")}
        texts = product.get("Description") or {}
        description = ", ".join(t for t in (texts.get("DetailedDescription"), texts.get("ProductDescription")) if t)
        item = _candidate(
            "Digi-Key", (product.get("Manufacturer") or {}).get("Name"), mpn, description, product.get("ProductUrl"), product.get("DatasheetUrl"),
            float(price) if price else None, "EUR", product.get("QuantityAvailable"), params,
        )
        if item:
            out.append(item)
    return out


class Nexar(Provider):
    name = "Nexar"
    env = ("NEXAR_CLIENT_ID", "NEXAR_CLIENT_SECRET")
    budget = Budget("Nexar", 60, 1000)

    def _token(self) -> str:
        token = _TOKENS.get(self.name)
        if token and token[1] > time.time() + 60:
            return token[0]
        body = urlencode({"grant_type": "client_credentials", "client_id": self._env("NEXAR_CLIENT_ID"), "client_secret": self._env("NEXAR_CLIENT_SECRET"), "scope": "supply.domain"}).encode()
        answer = _http("POST", NEXAR_TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, body)
        if not answer.get("access_token"):
            raise DistributorError("Nexar gave no access token.")
        _TOKENS[self.name] = (answer["access_token"], time.time() + float(answer.get("expires_in") or 3600))
        return answer["access_token"]

    def search(self, keyword: str, limit: int) -> list[dict]:
        body = json.dumps({"query": NEXAR_QUERY, "variables": {"q": keyword, "limit": limit}}).encode()
        answer = _http("POST", NEXAR_GRAPHQL_URL, {"Authorization": "Bearer " + self._token(), "Content-Type": "application/json"}, body)
        if answer.get("errors"):
            raise DistributorError("Nexar: " + scrub(str(answer["errors"][0].get("message", "error"))[:160]))
        return parse_nexar(answer)


def parse_nexar(answer: dict) -> list[dict]:
    out = []
    results = (((answer.get("data") or {}).get("supSearch") or {}).get("results")) or []
    for result in results:
        part = (result or {}).get("part") or {}
        params = {}
        for spec in part.get("specs") or []:
            name = (spec.get("attribute") or {}).get("name")
            text = spec.get("displayValue") or " ".join(str(v) for v in (spec.get("value"), spec.get("units")) if v)
            if name and text:
                params[name] = text
        price = currency = None
        stock = part.get("totalAvail")
        for seller in part.get("sellers") or []:
            for offer in seller.get("offers") or []:
                points = sorted(offer.get("prices") or [], key=lambda p: p.get("quantity") or 0)
                if points and price is None:
                    point = points[0]
                    if point.get("convertedCurrency") == "EUR" and point.get("convertedPrice"):
                        price, currency = float(point["convertedPrice"]), "EUR"
                    elif point.get("price"):
                        price, currency = float(point["price"]), point.get("currency")
        item = _candidate(
            "Nexar", (part.get("manufacturer") or {}).get("name"), part.get("mpn"), part.get("shortDescription"), part.get("octopartUrl"),
            (part.get("bestDatasheet") or {}).get("url"), price, currency, stock, params,
        )
        if item:
            out.append(item)
    return out


class Mouser(Provider):
    name = "Mouser"
    env = ("MOUSER_API_KEY",)
    budget = Budget("Mouser", 30, 1000)

    def search(self, keyword: str, limit: int) -> list[dict]:
        body = {"SearchByKeywordRequest": {"keyword": keyword, "records": limit, "startingRecord": 0, "searchOptions": "", "searchWithYourSignUpLanguage": "false"}}
        url = MOUSER_SEARCH_URL + "?" + urlencode({"apiKey": self._env("MOUSER_API_KEY")})
        answer = _http("POST", url, {"Content-Type": "application/json"}, json.dumps(body).encode())
        errors = answer.get("Errors") or []
        if errors:
            raise DistributorError("Mouser: " + scrub(str(errors[0].get("Message") or errors[0].get("Code") or "error")[:160]))
        return parse_mouser(answer)


def parse_mouser(answer: dict) -> list[dict]:
    out = []
    for part in ((answer.get("SearchResults") or {}).get("Parts")) or []:
        breaks = sorted(part.get("PriceBreaks") or [], key=lambda b: b.get("Quantity") or 0)
        price = _price_number(breaks[0].get("Price")) if breaks else None
        currency = breaks[0].get("Currency") if breaks else None
        stock = part.get("AvailabilityInStock")
        try:
            stock = int(str(stock).replace(",", "").replace(".", "")) if stock not in (None, "") else None
        except ValueError:
            stock = None
        params = {a.get("AttributeName"): a.get("AttributeValue") for a in part.get("ProductAttributes") or [] if a.get("AttributeName")}
        weight = (part.get("UnitWeightKg") or {}).get("UnitWeight")
        item = _candidate(
            "Mouser", part.get("Manufacturer"), part.get("ManufacturerPartNumber"), part.get("Description"), part.get("ProductDetailUrl"),
            part.get("DataSheetUrl"), price, currency, stock, params, float(weight) if weight else None,
        )
        if item:
            out.append(item)
    return out


PROVIDERS: list[Provider] = [DigiKey(), Nexar(), Mouser()]


def configured() -> list[str]:
    """The providers whose credentials are set."""

    return [p.name for p in PROVIDERS if p.configured()]


def applies(category: str) -> bool:
    return category not in SKIP_CATEGORIES


def _close(a: list, b: list) -> bool:
    if a[1] != b[1]:
        return True  # different units: the validator converts; not compared here
    x, y = a[0], b[0]
    if isinstance(x, list) or isinstance(y, list):
        return x == y
    return abs(float(x) - float(y)) <= 0.1 * max(abs(float(x)), abs(float(y)), 1e-9)


def combine(items: list[dict]) -> list[dict]:
    """One candidate per manufacturer and part number, with every distributor's listing as a source."""

    groups: list[dict] = []
    for item in items:
        group = next((g for g in groups if norm(g["mpn"]) == norm(item["mpn"]) and same_maker(g["manufacturer"], item["manufacturer"])), None)
        listing = {"url": item["url"], "kind": "distributor", "distributor": item["distributor"], "manufacturer": item["manufacturer"], "mpn": item["mpn"]}
        if group is None:
            groups.append({**item, "listings": [listing], "spec_sources": {k: item["url"] for k in item["specs"]}, "conflicts": [], "text": item["description"]})
            continue
        group["listings"].append(listing)
        group["text"] += " " + item["description"]
        group["datasheet_url"] = group.get("datasheet_url") or item.get("datasheet_url")
        if group.get("price") is None and item.get("price") is not None:
            group.update({"price": item["price"], "currency": item["currency"], "url": item["url"], "distributor": item["distributor"]})
        for field, value in item["specs"].items():
            if field not in group["specs"]:
                group["specs"][field] = value
                group["spec_sources"][field] = item["url"]
            elif field != "mass_g" and not _close(group["specs"][field], value):
                # Two distributors disagree: the number is unknown, not averaged.
                group["conflicts"].append(field + ": " + group["distributor"] + " " + str(group["specs"][field]) + ", " + item["distributor"] + " " + str(value))
                group["specs"].pop(field)
                group["spec_sources"].pop(field, None)
    return groups


def search(category: str, keyword: str, limit: int = 4) -> dict:
    """{"candidates", "used", "notes"}: every configured distributor's matches for the keyword, combined."""

    keyword = " ".join(str(keyword or "").split())[:120]
    notes: list[str] = []
    used: list[str] = []
    items: list[dict] = []
    if not keyword or not applies(category):
        return {"candidates": [], "used": used, "notes": notes}
    for provider in PROVIDERS:
        if not provider.configured():
            continue
        found = _cached(provider.name, keyword)
        if found is None:
            refused = provider.budget.take()
            if refused:
                notes.append(refused)
                continue
            try:
                found = provider.search(keyword, limit)
            except DistributorError as exc:
                notes.append(provider.name + ": " + str(exc))
                log.info("distributor %s failed: %s", provider.name, exc)
                continue
            _store(provider.name, keyword, found)
        used.append(provider.name)
        items += found[:limit]
    return {"candidates": combine(items), "used": used, "notes": notes}


def reset() -> None:
    """Forget tokens and budgets in this process (tests)."""

    _TOKENS.clear()
    for provider in PROVIDERS:
        provider.budget.recent.clear()
