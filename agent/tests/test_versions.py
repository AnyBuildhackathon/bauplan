"""Versions: a snapshot copies the model and records the build, diff finds what changed, restore rebuilds."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pai_agent import versions
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState

SPEC = {
    "id": "phone-stand",
    "name": "Desk phone stand",
    "function": "Holds a phone",
    "parts": [
        {"id": "base", "name": "Base", "kind": "printed", "material": "PETG", "description": "Plate", "params": {"length_mm": 110}},
        {"id": "feet", "name": "Rubber feet", "kind": "bought", "description": "Feet"},
    ],
}


def _generic_ctx(length: float, feet: str, met: bool) -> Ctx:
    directory = Path(tempfile.mkdtemp())
    (directory / "assembly.glb").write_bytes(b"glb")
    state = BuildState(session_id="test", directory=directory)
    state.product = "generic"
    state.spec = json.loads(json.dumps(SPEC))
    state.built = {"base": {"params": {"length_mm": length}, "script": "print('base')", "generated": True}}
    state.picked = {"feet": {"id": feet, "name": feet.replace("-", " ").title()}}
    state.checks = {"tip_over": {"tool": "check_tip_over", "args": {"tilt_deg": 15}}}
    state.assembly = {"glb": "assembly.glb", "product_mass_g": 95.0 + length / 10, "cost_eur": 4.0}
    state.bom = {"total_eur": 4.5, "items": []}
    state.requirements = [{"id": "stable", "text": "Does not tip over", "_met": met}]
    ctx = Ctx(EventBus(), state, auto_steps=False)
    ctx.bus.events.append({"type": "metrics", "weight_g": 106.0, "price_eur": 4.5, "cards": [{"key": "tip", "label": "Tip angle", "value": 20 + length / 10, "unit": "°", "digits": 0}]})
    return ctx


class SnapshotAndDiff(unittest.TestCase):
    def test_commit_copies_the_model_and_diffs_against_the_last_version(self):
        ctx = _generic_ctx(110, "rubber-feet-10mm", met=False)
        ctx.trigger = "chat"
        first = asyncio.run(versions.commit(ctx, label="Design a phone stand"))
        self.assertEqual(first["n"], 1)
        self.assertEqual(first["trigger"], "chat")
        self.assertEqual(first["files"]["glb_url"], "/files/test/v1-assembly.glb")
        self.assertTrue((ctx.state.directory / "v1-assembly.glb").is_file())
        self.assertEqual(first["parts"], {"base": "Base", "feet": "Rubber Feet 10Mm"})
        self.assertEqual(first["nodes"]["feet"], "Rubber feet")
        self.assertEqual(first["params"], {"base.length_mm": 110})
        saved = json.loads((ctx.state.directory / "versions" / "v1" / "reference.json").read_text())
        self.assertEqual(saved["picks"], {"feet": {"select_id": "rubber-feet-10mm"}})
        self.assertEqual(saved["scripts"]["base"]["file"], "base.py")

        # The second build changes the base, swaps the feet and now passes the failed check.
        ctx.state.built["base"]["params"]["length_mm"] = 130
        ctx.state.picked["feet"] = {"id": "rubber-feet-12mm", "name": "Rubber Feet 12Mm"}
        ctx.state.assembly["product_mass_g"] = 108.0
        ctx.state.requirements[0]["_met"] = True
        second = asyncio.run(versions.commit(ctx, label="Make the base longer"))
        self.assertEqual(second["trigger"], "check_failed")
        keys = {row["key"]: row for row in second["diff"]}
        self.assertEqual(keys["weight_g"]["before"], 106.0)
        self.assertEqual(keys["weight_g"]["after"], 108.0)
        self.assertEqual(keys["part:feet"]["after"], "Rubber Feet 12Mm")
        self.assertEqual((keys["param:base.length_mm"]["before"], keys["param:base.length_mm"]["after"]), (110, 130))
        self.assertEqual((keys["req:stable"]["before"], keys["req:stable"]["after"]), ("fail", "pass"))
        published = [ev for ev in ctx.bus.events if ev["type"] == "version"]
        self.assertEqual([ev["n"] for ev in published], [1, 2])

    def test_drone_diff_has_numbers_and_the_battery_swap(self):
        v1 = {"product": "drone", "weight_g": 48.3, "flight_time_min": 8.2, "price_eur": 117.38, "thrust_to_weight": 4.14, "parts": {"battery": "Tattu R-Line 1S 550mAh 95C", "motor": "1103"}}
        v2 = {**v1, "weight_g": 49.5, "flight_time_min": 10.1, "parts": {"battery": "BetaFPV LAVA II 1S 680mAh 95C", "motor": "1103"}}
        rows = {row["key"]: row for row in versions.diff(v1, v2)}
        self.assertEqual(set(rows), {"weight_g", "flight_time_min", "part:battery"})
        self.assertEqual(rows["part:battery"]["before"], "Tattu R-Line 1S 550mAh 95C")
        self.assertEqual(versions.diff(None, v2), [])


def _trial(ctx: Ctx, tid: str, verdict: str, reward: float | None, status: str = "done", matches: bool = True, harness: str = "oracle") -> dict:
    """A finished trial event as robouse_trial publishes it, on the version the bench holds; returns the tool's answer."""

    event = {
        "type": "trial",
        "id": tid,
        "status": status,
        "harness": harness,
        "verdict": verdict,
        "reward": reward,
        "summary": "The reference solution " + ("put the cube in the bowl." if verdict == "pass" else "dropped the cube."),
        "version": versions.bench_version(ctx.state),
        "recorded": {"matches_build": matches, "reason": "Robo Use is turned off here."} if status == "recorded" else None,
    }
    ctx.bus.events.append(event)
    return {"ok": True, "id": tid, "status": status, "verdict": verdict}


class VerdictBook(unittest.TestCase):
    """Independent verdicts (Robo Use) land in the book of the version they judged, next to the version's own test."""

    def _committed(self, length: float = 110, feet: str = "rubber-feet-10mm") -> Ctx:
        ctx = _generic_ctx(length, feet, met=True)
        ctx.trigger = "chat"
        asyncio.run(versions.commit(ctx, label="Design a phone stand"))
        return ctx

    def test_a_verdict_after_the_commit_joins_that_version_and_publishes_it_again(self):
        ctx = self._committed()
        self.assertEqual(ctx.state.versions[0]["verdicts"], [])
        self.assertEqual(versions.bench_version(ctx.state), 1)
        # call_tool hands every finished robouse_trial to after_tool.
        asyncio.run(versions.after_tool(ctx, "robouse_trial", {}, _trial(ctx, "trial-a", "fail", 0.0)))
        [verdict] = ctx.state.versions[0]["verdicts"]
        self.assertEqual(
            {k: verdict[k] for k in ("judge", "label", "trial_id", "harness", "verdict", "reward", "status")},
            {"judge": "robouse", "label": "Robo Use", "trial_id": "trial-a", "harness": "oracle", "verdict": "fail", "reward": 0.0, "status": "done"},
        )
        published = [ev for ev in ctx.bus.events if ev["type"] == "version"]
        self.assertEqual([ev["n"] for ev in published], [1, 1])
        self.assertEqual(published[-1]["verdicts"], ctx.state.versions[0]["verdicts"])
        # The same judge again replaces its verdict; Claude Code driving it is a second line.
        asyncio.run(versions.record_verdict(ctx, _trial(ctx, "trial-b", "pass", 1.0)))
        asyncio.run(versions.record_verdict(ctx, _trial(ctx, "trial-c", "fail", 0.0, harness="claude-code")))
        book = ctx.state.versions[0]["verdicts"]
        self.assertEqual([(v["trial_id"], v["label"]) for v in book], [("trial-b", "Robo Use"), ("trial-c", "Robo Use, Claude Code")])

    def test_the_next_version_diffs_its_verdict_against_the_last(self):
        ctx = self._committed()
        asyncio.run(versions.record_verdict(ctx, _trial(ctx, "trial-1", "fail", 0.0)))
        ctx.state.picked["feet"] = {"id": "rubber-feet-12mm", "name": "Rubber Feet 12Mm"}
        # A chat rebuild in the run where Robo Use failed v1 answers that verdict.
        second = asyncio.run(versions.commit(ctx, label="Fix for Robo Use: bigger feet"))
        self.assertEqual(second["trigger"], "check_failed")
        self.assertNotIn("verdict:robouse", {row["key"] for row in second["diff"]})
        asyncio.run(versions.record_verdict(ctx, _trial(ctx, "trial-2", "pass", 1.0)))
        rows = {row["key"]: row for row in ctx.state.versions[1]["diff"]}
        self.assertEqual((rows["verdict:robouse"]["before"], rows["verdict:robouse"]["after"]), ("fail, reward 0", "pass, reward 1"))
        self.assertEqual(rows["verdict:robouse"]["label"], "Robo Use")
        self.assertEqual([v["verdict"] for v in ctx.state.versions[0]["verdicts"]], ["fail"])
        last = [ev for ev in ctx.bus.events if ev["type"] == "version"][-1]
        self.assertEqual((last["n"], last["verdicts"][0]["verdict"]), (2, "pass"))

    def test_a_rebuild_after_a_passed_verdict_is_a_plain_chat_version(self):
        ctx = self._committed()
        asyncio.run(versions.record_verdict(ctx, _trial(ctx, "trial-ok", "pass", 1.0)))
        ctx.state.picked["feet"] = {"id": "rubber-feet-12mm", "name": "Rubber Feet 12Mm"}
        second = asyncio.run(versions.commit(ctx, label="Make it cheaper"))
        self.assertEqual(second["trigger"], "chat")

    def test_a_verdict_on_a_changed_bench_waits_for_that_design_to_be_committed(self):
        ctx = self._committed()
        # A swap after the commit: the bench is the next version, even before its bill of materials.
        ctx.state.picked["feet"] = {"id": "rubber-feet-12mm", "name": "Rubber Feet 12Mm"}
        self.assertEqual(versions.bench_version(ctx.state), 2)
        asyncio.run(versions.record_verdict(ctx, _trial(ctx, "trial-early", "pass", 1.0)))
        self.assertEqual(ctx.state.versions[0]["verdicts"], [])
        self.assertEqual(len(ctx.state.pending_verdicts), 1)
        second = asyncio.run(versions.commit(ctx, label="Bigger feet"))
        self.assertEqual([v["trial_id"] for v in second["verdicts"]], ["trial-early"])
        self.assertNotIn("bench", second["verdicts"][0])
        self.assertEqual(ctx.state.pending_verdicts, [])

    def test_a_verdict_on_a_design_that_changed_again_before_its_commit_is_dropped(self):
        ctx = self._committed()
        ctx.state.picked["feet"] = {"id": "rubber-feet-12mm", "name": "Rubber Feet 12Mm"}
        asyncio.run(versions.record_verdict(ctx, _trial(ctx, "trial-stale", "pass", 1.0)))
        ctx.state.built["base"]["params"]["length_mm"] = 150
        second = asyncio.run(versions.commit(ctx, label="Bigger feet and a longer base"))
        self.assertEqual(second["verdicts"], [])
        self.assertEqual(ctx.state.pending_verdicts, [])

    def test_only_a_trial_that_judged_this_design_counts(self):
        ctx = self._committed()
        # A recorded trial of another design, a run that could not start and one still running say nothing about v1.
        asyncio.run(versions.record_verdict(ctx, _trial(ctx, "trial-example", "pass", 1.0, status="recorded", matches=False)))
        asyncio.run(versions.record_verdict(ctx, _trial(ctx, "trial-broken", "fail", None, status="failed")))
        self.assertEqual(ctx.state.versions[0]["verdicts"], [])
        asyncio.run(versions.record_verdict(ctx, _trial(ctx, "trial-same", "fail", 0.0, status="recorded")))
        asyncio.run(versions.record_verdict(ctx, _trial(ctx, "trial-refused", "refused", None, status="failed", harness="claude-code")))
        book = {v["trial_id"]: v for v in ctx.state.versions[0]["verdicts"]}
        self.assertEqual(set(book), {"trial-same", "trial-refused"})
        self.assertEqual(versions.verdict_text(book["trial-same"]), "fail, reward 0")
        self.assertEqual(versions.verdict_text(book["trial-refused"]), "cannot take the object")
        self.assertIsNone(book["trial-refused"]["reward"])
        self.assertEqual(versions.verdict_text({"verdict": "invalid", "reward": 0.0}), "not counted")


class Restore(unittest.TestCase):
    def test_generic_restore_rebuilds_the_saved_build_through_the_tools(self):
        ctx = _generic_ctx(110, "rubber-feet-10mm", met=True)
        ctx.trigger = "chat"
        asyncio.run(versions.commit(ctx, label="Design a phone stand"))
        calls = []

        async def call_tool(ctx, name, args):
            calls.append((name, args))
            if name == "bom_build":
                await versions.after_tool(ctx, name, args, {"ok": True})
            return {"ok": True, "total_eur": 4.5}

        with mock.patch("pai_agent.tools.registry.call_tool", call_tool):
            restored = asyncio.run(versions.restore(ctx, 1))
        names = [name for name, _args in calls]
        self.assertEqual(names, ["product_spec", "cad_part", "part_pick", "assemble", "check_tip_over", "blender_render", "bom_build"])
        self.assertEqual(calls[1][1]["script"], "print('base')\n")
        self.assertEqual(calls[2][1], {"part_id": "feet", "select_id": "rubber-feet-10mm"})
        self.assertEqual(restored["n"], 2)
        self.assertEqual(restored["trigger"], "restore")
        self.assertEqual(restored["restored_from"], 1)
        self.assertEqual(len(ctx.state.versions), 2)

    def test_unknown_version_is_refused(self):
        ctx = _generic_ctx(110, "rubber-feet-10mm", met=True)
        with self.assertRaises(ValueError):
            asyncio.run(versions.restore(ctx, 4))


class Labels(unittest.TestCase):
    def test_a_long_request_ends_at_a_word_with_an_ellipsis(self):
        text = "Build a micro drone under 120 euros with at least 8 minutes of flight time, under 50 g."
        self.assertEqual(versions.label_of(text), "Build a micro drone under 120 euros with at least 8 minutes of flight time…")
        self.assertEqual(versions.label_of("Make it fly\n10 minutes."), "Make it fly 10 minutes.")
        self.assertEqual(len(versions.label_of("x" * 200)), versions.LABEL_MAX)


if __name__ == "__main__":
    unittest.main()
