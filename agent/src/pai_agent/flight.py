"""Flight performance of a quadcopter from its parts' published specs: the model behind physics_calc.

Every input is a catalog field (the motor's load-table row in `bench`, the propeller's diameter
and pitch, the pack's voltage, capacity and C rating, part sizes and masses); every output is an
estimate and `assumptions` says what was assumed. The model, in order:

- Thrust. Each motor gives its load-table thrust at 100 % throttle. Below the test voltage the
  thrust falls with the square of the voltage (rpm follows volts, thrust follows rpm squared); above
  it the bench figure stays, a higher voltage never invents thrust.
- Dynamic thrust. Thrust falls linearly with the airflow through the disc and reaches zero at the
  pitch speed, rpm times pitch (the rpm from the load table, else KV x volts x 0.8). Without a
  published pitch there is no pitch-speed limit and the result says so.
- Drag. Quadratic, 1/2 rho Cd A v^2, with the area seen by the wind interpolated between the
  front view (level) and the plan view (tilted 90 degrees) by the pitch angle; both areas are
  boxes around the frame, the motors, the pack and the stack sized from the part dimensions.
- Top speed. The fastest level flight where the drag balances m g tan(pitch) and the thrust left
  at that airflow still carries the weight: T(v sin pitch) cos pitch >= m g.
- Acceleration. From a hover at full throttle, holding altitude, a = g sqrt(TWR^2 - 1); the time
  to 90 % of top speed integrates the best feasible pitch at every speed.
- Climb. Full thrust straight up against weight, inflow loss and the plan-view drag.
- Turn. A level coordinated turn at half the top speed: the bank where thrust still carries the
  weight and the drag, turn rate = lateral acceleration / speed. Roll: from hover two motors go to
  full and two drop as much, about the inertia of the parts as placed.
- Endurance. The power for a thrust is read off the motor's published load table (log-log
  between its rows); a motor with only the 100 % row scales power with thrust^1.5 from it, the
  induced-power exponent. 80 % of the pack counts. Hover carries the weight, top speed carries
  m g / cos(pitch), full throttle is the 100 % row. The pack's C rating and the ESC rating are checked against the current.
"""

from __future__ import annotations

import math

G = 9.80665
RHO = 1.225  # sea-level air, kg/m3
USABLE = 0.8  # share of the pack's capacity used, as the hover estimate always assumed
HOVER_TWR = 1.05
CD_FRONT = 1.05  # a bluff box
CD_TOP = 1.2  # a flat plate broadside
LOADED_RPM = 0.8  # loaded rpm as a share of KV x volts when the load table gives no rpm
PROP_PITCH_SPEED_MARGIN = 1.0


def _num(part: dict, key: str, default: float | None = None) -> float | None:
    try:
        value = float(part.get(key))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def bench(motor: dict) -> dict:
    """The motor's 100 % load-table row; older catalog motors only have thrust_g and g/W."""

    row = dict(motor.get("bench") or {})
    row.setdefault("thrust_g", _num(motor, "thrust_g", 0.0))
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


def pitch_speed_ms(motor: dict, propeller: dict, pack_v: float) -> tuple[float | None, str]:
    """Air speed at which the propeller stops making thrust: rpm x pitch. None without a pitch."""

    pitch_in = _num(propeller, "pitch_in")
    if not pitch_in:
        return None, "The propeller has no published pitch, so the top speed has no prop-speed limit (an upper bound)."
    row = bench(motor)
    rpm = _num(row, "rpm")
    test_v = _num(row, "voltage_v")
    if rpm and test_v and pack_v:
        rpm *= min(1.0, pack_v / test_v)
        source = "the load table's " + f"{rpm:.0f}" + " rpm"
    else:
        kv = _num(motor, "kv", 0.0) or 0.0
        rpm = kv * pack_v * LOADED_RPM
        source = f"{rpm:.0f}" + " rpm, estimated as KV x volts x " + f"{LOADED_RPM:g}"
    speed = rpm / 60.0 * pitch_in * 0.0254 * PROP_PITCH_SPEED_MARGIN
    return speed, "Pitch speed " + f"{speed:.1f}" + " m/s from " + source + " and the " + f"{pitch_in:g}" + " in pitch."


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
    """Thrust at an airflow, drag at an attitude: the two curves every result below is read from."""

    def __init__(self, mass_kg: float, thrust_n: float, pitch_speed: float | None, front_m2: float, top_m2: float) -> None:
        self.m = mass_kg
        self.t0 = thrust_n
        self.vp = pitch_speed
        self.front = front_m2
        self.top = top_m2

    def thrust(self, inflow: float) -> float:
        if self.vp is None:
            return self.t0
        return self.t0 * max(0.0, 1.0 - max(0.0, inflow) / self.vp)

    def drag_area(self, tilt: float) -> float:
        return CD_FRONT * self.front * math.cos(tilt) + CD_TOP * self.top * math.sin(tilt)

    def drag(self, speed: float, tilt: float) -> float:
        return 0.5 * RHO * self.drag_area(tilt) * speed * speed

    def level_speed(self, tilt: float) -> float:
        """The speed where drag balances the horizontal thrust at this pitch, holding altitude."""

        return math.sqrt(2.0 * self.m * G * math.tan(tilt) / (RHO * self.drag_area(tilt)))

    def feasible(self, speed: float, tilt: float) -> bool:
        return self.thrust(speed * math.sin(tilt)) * math.cos(tilt) >= self.m * G

    def top_speed(self) -> tuple[float, float]:
        best = (0.0, 0.0)
        for step in range(1, 890):
            tilt = math.radians(step / 10.0)
            speed = self.level_speed(tilt)
            if self.feasible(speed, tilt) and speed > best[0]:
                best = (speed, tilt)
        return best

    def accel_at(self, speed: float) -> float:
        """Best horizontal acceleration at this speed while holding altitude."""

        best = 0.0
        for step in range(1, 890, 2):
            tilt = math.radians(step / 10.0)
            if not self.feasible(speed, tilt):
                continue
            best = max(best, G * math.tan(tilt) - self.drag(speed, tilt) / self.m)
        return best

    def time_to(self, target: float) -> float:
        elapsed = 0.0
        steps = 60
        dv = target / steps
        for index in range(steps):
            a = self.accel_at((index + 0.5) * dv)
            if a <= 1e-6:
                return math.inf
            elapsed += dv / a
        return elapsed

    def climb_rate(self) -> float:
        low, high = 0.0, 200.0
        for _ in range(60):
            mid = (low + high) / 2.0
            surplus = self.thrust(mid) - self.m * G - 0.5 * RHO * CD_TOP * self.top * mid * mid
            if surplus > 0:
                low = mid
            else:
                high = mid
        return low

    def turn(self, speed: float) -> tuple[float, float]:
        """Sustained level turn at `speed`: (turn rate rad/s, radius m), bank limited by the thrust
        left after the drag and the weight."""

        best = 0.0
        # The disc leans forward just enough to hold the speed against the drag.
        lean = math.atan2(self.drag(speed, 0.3), self.m * G)
        drag = self.drag(speed, lean)
        available = self.thrust(speed * math.sin(lean))
        for step in range(1, 890, 2):
            bank = math.radians(step / 10.0)
            if math.hypot(self.m * G / math.cos(bank), drag) <= available:
                best = bank
        lateral = G * math.tan(best)
        if speed <= 0 or lateral <= 0:
            return 0.0, math.inf
        return lateral / speed, speed * speed / lateral


def performance(selected: dict, frame_mass_g: float, arm_mm: float, weight_g: float) -> dict:
    """Every performance number for the chosen parts, with the assumptions behind them."""

    motor = selected["motor"]
    propeller = selected["propeller"]
    battery = selected["battery"]
    controller = selected["flight_controller"]
    qty = int(motor.get("bom_qty", 4))
    pack_v = float(battery["voltage_v"])
    per_motor_g, scaled = thrust_per_motor_g(motor, pack_v)
    total_g = per_motor_g * qty
    assumptions = [
        "Sea-level air, " + f"{RHO:g}" + " kg/m3; drag coefficients " + f"{CD_FRONT:g}" + " level and " + f"{CD_TOP:g}" + " broadside on boxes sized from the parts.",
        "Thrust falls linearly with the airflow through the disc to zero at the pitch speed.",
    ]
    if scaled:
        assumptions.append(scaled)
    vp, vp_note = pitch_speed_ms(motor, propeller, pack_v)
    assumptions.append(vp_note)
    shape, notes = geometry(selected, arm_mm)
    assumptions += notes
    mass = weight_g / 1000.0
    model = Model(mass, total_g * G / 1000.0, vp, shape["front_m2"], shape["top_m2"])
    twr = total_g / weight_g if weight_g > 0 else 0.0
    out = {
        "thrust_g": round(total_g, 1),
        "frontal_area_cm2": round(shape["front_m2"] * 1e4, 1),
        "plan_area_cm2": round(shape["top_m2"] * 1e4, 1),
        "pitch_speed_mps": round(vp, 1) if vp else None,
        "inertia_kg_m2": inertia(selected, frame_mass_g, shape["arm_m"], shape["pack_mm"]),
        "arm_length_mm": round(arm_mm, 1),
        "estimate": True,
    }
    if twr < HOVER_TWR:
        out.update({"top_speed_mps": 0.0, "top_speed_kmh": 0.0, "accel_mps2": 0.0, "climb_rate_mps": 0.0, "turn_rate_dps": 0.0,
                    "flight_time_full_speed_min": 0.0, "flight_time_full_throttle_min": 0.0})
        out["assumptions"] = assumptions + ["Thrust-to-weight under " + f"{HOVER_TWR:g}" + ": it cannot hover, so it cannot fly anywhere."]
        return out

    top, tilt = model.top_speed()
    accel = G * math.sqrt(max(0.0, twr * twr - 1.0))
    climb_accel = G * (twr - 1.0)
    time_90 = model.time_to(0.9 * top) if top > 0 else math.inf
    cruise = 0.5 * top
    turn_rate, radius = model.turn(cruise)
    hover_each = weight_g / qty
    delta = min(per_motor_g - hover_each, hover_each) * G / 1000.0
    roll_torque = 2.0 * math.sqrt(2.0) * delta * shape["arm_m"]
    ixx = out["inertia_kg_m2"][0]
    roll_accel = roll_torque / ixx if ixx > 0 else 0.0
    flip_s = 2.0 * math.sqrt(math.pi / roll_accel) if roll_accel > 0 else math.inf

    row = bench(motor)
    full_w_each = float(row.get("power_w") or 0.0)
    test_v = _num(row, "voltage_v")
    if full_w_each and test_v and pack_v < 0.9 * test_v:
        full_w_each *= (pack_v / test_v) ** 3  # prop load power follows rpm cubed
    usable_ah = float(battery["capacity_mah"]) / 1000.0 * USABLE
    full_a = full_w_each * qty / pack_v if pack_v > 0 else 0.0
    full_min = usable_ah / full_a * 60.0 if full_a > 0 else 0.0
    cruise_each_g = min(per_motor_g, weight_g / math.cos(tilt) / qty) if tilt < math.pi / 2 else per_motor_g
    cruise_w, source = motor_power_w(motor, cruise_each_g)
    cruise_a = cruise_w * qty / pack_v if pack_v > 0 else 0.0
    cruise_min = usable_ah / cruise_a * 60.0 if cruise_a > 0 else 0.0
    assumptions.append("Motor power from the " + source + "; 80 % of the pack's capacity is usable.")

    warnings = []
    c_rating = _num(battery, "c_rating")
    if c_rating and full_a:
        limit_a = c_rating * float(battery["capacity_mah"]) / 1000.0
        if full_a > limit_a:
            warnings.append(
                "At full throttle the motors pull " + f"{full_a:.0f}" + " A; the pack's " + f"{c_rating:g}" + "C rating allows " + f"{limit_a:.0f}" + " A, so the voltage sags and the top speed is lower than computed."
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
            "top_speed_pitch_deg": round(math.degrees(tilt), 1),
            "accel_mps2": round(accel, 1),
            "accel_g": round(accel / G, 2),
            "time_to_90pct_s": round(time_90, 2) if math.isfinite(time_90) else None,
            "climb_accel_mps2": round(climb_accel, 1),
            "climb_rate_mps": round(model.climb_rate(), 1),
            "turn_speed_mps": round(cruise, 1),
            "turn_rate_dps": round(math.degrees(turn_rate), 0),
            "turn_radius_m": round(radius, 2) if math.isfinite(radius) else None,
            "roll_accel_dps2": round(math.degrees(roll_accel), 0),
            "flip_time_s": round(flip_s, 3) if math.isfinite(flip_s) else None,
            "full_throttle_current_a": round(full_a, 1),
            "flight_time_full_throttle_min": round(full_min, 1),
            "flight_time_full_speed_min": round(cruise_min, 1),
            "assumptions": assumptions,
            "warnings": warnings,
        }
    )
    return out
