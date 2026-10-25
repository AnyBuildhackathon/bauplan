"""Flight performance of a quadcopter from its parts' published specs: the model behind physics_calc.

Every input is a catalog field (the motor's load-table row in `bench`, the propeller's diameter
and pitch, the pack's voltage, capacity and C rating, part sizes and masses); every output is an
estimate and `assumptions` says what was assumed. It reads the same airframe the MuJoCo missions
fly (`mission_sim.airframe` on `drone_geometry.geometry`), so the card's top speed and turn rate and
the speed run and hard turn describe one machine with one thrust, pitch-speed and drag model:

- Thrust. Each motor gives its load-table thrust at 100 % throttle. Below the test voltage the
  thrust falls with the square of the voltage (rpm follows volts, thrust follows rpm squared); above
  it the bench figure stays, a higher voltage never invents thrust.
- Dynamic thrust and the pack. The power train in `plant.py`, the one the missions fly: thrust
  against the airflow through the disc follows the nearest measured propeller curve (UIUC
  database) with the motor fitted to its load table spinning up as the prop unloads, on a pack
  whose voltage sags with the current drawn (internal resistance from its C rating) and drains over
  the flight. The card's top speed is on the fresh pack; `top_speed_end_kmh` is the same flight at
  the end of the usable charge.
- Drag. Body drag 1/2 rho Cd A v^2 on the parts' outlines, Cd 1.0 edgewise and 1.2 through the disc
  plane, plus the rotors' H force (thrust x in-plane air speed / tip speed).
- Top speed. The fastest level flight where some pitch up to 70 degrees holds altitude on at most
  95 % of the thrust left at that airflow and still pushes forward, as the missions' controller flies.
- Acceleration. From a hover on 95 % thrust, tilt capped at 70 degrees; the time to 90 % of top speed
  integrates the best feasible pitch at every speed.
- Climb. 95 % thrust straight up against weight, inflow loss and the plan-view drag.
- Turn. A level turn at the hard-turn mission's 8 m/s (or 90 % of top speed when slower): the
  lateral acceleration left after weight and drag gives the steady rate (lateral acceleration /
  speed); like the mission, the turn rate is 90 degrees over the time to turn them, the roll-in
  included (bank and stop the roll at full differential thrust, plus 1.5 motor lags). Roll: from
  hover two motors go to full and two drop as much, about the inertia of the parts as placed.
- Endurance. The power for a thrust is read off the motor's published load table (log-log
  between its rows); a motor with only the 100 % row scales power with thrust^1.5 from it, the
  induced-power exponent; the plant adds how it changes with airspeed. Hover carries the weight,
  top speed carries the thrust that holds it there, full throttle is all motors at 100 % as the
  pack sags. Each flight drains the pack step by step at the current that power takes from the
  sagging voltage, until 80 % of the capacity is used or a cell falls under 3.3 V under load. The
  pack's C rating and the ESC rating are checked against the current.
"""

from __future__ import annotations

import math

import numpy as np

G = 9.80665
RHO = 1.225  # sea-level air, kg/m3
USABLE = 0.8  # share of the pack's capacity used, as the hover estimate always assumed
HOVER_TWR = 1.05
# The missions' airframe and controller (mission_sim): the same numbers on both sides.
CD_SIDE = 1.0
CD_TOP = 1.2
TILT_MAX = math.radians(70.0)
THRUST_USE = 0.95
TURN_SPEED = 8.0


def _num(part: dict, key: str, default: float | None = None) -> float | None:
    try:
        value = float(part.get(key))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def bench(motor: dict) -> dict:
    """The motor's 100 % load-table row; older catalog motors only have thrust_g and g/W."""

    row = dict(motor.get("bench") or {})
    # thrust_g is the catalog's 100 % figure and the load table's last row; it wins if they differ.
    row["thrust_g"] = _num(motor, "thrust_g", row.get("thrust_g") or 0.0)
    if not row.get("power_w") and _num(motor, "efficiency_g_per_w"):
        row["power_w"] = float(row["thrust_g"]) / float(motor["efficiency_g_per_w"])
    return row


def motor_power_w(motor: dict, thrust_g: float) -> tuple[float, str]:
    """Electrical watts one motor draws for `thrust_g`, from its load table when it has one."""

    row = bench(motor)
    peak_t = float(row.get("thrust_g") or 0.0)
    peak_w = float(row.get("power_w") or 0.0)
    if thrust_g <= 0 or peak_t <= 0 or peak_w <= 0:
        return 0.0, "none"
    table = sorted(([float(r[1]), float(r[2])] for r in row.get("load_table") or [] if r[1] > 0 and r[2] > 0), key=lambda r: r[0])
    if len(table) >= 2:
        if thrust_g >= table[-1][0]:
            return table[-1][1], "load table"
        low = table[0]
        if thrust_g <= low[0]:
            # Under the first row: the induced-power exponent from it.
            return low[1] * (thrust_g / low[0]) ** 1.5, "load table"
        for (t0, w0), (t1, w1) in zip(table, table[1:]):
            if t0 <= thrust_g <= t1:
                slope = math.log(w1 / w0) / math.log(t1 / t0)
                return w0 * (thrust_g / t0) ** slope, "load table"
    return peak_w * min(1.0, thrust_g / peak_t) ** 1.5, "100 % row, thrust^1.5"


def thrust_per_motor_g(motor: dict, pack_v: float) -> tuple[float, str | None]:
    """Static thrust at 100 % on this pack, and a note when the voltage changed it."""

    row = bench(motor)
    thrust = float(row.get("thrust_g") or 0.0)
    test_v = _num(row, "voltage_v")
    if test_v and pack_v and pack_v < 0.9 * test_v:
        scale = (pack_v / test_v) ** 2
        return thrust * scale, (
            "The pack's " + f"{pack_v:.1f}" + " V is below the " + f"{test_v:.1f}" + " V of the motor's load table: thrust x "
            + f"{scale:.2f}" + " (rpm follows volts, thrust follows rpm squared)."
        )
    return thrust, None


def _box(part: dict, keys=("length_mm", "width_mm", "height_mm")) -> list[float] | None:
    if all(_num(part, key) for key in keys):
        return [float(part[key]) for key in keys]
    size = part.get("size_mm")
    if isinstance(size, list) and len(size) == 3:
        return [float(v) for v in size]
    return None


def geometry(selected: dict, arm_mm: float) -> tuple[dict, list[str]]:
    """Areas, the motor lever and the part layout, from the part dimensions where they exist."""

    notes: list[str] = []
    motor = selected["motor"]
    propeller = selected["propeller"]
    battery = selected["battery"]
    controller = selected["flight_controller"]
    frame = selected["frame"]
    motor_d = _num(motor, "diameter_mm") or 0.9 * (float(str(motor.get("size", "1103"))[:2]) if str(motor.get("size", "")).isdigit() else 11.0)
    motor_h = _num(motor, "height_mm") or motor_d
    prop_d = _num(propeller, "diameter_mm") or 2.0 * arm_mm / 1.6
    pack = _box(battery)
    if pack is None:
        pack = [60.0, 18.0, 8.0]
        notes.append("The pack has no published size; 60 x 18 x 8 mm assumed for its drag.")
    board = _num(controller, "board_mm") or (_num(controller, "mount_mm") or 26.0) + 4.0
    stack_h = 8.0 + (6.0 if selected.get("vtx") else 0.0)
    arm_w = max(4.0, motor_d * 0.5)
    arm_t = _num(frame, "arm_thickness_mm") or 3.0
    span = 2.0 * arm_mm
    # Front view: pack and stack across the body, two motors and the arm edges.
    front = pack[1] * pack[2] + board * stack_h + 2.0 * motor_d * motor_h + 2.0 * span * arm_t
    # Plan view: pack and board, the four motors and the arms; the prop discs are not a plate.
    top = pack[0] * pack[1] + board * board + 4.0 * math.pi * (motor_d / 2.0) ** 2 + 2.0 * span * arm_w
    if frame.get("ducted"):
        duct_h = 8.0
        front += 2.0 * (prop_d + 4.0) * duct_h
        top += 4.0 * math.pi * (prop_d / 2.0 + 2.0) * 2.0
        notes.append("Ducted frame: the ducts add front area, " + f"{duct_h:g}" + " mm tall assumed.")
    return {
        "front_m2": front * 1e-6,
        "top_m2": top * 1e-6,
        "arm_m": arm_mm / 1000.0,
        "pack_mm": pack,
        "prop_d_mm": prop_d,
        "motor_d_mm": motor_d,
        "motor_h_mm": motor_h,
    }, notes


def inertia(selected: dict, frame_mass_g: float, arm_m: float, pack_mm: list[float]) -> list[float]:
    """Ixx, Iyy, Izz in kg m^2: motors and props as points on the X, the pack as a box under the
    centre, the frame as a thin plate across its span, the rest as a point at the centre."""

    motor = selected["motor"]
    propeller = selected["propeller"]
    battery = selected["battery"]
    each = (float(motor["mass_g"]) + float(propeller["mass_g"])) / 1000.0
    lever = arm_m / math.sqrt(2.0)
    ixx = iyy = 4.0 * each * lever**2
    izz = 4.0 * each * arm_m**2
    mb = float(battery["mass_g"]) / 1000.0
    length, width, height = (v / 1000.0 for v in pack_mm)
    drop = height / 2.0 + 0.004  # the pack hangs under the plate
    ixx += mb * (length**2 + height**2) / 12.0 + mb * drop**2
    iyy += mb * (width**2 + height**2) / 12.0 + mb * drop**2
    izz += mb * (length**2 + width**2) / 12.0
    mf = frame_mass_g / 1000.0
    side = 2.0 * arm_m / math.sqrt(2.0)
    ixx += mf * side**2 / 12.0
    iyy += mf * side**2 / 12.0
    izz += mf * side**2 / 6.0
    return [round(ixx, 9), round(iyy, 9), round(izz, 9)]


class Model:
    """The missions' forces in steady flight: thrust that fades with inflow, rotor H force, body drag.

    `curve` is (airspeed through the disc, total full-throttle thrust) from the plant; without it
    the thrust fades linearly to zero at `pitch_speed`."""

    def __init__(self, mass_kg: float, thrust_n: float, pitch_speed: float, tip_speed: float, cda_side: float, cda_top: float, curve=None) -> None:
        self.m = mass_kg
        self.t0 = thrust_n
        self.vp = pitch_speed
        self.tip = tip_speed
        self.cda_side = cda_side
        self.cda_top = cda_top
        self.curve = curve

    def t_max(self, axial: float) -> float:
        if self.curve is not None:
            return float(np.interp(axial, self.curve[0], self.curve[1]))
        return self.t0 * min(1.2, max(0.0, 1.0 - axial / self.vp))

    def level(self, speed: float, tilt: float) -> float | None:
        """Forward force in level flight at this pitch, or None when the thrust cannot hold altitude."""

        cos, sin = math.cos(tilt), math.sin(tilt)
        drag_x = 0.5 * RHO * self.cda_side * speed * speed * cos  # along the body x axis, backwards
        drag_z = 0.5 * RHO * self.cda_top * speed * speed * sin  # along the body z axis, downwards
        lift = cos + speed * cos * sin / self.tip
        thrust = (self.m * G + drag_z * cos - drag_x * sin) / lift
        if thrust < 0 or thrust > THRUST_USE * self.t_max(speed * sin):
            return None
        rotor_h = thrust * speed * cos / self.tip
        return thrust * sin - (rotor_h + drag_x) * cos - drag_z * sin

    def push(self, speed: float) -> float | None:
        """The best forward force at this speed over every pitch up to the tilt limit."""

        best = None
        for step in range(0, 701, 5):
            forward = self.level(speed, math.radians(step / 10.0))
            if forward is not None and (best is None or forward > best):
                best = forward
        return best

    def top_speed(self) -> float:
        low, high = 0.0, max(5.0, self.vp * 1.2)
        if (self.push(0.0) or -1.0) < 0:
            return 0.0
        for _ in range(40):
            mid = (low + high) / 2.0
            push = self.push(mid)
            if push is not None and push >= 0:
                low = mid
            else:
                high = mid
        return low

    def tilt_at(self, speed: float) -> float:
        """The pitch that holds this speed in level flight (forward force zero)."""

        best, err = 0.0, math.inf
        for step in range(0, 701, 2):
            tilt = math.radians(step / 10.0)
            forward = self.level(speed, tilt)
            if forward is not None and abs(forward) < err:
                best, err = tilt, abs(forward)
        return best

    def time_to(self, target: float) -> float:
        elapsed = 0.0
        steps = 40
        dv = target / steps
        for index in range(steps):
            push = self.push((index + 0.5) * dv)
            if not push or push <= 1e-9:
                return math.inf
            elapsed += dv / (push / self.m)
        return elapsed

    def climb_rate(self) -> float:
        low, high = 0.0, 200.0
        for _ in range(60):
            mid = (low + high) / 2.0
            surplus = THRUST_USE * self.t_max(mid) - self.m * G - 0.5 * RHO * self.cda_top * mid * mid
            if surplus > 0:
                low = mid
            else:
                high = mid
        return low

    def turn(self, speed: float) -> tuple[float, float]:
        """Sustained level turn at `speed`: (turn rate rad/s, radius m)."""

        tilt = self.tilt_at(speed)
        available = THRUST_USE * self.t_max(speed * math.sin(tilt))
        drag = 0.5 * RHO * self.cda_side * speed * speed
        weight = self.m * G
        side = math.sqrt(max(0.0, available * available - weight * weight - drag * drag))
        side = min(side, weight * math.tan(TILT_MAX))
        lateral = side / self.m
        if speed <= 0 or lateral <= 0:
            return 0.0, math.inf
        return lateral / speed, speed * speed / lateral


def _airframe(state, selected: dict, weight_g: float) -> tuple[dict, list[str]]:
    """The missions' airframe for these parts; the same rules on the part outlines when the CAD
    geometry cannot be built (a part without the dimensions it needs)."""

    motor = selected["motor"]
    try:
        from pai_agent.drone_geometry import geometry as drone_geometry
        from pai_agent.mission_sim import airframe

        frame = airframe(drone_geometry(state), selected)
        return {
            "plant": frame["plant"],
            "pitch_speed": frame["pitch_speed"],
            "tip_speed": frame["tip_speed"],
            "cda_side": frame["cda_side"],
            "cda_top": frame["cda_top"],
            "tau": frame["tau"],
            "source": "the airframe the MuJoCo missions fly",
        }, []
    except Exception as exc:  # the geometry lacks a dimension; the outline estimate takes over
        from pai_agent.mission_sim import motor_lag_s
        from pai_agent.plant import Plant

        shape, notes = geometry(selected, arm_length(state))
        plant = Plant(motor, dict(selected["propeller"], diameter_mm=shape["prop_d_mm"]), selected["battery"], int(motor.get("bom_qty", 4)))
        return {
            "plant": plant,
            "pitch_speed": plant.zero_thrust_speed(1.0),
            "tip_speed": plant.tip_speed(1.0),
            "cda_side": CD_SIDE * shape["front_m2"],
            "cda_top": CD_TOP * shape["top_m2"],
            "tau": motor_lag_s(shape["prop_d_mm"]),
            "source": "part outlines (" + str(exc)[:80] + ")",
        }, notes


def arm_length(state) -> float:
    """Centre to motor shaft: the built CAD frame, else the frame's wheelbase, else what the props need."""

    from pai_agent.drone_geometry import frame_arm_mm

    built = (getattr(state, "cad_params", None) or {}).get("arm_length_mm")
    if built:
        return float(built)
    return frame_arm_mm(state.selected)


def performance(state, weight_g: float) -> dict:
    """Every performance number for the chosen parts, with the assumptions behind them."""

    selected = state.selected
    motor = selected["motor"]
    battery = selected["battery"]
    controller = selected["flight_controller"]
    frame_part = selected["frame"]
    qty = int(motor.get("bom_qty", 4))
    pack_v = float(battery["voltage_v"])
    per_motor_g, scaled = thrust_per_motor_g(motor, pack_v)
    total_g = per_motor_g * qty
    air, notes = _airframe(state, selected, weight_g)
    plant = air["plant"]
    fresh = plant.full_throttle(1.0)
    assumptions = [
        "Same model as the MuJoCo missions, from " + air["source"] + ": sea-level air, body drag Cd " + f"{CD_SIDE:g}" + " edgewise and " + f"{CD_TOP:g}"
        + " through the disc on the parts' outlines, rotor H force, 95 % thrust and 70 degrees tilt at most.",
        "Full throttle on the fresh pack: " + f"{fresh['thrust_n'] * qty / G * 1000.0:.0f}" + " g of thrust, the pack sagging from " + f"{plant.pack.ocv(1.0):.2f}"
        + " to " + f"{fresh['v_pack']:.2f}" + " V at " + f"{fresh['current_a']:.0f}" + " A (internal resistance " + f"{plant.pack.r * 1000.0:.1f}"
        + " mOhm from its " + f"{plant.pack.c_rating:g}" + "C rating). Thrust stops at " + f"{air['pitch_speed'] * 3.6:.0f}" + " km/h through the disc.",
        *plant.notes,
    ]
    if scaled:
        assumptions.append(scaled)
    assumptions += notes
    arm_mm = arm_length(state)
    pack_mm = _box(battery) or [60.0, 18.0, 8.0]
    frame_mass_g = float(state.frame_mass_g if getattr(state, "frame_mass_g", None) is not None else frame_part["mass_g"])
    mass = weight_g / 1000.0
    curve = plant.thrust_curve(1.0)
    model = Model(mass, float(curve[1][0]), air["pitch_speed"], air["tip_speed"], air["cda_side"], air["cda_top"], curve=curve)
    twr = total_g / weight_g if weight_g > 0 else 0.0
    out = {
        "thrust_g": round(total_g, 1),
        "thrust_full_fresh_g": round(fresh["thrust_n"] * qty / G * 1000.0, 1),
        "pack_sag_v": round(plant.pack.ocv(1.0) - fresh["v_pack"], 2),
        "drag_area_side_cm2": round(air["cda_side"] * 1e4, 1),
        "drag_area_top_cm2": round(air["cda_top"] * 1e4, 1),
        "pitch_speed_mps": round(air["pitch_speed"], 1),
        "inertia_kg_m2": inertia(selected, frame_mass_g, arm_mm / 1000.0, pack_mm),
        "arm_length_mm": round(arm_mm, 1),
        "estimate": True,
    }
    if twr * THRUST_USE < 1.0 or model.push(0.0) is None:
        out.update({"top_speed_mps": 0.0, "top_speed_kmh": 0.0, "accel_mps2": 0.0, "climb_rate_mps": 0.0, "turn_rate_dps": 0.0,
                    "flight_time_full_speed_min": 0.0, "flight_time_full_throttle_min": 0.0})
        out["assumptions"] = assumptions + ["Thrust-to-weight under " + f"{1.0 / THRUST_USE:.2f}" + ": on 95 % thrust it cannot hold a hover, so it cannot fly anywhere."]
        out["warnings"] = []
        return out

    top = model.top_speed()
    tilt = model.tilt_at(top)
    hover_g = THRUST_USE * twr
    accel = min(G * math.sqrt(max(0.0, hover_g * hover_g - 1.0)), G * math.tan(TILT_MAX))
    time_90 = model.time_to(0.9 * top) if top > 0 else math.inf
    turn_speed = min(TURN_SPEED, 0.9 * top)
    turn_rate, radius = model.turn(turn_speed)
    hover_each = weight_g / qty
    delta = min(per_motor_g - hover_each, hover_each) * G / 1000.0
    roll_torque = 2.0 * math.sqrt(2.0) * delta * arm_mm / 1000.0
    ixx = out["inertia_kg_m2"][0]
    roll_accel = roll_torque / ixx if ixx > 0 else 0.0
    flip_s = 2.0 * math.sqrt(math.pi / roll_accel) if roll_accel > 0 else math.inf
    # The hard-turn mission times a 90 degree heading change, rolling in included: the steady rate
    # plus the time to bank (accelerate and stop the roll) and the motors' lag.
    steady_rate = turn_rate
    if turn_rate > 0 and roll_accel > 0:
        bank = math.atan2(turn_rate * turn_speed, G)
        roll_in = 2.0 * math.sqrt(bank / roll_accel) + 1.5 * air["tau"]
        turn_rate = (math.pi / 2.0) / ((math.pi / 2.0) / turn_rate + roll_in)

    # Endurance on the sagging, draining pack.
    full_min, _soc = plant.endurance_min(lambda soc, v: plant.full_throttle(soc)["power_w"])
    full_a = fresh["current_a"]
    # At top speed the motors make the thrust that holds altitude at that pitch.
    cos, sin = math.cos(tilt), math.sin(tilt)
    drag_x = 0.5 * RHO * air["cda_side"] * top * top * cos
    drag_z = 0.5 * RHO * air["cda_top"] * top * top * sin
    held_n = (mass * G + drag_z * cos - drag_x * sin) / (cos + top * cos * sin / air["tip_speed"]) if top > 0 else mass * G
    cruise_n = max(hover_each * G / 1000.0, held_n / qty)
    axial = top * sin

    def cruise(soc: float, v: float) -> float:
        thrust = min(cruise_n, float(plant.thrust_max(v, axial)))
        return qty * float(plant.power(thrust, axial))

    cruise_min, soc_end = plant.endurance_min(cruise)
    hover_min, _soc = plant.endurance_min(lambda soc, v: qty * float(plant.power(hover_each * G / 1000.0, 0.0)))
    tired = Model(mass, 0.0, air["pitch_speed"], air["tip_speed"], air["cda_side"], air["cda_top"], curve=plant.thrust_curve(soc_end))
    top_end = tired.top_speed() if tired.push(0.0) is not None else 0.0
    _w, source = motor_power_w(motor, hover_each)
    assumptions.append(
        "Motor power from the " + source + "; each flight drains the pack until 80 % of it is used or a cell sags under 3.3 V. At the end of a full-speed flight the top speed is "
        + f"{top_end * 3.6:.0f}" + " km/h."
    )

    warnings = []
    row = bench(motor)
    test_v = _num(row, "voltage_v")
    c_rating = _num(battery, "c_rating")
    if c_rating and full_a:
        limit_a = c_rating * float(battery["capacity_mah"]) / 1000.0
        if full_a > limit_a:
            warnings.append(
                "At full throttle the motors pull " + f"{full_a:.0f}" + " A; the pack's " + f"{c_rating:g}" + "C rating allows " + f"{limit_a:.0f}" + " A, so it runs past its rating."
            )
    motor_a = _num(row, "current_a")
    esc_a = _num(controller, "esc_peak_a") or _num(controller, "esc_continuous_a")
    if motor_a and esc_a:
        if test_v and pack_v > test_v * 1.1:
            motor_a *= pack_v / test_v
        if motor_a > esc_a:
            warnings.append(
                "Each motor pulls about " + f"{motor_a:.1f}" + " A at full throttle; the " + str(controller.get("name")) + " ESC is rated " + f"{esc_a:g}" + " A."
            )
    out.update(
        {
            "top_speed_mps": round(top, 1),
            "top_speed_kmh": round(top * 3.6, 1),
            "top_speed_end_kmh": round(top_end * 3.6, 1),
            "top_speed_pitch_deg": round(math.degrees(tilt), 1),
            "accel_mps2": round(accel, 1),
            "accel_g": round(accel / G, 2),
            "time_to_90pct_s": round(time_90, 2) if math.isfinite(time_90) else None,
            "climb_rate_mps": round(model.climb_rate(), 1),
            "turn_speed_mps": round(turn_speed, 1),
            "turn_rate_dps": round(math.degrees(turn_rate), 0),
            "turn_rate_steady_dps": round(math.degrees(steady_rate), 0),
            "turn_radius_m": round(radius, 2) if math.isfinite(radius) else None,
            "roll_accel_dps2": round(math.degrees(roll_accel), 0),
            "flip_time_s": round(flip_s, 3) if math.isfinite(flip_s) else None,
            "full_throttle_current_a": round(full_a, 1),
            "flight_time_hover_min": round(hover_min, 1),
            "flight_time_full_throttle_min": round(full_min, 1),
            "flight_time_full_speed_min": round(cruise_min, 1),
            "assumptions": assumptions,
            "warnings": warnings,
        }
    )
    return out
