"""Look-alike drone parts: brushless motors, propellers, LiPo packs, cameras, VTX and frames.

Each generator takes the part's measured numbers (`p`) and draws the part around them. Pieces whose
names the checks measure: `bell`, `base` and `mount_hole_N` on a motor, `blade_N` and `hub` on a
propeller, `body` and `connector` on a battery, `frame_*`, `motor_mount_N` on a frame.
Anything not in `p` is drawn in proportion and listed as styled in the manifest, never as measured.
"""

from __future__ import annotations

import math

import cadquery as cq

from .model import Model
from .glb import ring_mesh
from .shapes import FINISH, box, cyl, finish, polar, rounded_plate, tube, wire_path


def brushless_motor(p: dict) -> Model:
    m = Model(p["id"])
    d = p["diameter_mm"]
    r = d / 2
    height = p["height_mm"]
    shaft_len = p.get("shaft_len_mm", 0.25 * height)
    shaft_d = p["shaft_mm"]
    body_h = height - shaft_len
    base_h = max(0.8, 0.16 * body_h)
    gap = max(0.4, 0.1 * body_h)
    bell_z = base_h + gap
    wall = max(0.35, 0.05 * d)
    cap_t = max(0.5, 0.09 * body_h)
    bolts = int(p.get("bolts", 3))
    circle = p["bolt_circle_mm"]
    thread = p.get("bolt_thread_mm", 1.4)
    base_r = max(circle / 2 + thread * 1.1, 0.42 * d)
    base_r = min(base_r, r * 1.02) if circle < d else circle / 2 + thread * 1.1

    base = cyl(base_r, base_h).faces(">Z").workplane().circle(shaft_d * 1.6).cutThruAll()
    for x, y in polar(bolts, circle / 2, 90):
        base = base.cut(cyl(thread / 2, base_h + 0.2, (x, y, -0.1)))
    try:
        base = base.faces("<Z").edges().fillet(min(0.3, base_h * 0.3))
    except Exception:
        pass
    m.add("base", base, finish(p.get("base_color", "#2a2b2e"), 0.8, 0.4))
    for i, (x, y) in enumerate(polar(bolts, circle / 2, 90), 1):
        m.add(f"mount_hole_{i}", tube(thread / 2, thread * 0.36, base_h, (x, y, 0)), FINISH["dark_steel"])

    stator_r = r - wall - max(0.25, 0.04 * d)
    stator = cyl(stator_r, body_h - cap_t - base_h - 0.15, (0, 0, base_h))
    teeth = max(9, int(round(d * 0.6 / 3)) * 3)
    for i in range(teeth):
        angle = 360.0 * i / teeth
        slot = box(stator_r * 0.5, max(0.25, stator_r * 0.12), body_h, (stator_r * 0.95, 0, base_h)).rotate((0, 0, 0), (0, 0, 1), angle + 180 / teeth)
        stator = stator.cut(slot)
    m.add("stator_windings", stator, FINISH["copper"])
    m.add("stator_core", tube(stator_r * 0.55, shaft_d * 0.9, body_h - cap_t - base_h - 0.1, (0, 0, base_h)), FINISH["dark_steel"])

    color = finish(p.get("color", "#1d1f22"), 0.8, 0.35)
    shell = tube(r, r - wall, body_h - cap_t - bell_z, (0, 0, bell_z))
    cap = cyl(r, cap_t, (0, 0, body_h - cap_t))
    spokes = int(p.get("spokes", 5 if d > 20 else 3))
    inner = max(shaft_d * 1.8, r * 0.3)
    outer = r - wall * 1.4
    if outer > inner + 0.5:
        for i in range(spokes):
            start = 360.0 * i / spokes + 360.0 / spokes * 0.18
            sweep = 360.0 / spokes * 0.64
            window = (
                cq.Workplane("XY")
                .moveTo(inner * math.cos(math.radians(start)), inner * math.sin(math.radians(start)))
                .lineTo(outer * math.cos(math.radians(start)), outer * math.sin(math.radians(start)))
                .threePointArc(
                    (outer * math.cos(math.radians(start + sweep / 2)), outer * math.sin(math.radians(start + sweep / 2))),
                    (outer * math.cos(math.radians(start + sweep)), outer * math.sin(math.radians(start + sweep))),
                )
                .lineTo(inner * math.cos(math.radians(start + sweep)), inner * math.sin(math.radians(start + sweep)))
                .threePointArc(
                    (inner * math.cos(math.radians(start + sweep / 2)), inner * math.sin(math.radians(start + sweep / 2))),
                    (inner * math.cos(math.radians(start)), inner * math.sin(math.radians(start))),
                )
                .close()
                .extrude(cap_t + 0.2)
                .translate((0, 0, body_h - cap_t - 0.1))
            )
            cap = cap.cut(window)
    bell = shell.union(cap)
    try:
        bell = bell.faces(">Z").edges("not %CIRCLE").fillet(0.1)
    except Exception:
        pass
    try:
        bell = bell.faces(">Z").edges(cq.selectors.RadiusNthSelector(-1)).fillet(min(0.6, cap_t * 0.6))
    except Exception:
        pass
    m.add("bell", bell, color)
    m.add("magnets", tube(r - wall, r - wall - max(0.2, 0.03 * d), body_h - cap_t - bell_z - 0.1, (0, 0, bell_z + 0.05)), FINISH["dark_steel"])
    m.add("shaft", cyl(shaft_d / 2, height - base_h + 0.4, (0, 0, base_h - 0.4)), FINISH["steel"])
    if p.get("prop_bolts"):
        for i, (x, y) in enumerate(polar(int(p["prop_bolts"]), p["prop_bolt_circle_mm"] / 2, 45), 1):
            m.add(f"prop_hole_{i}", tube(p.get("prop_bolt_thread_mm", 2.0) / 2, p.get("prop_bolt_thread_mm", 2.0) * 0.36, 0.05, (x, y, body_h - 0.04)), FINISH["dark_steel"])
    if shaft_d >= 4:
        nut_r = shaft_d * 0.95
        nut = cq.Workplane("XY").polygon(6, nut_r * 2).extrude(shaft_len * 0.35).faces(">Z").workplane().hole(shaft_d)
        m.add("prop_nut", nut.translate((0, 0, height - shaft_len * 0.38)), FINISH["aluminium"])
    lead_len = min(p.get("wire_len_mm", 20), 0.45 * d + 3)
    wire_r = p.get("wire_r_mm", max(0.28, 0.022 * d))
    for i, colour in enumerate(p.get("wire_colors", ["wire_black", "wire_black", "wire_black"])):
        y = (i - 1) * wire_r * 2.3
        path = [(-base_r * 0.6, y, base_h * 0.5), (-base_r - 0.6, y, base_h * 0.5), (-base_r - lead_len, y, base_h * 0.5 - lead_len * 0.12)]
        m.add(f"lead_{i + 1}", wire_path(path, wire_r), FINISH[colour])
    return m


def propeller(p: dict) -> Model:
    m = Model(p["id"])
    diameter = p["diameter_mm"]
    radius = diameter / 2
    blades = int(p["blades"])
    bore = p.get("shaft_mm", 1.5)
    hub_r = p.get("hub_d_mm", max(bore * 2.6, diameter * 0.085)) / 2
    hub_h = p.get("hub_h_mm", max(3.2, diameter * 0.075))
    pitch = p.get("pitch_in", 0.45 * diameter / 25.4) * 25.4
    color = finish(p.get("color", "#2b2f36"), 0.0, 0.25)
    if p.get("alpha", 1.0) < 1.0:
        color = type(color)(color.color, 0.0, 0.15, p["alpha"])
    cmax = p.get("chord_mm", radius * {2: 0.26, 3: 0.23, 4: 0.19, 5: 0.17}.get(blades, 0.18))
    thick = max(0.32, diameter * 0.011)
    stations = [
        (hub_r * 0.55, 0.42, 1.0),
        (hub_r * 1.25, 0.62, 0.95),
        (radius * 0.35, 0.9, 0.8),
        (radius * 0.55, 1.0, 0.65),
        (radius * 0.75, 0.88, 0.5),
        (radius * 0.9, 0.62, 0.42),
        (radius * 0.975, 0.34, 0.36),
        (radius, 0.12, 0.3),
    ]
    def section(rr: float, chord_f: float, thick_f: float) -> list[tuple[float, float, float]]:
        theta = min(math.radians(62), math.atan(pitch / (2 * math.pi * max(rr, 0.3))))
        sweep = 0.07 * radius * (rr / radius) ** 2
        return _blade_points(rr, sweep, hub_h * 0.55, theta, max(0.4, cmax * chord_f), max(0.12, thick * thick_f))

    wires = [cq.Wire.assembleEdges([cq.Edge.makeSpline([cq.Vector(*q) for q in section(*s)], periodic=True)]) for s in stations]
    blade = _loft(wires)
    # The GLB blade is the same surface sampled on a fine span grid (OCC meshes thin blades far too densely).
    rings = []
    samples = 22
    for k in range(samples + 1):
        rr = stations[0][0] + (stations[-1][0] - stations[0][0]) * k / samples
        for (r0, c0, t0), (r1, c1, t1) in zip(stations, stations[1:]):
            if r0 <= rr <= r1 + 1e-9:
                f = (rr - r0) / (r1 - r0) if r1 > r0 else 0.0
                rings.append(section(rr, c0 + (c1 - c0) * f, t0 + (t1 - t0) * f))
                break
    for i in range(blades):
        angle = 2 * math.pi * i / blades
        ca, sa = math.cos(angle), math.sin(angle)
        turned = [[(x * ca - y * sa, x * sa + y * ca, z) for x, y, z in ring] for ring in rings]
        m.add(f"blade_{i + 1}", blade.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), math.degrees(angle)), color, mesh=ring_mesh(turned))
    hub = cyl(hub_r, hub_h).faces(">Z").workplane().hole(bore)
    try:
        hub = hub.faces(">Z").edges(cq.selectors.RadiusNthSelector(-1)).fillet(min(0.5, hub_h * 0.2))
    except Exception:
        pass
    m.add("hub", hub, color)
    return m


def _blade_points(rr: float, sweep: float, z: float, theta: float, chord: float, thick: float, n: int = 16) -> list[tuple[float, float, float]]:
    """A closed airfoil-like section at radius rr, its chord turned theta from the rotor plane."""

    points = []
    for k in range(n):
        a = 2 * math.pi * k / n
        u = chord / 2 * math.cos(a)
        v = thick / 2 * math.sin(a) * (1.0 if math.sin(a) > 0 else 0.5)
        points.append((rr, sweep + u * math.cos(theta) - v * math.sin(theta), z + u * math.sin(theta) + v * math.cos(theta)))
    return points


def _loft(wires: list[cq.Wire]) -> cq.Shape:
    """A smooth solid through the sections; OCP's own compatibility pass fails on twisted blades."""

    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections

    builder = BRepOffsetAPI_ThruSections(True, False, 1e-6)
    builder.CheckCompatibility(False)
    for wire in wires:
        builder.AddWire(wire.wrapped)
    builder.Build()
    return cq.Shape.cast(builder.Shape())


CONNECTORS = {
    # body length along the lead, width, height (mm), pins; see the manifest for each source.
    "bt2.0": (7.6, 5.4, 9.0, 2),
    "ph2.0": (6.0, 4.5, 6.0, 2),
    "xt30": (15.6, 10.2, 5.2, 2),
    "xt60": (16.0, 15.6, 8.2, 2),
    "jst-rcy": (8.6, 5.0, 3.6, 2),
}


def connector(kind: str, at: tuple[float, float, float], toward_x: int = -1) -> list[tuple[str, object, object]]:
    """A battery plug body with its contact holes, its length running along -X from `at`."""

    length, width, height, pins = CONNECTORS[kind]
    x0, y0, z0 = at
    colour = FINISH["white_plastic"] if kind in ("ph2.0", "jst-rcy") else finish("#e3c400") if kind.startswith("xt") else FINISH["black_plastic"]
    if kind == "bt2.0":
        colour = finish("#c7c7c4")
    body = box(length, width, height, (x0 + toward_x * length / 2, y0, z0 - height / 2), fillet=min(0.6, height * 0.15))
    pieces = [("connector", body, colour)]
    for i in range(pins):
        y = y0 + (i - (pins - 1) / 2) * width * 0.45
        hole = cyl(min(width, height) * 0.16, 0.4, (x0 + toward_x * length + (0.3 if toward_x < 0 else -0.3), y, z0), axis="X")
        pieces.append((f"connector_pin_{i + 1}", hole, FINISH["gold"]))
    return pieces


def lipo_pack(p: dict) -> Model:
    m = Model(p["id"])
    length, width, height = p["length_mm"], p["width_mm"], p["height_mm"]
    plug = p.get("connector")
    if p.get("end_cap"):
        # BetaFPV 1S packs: a moulded end cap the full width and height of the pack holds the BT2.0
        # socket, and the shop length runs from the socket face to the far end (their drawings).
        nub = 2.4
        cap = p.get("end_cap_mm", min(7.0, length * 0.11))
        body_len = length - cap - nub
        m.add("body", box(body_len, width, height, (length / 2 - body_len / 2, 0, 0), fillet=min(0.8, height * 0.15)), finish(p.get("wrap_color", "#c9ccd1"), 0.3, 0.35))
        m.add("label", box(body_len * 0.8, width * 0.9, 0.05, (length / 2 - body_len / 2 + body_len * 0.05, 0, height - 0.02)), finish(p.get("label_color", "#e0512a"), 0.1, 0.4))
        m.add("connector_housing", box(cap, width, height, (-length / 2 + nub + cap / 2, 0, 0), fillet=0.3), FINISH["black_plastic"])
        m.add("connector", box(nub, min(width * 0.7, 6.0), min(height * 0.75, 4.2), (-length / 2 + nub / 2, 0, height * 0.125), fillet=0.2), finish("#ecebe6", 0.0, 0.5))
        for i, y in enumerate((-1.2, 1.2), 1):
            m.add(f"connector_pin_{i}", box(0.3, 1.0, 1.6, (-length / 2 + 0.1, y, height * 0.5 - 0.8)), FINISH["gold"])
        return m
    # When the shop's length includes the plug (1S packs with a fixed BT2.0), the pack body is shorter.
    plug_len = CONNECTORS[plug][0] if plug and p.get("length_includes_connector") else 0.0
    body_len = length - plug_len
    x0 = length / 2 - body_len / 2 if plug_len else 0.0
    body = box(body_len, width, height, (x0, 0, 0), fillet=min(1.2, height * 0.22, width * 0.2))
    m.add("body", body, finish(p.get("wrap_color", "#1f2a44"), 0.1, 0.35))
    label_len = body_len * 0.62
    m.add("label", box(label_len, width * 0.86, 0.06, (x0 + body_len * 0.08, 0, height - 0.02)), finish(p.get("label_color", "#d7262b"), 0.1, 0.4))
    if p.get("cells", 1) > 1:
        for i in range(1, int(p["cells"])):
            m.add(f"cell_seam_{i}", box(body_len * 0.98, width + 0.04, 0.12, (x0, 0, height * i / p["cells"] - 0.06)), FINISH["black_plastic"])
    end = x0 - body_len / 2
    if not plug:
        return m
    if plug_len:
        for name, work, fin in connector(plug, (end + 0.01, 0, height / 2)):
            m.add(name, work, fin)
        return m
    lead = p.get("lead_len_mm", 30.0)
    wire_r = p.get("wire_r_mm", 0.9 if plug == "xt60" else 0.65 if plug == "xt30" else 0.4)
    z = height * 0.5
    for i, colour in enumerate(("wire_red", "wire_black")):
        y = (i - 0.5) * wire_r * 2.6
        path = [(end + 1.0, y, z), (end - 3.0, y, z), (end - lead * 0.6, y * 2.5, z + 0.5), (end - lead, y, z)]
        m.add(f"lead_{'red' if i == 0 else 'black'}", wire_path(path, wire_r), FINISH[colour])
    for name, work, fin in connector(plug, (end - lead, 0, z)):
        m.add(name, work, fin)
    if p.get("balance_lead") and p.get("cells", 1) > 1:
        bal = []
        for i in range(int(p["cells"]) + 1):
            y = width * 0.3 + i * 0.6
            bal.append(wire_path([(end + 1.0, y, height * 0.8), (end - 8.0, y, height * 0.8)], 0.28))
        for i, work in enumerate(bal):
            m.add(f"balance_wire_{i + 1}", work, FINISH["wire_black" if i == 0 else "wire_red" if i == len(bal) - 1 else "wire_white"])
        m.add("balance_plug", box(3.4, 0.6 * (len(bal)) + 1.2, 2.4, (end - 9.7, width * 0.3 + 0.3 * (len(bal) - 1), height * 0.8 - 1.2)), FINISH["white_plastic"])
    return m


def fpv_camera(p: dict) -> Model:
    m = Model(p["id"])
    length, width, height = p["length_mm"], p["width_mm"], p["height_mm"]
    lens_d = p.get("lens_d_mm", min(width, height) * 0.62)
    lens_len = p.get("lens_len_mm", length * 0.32)
    body_len = length - lens_len
    body = box(body_len, width, height, (-length / 2 + body_len / 2, 0, 0), fillet=min(1.0, width * 0.08))
    m.add("body", body, finish(p.get("color", "#1d1e21"), 0.3, 0.45))
    front = -length / 2 + body_len
    zc = height / 2
    barrel = cyl(lens_d / 2, lens_len * 0.82, (front, 0, zc), axis="X")
    m.add("lens_barrel", barrel, finish(p.get("lens_color", "#2a2b2e"), 0.5, 0.35))
    m.add("lens_ring", tube(lens_d / 2 * 0.98, lens_d * 0.3, lens_len * 0.18, (front + lens_len * 0.82, 0, zc), axis="X"), FINISH["anodised_black"])
    m.add("lens_glass", cyl(lens_d * 0.3, lens_len * 0.12, (front + lens_len * 0.84, 0, zc), axis="X"), FINISH["lens"])
    if p.get("side_bracket", True):
        for side in (-1, 1):
            m.add(f"mount_tab_{'left' if side < 0 else 'right'}", cyl(min(2.0, height * 0.14), 0.3, (front - body_len * 0.45, side * width / 2, zc), axis="Y"), FINISH["dark_steel"])
    m.add("rear_board", box(0.6, width * 0.82, height * 0.82, (-length / 2 + 0.3, 0, height * 0.09)), FINISH["pcb_black"])
    m.add("cable_socket", box(1.2, width * 0.42, 1.0, (-length / 2 + 0.9, 0, height * 0.2)), FINISH["white_plastic"])
    return m


def vtx(p: dict) -> Model:
    m = Model(p["id"])
    length, width, height = p["length_mm"], p["width_mm"], p["height_mm"]
    pcb_t = min(1.0, height * 0.3)
    board = rounded_plate(length, width, pcb_t, min(1.5, width * 0.08))
    for i, (x, y) in enumerate(_square(p.get("mount_mm")), 1):
        board = board.cut(cyl(p.get("mount_hole_d_mm", 2.0) / 2, pcb_t + 0.2, (x, y, -0.1)))
    m.add("board", board, finish(p.get("pcb_color", "#18191b"), 0.0, 0.45))
    for i, (x, y) in enumerate(_square(p.get("mount_mm")), 1):
        m.add(f"mount_hole_{i}", tube(p.get("mount_hole_d_mm", 2.0) / 2 + 0.5, p.get("mount_hole_d_mm", 2.0) / 2, 0.04, (x, y, pcb_t)), FINISH["gold"])
    shield = box(min(length * 0.5, 16), min(width * 0.6, 12), max(0.4, height - pcb_t - 0.05), (length * 0.08, -width * 0.05, pcb_t))
    m.add("rf_shield", shield, FINISH["tin"])
    m.add("ufl_connector", cyl(1.0, 1.25 if height - pcb_t > 1.3 else max(0.3, height - pcb_t - 0.1), (length * 0.38, width * 0.3, pcb_t)), FINISH["gold"])
    for i in range(5):
        m.add(f"pad_{i + 1}", box(0.9, 0.6, 0.05, (-length * 0.42, (i - 2) * 1.1, pcb_t)), FINISH["gold"])
    m.add("led", box(0.8, 0.5, 0.35, (-length * 0.2, width * 0.35, pcb_t)), FINISH["led_white"])
    return m


def _square(pattern):
    if not pattern:
        return []
    half = pattern / 2
    return [(half, half), (-half, half), (-half, -half), (half, -half)]


def whoop_frame(p: dict) -> Model:
    m = Model(p["id"])
    wheelbase = p["wheelbase_mm"]
    a = wheelbase / (2 * math.sqrt(2))
    overall = p.get("size_mm", [wheelbase / math.sqrt(2) + wheelbase * 0.6] * 2 + [16.0])
    duct_od = overall[0] - 2 * a
    height = overall[2]
    wall = max(0.8, duct_od * 0.022)
    duct_id = duct_od - 2 * wall
    colour = finish(p.get("color", "#1c1c1f"), 0.0, 0.5)
    mount_d = p.get("mount_diameter_mm", 6.6)
    centres = [(a, a), (-a, a), (-a, -a), (a, -a)]
    for i, (x, y) in enumerate(centres, 1):
        ring = tube(duct_od / 2, duct_id / 2, height, (x, y, 0))
        try:
            ring = ring.faces(">Z").edges().fillet(wall * 0.45)
        except Exception:
            pass
        m.add(f"frame_duct_{i}", ring, colour)
        hub_r = mount_d / 2 + 1.6
        floor = cyl(hub_r, 1.2, (x, y, 0))
        for j, (dx, dy) in enumerate(polar(3, mount_d / 2, 90)):
            floor = floor.cut(cyl(0.75, 1.4, (x + dx, y + dy, -0.1)))
        floor = floor.cut(cyl(1.6, 1.4, (x, y, -0.1)))
        for k in range(3):
            angle = math.radians(90 + 120 * k + 60)
            ex, ey = math.cos(angle), math.sin(angle)
            spoke_len = duct_id / 2 - hub_r + wall * 0.5
            spoke = box(spoke_len, 1.4, 1.2, (x + ex * (hub_r + spoke_len / 2), y + ey * (hub_r + spoke_len / 2), 0)).rotate(
                (x + ex * (hub_r + spoke_len / 2), y + ey * (hub_r + spoke_len / 2), 0), (x + ex * (hub_r + spoke_len / 2), y + ey * (hub_r + spoke_len / 2), 1), math.degrees(angle)
            )
            floor = floor.union(spoke)
        m.add(f"motor_mount_{i}", floor, colour)
    fc = p.get("mount_mm", 26)
    plate_side = fc + 5
    plate = rounded_plate(plate_side, plate_side, 1.6, 3.0, (0, 0, 0))
    plate = plate.cut(rounded_plate(plate_side * 0.45, plate_side * 0.45, 2.0, 1.5, (0, 0, -0.2)))
    for x, y in _square(fc):
        plate = plate.cut(cyl(0.8, 2, (x, y, -0.2)))
    m.add("frame_centre", plate, colour)
    for i, (x, y) in enumerate(_square(fc), 1):
        m.add(f"fc_mount_{i}", tube(1.4, 0.8, 2.6, (x, y, 1.6)), colour)
    for i, (x, y) in enumerate(centres, 1):
        length = math.hypot(x, y) - duct_od / 2 + wall * 1.5 - plate_side * 0.45
        mid = (math.hypot(x, y) - duct_od / 2 + plate_side * 0.6) / 2
        angle = math.degrees(math.atan2(y, x))
        beam = box(max(length, 1.0), 4.0, 1.6, (mid, 0, 0)).rotate((0, 0, 0), (0, 0, 1), angle)
        m.add(f"frame_arm_{i}", beam, colour)
    return m


def carbon_frame(p: dict) -> Model:
    m = Model(p["id"])
    wheelbase = p["wheelbase_mm"]
    a = wheelbase / (2 * math.sqrt(2))
    thick = p.get("arm_thickness_mm", 2.0)
    mount_d = p.get("mount_diameter_mm", 6.6)
    holes = int(p.get("motor_bolts", 4 if mount_d >= 9 else 3))
    pad_r = mount_d / 2 + max(2.2, mount_d * 0.3)
    arm_w = max(5.0, pad_r * 1.2)
    colour = FINISH["carbon"]
    fc = p.get("mount_mm", 26)
    body = rounded_plate(fc + 7, fc + 7, thick, 3.5)
    for x, y in _square(fc):
        body = body.cut(cyl(1.0, thick + 0.4, (x, y, -0.2)))
    body = body.cut(rounded_plate(fc * 0.4, fc * 0.4, thick + 0.4, 1.5, (0, 0, -0.2)))
    m.add("frame_centre", body, colour)
    for i, (x, y) in enumerate([(a, a), (-a, a), (-a, -a), (a, -a)], 1):
        angle = math.degrees(math.atan2(y, x))
        reach = math.hypot(x, y)
        arm = box(reach - fc * 0.3, arm_w, thick, ((reach + fc * 0.3) / 2, 0, 0)).rotate((0, 0, 0), (0, 0, 1), angle)
        pad = cyl(pad_r, thick, (x, y, 0))
        piece = arm.union(pad).cut(cyl(1.0 if mount_d < 12 else 2.6, thick + 0.4, (x, y, -0.2)))
        start = 45 if holes == 4 else 90
        for dx, dy in polar(holes, mount_d / 2, start + angle):
            piece = piece.cut(cyl(0.75 if mount_d < 9 else 1.0 if mount_d < 12 else 1.6, thick + 0.4, (x + dx, y + dy, -0.2)))
        m.add(f"frame_arm_{i}", piece, colour)
        m.add(f"motor_mount_{i}", tube(pad_r, pad_r - 0.3, 0.02, (x, y, thick)), colour)
    if p.get("top_plate", True):
        top = rounded_plate(fc + 4, fc * 1.2, max(1.0, thick * 0.5), 3.0, (0, 0, thick + 0.05 + p.get("standoff_mm", 0)))
        if p.get("standoff_mm"):
            for i, (x, y) in enumerate(_square(fc * 0.8), 1):
                m.add(f"standoff_{i}", cyl(1.5, p["standoff_mm"], (x, y, thick)), FINISH["aluminium"])
            m.add("frame_top", top, colour)
    return m


def canopy(p: dict) -> Model:
    m = Model(p["id"])
    length = p.get("length_mm", 34.0)
    width = p.get("width_mm", 22.0)
    height = p.get("height_mm", 18.0)
    shell = box(length, width, height, fillet=min(width, height) * 0.4)
    inner = box(length - 2.4, width - 2.4, height - 1.2, (0, 0, -0.01), fillet=min(width, height) * 0.35)
    shell = shell.cut(inner)
    shell = shell.cut(box(4, 15, 15, (length / 2 - 1, 0, height * 0.12)))
    m.add("shell", shell, finish(p.get("color", "#d23a2b"), 0.0, 0.7))
    return m
