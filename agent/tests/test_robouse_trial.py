"""robouse_trial: the recorded trial, reading Robo Use's trial folders, and the plumbing against a stand-in bridge.

No test here starts Robo Use or a model. PAI_ROBOUSE_BIN is off, or names a small script that answers like
`anybuild-robouse` from the recorded trial folders; the agent credentials are unset. The last test runs the real
bridge on a gripper built in FreeCAD, and only where all of it is installed.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pai_agent import orchestrator
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools import robouse_trial as rt
from pai_agent.tools.cad_part import LIBRARY
from pai_agent.tools.gripper import gripper_catalog, servo_params

FIXTURES = Path(__file__).parent / "fixtures" / "robouse"
FAILED = FIXTURES / "anybuild-gripper-cube-40mm-400g-in-bowl"
RECORDED = rt.RECORDED_DIR / rt.RECORDED_TASK

# What a bridge command needs to answer: `task` writes a folder, `check` keeps the recorded trials, `trial` copies the
# recorded reference trial as an agent's. FAKE_ROBOUSE picks a misbehaviour; every call is logged with its environment.
STAND_IN = """#!{python}
import json, os, shutil, sys, time
from pathlib import Path

RECORDED = Path({recorded!r})
args = sys.argv[1:]
with open({log!r}, "a") as log:
    log.write(json.dumps({{"args": args, "record_size": os.environ.get("ROBOUSE_RECORD_SIZE"), "pid": os.getpid()}}) + "\\n")
mode = os.environ.get("FAKE_ROBOUSE", "")
opt = lambda name: args[args.index(name) + 1]
if args[0] == "task":
    if mode == "refuse":
        print("anybuild-robouse: The cube is 80 mm wide, but this gripper opens 76.0 mm; it needs 4 mm to spare to reach around it.", file=sys.stderr)
        sys.exit(2)
    folder = Path(opt("--out")) / RECORDED.name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "task.md").write_text("---\\n---\\n")
    print(json.dumps({{"task_dir": str(folder)}}, indent=2))
elif args[0] == "check":
    if mode == "hang":
        time.sleep(60)
    keep = Path(opt("--keep-trials"))
    for harness in ("oracle", "noop"):
        shutil.copytree(RECORDED / harness, keep / harness)
    report = json.loads((RECORDED / "check.json").read_text())
    print(json.dumps({{**report, "task_dir": args[1]}}, indent=2))
    sys.exit(0 if report["valid"] else 1)
elif args[0] == "trial":
    source = next((RECORDED / "oracle").iterdir())
    target = Path(opt("--out")) / source.name.replace("__oracle__", "__claude-code__")
    shutil.copytree(source, target)
    config = json.loads((target / "config.json").read_text())
    (target / "config.json").write_text(json.dumps({{**config, "harness": "claude-code"}}))
    print(json.dumps({{"trial_dir": str(target), "reward": 1.0, "exception": None}}, indent=2))
"""


def gripper_state(directory: Path, servo: str = "towerpro-mg996r") -> BuildState:
    """A built gripper as the mock story leaves it: MG996R, printed TPU pads, the template's sizes, the 66 mm 200 g can."""

    catalog = {part["id"]: part for part in gripper_catalog()["parts"]}
    state = BuildState("robouse-test", directory)
    state.product = "gripper"
    state.brief = {"object_mass_g": 200.0, "object_width_mm": 66.0, "max_weight_g": 150.0, "budget_eur": 30.0}
    state.selected = {"servo": dict(catalog[servo]), "pads": dict(catalog["pads-tpu-printed"])}
    params = {key: default for key, (default, _low, _high) in LIBRARY["gripper"]["params"].items()}
    params.update(servo_params(state))
    state.part = {"name": "Robot gripper", "template": "gripper", "params": params, "parts": []}
    return state


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ctx = Ctx(EventBus(), gripper_state(self.root), auto_steps=False)
        clean = {k: v for k, v in os.environ.items() if k not in {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "FAKE_ROBOUSE"}}
        self.environment = patch.dict(os.environ, {**clean, "PAI_ROBOUSE_BIN": "off"}, clear=True)
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def trials(self) -> list[dict]:
        return [ev for ev in self.ctx.bus.events if ev.get("type") == "trial"]

    def stand_in(self) -> Path:
        """Points PAI_ROBOUSE_BIN at the stand-in bridge; the gripper's MJCF export is a placeholder file."""

        cli = self.root / "anybuild-robouse"
        cli.write_text(STAND_IN.format(python=sys.executable, recorded=str(RECORDED), log=str(self.root / "calls.jsonl")))
        cli.chmod(0o755)
        os.environ["PAI_ROBOUSE_BIN"] = str(cli)
        self.export = patch.object(rt, "export_hand", lambda state, path: path.write_text("<mujoco/>"))
        self.export.start()
        self.addCleanup(self.export.stop)
        return cli

    def calls(self) -> list[dict]:
        log = self.root / "calls.jsonl"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.is_file() else []


class ReadingTrials(unittest.TestCase):
    def test_the_recorded_trial_reads_like_a_live_one(self):
        trial, validity = rt.read_recorded()
        self.assertEqual(validity["reference"], 1.0)
        self.assertEqual(validity["noop"], 0.0)
        self.assertTrue(validity["valid"])
        self.assertEqual(validity["report"][-1], "valid")
        self.assertEqual((trial["harness"], trial["reward"], trial["outcome"]), ("oracle", 1.0, "done"))
        self.assertEqual((trial["steps_used"], trial["max_steps"]), (242, 800))
        self.assertEqual(trial["provenance"], {"robouse": "0.6.1", "mujoco": "3.3.0"})
        self.assertEqual(trial["design"]["servo"], "TowerPro MG996R servo")
        self.assertEqual((trial["design"]["object_width_mm"], trial["design"]["object_mass_g"]), (66.0, 200.0))
        self.assertTrue(trial["video"].is_file())
        self.assertEqual(trial["video_info"]["size"], [960, 720])

        steps = trial["steps"]
        # Eight motions and grips, then robo done; the runner's own status request is not a step.
        self.assertEqual([s["op"] for s in steps], ["move_to", "move_to", "grip", "move_to", "move_to", "move_to", "grip", "move_to", "done"])
        self.assertEqual(steps[0]["action"], "robo move-to -0.13 -0.06 0.1162 --grip -1")
        self.assertEqual(steps[2]["action"], "robo grip 1 --steps 25")
        self.assertEqual(steps[-1]["action"], 'robo done "the cube is in the bowl"')
        self.assertEqual(steps[2]["holding"], ["cube"])
        self.assertIn("holding cube", steps[2]["result"])
        duration = trial["video_info"]["duration_s"]
        ends = [s["t_end"] for s in steps]
        self.assertEqual(ends, sorted(ends))
        self.assertTrue(all(0 <= s["t_start"] <= s["t_end"] <= duration for s in steps))
        self.assertEqual(steps[0]["t_start"], 0.0)

        self.assertEqual(len(trial["ee_path"]), 242)
        self.assertTrue(all(0 <= row[0] <= duration for row in trial["ee_path"]))
        self.assertAlmostEqual(max(f for _t, f in trial["force"]), trial["metrics"]["max_contact_force_n"], places=2)
        target = trial["scene"]["target"]
        self.assertEqual((target["kind"], target["inner_diameter_m"]), ("bowl", 0.14))
        self.assertEqual(trial["scene"]["object"]["size_m"], [0.066, 0.066, 0.066])
        self.assertEqual(trial["analysis"]["dropped"], None)
        self.assertTrue(trial["analysis"]["held"] and trial["analysis"]["released"])
        self.assertLess(trial["analysis"]["lift_slip_mm"], 2.0)
        self.assertEqual(rt.verdict(trial, validity), "pass")
        self.assertIn("put the cube in the bowl", rt.summary(trial, "pass"))

    def test_a_failed_reference_names_the_slip_and_where_the_cube_fell(self):
        # MG996R on a 40 mm, 400 g cube: AnyBuild's own grip calculation passes it at 2.43x; in Robo Use the cube drops.
        report = json.loads((FAILED / "check.json").read_text())
        validity, reference = rt.check_validity(report, FAILED)
        self.assertEqual((validity["reference"], validity["noop"], validity["valid"]), (0.0, 0.0, False))
        trial = rt.read_trial(reference)
        self.assertIsNone(trial["video"])
        self.assertEqual(trial["analysis"]["dropped"], "carry")
        self.assertAlmostEqual(trial["analysis"]["lift_slip_mm"], 5.8, places=1)
        self.assertEqual(rt.verdict(trial, validity), "fail")
        self.assertEqual(
            rt.summary(trial, "fail"),
            "Even the reference solution fails with this gripper: the cube slipped 5.8 mm in the fingers during the lift "
            "and fell out during the carry, 15 cm from the middle of the bowl.",
        )

    def test_a_no_op_that_scores_makes_the_task_invalid(self):
        trial, _validity = rt.read_recorded()
        self.assertEqual(rt.verdict(trial, {"reference": 1.0, "noop": 1.0, "valid": False}), "invalid")
        self.assertTrue(rt.summary(trial, "invalid").startswith("Not counted"))

    def test_requests_read_as_command_lines(self):
        self.assertEqual(rt.action_text({"op": "observe", "image": True}), "robo observe --image")
        self.assertEqual(rt.action_text({"op": "act", "action": [0.01, 0, -0.02, 1], "repeat": 5}), "robo act 0.01 0 -0.02 1 --repeat 5")
        self.assertEqual(rt.action_text({"op": "give_up", "text": "cannot reach"}), 'robo give-up "cannot reach"')
        self.assertEqual(rt.action_text({"op": "move_to", "pos": [0.12, 0.1, 0.0635]}), "robo move-to 0.12 0.1 0.0635")

    def test_the_offline_demo_phrases(self):
        for text in ("Test it in Robo Use", "run a robouse trial", "an independent test of the gripper", "Let Claude Code drive it in robo-use"):
            self.assertTrue(rt.wants_trial(text), text)
        for text in ("Make it lighter", "stress test it", "use a stronger servo", "train the robot"):
            self.assertFalse(rt.wants_trial(text), text)


class RecordedStandIn(Base):
    async def test_without_robo_use_the_recorded_trial_of_the_same_design_stands_in(self):
        result = await rt.robouse_trial(self.ctx, {})
        self.assertTrue(result["ok"])
        self.assertEqual((result["status"], result["verdict"]), ("recorded", "pass"))
        self.assertTrue(result["recorded"]["matches_build"])
        self.assertIn("turned off", result["detail"])
        self.assertIn("this same design (TowerPro MG996R servo, printed TPU finger pads, 76 mm jaw, 66 mm 200 g cube)", result["detail"])
        self.assertNotIn("ee_path", result)
        [event] = self.trials()
        self.assertEqual(event["status"], "recorded")
        self.assertEqual(event["video_url"], f"/files/robouse-test/{event['id']}.mp4")
        self.assertTrue((self.root / (event["id"] + ".mp4")).is_file())
        self.assertEqual(event["version"], 1)
        # The contract in docs/events.md.
        for key in ("id", "task_id", "task_title", "harness", "status", "reward", "outcome", "steps_used", "max_steps", "wall_s", "metrics",
                    "validity", "video_url", "steps", "ee_path", "force", "summary", "version", "verdict", "scene", "analysis", "design", "detail"):
            self.assertIn(key, event)
        self.assertEqual(event["task_title"], "Put the cube in the bowl")
        self.assertEqual({"max_contact_force_n", "safety_events"} - set(event["metrics"]), set())
        self.assertEqual({k: event["validity"][k] for k in ("reference", "noop", "valid")}, {"reference": 1.0, "noop": 0.0, "valid": True})
        self.assertFalse(any(key.startswith("_") for step in event["steps"] for key in step))
        json.dumps(event)

    async def test_a_different_design_is_shown_as_the_example_and_never_as_this_build(self):
        self.ctx.state = gripper_state(self.root, servo="towerpro-sg90")
        result = await rt.robouse_trial(self.ctx, {})
        self.assertEqual(result["status"], "recorded")
        self.assertFalse(result["recorded"]["matches_build"])
        self.assertIn("on AnyBuild's example gripper", result["detail"])
        self.assertIn("not on this build", result["detail"])
        self.assertIn("do not quote its numbers", result["next"])
        # The example's design, not the bench's: the SG90 never ran.
        self.assertEqual(self.trials()[0]["design"]["servo"], "TowerPro MG996R servo")
        self.assertIn("with AnyBuild's example gripper in 242 of 800 steps", result["summary"])
        self.assertNotIn("this gripper", result["summary"])

    async def test_a_bigger_cube_is_not_the_recorded_design(self):
        self.ctx.state.brief["object_width_mm"] = 50.0
        self.assertFalse(rt.matches_recorded(self.ctx.state, "bowl"))
        self.ctx.state.brief["object_width_mm"] = 66.0
        self.assertTrue(rt.matches_recorded(self.ctx.state, "bowl"))
        self.assertFalse(rt.matches_recorded(self.ctx.state, "pad"))

    async def test_it_needs_a_built_gripper_and_sane_arguments(self):
        self.assertFalse((await rt.robouse_trial(self.ctx, {"harness": "codex"}))["ok"])
        self.assertFalse((await rt.robouse_trial(self.ctx, {"goal": "shelf"}))["ok"])
        self.ctx.state.part = None
        self.assertIn("built gripper", (await rt.robouse_trial(self.ctx, {}))["error"])
        self.ctx.state = BuildState("robouse-test", self.root)
        self.assertFalse((await rt.robouse_trial(self.ctx, {}))["ok"])
        self.assertEqual(self.trials(), [])

    async def test_the_registry_runs_it_as_a_tool(self):
        from pai_agent.tools.registry import SCHEMAS, call_tool

        self.assertIn("robouse_trial", {schema["name"] for schema in SCHEMAS})
        result = await call_tool(self.ctx, "robouse_trial", {})
        self.assertEqual(result["status"], "recorded")
        tools = [ev for ev in self.ctx.bus.events if ev.get("type") == "tool" and ev["name"] == "robouse_trial"]
        self.assertEqual([ev["status"] for ev in tools], ["running", "ok"])


class LiveAgainstAStandIn(Base):
    async def test_the_check_runs_with_the_recorded_size_and_its_reference_trial_is_shown(self):
        self.stand_in()
        result = await rt.robouse_trial(self.ctx, {})
        self.assertEqual((result["status"], result["verdict"], result["harness"]), ("done", "pass", "oracle"))
        self.assertEqual(result["validity"]["reference"], 1.0)
        self.assertIn("ran the reference solution on this build", result["detail"])
        events = self.trials()
        self.assertEqual([ev.get("stage") for ev in events], ["export", "task", "check", None])
        self.assertEqual(len({ev["id"] for ev in events}), 1)
        self.assertIsNone(events[-1]["recorded"])
        self.assertTrue((self.root / (events[-1]["id"] + ".mp4")).is_file())
        brief = json.loads((self.root / events[-1]["id"] / "brief.json").read_text())
        self.assertEqual(brief, {"object_mass_g": 200.0, "object_width_mm": 66.0, "goal": "bowl"})
        calls = self.calls()
        self.assertEqual([c["args"][0] for c in calls], ["task", "check"])
        self.assertEqual(calls[1]["record_size"], "960x720")

    async def test_claude_code_without_credentials_does_not_run(self):
        self.stand_in()
        result = await rt.robouse_trial(self.ctx, {"harness": "claude-code"})
        self.assertEqual(result["harness"], "oracle")
        self.assertIn("Claude Code did not run: it needs ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN", result["detail"])
        self.assertNotIn("trial", [c["args"][0] for c in self.calls()])

    async def test_claude_code_runs_after_a_valid_check_within_its_time_limit(self):
        # The stand-in answers for Claude Code; no model runs.
        self.stand_in()
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = "test-token-not-real"
        result = await rt.robouse_trial(self.ctx, {"harness": "claude-code", "timeout_s": 300})
        self.assertEqual((result["status"], result["harness"]), ("done", "claude-code"))
        self.assertIn("ran Claude Code on this build", result["detail"])
        self.assertEqual([ev.get("stage") for ev in self.trials()], ["export", "task", "check", "agent", None])
        trial = next(c["args"] for c in self.calls() if c["args"][0] == "trial")
        self.assertEqual(trial[trial.index("--timeout") + 1], "300")
        self.assertEqual(trial[trial.index("--harness") + 1], "claude-code")

    async def test_a_brief_the_gripper_cannot_take_is_refused_with_the_reason(self):
        self.stand_in()
        os.environ["FAKE_ROBOUSE"] = "refuse"
        result = await rt.robouse_trial(self.ctx, {})
        self.assertEqual((result["status"], result["verdict"]), ("failed", "refused"))
        self.assertIn("The cube is 80 mm wide, but this gripper opens 76.0 mm", result["error"])
        self.assertEqual(self.trials()[-1]["status"], "failed")

    async def test_a_hung_check_is_killed_and_the_recorded_trial_stands_in(self):
        self.stand_in()
        os.environ["FAKE_ROBOUSE"] = "hang"
        with patch.object(rt, "CHECK_TIMEOUT_S", 1.0):
            result = await rt.robouse_trial(self.ctx, {})
        self.assertEqual(result["status"], "recorded")
        self.assertIn("took longer than its time limit", result["detail"])
        pid = next(c["pid"] for c in self.calls() if c["args"][0] == "check")
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    async def test_without_the_exporter_the_recorded_trial_says_why(self):
        self.stand_in()
        self.export.stop()
        with patch.dict(sys.modules, {"pai_agent.mjcf_export": None}):
            result = await rt.robouse_trial(self.ctx, {})
        self.assertEqual(result["status"], "recorded")
        self.assertIn("no MuJoCo export of the gripper", result["detail"])
        self.export.start()


class CheckAdapter(unittest.TestCase):
    """The Check adapters row for Robo Use (pai_agent.adapters) finds the bridge where the tool does and logs its trials."""

    def test_finished_trials_are_robo_uses_runs_and_recorded_ones_are_not(self):
        from pai_agent import adapters

        done = {"type": "trial", "status": "done", "verdict": "pass", "summary": "The reference solution put the cube in the bowl."}
        self.assertEqual(adapters.run_of(done), ("robouse", True, "Robo Use trial passed: The reference solution put the cube in the bowl."))
        self.assertEqual(adapters.run_of({**done, "verdict": "fail"})[:2], ("robouse", False))
        self.assertIsNone(adapters.run_of({**done, "status": "recorded"}))
        self.assertIsNone(adapters.run_of({**done, "status": "running"}))
        refused = {"type": "trial", "status": "failed", "verdict": "refused", "summary": "Robo Use cannot pose this task for this gripper."}
        self.assertEqual(adapters.run_of(refused), ("robouse", False, "Robo Use cannot pose this task for this gripper."))

    def test_the_row_finds_robo_use_where_the_tool_does(self):
        from pai_agent import adapters

        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / "anybuild-robouse"
            cli.write_text("#!/bin/sh\n")
            cli.chmod(0o755)
            with patch.dict(os.environ, {"PAI_ROBOUSE_BIN": str(cli)}):
                self.assertEqual(adapters.find_robouse(), cli)
                self.assertTrue(adapters._robouse().available)
            with patch.dict(os.environ, {"PAI_ROBOUSE_BIN": "off"}):
                self.assertFalse(adapters._robouse().available)
                self.assertIn("PAI_ROBOUSE_BIN=off", adapters._robouse().detail)
            with patch.dict(os.environ, {"PAI_ROBOUSE_BIN": str(Path(tmp) / "missing")}):
                self.assertFalse(adapters._robouse().available)
                self.assertIn("names no program", adapters._robouse().detail)


class OfflineDemo(Base):
    async def test_test_it_in_robo_use_runs_the_tool_with_mechanics_lines(self):
        with (
            patch.object(orchestrator, "claude_enabled", return_value=False),
            patch.object(orchestrator, "_first", AsyncMock(return_value=False)),
        ):
            await orchestrator.run_prompt(self.ctx, "Test it in Robo Use", [])
        [event] = self.trials()
        self.assertEqual(event["status"], "recorded")
        said = [ev["text"] for ev in self.ctx.bus.events if ev.get("type") == "chat" and ev["role"] == "agent"]
        self.assertIn("Independent test in Robo Use", said[0])
        self.assertTrue(said[-1].startswith("Robo Use did not run on this machine, so this is the trial recorded earlier on this same design. The reference solution"))

    async def test_before_a_gripper_is_built_mechanic_asks_for_one(self):
        self.ctx.state = BuildState("robouse-test", self.root)
        with (
            patch.object(orchestrator, "claude_enabled", return_value=False),
            patch.object(orchestrator, "_first", AsyncMock(return_value=False)),
        ):
            await orchestrator.run_prompt(self.ctx, "Test it in Robo Use", [])
        self.assertEqual(self.trials(), [])
        said = [ev["text"] for ev in self.ctx.bus.events if ev.get("type") == "chat" and ev["role"] == "agent"]
        self.assertIn("Ask me for one first", said[-1])


def _real_bridge() -> str:
    """Why the real-bridge test cannot run here, or '' when it can."""

    from pai_agent.freecad_run import find_freecadcmd

    if os.environ.get("PAI_ROBOUSE_BIN", "").strip().lower() == "off" or rt.robouse_cli()[0] is None:
        return "the Robo Use environment is not installed (cd anybuild-robouse && uv sync)"
    try:
        import pai_agent.mjcf_export  # noqa: F401
    except ImportError:
        return "this AnyBuild has no pai_agent.mjcf_export yet"
    return "" if find_freecadcmd() else "FreeCAD is not installed"


@unittest.skipIf(_real_bridge(), _real_bridge())
class RealBridge(unittest.IsolatedAsyncioTestCase):
    async def test_the_template_gripper_scores_reference_1_and_no_op_0(self):
        """The acceptance run: the gripper template built in FreeCAD, exported, written as a task and checked by Robo Use."""

        from pai_agent.paths import SESSIONS_DIR
        from pai_agent.tools.registry import call_tool

        # cad_part keeps its files under the repository, as a session does.
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=SESSIONS_DIR) as tmp, patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "CLAUDE_CODE_OAUTH_TOKEN": ""}):
            ctx = Ctx(EventBus(), gripper_state(Path(tmp)), auto_steps=False)
            built = await call_tool(ctx, "cad_part", {"name": "Robot gripper", "template": "gripper", "material": "PLA", "params": {"jaw_opening_mm": 76, "finger_length_mm": 70}})
            self.assertTrue(built["ok"], built)
            result = await call_tool(ctx, "robouse_trial", {})
        self.assertEqual(result["status"], "done", result.get("detail"))
        self.assertEqual((result["validity"]["reference"], result["validity"]["noop"], result["validity"]["valid"]), (1.0, 0.0, True))
        self.assertEqual(result["verdict"], "pass")


if __name__ == "__main__":
    unittest.main()
