"""The fix loop: Robo Use fails the first version, Mechanic offers fixes, the chosen one is the next version, judged again.

"Gripper that puts a 400 g cube into a bowl" builds v1 with the MG996R and printed pads on a 53 mm cube (400 g of
aluminium). AnyBuild's own grip test passes it at 2.1x; Robo Use's reference solution drops the cube in the carry.
Every fix the question offers passes Robo Use as v2. No test here starts Robo Use or a model: PAI_ROBOUSE_BIN is off,
so the trials recorded on exactly these designs (agent/data/robouse/recorded/) give the verdicts, or a stand-in
bridge that always fails drives the round limit. FreeCAD and Blender are the fallbacks (the fallback_apps fixture).
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pai_agent import mock_gripper, orchestrator
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.paths import SESSIONS_DIR
from pai_agent.state import BuildState
from pai_agent.tools import robouse_trial as rt
from pai_agent.tools.gripper import EUROS, GRAMS, MILLIMETRES, product_brief, typed_number

STORY = "Gripper that puts a 400 g cube into a bowl"
FAILED = Path(__file__).parent / "fixtures" / "robouse" / "anybuild-gripper-cube-40mm-400g-in-bowl"
# A bridge whose reference solution always drops the cube: `check` keeps the failing fixture's trials.
ALWAYS_FAILS = """#!{python}
import json, shutil, sys
from pathlib import Path

FAILED = Path({failed!r})
args = sys.argv[1:]
opt = lambda name: args[args.index(name) + 1]
if args[0] == "task":
    folder = Path(opt("--out")) / FAILED.name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "task.md").write_text("---\\n---\\n")
    print(json.dumps({{"task_dir": str(folder)}}))
elif args[0] == "check":
    keep = Path(opt("--keep-trials"))
    for harness in ("oracle", "noop"):
        shutil.copytree(FAILED / harness, keep / harness)
    print(json.dumps({{**json.loads((FAILED / "check.json").read_text()), "task_dir": args[1]}}))
    sys.exit(1)
"""


@pytest.fixture
def offline(fallback_apps, monkeypatch):
    """No key, no model, no Robo Use: the recorded trials judge."""

    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAI_ROBOUSE_BIN", "off")


@pytest.fixture
def bench():
    """A session folder where a session keeps one: cad_part stores its files under the repository."""

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=SESSIONS_DIR) as tmp:
        yield Path(tmp)


class Room:
    """The people in the room: they answer the n-th question with answers[n], else the question's default."""

    def __init__(self, answers: dict[int, str] | None = None):
        self.answers = answers or {}
        self.questions: list[dict] = []

    async def __call__(self, question: dict) -> str:
        self.questions.append(question)
        ids = [option["id"] for option in question["options"]]
        pick = self.answers.get(len(self.questions))
        return pick if pick in ids else str(question["default_id"])


def _ctx(directory: Path, room: Room) -> Ctx:
    ctx = Ctx(EventBus(), BuildState("fix-loop", directory), auto_steps=False, asker=room)
    ctx.trigger, ctx.label = "chat", STORY
    return ctx


def _play(ctx: Ctx, text: str) -> None:
    with patch.object(orchestrator, "claude_enabled", return_value=False), patch.object(orchestrator, "_first", AsyncMock(return_value=False)):
        asyncio.run(orchestrator.run_prompt(ctx, text, []))


def _events(ctx: Ctx, kind: str) -> list[dict]:
    return [ev for ev in ctx.bus.events if ev.get("type") == kind]


def _said(ctx: Ctx) -> list[str]:
    return [ev["text"] for ev in _events(ctx, "chat") if ev["role"] == "agent"]


def test_the_story_ends_with_robo_use_0_on_v1_and_1_on_v2(bench, offline):
    room = Room()
    ctx = _ctx(bench, room)
    _play(ctx, STORY)

    state = ctx.state
    assert state.brief["object_width_mm"] == 53.0 and state.brief["object_mass_g"] == 400.0
    v1, v2 = state.versions
    # v1: the MG996R with printed pads. AnyBuild's own test passes it; Robo Use, recorded on this design, drops the cube.
    assert v1["parts"]["servo"] == "TowerPro MG996R servo" and v1["sim"] == "pass"
    assert [(v["judge"], v["verdict"], v["reward"], v["status"]) for v in v1["verdicts"]] == [("robouse", "fail", 0.0, "recorded")]
    assert "fell out during the carry" in v1["verdicts"][0]["summary"]
    # One fix round: the question offers three fixes, the strongest margin first, and its default builds v2.
    [question] = room.questions
    assert [option["id"] for option in question["options"]] == ["servo", "pads", "fingers"]
    assert question["default_id"] == "servo" and question["text"].startswith("Which fix goes into v2?")
    assert question["options"][0]["label"] == "DS3218 servo, 19 kg cm: grip safety 4.3x, +7.00 €"
    assert v2["parts"]["servo"] == "DSSERVO DS3218 20 kg servo" and v2["sim"] == "pass"
    assert (v2["trigger"], v2["label"]) == ("check_failed", "Fix for Robo Use: DS3218 servo")
    assert [(v["verdict"], v["reward"]) for v in v2["verdicts"]] == [("pass", 1.0)]
    rows = {row["key"]: row for row in v2["diff"]}
    assert (rows["verdict:robouse"]["before"], rows["verdict:robouse"]["after"]) == ("fail, reward 0", "pass, reward 1")
    assert rows["part:servo"]["after"] == "DSSERVO DS3218 20 kg servo"
    # Every trial is a recorded one of the same design, and each version is published again with its verdict.
    trials = [ev for ev in _events(ctx, "trial") if ev["status"] != "running"]
    assert [(ev["version"], ev["verdict"], ev["recorded"]["matches_build"]) for ev in trials] == [(1, "fail", True), (2, "pass", True)]
    assert [ev["n"] for ev in _events(ctx, "version")] == [1, 1, 2, 2]
    # The comparison opens with both versions, and Mechanic names both verdicts.
    [compare] = [ev for ev in _events(ctx, "ui") if ev["control"] == "panel:compare"]
    assert compare["versions"] == [1, 2]
    said = _said(ctx)
    assert any("Robo Use also carries it sideways to the bowl" in line for line in said)
    assert said[-1].startswith("Done. v2 puts the cube where it belongs: Robo Use scores v1 0 and v2 1.")


@pytest.mark.parametrize(("fix", "servo", "pads", "fingers"), [("pads", "TowerPro MG996R servo", "Silicone grip pads 30 x 20 mm", 70.0), ("fingers", "TowerPro MG996R servo", "Printed TPU finger pads", 55.0)])
def test_every_fix_offered_passes_robo_use(bench, offline, fix, servo, pads, fingers):
    ctx = _ctx(bench, Room({1: fix}))
    _play(ctx, STORY)
    v1, v2 = ctx.state.versions
    assert v2["parts"]["servo"] == servo and v2["parts"]["pads"] == pads
    assert v2["params"]["finger_length_mm"] == fingers
    assert [v["verdict"] for v in v1["verdicts"]] == ["fail"]
    assert [v["verdict"] for v in v2["verdicts"]] == ["pass"]


def test_a_request_without_a_goal_gets_no_outside_judge(bench, offline):
    room = Room()
    ctx = _ctx(bench, room)
    _play(ctx, "Design a robot gripper that picks up a 200 g soda can, 66 mm wide")
    [v1] = ctx.state.versions
    assert v1["verdicts"] == [] and _events(ctx, "trial") == [] and room.questions == []
    assert _said(ctx)[-1].startswith("Done. The gripper weighs")


def test_two_failed_fix_rounds_hand_the_decision_to_the_user(bench, tmp_path, offline, monkeypatch):
    # Robo Use runs here, through a bridge whose reference solution always drops the cube.
    bridge = tmp_path / "anybuild-robouse"
    bridge.write_text(ALWAYS_FAILS.format(python=sys.executable, failed=str(FAILED)))
    bridge.chmod(0o755)
    monkeypatch.setenv("PAI_ROBOUSE_BIN", str(bridge))
    monkeypatch.setattr(rt, "export_hand", lambda state, path: path.write_text("<mujoco/>"))
    room = Room()
    ctx = _ctx(bench, room)
    _play(ctx, STORY)

    # v1 and two fixes, each judged once: no third fix round.
    assert len(ctx.state.versions) == 3
    assert [[v["verdict"] for v in version["verdicts"]] for version in ctx.state.versions] == [["fail"], ["fail"], ["fail"]]
    assert [q["text"].split("?")[0] for q in room.questions] == ["Which fix goes into v2", "Which fix goes into v3", "Robo Use still drops the cube with v3. What now"]
    # The second round offers what is left after the DS3218: no stronger servo.
    assert [option["id"] for option in room.questions[1]["options"]] == ["pads", "fingers"]
    assert len([ev for ev in _events(ctx, "trial") if ev["status"] == "done"]) == 3
    assert _said(ctx)[-1] == "v3 stays the current version. Robo Use's verdict on it is 0, so it is not ready for this task yet."
    assert not [ev for ev in _events(ctx, "ui") if ev["control"] == "panel:compare"]


def test_a_fixed_design_without_a_recording_stays_unjudged(bench, offline, monkeypatch):
    real = rt.recording_for
    monkeypatch.setattr(rt, "recording_for", lambda state, goal: real(state, goal) if state.selected["servo"]["id"] == "towerpro-mg996r" else None)
    ctx = _ctx(bench, Room())
    _play(ctx, STORY)
    v1, v2 = ctx.state.versions
    assert [v["verdict"] for v in v1["verdicts"]] == ["fail"]
    # The example gripper's recording stood in, so v2 has no verdict and Mechanic says how to get one.
    assert v2["verdicts"] == []
    assert _said(ctx)[-1].startswith("v2 is built, but Robo Use is not installed here and there is no recorded trial of this design")


def test_test_it_in_robo_use_on_a_failing_build_runs_the_fix_loop(bench, offline):
    room = Room({1: "fingers"})
    ctx = _ctx(bench, room)
    # The story without its judge: the request names no goal, so v1 is built and nothing judged it yet.
    with patch.object(mock_gripper, "placed_goal", lambda text: None):
        _play(ctx, STORY)
    assert [v["verdicts"] for v in ctx.state.versions] == [[]]
    _play(ctx, "Test it in Robo Use")
    v1, v2 = ctx.state.versions
    assert [v["verdict"] for v in v1["verdicts"]] == ["fail"] and [v["verdict"] for v in v2["verdicts"]] == ["pass"]
    assert v2["params"]["finger_length_mm"] == 55.0


def test_a_number_the_user_did_not_type_is_mechanics_proposal(tmp_path):
    ctx = Ctx(EventBus(), BuildState("brief", tmp_path), auto_steps=False)
    ctx.state.requests.append(STORY)
    numbers, material = mock_gripper._brief_numbers(STORY)
    assert (numbers["object_width_mm"], material) == (53.0, "aluminium")
    asyncio.run(product_brief(ctx, {"product": "gripper", "quote": STORY, **numbers}))
    sources = {row["id"]: (row["source"], row["source_quote"]) for row in ctx.state.requirements}
    assert sources["payload"] == ("user", STORY)
    assert sources["opening"] == ("proposed", "Proposed by Mechanic: your request names no size, so the jaws are sized for 53 mm.")
    assert sources["weight"][0] == "proposed" and sources["budget"][0] == "proposed"

    typed = "Design a robot gripper for our arm that picks up a 200 g soda can, 66 mm wide. Keep it under 150 g and 30 €."
    ctx = Ctx(EventBus(), BuildState("brief", tmp_path), auto_steps=False)
    ctx.state.requests.append(typed)
    asyncio.run(product_brief(ctx, {"product": "gripper", "quote": typed, "object_mass_g": 200, "object_width_mm": 66, "max_weight_g": 150, "budget_eur": 30}))
    assert {row["source"] for row in ctx.state.requirements if row["id"] != "printable"} == {"user"}


def test_typed_numbers_in_their_units():
    state = BuildState("units", Path("."))
    state.requests = ["a 0.4 kg block, 5.3 cm wide, under €25 and 40 euros", "the 66mm can"]
    assert typed_number(state, 400.0, GRAMS) and typed_number(state, 53.0, MILLIMETRES) and typed_number(state, 66.0, MILLIMETRES)
    assert typed_number(state, 25.0, EUROS) and typed_number(state, 40.0, EUROS)
    assert not typed_number(state, 200.0, GRAMS) and not typed_number(state, 30.0, EUROS) and not typed_number(state, 5.0, MILLIMETRES)


def test_cube_sizes_follow_mass_and_material():
    assert mock_gripper.cube_side(400.0, "a 400 g cube") == (53.0, "aluminium")
    assert mock_gripper.cube_side(400.0, "a 400 g steel cube") == (37.0, "steel")
    assert mock_gripper.cube_side(400.0, "a wooden block of 400 g") == (83.0, "wood")
    assert mock_gripper.placed_goal("put it onto the pad") == "pad" and mock_gripper.placed_goal("hold a can") is None


def test_a_pass_where_the_cube_only_fell_in_says_so():
    trial = {
        "harness": "oracle",
        "design": {"goal": "bowl"},
        "analysis": {"held": True, "lift_slip_mm": 3.0, "dropped": "carry", "released": False, "distance_mm": 38.0},
        "metrics": {"max_contact_force_n": 13.5},
        "steps_used": 239,
        "max_steps": 800,
        "reward": 1.0,
    }
    assert rt.summary(trial, "pass") == (
        "The reference solution got the cube in the bowl with this gripper in 239 of 800 steps, but it fell out of the fingers "
        "during the carry and landed in the bowl, 4 cm from its middle."
    )


def test_every_story_design_has_its_recording():
    """The offline story's verdicts: one recording per design it can build, each recorded on that exact design."""

    designs = {(d["servo_id"], d["pads_id"], d["params"]["finger_length_mm"]) for d in (rt._json(f / "design.json") for f in rt.recordings()) if d.get("story") == STORY}
    assert designs == {
        ("towerpro-mg996r", "pads-tpu-printed", 70.0),
        ("dsservo-ds3218", "pads-tpu-printed", 70.0),
        ("towerpro-mg996r", "pads-silicone", 70.0),
        ("towerpro-mg996r", "pads-tpu-printed", 55.0),
    }
    verdicts = {}
    for folder in rt.recordings():
        trial, validity = rt.read_recorded(folder)
        verdicts[folder.name] = rt.verdict(trial, validity)
    assert rt.recordings()[0].name == rt.RECORDED_TASK
    assert sorted(verdicts.values()) == ["fail", "pass", "pass", "pass", "pass"]
    assert verdicts["anybuild-gripper-cube-53mm-400g-in-bowl--towerpro-mg996r--pads-tpu-printed--fingers-70mm"] == "fail"
    # Recorded without the recording machine's paths.
    for path in rt.RECORDED_DIR.glob("*/*/*/config.json"):
        config = json.loads(path.read_text())
        assert config["task_path"].startswith("tasks/") and config["workspace"] == ""
