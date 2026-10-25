"""Look-alike maker parts: boards, servos, DC, geared and stepper motors, wheels, cells, fans, hardware.

Feature pieces the checks measure: `hole_N` (plated mounting holes) on boards, `mount_hole_N` on motor
faces and servo tabs, `shaft`, `tyre`, `outer_ring`/`inner_ring` on a bearing, `body` everywhere.
Boards are data: an outline, holes and a list of components with positions, so a drawing's numbers go
straight in and anything the drawing does not give is listed as styled in the manifest.
"""

from __future__ import annotations

import math

import cadquery as cq

from .model import Model
from .shapes import FINISH, box, cyl, finish, polar, rounded_plate, tube, wire_path

PCB = {"green": "pcb_green", "blue": "pcb_blue", "black": "pcb_black", "red": "pcb_red", "purple": "pcb_purple", "white": "pcb_white"}


def _pcb_finish(name: str):
    return FINISH[PCB[name]] if name in PCB else finish(name, 0.0, 0.45)


def _rot(work, angle: float, x: float, y: float):
    return work.rotate((x, y, 0), (x, y, 1), angle) if angle else work


def _header(n: int, rows: int, pitch: float, x: float, y: float, z: float, along: str, female: bool, pin_up: float, pin_down: float):
    """A 0.1 in header: plastic body and square pins, `n` pins per row along X or Y."""

    length = n * pitch
    width = rows * pitch
    lx, ly = (length, width) if along == "x" else (width, length)
    body_h = 8.5 if female else 2.5
    body = box(lx, ly, body_h, (x, y, z))
    pins = None
    for i in range(n):
        for j in range(rows):
            u = (i - (n - 1) / 2) * pitch
            v = (j - (rows - 1) / 2) * pitch
            px, py = (x + u, y + v) if along == "x" else (x + v, y + u)
            if female:
                body = body.cut(box(1.0, 1.0, 2.0, (px, py, z + body_h - 1.9)))
                pin = box(0.64, 0.64, pin_down, (px, py, z - pin_down))
            else:
                pin = box(0.64, 0.64, pin_up + pin_down, (px, py, z - pin_down))
            pins = pin if pins is None else pins.union(pin)
    return body, pins


def board(p: dict) -> Model:
    """A printed circuit board with its holes and parts, from an outline and a component list."""

    m = Model(p["id"])
    length, width = p["length_mm"], p["width_mm"]
    t = p.get("pcb_mm", 1.6)
    under = p.get("under_mm", 0.0)
    z0 = under
    shape = p.get("outline", "rect")
    if shape == "ring":
        pcb = tube(length / 2, p["inner_d_mm"] / 2, t, (0, 0, z0))
    elif shape == "disc":
        pcb = cyl(length / 2, t, (0, 0, z0))
    else:
        pcb = rounded_plate(length, width, t, p.get("corner_mm", 0.8), (0, 0, z0))
    for x, y, d in p.get("holes", []):
        pcb = pcb.cut(cyl(d / 2, t + 0.4, (x, y, z0 - 0.2)))
    for cx, cy, cw, cl in p.get("cutouts", []):
        pcb = pcb.cut(box(cw, cl, t + 0.4, (cx, cy, z0 - 0.2)))
    m.add("board", pcb, _pcb_finish(p.get("pcb_color", "green")))
    for i, (x, y, d) in enumerate(p.get("holes", []), 1):
        ring = tube(d / 2 + max(0.35, d * 0.3), d / 2, t + 0.06, (x, y, z0 - 0.03))
        m.add(f"hole_{i}", ring, FINISH["gold"] if p.get("plated", True) else _pcb_finish(p.get("pcb_color", "green")))
    for index, c in enumerate(p.get("parts", []), 1):
        _component(m, c, index, z0, t)
    return m


def _component(m: Model, c: dict, index: int, z0: float, t: float) -> None:
    kind = c["k"]
    x, y = c.get("x", 0.0), c.get("y", 0.0)
    w, l = c.get("w", 3.0), c.get("l", 3.0)
    h = c.get("h", 1.0)
    angle = c.get("rot", 0.0)
    bottom = c.get("side") == "bottom"
    z = (z0 - h if bottom else z0 + t) + c.get("dz", 0.0)
    name = c.get("name", f"{kind}_{index}")
    colour = c.get("color")
    if kind in ("chip", "box"):
        piece = box(w, l, h, (x, y, z), fillet=c.get("fillet", 0.0))
        m.add(name, _rot(piece, angle, x, y), finish(colour, 0.0, 0.45) if colour else FINISH["chip"])
        if kind == "chip" and w > 2.5 and c.get("dot", True):
            dot = cyl(min(w, l) * 0.06, 0.02, (x - w * 0.32, y + l * 0.32, z + h))
            m.add(name + "_dot", _rot(dot, angle, x, y), FINISH["white_plastic"])
    elif kind == "can":
        m.add(name, _rot(box(w, l, h, (x, y, z)), angle, x, y), FINISH["tin"])
    elif kind == "cyl":
        piece = cyl(c["d"] / 2, h, (x, y, z))
        m.add(name, piece, finish(colour, c.get("metal", 0.0), 0.4) if colour else FINISH["aluminium"])
    elif kind == "transducer":
        outer = tube(c["d"] / 2, c["d"] / 2 - 0.5, h, (x, y, z))
        m.add(name, outer, FINISH["aluminium"])
        m.add(name + "_mesh", cyl(c["d"] / 2 - 0.5, h - 0.6, (x, y, z)), finish("#2b2b2b", 0.2, 0.9))
    elif kind == "header":
        body, pins = _header(c["n"], c.get("rows", 1), c.get("pitch", 2.54), x, y, z0 + t if not bottom else z0 - 2.5, c.get("along", "x"), False, c.get("pin_up", 6.0), c.get("pin_down", 0.0 if bottom else 0.0))
        if bottom:
            body, pins = _header(c["n"], c.get("rows", 1), c.get("pitch", 2.54), x, y, z0 - 2.5, c.get("along", "x"), False, 2.5 + t + 0.6, 6.0)
        m.add(name, body, FINISH["black_plastic"])
        m.add(name + "_pins", pins, FINISH["gold"])
    elif kind == "ra_header":
        n = c["n"]
        pitch = c.get("pitch", 2.54)
        body = box(n * pitch, 2.5, 2.5, (x, y, z0 - 2.5))
        pins = None
        for i in range(n):
            u = x + (i - (n - 1) / 2) * pitch
            pin = box(0.64, c.get("pin_len", 8.0), 0.64, (u, y - c.get("pin_len", 8.0) / 2, z0 - 1.57))
            pins = pin if pins is None else pins.union(pin)
        m.add(name, body, FINISH["black_plastic"])
        m.add(name + "_pins", pins, FINISH["gold"])
    elif kind == "socket":
        body, pins = _header(c["n"], c.get("rows", 1), c.get("pitch", 2.54), x, y, z0 + t, c.get("along", "x"), True, 0.0, 0.01)
        m.add(name, body, FINISH["black_plastic"])
    elif kind in ("usb_c", "micro_usb", "usb_a", "rj45", "hdmi", "barrel", "mmcx"):
        size = {"usb_c": (7.35, 8.9, 3.2), "micro_usb": (5.6, 7.5, 2.7), "usb_a": (14.5, 17.5, 15.6), "rj45": (16.0, 21.5, 13.5), "hdmi": (6.5, 7.5, 3.2), "barrel": (9.0, 14.0, 11.0), "mmcx": (3.0, 3.0, 3.6)}[kind]
        sw, sl, sh = c.get("w", size[0]), c.get("l", size[1]), c.get("h", size[2])
        if kind == "usb_c":
            shell = box(sw, sl, sh, (x, y, z), fillet=sh * 0.45).cut(box(sw - 0.8, sl + 1, sh - 0.8, (x, y, z + 0.4), fillet=(sh - 0.8) * 0.45))
        elif kind == "mmcx":
            shell = cyl(1.5, sh, (x, y, z))
        else:
            shell = box(sw, sl, sh, (x, y, z))
            if kind in ("usb_a", "rj45", "hdmi", "micro_usb"):
                shell = shell.cut(box(sw * 0.8, 1.2, sh * 0.6, (x, y + sl / 2 - 0.5, z + sh * 0.2)).rotate((x, y, 0), (x, y, 1), 0))
        m.add(name, _rot(shell, angle, x, y), finish("#2e2e2e", 0.0, 0.6) if kind == "barrel" else FINISH["tin"])
    elif kind in ("jst_ph", "jst_sh", "jst_xh", "jst_gh"):
        pitch = {"jst_ph": 2.0, "jst_sh": 1.0, "jst_xh": 2.5, "jst_gh": 1.25}[kind]
        n = c.get("n", 2)
        bw = n * pitch + (2.0 if kind != "jst_sh" else 2.0)
        depth = {"jst_ph": 4.5, "jst_sh": 2.9, "jst_xh": 5.75, "jst_gh": 4.25}[kind]
        height = {"jst_ph": 6.0, "jst_sh": 4.25, "jst_xh": 7.0, "jst_gh": 4.25}[kind]
        if c.get("right_angle", True):
            depth, height = height, depth
        shell = box(bw, depth, height, (x, y, z)).cut(box(bw - 1.0, depth * 0.7, height - 0.9, (x, y + depth * 0.2, z + 0.5)))
        m.add(name, _rot(shell, angle, x, y), FINISH["white_plastic"] if kind != "jst_sh" or c.get("white", True) else FINISH["black_plastic"])
    elif kind == "terminal":
        n = c.get("n", 2)
        pitch = c.get("pitch", 5.0)
        body = box(n * pitch, 7.5, 10.0, (x, y, z))
        for i in range(n):
            u = x + (i - (n - 1) / 2) * pitch
            body = body.cut(cyl(1.6, 1.0, (u, y, z + 9.1)))
        m.add(name, _rot(body, angle, x, y), finish(colour or "#2f6fd1", 0.0, 0.5))
        screws = None
        for i in range(n):
            u = x + (i - (n - 1) / 2) * pitch
            s = cyl(1.5, 0.9, (u, y, z + 9.0)).cut(box(3.2, 0.5, 0.6, (u, y, z + 9.4)))
            screws = s if screws is None else screws.union(s)
        m.add(name + "_screws", _rot(screws, angle, x, y), FINISH["steel"])
    elif kind == "pot":
        body = box(6.5, 6.5, 4.5, (x, y, z))
        m.add(name, body, finish("#2a5bd7", 0.0, 0.5))
        m.add(name + "_screw", cyl(1.4, 0.6, (x, y, z + 4.5)).cut(box(2.6, 0.4, 0.5, (x, y, z + 4.75))), FINISH["brass"])
    elif kind == "trimmer":
        m.add(name, cyl(c.get("d", 3.0) / 2, h, (x, y, z)).cut(box(c.get("d", 3.0) * 0.8, 0.3, 0.2, (x, y, z + h - 0.15))), FINISH["aluminium"])
    elif kind == "elcap":
        d = c.get("d", 6.3)
        body = cyl(d / 2, h, (x, y, z))
        m.add(name, body, finish(colour or "#1e1e1e", 0.3, 0.35))
        m.add(name + "_top", cyl(d / 2 * 0.92, 0.05, (x, y, z + h)), FINISH["aluminium"])
    elif kind == "inductor":
        m.add(name, box(w, l, h, (x, y, z), fillet=0.4), finish("#3a3a3a", 0.3, 0.5))
    elif kind == "led":
        m.add(name, _rot(box(w, l, h, (x, y, z)), angle, x, y), FINISH["white_plastic"])
        m.add(name + "_lens", _rot(cyl(min(w, l) * 0.35, 0.05, (x, y, z + h)), angle, x, y), finish(colour or "#f2e9a0", 0.0, 0.2))
    elif kind == "button":
        m.add(name, box(w, l, h * 0.6, (x, y, z)), FINISH["tin"])
        m.add(name + "_cap", cyl(min(w, l) * 0.3, h * 0.4, (x, y, z + h * 0.6)), FINISH["black_plastic"])
    elif kind == "crystal":
        m.add(name, _rot(box(w, l, h, (x, y, z), fillet=min(w, l) * 0.45), angle, x, y), FINISH["tin"])
    elif kind == "display":
        m.add(name, box(w, l, h, (x, y, z)), finish("#141618", 0.3, 0.15))
        aw, al = c.get("active", (w * 0.9, l * 0.7))
        m.add(name + "_active", box(aw, al, 0.02, (x + c.get("ax", 0.0), y + c.get("ay", 0.0), z + h)), finish("#0b1d2e", 0.4, 0.05))
    elif kind == "heatsink":
        fins = int(c.get("fins", 7))
        base = box(w, l, h * 0.25, (x, y, z))
        for i in range(fins):
            u = x + (i - (fins - 1) / 2) * (w / fins)
            base = base.union(box(w / fins * 0.45, l, h * 0.75, (u, y, z + h * 0.25)))
        m.add(name, _rot(base, angle, x, y), finish(colour or "#1f1f22", 0.7, 0.45))
    elif kind == "dome":
        d = c["d"]
        dome = cq.Workplane("XY").sphere(d / 2).intersect(box(d + 1, d + 1, d / 2 + 0.1)).translate((x, y, z + c.get("lift", 0.0)))
        if c.get("lift"):
            dome = dome.union(cyl(d / 2, c["lift"], (x, y, z)))
        m.add(name, dome, finish(colour, 0.0, 0.3) if colour else FINISH["fresnel"])
    elif kind == "lens":
        d = c["d"]
        m.add(name, cyl(d / 2, h, (x, y, z)), FINISH["anodised_black"])
        m.add(name + "_glass", cyl(d * 0.3, 0.1, (x, y, z + h)), FINISH["lens"])
    elif kind == "antenna_trace":
        m.add(name, box(w, l, 0.04, (x, y, z)), FINISH["gold"])
    elif kind == "pads":
        n = c.get("n", 4)
        pitch = c.get("pitch", 2.54)
        for i in range(n):
            u = (i - (n - 1) / 2) * pitch
            px, py = (x + u, y) if c.get("along", "x") == "x" else (x, y + u)
            m.add(f"{name}_{i + 1}", cyl(c.get("d", 1.6) / 2, 0.05, (px, py, z)), FINISH["gold"])
    elif kind == "fan":
        d = c.get("d", w)
        ring = tube(d / 2, d / 2 - 0.8, h, (x, y, z))
        m.add(name + "_shroud", ring, FINISH["black_plastic"])
        m.add(name + "_hub", cyl(d * 0.2, h * 0.9, (x, y, z)), FINISH["black_plastic"])
        blades = None
        for i in range(c.get("blades", 9)):
            blade = box(d * 0.28, 0.5, h * 0.7, (d * 0.34, 0, z + h * 0.1)).rotate((0, 0, 0), (1, 0, 0), 30).rotate((0, 0, 0), (0, 0, 1), 360.0 * i / c.get("blades", 9)).translate((x, y, 0))
            blades = blade if blades is None else blades.union(blade)
        m.add(name + "_blades", blades, FINISH["black_plastic"])
    elif kind == "wire":
        points = [tuple(pt) for pt in c["path"]]
        m.add(name, wire_path(points, c.get("r", 0.5)), FINISH[c.get("finish", "wire_black")])
    else:
        raise ValueError("Unknown board component kind: " + kind)


def servo(p: dict) -> Model:
    """A hobby servo: case, mounting tabs with holes, gear tower, spline, one-arm horn and cable.

    Measured from the maker's drawing: body length and width, tab span, height of the tab underside,
    overall height to the top of the horn, and the tab hole spacing when the drawing gives it.
    """

    m = Model(p["id"])
    length, width = p["length_mm"], p["width_mm"]
    overall = p["overall_height_mm"]
    tab_bottom = p["tab_bottom_mm"]
    tab_span = p["tab_span_mm"]
    tab_t = p.get("tab_t_mm", 2.5 if length > 30 else 1.6)
    case_h = p.get("case_height_mm", tab_bottom + tab_t + (overall - tab_bottom) * 0.35)
    hole_spacing = p.get("hole_spacing_mm", (length + tab_span) / 2)
    hole_d = p.get("hole_d_mm", 2.0 if length < 30 else 4.5)
    shaft_x = length / 2 - p.get("shaft_offset_mm", width / 2)
    horn_t = 1.6 if length < 30 else 2.4
    spline_d = p.get("spline_d_mm", 4.8 if length < 30 else 5.9)
    tower_h = (overall - case_h - horn_t) * 0.55
    colour = finish(p.get("color", "#2457b5"), 0.0, 0.45)
    m.add("body", box(length, width, tab_bottom, fillet=0.4), colour)
    tabs = box(tab_span, width, tab_t, (0, 0, tab_bottom))
    for sx in (-1, 1):
        tabs = tabs.cut(cyl(hole_d / 2, tab_t + 0.4, (sx * hole_spacing / 2, 0, tab_bottom - 0.2)))
        slot_len = tab_span / 2 - hole_spacing / 2 + 0.1
        tabs = tabs.cut(box(slot_len, max(0.8, hole_d * 0.45), tab_t + 0.4, (sx * (hole_spacing / 2 + slot_len / 2), 0, tab_bottom - 0.2)))
    m.add("tabs", tabs, colour)
    for i, sx in enumerate((-1, 1), 1):
        m.add(f"mount_hole_{i}", tube(hole_d / 2, hole_d / 2 - 0.15, tab_t, (sx * hole_spacing / 2, 0, tab_bottom)), colour)
    m.add("body_top", box(length, width, case_h - tab_bottom - tab_t, (0, 0, tab_bottom + tab_t), fillet=0.4), colour)
    if p.get("label", True):
        m.add("label", box(length * 0.7, 0.05, tab_bottom * 0.6, (0, -width / 2 - 0.02, tab_bottom * 0.2)), finish(p.get("label_color", "#e8e8e8"), 0.0, 0.5))
    tower = cyl(width / 2 * 0.98, tower_h, (shaft_x, 0, case_h))
    if p.get("small_tower", True):
        tower = tower.union(cyl(width * 0.28, tower_h * 0.7, (shaft_x - width * 0.55, 0, case_h)))
    m.add("gear_tower", tower, colour)
    spline_top = overall - horn_t * 0.4
    m.add("spline", cyl(spline_d / 2, spline_top - case_h - tower_h, (shaft_x, 0, case_h + tower_h)), FINISH["brass"] if p.get("metal_spline") else FINISH["white_plastic"])
    if p.get("horn", True):
        horn_len = p.get("horn_len_mm", length * 0.72)
        horn_z = overall - horn_t
        horn = cyl(spline_d * 0.9, horn_t, (shaft_x, 0, horn_z)).union(
            cq.Workplane("XY").moveTo(shaft_x, -spline_d * 0.75).lineTo(shaft_x - horn_len, -1.6).lineTo(shaft_x - horn_len, 1.6).lineTo(shaft_x, spline_d * 0.75).close().extrude(horn_t * 0.8).translate((0, 0, horn_z))
        )
        horn = horn.union(cyl(1.6, horn_t * 0.8, (shaft_x - horn_len, 0, horn_z)))
        for k in range(1, 6):
            horn = horn.cut(cyl(0.45, horn_t + 1, (shaft_x - spline_d - (horn_len - spline_d) * k / 5.6, 0, horn_z - 0.5)))
        m.add("horn", horn, FINISH["white_plastic"])
    for i, colour_name in enumerate(p.get("cable_colors", ["wire_brown", "wire_red", "wire_orange"])):
        y = (i - 1) * 0.75
        path = [(-length / 2 + 1.0, y, 2.0), (-length / 2 - 3.0, y, 2.0), (-length / 2 - 9.0, y, 0.5)]
        m.add(f"cable_{i + 1}", wire_path(path, 0.36), FINISH[colour_name])
    return m


def micro_gearmotor(p: dict) -> Model:
    """Micro metal / N20 gearmotor: gearbox plates, flat-sided can, D shaft, solder tabs."""

    m = Model(p["id"])
    w, h = p["width_mm"], p["height_mm"]  # flat sides across, round across
    gear_len = p.get("gearbox_mm", 9.0)
    can_len = p["length_mm"] - gear_len
    shaft_len = p.get("shaft_len_mm", 9.0)
    shaft_d = p.get("shaft_mm", 3.0)
    x0 = -p["length_mm"] / 2
    can = cyl(h / 2, can_len, (x0, 0, h / 2), axis="X").intersect(box(can_len + 1, w, h, (x0 + can_len / 2, 0, 0)))
    m.add("body", can, FINISH["steel"])
    m.add("end_cap", box(1.4, w * 0.9, h * 0.85, (x0 - 0.7, 0, h * 0.075)), FINISH["black_plastic"])
    for sy in (-1, 1):
        m.add(f"terminal_{'a' if sy < 0 else 'b'}", box(1.6, 1.2, 0.25, (x0 - 1.9, sy * w * 0.25, h * 0.75)), FINISH["brass"])
    gx = x0 + can_len
    plates = None
    for k, (off, thick) in enumerate(((0.0, 1.0), (gear_len - 1.2, 1.2))):
        plate = box(thick, w, h, (gx + off + thick / 2, 0, 0))
        plates = plate if plates is None else plates.union(plate)
    m.add("gearbox_plates", plates, FINISH["aluminium"])
    m.add("gears", box(gear_len - 2.2, w * 0.8, h * 0.8, (gx + 1.0 + (gear_len - 2.2) / 2, 0, h * 0.1)), FINISH["brass"])
    for sy in (-1, 1):
        for sz in (-1, 1):
            m.add(f"standoff_{sy}_{sz}", cyl(0.6, gear_len - 2.2, (gx + 1.0, sy * w * 0.32, h / 2 + sz * h * 0.32), axis="X"), FINISH["steel"])
    shaft = cyl(shaft_d / 2, shaft_len, (gx + gear_len, 0, h / 2 + p.get("shaft_offset_mm", 0.0)), axis="X")
    shaft = shaft.cut(box(shaft_len + 0.1, shaft_d, shaft_d, (gx + gear_len + shaft_len / 2 + 0.6, 0, h / 2 + shaft_d / 2 - 0.5 + p.get("shaft_offset_mm", 0.0))))
    m.add("shaft", shaft, FINISH["steel"])
    m.add("bushing", cyl(shaft_d * 0.6 + 0.6, 0.6, (gx + gear_len, 0, h / 2 + p.get("shaft_offset_mm", 0.0)), axis="X"), FINISH["brass"])
    for i, sy in enumerate((-1, 1), 1):
        hole_y = sy * p.get("hole_spacing_mm", 9.0) / 2
        m.add(f"mount_hole_{i}", tube(0.8, 0.55, 0.05, (gx + gear_len, hole_y, h / 2), axis="X"), FINISH["dark_steel"])
    return m


def round_gearmotor(p: dict) -> Model:
    """Round metal gearmotor (20D, 25D, 37D): can, gearbox, face holes, D shaft in a bushing, encoder.

    Pololu's drawings give each length (gearbox, motor, encoder), the diameters, the bushing, the
    shaft offset and the face hole pattern; the motor stands on its back with the shaft up (+Z).
    """

    m = Model(p["id"])
    d = p["diameter_mm"]
    gear_len = p.get("gearbox_mm", p["length_mm"] * 0.35)
    enc_len = p.get("encoder_mm", 0.0)
    can_len = p.get("motor_mm", p["length_mm"] - gear_len - enc_len)
    can_d = p.get("can_d_mm", d * 0.95)
    shaft_d = p["shaft_mm"]
    bush_h = p.get("bushing_h_mm", 2.5)
    bush_d = p.get("bushing_d_mm", shaft_d * 1.75)
    shaft_len = p.get("shaft_len_mm", 12.0) - bush_h
    offset = p.get("shaft_offset_mm", 0.0)
    z_can = enc_len
    z_gear = enc_len + can_len
    face = z_gear + gear_len
    can = cyl(can_d / 2, can_len, (0, 0, z_can))
    if p.get("can_flats_mm"):
        can = can.intersect(box(p["can_flats_mm"], can_d + 1, can_len, (0, 0, z_can)))
    m.add("body", can, FINISH["steel"])
    gear = cyl(d / 2, gear_len, (0, 0, z_gear))
    holes = int(p.get("face_holes", 2))
    circle = p.get("face_hole_circle_mm", d * 0.65)
    thread = p.get("face_hole_thread_mm", 3.0)
    start = p.get("face_hole_start_deg", 0.0)
    for x, y in polar(holes, circle / 2, start):
        gear = gear.cut(cyl(thread / 2 * 0.85, 3.0, (x, y, face - 2.9)))
    gear = gear.union(cyl(d / 2 + 0.01, 0.6, (0, 0, z_gear + gear_len * 0.45)).cut(cyl(d / 2 - 0.3, 0.8, (0, 0, z_gear + gear_len * 0.45 - 0.1))))
    m.add("gearbox", gear, FINISH["aluminium"] if p.get("gearbox_color") is None else finish(p["gearbox_color"], 0.8, 0.4))
    for i, (x, y) in enumerate(polar(holes, circle / 2, start), 1):
        m.add(f"mount_hole_{i}", tube(thread / 2, thread / 2 * 0.8, 0.05, (x, y, face)), FINISH["dark_steel"])
    m.add("bushing", cyl(bush_d / 2, bush_h, (offset, 0, face)), FINISH["brass"])
    shaft = cyl(shaft_d / 2, shaft_len, (offset, 0, face + bush_h))
    flat = p.get("flat_mm", shaft_d * 0.1)
    shaft = shaft.cut(box(shaft_d, shaft_d * 1.2, shaft_len * 0.85, (offset + shaft_d - flat, 0, face + bush_h + shaft_len * 0.15)))
    m.add("shaft", shaft, FINISH["steel"])
    if enc_len:
        enc_d = p.get("encoder_d_mm", can_d)
        m.add("encoder_board", cyl(enc_d / 2 * 0.98, 1.2, (0, 0, enc_len - 1.2)), FINISH["pcb_green"])
        m.add("encoder_cap", cyl(enc_d / 2, enc_len - 1.2, (0, 0, 0)), FINISH["black_plastic"])
        m.add("encoder_cable", wire_path([(enc_d / 2 - 1.5, 0, enc_len * 0.5), (enc_d / 2 + 6, 0, enc_len * 0.5)], 1.2), FINISH["wire_black"])
    else:
        m.add("end_cap", cyl(can_d / 2 * 0.95, 1.5, (0, 0, -1.5)), FINISH["black_plastic"])
        for sx in (-1, 1):
            m.add(f"terminal_{'a' if sx < 0 else 'b'}", box(1.2, 0.3, 2.0, (sx * can_d * 0.25, 0, -3.3)), FINISH["brass"])
    return m


def can_motor(p: dict) -> Model:
    """130-size brushed DC motor: flat-sided can, plastic end bell, shaft and solder tabs."""

    m = Model(p["id"])
    w, h, length = p["width_mm"], p["height_mm"], p["length_mm"]
    can = cyl(h / 2, length, (0, 0, h / 2), axis="X").intersect(box(length + 1, w, h, (length / 2, 0, 0)))
    m.add("body", can.translate((-length / 2, 0, 0)), FINISH["steel"])
    m.add("end_bell", cyl(h * 0.42, 3.0, (-length / 2 - 3.0, 0, h / 2), axis="X"), FINISH["white_plastic"])
    m.add("shaft", cyl(p.get("shaft_mm", 2.0) / 2, p.get("shaft_len_mm", 8.0), (length / 2, 0, h / 2), axis="X"), FINISH["steel"])
    m.add("bushing", cyl(p.get("boss_d_mm", 6.0) / 2, 1.5, (length / 2, 0, h / 2), axis="X"), FINISH["brass"])
    for sy in (-1, 1):
        m.add(f"terminal_{'a' if sy < 0 else 'b'}", box(0.3, 1.5, 3.0, (-length / 2 - 1.5, sy * h * 0.25, h * 0.7)), FINISH["brass"])
    return m


def tt_motor(p: dict) -> Model:
    """TT gear motor: yellow gearbox with mounting holes, motor can on the back, double D output shaft."""

    m = Model(p["id"])
    length, width, height = p["length_mm"], p["width_mm"], p["height_mm"]
    gear_len = p.get("gearbox_mm", length * 0.6)
    gearbox = box(gear_len, width, height, (length / 2 - gear_len / 2, 0, 0), fillet=1.0)
    for x, z in p.get("holes", [(length / 2 - gear_len + 6, height / 2), (length / 2 - 8, height / 2)]):
        gearbox = gearbox.cut(cyl(1.6, width + 2, (x, -width / 2 - 1, z), axis="Y").translate((0, width + 2, 0)))
    m.add("body", gearbox, finish(p.get("color", "#f2c230"), 0.0, 0.5))
    can_d = p.get("can_d_mm", height * 0.9)
    can_len = length - gear_len
    can = cyl(can_d / 2, can_len, (-length / 2, 0, height / 2), axis="X").intersect(box(can_len + 1, width * 0.9, can_d, (-length / 2 + can_len / 2, 0, height / 2 - can_d / 2)))
    m.add("motor_can", can, FINISH["steel"])
    shaft_x = length / 2 - p.get("shaft_from_end_mm", 11.0)
    for sy in (-1, 1):
        m.add(f"shaft_{'a' if sy < 0 else 'b'}", cyl(2.7, 9.0, (shaft_x, sy * (width / 2), height * 0.5), axis="Y").translate((0, 0 if sy < 0 else 9.0, 0)).intersect(box(3.7, 30, 30, (shaft_x, 0, height * 0.5 - 15))), FINISH["white_plastic"])
    if p.get("wheel_d_mm"):
        wheel_d = p["wheel_d_mm"]
        wheel_w = p.get("wheel_w_mm", 26.0)
        y = width / 2 + 9.0 - 0.5
        tyre = tube(wheel_d / 2, wheel_d / 2 - 5.0, wheel_w, (shaft_x, y, height * 0.5), axis="Y").translate((0, wheel_w, 0))
        m.add("tyre", tyre, FINISH["rubber"])
        rim = tube(wheel_d / 2 - 5.0, 3.0, wheel_w * 0.6, (shaft_x, y + wheel_w * 0.2, height * 0.5), axis="Y").translate((0, wheel_w * 0.6, 0))
        m.add("rim", rim, finish("#f2c230", 0.0, 0.5))
    return m


def stepper(p: dict) -> Model:
    """NEMA stepper: chamfered square body in three sections, pilot boss, D shaft, four face holes, leads."""

    m = Model(p["id"])
    face = p["face_mm"]
    length = p["length_mm"]
    chamfer = p.get("chamfer_mm", face * 0.12)
    spacing = p["hole_spacing_mm"]
    thread = p.get("hole_thread_mm", 3.0)

    def section(z: float, h: float):
        return cq.Workplane("XY").rect(face, face).extrude(h).edges("|Z").chamfer(chamfer).translate((0, 0, z))

    cap_h = min(8.0, length * 0.2)
    m.add("end_cap_back", section(0, cap_h), FINISH["anodised_black"])
    m.add("body", section(cap_h, length - 2 * cap_h), finish("#2b2c2f", 0.6, 0.45))
    front = section(length - cap_h, cap_h)
    for x, y in [(spacing / 2, spacing / 2), (-spacing / 2, spacing / 2), (-spacing / 2, -spacing / 2), (spacing / 2, -spacing / 2)]:
        front = front.cut(cyl(thread / 2 * 0.85, 4.6, (x, y, length - 4.5)))
    m.add("end_cap_front", front, FINISH["anodised_black"])
    for i, (x, y) in enumerate([(spacing / 2, spacing / 2), (-spacing / 2, spacing / 2), (-spacing / 2, -spacing / 2), (spacing / 2, -spacing / 2)], 1):
        m.add(f"mount_hole_{i}", tube(thread / 2, thread / 2 * 0.8, 0.05, (x, y, length)), FINISH["dark_steel"])
    m.add("boss", cyl(p.get("boss_d_mm", 22.0) / 2, p.get("boss_h_mm", 2.0), (0, 0, length)), FINISH["aluminium"])
    shaft_d = p["shaft_mm"]
    shaft_len = p.get("shaft_len_mm", 24.0)
    shaft = cyl(shaft_d / 2, shaft_len, (0, 0, length + p.get("boss_h_mm", 2.0)))
    shaft = shaft.cut(box(shaft_d, shaft_d, shaft_len * 0.8, (shaft_d - p.get("flat_mm", 0.5), 0, length + p.get("boss_h_mm", 2.0) + shaft_len * 0.2)))
    m.add("shaft", shaft, FINISH["steel"])
    if p.get("connector", True):
        m.add("connector", box(6.0, 10.0, 6.0, (face / 2 + 2.5, 0, cap_h * 0.3)), FINISH["white_plastic"])
    else:
        for i, colour in enumerate(p.get("lead_colors", ["wire_red", "wire_blue", "wire_green", "wire_black"])):
            y = (i - 1.5) * 1.3
            m.add(f"lead_{i + 1}", wire_path([(face / 2 - 1.0, y, cap_h * 0.5), (face / 2 + 10.0, y, cap_h * 0.5)], 0.55), FINISH[colour])
    return m


def can_stepper(p: dict) -> Model:
    """28BYJ-48: round can with mounting ears, blue cap, offset flatted shaft and lead bundle."""

    m = Model(p["id"])
    d = p["diameter_mm"]
    h = p["height_mm"]
    ears = p.get("ear_spacing_mm", 35.0)
    can = cyl(d / 2, h - 1.0)
    m.add("body", can, FINISH["steel"])
    ear = box(ears + 7.0, 7.0, 0.8, (0, 0, h - 1.8), fillet=0.0)
    for sx in (-1, 1):
        ear = ear.union(cyl(3.5, 0.8, (sx * ears / 2, 0, h - 1.8)))
        ear = ear.cut(cyl(2.1, 1.2, (sx * ears / 2, 0, h - 2.0)))
    m.add("ears", ear, FINISH["steel"])
    for i, sx in enumerate((-1, 1), 1):
        m.add(f"mount_hole_{i}", tube(2.1, 1.9, 0.8, (sx * ears / 2, 0, h - 1.8)), FINISH["steel"])
    offset = p.get("shaft_offset_mm", 8.0)
    m.add("boss", cyl(4.5, 1.5, (0, offset, h - 1.0)), FINISH["steel"])
    shaft = cyl(p.get("shaft_mm", 5.0) / 2, p.get("shaft_len_mm", 10.0), (0, offset, h + 0.5)).cut(box(6, 6, 6.5, (0, offset + 3 + 1.5, h + 4.0)).union(box(6, 6, 6.5, (0, offset - 3 - 1.5, h + 4.0))))
    m.add("shaft", shaft, FINISH["brass"])
    m.add("cap", box(17.0, 6.0, h - 3.0, (0, -d / 2 - 1.5, 0.5)), finish("#2f6fd1", 0.0, 0.5))
    for i, colour in enumerate(("wire_blue", "wire_red", "wire_orange", "wire_yellow", "wire_white")):
        x = (i - 2) * 1.2
        m.add(f"lead_{i + 1}", wire_path([(x, -d / 2 - 3.5, h * 0.4), (x, -d / 2 - 12.0, h * 0.4)], 0.5), FINISH["wire_brown" if colour == "wire_white" else colour])
    return m


def wheel(p: dict) -> Model:
    """A robot wheel: tyre, rim with spokes, hub with its bore."""

    m = Model(p["id"])
    d = p["diameter_mm"]
    width = p["width_mm"]
    tyre_t = p.get("tyre_mm", max(2.0, d * 0.08))
    bore = p.get("bore_mm", 3.0)
    tyre = tube(d / 2, d / 2 - tyre_t, width)
    try:
        tyre = tyre.faces(">Z or <Z").edges(cq.selectors.RadiusNthSelector(-1)).fillet(min(tyre_t, width) * 0.35)
    except Exception:
        pass
    m.add("tyre", tyre, finish(p.get("tyre_color", "#1d1d1d"), 0.0, 0.85))
    rim_w = width * 0.8
    rim_r = d / 2 - tyre_t
    rim = tube(rim_r, rim_r - 1.2, rim_w, (0, 0, (width - rim_w) / 2))
    hub_r = max(bore * 1.6, d * 0.11)
    hub = cyl(hub_r, width, (0, 0, 0)).faces(">Z").workplane().hole(bore)
    web = cyl(rim_r - 0.5, 1.4, (0, 0, width / 2 - 0.7))
    for x, y in polar(int(p.get("spokes", 6)), (rim_r + hub_r) / 2, 30):
        web = web.cut(cyl((rim_r - hub_r) * 0.32, 2.0, (x, y, width / 2 - 1.0)))
    rim = rim.union(web).union(hub)
    rim = rim.cut(cyl(bore / 2, width + 1, (0, 0, -0.5)))
    m.add("rim", rim, finish(p.get("rim_color", "#202124"), 0.0, 0.5))
    if p.get("hub_holes_mm"):
        for i, sx in enumerate((-1, 1), 1):
            m.add(f"hub_hole_{i}", tube(1.6, 1.4, 0.05, (sx * p["hub_holes_mm"] / 2, 0, width / 2 + 0.7)), finish(p.get("rim_color", "#202124"), 0.0, 0.5))
    return m


def ball_caster(p: dict) -> Model:
    m = Model(p["id"])
    ball = p["ball_mm"]
    height = p["height_mm"]
    length = p.get("length_mm", ball * 2.0)
    width = p.get("width_mm", ball * 1.5)
    housing = box(length, width, max(2.0, height - ball * 0.75), (0, 0, height - max(2.0, height - ball * 0.75)), fillet=1.0)
    housing = housing.union(cyl(min(ball * 0.62, width / 2), height - ball * 0.45, (0, 0, ball * 0.45)))
    housing = housing.cut(cq.Workplane("XY").sphere(ball / 2 + 0.2).translate((0, 0, ball / 2)))
    spacing = p.get("hole_spacing_mm", length - 5.0)
    for sx in (-1, 1):
        housing = housing.cut(cyl(1.1, height + 1, (sx * spacing / 2, 0, -0.5)))
    m.add("body", housing, finish(p.get("color", "#1d1d1f"), 0.0, 0.5))
    for i, sx in enumerate((-1, 1), 1):
        m.add(f"mount_hole_{i}", tube(1.1, 0.95, 0.05, (sx * spacing / 2, 0, height)), finish(p.get("color", "#1d1d1f"), 0.0, 0.5))
    m.add("ball", cq.Workplane("XY").sphere(ball / 2).translate((0, 0, ball / 2)), FINISH["steel"] if p.get("metal", True) else FINISH["white_plastic"])
    return m


def bearing(p: dict) -> Model:
    m = Model(p["id"])
    bore, outer, width = p["bore_mm"], p["outer_mm"], p["width_mm"]
    ring = (outer - bore) / 2
    m.add("outer_ring", tube(outer / 2, outer / 2 - ring * 0.22, width), FINISH["steel"])
    m.add("inner_ring", tube(bore / 2 + ring * 0.22, bore / 2, width), FINISH["steel"])
    shield = FINISH["steel"] if p.get("shield", "metal") == "metal" else finish("#1b1b1b", 0.0, 0.8)
    for z in (0.15, width - 0.25):
        m.add(f"shield_{'a' if z < 1 else 'b'}", tube(outer / 2 - ring * 0.22, bore / 2 + ring * 0.22, 0.1, (0, 0, z)), shield)
    return m


def screw(p: dict) -> Model:
    m = Model(p["id"])
    d = p["thread_mm"]
    length = p["length_mm"]
    head_d = p.get("head_d_mm", d * 1.9)
    head_h = p.get("head_h_mm", d * 0.75)
    head = cyl(head_d / 2, head_h, (0, 0, length))
    try:
        head = head.faces(">Z").edges().fillet(head_h * 0.45)
    except Exception:
        pass
    drive = p.get("drive", "phillips")
    if drive == "phillips":
        head = head.cut(box(head_d * 0.55, head_d * 0.14, head_h, (0, 0, length + head_h * 0.45))).cut(box(head_d * 0.14, head_d * 0.55, head_h, (0, 0, length + head_h * 0.45)))
    else:
        head = head.cut(cq.Workplane("XY").polygon(6, d * 0.58 * 1.1547).extrude(head_h).translate((0, 0, length + head_h * 0.4)))
    m.add("head", head, finish(p.get("color", "#c4c7cc"), 1.0, 0.3))
    shank = cyl(d / 2 * 0.86, length)
    pitch = p.get("pitch_mm", 0.5 if d >= 3 else 0.3)
    k = 0.0
    while k < length - pitch:
        shank = shank.union(tube(d / 2, d / 2 * 0.86, pitch * 0.45, (0, 0, k)))
        k += pitch
    m.add("shank", shank, finish(p.get("color", "#c4c7cc"), 1.0, 0.3))
    return m


def nut_or_insert(p: dict) -> Model:
    m = Model(p["id"])
    if p.get("kind") == "insert":
        od, length, bore = p["outer_mm"], p["length_mm"], p["bore_mm"]
        body = tube(od / 2, bore / 2, length)
        for z in (length * 0.15, length * 0.55):
            for i in range(12):
                body = body.cut(box(0.35, 0.8, length * 0.3, (od / 2, 0, z)).rotate((0, 0, 0), (0, 0, 1), 30.0 * i + (15 if z > 1 else 0)))
        m.add("body", body, FINISH["brass"])
    return m


def disc(p: dict) -> Model:
    """A disc or rod: magnets, rubber feet, steel rod, silicone pads."""

    m = Model(p["id"])
    d, h = p["diameter_mm"], p["height_mm"]
    shape = p.get("shape", "cylinder")
    if shape == "dome":
        piece = cq.Workplane("XY").sphere(d / 2).intersect(box(d + 1, d + 1, h)).translate((0, 0, 0))
        piece = cq.Workplane("XY").ellipse(d / 2, d / 2).extrude(h).edges(">Z").fillet(min(h * 0.9, d * 0.45))
    elif shape == "rod":
        piece = cyl(d / 2, h).edges().chamfer(min(0.5, d * 0.08))
    else:
        piece = cyl(d / 2, h)
        try:
            piece = piece.edges().fillet(min(0.2, h * 0.1))
        except Exception:
            pass
    m.add("body", piece, finish(p.get("color", "#b9bcc0"), p.get("metal", 0.0), p.get("rough", 0.4)))
    return m


def cell(p: dict) -> Model:
    """A cylindrical cell (18650, AA) lying along X: wrap, insulator ring, positive cap."""

    m = Model(p["id"])
    d, length = p["diameter_mm"], p["length_mm"]
    cap = p.get("cap_mm", 0.8)
    body = cyl(d / 2, length - cap, (-length / 2, 0, d / 2), axis="X")
    m.add("body", body, finish(p.get("wrap_color", "#2c62c4"), 0.2, 0.35))
    m.add("band", tube(d / 2 + 0.02, d / 2 - 0.2, length * 0.18, (-length / 2 + length * 0.55, 0, d / 2), axis="X"), finish(p.get("band_color", "#d7d7d7"), 0.2, 0.4))
    m.add("insulator", tube(d / 2 - 0.4, d * 0.22, 0.05, (length / 2 - cap - 0.05, 0, d / 2), axis="X"), FINISH["white_plastic"])
    m.add("positive_cap", cyl(p.get("button_d_mm", d * 0.4) / 2, cap, (length / 2 - cap, 0, d / 2), axis="X"), FINISH["steel"])
    m.add("negative_end", cyl(d / 2 * 0.9, 0.05, (-length / 2 - 0.05, 0, d / 2), axis="X"), FINISH["steel"])
    return m


def cell_pack(p: dict) -> Model:
    """Cells side by side (a 2S/3S pack, a blister of AA cells) or in a holder tray."""

    m = Model(p["id"])
    n = int(p["cells"])
    d, length = p["cell_d_mm"], p["cell_len_mm"]
    gap = p.get("gap_mm", 0.0)
    wall = p.get("wall_mm", 0.0)
    span = n * d + (n - 1) * gap
    for i in range(0 if p.get("empty") else n):
        y = -span / 2 + d / 2 + i * (d + gap)
        part = cell({"id": "c", "diameter_mm": d, "length_mm": length, "wrap_color": p.get("wrap_color", "#2c62c4"), "band_color": p.get("band_color", "#d7d7d7")})
        for name, shape, fin in part.pieces:
            m.pieces.append((f"cell_{i + 1}_{name}" if name != "body" else f"cell_{i + 1}", shape.translate(cq.Vector(0, y, wall)), fin))
    if p.get("holder"):
        tray_l = p.get("holder_len_mm", length + 2 * wall + 6)
        tray_w = p.get("holder_w_mm", span + 2 * wall)
        tray_h = p.get("holder_h_mm", d * 0.75 + wall)
        tray = box(tray_l, tray_w, tray_h)
        for i in range(n):
            y = -span / 2 + d / 2 + i * (d + gap)
            tray = tray.cut(cyl(d / 2 + 0.3, length + 0.6, (-length / 2 - 0.3, y, wall + d / 2), axis="X"))
        tray = tray.cut(box(tray_l - 2 * wall, tray_w - 2 * wall, tray_h, (0, 0, wall + d * 0.35)))
        m.pieces.insert(0, ("body", tray.val(), finish(p.get("holder_color", "#1e1e1f"), 0.0, 0.55)))
        for sy, colour in ((-1, "wire_black"), (1, "wire_red")):
            m.add(f"lead_{'black' if sy < 0 else 'red'}", wire_path([(-tray_l / 2 + 2, sy * (tray_w / 2 - 3), wall + 1), (-tray_l / 2 - 15, sy * 2, wall + 1)], 0.6), FINISH[colour])
    elif p.get("shrink"):
        # A shrink-wrapped pack: the wrap hides the cells, so the pack's own size is the body.
        pack_l = p.get("length_mm", length + 1.0)
        pack_w = p.get("width_mm", span + 1.0)
        pack_h = p.get("height_mm", d + 1.0)
        m.pieces = []
        m.add("body", box(pack_l, pack_w, pack_h, fillet=min(pack_w, pack_h) * 0.3), finish(p.get("shrink_color", "#3a6fd8"), 0.1, 0.35))
        m.add("label", box(pack_l * 0.5, pack_w * 0.7, 0.05, (0, 0, pack_h - 0.02)), finish(p.get("label_color", "#f2f2f0"), 0.0, 0.5))
        for sy, colour in ((-1, "wire_black"), (1, "wire_red")):
            m.add(f"lead_{'black' if sy < 0 else 'red'}", wire_path([(-pack_l / 2 + 1, sy * 2.0, pack_h / 2), (-pack_l / 2 - 12, sy * 2.0, pack_h / 2)], 0.7), FINISH[colour])
        if p.get("connector") == "jst_ph":
            m.add("connector", box(4.5, 6.0, 6.0, (-pack_l / 2 - 14.2, 0, pack_h / 2 - 3.0)), FINISH["white_plastic"])
    return m


def enclosure(p: dict) -> Model:
    """A boxed device: wall adapters, power banks, pumps, lidars, cameras. Main block plus features."""

    m = Model(p["id"])
    length, width, height = p["length_mm"], p["width_mm"], p["height_mm"]
    style = p.get("style", "box")
    colour = finish(p.get("color", "#1f1f21"), 0.0, p.get("rough", 0.5))
    if style == "cylinder":
        body = cyl(min(length, width) / 2, height)
    else:
        body = box(length, width, height, fillet=p.get("fillet_mm", min(length, width, height) * 0.15))
    m.add("body", body, colour)
    for index, c in enumerate(p.get("parts", []), 1):
        _component(m, c, index, c.get("z0", 0.0), c.get("t", 0.0))
    return m


def europlug(m: Model, x: float, y: float, z: float, axis: str = "Z") -> None:
    """Two Europlug pins (EN 50075: 4.0 mm across, 19 mm apart, 19 mm long) along +axis from (x, y, z)."""

    for i, s in enumerate((-1, 1), 1):
        if axis == "Z":
            m.add(f"plug_pin_{i}", cyl(2.0, 19.0, (x + s * 9.5, y, z)), FINISH["steel"])
        else:
            m.add(f"plug_pin_{i}", cyl(2.0, 19.0, (x, y + s * 9.5, z), axis="X"), FINISH["steel"])


def wall_adapter(p: dict) -> Model:
    m = enclosure(p)
    if p.get("plug", "europlug") == "europlug":
        europlug(m, 0, 0, p["height_mm"])
    if p.get("cable", True):
        m.add("cable", wire_path([(0, -p["width_mm"] / 2 + 2, 4), (0, -p["width_mm"] / 2 - 8, 4), (8, -p["width_mm"] / 2 - 18, 4)], 1.6), FINISH["wire_black" if p.get("color", "#1f1f21") != "#f2f2f0" else "wire_white"])
    return m


def fan(p: dict) -> Model:
    m = Model(p["id"])
    s, t = p["size_mm"], p["thickness_mm"]
    spacing = p["hole_spacing_mm"]
    frame = box(s, s, t, fillet=0.0).edges("|Z").fillet(s * 0.06).cut(cyl(s * 0.48, t + 1, (0, 0, -0.5)))
    for x, y in [(spacing / 2, spacing / 2), (-spacing / 2, spacing / 2), (-spacing / 2, -spacing / 2), (spacing / 2, -spacing / 2)]:
        frame = frame.cut(cyl(p.get("hole_d_mm", 3.4) / 2, t + 1, (x, y, -0.5)))
    m.add("body", frame, FINISH["black_plastic"])
    for i, (x, y) in enumerate([(spacing / 2, spacing / 2), (-spacing / 2, spacing / 2), (-spacing / 2, -spacing / 2), (spacing / 2, -spacing / 2)], 1):
        m.add(f"mount_hole_{i}", tube(p.get("hole_d_mm", 3.4) / 2, p.get("hole_d_mm", 3.4) / 2 - 0.2, t, (x, y, 0)), FINISH["black_plastic"])
    hub_r = s * 0.2
    m.add("hub", cyl(hub_r, t * 0.9, (0, 0, t * 0.05)), FINISH["black_plastic"])
    m.add("sticker", cyl(hub_r * 0.85, 0.05, (0, 0, t * 0.95)), finish(p.get("sticker_color", "#d8d8d8"), 0.0, 0.5))
    blades = None
    count = int(p.get("blades", 7))
    for i in range(count):
        blade = box(s * 0.48 - hub_r, s * 0.15, 0.6, ((s * 0.48 + hub_r) / 2 - 0.3, 0, t * 0.5)).rotate(((s * 0.48 + hub_r) / 2, 0, t * 0.5), ((s * 0.48 + hub_r) / 2 + 1, 0, t * 0.5), 35)
        blade = blade.rotate((0, 0, 0), (0, 0, 1), 360.0 * i / count)
        blades = blade if blades is None else blades.union(blade)
    m.add("blades", blades, FINISH["black_plastic"])
    for i, colour in enumerate(("wire_red", "wire_black")):
        m.add(f"lead_{i + 1}", wire_path([(s / 2 - 3, s / 2 - 4 + i * 1.0, t * 0.5), (s / 2 + 8, s / 2 - 4 + i * 1.0, t * 0.5)], 0.45), FINISH[colour])
    return m


def rocker_switch(p: dict) -> Model:
    m = Model(p["id"])
    length, width, height = p["length_mm"], p["width_mm"], p["height_mm"]
    bezel_t = 2.0
    body_h = height - bezel_t - 3.0
    m.add("body", box(length - 2.0, width - 2.0, body_h), FINISH["black_plastic"])
    m.add("bezel", box(length, width, bezel_t, (0, 0, body_h), fillet=0.5), FINISH["black_plastic"])
    rocker = box(length - 3.0, width - 3.0, 3.0, (0, 0, body_h + bezel_t)).rotate((0, 0, body_h + bezel_t), (0, 1, body_h + bezel_t), 8)
    m.add("rocker", rocker, finish(p.get("color", "#1f1f1f"), 0.0, 0.5))
    for i, sx in enumerate((-1, 1), 1):
        m.add(f"terminal_{i}", box(0.8, 4.8, 6.0, (sx * length * 0.22, 0, -6.0)), FINISH["brass"])
    return m


def coil(p: dict) -> Model:
    """A coiled cable or tube, drawn as stacked loops (its length is in the name, not the model)."""

    m = Model(p["id"])
    d = p["coil_d_mm"]
    r = p["cord_d_mm"] / 2
    loops = int(p.get("loops", 4))
    for i in range(loops):
        m.add(f"loop_{i + 1}", tube(d / 2 + r, d / 2 - r, 2 * r, (0, 0, i * 2 * r * 1.05)), finish(p.get("color", "#1f1f21"), 0.0, p.get("rough", 0.6), ) if p.get("alpha", 1) == 1 else finish(p.get("color"), 0.0, 0.2))
    for k, end in enumerate(p.get("ends", [])):
        m.add(f"plug_{k + 1}", box(end[0], end[1], end[2], (d / 2 + end[0] / 2 + 2 * k * end[0], 0, 0), fillet=0.6), FINISH["tin"] if end[3] == "metal" else finish(end[3], 0.0, 0.5))
    return m


def pad(p: dict) -> Model:
    m = Model(p["id"])
    m.add("body", box(p["length_mm"], p["width_mm"], p["height_mm"], fillet=p.get("fillet_mm", 0.8)), finish(p.get("color", "#2b2b2b"), 0.0, 0.85))
    if p.get("ridges"):
        for i in range(int(p["ridges"])):
            x = -p["length_mm"] / 2 + p["length_mm"] * (i + 0.5) / p["ridges"]
            m.add(f"ridge_{i + 1}", box(p["length_mm"] / p["ridges"] * 0.4, p["width_mm"] * 0.9, 0.4, (x, 0, p["height_mm"])), finish(p.get("color", "#2b2b2b"), 0.0, 0.85))
    return m
