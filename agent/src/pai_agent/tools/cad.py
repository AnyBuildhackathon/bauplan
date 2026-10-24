"""Parametric whoop frame. arm_length is center to motor shaft, motor_spacing is the bolt-circle diameter.

FreeCAD runs first when freecadcmd is on the machine: it builds the whole hero drone around the
frame (freecad/frame_build.py) from the parts chosen so far. CadQuery is the frame-only fallback.
"""

from __future__ import annotations

import asyncio
import logging
import math
import subprocess
import threading
from pathlib import Path

from pai_agent import cache, freecad_run
from pai_agent.context import Ctx
from pai_agent.freecad_run import FreeCADFailed, build_in_gui, build_with_freecad, ensure_gui, find_freecadcmd
from pai_agent.mesh_export import stl_to_glb
from pai_agent.paths import AGENT_ROOT, REPO_ROOT

log = logging.getLogger(__name__)

_CARBON_G_PER_MM3 = 1.55 / 1000.0
_PROP_GAP_MM = 4.0
DEFAULT_PARAMS = {
    "arm_length_mm": 42.5,
    "thickness_mm": 2.0,
    "motor_spacing_mm": 6.6,
}
_LIMITS = {
    "arm_length_mm": (20.0, 80.0, "mm"),
    "thickness_mm": (1.2, 6.0, "mm"),
    "motor_spacing_mm": (4.0, 16.0, "mm"),
}
_FRAME_TREE = {
    "id": "frame",
    "label": "Frame",
    "children": [
        {"id": "hub", "label": "Hub", "children": []},
        {"id": "arms", "label": "Arms", "children": []},
        {"id": "pads", "label": "Motor pads", "children": []},
    ],
}
# The pack's label colour in the model, so a battery swap shows at a glance.
_BATTERY_LABELS = {"tattu-rline-1s-550": "#e8c21a", "betafpv-lava-1s-680": "#8fd14f", "tattu-funfly-4s-1300": "#d61f3c"}
_BATTERY_LABEL = "#1f9fd6"


def _assembly(state) -> dict:
    """The chosen parts at catalog size, for the parts FreeCAD places around the frame."""

    out: dict = {}
    propeller = state.selected.get("propeller") or {}
    if propeller.get("diameter_mm"):
        out["prop_mm"] = float(propeller["diameter_mm"])
    if propeller.get("pitch_in"):
        out["prop_pitch_in"] = float(propeller["pitch_in"])
    if propeller.get("blades"):
        out["prop_blades"] = int(propeller["blades"])
    motor = state.selected.get("motor") or {}
    if motor.get("height_mm"):
        out["motor_height_mm"] = float(motor["height_mm"])
    if motor.get("kv"):
        out["motor_kv"] = float(motor["kv"])
    if motor.get("size"):
        out["motor_size"] = str(motor["size"])
    if motor.get("diameter_mm"):
        out["motor_diameter_mm"] = float(motor["diameter_mm"])
    if motor.get("shaft_mm"):
        out["shaft_mm"] = float(motor["shaft_mm"])
    camera = state.selected.get("camera") or {}
    if camera.get("size_mm"):
        out["camera_mm"] = float(camera["size_mm"])
    battery = state.selected.get("battery") or {}
    if all(battery.get(key) for key in ("length_mm", "width_mm", "height_mm")):
        out["battery_mm"] = [float(battery[key]) for key in ("length_mm", "width_mm", "height_mm")]
        out["battery_label"] = _BATTERY_LABELS.get(str(battery.get("id")), _BATTERY_LABEL)
    return out


def _tree(state, assembly: bool) -> list[dict]:
    if not assembly:
        return [_FRAME_TREE]
    names = {category: part.get("name") for category, part in state.selected.items()}

    def leaf(node_id: str, label: str, category: str | None = None) -> dict:
        name = names.get(category) if category else None
        return {"id": node_id, "label": label + (" · " + name if name else ""), "children": []}

    frame = {
        "id": "frame",
        "label": "Printed parts",
        "children": [
            {"id": "plate", "label": "X-frame", "children": []},
            {"id": "canopy", "label": "Canopy with antenna tube", "children": []},
            {"id": "holder", "label": "Battery holder", "children": []},
        ],
    }
    return [
        {
            "id": "drone",
            "label": "Drone",
            "children": [
                frame,
                leaf("motors", "Motors ×4", "motor"),
                leaf("propellers", "Propellers ×4", "propeller"),
                leaf("flight_controller", "Flight controller stack", "flight_controller"),
                leaf("camera", "FPV camera"),
                leaf("battery", "Battery and strap", "battery"),
                leaf("antenna", "Receiver antenna"),
            ],
        }
    ]


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message}


def _number(args: dict, key: str) -> float | None:
    try:
        return float(args[key])
    except (KeyError, TypeError, ValueError):
        return None


def build_frame(arm_length_mm: float, thickness_mm: float, motor_spacing_mm: float):
    import cadquery as cq

    arm_width = 6.0
    hub_radius = 20.0
    pad_radius = 6.0
    bolt_radius = motor_spacing_mm / 2.0

    def arm():
        return cq.Workplane("XY").box(
            arm_length_mm,
            arm_width,
            thickness_mm,
            centered=(False, True, False),
        )

    frame = arm()
    for angle in (90, 180, 270):
        frame = frame.union(arm().rotate((0, 0, 0), (0, 0, 1), angle))
    frame = frame.union(cq.Workplane("XY").circle(hub_radius).extrude(thickness_mm))
    for angle in (0, 90, 180, 270):
        radians = math.radians(angle)
        frame = frame.union(
            cq.Workplane("XY")
            .center(arm_length_mm * math.cos(radians), arm_length_mm * math.sin(radians))
            .circle(pad_radius)
            .extrude(thickness_mm)
        )

    cutters = cq.Workplane("XY")
    first = True
    holes: list[tuple[float, float, float]] = [(0.0, 0.0, 2.2)]
    for sign_x in (-1, 1):
        for sign_y in (-1, 1):
            holes.append((13.0 * sign_x, 13.0 * sign_y, 1.1))
    for angle in (0, 90, 180, 270):
        radians = math.radians(angle)
        cx = arm_length_mm * math.cos(radians)
        cy = arm_length_mm * math.sin(radians)
        holes.append((cx, cy, 1.0))
        for index in range(3):
            hole_angle = math.radians(angle + index * 120)
            holes.append(
                (
                    cx + bolt_radius * math.cos(hole_angle),
                    cy + bolt_radius * math.sin(hole_angle),
                    0.8,
                )
            )
    for x_mm, y_mm, radius in holes:
        cutter = (
            cq.Workplane("XY")
            .center(x_mm, y_mm)
            .circle(radius)
            .extrude(thickness_mm + 2)
            .translate((0, 0, -1))
        )
        cutters = cutter if first else cutters.union(cutter)
        first = False
    frame = frame.cut(cutters)
    return frame


def export_frame(frame, path: Path) -> float:
    from cadquery import exporters

    path.parent.mkdir(parents=True, exist_ok=True)
    exporters.export(frame, str(path))
    volume_mm3 = float(frame.val().Volume())
    return volume_mm3 * _CARBON_G_PER_MM3


def apply_param_body(current: dict, body: dict) -> dict:
    params = dict(DEFAULT_PARAMS)
    params.update(current or {})
    if "name" in body or "value" in body:
        name = body.get("name")
        if name not in _LIMITS or "value" not in body:
            raise ValueError("name and value must name a known dimension.")
        params[str(name)] = float(body["value"])
        return params
    for key in _LIMITS:
        if key in body:
            params[key] = float(body[key])
    return params


def _cadquery_bundle(directory: Path, params: dict) -> float:
    frame = build_frame(params["arm_length_mm"], params["thickness_mm"], params["motor_spacing_mm"])
    directory.mkdir(parents=True, exist_ok=True)
    mass_g = export_frame(frame, directory / "frame.stl")
    export_frame(frame, directory / "frame.step")
    stl_to_glb(directory / "frame.stl", directory / "frame.glb")
    return mass_g


def _param_payload(params: dict) -> dict:
    payload = {}
    for name, (low, high, unit) in _LIMITS.items():
        payload[name] = {"value": params[name], "min": low, "max": high, "unit": unit}
    return payload


def _file_url(session_id: str, name: str, build: int) -> str:
    # The query changes with every build, so a browser never shows a cached older part.
    return "/files/" + session_id + "/" + name + "?build=" + str(build)


# What a headless frame build leaves behind; the GUI build is never cached, the room watches it.
_FRAME_FILES = ("frame.stl", "frame.step", "frame.glb", "frame.FCStd", "drone.step")


def _frame_cache_key(build_params: dict) -> str:
    code = sorted((AGENT_ROOT / "freecad").glob("*.py")) + [Path(__file__), Path(freecad_run.__file__)]
    return cache.key("frame", build_params, cache.tool_version(find_freecadcmd()), [cache.digest(path) for path in code])


async def cad_frame(ctx: Ctx, args: dict) -> dict:
    arm_length = _number(args, "arm_length_mm")
    thickness = _number(args, "thickness_mm")
    motor_spacing = _number(args, "motor_spacing_mm")
    if arm_length is None or thickness is None or motor_spacing is None:
        return _fail("arm_length_mm, thickness_mm and motor_spacing_mm must be numbers.")
    if not 20 <= arm_length <= 80:
        return _fail("arm_length_mm must be between 20 and 80. That is the distance from the center to the motor shaft.")
    if not 1.2 <= thickness <= 6:
        return _fail("thickness_mm must be between 1.2 and 6.")
    if not 4 <= motor_spacing <= 16:
        return _fail("motor_spacing_mm is the bolt circle of the motor screws and must be between 4 and 16.")

    propeller = ctx.state.selected.get("propeller")
    clearance = None
    if propeller and propeller.get("diameter_mm"):
        # Neighbouring motors sit arm * sqrt(2) apart; two propeller radii must fit with a gap.
        clearance = arm_length * math.sqrt(2) - float(propeller["diameter_mm"])
        if clearance < _PROP_GAP_MM:
            needed = (float(propeller["diameter_mm"]) + _PROP_GAP_MM) / math.sqrt(2)
            return _fail(
                "At a "
                + f"{arm_length:.0f}"
                + " mm arm the motors stand "
                + f"{arm_length * math.sqrt(2):.1f}"
                + " mm apart and the "
                + f"{float(propeller['diameter_mm']):.0f}"
                + " mm props touch. The arm needs at least "
                + f"{math.ceil(needed):.0f}"
                + " mm."
            )

    params = {
        "arm_length_mm": arm_length,
        "thickness_mm": thickness,
        "motor_spacing_mm": motor_spacing,
        "prop_clearance_mm": round(clearance, 1) if clearance is not None else None,
    }
    directory = Path(ctx.state.directory)
    for stale in ("frame.stl", "frame.step", "frame.glb", "drone.step", "view.png"):
        (directory / stale).unlink(missing_ok=True)
    build_params = {**params, **_assembly(ctx.state)}
    source = "freecad"
    viewed = False
    loop = asyncio.get_running_loop()
    stop = threading.Event()

    def progress(detail: str) -> None:
        # A reset cancels the run but not this thread; stop before the next step instead of
        # writing into the new session.
        if stop.is_set():
            raise FreeCADFailed("cancelled")
        asyncio.run_coroutine_threadsafe(
            ctx.emit({"type": "tool", "name": "cad_frame", "status": "running", "detail": detail}), loop
        )

    mass_g: float | None = None
    if await asyncio.to_thread(ensure_gui):
        try:
            mass_g = await asyncio.to_thread(build_in_gui, directory, build_params, len(ctx.state.versions) + 1, progress)
            viewed = True
        except asyncio.CancelledError:
            stop.set()
            raise
        except (FreeCADFailed, OSError, TimeoutError, ValueError) as exc:
            log.warning("FreeCAD-Fenster fällt auf headless zurück: %s", exc)
            await ctx.emit({"type": "tool", "name": "cad_frame", "status": "running", "detail": "FreeCAD window stalled, continuing in the background"})
    cache_entry = _frame_cache_key(build_params) if mass_g is None else None
    if cache_entry is not None:
        hit = cache.restore("frames", cache_entry, {}) or {}
        if hit and cache.restore("frames", cache_entry, {name: directory / name for name in hit["files"]}) is not None:
            mass_g = float(hit["mass_g"])
            source = str(hit["source"])
            cache_entry = None
    if mass_g is None:
        try:
            mass_g = await asyncio.to_thread(build_with_freecad, directory, build_params)
        except (FreeCADFailed, OSError, TimeoutError, ValueError, subprocess.TimeoutExpired) as exc:
            log.info("FreeCAD fällt auf CadQuery zurück: %s", exc)
            source = "cadquery"
            try:
                mass_g = await asyncio.to_thread(_cadquery_bundle, directory, params)
            except Exception as fallback:
                message = "CadQuery could not build the frame: " + str(fallback)
                return _fail(message)
    stl = directory / "frame.stl"
    if not stl.is_file() or stl.stat().st_size < 100 or not (directory / "frame.step").is_file():
        return _fail("STL or STEP is missing.")
    if not (directory / "frame.glb").is_file():
        await asyncio.to_thread(stl_to_glb, stl, directory / "frame.glb")
    if cache_entry is not None and not viewed:
        files = {name: directory / name for name in _FRAME_FILES if (directory / name).is_file()}
        cache.store("frames", cache_entry, files, {"files": list(files), "mass_g": mass_g, "source": source})

    mass_g = round(mass_g, 2)
    ctx.state.frame_mass_g = mass_g
    ctx.state.cad_params = params
    relative = stl.relative_to(REPO_ROOT).as_posix()
    ctx.state.stl_path = relative
    session_id = ctx.state.session_id
    ctx.state.cad_builds += 1
    build = ctx.state.cad_builds
    view_url = _file_url(session_id, "view.png", build) if viewed and (directory / "view.png").is_file() else None
    await ctx.emit(
        {
            "type": "cad",
            "source": source,
            "tree": _tree(ctx.state, source == "freecad"),
            "params": _param_payload(params),
            "glb_url": _file_url(session_id, "frame.glb", build),
            "stl_url": _file_url(session_id, "frame.stl", build),
            "step_url": _file_url(session_id, "frame.step", build),
            "view_png_url": view_url,
        }
    )
    where = "FreeCAD window" if viewed else ("FreeCAD headless" if source == "freecad" else "CadQuery")
    detail = where + ", " + f"{mass_g:.1f}" + " g carbon, STL and STEP"
    return {
        "ok": True,
        "detail": detail,
        "source": source,
        "stl_path": relative,
        "mass_g": mass_g,
        "arm_length_mm": arm_length,
        "thickness_mm": thickness,
        "motor_spacing_mm": motor_spacing,
        "prop_clearance_mm": round(clearance, 1) if clearance is not None else None,
    }
