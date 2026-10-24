"""Learning-mode explanations without a network: facts, formulas, templates and the number guard."""

import asyncio
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pai_agent import explain
from pai_agent.state import BuildState
from pai_agent.tools.parts import catalog


def _part(part_id):
    return next(p for p in catalog()["parts"] if p["id"] == part_id)


def _pick(part_id, reason="", why=None):
    p = _part(part_id)
    return {"type": "part", "category": p["category"], "id": p["id"], "name": p["name"], "mass_g": p["mass_g"], "reason": reason, "why": why, "warnings": [], "considered": False}


def drone_run():
    state = BuildState(session_id="t", directory=Path("."))
    state.selected = {"motor": _part("generic-1103-15000kv"), "propeller": _part("gemfan-2020-4"), "battery": _part("tattu-rline-1s-550")}
    state.metrics = {"weight_g": 47.2, "thrust_to_weight": 4.23, "flight_time_min": 8.5, "price_eur": 117.38}
    events = [
        _pick("generic-1103-15000kv"),
        _pick("tattu-funfly-4s-1300", "1300 mAh looks like plenty of flight time."),
        {"type": "metrics", "weight_g": 181.8, "thrust_to_weight": 1.1, "flight_time_min": 10.7, "price_eur": 129.52},
        {"type": "sim", "run": 1, "result": "fail", "summary": "Thrust-to-weight 1.10. It barely hovers.", "trajectory": []},
        _pick("tattu-rline-1s-550", "15 g instead of 150 g, and 1S suits the motors."),
        {"type": "metrics", "weight_g": 47.2, "thrust_to_weight": 4.23, "flight_time_min": 8.5, "price_eur": 117.38},
        {"type": "sim", "run": 2, "result": "pass", "summary": "Thrust-to-weight 4.23.", "trajectory": []},
    ]
    return state, events


def phone_stand():
    state = BuildState(session_id="t", directory=Path("."), product="phone-stand")
    state.requirements = [{"id": "tap", "text": "A 0.75 N tap on the phone top does not tip it", "check": "tip_over", "min": 0.75, "unit": "N"}]
    state.checks = {"tip_over": {"angle_deg": 21.4, "force_n": 0.35, "margin_mm": 18.2, "com_height_mm": 46.5, "push_height_mm": 160.0, "tool": "check_tip_over", "args": {}}}
    state.assembly = {"total_mass_g": 316.0}
    events = [{"type": "requirement", "id": "tap", "text": "A 0.75 N tap on the phone top does not tip it", "met": False, "detail": "0.35 N, min. 0.75 N", "source_quote": "It must not tip"}]
    return state, events


class FactsTest(unittest.TestCase):
    def test_battery_swap_has_both_packs_and_numbers(self):
        state, events = drone_run()
        facts = explain.facts_for(state, events, "swap", "battery")
        self.assertEqual(facts["from"], "Tattu FunFly 4S 1300mAh 100C")
        self.assertEqual(facts["to"], "Tattu R-Line 1S 550mAh 95C")
        self.assertEqual((facts["tw_before"], facts["tw_after"]), (1.1, 4.23))
        self.assertEqual((facts["result_before"], facts["result_after"]), ("fail", "pass"))
        self.assertEqual(facts["thrust_g"], 200)
        formula = explain.formula_for("swap", facts)
        self.assertIn("200 g / 47.2 g = 4.23", formula["formula"])
        title, text = explain.template("swap", facts)
        self.assertIn("1.1 to 4.23", text)
        self.assertIn("149.5 g", text)
        self.assertTrue(explain.grounded(text, str(facts), formula["formula"]))

    def test_phone_stand_tip_over_formula(self):
        state, events = phone_stand()
        facts = explain.facts_for(state, events, "requirement", "tap")
        formula = explain.formula_for("requirement", facts)
        self.assertIn("atan(18.2 / 46.5) = 21.4°", formula["formula"])
        self.assertIn("m g d / H = 0.316 kg × 9.81 × 18.2 mm / 160 mm = 0.35 N", formula["formula"])
        title, text = explain.template("requirement", facts)
        self.assertTrue(title.startswith("Not met"))
        self.assertIn("0.35 N, min. 0.75 N", text)

    def test_missing_decision_is_not_found(self):
        state, events = drone_run()
        with self.assertRaises(explain.NotFound):
            explain.facts_for(state, events, "swap", "motor")


class FakeMessages:
    def __init__(self, text):
        self.text, self.calls = text, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(text=self.text)])


class ExplainTest(unittest.TestCase):
    def setUp(self):
        explain.clear()

    def run_explain(self, answer, key="test"):
        state, events = drone_run()
        fake = FakeMessages(answer)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": key}), patch.object(explain, "_anthropic", return_value=SimpleNamespace(messages=fake)):
            first = asyncio.run(explain.explain(state, events, "swap", "battery"))
            second = asyncio.run(explain.explain(state, events, "swap", "battery"))
        return first, second, fake

    def test_without_key_the_template_answers(self):
        first, _, fake = self.run_explain("unused", key="")
        self.assertEqual(first["source"], "template")
        self.assertIsNone(first["model"])
        self.assertEqual(fake.calls, [])

    def test_grounded_haiku_answer_is_cached(self):
        first, second, fake = self.run_explain("The 149.5 g 4S pack left thrust-to-weight at 1.1; the 15 g 1S pack gives 4.23.")
        self.assertEqual(first["source"], "claude")
        self.assertIs(first, second)
        self.assertEqual(len(fake.calls), 1)

    def test_invented_number_falls_back_to_the_template(self):
        first, _, fake = self.run_explain("Now it flies 14 minutes.")
        self.assertEqual(first["source"], "template")
        self.assertIn("Swapped the Tattu FunFly", first["text"])
        self.assertEqual(len(fake.calls), 2)


if __name__ == "__main__":
    unittest.main()
