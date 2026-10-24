"""Mock routing in run_prompt: which prompts train, stress test, or do both in order."""

import unittest
from unittest.mock import AsyncMock, patch

from pai_agent import orchestrator


class Ctx:
    def __init__(self):
        self.state = type("State", (), {"finished": True, "started": True})()
        self.chat = AsyncMock()


class RoutingTest(unittest.IsolatedAsyncioTestCase):
    def test_combined_phrase(self):
        self.assertTrue(orchestrator.wants_train_then_stress("train it, then stress test it"))
        self.assertTrue(orchestrator.wants_train_then_stress("Train the drone and stress test it"))
        self.assertFalse(orchestrator.wants_train_then_stress("stress test it"))
        self.assertFalse(orchestrator.wants_train_then_stress("train it"))
        self.assertFalse(orchestrator.wants_train_then_stress("stress test the trained controller"))

    async def test_train_then_stress_runs_both_in_order(self):
        order = []
        train = AsyncMock(side_effect=lambda ctx, **kw: order.append("train"))
        stress = AsyncMock(side_effect=lambda ctx: order.append("stress"))
        with (
            patch.object(orchestrator, "claude_enabled", return_value=False),
            patch.object(orchestrator, "_first", AsyncMock(return_value=False)),
            patch.object(orchestrator, "run_mock_training", train),
            patch.object(orchestrator, "run_stress_mock", stress),
        ):
            await orchestrator.run_prompt(Ctx(), "train it, then stress test it", [])
        self.assertEqual(order, ["train", "stress"])

    async def test_stress_alone_does_not_train(self):
        train, stress = AsyncMock(), AsyncMock()
        with (
            patch.object(orchestrator, "claude_enabled", return_value=False),
            patch.object(orchestrator, "_first", AsyncMock(return_value=False)),
            patch.object(orchestrator, "_mock_omniverse", AsyncMock(return_value=False)),
            patch.object(orchestrator, "_next_review", return_value=None),
            patch.object(orchestrator, "run_mock_training", train),
            patch.object(orchestrator, "run_stress_mock", stress),
        ):
            await orchestrator.run_prompt(Ctx(), "stress test the trained controller", [])
        train.assert_not_called()
        stress.assert_called_once()


if __name__ == "__main__":
    unittest.main()
