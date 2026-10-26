"""circuit_design: the chosen parts as a real circuit, wired, checked and simulated by SparkBench.

The parts are the rows electronics_plan reads. The controller sets the board, an ESP32 or a Raspberry Pi Pico;
without one among the parts, Claude may name the board, and the event marks it as proposed by Mechanic.
A part SparkBench builds in (an SG90, a 5 mm LED, a WS2812 ring, a button, an HC-SR04, an MPU-6050 and its other
built-in sensors) becomes one of its feature kinds, which its planner wires and writes the firmware for.
Any other part is looked up by its part number in SparkBench's parts library (an MG996R, a PCA9685, a DRV8833)
and wired with its driver file added. SparkBench powers the board over USB and adds a supply for a part that
needs its own. What it has no model for is listed in gaps, never left out silently. SparkBench then runs its
design checks, its acceptance tests and 5 s of the firmware in its simulator (`sparkbench.py`,
`agent/sparkbench/bridge.ts`); the files land in the session and the `circuit` event carries the result.
"""

from __future__ import annotations

import datetime
import re

from pai_agent import sparkbench
from pai_agent.context import Ctx
from pai_agent.tools.electronics import _parts
from pai_agent.versions import bench_version

BOARDS = {"esp32": "ESP32 DevKit V1", "pico": "Raspberry Pi Pico"}
# Bought parts that carry no current stay out of the circuit without a gap.
_MECHANICAL = {"hardware", "bearing", "magnet", "wheel", "pads", "tubing", "frame", "propeller", "canopy"}
_CONTROLLERS = {"controller", "flight_controller", "microcontroller", "mcu"}
_POWER = {"power", "battery", "regulator"}

# The parts SparkBench builds in, by the words of their name: (pattern, unless, feature kind); the first match wins.
# A module with its own part number (a KY-016 RGB module, a 4-channel relay board) is left to the library.
_FEATURES = (
    # SparkBench's built-in servo is the SG90; the 360-degree one is a library part.
    (r"\bsg ?90\b", r"\b360\b", "servo"),
    (r"\b(ws ?28(11|12)b?|sk ?6812|neopixels?|addressable)\b", r"\b(matrix|panel|rgbw)\b", "neopixel"),
    (r"\brgb\b", r"\b(module|camera)\b", "rgb"),
    (r"\bhc ?sr ?04\b|\bultrasonic\b", None, "hcsr04"),
    (r"\bpir\b|\bhc ?sr ?50[15]\b", None, "pir"),
    (r"\bdht ?22\b|\bam ?2302\b", None, "dht22"),
    (r"\bsoil\b", None, "soil"),
    (r"\bmpu ?6050\b|\bgy ?521\b", None, "mpu6050"),
    (r"\bldr\b|\bphoto ?(resistor|cell)\b", None, "ldr"),
    (r"\bntc\b|\bthermistor\b", None, "ntc"),
    # The built-in OLED is the 0.96 inch SSD1306 with 128 x 64 pixels.
    (r"\bssd ?1306\b|\boled\b", r"\b(sh ?1106|ssd ?13(09|15|27)|128 ?x ?32|0.91)\b", "oled"),
    (r"\b(lcd ?)?1602\b|\b16 ?x ?2\b", None, "lcd"),
    (r"\be ?(paper|ink)\b", None, "epaper"),
    (r"\bpotentiometers?\b", None, "pot"),
    (r"\bbuttons?\b|\btactile\b|\bmomentary\b", r"\b(cell|coin|battery|arcade)\b", "button"),
    (r"\b(buzzer|piezo)\b", r"\bactive\b", "buzzer"),
    # The built-in relay is a 1-channel 5 V module.
    (r"\brelay\b", r"\b([2-9]|\d{2,}) ?(channel|ch)\b|\b(ssr|solid state)\b", "relay"),
    # A power LED on a star or in a bulb needs a driver; SparkBench's LED is a 5 mm indicator.
    (r"\bleds?\b", r"\b\d+(\.\d+)? ?w\b|\b(watts?|star|cob|strip|bulb|e14|e27|matrix|bar|panel|ring|driver|module)\b", "led"),
)
_COLORS = ("red", "green", "blue", "yellow", "white", "orange")
_ESP32 = re.compile(r"\besp ?32\b")
_ESP32_OTHER = re.compile(r"\besp ?32 ?(s2|s3|c2|c3|c5|c6|h2|p4)\b")
_CAMERA = re.compile(r"\b(cam|camera)\b")
_PICO = re.compile(r"\b(pico|rp ?2040)\b")
_USB_POWER = re.compile(r"\busb\b")
_NOT_USB_POWER = re.compile(r"\b(boost|buck|step ?(up|down)|charger|holder|battery|lipo|li ?ion|18650|power ?bank)\b")


def _words(*texts) -> str:
    return re.sub(r"[^a-z0-9.]+", " ", " ".join(str(t) for t in texts if t).lower()).strip()


def _feature(words: str) -> dict | None:
    for pattern, unless, kind in _FEATURES:
        if re.search(pattern, words) and not (unless and re.search(unless, words)):
            feature: dict = {"kind": kind}
            color = next((c for c in _COLORS if re.search(r"\b" + c + r"\b", words)), None)
            if kind == "led" and color:
                feature["props"] = {"color": color}
            count = re.search(r"\b(\d+) ?(leds?|pixels?)\b", words)
            if kind == "neopixel" and count:
                feature["props"] = {"pixels": int(count[1])}
            return feature
    return None


def _board(name: str, words: str, category: str) -> tuple[str | None, str]:
    """The SparkBench board for a controller part, or None with the reason SparkBench cannot build on it."""

    if category == "flight_controller":
        return None, f"SparkBench has no flight controllers: the {name} keeps the Betaflight configuration from the firmware tool"
    if _ESP32_OTHER.search(words):
        return None, f"SparkBench simulates the original ESP32 (DevKit V1); the {name} is a newer ESP32 with other pins"
    if _ESP32.search(words) and _CAMERA.search(words):
        return None, f"the {name} is a camera board whose camera takes most of its pins, and SparkBench has no model of it"
    if _ESP32.search(words):
        return "esp32", ""
    if _PICO.search(words):
        return "pico", ""
    return None, f"SparkBench builds on an ESP32 or a Raspberry Pi Pico, and the {name} is neither"


def _rows(ctx: Ctx) -> tuple[list[dict], list[str]]:
    """The chosen parts with the label they keep in the circuit, and the spec's bought parts nobody picked yet.

    The rules read a part's name and catalog id; its aliases are search words ("relay" for a MOSFET module), so they
    only help find a library part number when the name has none.
    """

    spec_parts = {p["id"]: p for p in (ctx.state.spec or {}).get("parts", [])}
    rows = []
    for row in _parts(ctx):
        item = row["item"]
        role = spec_parts.get(row["key"], {}).get("name")
        rows.append({**row, "label": str(role or row["name"]), "words": _words(item.get("name"), item.get("id")), "alt": _words(*item.get("aliases", []))})
    unpicked = [
        f"{p['name']}: not picked yet, so it is not in the circuit."
        for p in spec_parts.values()
        if p.get("kind") == "bought" and p["id"] not in ctx.state.picked and str(p.get("category") or "") not in _MECHANICAL
    ]
    return rows, unpicked


def _plan(ctx: Ctx, wanted: str) -> dict:
    """What SparkBench gets: the board, whether Mechanic proposed it, the parts, and the gaps known before it runs."""

    rows, gaps = _rows(ctx)
    boards, refused, parts, notes = [], [], [], []
    for row in rows:
        category = str(row["category"] or "")
        if category in _MECHANICAL:
            continue
        if category in _CONTROLLERS:
            board, reason = _board(row["name"], row["words"], category)
            (boards if board else refused).append((board, row, reason))
            continue
        if category == "power" and _USB_POWER.search(row["words"]) and not _NOT_USB_POWER.search(row["words"]):
            notes.append(f"{row['label']} powers the board over USB.")
            continue
        if category in _POWER:
            gaps.append(f"{row['label']}: SparkBench powers the board over USB and adds a supply where a part needs one, so it is not in the circuit.")
            continue
        if category == "resistor":
            gaps.append(f"{row['label']}: SparkBench sizes and places its own resistors, so it is not in the circuit.")
            continue
        feature = _feature(row["words"])
        if category == "switch" and not feature:
            gaps.append(f"{row['label']}: a switch in the supply line; SparkBench powers the board over USB, so it is not in the circuit.")
            continue
        parts.append({"key": row["key"], "label": row["label"], "text": row["words"], "alt": row["alt"], "qty": row["qty"], **({"feature": feature} if feature else {})})
    if refused and not boards:
        _board_name, row, reason = refused[0]
        return {"error": reason[0].upper() + reason[1:] + "."}
    if boards:
        board, row, _reason = boards[0]
        if wanted and wanted != board:
            return {"error": f"The parts already have the {row['name']}; leave board out, or pick a {BOARDS[wanted]} with part_pick first."}
        gaps += [f"{other['label']}: a second controller; the circuit is built on the {row['label']}." for _b, other, _r in boards[1:] + refused]
        return {"board": board, "proposed": False, "controller": row["key"], "parts": parts, "gaps": gaps, "notes": notes}
    if not wanted:
        return {"error": "No ESP32 or Raspberry Pi Pico among the parts. Pick one with part_pick, or pass board to build on one Mechanic proposes."}
    notes.append(f"No controller among the parts: the {BOARDS[wanted]} is proposed by Mechanic.")
    return {"board": wanted, "proposed": True, "controller": None, "parts": parts, "gaps": gaps, "notes": notes}


def _today() -> str:
    """The date in the KiCad title blocks, so the files say when they were made."""

    return datetime.date.today().isoformat()


def _name(ctx: Ctx) -> str:
    return str((ctx.state.spec or {}).get("name") or {"gripper": "Robot gripper", "drone": "Drone"}.get(ctx.state.product, "Product"))


def _summary(result: dict, gaps: list[str]) -> str:
    counts = {s: sum(1 for c in result["checks"] if c["severity"] == s) for s in ("error", "warning")}
    passed = sum(1 for t in result["tests"] if t["pass"])
    sim = result["sim"]
    ran = f"{sim['simulated_s']:g} s simulated" + (f", stopped by an error: {sim['error']}" if sim["error"] else " without an error")
    others, wires = len(result["parts"]) - 1, len(result["wires"])
    return (
        f"{result['board_name']} with {others} part{'s' if others != 1 else ''} and {wires} wire{'s' if wires != 1 else ''}: "
        f"{counts['error']} error{'s' if counts['error'] != 1 else ''} and {counts['warning']} warning{'s' if counts['warning'] != 1 else ''} in the checks, "
        f"{passed} of {len(result['tests'])} tests pass, {ran}."
        + (f" {len(gaps)} gap{'s' if len(gaps) != 1 else ''} to the real build." if gaps else "")
    )


async def circuit_design(ctx: Ctx, args: dict) -> dict:
    wanted = str(args.get("board") or "").strip().lower()
    if wanted and wanted not in BOARDS:
        message = "board is esp32 or pico."
        return {"ok": False, "error": message, "detail": message}
    plan = _plan(ctx, wanted)
    if "error" in plan:
        return {"ok": False, "error": plan["error"], "detail": plan["error"]}
    why = sparkbench.missing()
    if why:
        message = f"SparkBench is not installed on this machine: {why}. {sparkbench.INSTALL_HINT}"
        return {"ok": False, "error": message, "detail": message, "next": "Go on without the circuit; say in one sentence that SparkBench is not installed here."}
    version = bench_version(ctx.state)
    request = {"name": _name(ctx), "board": plan["board"], "date": _today(), "parts": plan["parts"]}
    try:
        result = await sparkbench.design(request, ctx.state.directory, f"circuit-v{version}")
    except sparkbench.SparkBenchFailed as exc:
        message = str(exc)
        return {"ok": False, "error": message, "detail": message, "next": "Go on without the circuit; say in one sentence that SparkBench failed."}
    gaps = plan["gaps"] + result["gaps"]
    if not result["ok"]:
        message = "SparkBench could not build the circuit: " + result["error"]
        return {"ok": False, "error": message, "detail": message, "gaps": gaps}
    for part in result["parts"]:
        if part["anybuild"] is None and part["type"] in ("esp32-devkit", "pi-pico"):
            part["anybuild"] = plan["controller"]
    passed = not any(c["severity"] == "error" for c in result["checks"]) and all(t["pass"] for t in result["tests"]) and not result["sim"]["error"]
    summary = _summary(result, gaps)
    session = ctx.state.session_id
    event = {
        "type": "circuit",
        "version": version,
        "product": str(ctx.state.product or "drone"),
        "name": result["name"],
        "board": result["board"],
        "board_name": result["board_name"],
        "board_proposed": plan["proposed"],
        "ok": passed,
        "summary": summary,
        "parts": result["parts"],
        "nets": result["nets"],
        "wires": result["wires"],
        "files": {kind: f"/files/{session}/{name}" for kind, name in result["files"].items()},
        "checks": result["checks"],
        "tests": result["tests"],
        "sim": result["sim"],
        "bom_total_usd": result["bom_total_usd"],
        "notes": plan["notes"] + result["notes"],
        "gaps": gaps,
        "source": sparkbench.source(),
    }
    await ctx.emit(event)
    problems = [f"{c['severity']}: {c['title']}" for c in result["checks"] if c["severity"] in ("error", "warning")]
    return {
        "ok": True,
        "result": "pass" if passed else "fail",
        "detail": ("pass: " if passed else "fail: ") + summary,
        "cached": result["cached"],
        "board": result["board_name"] + (" (proposed by Mechanic)" if plan["proposed"] else ""),
        "notes": event["notes"],
        "problems": problems,
        "tests": [("pass: " if t["pass"] else "FAIL: ") + t["name"] + ("" if t["pass"] else f" ({t['detail']})") for t in result["tests"]],
        "simulation": f"{result['sim']['status']} after {result['sim']['simulated_s']:g} s" + (f", error: {result['sim']['error']}" if result["sim"]["error"] else ", no error"),
        "gaps": gaps,
        "next": "Say in one sentence what SparkBench found: any error or failed test first, else the pins that matter (notes), then what is not in the circuit (gaps).",
    }


SCHEMA = {
    "name": "circuit_design",
    "description": (
        "SparkBench designs the circuit from the chosen parts: real pins on an ESP32 or Raspberry Pi Pico, a KiCad schematic, a netlist, "
        "a breadboard plan, a parts list and MicroPython firmware, then its design checks, its acceptance tests and 5 s of the firmware in its simulator. "
        "Built-in parts (SG90, LEDs, WS2812 rings, buttons, HC-SR04, MPU-6050 and more) and library parts by part number (MG996R, PCA9685, DRV8833 and more) "
        "are wired; what it has no model for comes back in gaps. Call it after electronics_plan when the build has an ESP32 or Pico. "
        "board (esp32 or pico) only when the parts have no controller: the board is then proposed by Mechanic."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "board": {"type": "string", "enum": list(BOARDS), "description": "Only without a controller among the parts: the board Mechanic proposes."},
        },
    },
}
