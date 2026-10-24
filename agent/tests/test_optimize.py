"""Design optimizer: goals from the sentence, the Pareto set, and the mock flow from a sentence to the next version."""

import asyncio
import os
import unittest
from unittest import mock

from pai_agent.tools import optimize


def _variant(vid: str, weight: float, minutes: float, feasible: bool = True) -> dict:
    return {"id": vid, "weight_g": weight, "flight_time_min": minutes, "price_eur": 10.0, "arm_stiffness": 1.0, "feasible": feasible}


class Parsing(unittest.TestCase):
    def test_lighter_but_keep_eight_minutes(self):
        goals, keep = optimize.goals_from_text("make the drone lighter but keep 8 minutes")
        self.assertEqual(goals, ["lighter"])
        self.assertEqual(keep, {"min_flight_time_min": 8.0})
        self.assertTrue(optimize.wants_optimize("make the drone lighter but keep 8 minutes"))

    def test_several_goals_and_a_pick(self):
        goals, keep = optimize.goals_from_text("cheaper and stronger, under 50 g")
        self.assertEqual(goals, ["cheaper", "stronger"])
        self.assertEqual(keep, {"max_weight_g": 50.0})
        self.assertEqual(optimize.wants_pick("take variant c"), "C")
        self.assertIsNone(optimize.wants_pick("take the battery out"))


class Pareto(unittest.TestCase):
    def test_dominated_and_infeasible_variants_are_off_the_front(self):
        variants = [_variant("A", 47, 8.5), _variant("B", 48, 8.4), _variant("C", 49, 10.0), _variant("D", 45, 7.0, feasible=False)]
        optimize.pareto(variants, ["lighter", "longer_runtime"])
        self.assertEqual([v["id"] for v in variants if v["pareto"]], ["A", "C"])
        self.assertEqual(optimize._recommend(variants, ["lighter", "longer_runtime"]), "A")


class MockFlow(unittest.TestCase):
    def test_sentence_gives_variants_and_a_pick_becomes_the_next_version(self):
        with mock.patch.dict(os.environ, {"PAI_FORCE_MOCK": "1", "PAI_WARM": "0", "PAI_ASK_TIMEOUT_S": "0", "FREECAD_GUI": "off"}):
            from pai_agent.session import Session

            async def flow():
                session = Session()
                await session.bootstrap()
                await session.start("make the drone lighter but keep 8 minutes")
                await session.task
                run = session.state.optimize["opt1"]
                before = len(session.state.versions)
                pick = run["recommended"]
                started = await session.apply_variant("opt1", pick)
                await session.task
                return session, run, before, pick, started

            session, run, before, pick, started = asyncio.run(flow())
        self.assertGreaterEqual(len(run["variants"]), 4)
        self.assertTrue(all(v["checks"] for v in run["variants"]))
        self.assertTrue(any(v["pareto"] for v in run["variants"]))
        chosen = next(v for v in run["variants"] if v["id"] == pick)
        self.assertTrue(chosen["feasible"])
        self.assertLess(chosen["weight_g"], run["baseline"]["weight_g"])
        self.assertTrue(started["ok"])
        version = session.state.versions[-1]
        self.assertEqual(version["n"], before + 1)
        self.assertEqual(run["applied"], pick)
        self.assertEqual(run["version"], version["n"])
        self.assertTrue(version["label"].startswith("Optimizer: " + pick))
        self.assertTrue(any(d["key"] == "weight_g" and d["after"] < d["before"] for d in version["diff"]))
        events = [e for e in session.bus.events if e.get("type") == "optimize"]
        self.assertEqual([e["status"] for e in events], ["running", "done", "done"])
        self.assertGreaterEqual(session.state.metrics["flight_time_min"], 8.0)


if __name__ == "__main__":
    unittest.main()
