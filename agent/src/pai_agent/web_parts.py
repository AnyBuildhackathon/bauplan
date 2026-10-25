"""Live part discovery: a real product from a real shop page when the curated library has nothing that fits.

`discover` asks Claude with Anthropic's server-side web search to find one product for a need
("1S brushless motor for a 65 mm whoop, at least 40 g thrust") and to copy its specs off the
product page, each as [value, unit] together with the page it came from. `validate` turns that
answer into a catalog part or refuses it:

- units are converted to the catalog's (g, mm, V, mAh, A, W, kg cm) and an unknown unit is a
  problem, not a guess;
- every required field for the category must be on the page; the model may list a field under
  `estimated` only when the page lacks it, and a required field may never be estimated;
- every number must sit in a plausible range for its category (a 3 g motor making 4 kg of thrust,
  a 1S pack at 11 V, a pack with an impossible energy density are refused);
- the URL must be a product page on a real host, the price positive.

A part that passes carries `provenance: "web"`, `source_url`, `shop`, `checked` (today) and
`estimated`, exactly like a curated part, and joins the session's library and a small file cache
(`agent/runs/cache/web_parts.json`) so the same search does not cost twice. Nothing here invents a
number: a field the page does not give stays out, and a required one makes the whole part fail.
On the local Claude Code subscription the search runs on Claude Code's WebSearch and WebFetch
instead, and its answer passes the same `validate`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date
from pathlib import Path

from pai_agent.env import model_name
from pai_agent.paths import RUNS_DIR
from pai_agent import provider
from pai_agent.tools.parts_search import _ask_claude, _parse, _version, _web_search_tool, live_prices_enabled

log = logging.getLogger(__name__)

CACHE_PATH = RUNS_DIR / "cache" / "web_parts.json"
TIMEOUT_S = 120.0
# 1 EUR in each currency, the ECB reference rates the catalog uses.
EUR_RATES = {"EUR": 1.0, "USD": 1.1193, "GBP": 0.83728, "CAD": 1.5665, "CHF": 0.93, "CNY": 7.97, "JPY": 170.0, "AUD": 1.70}

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
}

# Per category: field -> (kind of unit, low, high, required). Ranges cover tiny whoops to big rovers.
FIELDS: dict[str, dict[str, tuple[str, float, float, bool]]] = {
    "motor": {
        "mass_g": ("g", 0.3, 2000, True),
        "thrust_g": ("g", 3, 20000, True),
        "bench_voltage_v": ("V", 1, 60, True),
        "bench_current_a": ("A", 0.1, 200, False),
        "bench_power_w": ("W", 0.3, 5000, True),
        "kv": ("KV", 50, 80000, True),
        "diameter_mm": ("mm", 5, 120, True),
        "height_mm": ("mm", 4, 120, True),
        "shaft_mm": ("mm", 0.5, 12, False),
        "mount_diameter_mm": ("mm", 3, 60, False),
        "cells_max": ("count", 1, 14, True),
        "cells_min": ("count", 1, 14, False),
    },
    "propeller": {
        "diameter_mm": ("mm", 15, 800, True),
        "pitch_in": ("in", 0.3, 15, False),
        "blades": ("count", 2, 8, True),
        "mass_g": ("g", 0.03, 300, True),
        "shaft_mm": ("mm", 0.5, 12, False),
    },
    "battery": {
        "cells": ("count", 1, 14, True),
        "voltage_v": ("V", 2.4, 60, True),
        "capacity_mah": ("mAh", 40, 50000, True),
        "c_rating": ("C", 1, 250, False),
        "mass_g": ("g", 1, 10000, True),
        "length_mm": ("mm", 5, 400, True),
        "width_mm": ("mm", 3, 300, True),
        "height_mm": ("mm", 2, 200, True),
    },
    "flight_controller": {
        "mass_g": ("g", 0.5, 200, True),
        "mount_mm": ("mm", 10, 45, True),
        "cells_min": ("count", 1, 14, False),
        "cells_max": ("count", 1, 14, True),
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
    "camera": {"mass_g": ("g", 0.2, 500, True), "length_mm": ("mm", 3, 150, True), "width_mm": ("mm", 3, 150, True), "height_mm": ("mm", 3, 150, False)},
    "vtx": {"mass_g": ("g", 0.2, 200, True), "length_mm": ("mm", 3, 100, True), "width_mm": ("mm", 3, 100, True), "height_mm": ("mm", 1, 60, False), "power_mw": ("count", 1, 5000, False)},
    "canopy": {"mass_g": ("g", 0.2, 200, True)},
    "hardware": {"mass_g": ("g", 0.001, 500, True)},
}
# Any other product's bought part (servo, sensor, wheel, pump): mass and size, plus what the checks read.
GENERIC: dict[str, tuple[str, float, float, bool]] = {
    "mass_g": ("g", 0.01, 50000, True),
    "length_mm": ("mm", 0.5, 3000, True),
    "width_mm": ("mm", 0.5, 3000, True),
    "height_mm": ("mm", 0.2, 3000, True),
    "voltage_v": ("V", 0.5, 400, False),
    "power_w": ("W", 0.001, 20000, False),
    "current_a": ("A", 0.001, 500, False),
    "capacity_mah": ("mAh", 10, 200000, False),
    "stall_torque_kgcm": ("kgcm", 0.01, 5000, False),
    "rpm": ("rpm", 1, 100000, False),
    "thrust_g": ("g", 1, 50000, False),
}
DRONE_CATEGORIES = tuple(FIELDS)

_SYSTEM = (
    "You find real, orderable parts for physical products and copy their specifications from the product page. "
    "Use web search. Prefer the maker's own product page or a shop that ships to the EU. Pick one exact product that is in stock if possible. "
    "Copy numbers exactly as the page states them with their unit; never compute, round up or fill in a number the page does not give. "
    "When a spec is not on the page, leave it out. Answer with one JSON object and nothing else."
)


def _shape(category: str) -> str:
    fields = FIELDS.get(category, GENERIC)
    specs = ", ".join('"' + key + '": [value, "' + kind + '"]' for key, (kind, _low, _high, _required) in fields.items())
    return (
        '{"found": true, "name": "...", "url": "https://<the product page>", "shop": "...", "price": 0.0, "currency": "EUR", '
        '"pack_qty": 1, "in_stock": true, "specs": {' + specs + '}, "spec_urls": {"<field>": "https://<another page, only if not the product page>"}, '
        '"estimated": [], "note": "one sentence: what the page says"}'
    )


def request_for(category: str, need: str, model: str) -> dict:
    fields = FIELDS.get(category, GENERIC)
    required = [key for key, spec in fields.items() if spec[3]]
    extra = ""
    if category == "motor":
        extra = (
            "thrust_g, bench_voltage_v, bench_current_a and bench_power_w are the 100 % throttle row of the maker's thrust/load test table "
            "(say which propeller in note). "
        )
    prompt = (
        "Category: " + category.replace("_", " ") + "\n"
        + "Need: " + need.strip() + "\n\n"
        + "Find one real product that fits and copy its specs from its page. " + extra
        + "Required specs: " + ", ".join(required) + ". If the page lacks a required spec, pick another product. "
        + "price is per pack in the shop's currency, pack_qty how many pieces the pack holds. "
        + 'If nothing fits, return {"found": false, "why": "..."}.\nShape: ' + _shape(category)
    )
    request = {
        "model": model,
        "max_tokens": 6000,
        "system": _SYSTEM,
        "tools": [{**_web_search_tool(model), "max_uses": 6}],
        "messages": [{"role": "user", "content": prompt}],
    }
    if _version(model)[1] >= 4.6:
        request["output_config"] = {"effort": "low"}
    return request


def _convert(raw, kind: str) -> float | None:
    """A [value, unit] pair (or a bare number in the catalog unit) in the catalog unit, else None."""

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


def validate(category: str, answer: dict | None, today: str | None = None) -> tuple[dict | None, list[str]]:
    """A catalog part from the model's answer, or None and every reason it was refused."""

    problems: list[str] = []
    if not isinstance(answer, dict) or answer.get("found") is False:
        why = (answer or {}).get("why") if isinstance(answer, dict) else None
        return None, ["Nothing found" + (": " + str(why) if why else ".")]
    name = str(answer.get("name") or "").strip()
    url = str(answer.get("url") or "").strip()
    if not name:
        problems.append("No product name.")
    if not re.match(r"^https?://[^\s/]+\.[a-z]{2,}(/\S*)?$", url, re.I):
        problems.append("No product page URL.")
    price = answer.get("price")
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = None
    currency = str(answer.get("currency") or "EUR").strip().upper()[:3]
    if price is None or price <= 0:
        problems.append("No price.")
    if currency not in EUR_RATES:
        problems.append("Unknown currency " + currency + ".")
    try:
        pack_qty = max(1, int(answer.get("pack_qty") or 1))
    except (TypeError, ValueError):
        pack_qty = 1
    fields = FIELDS.get(category, GENERIC)
    specs = answer.get("specs") if isinstance(answer.get("specs"), dict) else {}
    estimated = [str(item) for item in answer.get("estimated") or [] if isinstance(item, str)]
    part: dict = {}
    for key, (kind, low, high, required) in fields.items():
        if key not in specs or specs[key] in (None, "", []):
            if required:
                problems.append(key + " is not on the page.")
            continue
        value = _convert(specs[key], kind)
        if value is None:
            problems.append(key + ": unit " + repr(specs[key]) + " is not a " + kind + " unit.")
            continue
        if not low <= value <= high:
            problems.append(key + " = " + f"{value:g}" + " " + kind + " is outside " + f"{low:g}" + " to " + f"{high:g}" + ".")
            continue
        if required and key in estimated:
            problems.append(key + " is required and may not be an estimate.")
            continue
        part[key] = round(value, 4)
    problems += _physics_checks(category, part)
    if problems:
        return None, problems

    unit_eur = price / EUR_RATES[currency] / pack_qty
    if not 0.005 <= unit_eur <= 20000:
        return None, ["Price per piece " + f"{unit_eur:.2f}" + " EUR is implausible."]
    stamp = today or date.today().isoformat()
    host = url.split("/")[2]
    item = {
        "id": "web-" + _slug(name),
        "name": name[:90],
        "category": category,
        "bom_qty": 4 if category in {"motor", "propeller"} else 1,
        **_catalog_fields(category, part),
        "unit_price_eur": round(unit_eur, 2),
        "price_is_sample": False,
        "shop": str(answer.get("shop") or host).strip()[:60],
        "url": url,
        "shop_price": round(price, 2),
        "shop_currency": currency,
        "shop_pack_qty": pack_qty,
        "in_stock": bool(answer.get("in_stock", True)),
        "price_checked": stamp,
        "provenance": "web",
        "source_url": url,
        "checked": stamp,
        "estimated": [key for key in estimated if key in part],
        "note": str(answer.get("note") or "").strip()[:300] or "Found on the web and checked against plausible ranges.",
        "aliases": [w for w in re.findall(r"[a-z0-9]+", name.lower()) if len(w) >= 3][:6],
    }
    spec_urls = answer.get("spec_urls") if isinstance(answer.get("spec_urls"), dict) else {}
    others = {k: str(v) for k, v in spec_urls.items() if k in part and str(v).startswith(("http://", "https://")) and str(v) != url}
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


def _catalog_fields(category: str, part: dict) -> dict:
    """The validated specs under the catalog's own field names, so physics and CAD read them as-is."""

    out = dict(part)
    if category == "motor":
        thrust = out["thrust_g"]
        bench = {"voltage_v": out.pop("bench_voltage_v"), "thrust_g": thrust, "power_w": out.pop("bench_power_w")}
        if "bench_current_a" in out:
            bench["current_a"] = out.pop("bench_current_a")
            out["max_current_a"] = bench["current_a"]
        out["bench"] = bench
        out["max_power_w"] = bench["power_w"]
        out["efficiency_g_per_w"] = round(thrust / bench["power_w"], 2)
        out["cells_max"] = int(out["cells_max"])
        if "cells_min" in out:
            out["cells_min"] = int(out["cells_min"])
        out["scene_target"] = "motor_front_left"
    elif category == "propeller":
        out["blades"] = int(out["blades"])
        out["scene_target"] = "propeller_front_left"
    elif category == "battery":
        out["cells"] = int(out["cells"])
        out["scene_target"] = "battery"
    elif category == "flight_controller":
        out["cells_max"] = int(out["cells_max"])
        out["scene_target"] = "flight_controller"
    elif category == "frame":
        out["arm_length_mm"] = round(out["wheelbase_mm"] / 2.0, 2)
        out["scene_target"] = "frame"
    elif category in {"camera", "vtx"}:
        out["size_mm"] = max(out["length_mm"], out["width_mm"])
        out["scene_target"] = "frame"
    elif category not in FIELDS:
        out["size_mm"] = [out.pop("length_mm"), out.pop("width_mm"), out.pop("height_mm")]
    return out


# The parts found so far in this process, by id; the file cache survives restarts.
_FOUND: dict[str, dict] = {}
_SEARCHES: dict[str, tuple[float, str | None]] = {}
_SEARCH_TTL_S = 6 * 3600.0


def _load_cache() -> None:
    if _FOUND or not CACHE_PATH.is_file():
        return
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for part in data.get("parts", []):
        if isinstance(part, dict) and part.get("id"):
            _FOUND[part["id"]] = part


def _save_cache() -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({"parts": list(_FOUND.values())}, indent=1), encoding="utf-8")
    except OSError as exc:
        log.warning("web parts cache not written: %s", exc)


def found_parts(category: str | None = None) -> list[dict]:
    """Every web part found so far (this process and the cache), optionally one category."""

    _load_cache()
    return [dict(part) for part in _FOUND.values() if category is None or part["category"] == category]


def add(part: dict) -> dict:
    _load_cache()
    _FOUND[part["id"]] = part
    _save_cache()
    return part


def clear() -> None:
    """Forget the found parts in this process (tests)."""

    _FOUND.clear()
    _SEARCHES.clear()


def enabled() -> bool:
    return live_prices_enabled()


def _search(request: dict, deadline: float) -> str:
    """The API's server-side web search, or Claude Code's WebSearch and WebFetch on the local subscription."""

    if provider.active() == "subscription":
        from pai_agent.subscription import ask_web

        return ask_web(request["model"], request["system"], request["messages"][0]["content"], deadline, max_turns=12)
    return _ask_claude(request, deadline)


async def discover(category: str, need: str) -> dict:
    """{ok, part} with a validated web part, or {ok: False, error, problems} saying why not."""

    need = need.strip()
    if not need:
        return {"ok": False, "error": "Say what the part must do: query names the need, e.g. '1S whoop motor, 40 g thrust'."}
    if not enabled():
        return {"ok": False, "error": "Web discovery needs Claude (ANTHROPIC_API_KEY or the local Claude subscription); pick from the curated library instead."}
    key = category + "|" + need.lower()
    cached = _SEARCHES.get(key)
    if cached and time.monotonic() - cached[0] < _SEARCH_TTL_S and cached[1] in _FOUND:
        return {"ok": True, "part": dict(_FOUND[cached[1]]), "cached": True}
    try:
        deadline = time.monotonic() + TIMEOUT_S
        text = await asyncio.wait_for(asyncio.to_thread(_search, request_for(category, need, model_name()), deadline), TIMEOUT_S + 5)
    except Exception as exc:
        log.warning("web part search failed for %s: %s", need, exc)
        return {"ok": False, "error": "The web search failed: " + str(exc)[:160]}
    part, problems = validate(category, _parse(text))
    if part is None:
        return {"ok": False, "error": "The web answer did not pass validation: " + " ".join(problems[:6]), "problems": problems}
    add(part)
    _SEARCHES[key] = (time.monotonic(), part["id"])
    return {"ok": True, "part": dict(part)}


def provenance_line(part: dict) -> str:
    """One line for a result: where the specs come from and what is estimated."""

    where = part.get("shop") or ""
    line = ("Web find" if part.get("provenance") == "web" else "Library") + ", specs from " + str(where) + " checked " + str(part.get("checked") or part.get("price_checked") or "")
    if part.get("estimated"):
        line += "; estimated: " + ", ".join(part["estimated"])
    return line


def library_path() -> Path:
    return CACHE_PATH
