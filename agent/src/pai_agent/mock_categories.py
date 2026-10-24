"""Deterministic runs for more product categories through the same tools Claude uses, for runs without a key.

pi-case: a Raspberry Pi 5 case. The Pi at 8 W in a closed PETG box heats the air inside
to about 97 °C, over the 70 °C component limit and the PETG limit. Mechanic opens the lid
for a 40 mm fan, the air exchange brings it under 30 °C, the 27 W supply has headroom.

rc-car: a 2WD RC car chassis. The battery tray sits high, and on a 100 mm track the car
rolls at about 0.95 g, short of the 1.2 g a 3 m/s turn on a 0.75 m radius needs. Mechanic
widens the track to 170 mm, the car now rolls only past 1.6 g, the MuJoCo push still runs.
"""

from __future__ import annotations

import copy
import re

from pai_agent.context import Ctx
from pai_agent.mock_story import _beat, _need, _say
from pai_agent.references import REFERENCES_DIR
from pai_agent.tools.registry import call_tool

# One pattern per category; none of them matches the drone, gripper, stress, training or phone stand prompts.
CATEGORIES = {
    "pi-case": re.compile(r"\b(raspberry|pi ?5|rpi|pcb|electronics?)\b.*\b(case|enclosure|housing|box)\b|\b(case|enclosure|housing)\b.*\b(raspberry|pi ?5|rpi|pcb)\b", re.IGNORECASE),
    "rc-car": re.compile(r"\b(rc|remote[- ]control(led)?|2wd|4wd)\b.*\b(car|vehicle|chassis|buggy|rover)\b|\brobot car\b", re.IGNORECASE),
}


def wants_category(text: str) -> str | None:
    for key, pattern in CATEGORIES.items():
        if pattern.search(text):
            return key
    return None


def _script(category: str, part_id: str) -> str:
    return (REFERENCES_DIR / category / (part_id + ".py")).read_text(encoding="utf-8")


def _pi_spec(quote: str) -> dict:
    return {
        "name": "Raspberry Pi 5 case",
        "function": "Closes a Raspberry Pi 5 in a printed case on the desk, with the USB-C, micro HDMI, USB and Ethernet ports open.",
        "quote": quote,
        "assemblies": [{"id": "case", "name": "Case"}],
        "requirements": [
            {"id": "mass", "text": "Weighs under 300 g with the Pi", "check": "mass", "max": 300, "unit": "g"},
            {"id": "cost", "text": "Parts under 110 €", "check": "cost", "max": 110, "unit": "eur"},
            {"id": "thermal", "text": "Air inside stays under 70 °C with the Pi at 8 W", "check": "thermal", "max": 70, "unit": "deg_c"},
            {"id": "power", "text": "The supply has 1.5× headroom over the peak", "check": "power", "min": 1.5, "unit": "x"},
            {"id": "printable", "text": "Printable parts with STL and STEP", "check": "printable"},
        ],
        "parts": [
            {
                "id": "shell",
                "name": "Bottom shell",
                "kind": "printed",
                "assembly": "case",
                "material": "PETG",
                "description": "Open box 95 x 70 x 27 mm centred on X = Y = 0 with 2 mm walls, four M2.5 standoffs on the Pi 58 x 49 mm hole pattern, cut-outs for USB-C and the two micro HDMI ports on the front wall and for USB and Ethernet on the right wall.",
                "size_mm": [95, 70, 27],
                "params": {"width_mm": 95, "depth_mm": 70, "height_mm": 27, "wall_mm": 2},
            },
            {
                "id": "lid",
                "name": "Lid",
                "kind": "printed",
                "assembly": "case",
                "material": "PETG",
                "description": "Plate 95 x 70 x 2.5 mm on the shell top at Z = 27 with a locating rim; vents_mm2 is the open area cut over the SoC for a 40 mm fan.",
                "size_mm": [95, 70, 5.5],
                "params": {"width_mm": 95, "depth_mm": 70, "thickness_mm": 2.5, "shell_height_mm": 27, "wall_mm": 2, "vents_mm2": 0},
            },
            {"id": "pi", "name": "Raspberry Pi 5", "kind": "bought", "assembly": "case", "category": "controller", "query": "raspberry pi 5", "position_mm": [-3.5, 0, 12.5]},
            {"id": "cooler", "name": "Active cooler", "kind": "bought", "assembly": "case", "category": "fan", "query": "pi 5 active cooler", "position_mm": [-3.5, 0, 22]},
            {"id": "supply", "name": "USB-C supply", "kind": "bought", "category": "power", "query": "pi 5 power supply", "position_mm": [90, 0, 15]},
        ],
    }


def _pi_fan_spec(spec: dict) -> dict:
    """The same case with a 40 mm fan opening in the lid and the fan on it."""

    revised = copy.deepcopy(spec)
    lid = next(p for p in revised["parts"] if p["id"] == "lid")
    # A 38 mm circle: the open area of the fan opening.
    lid["params"]["vents_mm2"] = 1134
    revised["parts"].append({"id": "case-fan", "name": "Case fan", "kind": "bought", "assembly": "case", "category": "fan", "query": "40mm fan", "position_mm": [-4, 0, 34.5]})
    return revised


async def run_pi_case(ctx: Ctx, text: str) -> None:
    await _beat()
    await ctx.step("meeting", "running")
    await _say(
        ctx,
        "denkt",
        "A Pi 5 case. First the spec.",
        "A case for a Raspberry Pi 5. I write the spec: a printed shell and lid, the Pi and its cooler as bought parts, and the checks an engineer runs on electronics in a box: heat and the power budget.",
    )
    spec = _pi_spec(text.strip())
    await _need(ctx, "product_spec", spec)
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": "Checks from your request"})

    await _beat()
    await ctx.step("cad", "running")
    await _say(ctx, "erklaert", "FreeCAD builds shell and lid.", "FreeCAD builds the shell with the port cut-outs and the Pi standoffs, then a closed lid.")
    for part_id in ("shell", "lid"):
        await _need(ctx, "cad_part", {"part_id": part_id, "script": _script("pi-case", part_id), "_generated": False})

    await _beat()
    await ctx.step("teile", "running")
    for part_id, query, select, reason in (
        ("pi", "raspberry pi 5", "rpi5-4gb", "The board the case is for."),
        ("cooler", "pi 5 active cooler", "rpi5-active-cooler", "Keeps the SoC from throttling under load."),
        ("supply", "pi 5 power supply", "usb-c-psu-5v3a", "The official 27 W supply, 5 A at 5.1 V."),
    ):
        await _need(ctx, "part_pick", {"part_id": part_id, "query": query})
        await _need(ctx, "part_pick", {"part_id": part_id, "select_id": select, "reason": reason})
    await _need(ctx, "assemble", {})
    await _need(ctx, "check_totals", {})

    await _beat()
    await ctx.step("simulation", "running")
    power = await _need(ctx, "check_power", {"supply_part_id": "supply", "loads": [{"part_id": "pi"}, {"part_id": "cooler"}]})
    heat = await _need(ctx, "check_thermal", {"enclosure_part_id": "shell", "heat_part_ids": ["pi"], "bbox_mm": [95, 70, 30]})
    if heat["result"] == "fail":
        await _need(ctx, "ui_point_at", {"target": "viewport", "label": "Heat stays inside"})
        await _say(
            ctx,
            "besorgt",
            f"{heat['internal_c']:.0f} °C inside. Too hot.",
            f"Fail. The Pi puts 8 W into a closed PETG box, and only {heat['conductance_w_k']['box']:.2f} W/K leaves through the walls "
            f"(h = 5 W/m²K on {heat['area_m2'] * 1e4:.0f} cm²), so the air inside rises {heat['rise_c']:.0f} K to {heat['internal_c']:.0f} °C, "
            f"over the 70 °C limit and the PETG limit of {heat['material_limit_c']:.0f} °C. The active cooler only stirs that air. "
            "I open the lid for a 40 mm fan that blows the warm air out.",
        )
        await _need(ctx, "product_spec", _pi_fan_spec(spec))
        await _need(ctx, "part_pick", {"part_id": "case-fan", "query": "40mm fan"})
        await _need(ctx, "part_pick", {"part_id": "case-fan", "select_id": "fan-5v-40mm", "reason": "9 m³/h through the lid exchanges the air inside."})
        await _need(ctx, "assemble", {})
        await _need(ctx, "check_totals", {})
        power = await _need(
            ctx, "check_power", {"supply_part_id": "supply", "loads": [{"part_id": "pi"}, {"part_id": "cooler"}, {"part_id": "case-fan"}]}
        )
        heat = await _need(ctx, "check_thermal", {"enclosure_part_id": "shell", "heat_part_ids": ["pi"], "bbox_mm": [95, 70, 30]})
    await _say(
        ctx,
        "freut_sich",
        f"{heat['internal_c']:.0f} °C now.",
        f"The fan moves {heat['conductance_w_k']['fan']:.1f} W/K of air: {heat['internal_c']:.0f} °C inside at 8 W. "
        f"The supply gives {power['supply_limit_a']:.0f} A for a peak of {power['peak_a']:.1f} A, headroom {power['headroom']:.1f}×.",
    )
    await _finish(ctx, "Pi 5 case")


def _car_spec(quote: str) -> dict:
    return {
        "name": "2WD RC car chassis",
        "function": "A small two-wheel-drive RC car: printed chassis and battery tray, two N20 motors on 65 mm wheels, a ball caster, a 2S LiPo, a motor driver and an ESP32-S3 over Wi-Fi.",
        "quote": quote,
        "assemblies": [{"id": "car", "name": "Car"}],
        "requirements": [
            {"id": "mass", "text": "Weighs under 400 g", "check": "mass", "max": 400, "unit": "g"},
            {"id": "cost", "text": "Parts under 90 €", "check": "cost", "max": 90, "unit": "eur"},
            {"id": "rollover", "text": "Takes a 3 m/s turn on a 0.75 m radius (1.2 g) without rolling", "check": "rollover", "min": 1.2, "unit": "g"},
            {"id": "power", "text": "The battery has 2× headroom over the peak", "check": "power", "min": 2, "unit": "x"},
            {"id": "runtime", "text": "Drives for at least 1 h", "check": "runtime", "min": 1, "unit": "h"},
            {"id": "ramp", "text": "Climbs a 10° ramp with 2× torque", "check": "torque", "min": 2, "unit": "x"},
            {"id": "printable", "text": "Printable parts with STL and STEP", "check": "printable"},
        ],
        "parts": [
            {
                "id": "chassis",
                "name": "Chassis plate",
                "kind": "printed",
                "assembly": "car",
                "material": "PETG",
                "description": "Plate 70 mm wide and 150 mm long at Z = 36, 4 mm thick, with an outrigger arm across the rear axle at y = +55 carrying two N20 motor clamps at track_mm between the wheel centres, and the caster holes at the front.",
                "size_mm": [70, 150, 12],
                "params": {"plate_width_mm": 70, "wheelbase_mm": 110, "track_mm": 100, "thickness_mm": 4, "deck_z_mm": 36},
            },
            {
                "id": "tray",
                "name": "Battery tray",
                "kind": "printed",
                "assembly": "car",
                "material": "PETG",
                "description": "Tray 41 x 76 mm for the 2S pack with a strap slot, its floor at tray_z_mm on four posts from the deck top at Z = 40.",
                "size_mm": [41, 76, 38],
                "params": {"length_mm": 76, "width_mm": 41, "wall_mm": 2, "rim_mm": 8, "deck_top_mm": 40, "tray_z_mm": 70},
            },
            {"id": "motors", "name": "Drive motors", "kind": "bought", "qty": 2, "assembly": "car", "category": "motor", "query": "n20 300rpm", "position_mm": [0, 55, 32.5]},
            {"id": "wheels", "name": "Wheels", "kind": "bought", "assembly": "car", "category": "hardware", "query": "65mm wheel", "position_mm": [0, 55, 32.5]},
            {"id": "caster", "name": "Ball caster", "kind": "bought", "assembly": "car", "category": "hardware", "query": "ball caster", "position_mm": [0, -55, 26]},
            {"id": "battery", "name": "Battery", "kind": "bought", "assembly": "car", "category": "battery", "query": "2s lipo", "position_mm": [0, 0, 79]},
            {"id": "driver", "name": "Motor driver", "kind": "bought", "assembly": "car", "category": "driver", "query": "tb6612", "position_mm": [0, 35, 42]},
            {"id": "controller", "name": "Controller", "kind": "bought", "assembly": "car", "category": "controller", "query": "esp32-s3", "position_mm": [0, -35, 45]},
        ],
    }


_TURN = {"speed_mps": 3.0, "turn_radius_m": 0.75}


async def run_rc_car(ctx: Ctx, text: str) -> None:
    await _beat()
    await ctx.step("meeting", "running")
    await _say(
        ctx,
        "denkt",
        "An RC car. First the spec.",
        "A small 2WD RC car. I write the spec with what a vehicle engineer checks: roll-over in a fast turn, the battery's current and runtime, and the motor torque on a ramp.",
    )
    await _need(ctx, "product_spec", _car_spec(text.strip()))
    await _need(ctx, "ui_point_at", {"target": "requirements", "label": "Checks from your request"})

    await _beat()
    await ctx.step("cad", "running")
    await _say(ctx, "erklaert", "FreeCAD builds chassis and tray.", "FreeCAD builds the chassis plate with the motor clamps, then the battery tray on its posts.")
    for part_id in ("chassis", "tray"):
        await _need(ctx, "cad_part", {"part_id": part_id, "script": _script("rc-car", part_id), "_generated": False})

    await _beat()
    await ctx.step("teile", "running")
    for part_id, query, select, reason in (
        ("motors", "n20 300rpm", "motor-n20-300rpm", "Small metal-gear motors, 0.06 N m stall."),
        ("wheels", "65mm wheel", "wheels-65mm-pair", "Rubber grip, 65 mm for about 1 m/s per 300 rpm."),
        ("caster", "ball caster", "ball-caster", "The third contact at the front."),
        ("battery", "2s lipo", "lipo-2s-1500", "7.4 V, 1500 mAh, 25C."),
        ("driver", "tb6612", "tb6612-driver", "Two channels for the two motors."),
        ("controller", "esp32-s3", "esp32-s3-devkit", "Wi-Fi remote control from a phone."),
    ):
        await _need(ctx, "part_pick", {"part_id": part_id, "query": query})
        await _need(ctx, "part_pick", {"part_id": part_id, "select_id": select, "reason": reason})
    await _need(ctx, "assemble", {})
    await _need(ctx, "check_totals", {})

    await _beat()
    await ctx.step("simulation", "running")
    loads = [
        {"part_id": "motors", "name": "Two N20 motors", "power_w": 2.4, "duty": 0.6, "peak_factor": 3},
        {"part_id": "controller"},
        {"part_id": "driver"},
    ]
    power = await _need(ctx, "check_power", {"supply_part_id": "battery", "loads": loads})
    torque = await _need(ctx, "check_torque", {"actuator_part_id": "motors", "required_torque_nm": 0.0072})
    roll = await _need(ctx, "check_rollover", dict(_TURN))
    if roll["result"] == "fail":
        await _need(ctx, "ui_point_at", {"target": "viewport", "label": "Rolls in the turn"})
        await _say(
            ctx,
            "besorgt",
            f"Rolls at {roll['max_lateral_g']:.2f} g.",
            f"Fail. The battery tray sits high, the centre of mass is {roll['com_height_mm']:.0f} mm up, and on a {roll['track_mm']:.0f} mm track "
            f"the static stability factor T / 2h is {roll['ssf']:.2f}: it rolls at {roll['max_lateral_g']:.2f} g. "
            f"A 3 m/s turn on 0.75 m needs v² / (r g) = {roll['turn_g']:.2f} g. I widen the track to 170 mm; every check runs again.",
        )
        await _need(ctx, "cad_update", {"part_id": "chassis", "params": {"track_mm": 170}})
        roll = ctx.state.checks.get("rollover", roll)
    sim = await call_tool(ctx, "simulate_assembly", {"mode": "push", "force_n": 1.0})
    await _say(
        ctx,
        "freut_sich",
        f"Rolls only past {roll['max_lateral_g']:.2f} g now.",
        f"On a {roll['track_mm']:.0f} mm track it rolls only past {roll['max_lateral_g']:.2f} g, the turn needs {roll['turn_g']:.2f} g. "
        f"The pack gives {power['supply_limit_a']:.0f} A for {power['peak_a']:.1f} A peak and runs {power.get('runtime_h', 0):.1f} h; "
        f"the motors have {torque['safety']:.1f}× the torque for the 10° ramp. " + str(sim.get("summary") or ""),
    )
    await _finish(ctx, "RC car")


async def _finish(ctx: Ctx, name: str) -> None:
    await _beat()
    await ctx.step("render", "running")
    await call_tool(ctx, "blender_render", {})

    await _beat()
    await ctx.step("stueckliste", "running")
    totals = await _need(ctx, "check_totals", {})
    bom = await _need(ctx, "bom_build", {})
    await call_tool(ctx, "print_prep", {})
    await ctx.step("stueckliste", "done")
    ctx.state.finished = True
    await _say(
        ctx,
        "freut_sich",
        f"{name} done: {totals['mass_g']:.0f} g, {bom['total_eur']:.2f} €.",
        f"Done: {totals['mass_g']:.0f} g and {bom['total_eur']:.2f} € in parts, every requirement met. "
        "Drag the sliders in the CAD tab and FreeCAD rebuilds it, then every check runs again.",
    )


RUNS = {"pi-case": run_pi_case, "rc-car": run_rc_car}
# The spec name of each run, so a follow-up on a finished build does not start it again.
NAMES = {"pi-case": "Raspberry Pi 5 case", "rc-car": "2WD RC car chassis"}
