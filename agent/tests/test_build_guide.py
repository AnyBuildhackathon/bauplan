"""The build guide checks the steps Claude writes and publishes one event."""

import asyncio
import copy
import tempfile
import unittest
from pathlib import Path

from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.scene import PART_TARGETS
from pai_agent.state import BuildState
from pai_agent.tools.build_guide import build_guide, mock_steps
from pai_agent.tools.parts import catalog

CHOSEN = {
    "motor": "betafpv-1102-22000kv",
    "propeller": "gemfan-1635-3",
    "battery": "betafpv-lava-1s-550",
    "flight_controller": "betafpv-f4-1s-12a-aio-v3",
    "frame": "printed-whoop-frame",
}


def _ctx(with_bom: bool = True) -> Ctx:
    state = BuildState(session_id="test", directory=Path(tempfile.mkdtemp()))
    parts = {part["id"]: part for part in catalog()["parts"]}
    state.selected = {category: parts[part_id] for category, part_id in CHOSEN.items()}
    state.cad_params = {"arm_length_mm": 36}
    if with_bom:
        state.bom = {"items": [], "total_eur": 0, "stl_path": ""}
    return Ctx(EventBus(), state, auto_steps=False)


def _run(ctx: Ctx, steps) -> dict:
    return asyncio.run(build_guide(ctx, {"steps": steps}))


class BuildGuideTest(unittest.TestCase):
    def test_mock_steps_cover_every_part_and_publish(self):
        ctx = _ctx()
        result = _run(ctx, mock_steps(ctx))
        self.assertTrue(result["ok"], result.get("error"))
        events = [e for e in ctx.bus.events if e["type"] == "build_guide"]
        self.assertEqual(len(events), 1)
        guide = events[0]
        self.assertEqual(guide["version"], 1)
        self.assertEqual([s["n"] for s in guide["steps"]], list(range(1, len(guide["steps"]) + 1)))
        self.assertEqual({p for s in guide["steps"] for p in s["parts"]}, set(PART_TARGETS))
        self.assertEqual(guide["total_minutes"], sum(s["minutes"] for s in guide["steps"]))
        motors = next(s for s in guide["steps"] if "motor_front_left" in s["parts"])
        self.assertIn("BetaFPV 1102 22000KV", motors["items"])

    def test_needs_bill_of_materials(self):
        ctx = _ctx(with_bom=False)
        result = _run(ctx, mock_steps(ctx))
        self.assertFalse(result["ok"])
        self.assertIn("bom_build", result["error"])

    def test_rejects_unknown_part(self):
        ctx = _ctx()
        steps = copy.deepcopy(mock_steps(ctx))
        steps[0]["parts"] = ["frame", "motor_left"]
        result = _run(ctx, steps)
        self.assertFalse(result["ok"])
        self.assertIn("motor_left", result["error"])
        self.assertEqual(ctx.bus.events, [])

    def test_rejects_steps_out_of_order(self):
        ctx = _ctx()
        steps = copy.deepcopy(mock_steps(ctx))
        steps[1]["n"] = 5
        result = _run(ctx, steps)
        self.assertFalse(result["ok"])
        self.assertIn("step 2", result["error"])

    def test_rejects_uncovered_part(self):
        ctx = _ctx()
        steps = [s for s in copy.deepcopy(mock_steps(ctx)) if "battery" not in s["parts"]]
        for n, step in enumerate(steps, start=1):
            step["n"] = n
        result = _run(ctx, steps)
        self.assertFalse(result["ok"])
        self.assertIn("battery", result["error"])

    def test_rejects_bad_minutes(self):
        ctx = _ctx()
        steps = copy.deepcopy(mock_steps(ctx))
        steps[0]["minutes"] = 0
        self.assertFalse(_run(ctx, steps)["ok"])


if __name__ == "__main__":
    unittest.main()
