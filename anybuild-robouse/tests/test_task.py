"""Tasks from a design brief: `robouse tasks check` passes them (reference solution 1, no-op control 0), a trial reports
reward, verdict and video, a weak design fails its own benchmark, and briefs the hand cannot grasp are refused.

Run with: cd anybuild-robouse && uv run pytest
The trials run Robo Use's episode server headless, about 10 s each. No model is called: agent harnesses are refused
without their credentials before anything starts.
"""

from __future__ import annotations

import json
import re

import imageio
import pytest
from robouse.tasks import load_task

from anybuild_robouse import cli, trial
from anybuild_robouse.hand import example_hand
from anybuild_robouse.task import Brief, TaskError, write_task


def _weaker(text: str, factor: float) -> str:
    """The example hand with a servo `factor` times as strong (stiffness and holding torque)."""

    def scale(match: re.Match) -> str:
        tag = re.sub(r'kp="([^"]+)"', lambda m: f'kp="{float(m.group(1)) * factor:.6g}"', match.group(0))
        return re.sub(r'forcerange="(\S+) (\S+)"', lambda m: f'forcerange="{float(m.group(1)) * factor:.6g} {float(m.group(2)) * factor:.6g}"', tag)

    return re.sub(r"<position [^>]*/>", scale, text)


def test_the_brief_becomes_a_valid_task(tmp_path) -> None:
    folder = write_task(tmp_path, example_hand(), Brief.from_dict({"object_mass_g": 200, "object_width_mm": 66, "max_weight_g": 300}))
    assert folder.name == "anybuild-gripper-cube-66mm-200g-in-bowl"
    valid, report = trial.check(folder)
    assert valid, report
    assert "reference solution: reward 1.0" in report
    assert "no-op control: reward 0.0" in report


def test_task_md_carries_the_hand_and_the_scene(tmp_path) -> None:
    folder = write_task(tmp_path, example_hand(), Brief(200, 66))
    task = load_task(folder)
    spec = task.spec
    assert spec["backend"] == "anybuild-gripper"
    assert spec["anybuild_hand"] == example_hand()  # exactly, so the task folder alone runs the episode
    cube = spec["scenario"]["objects"][0]
    assert cube["size"] == [0.033] * 3
    assert cube["density"] * 0.066**3 == pytest.approx(0.2, rel=1e-3)
    assert spec["scenario"]["goals"] == [{"type": "in", "obj": "cube", "container": "bowl"}]
    assert task.metadata["anybuild"]["servo"] == "TowerPro MG996R servo"
    assert "anybuild_hand: |\n" in (folder / "task.md").read_text()  # a readable block, not one escaped line
    body = task.instruction
    assert "66 mm on each side, 200 g" in body and "76 mm between the pads" in body
    assert "## How to control the robot" in body
    solve = (folder / "oracle" / "solve.sh").read_text()
    assert solve.count("robo move-to") == 6 and solve.rstrip().endswith('robo done "the cube is in the bowl"')
    # The grasp keeps the cube's top 5 mm under the servo, which hangs 23.55 mm above the tool point.
    assert "robo move-to -0.13 -0.06 0.0475 " in solve


def test_the_trial_reports_reward_verdict_and_video(tmp_path, capsys) -> None:
    folder = write_task(tmp_path / "tasks", example_hand(), Brief(150, 50, goal="pad"))
    code = cli.main(["trial", str(folder), "--harness", "oracle", "--out", str(tmp_path / "runs"), "--record-size", "640x480"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0, result
    assert (result["reward"], result["verdict"], result["outcome"]) == (1.0, "pass", "done")
    assert result["trial_dir"].startswith(str(tmp_path / "runs"))
    assert result["video"].endswith("artifacts/recording.mp4")
    with imageio.get_reader(result["video"]) as video:
        assert video.get_meta_data()["size"] == (640, 480)
    assert result["metrics"]["success"] == 1


def test_a_weak_servo_drops_what_the_strong_one_carries(tmp_path) -> None:
    """The same 40 mm, 200 g cube: the MG996R carries it, a servo with an SG90's torque lets it slip out."""

    strong = trial.run(write_task(tmp_path / "tasks", example_hand(), Brief(200, 40), "mg996r"), "oracle", tmp_path / "runs")
    weak = trial.run(write_task(tmp_path / "tasks", _weaker(example_hand(), 1.8 / 9.4), Brief(200, 40), "sg90"), "oracle", tmp_path / "runs")
    assert (strong["verdict"], weak["verdict"]) == ("pass", "fail")
    assert weak["exception"] is None and weak["outcome"] == "done"


def test_no_op_scores_zero(tmp_path) -> None:
    result = trial.run(write_task(tmp_path / "tasks", example_hand(), Brief(200, 66)), "noop", tmp_path / "runs")
    assert (result["reward"], result["verdict"]) == (0.0, "fail")


def test_agent_harnesses_need_their_credentials(tmp_path, monkeypatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(trial, "_robouse", lambda *a, **k: pytest.fail("no trial may start without credentials"))
    assert "ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN" in (trial.missing_credentials("claude-code") or "")
    with pytest.raises(trial.TrialError, match="claude-code needs"):
        trial.run(tmp_path, "claude-code", tmp_path / "runs")
    assert trial.missing_credentials("oracle") is None
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "set")
    assert trial.missing_credentials("claude-code") is None


@pytest.mark.parametrize(
    ("brief", "message"),
    [
        ({"object_mass_g": 100, "object_width_mm": 74}, "opens 76.0 mm"),
        ({"object_mass_g": 10, "object_width_mm": 12}, "pads touch only the top 0 mm"),
        ({"object_mass_g": 100, "object_width_mm": 40, "goal": "shelf"}, "goal must be one of"),
        ({"object_mass_g": 0, "object_width_mm": 40}, "positive"),
        ({"object_width_mm": 40}, "object_mass_g and object_width_mm"),
    ],
)
def test_briefs_the_hand_cannot_grasp_are_refused(tmp_path, brief, message) -> None:
    with pytest.raises(TaskError, match=message):
        write_task(tmp_path, example_hand(), Brief.from_dict(brief))


def test_cli_writes_a_task_from_a_brief_file(tmp_path, capsys) -> None:
    brief = tmp_path / "brief.json"
    brief.write_text(json.dumps({"object_mass_g": 120, "object_width_mm": 45}))
    code = cli.main(["task", "--example", "--brief", str(brief), "--goal", "pad", "--out", str(tmp_path), "--no-check"])
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result["task_dir"].endswith("anybuild-gripper-cube-45mm-120g-on-pad")
    assert cli.main(["task", "--example", "--mass-g", "10", "--width-mm", "90", "--out", str(tmp_path)]) == 2
    assert "opens 76.0 mm" in capsys.readouterr().err
