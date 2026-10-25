"""Flight performance from the parts' specs: the formulas, the honesty rules and real library builds."""

import math
import tempfile
from pathlib import Path

import pytest

from pai_agent.drone_geometry import geometry
from pai_agent.flight import G, TILT_MAX, Model, inertia, motor_power_w, thrust_per_motor_g
from pai_agent.mission_sim import airframe, run
from pai_agent.state import BuildState
from pai_agent.tools.parts import catalog
from pai_agent.tools.physics import PhysicsError, compute

PARTS = {p["id"]: p for p in catalog()["parts"]}
REFERENCE = ["generic-1103-15000kv", "gemfan-2020-4", "tattu-rline-1s-550", "betafpv-matrix-1s-5in1-v2", "twiglet-2in-carbon", "caddx-ant", "toothpick-canopy-holder", "m14-bolts"]
WHOOP = ["betafpv-0802-22000kv", "gemfan-1614-3", "betafpv-lava-1s-300", "betafpv-matrix-1s-5in1-v2", "betafpv-air75-ii", "betafpv-c03"]
FIVE_INCH = ["betafpv-snow-2306-1860kv", "gemfan-51466-v2", "betafpv-lava-6s-1100", "betafpv-f722-35a-aio", "betafpv-x-knight-5", "caddx-ratel-19mm", "betafpv-a03-vtx"]
METEOR = ["betafpv-1102-21000kv", "gemfan-1811-3", "betafpv-lava-1s-450", "betafpv-f4-1s-5a-aio", "betafpv-meteor75-pro-ii", "betafpv-c03"]
AQUILA_2S = ["betafpv-1103-10500kv", "gemfan-2218-3", "betafpv-lava-2s-550", "betafpv-f4-2-3s-20a-aio", "betafpv-aquila20", "betafpv-c03"]
PAVO20_4S = ["betafpv-1104-5500kv", "gemfan-d22-3", "betafpv-lava-4s-550", "betafpv-toothpick-f405-20a", "betafpv-pavo20-pro-ii", "betafpv-c03"]
PAVO25_4S = ["betafpv-1506-4200kv", "gemfan-d63-3", "betafpv-lava-4s-850", "betafpv-cube-2-4s-30a", "betafpv-pavo25-v2", "caddx-ratel-19mm"]
# Every drone class in the library: 1S micros and whoops, 2S and 4S 2 to 2.5 inch, 6S 5 inch.
CLASSES = {"reference": REFERENCE, "whoop": WHOOP, "meteor75-1s": METEOR, "aquila-2s": AQUILA_2S, "pavo20-4s": PAVO20_4S, "pavo25-4s": PAVO25_4S, "five-inch-6s": FIVE_INCH}


def _state(ids, **overrides) -> BuildState:
    state = BuildState(session_id="t", directory=Path(tempfile.mkdtemp()))
    for part_id in ids:
        part = dict(PARTS[part_id])
        part.update(overrides.get(part["category"], {}))
        state.selected[part["category"]] = part
    return state


def test_reference_build_keeps_its_four_numbers():
    metrics = compute(_state(REFERENCE))
    # The stage demo's numbers from before the performance model.
    assert metrics["weight_g"] == 47.2
    assert metrics["thrust_to_weight"] == 4.23
    assert metrics["flight_time_min"] == 8.5
    assert metrics["price_eur"] == 117.38


def test_performance_numbers_are_present_and_labelled_estimates():
    metrics = compute(_state(WHOOP))
    for key in ("top_speed_mps", "top_speed_kmh", "accel_mps2", "climb_rate_mps", "turn_rate_dps", "flight_time_full_speed_min", "flight_time_full_throttle_min"):
        assert metrics[key] > 0, key
    assert metrics["performance"]["estimate"] is True
    assert metrics["performance"]["assumptions"]
    assert metrics["top_speed_kmh"] == pytest.approx(metrics["top_speed_mps"] * 3.6, abs=0.2)


def test_acceleration_is_the_missions_95_percent_thrust_and_tilt_limit():
    metrics = compute(_state(WHOOP))
    twr = 0.95 * metrics["thrust_g"] / metrics["weight_g"]
    expected = min(G * math.sqrt(twr * twr - 1), G * math.tan(TILT_MAX))
    assert metrics["accel_mps2"] == pytest.approx(expected, rel=0.01)


def test_top_speed_is_where_the_forward_push_runs_out():
    model = Model(0.4, 15.0, 40.0, 150.0, 0.005, 0.012)
    top = model.top_speed()
    assert 0 < top < 40.0
    assert model.push(top * 0.98) is not None and model.push(top * 0.98) >= 0
    after = model.push(top * 1.02)
    assert after is None or after < 0


def test_without_a_pitch_the_missions_rule_applies_and_says_so():
    state = _state(WHOOP, propeller={"pitch_in": None})
    state.selected["propeller"].pop("pitch_in")
    metrics = compute(state)
    prop = state.selected["propeller"]
    assumed = compute(_state(WHOOP, propeller={"pitch_in": prop["diameter_mm"] * 0.8 / 25.4}))
    assert metrics["performance"]["pitch_speed_mps"] == pytest.approx(assumed["performance"]["pitch_speed_mps"], abs=0.1)
    assert any("no published pitch" in line for line in metrics["performance"]["assumptions"])


def test_lighter_build_climbs_harder_and_hovers_longer():
    light = compute(_state(WHOOP))
    heavy = compute(_state(WHOOP, battery={"mass_g": 30.0}))
    assert light["climb_rate_mps"] > heavy["climb_rate_mps"]  # both whoops hit the 70 degree tilt cap in acceleration
    assert light["flight_time_min"] > heavy["flight_time_min"]


def test_load_table_power_hits_every_published_row():
    motor = PARTS["betafpv-snow-2306-1860kv"]
    for _throttle, thrust, watts in motor["bench"]["load_table"]:
        power, source = motor_power_w(motor, thrust)
        assert source == "load table"
        assert power == pytest.approx(watts, rel=1e-6)
    between, _ = motor_power_w(motor, 300)
    assert 39.68 < between < 100.29


def test_motor_without_table_uses_the_induced_power_exponent():
    motor = PARTS["generic-1103-15000kv"]
    power, source = motor_power_w(motor, 12.5)
    assert "1.5" in source
    assert power == pytest.approx(25.0 * (12.5 / 50) ** 1.5, rel=1e-6)


def test_lower_voltage_loses_thrust_higher_voltage_adds_none():
    motor = PARTS["betafpv-snow-2306-1860kv"]  # tested at 24 V
    on_4s, note = thrust_per_motor_g(motor, 14.8)
    assert on_4s == pytest.approx(1534 * (14.8 / 24.0) ** 2, rel=1e-6)
    assert note and "thrust x" in note
    on_8s, note = thrust_per_motor_g(motor, 29.6)
    assert on_8s == 1534 and note is None


def test_c_rating_and_esc_warnings():
    metrics = compute(_state(FIVE_INCH))
    assert any("C rating" in line for line in metrics["warnings"])
    small = compute(_state(WHOOP, flight_controller={"esc_continuous_a": 5, "esc_peak_a": 5}))
    assert any("ESC is rated" in line for line in small["warnings"])


def test_inertia_grows_with_the_arm():
    selected = _state(WHOOP).selected
    near = inertia(selected, 4.0, 0.030, [63.5, 11, 6.4])
    far = inertia(selected, 4.0, 0.060, [63.5, 11, 6.4])
    assert all(b > a for a, b in zip(near, far))


@pytest.mark.parametrize("ids", list(CLASSES.values()), ids=list(CLASSES))
def test_card_and_missions_agree(ids):
    """The metrics card and the MuJoCo speed run and hard turn describe one machine."""

    state = _state(ids)
    metrics = compute(state)
    frame = airframe(geometry(state), state.selected)
    speed = run(frame, "speed_run")
    turn = run(frame, "turn")
    # Within 7 %: a tilt-limited run (the Meteor75) flies a few degrees short of the card's 70.
    assert metrics["top_speed_kmh"] == pytest.approx(speed["top_speed_kmh"], rel=0.07)
    assert metrics["turn_rate_dps"] == pytest.approx(turn["turn_rate_dps"], rel=0.08)


def test_five_inch_speed_run_reaches_its_thrust_limit():
    """A 5-inch racer runs until its props run out of thrust, not with thrust to spare."""

    state = _state(FIVE_INCH)
    frame = airframe(geometry(state), state.selected)
    speed = run(frame, "speed_run")
    assert not speed["crashed"] and not speed["still_accelerating"]
    # The pitch speed is the wall: little static thrust left at top speed.
    assert speed["thrust_left_pct"] < 50
    assert speed["top_speed_kmh"] > 0.9 * compute(state)["top_speed_kmh"]


def test_before_cad_the_arm_is_the_frames():
    """Without a built frame the sim, the card and the 3D model put the motors where the chosen frame does."""

    for name, ids in CLASSES.items():
        state = _state(ids)
        geo = geometry(state)
        frame = state.selected["frame"]
        assert geo["arm_length_mm"] == pytest.approx(frame["arm_length_mm"]), name
        assert geo["props_clear"], name
        assert compute(state)["performance"]["arm_length_mm"] == pytest.approx(frame["arm_length_mm"], abs=0.1), name
    state = _state(FIVE_INCH)
    state.selected["frame"] = {k: v for k, v in state.selected["frame"].items() if k != "arm_length_mm"}
    assert geometry(state)["arm_length_mm"] == pytest.approx(state.selected["frame"]["wheelbase_mm"] / 2)
    state.selected["frame"].pop("wheelbase_mm")
    # No frame size at all: the shortest arm whose 132 mm props keep their gap.
    assert geometry(state)["props_clear"]
    state.cad_params = {"arm_length_mm": 110.0}
    assert geometry(state)["arm_length_mm"] == 110.0


@pytest.mark.parametrize("ids", [PAVO25_4S, FIVE_INCH], ids=["pavo25-4s", "five-inch-6s"])
def test_big_drones_hold_and_chase(ids):
    """Bigger builds hold a point in the gusts as tightly as the micros and chase flies without crashing."""

    state = _state(ids)
    frame = airframe(geometry(state), state.selected)
    hold = run(frame, "hold")
    chase = run(frame, "chase")
    assert not hold["crashed"] and hold["hold_error_cm"] < 12.0
    # The Ratel sees a 6 mm fly within about 1 m, each fix 56 ms late: no camera in the library lets a chase catch one.
    assert not chase["crashed"] and chase["detect_range_m"] < 1.1 and chase["first_fix_s"] is not None


def test_cannot_hover_gives_zero_performance():
    metrics = compute(_state(WHOOP, battery={"mass_g": 400.0}))
    assert metrics["thrust_to_weight"] < 1.05
    assert metrics["top_speed_mps"] == 0 and metrics["flight_time_min"] == 0


def test_core_parts_are_required_extras_are_optional():
    state = _state(WHOOP)
    state.selected.pop("camera")
    compute(state)
    state.selected.pop("frame")
    with pytest.raises(PhysicsError):
        compute(state)


def test_five_inch_is_faster_than_a_whoop():
    whoop = compute(_state(WHOOP))
    racer = compute(_state(FIVE_INCH))
    assert racer["top_speed_mps"] > whoop["top_speed_mps"]
    assert racer["climb_rate_mps"] > whoop["climb_rate_mps"]
