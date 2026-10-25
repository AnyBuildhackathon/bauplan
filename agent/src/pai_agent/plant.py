"""The drone's power train and senses as the missions fly them: pack, motor, propeller, ground, camera.

Every number comes from a part's published spec or from a cited measurement; what had to be
assumed is listed in `Plant.notes` and `camera_spec(...)["assumed"]`.

- Propeller. Thrust and power coefficients against advance ratio J = V / (n D), measured in the
  UIUC propeller database (Brandt, Deters, Dantsker and Selig, volume 2, small props at the highest
  rpm tested). The chosen prop takes the documented prop closest to it: the same blade count
  first, then the nearest pitch to diameter ratio, and its curve is stretched along J by the ratio
  of the two pitch ratios (J / (P/D) is the similarity variable). Past the last measured point the
  curve continues on the slope of its last two points. The level of the curve, CT0 and CP0, comes
  from the motor maker's 100 % load-table row, so the static thrust is the published one.
- Motor. A DC motor: back EMF from its KV and a winding resistance that makes the 100 % row come
  out at its published rpm, voltage and current, R = (V - rpm / KV) / I. The motor and the
  propeller settle where the motor's torque, KV' x I, meets the prop's, CP rho n^3 D^5 / omega, so
  as the air comes through the disc faster the prop unloads, spins up and its thrust fades along
  the measured curve rather than a straight line. A motor without a published rpm is taken at 75 %
  of KV x volts at its 100 % row, the rule the missions used before.
- Pack. Open-circuit voltage against state of charge from Chen and Rincón-Mora (IEEE Transactions
  on Energy Conversion 21(2), 2006, a lithium polymer cell), scaled to 4.35 V full for LiHV packs.
  Internal resistance per cell is 0.326 V over the pack's rated current (C rating x capacity): a
  4S 1300 mAh 75C pack measured 3.34 mOhm per cell on a test bench (drone-zone.de review of the
  DroneLab CHAOS 4S 1300), which is 0.326 V of sag at 97.5 A. The terminal voltage follows the
  current actually drawn, V = Voc - I R, and the charge drains with it; a flight ends at 80 % of
  the capacity or at 3.3 V per cell under load, whichever comes first (BetaFPV measures its whoops'
  flight times down to 3.3 V).
- Ground effect. Thrust near the floor rises by 1 / (1 - (R / 4z)^2), Cheeseman and Bennett
  (ARC R&M 3021, 1955), with the rotor at least half a radius up.
- Camera. Field of view, video standard and frame rate from the camera's page; analog NTSC is
  digitised at 720 x 480 (ITU-R BT.601) whatever TVL the sensor claims. A fly is detected when it
  covers 2 pixels, the Johnson criterion for detection at 50 % probability (Johnson 1958; 1 cycle
  across the target's critical dimension), with a house fly 6 mm long (Musca domestica adults are
  6 to 7 mm).
"""

from __future__ import annotations

import math

import numpy as np

RHO = 1.225
G = 9.80665

# Measured propeller curves: J, CT, CP from the UIUC propeller database, volume 2
# (https://m-selig.ae.illinois.edu/props/volume-2/propDB-volume-2.html). J = 0 is the static
# test at its highest rpm; the rest is the run named in `run`, sampled every ~0.09 in J.
PROP_CURVES = {
    "gwsdd_2.5x1": {"name": "GWS Direct Drive 2.5 x 1", "d_in": 2.5, "p_in": 1.0, "blades": 2, "run": "gwsdd_2.5x1_0461rd_25060",
                    "points": ((0.000, 0.0736, 0.0319), (0.088, 0.0620, 0.0323), (0.177, 0.0478, 0.0293), (0.265, 0.0313, 0.0254), (0.354, 0.0126, 0.0224), (0.442, -0.0094, 0.0174))},
    "gwsdd_3x2": {"name": "GWS Direct Drive 3 x 2", "d_in": 3.0, "p_in": 2.0, "blades": 2, "run": "gwsdd_3x2_0397rd_19047",
                  "points": ((0.000, 0.1379, 0.0687), (0.091, 0.1288, 0.0664), (0.183, 0.1132, 0.0623), (0.275, 0.0944, 0.0566), (0.364, 0.0765, 0.0509), (0.456, 0.0552, 0.0436))},
    "gwsdd_4x2.5": {"name": "GWS Direct Drive 4 x 2.5", "d_in": 4.0, "p_in": 2.5, "blades": 2, "run": "gwsdd_4x2.5_0378rd_14059",
                    "points": ((0.000, 0.1281, 0.0590), (0.100, 0.1161, 0.0557), (0.177, 0.1028, 0.0521), (0.276, 0.0822, 0.0460), (0.351, 0.0660, 0.0409), (0.453, 0.0420, 0.0333), (0.503, 0.0289, 0.0286))},
    "gwsdd_4.5x3": {"name": "GWS Direct Drive 4.5 x 3", "d_in": 4.5, "p_in": 3.0, "blades": 2, "run": "gwsdd_4.5x3_0346rd_11056",
                    "points": ((0.000, 0.1221, 0.0570), (0.085, 0.1136, 0.0542), (0.170, 0.1022, 0.0515), (0.254, 0.0889, 0.0481), (0.342, 0.0724, 0.0430), (0.426, 0.0550, 0.0373), (0.510, 0.0366, 0.0307), (0.567, 0.0222, 0.0249))},
    "gwsdd_3x3": {"name": "GWS Direct Drive 3 x 3", "d_in": 3.0, "p_in": 3.0, "blades": 2, "run": "gwsdd_3x3_0407rd_15063",
                  "points": ((0.000, 0.1948, 0.1434), (0.087, 0.1895, 0.1396), (0.176, 0.1804, 0.1325), (0.262, 0.1656, 0.1233), (0.352, 0.1495, 0.1131), (0.439, 0.1328, 0.1048), (0.528, 0.1146, 0.0959), (0.588, 0.1001, 0.0883))},
    "gwsdd_4x4": {"name": "GWS Direct Drive 4 x 4", "d_in": 4.0, "p_in": 4.0, "blades": 2, "run": "gwsdd_4x4_0442rd_10060",
                  "points": ((0.000, 0.1710, 0.1286), (0.105, 0.1657, 0.1247), (0.210, 0.1550, 0.1178), (0.317, 0.1417, 0.1088), (0.422, 0.1235, 0.0985), (0.527, 0.1018, 0.0871), (0.630, 0.0774, 0.0738), (0.700, 0.0607, 0.0647))},
    "apcff_4.2x4": {"name": "APC Free Flight 4.2 x 4", "d_in": 4.2, "p_in": 4.0, "blades": 2, "run": "apcff_4.2x4_0620rd_10042",
                    "points": ((0.000, 0.1292, 0.1070), (0.102, 0.1309, 0.1111), (0.203, 0.1256, 0.1080), (0.305, 0.1184, 0.1028), (0.409, 0.1103, 0.0988), (0.511, 0.0993, 0.0943), (0.610, 0.0842, 0.0867), (0.681, 0.0734, 0.0807))},
    "mit_4.3x3.5": {"name": "Micro Invent 4.3 x 3.5 3-blade", "d_in": 4.3, "p_in": 3.5, "blades": 3, "run": "mit_4.3x3.5_0579rd_9055",
                    "points": ((0.000, 0.1767, 0.1072), (0.107, 0.1602, 0.0972), (0.215, 0.1388, 0.0864), (0.323, 0.1106, 0.0743), (0.432, 0.0743, 0.0601), (0.543, 0.0319, 0.0447), (0.650, -0.0163, 0.0282), (0.721, -0.0507, 0.0181))},
}
UIUC_URL = "https://m-selig.ae.illinois.edu/props/volume-2/data/"

SAG_AT_RATED_V = 0.326  # volts per cell at the rated current: 3.34 mOhm x 97.5 A (4S 1300 mAh 75C on a bench)
DEFAULT_C = 30.0
CUTOFF_V = 3.3  # per cell under load
USABLE = 0.8
LOADED_RPM = 0.75

FLY_SIZE_M = 0.006
DETECT_PX = 2.0


def _num(part: dict | None, key: str) -> float | None:
    try:
        value = float((part or {})[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def nearest_curve(blades: int, pitch_ratio: float) -> str:
    """The documented prop closest to this one: same blade count first, then the nearest P/D."""

    def score(key: str) -> tuple[int, float]:
        ref = PROP_CURVES[key]
        return (0 if ref["blades"] == blades else 1, abs(math.log(pitch_ratio / (ref["p_in"] / ref["d_in"]))))

    return min(PROP_CURVES, key=score)


class Curve:
    """CT / CT0 and CP / CP0 of one measured prop against x = J / (P/D)."""

    def __init__(self, key: str) -> None:
        ref = PROP_CURVES[key]
        pts = np.array(ref["points"], dtype=float)
        self.key = key
        self.ratio = ref["p_in"] / ref["d_in"]
        self.x = pts[:, 0] / self.ratio
        self.ct = pts[:, 1] / pts[0, 1]
        self.cp = pts[:, 2] / pts[0, 2]
        self.ct_tail = (self.ct[-1] - self.ct[-2]) / (self.x[-1] - self.x[-2])
        self.cp_tail = (self.cp[-1] - self.cp[-2]) / (self.x[-1] - self.x[-2])
        self.ct_head = (self.ct[1] - self.ct[0]) / (self.x[1] - self.x[0])
        self.cp_head = (self.cp[1] - self.cp[0]) / (self.x[1] - self.x[0])
        # Where the measured (or continued) thrust reaches zero.
        if self.ct[-1] <= 0:
            self.x_zero = float(np.interp(0.0, self.ct[::-1], self.x[::-1]))
        else:
            self.x_zero = float(self.x[-1] - self.ct[-1] / self.ct_tail) if self.ct_tail < 0 else float(self.x[-1] * 2)

    def _eval(self, x, values, head, tail, low):
        x = np.asarray(x, dtype=float)
        out = np.interp(x, self.x, values)
        out = np.where(x > self.x[-1], values[-1] + tail * (x - self.x[-1]), out)
        # Descending through the disc (x < 0) the prop works harder: the slope at the origin, at most +20 %.
        out = np.where(x < 0, np.minimum(1.2, values[0] + head * x), out)
        return np.maximum(out, low)

    def thrust(self, x):
        return self._eval(x, self.ct, self.ct_head, self.ct_tail, -0.6)

    def power(self, x):
        return self._eval(x, self.cp, self.cp_head, self.cp_tail, 0.05)


def _interp2(xs: np.ndarray, ys: np.ndarray, table: np.ndarray, x, y) -> np.ndarray:
    """Bilinear lookup in table[len(xs), len(ys)], clipped to the grid."""

    x = np.clip(np.asarray(x, dtype=float), xs[0], xs[-1])
    y = np.clip(np.asarray(y, dtype=float), ys[0], ys[-1])
    i = np.clip(np.searchsorted(xs, x) - 1, 0, len(xs) - 2)
    j = np.clip(np.searchsorted(ys, y) - 1, 0, len(ys) - 2)
    fx = (x - xs[i]) / (xs[i + 1] - xs[i])
    fy = (y - ys[j]) / (ys[j + 1] - ys[j])
    return (table[i, j] * (1 - fx) * (1 - fy) + table[i + 1, j] * fx * (1 - fy) + table[i, j + 1] * (1 - fx) * fy + table[i + 1, j + 1] * fx * fy)


class Pack:
    """The battery: open-circuit voltage against charge, internal resistance from its C rating."""

    def __init__(self, battery: dict) -> None:
        self.notes: list[str] = []
        self.cells = int(battery.get("cells") or max(1, round(float(battery.get("voltage_v") or 3.7) / 3.7)))
        self.capacity_ah = (_num(battery, "capacity_mah") or 500.0) / 1000.0
        nominal = (_num(battery, "voltage_v") or 3.7 * self.cells) / self.cells
        hv = "hv" in str(battery.get("chemistry") or "").lower() or nominal >= 3.8
        self.full_cell = 4.35 if hv else 4.2
        c_rating = _num(battery, "c_rating")
        if c_rating is None:
            c_rating = DEFAULT_C
            self.notes.append("The pack has no C rating; " + f"{DEFAULT_C:g}" + "C assumed for its internal resistance.")
        self.c_rating = c_rating
        self.r_cell = SAG_AT_RATED_V / (c_rating * self.capacity_ah)
        self.r = self.r_cell * self.cells

    def ocv(self, soc: float) -> float:
        s = min(max(soc, 0.0), 1.0)
        cell = -1.031 * math.exp(-35.0 * s) + 3.685 + 0.2156 * s - 0.1178 * s * s + 0.3201 * s**3
        return cell * self.full_cell / 4.2 * self.cells

    def terminal(self, soc: float, power_w: float) -> tuple[float, float]:
        """(terminal voltage, current) when the load draws `power_w`; past the pack's peak power, the peak."""

        voc = self.ocv(soc)
        disc = voc * voc - 4.0 * self.r * max(power_w, 0.0)
        if disc <= 0:
            return voc / 2.0, voc / (2.0 * self.r)
        v = (voc + math.sqrt(disc)) / 2.0
        return v, max(power_w, 0.0) / v

    def drain(self, soc: float, current_a: float, dt: float) -> float:
        return soc - current_a * dt / (self.capacity_ah * 3600.0)


class Plant:
    """One build's power train: four motors with their props on one pack."""

    def __init__(self, motor: dict, propeller: dict, battery: dict, count: int = 4) -> None:
        from pai_agent.flight import bench

        self.notes: list[str] = []
        self.count = count
        self.pack = Pack(battery)
        self.notes += self.pack.notes
        row = bench(motor)
        cells_max = _num(motor, "cells_max")
        v_b = _num(row, "voltage_v")
        if v_b is None:
            v_b = 3.8 * (cells_max or self.pack.cells)
            self.notes.append("The motor's thrust has no test voltage; " + f"{v_b:.1f}" + " V assumed (3.8 V per cell it is rated for).")
        t_b = float(row.get("thrust_g") or 0.0) / 1000.0 * G
        p_b = _num(row, "power_w") or (float(row.get("thrust_g") or 0.0) / (_num(motor, "efficiency_g_per_w") or 2.0))
        i_b = _num(row, "current_a") or p_b / v_b
        diameter_mm = _num(propeller, "diameter_mm") or 51.0
        self.d = diameter_mm / 1000.0
        pitch_in = _num(propeller, "pitch_in")
        if pitch_in is None:
            pitch_in = diameter_mm * 0.8 / 25.4
            self.notes.append("The propeller has no published pitch; 0.8 x its diameter is assumed.")
        self.pitch_ratio = pitch_in * 25.4 / diameter_mm
        kv = _num(motor, "kv")
        rpm_b = _num(row, "rpm")
        if kv is None:
            # No KV: a tip speed of 110 m/s at the 100 % row, the missions' old default.
            rpm_b = rpm_b or 110.0 / (math.pi * self.d) * 60.0
            kv = rpm_b / (LOADED_RPM * v_b)
            self.notes.append("The motor has no KV; " + f"{kv:.0f}" + " KV assumed from a 110 m/s tip speed.")
        if rpm_b is None:
            rpm_b = LOADED_RPM * kv * v_b
            self.notes.append("The load table has no rpm; the motor is taken at " + f"{LOADED_RPM:.0%}" + " of KV x volts at 100 %.")
        self.kv = kv
        self.ke = 60.0 / (2.0 * math.pi * kv)  # volt seconds per radian, also newton metres per amp
        back_emf = rpm_b / kv
        self.r = max((v_b - back_emf) / i_b, 0.02 * v_b / i_b)
        n_b = rpm_b / 60.0
        self.ct0 = t_b / (RHO * n_b**2 * self.d**4)
        self.cp0 = back_emf * i_b / (RHO * n_b**3 * self.d**5)
        self.bench = {"voltage_v": v_b, "current_a": i_b, "rpm": rpm_b, "thrust_n": t_b}
        blades = int(propeller.get("blades") or 2)
        self.curve_key = nearest_curve(blades, self.pitch_ratio)
        self.curve = Curve(self.curve_key)
        ref = PROP_CURVES[self.curve_key]
        same = ref["blades"] == blades
        self.notes.append(
            "Thrust and power against airspeed follow the measured curve of the " + ref["name"] + " (UIUC propeller database, P/D "
            + f"{ref['p_in'] / ref['d_in']:.2f}" + (", the same blade count" if same else ", the nearest documented: no " + str(blades) + "-blade curve")
            + "), stretched to this prop's P/D " + f"{self.pitch_ratio:.2f}" + "."
        )
        # The motor never sees more than the voltage it is rated for; on a pack above its rating it is
        # held to its load table's voltage, as physics_calc counts it (no thrust added).
        self.v_cap = cells_max * 4.35 if cells_max else math.inf
        if cells_max and self.pack.cells > cells_max:
            self.v_cap = v_b
        self.motor = motor
        self._tables()

    # -- motor and prop in equilibrium -----------------------------------------------------------

    def _torque(self, n, va):
        x = va / (np.maximum(n, 1e-6) * self.d) / self.pitch_ratio
        return self.cp0 * self.curve.power(x) * RHO * n**3 * self.d**5 / (2.0 * math.pi * np.maximum(n, 1e-6))

    def _thrust(self, n, va):
        x = va / (np.maximum(n, 1e-6) * self.d) / self.pitch_ratio
        return self.ct0 * self.curve.thrust(x) * RHO * n**2 * self.d**4

    def _spin(self, v_motor, va):
        """Revolutions per second where the motor on `v_motor` drives the prop at airspeed `va`."""

        v_motor, va = np.broadcast_arrays(np.asarray(v_motor, dtype=float), np.asarray(va, dtype=float))
        low = np.zeros_like(v_motor)
        high = self.kv * v_motor / 60.0 + 1e-6
        for _ in range(50):
            n = (low + high) / 2.0
            residual = self.ke * 2.0 * math.pi * n + self.r * self._torque(n, va) / self.ke - v_motor
            low = np.where(residual < 0, n, low)
            high = np.where(residual < 0, high, n)
        return (low + high) / 2.0

    def _spin_for(self, thrust, va):
        thrust, va = np.broadcast_arrays(np.asarray(thrust, dtype=float), np.asarray(va, dtype=float))
        low = np.zeros_like(thrust)
        high = np.full_like(thrust, 3.0 * self.kv * self.v_max / 60.0)
        for _ in range(50):
            n = (low + high) / 2.0
            short = self._thrust(n, va) < thrust
            low = np.where(short, n, low)
            high = np.where(short, high, n)
        return (low + high) / 2.0

    def _tables(self) -> None:
        self.v_max = min(self.v_cap, self.pack.ocv(1.0))
        n_free = self.kv * self.v_max / 60.0
        self.va_zero_est = max(self.curve.x_zero * self.pitch_ratio * n_free * self.d, 5.0)
        self.va_grid = np.concatenate([np.linspace(-0.4 * self.va_zero_est, 0.0, 9)[:-1], np.linspace(0.0, 1.6 * self.va_zero_est, 49)])
        self.v_grid = np.linspace(0.2 * self.v_max, self.v_max, 17)
        vv, aa = np.meshgrid(self.v_grid, self.va_grid, indexing="ij")
        n = self._spin(vv, aa)
        self.t_table = np.maximum(self._thrust(n, aa), 0.0)
        t_top = float(self.t_table[-1].max())
        self.t_grid = np.linspace(0.0, 1.3 * t_top, 41)
        tt, aa = np.meshgrid(self.t_grid, self.va_grid, indexing="ij")
        n = self._spin_for(tt, aa)
        current = self._torque(n, aa) / self.ke
        modelled = current * (self.ke * 2.0 * math.pi * n + current * self.r)
        # The static power is the maker's: the load table read at each thrust (flight.motor_power_w).
        # The model has no iron, bearing or ESC losses, so it reads low at part throttle; it only
        # supplies how the power changes with airspeed.
        from pai_agent.flight import motor_power_w

        t_bench = self.bench["thrust_n"]
        still = int(np.argmin(np.abs(self.va_grid)))
        static = modelled[:, still]
        scale = np.ones(len(self.t_grid))
        for k in range(1, len(self.t_grid)):
            at = min(float(self.t_grid[k]), t_bench)
            published, _source = motor_power_w(self.motor, at / G * 1000.0)
            model_at = float(np.interp(at, self.t_grid, static))
            if published > 0 and model_at > 0:
                scale[k] = published / model_at
        scale[0] = scale[1]
        self.p_table = np.where(tt > 0, modelled * scale[:, None], 0.0)

    # -- what the missions and the card read -----------------------------------------------------

    def motor_voltage(self, v_pack: float) -> float:
        return min(v_pack, self.v_cap)

    def thrust_max(self, v_pack, axial):
        """Newtons one motor makes at full throttle on this pack voltage with `axial` m/s through its disc."""

        return _interp2(self.v_grid, self.va_grid, self.t_table, np.minimum(v_pack, self.v_cap), axial)

    def power(self, thrust, axial):
        """Electrical watts one motor draws to make `thrust` newtons with `axial` m/s through its disc."""

        return _interp2(self.t_grid, self.va_grid, self.p_table, thrust, axial)

    def full_throttle(self, soc: float, axial: float = 0.0) -> dict:
        """All motors at 100 %: per-motor thrust, the pack's sagged voltage and current."""

        v = self.pack.ocv(soc)
        for _ in range(12):
            thrust = float(self.thrust_max(v, axial))
            watts = self.count * float(self.power(thrust, axial))
            v_new, current = self.pack.terminal(soc, watts)
            if abs(v_new - v) < 1e-4:
                break
            v = 0.5 * (v + v_new)
        return {"thrust_n": thrust, "v_pack": v, "current_a": current, "power_w": watts}

    def thrust_curve(self, soc: float) -> tuple[np.ndarray, np.ndarray]:
        """Total full-throttle thrust (all motors, sagged) against axial airspeed, for the card's model."""

        speeds = self.va_grid[self.va_grid >= 0]
        return speeds, np.array([self.count * self.full_throttle(soc, float(va))["thrust_n"] for va in speeds])

    def zero_thrust_speed(self, soc: float = 1.0) -> float:
        """The airspeed through the disc where full throttle makes no thrust: the prop's real pitch speed."""

        speeds, thrust = self.thrust_curve(soc)
        if thrust[-1] > 0:
            return float(speeds[-1])
        k = int(np.argmax(thrust <= 0))
        if k == 0:
            return 0.0
        t0, t1 = thrust[k - 1], thrust[k]
        return float(speeds[k - 1] + (speeds[k] - speeds[k - 1]) * t0 / (t0 - t1))

    def tip_speed(self, soc: float = 1.0) -> float:
        v = self.full_throttle(soc)["v_pack"]
        n = float(self._spin(self.motor_voltage(v), 0.0))
        return n * math.pi * self.d

    def endurance_min(self, demand, soc: float = 1.0, usable: float = USABLE, dt: float = 1.0) -> tuple[float, float]:
        """Minutes until 80 % of the pack is used or a cell sags under 3.3 V, drawing demand(soc, v) watts.

        Returns (minutes, state of charge at the end)."""

        floor = 1.0 - usable
        cutoff = CUTOFF_V * self.pack.cells
        v = self.pack.ocv(soc)
        elapsed = 0.0
        while soc > floor and elapsed < 7200.0:
            watts = float(demand(soc, v))
            if watts <= 0:
                return math.inf, soc
            v, current = self.pack.terminal(soc, watts)
            if v < cutoff:
                break
            soc = self.pack.drain(soc, current, dt)
            elapsed += dt
        return elapsed / 60.0, soc


def ground_effect(height_m, radius_m: float):
    """Thrust gain near the floor (Cheeseman and Bennett 1955), the rotor at least half a radius up."""

    ratio = np.maximum(np.asarray(height_m, dtype=float), 0.5 * radius_m) / radius_m
    return 1.0 / (1.0 - (1.0 / (4.0 * ratio)) ** 2)


# -- the camera --------------------------------------------------------------------------------------

DEFAULT_CAMERA = {"fov_deg": 150.0, "resolution_px": [720, 480], "fps": 30.0, "latency_ms": 20.0, "uptilt_deg": 20.0}
PROCESS_S = 0.015  # an onboard detector on each frame, assumed


def camera_spec(camera: dict | None) -> dict:
    """What the chosen camera sees: field of view, pixels, frame rate and latency, and the fly's detection range."""

    camera = camera or {}
    assumed = []
    values = {}
    for key, default in DEFAULT_CAMERA.items():
        value = camera.get(key)
        if value in (None, "", []):
            values[key] = default
            assumed.append(key)
        else:
            values[key] = value
    if not camera:
        assumed = ["camera"]
    diagonal = math.radians(float(values["fov_deg"]))
    width, height = (int(v) for v in values["resolution_px"])
    # A fisheye maps angle evenly onto the 4:3 picture: 4 and 3 parts of the 5 along the diagonal.
    fov_h = diagonal * 4.0 / 5.0
    fov_v = diagonal * 3.0 / 5.0
    ifov = fov_h / width
    fps = float(values["fps"])
    latency = float(values["latency_ms"]) / 1000.0
    return {
        "id": camera.get("id"),
        "fov_h": fov_h,
        "fov_v": fov_v,
        "width_px": width,
        "height_px": height,
        "ifov": ifov,
        "fps": fps,
        "tilt": math.radians(float(values["uptilt_deg"])),
        # Light to estimate: the camera's own latency, one frame to read out, the detector's pass.
        "delay_s": latency + 1.0 / fps + PROCESS_S,
        "detect_range_m": FLY_SIZE_M / (DETECT_PX * ifov),
        "assumed": assumed,
    }
