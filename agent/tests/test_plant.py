"""The power train and the camera the missions fly: measured prop curves, a motor fitted to its load table, pack sag, ground effect, detection range."""

import math

import pytest

from pai_agent.plant import CUTOFF_V, FLY_SIZE_M, SAG_AT_RATED_V, G, Pack, Plant, camera_spec, ground_effect, nearest_curve
from pai_agent.tools.parts import catalog

PARTS = {p["id"]: p for p in catalog()["parts"]}


def _plant(motor="betafpv-1102-21000kv", prop="gemfan-1811-3", pack="betafpv-lava-1s-680") -> Plant:
    return Plant(PARTS[motor], PARTS[prop], PARTS[pack])


def test_the_nearest_documented_prop_is_chosen_and_named():
    assert nearest_curve(3, 1.0) == "mit_4.3x3.5"  # the only 3-blade curve
    assert nearest_curve(2, 0.4) == "gwsdd_2.5x1"
    four_blade = _plant("generic-1103-15000kv", "gemfan-2020-4", "tattu-rline-1s-550")
    assert four_blade.curve_key == "gwsdd_3x3"
    assert any("no 4-blade curve" in note for note in four_blade.notes)


def test_static_thrust_is_the_load_table_row():
    plant = _plant()
    bench = PARTS["betafpv-1102-21000kv"]["bench"]
    assert float(plant.thrust_max(bench["voltage_v"], 0.0)) == pytest.approx(bench["thrust_g"] / 1000 * G, rel=0.01)
    assert float(plant.power(bench["thrust_g"] / 1000 * G, 0.0)) == pytest.approx(bench["power_w"], rel=0.02)


def test_thrust_fades_with_airspeed_to_the_zero_thrust_speed():
    plant = _plant()
    speeds = [0.0, 10.0, 20.0, 30.0]
    thrust = [float(plant.thrust_max(4.0, v)) for v in speeds]
    assert thrust == sorted(thrust, reverse=True)
    zero = plant.zero_thrust_speed(1.0)
    assert 20.0 < zero < 60.0
    assert plant.full_throttle(1.0, zero + 1.0)["thrust_n"] == pytest.approx(0.0, abs=1e-3)
    # The prop unloads at speed, so the motor spins up past its loaded rpm: the zero-thrust
    # speed is above pitch x the 100 % row's rpm, but under pitch x the no-load rpm.
    pitch_m = PARTS["gemfan-1811-3"]["pitch_in"] * 0.0254
    assert pitch_m * PARTS["betafpv-1102-21000kv"]["bench"]["rpm"] / 60 * 0.76 < zero < pitch_m * 21000 * 4.25 / 60


def test_pack_resistance_comes_from_its_c_rating():
    pack = Pack(PARTS["betafpv-lava-6s-1100"])
    assert pack.r_cell == pytest.approx(SAG_AT_RATED_V / (100 * 1.1))
    assert pack.r == pytest.approx(6 * pack.r_cell)
    v, current = pack.terminal(1.0, 1000.0)
    assert v == pytest.approx(pack.ocv(1.0) - current * pack.r, rel=1e-6)
    assert v * current == pytest.approx(1000.0, rel=1e-6)
    assert pack.ocv(1.0) > pack.ocv(0.5) > pack.ocv(0.2)
    # A LiHV cell rests higher than a LiPo one.
    assert Pack(PARTS["betafpv-lava-1s-680"]).ocv(1.0) > Pack(dict(PARTS["betafpv-lava-1s-680"], chemistry="LiPo", voltage_v=3.7)).ocv(1.0)


def test_a_sagging_draining_pack_loses_thrust():
    plant = _plant()
    fresh, empty = plant.full_throttle(1.0), plant.full_throttle(0.2)
    assert fresh["v_pack"] < plant.pack.ocv(1.0)  # sag under load
    assert empty["thrust_n"] < 0.92 * fresh["thrust_n"]
    assert plant.zero_thrust_speed(0.2) < plant.zero_thrust_speed(1.0)


def test_a_smaller_pack_sags_more():
    small = _plant(pack="betafpv-lava-1s-300")
    big = _plant(pack="betafpv-lava-1s-680")
    assert small.full_throttle(1.0)["v_pack"] < big.full_throttle(1.0)["v_pack"]


def test_endurance_stops_at_80_percent_or_the_cutoff():
    plant = _plant()
    hover = 4 * float(plant.power(0.1, 0.0))
    minutes, soc = plant.endurance_min(lambda soc, v: hover)
    assert soc == pytest.approx(0.2, abs=0.01)
    assert minutes == pytest.approx(0.8 * 0.68 * 3.9 / hover * 60, rel=0.15)
    flat_out, soc = plant.endurance_min(lambda soc, v: plant.full_throttle(soc)["power_w"])
    assert flat_out < minutes / 5
    # Past the pack's peak power it stops at once, the cell under 3.3 V.
    none, _soc = plant.endurance_min(lambda soc, v: 2000.0)
    assert none == 0.0 and CUTOFF_V == 3.3


def test_a_motor_on_a_pack_above_its_rating_adds_no_thrust():
    plant = _plant("generic-1103-15000kv", "gemfan-2020-4", "tattu-funfly-4s-1300")
    assert plant.full_throttle(1.0)["thrust_n"] == pytest.approx(50 / 1000 * G, rel=0.01)


def test_ground_effect_matters_only_near_the_floor():
    radius = 0.0255
    assert float(ground_effect(1.5, radius)) == pytest.approx(1.0, abs=1e-4)
    assert float(ground_effect(radius, radius)) == pytest.approx(1 / (1 - 1 / 16))
    assert float(ground_effect(0.0, radius)) == pytest.approx(1 / (1 - 0.25))


def test_detection_range_follows_the_cameras_pixels_and_lens():
    ant = camera_spec(PARTS["caddx-ant"])
    assert ant["assumed"] == ["latency_ms", "uptilt_deg"]
    ifov = math.radians(165) * 0.8 / 720
    assert ant["detect_range_m"] == pytest.approx(FLY_SIZE_M / (2 * ifov))
    assert 0.9 < ant["detect_range_m"] < 1.2
    ratel = camera_spec(PARTS["caddx-ratel-19mm"])
    assert ratel["delay_s"] == pytest.approx(0.008 + 1 / 30 + 0.015)
    narrow = camera_spec(dict(PARTS["caddx-ant"], fov_deg=60, resolution_px=[1280, 720]))
    assert narrow["detect_range_m"] > 4 * ant["detect_range_m"]
    assert camera_spec(None)["assumed"] == ["camera"]
