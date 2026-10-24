"""Hand-computed cases for analysis_more and the mock category routing.

power_budget, USB 5 V 3 A: a 5 W load at duty 0.5 peaking 2x and a 1 W load on 3.3 V
behind an 85 % regulator. Average 2.5 + 1 / 0.85 = 3.676 W, peak 10 + 1.176 = 11.176 W,
peak current 11.176 / 5 = 2.235 A, headroom 3 / 2.235 = 1.34.
power_budget, 2S 1500 mAh 25C: limit 37.5 A, a 3.7 W load draws 0.5 A, headroom 75;
runtime 11.1 Wh x 0.8 / 3.7 W = 2.4 h.
thermal, 8 W in a closed 95 x 70 x 30 mm PETG box with 2 mm walls: A = 2 (ab + ac + bc)
= 0.0232 m2, wall k A / t = 0.2 x 0.0232 / 0.002 = 2.32 W/K, air h A = 0.116 W/K, in
series 0.1105 W/K, rise 8 / 0.1105 = 72.4 K, 97.4 C inside. A 9 m3/h fan adds
1206 x 9 / 3600 = 3.015 W/K: rise 8 / 3.1255 = 2.6 K.
rollover, track 100 mm, centre of mass 50 mm up: SSF 100 / 100 = 1.0 g, side slope
atan(1) = 45 deg, wheelbase 110 mm forward slope atan(1.1) = 47.7 deg; a 3 m/s turn on
0.75 m needs 9 / (0.75 x 9.80665) = 1.22 g, so it rolls.
"""

from __future__ import annotations

import pytest

from pai_agent import analysis_more
from pai_agent.mock_categories import wants_category


def test_power_budget_two_rails() -> None:
    result = analysis_more.power_budget(
        {"voltage_v": 5.0, "max_current_a": 3.0},
        [{"name": "a", "power_w": 5.0, "duty": 0.5, "peak_factor": 2.0}, {"name": "b", "power_w": 1.0, "voltage_v": 3.3}],
    )
    assert result["average_w"] == pytest.approx(3.676, abs=1e-3)
    assert result["peak_a"] == pytest.approx(2.235, abs=1e-3)
    assert result["headroom"] == pytest.approx(1.34, abs=0.01)
    assert result["weakest_rail_v"] == 5.0
    assert "runtime_h" not in result


def test_power_budget_battery() -> None:
    result = analysis_more.power_budget({"kind": "battery", "voltage_v": 7.4, "capacity_mah": 1500, "c_rating": 25}, [{"name": "car", "power_w": 3.7}])
    assert result["supply_limit_a"] == pytest.approx(37.5)
    assert result["headroom"] == pytest.approx(75.0)
    assert result["runtime_h"] == pytest.approx(2.4)


def test_power_budget_needs_a_current_rating() -> None:
    with pytest.raises(ValueError, match="max_current_a"):
        analysis_more.power_budget({"name": "Mystery", "voltage_v": 5.0}, [{"name": "a", "power_w": 1.0}])


def test_thermal_closed_box_and_fan() -> None:
    closed = analysis_more.thermal(8.0, [95, 70, 30], 2.0, "PETG")
    assert closed["area_m2"] == pytest.approx(0.0232, abs=1e-4)
    assert closed["conductance_w_k"]["box"] == pytest.approx(0.1105, abs=1e-3)
    assert closed["internal_c"] == pytest.approx(97.4, abs=0.3)
    assert closed["limit_c"] == 70.0 and closed["material_limit_c"] == 75.0
    assert closed["margin_c"] < 0
    fan = analysis_more.thermal(8.0, [95, 70, 30], 2.0, "PETG", fan_m3h=9.0)
    assert fan["conductance_w_k"]["fan"] == pytest.approx(3.015, abs=1e-3)
    assert fan["rise_c"] == pytest.approx(2.6, abs=0.1)
    assert fan["margin_c"] > 0


def test_rollover() -> None:
    result = analysis_more.rollover(100.0, 110.0, 50.0, 3.0, 0.75)
    assert result["ssf"] == pytest.approx(1.0)
    assert result["side_slope_deg"] == pytest.approx(45.0)
    assert result["forward_slope_deg"] == pytest.approx(47.7)
    assert result["turn_g"] == pytest.approx(1.22)
    assert result["rolls_in_turn"] is True
    assert analysis_more.rollover(170.0, 110.0, 50.0, 3.0, 0.75)["rolls_in_turn"] is False


@pytest.mark.parametrize(
    "text, category",
    [
        ("Design a case for my Raspberry Pi 5 with a fan", "pi-case"),
        ("Build a small 2WD RC car chassis", "rc-car"),
        ("Design a phone stand for my desk that holds my phone for video calls. It must not tip when I tap the screen and cost under 6 €.", None),
        ("Design a small USB desk fan that stands stable on the desk, under 300 g and 25 €.", None),
        ("Design a plant-watering robot for one pot: a water tank, a pump and a soil sensor, running a month on a battery, under 40 €.", None),
        ("Build the small drone from the kickoff.", None),
        ("Design a robot gripper for our arm that picks up a 200 g soda can, 66 mm wide. Keep it under 150 g and 30 €.", None),
        ("Stress test the frame", None),
        ("Train the hover controller in the browser", None),
    ],
)
def test_category_routing(text: str, category: str | None) -> None:
    assert wants_category(text) == category
