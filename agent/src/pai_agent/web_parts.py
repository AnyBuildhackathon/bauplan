"""Live part discovery: a real product, its numbers from its own pages, when the curated library has nothing that fits.

`discover` looks in this order and stops at the first part that passes `validate`:

1. the learned library (`learned_parts`): the part an earlier build found for the same need, or a
   learned part that matches the query and has every field this build needs;
2. the distributor APIs (`distributors`, Digi-Key, Nexar/Octopart and Mouser, each only with its
   credentials) for electronics: exact manufacturer, part number, datasheet and parametric data;
3. Claude with web search and web fetch (or Claude Code's WebSearch and WebFetch on the local
   subscription), which may combine several pages of the same exact product: the shop listing, the
   maker's product page and its datasheet PDF, each number with the page it came from. Distributor
   candidates are handed to it so it completes the one that fits from the maker's datasheet.

`validate` turns an answer into a catalog part or refuses it:

- identity: every source must name the same part number (and, where it names one, the same
  manufacturer); a page of another model or variant refuses the part;
- required fields: the category's critical fields (`FIELDS`, what physics needs) plus the fields
  the calling tool asks for (`require`, a chase camera's fov_deg, resolution_px and fps) must each
  be stated on a source page or read off its drawing; the rest may be missing, and their consumers
  (the 3D model, the drag model) use their labelled fallbacks;
- units are converted to the catalog's, an unknown unit is a problem, not a guess; every number
  must sit in a plausible range for its category, and the cross-field checks catch mistyped tables;
- the price converts from any currency at the day's ECB reference rate (`currency`); an unknown
  code refuses the part.

Every field of a part carries its source URL, how it was read and a confidence: `sourced` (stated
on a page), `derived` (read off a drawing, or computed from sourced numbers) or `estimated`. An
estimate is allowed only in exploration mode (`settings.allow_estimated`, `PAI_ALLOW_ESTIMATED`)
and never for a critical field; it is labelled wherever the part shows. Nothing here invents a
number. A part that passes joins the learned library, so the next build finds it at once.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date
from pathlib import Path

from pai_agent import currency, distributors, learned_parts, provider
from pai_agent.env import model_name
from pai_agent.tools.parts_search import _parse, _version, _web_search_tool, live_prices_enabled

log = logging.getLogger(__name__)

TIMEOUT_S = 180.0
# Per part: web searches and page or PDF reads, and how much of one page the model may read.
SEARCH_USES = 10
FETCH_USES = 8
FETCH_TOKENS = 40000
SUBSCRIPTION_TURNS = 30
# USD per web search (Anthropic's server-side search); fetches cost only their tokens.
SEARCH_USD = 0.01
CONFIDENCE = ("sourced", "derived", "estimated")

# Unit conversions to the catalog unit of each kind.
_UNITS = {
    "g": {"g": 1.0, "gram": 1.0, "grams": 1.0, "kg": 1000.0, "oz": 28.3495, "lb": 453.592, "mg": 0.001},
    "mm": {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4},
    "in": {"in": 1.0, "inch": 1.0, "inches": 1.0, '"': 1.0, "mm": 1 / 25.4, "cm": 1 / 2.54},
    "V": {"v": 1.0, "volt": 1.0, "volts": 1.0, "mv": 0.001},
    "mAh": {"mah": 1.0, "ah": 1000.0},
    "A": {"a": 1.0, "amp": 1.0, "amps": 1.0, "ma": 0.001},
    "W": {"w": 1.0, "watt": 1.0, "watts": 1.0, "kw": 1000.0, "mw": 0.001},
    "kgcm": {"kgcm": 1.0, "kg cm": 1.0, "kg.cm": 1.0, "kg·cm": 1.0, "kgf cm": 1.0, "nm": 10.197, "n·m": 10.197, "ncm": 0.10197, "n cm": 0.10197, "oz in": 0.0720078, "oz·in": 0.0720078, "ozin": 0.0720078},
    "KV": {"kv": 1.0, "rpm/v": 1.0},
    "rpm": {"rpm": 1.0},
    "C": {"c": 1.0},
    "count": {"": 1.0, "s": 1.0, "pcs": 1.0, "blades": 1.0, "cells": 1.0},
    "cm": {"cm": 1.0, "mm": 0.1, "m": 100.0},
    "deg": {"deg": 1.0, "°": 1.0, "degree": 1.0, "degrees": 1.0},
    "fps": {"fps": 1.0, "hz": 1.0, "frames/s": 1.0, "f/s": 1.0},
    "ms": {"ms": 1.0, "s": 1000.0, "us": 0.001, "µs": 0.001},
    "mW": {"mw": 1.0, "w": 1000.0},
}

# The sensing numbers a camera or vision sensor may carry; the chase mission reads them (plant.camera_spec).
_SENSING: dict[str, tuple[str, float, float, bool]] = {
    "fov_deg": ("deg", 5, 360, False),
    "fov_h_deg": ("deg", 5, 300, False),
    "resolution_px": ("px2", 16, 20000, False),
    "fps": ("fps", 1, 2000, False),
    "latency_ms": ("ms", 0.1, 1000, False),
}

# Per category: field -> (kind of unit, low, high, critical). Critical fields are what physics needs
# and are always required; the rest may be missing and fall back to labelled defaults where they are used.
FIELDS: dict[str, dict[str, tuple[str, float, float, bool]]] = {
    "motor": {
        "mass_g": ("g", 0.3, 2000, True),
        "thrust_g": ("g", 3, 20000, True),
        "bench_voltage_v": ("V", 1, 60, True),
        "bench_current_a": ("A", 0.1, 200, False),
        "bench_power_w": ("W", 0.3, 5000, True),
        "kv": ("KV", 50, 80000, False),
        "diameter_mm": ("mm", 5, 120, False),
        "height_mm": ("mm", 4, 120, False),
        "shaft_mm": ("mm", 0.5, 12, False),
        "mount_diameter_mm": ("mm", 3, 60, False),
        "cells_max": ("count", 1, 14, True),
        "cells_min": ("count", 1, 14, False),
    },
    "propeller": {
        "diameter_mm": ("mm", 15, 800, True),
        "pitch_in": ("in", 0.3, 15, False),
        "blades": ("count", 2, 8, False),
        "mass_g": ("g", 0.03, 300, True),
        "shaft_mm": ("mm", 0.5, 12, False),
    },
    "battery": {
        "cells": ("count", 1, 14, True),
        "voltage_v": ("V", 2.4, 60, True),
        "capacity_mah": ("mAh", 40, 50000, True),
        "c_rating": ("C", 1, 250, False),
        "mass_g": ("g", 1, 10000, True),
        "length_mm": ("mm", 5, 400, False),
        "width_mm": ("mm", 3, 300, False),
        "height_mm": ("mm", 2, 200, False),
    },
    "flight_controller": {
        "mass_g": ("g", 0.5, 200, True),
        "mount_mm": ("mm", 10, 45, False),
        "cells_min": ("count", 1, 14, False),
        "cells_max": ("count", 1, 14, False),
        "esc_continuous_a": ("A", 1, 200, False),
        "esc_peak_a": ("A", 1, 250, False),
        "board_mm": ("mm", 12, 60, False),
    },
    "frame": {
        "mass_g": ("g", 1, 3000, True),
        "wheelbase_mm": ("mm", 40, 1500, True),
        "mount_mm": ("mm", 10, 45, False),
        "mount_diameter_mm": ("mm", 3, 60, False),
        "prop_max_mm": ("mm", 20, 800, False),
        "arm_thickness_mm": ("mm", 0.5, 15, False),
    },
    "camera": {"mass_g": ("g", 0.2, 500, True), "length_mm": ("mm", 3, 150, False), "width_mm": ("mm", 3, 150, False), "height_mm": ("mm", 3, 150, False), **_SENSING},
    "vtx": {"mass_g": ("g", 0.2, 200, True), "length_mm": ("mm", 3, 100, False), "width_mm": ("mm", 3, 100, False), "height_mm": ("mm", 1, 60, False), "power_mw": ("mW", 1, 5000, False)},
    "canopy": {"mass_g": ("g", 0.2, 200, True)},
    "hardware": {"mass_g": ("g", 0.001, 500, True)},
}
# Any other product's bought part (servo, sensor, wheel, pump): mass, plus size and what the checks read.
GENERIC: dict[str, tuple[str, float, float, bool]] = {
    "mass_g": ("g", 0.01, 50000, True),
    "length_mm": ("mm", 0.5, 3000, False),
    "width_mm": ("mm", 0.5, 3000, False),
    "height_mm": ("mm", 0.2, 3000, False),
    "voltage_v": ("V", 0.5, 400, False),
    "power_w": ("W", 0.001, 20000, False),
    "current_a": ("A", 0.001, 500, False),
    "capacity_mah": ("mAh", 10, 200000, False),
    "stall_torque_kgcm": ("kgcm", 0.01, 5000, False),
    "rpm": ("rpm", 1, 100000, False),
    "thrust_g": ("g", 1, 50000, False),
    **_SENSING,
}
DRONE_CATEGORIES = tuple(FIELDS)


def fields_for(category: str) -> dict[str, tuple[str, float, float, bool]]:
    return FIELDS.get(category, GENERIC)


def critical(category: str) -> list[str]:
    return [key for key, spec in fields_for(category).items() if spec[3]]


def unknown_fields(category: str, require) -> list[str]:
    return [name for name in require if name not in fields_for(category)]


_SYSTEM = (
    "You find real, orderable parts for physical products and copy their specifications from the product's own pages. "
    "Use web search, and web fetch to read the maker's product page and its datasheet (PDF datasheets too). "
    "Prefer the maker's own pages and datasheets; use a shop that ships to the EU for the price. Pick one exact product, in stock if possible. "
    "You may combine several pages of the same exact product, but only pages that name the same part number. "
    "Copy numbers exactly as a page states them with their unit; never compute, round up or fill in a number no page gives. "
    "Answer with one JSON object and nothing else."
)


def _shape(category: str) -> str:
    fields = fields_for(category)
    specs = ", ".join('"' + key + '": {"value": [value, "' + ("px" if kind == "px2" else kind) + '"], "source": "<url of the page>", "read": "stated"}' for key, (kind, *_rest) in list(fields.items())[:3])
    return (
        '{"found": true, "name": "...", "manufacturer": "...", "mpn": "<the part or model number>", '
        '"url": "https://<page where it is bought>", "shop": "...", "price": 0.0, "currency": "<ISO code>", "pack_qty": 1, "in_stock": true, '
        '"sources": [{"url": "https://...", "kind": "shop|maker|datasheet|distributor", "manufacturer": "<as this page names it>", "mpn": "<as this page names it>"}], '
        '"specs": {' + specs + ', ...}, "note": "one sentence: what the pages say"}'
    )


def request_for(category: str, need: str, model: str, require=(), allow_estimated: bool = False, candidates: list[dict] | None = None) -> dict:
    fields = fields_for(category)
    required = list(dict.fromkeys(critical(category) + [name for name in require if name in fields]))
    optional = [key for key in fields if key not in required]
    extra = ""
    if category == "motor":
        extra = (
            "thrust_g, bench_voltage_v, bench_current_a and bench_power_w are the 100 % throttle row of the maker's thrust/load test table "
            "(say which propeller in note). "
        )
    if "fov_deg" in fields:
        extra += (
            "fov_deg is the diagonal field of view of the lens it ships with; when the pages state only the horizontal one, give fov_h_deg instead. "
            "resolution_px is [width, height] in pixels; latency_ms the camera's own latency. "
        )
    estimates = (
        'For an optional field no page states you may give an estimate as {"value": [...], "read": "estimated", "basis": "why this number"}; '
        "it will be labelled estimated. Never estimate a required field. "
        if allow_estimated
        else "Never estimate: leave out what no page states. "
    )
    found = ""
    if candidates:
        rows = []
        for c in candidates[:4]:
            known = ", ".join(sorted(c.get("specs") or {})) or "no parametric numbers"
            rows.append("- " + c["manufacturer"] + " " + c["mpn"] + " (" + c["description"][:80] + "), datasheet " + str(c.get("datasheet_url") or "unknown") + ", " + c["distributor"] + " " + c["url"] + "; distributor gives: " + known)
        found = (
            "Distributor catalogs list these exact parts for the need:\n" + "\n".join(rows) + "\n"
            + "If one fits, complete it from its maker's datasheet and product page (keep its mpn); otherwise find another. "
        )
    prompt = (
        "Category: " + category.replace("_", " ") + "\n"
        + "Need: " + need.strip() + "\n\n"
        + found
        + "Find one real product that fits and copy its specs from its pages: the shop listing, the maker's product page, its datasheet. " + extra
        + "Required specs: " + ", ".join(required) + ". If no page of the product states a required spec, pick another product. "
        + ("Optional specs, include what the pages state: " + ", ".join(optional) + ". " if optional else "")
        + 'Each spec says its source (one of the sources) and read: "stated" (the page states it) or "drawing" (read off the dimensioned drawing). '
        + estimates
        + "List every page you used in sources with the manufacturer and part number as that page names them. "
        + "price is per pack in the shop's currency (ISO code), pack_qty how many pieces the pack holds. "
        + 'If nothing fits, return {"found": false, "why": "..."}.\nShape: ' + _shape(category)
    )
    tools = [{**_web_search_tool(model), "max_uses": SEARCH_USES}, _web_fetch_tool(model)]
    request = {
        "model": model,
        "max_tokens": 8000,
        "system": _SYSTEM,
        "tools": tools,
        "messages": [{"role": "user", "content": prompt}],
    }
    if _version(model)[1] >= 4.6:
        request["output_config"] = {"effort": "low"}
    return request


def _web_fetch_tool(model: str) -> dict:
    family, version = _version(model)
    modern = family in {"fable", "mythos"} or (family in {"opus", "sonnet"} and version >= 4.6)
    return {"type": "web_fetch_20260209" if modern else "web_fetch_20250910", "name": "web_fetch", "max_uses": FETCH_USES, "max_content_tokens": FETCH_TOKENS}


def _pair(raw) -> list[float] | None:
    """[width, height] from [[w, h], "px"], [w, h] or "1280 x 800"."""

    if isinstance(raw, (list, tuple)) and len(raw) == 2 and isinstance(raw[0], (list, tuple)):
        raw = raw[0]
    if isinstance(raw, str):
        match = re.search(r"(\d{2,5})\s*[x×*]\s*(\d{2,5})", raw)
        return [float(match.group(1)), float(match.group(2))] if match else None
    if isinstance(raw, (list, tuple)) and len(raw) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in raw):
        return [float(raw[0]), float(raw[1])]
    return None


def _convert(raw, kind: str):
    """A [value, unit] pair (or a bare number in the catalog unit) in the catalog unit, else None."""

    if kind == "px2":
        return _pair(raw)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, str):
        match = re.match(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*(.*)$", raw)
        if not match:
            return None
        raw = [match.group(1).replace(",", "."), match.group(2)]
    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    try:
        value = float(str(raw[0]).replace(",", "."))
    except ValueError:
        return None
    unit = str(raw[1] if len(raw) > 1 else "").strip().lower().replace("·", " ").replace("⋅", " ")
    table = _UNITS[kind]
    lookup = {k.replace("·", " "): v for k, v in table.items()}
    if unit in lookup:
        return value * lookup[unit]
    if unit.replace(" ", "") in {k.replace(" ", "") for k in lookup}:
        return value * next(v for k, v in lookup.items() if k.replace(" ", "") == unit.replace(" ", ""))
    if unit in {kind.lower(), ""} or (kind in {"count", "C"} and unit in {"c", "s", "x", "count", "pieces", "piece"}):
        # The model named the field's own unit kind ("count", "KV", "rpm") or gave none.
        return value
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "part"


def _is_url(text) -> bool:
    return bool(re.match(r"^https?://[^\s/]+\.[a-z]{2,}(/\S*)?$", str(text or ""), re.I))


def _spec_entry(raw, url: str, estimated: list[str], key: str) -> dict:
    """{"value", "source", "read"} from a spec given either as an object or as a bare [value, unit]."""

    if isinstance(raw, dict) and "value" in raw:
        read = str(raw.get("read") or "stated").strip().lower()
        return {"value": raw["value"], "source": str(raw.get("source") or url).strip(), "read": read, "basis": str(raw.get("basis") or "").strip()[:200]}
    return {"value": raw, "source": url, "read": "estimated" if key in estimated else "stated", "basis": ""}


def _identity(answer: dict, url: str) -> tuple[list[dict], list[str]]:
    """The answer's sources and every reason they are not all the same product.

    A page may name a co-brand (RunCam makes HDZero's cameras): with the same part number, a maker
    that the product's own name also carries is the same product."""

    manufacturer = str(answer.get("manufacturer") or "").strip()
    product_name = learned_parts.norm(answer.get("name"))
    mpn = str(answer.get("mpn") or "").strip()
    listed = answer.get("sources")
    if not isinstance(listed, list) or not listed:
        # One page only (the older answer shape): nothing to match it against.
        return [{"url": url, "kind": "shop", "manufacturer": manufacturer, "mpn": mpn}], []
    problems = []
    sources = []
    for raw in listed:
        if not isinstance(raw, dict) or not _is_url(raw.get("url")):
            continue
        source = {"url": str(raw["url"]).strip(), "kind": str(raw.get("kind") or "page")[:20], "manufacturer": str(raw.get("manufacturer") or "").strip()[:80], "mpn": str(raw.get("mpn") or "").strip()[:80]}
        if raw.get("distributor"):
            source["distributor"] = str(raw["distributor"])[:30]
        sources.append(source)
    if url not in {s["url"] for s in sources}:
        sources.insert(0, {"url": url, "kind": "shop", "manufacturer": manufacturer, "mpn": mpn})
    if len(sources) > 1 and not mpn:
        problems.append("Several pages but no part number to check they are the same product.")
        return sources, problems
    for source in sources:
        if source["url"] == url and not source["mpn"] and source["kind"] == "shop" and len(sources) == 1:
            continue
        if mpn and not learned_parts.names_mpn(source["mpn"], mpn):
            named = source["mpn"] or "no part number"
            problems.append("Source " + source["url"] + " names " + named + ", not " + mpn + ": every source must be the same product.")
        elif (
            manufacturer
            and source["manufacturer"]
            and not learned_parts.same_maker(source["manufacturer"], manufacturer)
            and learned_parts.maker_token(source["manufacturer"]) not in product_name
        ):
            problems.append("Source " + source["url"] + " names the maker " + source["manufacturer"] + ", not " + manufacturer + ".")
    return sources, problems


def validate(category: str, answer: dict | None, today: str | None = None, require=(), allow_estimated: bool = False) -> tuple[dict | None, list[str]]:
    """A catalog part from the answer, or None and every reason it was refused."""

    problems: list[str] = []
    if not isinstance(answer, dict) or answer.get("found") is False:
        why = (answer or {}).get("why") if isinstance(answer, dict) else None
        return None, ["Nothing found" + (": " + str(why) if why else ".")]
    name = str(answer.get("name") or "").strip()
    url = str(answer.get("url") or "").strip()
    if not name:
        problems.append("No product name.")
    if not _is_url(url):
        problems.append("No product page URL.")
    sources, identity = _identity(answer, url)
    problems += identity
    known_urls = {s["url"] for s in sources}
    legacy = not isinstance(answer.get("sources"), list)
    price = answer.get("price")
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = None
    code = str(answer.get("currency") or "EUR").strip().upper()
    if price is None or price <= 0:
        problems.append("No price.")
    try:
        pack_qty = max(1, int(answer.get("pack_qty") or 1))
    except (TypeError, ValueError):
        pack_qty = 1
    fields = fields_for(category)
    required = set(critical(category)) | {name_ for name_ in require if name_ in fields}
    specs = answer.get("specs") if isinstance(answer.get("specs"), dict) else {}
    if "fov_deg" in required and specs.get("fov_deg") in (None, "", []) and specs.get("fov_h_deg") not in (None, "", []):
        # The diagonal follows from a stated horizontal field of view (see _catalog_fields).
        required = (required - {"fov_deg"}) | {"fov_h_deg"}
    estimated_list = [str(item) for item in answer.get("estimated") or [] if isinstance(item, str)]
    legacy_urls = answer.get("spec_urls") if isinstance(answer.get("spec_urls"), dict) else {}
    part: dict = {}
    meta: dict = {}
    dropped: list[str] = []
    for key, (kind, low, high, is_critical) in fields.items():
        raw = specs.get(key)
        if raw in (None, "", []) or (isinstance(raw, dict) and raw.get("value") in (None, "", [])):
            if key in required:
                problems.append(key + " is not on any of its pages.")
            continue
        entry = _spec_entry(raw, url, estimated_list, key)
        if legacy and key in legacy_urls and _is_url(legacy_urls[key]):
            entry["source"] = str(legacy_urls[key])
        value = _convert(entry["value"], kind)
        if value is None:
            problems.append(key + ": unit " + repr(entry["value"]) + " is not a " + ("pixel pair" if kind == "px2" else kind + " unit") + ".")
            continue
        values = value if isinstance(value, list) else [value]
        if not all(low <= v <= high for v in values):
            shown = " x ".join(f"{v:g}" for v in values)
            problems.append(key + " = " + shown + " " + kind + " is outside " + f"{low:g}" + " to " + f"{high:g}" + ".")
            continue
        read = entry["read"] if entry["read"] in {"stated", "drawing", "estimated"} else "stated"
        if read == "estimated":
            if is_critical or (key in required and not allow_estimated):
                problems.append(key + " is required and may not be an estimate.")
                continue
            if not allow_estimated:
                dropped.append(key)
                continue
        elif not legacy and entry["source"] not in known_urls:
            problems.append(key + " cites " + entry["source"] + ", which is not among the sources.")
            continue
        part[key] = [int(v) for v in values] if kind == "px2" else round(value, 4)
        confidence = {"stated": "sourced", "drawing": "derived", "estimated": "estimated"}[read]
        meta[key] = {"source": entry["source"] if read != "estimated" else None, "read": read, "confidence": confidence}
        if read == "estimated":
            meta[key]["basis"] = entry["basis"] or "estimated by Claude; no page states it"
    for conflict in answer.get("conflicts") or []:
        problems.append("Sources disagree: " + str(conflict))
    problems += _physics_checks(category, part)
    unit_eur = None
    rate = None
    if price is not None and price > 0:
        try:
            converted, rate = currency.to_eur(price, code, today)
            unit_eur = converted / pack_qty
        except currency.CurrencyError as exc:
            problems.append(str(exc))
    if problems:
        return None, problems
    if not 0.005 <= unit_eur <= 20000:
        return None, ["Price per piece " + f"{unit_eur:.2f}" + " EUR is implausible."]
    stamp = today or date.today().isoformat()
    host = url.split("/")[2]
    manufacturer = str(answer.get("manufacturer") or "").strip()[:80]
    mpn = str(answer.get("mpn") or "").strip()[:80]
    ident = (manufacturer + " " + mpn).strip() if mpn else name
    catalog, derived = _catalog_fields(category, part)
    for key, origin in derived.items():
        inputs = [meta[k]["confidence"] for k in origin if k in meta]
        meta[key] = {"read": "computed", "from": origin, "confidence": "estimated" if "estimated" in inputs else "derived"}
    estimated = sorted(key for key, m in meta.items() if m["confidence"] == "estimated")
    # Exact arithmetic on stated numbers (g/W, half the wheelbase, the larger side) keeps a part sourced;
    # a drawing reading or a conversion that rests on a model (diagonal from horizontal view) makes it derived.
    exact = {"efficiency_g_per_w", "arm_length_mm", "size_mm"}
    confidence = "estimated" if estimated else ("derived" if any(m["confidence"] == "derived" and k not in exact for k, m in meta.items()) else "sourced")
    item = {
        "id": "web-" + _slug(ident),
        "name": name[:90],
        "category": category,
        "bom_qty": 4 if category in {"motor", "propeller"} else 1,
        **catalog,
        "unit_price_eur": round(unit_eur, 2),
        "price_is_sample": False,
        "shop": str(answer.get("shop") or host).strip()[:60],
        "url": url,
        "shop_price": round(price, 2),
        "shop_currency": code,
        "shop_pack_qty": pack_qty,
        "price_rate": rate,
        "in_stock": bool(answer.get("in_stock", True)),
        "price_checked": stamp,
        "provenance": "web",
        "source_url": url,
        "sources": [{**s, "checked": stamp} for s in sources],
        "fields": meta,
        "confidence": confidence,
        "checked": stamp,
        "estimated": estimated,
        "note": str(answer.get("note") or "").strip()[:300] or "Found on the web and checked against plausible ranges.",
        "aliases": [w for w in re.findall(r"[a-z0-9]+", (name + " " + mpn).lower()) if len(w) >= 3][:8],
    }
    if manufacturer:
        item["manufacturer"] = manufacturer
    if mpn:
        item["mpn"] = mpn
    if dropped:
        item["left_out"] = sorted(dropped)
    others = {k: m["source"] for k, m in meta.items() if m.get("source") and m["source"] != url}
    if others:
        item["spec_urls"] = others
    return item, []


def _physics_checks(category: str, part: dict) -> list[str]:
    """Cross-field sanity: numbers that pass alone but not together."""

    problems = []
    if category == "motor" and {"thrust_g", "mass_g", "bench_power_w"} <= set(part):
        if part["thrust_g"] / part["mass_g"] > 80:
            problems.append("Thrust " + f"{part['thrust_g']:g}" + " g from a " + f"{part['mass_g']:g}" + " g motor is more than 80 times its weight.")
        efficiency = part["thrust_g"] / part["bench_power_w"]
        if not 0.5 <= efficiency <= 15:
            problems.append("Full-throttle efficiency " + f"{efficiency:.1f}" + " g/W is outside 0.5 to 15.")
        if "bench_current_a" in part and "bench_voltage_v" in part:
            electrical = part["bench_current_a"] * part["bench_voltage_v"]
            if not 0.5 <= part["bench_power_w"] / electrical <= 1.6:
                problems.append("Power " + f"{part['bench_power_w']:g}" + " W does not match " + f"{part['bench_current_a']:g}" + " A at " + f"{part['bench_voltage_v']:g}" + " V.")
    if category == "battery" and {"cells", "voltage_v", "capacity_mah", "mass_g"} <= set(part):
        per_cell = part["voltage_v"] / part["cells"]
        if not 3.2 <= per_cell <= 4.4:
            problems.append(f"{part['voltage_v']:g}" + " V over " + f"{part['cells']:g}" + " cells is " + f"{per_cell:.2f}" + " V per cell; a lithium cell is 3.2 to 4.4 V.")
        wh_per_kg = part["voltage_v"] * part["capacity_mah"] / 1000.0 / (part["mass_g"] / 1000.0)
        if not 60 <= wh_per_kg <= 320:
            problems.append("Energy density " + f"{wh_per_kg:.0f}" + " Wh/kg is outside what lithium packs reach (60 to 320).")
    if category == "propeller" and "pitch_in" in part and "diameter_mm" in part:
        if part["pitch_in"] * 25.4 > part["diameter_mm"] * 1.6:
            problems.append("Pitch is far larger than the diameter.")
    return problems


def _catalog_fields(category: str, part: dict) -> tuple[dict, dict]:
    """The validated specs under the catalog's own field names, so physics and CAD read them as-is,
    and the computed fields with the fields they come from."""

    out = dict(part)
    derived: dict[str, list[str]] = {}
    if category == "motor":
        thrust = out["thrust_g"]
        bench = {"voltage_v": out.pop("bench_voltage_v"), "thrust_g": thrust, "power_w": out.pop("bench_power_w")}
        if "bench_current_a" in out:
            bench["current_a"] = out.pop("bench_current_a")
            out["max_current_a"] = bench["current_a"]
        out["bench"] = bench
        out["max_power_w"] = bench["power_w"]
        out["efficiency_g_per_w"] = round(thrust / bench["power_w"], 2)
        derived["efficiency_g_per_w"] = ["thrust_g", "bench_power_w"]
        out["cells_max"] = int(out["cells_max"])
        if "cells_min" in out:
            out["cells_min"] = int(out["cells_min"])
        out["scene_target"] = "motor_front_left"
    elif category == "propeller":
        if "blades" in out:
            out["blades"] = int(out["blades"])
        out["scene_target"] = "propeller_front_left"
    elif category == "battery":
        out["cells"] = int(out["cells"])
        out["scene_target"] = "battery"
    elif category == "flight_controller":
        if "cells_max" in out:
            out["cells_max"] = int(out["cells_max"])
        out["scene_target"] = "flight_controller"
    elif category == "frame":
        out["arm_length_mm"] = round(out["wheelbase_mm"] / 2.0, 2)
        derived["arm_length_mm"] = ["wheelbase_mm"]
        out["scene_target"] = "frame"
    if "fov_h_deg" in out and "fov_deg" not in out:
        # The chase model maps a diagonal field of view onto a 4:3 picture as 4/5 horizontal (plant.camera_spec); this is its inverse.
        out["fov_deg"] = round(min(out["fov_h_deg"] * 5.0 / 4.0, 360.0), 1)
        derived["fov_deg"] = ["fov_h_deg"]
    if category in {"camera", "vtx"}:
        sides = [out[k] for k in ("length_mm", "width_mm") if k in out]
        if sides:
            out["size_mm"] = max(sides)
            derived["size_mm"] = [k for k in ("length_mm", "width_mm") if k in out]
        out["scene_target"] = "frame"
    elif category not in FIELDS:
        if all(k in out for k in ("length_mm", "width_mm", "height_mm")):
            out["size_mm"] = [out.pop("length_mm"), out.pop("width_mm"), out.pop("height_mm")]
    return out, derived


_STOP = {"the", "and", "for", "with", "module", "board", "part", "kit", "pcs", "piece", "new"}


def relevance(candidate: dict, query: str) -> float:
    """The share of the query's words a distributor candidate carries (maker, part number, description, parameters)."""

    words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 3 and w not in _STOP}
    if not words:
        return 0.0
    text = " ".join([candidate.get("manufacturer", ""), candidate.get("mpn", ""), candidate.get("text") or candidate.get("description", "")] + [str(v) for v in (candidate.get("params") or {}).values()]).lower()
    compact = learned_parts.norm(text)
    return sum(1 for w in words if w in text or w in compact) / len(words)


def from_candidate(candidate: dict) -> dict:
    """A distributor candidate as an answer for `validate`: its listings are the sources, its parametric numbers the specs."""

    sources = candidate.get("listings") or [{"url": candidate["url"], "kind": "distributor", "distributor": candidate["distributor"], "manufacturer": candidate["manufacturer"], "mpn": candidate["mpn"]}]
    spec_sources = candidate.get("spec_sources") or {}
    return {
        "found": True,
        "name": (candidate["manufacturer"] + " " + candidate["mpn"] + (", " + candidate["description"] if candidate.get("description") else ""))[:90],
        "manufacturer": candidate["manufacturer"],
        "mpn": candidate["mpn"],
        "url": candidate["url"],
        "shop": candidate["distributor"],
        "price": candidate.get("price"),
        "currency": candidate.get("currency") or "EUR",
        "pack_qty": 1,
        "in_stock": bool(candidate.get("stock")),
        "sources": sources,
        "specs": {k: {"value": v, "source": spec_sources.get(k, candidate["url"]), "read": "stated"} for k, v in (candidate.get("specs") or {}).items()},
        "conflicts": candidate.get("conflicts") or [],
        "note": "Parametric data from " + ", ".join(sorted({s.get("distributor") or s["url"].split("/")[2] for s in sources})) + "; datasheet " + str(candidate.get("datasheet_url") or "not listed") + ".",
    }


def with_candidate(answer: dict | None, candidates: list[dict], category: str) -> dict | None:
    """The answer completed by the distributor listing of the same part: its listings join the
    sources, numbers the pages lack are taken with the listing as their source, numbers both give
    must agree (within 10 %, mass excepted: a distributor's unit weight may include packaging)."""

    if not isinstance(answer, dict) or answer.get("found") is False or not answer.get("mpn"):
        return answer
    match = next((c for c in candidates if learned_parts.norm(c["mpn"]) == learned_parts.norm(answer["mpn"]) and learned_parts.same_maker(c["manufacturer"], answer.get("manufacturer") or c["manufacturer"])), None)
    if match is None:
        return answer
    out = json.loads(json.dumps(answer))
    listed = out.get("sources") if isinstance(out.get("sources"), list) else [{"url": out.get("url"), "kind": "shop", "manufacturer": out.get("manufacturer"), "mpn": out.get("mpn")}]
    for listing in match.get("listings") or []:
        if listing["url"] not in {s.get("url") for s in listed if isinstance(s, dict)}:
            listed.append(listing)
    out["sources"] = listed
    specs = out.get("specs") if isinstance(out.get("specs"), dict) else {}
    fields = fields_for(category)
    conflicts = list(out.get("conflicts") or []) + list(match.get("conflicts") or [])
    for key, value in (match.get("specs") or {}).items():
        if key not in fields:
            continue
        source = (match.get("spec_sources") or {}).get(key, match["url"])
        if key not in specs or specs[key] in (None, "", []):
            specs[key] = {"value": value, "source": source, "read": "stated"}
            continue
        if key == "mass_g":
            continue
        kind = fields[key][0]
        page = _convert(_spec_entry(specs[key], out.get("url", ""), [], key)["value"], kind)
        listing = _convert(value, kind)
        if isinstance(page, float) and isinstance(listing, float) and abs(page - listing) > 0.1 * max(abs(page), abs(listing), 1e-9):
            conflicts.append(key + ": the pages say " + f"{page:g}" + ", " + match["distributor"] + " lists " + f"{listing:g}")
    out["specs"] = specs
    out["conflicts"] = conflicts
    if not out.get("price") and match.get("price"):
        out.update({"price": match["price"], "currency": match.get("currency") or "EUR", "pack_qty": 1, "url": match["url"], "shop": match["distributor"]})
    return out


def enabled() -> bool:
    return live_prices_enabled()


def allow_estimated() -> bool:
    from pai_agent import settings

    return bool(settings.current().get("allow_estimated"))


def _ask_claude(request: dict, deadline: float) -> tuple[str, dict]:
    """One blocking search conversation with the API's web search and fetch; (final text, usage). Runs in a worker thread."""

    import anthropic

    client = anthropic.Anthropic(max_retries=0)
    messages = list(request["messages"])
    text = ""
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0, "searches": 0, "fetches": 0}
    # Long searches pause the turn; send the partial answer back so the server continues it.
    for _round in range(8):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        response = client.messages.create(**{**request, "messages": messages}, timeout=remaining)
        got = getattr(response, "usage", None)
        usage["input_tokens"] += int(getattr(got, "input_tokens", 0) or 0)
        usage["output_tokens"] += int(getattr(got, "output_tokens", 0) or 0)
        usage["cache_read_tokens"] += int(getattr(got, "cache_read_input_tokens", 0) or 0)
        usage["cache_write_tokens"] += int(getattr(got, "cache_creation_input_tokens", 0) or 0)
        server = getattr(got, "server_tool_use", None)
        usage["searches"] += int(getattr(server, "web_search_requests", 0) or 0)
        usage["fetches"] += int(getattr(server, "web_fetch_requests", 0) or 0)
        text = "".join(str(block.text) for block in response.content if getattr(block, "type", None) == "text")
        if response.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": [block.model_dump(exclude_none=True) for block in response.content]}]
    return text, usage


def _search(request: dict, deadline: float) -> tuple[str, dict]:
    """The API's server-side web search, or Claude Code's WebSearch and WebFetch on the local subscription."""

    if provider.active() == "subscription":
        from pai_agent.subscription import ask_web

        return ask_web(request["model"], request["system"], request["messages"][0]["content"], deadline, max_turns=SUBSCRIPTION_TURNS), {"plan": True}
    answer = _ask_claude(request, deadline)
    return answer if isinstance(answer, tuple) else (answer, {})


def _cost(model: str, usage: dict) -> dict:
    """What the search cost: searches, page reads, tokens and dollars (or the plan on the subscription)."""

    if usage.get("plan"):
        return {"billed": "Claude subscription plan"}
    if not usage:
        return {}
    from pai_agent.settings import cost_usd

    usd = cost_usd(model, usage) + usage.get("searches", 0) * SEARCH_USD
    return {
        "searches": usage.get("searches", 0),
        "page_reads": usage.get("fetches", 0),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "usd": round(usd, 4),
    }


def add(part: dict) -> dict:
    """Keeps a validated part in the learned library; returns the stored (possibly merged) entry."""

    return learned_parts.add(part)


def found_parts(category: str | None = None, allow_estimated_parts: bool | None = None) -> list[dict]:
    """Every learned part, optionally one category; parts with estimates only in exploration mode."""

    allowed = allow_estimated() if allow_estimated_parts is None else allow_estimated_parts
    return learned_parts.all_parts(category, allowed)


def clear() -> None:
    """Forget the loaded library in this process (tests)."""

    learned_parts.reset()


async def discover(category: str, need: str, query: str = "", require=(), allow_estimated_parts: bool | None = None) -> dict:
    """{ok, part, ...} with a validated part, or {ok: False, error, problems} saying why not."""

    need = need.strip()
    require = [str(name).strip() for name in require or [] if str(name).strip()]
    if not need:
        return {"ok": False, "error": "Say what the part must do: need names it, e.g. '1S whoop motor, 40 g thrust'."}
    unknown = unknown_fields(category, require)
    if unknown:
        return {"ok": False, "error": "require names unknown fields " + ", ".join(unknown) + "; for " + category + " use " + ", ".join(fields_for(category)) + "."}
    allowed = allow_estimated() if allow_estimated_parts is None else allow_estimated_parts
    required = list(dict.fromkeys(critical(category) + require))
    learned = learned_parts.for_need(category, need, required, allowed) or learned_parts.match(category, query or need, required, allowed)
    if learned:
        return {"ok": True, "part": learned, "cached": True, "from": "learned library"}
    search: dict = {"required": required}
    candidates: list[dict] = []
    refused: list[str] = []
    if distributors.applies(category) and distributors.configured():
        keywords = query or need
        found = await asyncio.to_thread(distributors.search, category, keywords)
        # A distributor's keyword search is fuzzy: keep the candidates that carry the search words.
        candidates = sorted((c for c in found["candidates"] if relevance(c, keywords) > 0), key=lambda c: -relevance(c, keywords))
        search.update({"distributors": found["used"], "distributor_notes": found["notes"], "distributor_matches": len(candidates)})
        for candidate in candidates:
            # Taken as it is only when it carries every search word the caller gave; otherwise Claude judges the fit.
            if not query or relevance(candidate, query) < 1.0:
                continue
            part, problems = validate(category, from_candidate(candidate), require=require, allow_estimated=allowed)
            if part is not None:
                stored = add(part)
                learned_parts.remember_need(category, need, stored["id"])
                return {"ok": True, "part": stored, "from": "distributors", "search": search}
            refused.append(candidate["manufacturer"] + " " + candidate["mpn"] + ": " + " ".join(problems[:3]))
    if not enabled():
        if refused:
            return {"ok": False, "error": "The distributors list parts that lack numbers this build needs, and web search needs Claude: " + " | ".join(refused[:3]), "problems": refused, "search": search}
        return {"ok": False, "error": "Web discovery needs Claude (ANTHROPIC_API_KEY or the local Claude subscription) or a distributor API key; pick from the curated library instead.", "search": search}
    model = model_name()
    try:
        deadline = time.monotonic() + TIMEOUT_S
        request = request_for(category, need, model, require, allowed, candidates)
        text, usage = await asyncio.wait_for(asyncio.to_thread(_search, request, deadline), TIMEOUT_S + 5)
    except Exception as exc:
        log.warning("web part search failed for %s: %s", need, exc)
        return {"ok": False, "error": "The web search failed: " + str(exc)[:160], "search": search}
    search["cost"] = _cost(model, usage)
    answer = with_candidate(_parse(text), candidates, category)
    part, problems = validate(category, answer, require=require, allow_estimated=allowed)
    if part is None:
        hint = "" if allowed else " Exploration mode (Settings, or PAI_ALLOW_ESTIMATED=1) would allow labelled estimates for non-critical fields."
        return {"ok": False, "error": "The web answer did not pass validation: " + " ".join(problems[:6]) + hint, "problems": problems, "search": search}
    stored = add(part)
    learned_parts.remember_need(category, need, stored["id"])
    return {"ok": True, "part": stored, "from": "web", "search": search}


def cost_line(search: dict | None) -> str:
    """ " · Digi-Key, Mouser · 6 searches, 2 page reads, $0.18": what a discovery asked and what it cost."""

    search = search or {}
    bits = []
    if search.get("distributors"):
        bits.append(", ".join(search["distributors"]))
    cost = search.get("cost") or {}
    if cost.get("billed"):
        bits.append(cost["billed"])
    elif cost:
        bits.append(str(cost.get("searches", 0)) + " searches, " + str(cost.get("page_reads", 0)) + " page reads, $" + f"{cost.get('usd', 0):.2f}")
    return "".join(" · " + bit for bit in bits)


def confidence_of(part: dict) -> str:
    """sourced, derived or estimated for a part (its worst field), or catalog for a sample catalog part."""

    if part.get("fields"):
        return part.get("confidence") or "sourced"
    if part.get("price_source") == "estimated" or str(part.get("id", "")).startswith("est-") or part.get("estimated"):
        return "estimated"
    if part.get("provenance") in {"curated", "web"} or part.get("source_url"):
        return "sourced"
    return "catalog"


def card(part: dict) -> dict:
    """What a part card shows about its numbers: the part's confidence, the estimated fields,
    each field's confidence and source, and the pages behind it."""

    out = {"confidence": confidence_of(part), "estimated": list(part.get("estimated") or [])}
    fields = part.get("fields") or {}
    if fields:
        out["fields"] = {k: {"confidence": m.get("confidence"), **({"source": m["source"]} if m.get("source") else {}), **({"basis": m["basis"]} if m.get("basis") else {})} for k, m in fields.items()}
    sources = [{k: s[k] for k in ("url", "kind", "distributor") if s.get(k)} for s in part.get("sources") or [] if s.get("url")]
    if sources:
        out["sources"] = sources
    return out


def estimated_inputs(selected: dict) -> list[str]:
    """ "Caddx Ant: fps, resolution_px" for each chosen part whose numbers include estimates."""

    lines = []
    for part in selected.values():
        if isinstance(part, dict) and part.get("estimated"):
            lines.append(str(part.get("name") or part.get("id")) + ": " + ", ".join(str(k) for k in part["estimated"]))
        elif isinstance(part, dict) and (part.get("price_source") == "estimated" or str(part.get("id", "")).startswith("est-")):
            lines.append(str(part.get("name") or part.get("id")) + ": mass and price")
    return lines


def provenance_line(part: dict) -> str:
    """One line for a result: where the specs come from and what is estimated."""

    sources = part.get("sources") or []
    where = ", ".join(sorted({s.get("distributor") or s["url"].split("/")[2] for s in sources if s.get("url")})) or part.get("shop") or ""
    line = ("Web find" if part.get("provenance") == "web" else "Library") + ", specs from " + str(where) + " checked " + str(part.get("checked") or part.get("price_checked") or "")
    if part.get("estimated"):
        line += "; estimated: " + ", ".join(part["estimated"])
    return line


def library_path() -> Path:
    return learned_parts.path()
