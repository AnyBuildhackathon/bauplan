"""AnyBuild Bench: the prompts, the judge of each check, the summary and one mock run through the real flow."""

import asyncio
import os
import unittest

from bench.judge import judge, retries, usage
from bench.run import load_prompts, run_one, summarize
from pai_agent.session import _new_state

CHECKS = {"built", "cad", "bom", "render"}


class PromptsTest(unittest.TestCase):
    def test_twenty_distinct_prompts_with_known_checks(self):
        prompts = load_prompts()
        self.assertEqual(len(prompts), 20)
        self.assertEqual(len({p["id"] for p in prompts}), 20)
        for p in prompts:
            self.assertTrue(p["prompt"] and p["checks"], p["id"])
            for check in p["checks"]:
                self.assertTrue(check in CHECKS or check.startswith("req:"), check)
        self.assertGreaterEqual(sum(1 for p in prompts if p["mock"]), 5)


class JudgeTest(unittest.TestCase):
    def test_requirement_by_id_or_check(self):
        state = _new_state()
        state.requirements = [
            {"id": "tap", "check": "tip_over", "text": "Does not tip", "_met": True, "_shown_detail": "0.9 N"},
            {"id": "weight", "text": "Under 50 g", "_met": False},
        ]
        self.assertTrue(judge("req:tip_over", state, [])["pass"])
        self.assertTrue(judge("req:tap", state, [])["pass"])
        self.assertFalse(judge("req:weight", state, [])["pass"])
        missing = judge("req:torque", state, [])
        self.assertFalse(missing["pass"])
        self.assertEqual(missing["detail"], "requirement missing")

    def test_build_checks(self):
        state = _new_state()
        self.assertFalse(judge("built", state, [])["pass"])
        state.finished, state.stl_path, state.bom = True, "x.stl", {"total_eur": 12.5}
        self.assertTrue(judge("built", state, [])["pass"])
        self.assertTrue(judge("cad", state, [])["pass"])
        self.assertEqual(judge("bom", state, [])["detail"], "12.50 €")
        self.assertTrue(judge("render", state, [{"type": "render"}])["pass"])

    def test_usage_takes_the_last_event_of_each_agent(self):
        events = [
            {"type": "agent", "id": "a", "input_tokens": 10, "output_tokens": 1, "cost_usd": 0.1, "rounds": 1},
            {"type": "agent", "id": "a", "input_tokens": 30, "output_tokens": 5, "cost_usd": 0.3, "rounds": 2},
            {"type": "agent", "id": "b", "input_tokens": 5, "output_tokens": 5, "cost_usd": 0.05, "rounds": 1},
        ]
        u = usage(events)
        self.assertEqual((u["input_tokens"], u["output_tokens"], u["agents"], u["model_rounds"]), (35, 10, 2, 3))
        self.assertAlmostEqual(u["cost_usd"], 0.35)

    def test_retries_count_errors_and_fixes(self):
        events = [
            {"type": "tool", "name": "cad_part", "status": "running"},
            {"type": "tool", "name": "cad_part", "status": "error"},
            {"type": "tool", "name": "cad_update", "status": "ok"},
        ]
        self.assertEqual(retries(events)["retries"], 2)

    def test_summary(self):
        rows = [
            {"status": "done", "pass": True, "checks_passed": 3, "checks_total": 3, "cost_usd": 0.4, "time_s": 10, "retries": 1, "cad_fallbacks": 0, "input_tokens": 1, "output_tokens": 1},
            {"status": "done", "pass": False, "checks_passed": 1, "checks_total": 3, "cost_usd": 0.2, "time_s": 5, "retries": 0, "cad_fallbacks": 0, "input_tokens": 1, "output_tokens": 1},
            {"status": "skipped", "pass": False, "checks_passed": 0, "checks_total": 3, "cost_usd": 0, "time_s": 0, "retries": 0, "cad_fallbacks": 0, "input_tokens": 0, "output_tokens": 0},
        ]
        s = summarize(rows)
        self.assertEqual((s["ran"], s["passed"], s["pass_rate"]), (2, 1, 0.5))
        self.assertAlmostEqual(s["cost_per_product_usd"], 0.3)
        self.assertAlmostEqual(s["cost_per_valid_product_usd"], 0.6)


class MockRunTest(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.get("PAI_FORCE_MOCK")
        os.environ["PAI_FORCE_MOCK"] = "1"

    def tearDown(self):
        if self._env is None:
            os.environ.pop("PAI_FORCE_MOCK", None)
        else:
            os.environ["PAI_FORCE_MOCK"] = self._env

    def test_drone_prompt_through_the_real_flow(self):
        item = next(p for p in load_prompts() if p["id"] == "drone-micro")
        result = asyncio.run(run_one(item, 120))
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["checks_total"], len(item["checks"]))
        self.assertTrue(next(c for c in result["checks"] if c["id"] == "built")["pass"])
        self.assertEqual(result["cost_usd"], 0)


if __name__ == "__main__":
    unittest.main()
