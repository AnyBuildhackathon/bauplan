"""How far the simulation and the physics card are from real drones: published numbers against ours.

Each row compares one number we compute for a library build with what its maker or a reviewer
published for the same drone (or, for the 5-inch, the class it belongs to). `table()` computes the
rows; `docs/validation.md` is its printout (`scripts/validation_table.py`), and the test keeps every
error inside the bound in its row, so a model change that drifts from reality fails.

How the comparisons are read:

- A maker's "up to" flight time is a gentle flight near hover: it is compared with the hover time.
- A reviewer's freestyle flight time lies between flat-out and hover: the error is how far it falls
  outside the band [full-speed time, hover time], zero inside it.
- A top speed is compared with the card's top speed on the fresh pack and with the MuJoCo speed run.
- A motor's thrust is the plant's motor and prop model at each throttle row of the maker's load
  table, taking the throttle as the share of the table's voltage, against the published thrust.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

# The LAVA II 1S packs the Air75 II and Meteor75 Pro II are rated with, from BetaFPV's page
# (https://betafpv.com/products/lava-ii-1s-battery): 95C, LiHV, BT2.0; mass and size per variant.
LAVA_II_480 = {"id": "betafpv-lava-ii-1s-480", "name": "BetaFPV LAVA II 1S 480mAh 95C", "category": "battery", "bom_qty": 1, "mass_g": 12.6, "capacity_mah": 480,
               "voltage_v": 3.8, "cells": 1, "c_rating": 95, "chemistry": "LiHV", "length_mm": 61, "width_mm": 15.5, "height_mm": 6, "unit_price_eur": 6.0}
LAVA_II_580 = {"id": "betafpv-lava-ii-1s-580", "name": "BetaFPV LAVA II 1S 580mAh 95C", "category": "battery", "bom_qty": 1, "mass_g": 14.1, "capacity_mah": 580,
               "voltage_v": 3.8, "cells": 1, "c_rating": 95, "chemistry": "LiHV", "length_mm": 70, "width_mm": 15, "height_mm": 6.5, "unit_price_eur": 6.0}

AIR75_II = ["betafpv-0802-22000kv", "gemfan-1614-3", "betafpv-matrix-1s-5in1-v2", "betafpv-air75-ii", "betafpv-c03"]
AIR75_II_CHAMPION = ["betafpv-0802-28000kv", "gemfan-1614-3", "betafpv-matrix-1s-5in1-v2", "betafpv-air75-ii", "betafpv-c03"]
METEOR75_PRO_II = ["betafpv-1102-21000kv", "gemfan-1811-3", "betafpv-matrix-1s-5in1-v2", "betafpv-meteor75-pro-ii", "betafpv-c03"]
FIVE_INCH = ["betafpv-snow-2306-1860kv", "gemfan-51466-v2", "betafpv-lava-6s-1100", "betafpv-f722-35a-aio", "betafpv-x-knight-5", "caddx-ratel-19mm", "betafpv-a03-vtx"]

AIR75_URL = "https://betafpv.com/products/air75-ii-brushless-whoop-quadcopter"
METEOR_URL = "https://betafpv.com/products/meteor75-pro-ii-brushless-whoop-quadcopter"
OSCAR_METEOR_URL = "https://oscarliang.com/betafpv-meteor75-pro-ii-analog/"
UT_SPEED_URL = "https://www.unmannedtechshop.co.uk/blogs/knowledge-base/fpv-drone-top-speed-how-fast-real-world-by-build-class"
UT_TIME_URL = "https://www.unmannedtechshop.co.uk/blogs/knowledge-base/fpv-drone-flight-time-how-to-get-more-minutes-in-the-air"

# (drone, parts, pack, what, real value or (low, high), unit, how we read it, source, bound on the error in %)
CLAIMS = [
    ("Air75 II Freestyle", AIR75_II, LAVA_II_480, "flight time", 7.5, "min", "maker", "BetaFPV: up to 7:30 on LAVA II 1S 480 mAh", AIR75_URL, 8),
    ("Air75 II Champion", AIR75_II_CHAMPION, LAVA_II_480, "flight time", 6.83, "min", "maker", "BetaFPV: up to 6:50 on LAVA II 1S 480 mAh", AIR75_URL, 8),
    ("Air75 II Freestyle", AIR75_II, LAVA_II_480, "dry weight", 21.3, "g", "weight", "BetaFPV: 21.3 g without battery", AIR75_URL, 18),
    ("Meteor75 Pro II", METEOR75_PRO_II, LAVA_II_580, "flight time", 10.5, "min", "maker", "BetaFPV: up to 10:30 on LAVA II 1S 580 mAh", METEOR_URL, 16),
    ("Meteor75 Pro II", METEOR75_PRO_II, "betafpv-lava-1s-680", "flight time", 11.5, "min", "maker", "BetaFPV: up to 11:30 on LAVA II 1S 680 mAh", METEOR_URL, 16),
    ("Meteor75 Pro II", METEOR75_PRO_II, LAVA_II_580, "flight time", 5.0, "min", "freestyle", "Oscar Liang: around 5 min on the 580, flown hard", OSCAR_METEOR_URL, 0),
    ("Meteor75 Pro II", METEOR75_PRO_II, "betafpv-lava-1s-680", "flight time", 6.0, "min", "freestyle", "Oscar Liang: around 6 min on the 680, flown hard", OSCAR_METEOR_URL, 0),
    ("Meteor75 Pro II", METEOR75_PRO_II, LAVA_II_580, "top speed", 85.0, "km/h", "speed", "Oscar Liang: estimated top speed around 85 km/h", OSCAR_METEOR_URL, 10),
    ("Meteor75 Pro II", METEOR75_PRO_II, LAVA_II_580, "thrust-to-weight", 6.33, ":1", "twr", "BetaFPV: 6.33:1 with the LAVA II 580", METEOR_URL, 13),
    ("Meteor75 Pro II", METEOR75_PRO_II, LAVA_II_580, "dry weight", 27.98, "g", "weight", "BetaFPV: 27.98 g", METEOR_URL, 18),
    ("5-inch 6S freestyle", FIVE_INCH, None, "top speed", 150.0, "km/h", "speed", "Unmanned Tech: a typical 6S 5-inch freestyle quad reaches roughly 150 km/h", UT_SPEED_URL, 10),
    ("5-inch 6S freestyle", FIVE_INCH, None, "flight time", (3.0, 5.0), "min", "freestyle", "Unmanned Tech: 3 to 5 min of 5-inch freestyle on a 4S 1300 (the 6S 1100 holds 27 % more energy)", UT_TIME_URL, 0),
]

# Motors with a published load table: the plant's thrust at each row against the maker's.
MOTOR_TABLES = [
    ("betafpv-0802-22000kv", "gemfan-1614-3"),
    ("betafpv-0802-28000kv", "gemfan-1614-3"),
    ("betafpv-1102-21000kv", "gemfan-1811-3"),
    ("betafpv-1103-10500kv", "gemfan-2218-3"),
    ("betafpv-1104-7200kv", "gemfan-d22-3"),
    ("betafpv-1104-5500kv", "gemfan-d22-3"),
    ("betafpv-snow-2306-1860kv", "gemfan-51466-v2"),
    ("betafpv-snow-2306-2500kv", "gemfan-51466-v2"),
]
MOTOR_BOUND_PCT = 12  # mean error over the rows from 50 to 100 % throttle


def _parts() -> dict:
    from pai_agent.tools.parts import catalog

    return {p["id"]: p for p in catalog()["parts"]}


def _state(ids: list[str], pack) -> object:
    from pai_agent.state import BuildState

    parts = _parts()
    state = BuildState(session_id="validation", directory=Path(tempfile.mkdtemp()))
    for pid in ids:
        part = dict(parts[pid])
        state.selected[part["category"]] = part
    if isinstance(pack, dict):
        state.selected["battery"] = dict(pack)
    elif isinstance(pack, str):
        state.selected["battery"] = dict(parts[pack])
    return state


def _error(ours: float, real) -> float:
    """Signed error in % of the real value; for a range, how far outside it (zero inside)."""

    if isinstance(real, tuple):
        low, high = real
        if ours < low:
            return (ours - low) / low * 100.0
        if ours > high:
            return (ours - high) / high * 100.0
        return 0.0
    return (ours - real) / real * 100.0


def build_rows(fly: bool = True) -> list[dict]:
    """One row per published number; `fly` adds the MuJoCo speed run to the top-speed rows."""

    from pai_agent.drone_geometry import geometry
    from pai_agent.mission_sim import airframe, run
    from pai_agent.tools.physics import compute

    rows = []
    cache: dict = {}
    for drone, ids, pack, what, real, unit, how, said, url, bound in CLAIMS:
        key = (tuple(ids), pack["id"] if isinstance(pack, dict) else pack)
        if key not in cache:
            state = _state(ids, pack)
            cache[key] = (state, compute(state))
        state, metrics = cache[key]
        perf = metrics["performance"]
        battery = state.selected["battery"]
        note = ""
        if how == "maker":
            ours = perf["flight_time_hover_min"]
            note = "hover, plant (core card " + f"{metrics['flight_time_min']:.1f}" + " min)"
            error = _error(ours, real)
        elif how == "freestyle":
            ours = (metrics["flight_time_full_speed_min"], perf["flight_time_hover_min"])
            note = "full speed to hover"
            low, high = real if isinstance(real, tuple) else (real, real)
            if ours[0] > high:
                error = (ours[0] - high) / high * 100.0
            elif ours[1] < low:
                error = (ours[1] - low) / low * 100.0
            else:
                error = 0.0
        elif how == "speed":
            ours = metrics["top_speed_kmh"]
            note = "card, fresh pack; " + f"{perf['top_speed_end_kmh']:.0f}" + " km/h at the end of the pack"
            if fly:
                flown = run(airframe(geometry(state), state.selected), "speed_run")
                note += "; MuJoCo speed run " + f"{flown['top_speed_kmh']:.0f}" + " km/h"
            error = _error(ours, real)
        elif how == "twr":
            ours = metrics["thrust_to_weight"]
            note = "bench thrust over the weight with the pack"
            error = _error(ours, real)
        else:
            ours = metrics["weight_g"] - float(battery["mass_g"])
            note = "the parts' masses, no pack"
            error = _error(ours, real)
        rows.append({
            "drone": drone, "what": what, "pack": battery.get("name") if how != "weight" else "", "real": real, "unit": unit, "ours": ours,
            "how": note, "error_pct": round(error, 1), "bound_pct": bound, "said": said, "url": url,
        })
    return rows


def motor_rows() -> list[dict]:
    """The plant's thrust at each load-table row against the maker's, per motor."""

    from pai_agent.plant import G, Plant

    parts = _parts()
    out = []
    for motor_id, prop_id in MOTOR_TABLES:
        motor = parts[motor_id]
        row = motor["bench"]
        pack = {"voltage_v": row["voltage_v"], "cells": motor.get("cells_max", 1), "capacity_mah": 1000, "c_rating": 100}
        plant = Plant(motor, parts[prop_id], pack)
        errors = []
        cells = []
        for throttle, thrust_g, _watts in row["load_table"]:
            n = float(plant._spin(row["voltage_v"] * throttle / 100.0, 0.0))
            ours = float(plant._thrust(n, 0.0)) / G * 1000.0
            err = (ours - thrust_g) / thrust_g * 100.0
            cells.append((throttle, thrust_g, round(ours, 1), round(err, 1)))
            if throttle >= 50:
                errors.append(abs(err))
        out.append({"motor": motor["name"], "prop": parts[prop_id]["name"], "rows": cells, "mean_error_pct": round(sum(errors) / len(errors), 1),
                    "bound_pct": MOTOR_BOUND_PCT, "url": motor.get("source_url") or motor.get("url")})
    return out


def _fmt(value, unit: str) -> str:
    if isinstance(value, tuple):
        return f"{value[0]:g} to {value[1]:g} {unit}"
    return f"{value:g} {unit}"


def markdown(rows: list[dict], motors: list[dict]) -> str:
    lines = [
        "| Drone | Number | Pack | Published | Ours | Ours is | Error | Bound | Source |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        ours = r["ours"]
        ours_s = f"{ours[0]:.1f} to {ours[1]:.1f} {r['unit']}" if isinstance(ours, tuple) else f"{ours:.1f} {r['unit']}" if r["unit"] != ":1" else f"{ours:.2f}:1"
        real_s = _fmt(r["real"], r["unit"]) if r["unit"] != ":1" else f"{r['real']:g}:1"
        lines.append(f"| {r['drone']} | {r['what']} | {r['pack']} | {real_s} | {ours_s} | {r['how']} | {r['error_pct']:+.1f} % | ±{r['bound_pct']} % | [{r['said']}]({r['url']}) |")
    lines += ["", "| Motor | Prop | Throttle rows: published g / ours g (error) | Mean error 50 to 100 % | Bound |", "| --- | --- | --- | --- | --- |"]
    for m in motors:
        cells = ", ".join(f"{t}%: {pub:g}/{ours:g} ({err:+.0f} %)" for t, pub, ours, err in m["rows"])
        lines.append(f"| [{m['motor']}]({m['url']}) | {m['prop']} | {cells} | {m['mean_error_pct']:.1f} % | {m['bound_pct']} % |")
    return "\n".join(lines) + "\n"
