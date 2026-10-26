"""SolidCraft for parts that move on joints, and their robot description in MuJoCo.

Offline, without solidcraft-cli: FreeCAD stays the default CAD engine and Claude sees SolidCraft's tools only with
PAI_CAD_ENGINE=solidcraft; a script may only model, assemble, move and measure; parameters take new values in their
own unit; without the CLI both tools say how to install it. SolidCraft's recorded URDF exports of a four-bar (a loop
closed by a hinge) and of an actuated panel (a loop closed by the actuator's slider, a mirrored panel on a motion
link, built at 20 degrees) become MJCF in which every joint follows SolidCraft's own motion study, the loops stay
closed and every part has the mass SolidCraft measured; without the loop's equality the rocker stays behind.

With solidcraft-cli 0.23.0 installed (bash agent/scripts/setup_solidcraft.sh) the acceptance runs for real: the
four-bar from SolidCraft's examples and the two-finger gripper build, export and run in MuJoCo with all their
joints, the loop closed and the masses within 1 % of measure, and a slider rebuilds through SolidCraft's timeline.
No network, no key.
"""

from __future__ import annotations

import asyncio
import copy
import json
import stat
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from pai_agent import orchestrator, solidcraft, solidcraft_mjcf
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.mock_solidcraft import wants_solidcraft
from pai_agent.session import Session
from pai_agent.state import BuildState
from pai_agent.tools import solidcraft_part as tool
from pai_agent.tools.registry import call_tool

FIXTURES = Path(__file__).parent / "fixtures" / "solidcraft"
INSTALLED = solidcraft.missing() is None
needs_cli = pytest.mark.skipif(not INSTALLED, reason="solidcraft-cli " + solidcraft.VERSION + " is not installed (bash agent/scripts/setup_solidcraft.sh)")


@pytest.fixture(autouse=True)
def _engine(monkeypatch):
    monkeypatch.delenv("PAI_CAD_ENGINE", raising=False)


def _bench(tmp_path: Path) -> Ctx:
    return Ctx(EventBus(), BuildState(session_id="t", directory=tmp_path), auto_steps=False)


def _robot(name: str, tmp_path: Path, change=None) -> solidcraft.Robot:
    """A recorded export as SolidCraft returned it, its URDF written next to the MJCF to come."""

    fixture = json.loads((FIXTURES / (name + ".json")).read_text(encoding="utf-8"))
    if change:
        change(fixture)
    urdf = tmp_path / (name + ".urdf")
    urdf.write_text(fixture["urdf"], encoding="utf-8")
    return solidcraft.Robot(
        urdf=urdf,
        meshes=[],
        joints=fixture["joints"],
        components=fixture["components"],
        properties=fixture["properties"],
        measure=fixture["measure"],
        study=fixture["study"],
        motion=fixture["motion"],
        warnings=fixture["warnings"],
    )


def _mujoco(robot: solidcraft.Robot, tmp_path: Path) -> tuple[dict, dict]:
    mjcf = tmp_path / "robot.mjcf.xml"
    converted = solidcraft_mjcf.mjcf_from_urdf(robot, mjcf)
    return converted, solidcraft_mjcf.check_mjcf(robot, mjcf, converted)


# --- The engine switch -------------------------------------------------------------------------------------------


def test_freecad_stays_the_cad_engine_unless_solidcraft_is_chosen(monkeypatch):
    assert solidcraft.engine() == "freecad"
    monkeypatch.setenv("PAI_CAD_ENGINE", "SolidCraft")
    assert solidcraft.engine() == "solidcraft"
    monkeypatch.setenv("PAI_CAD_ENGINE", "onshape")
    assert solidcraft.engine() == "freecad"


def test_claude_sees_solidcraft_tools_only_with_the_engine(monkeypatch):
    for delegation in (True, False):
        names = {schema["name"] for schema in orchestrator._tools(delegation)}
        assert not names & {"solidcraft_part", "export_urdf"}
        assert "cad_part" in names
    assert "SolidCraft" not in orchestrator._system(True)[0]["text"]
    monkeypatch.setenv("PAI_CAD_ENGINE", "solidcraft")
    for delegation in (True, False):
        names = {schema["name"] for schema in orchestrator._tools(delegation)}
        assert {"solidcraft_part", "export_urdf", "cad_part"} <= names
    assert "solidcraft_part" in orchestrator._system(False)[0]["text"]


def test_offline_requests_reach_solidcraft_only_with_the_engine(monkeypatch):
    assert not wants_solidcraft("Build a four-bar linkage")
    monkeypatch.setenv("PAI_CAD_ENGINE", "solidcraft")
    assert wants_solidcraft("Build a four-bar linkage")
    assert wants_solidcraft("Design a two-finger gripper in SolidCraft")
    # A gripper without SolidCraft's name stays the FreeCAD gripper flow.
    assert not wants_solidcraft("Design a robot gripper for a 40 g part")


# --- Scripts and parameters ----------------------------------------------------------------------------------------


def test_a_design_may_only_model_assemble_move_and_measure():
    for name in ("chebyshev-motion-trace.json", "two-finger-gripper.json"):
        commands = solidcraft.check_script((solidcraft.LIBRARY_DIR / name).read_text(encoding="utf-8"))
        assert commands and all(row["command"] for row in commands)
    refused = {
        "a file export": {"commands": [{"command": "file.export", "params": {"path": "/tmp/x.stl"}}]},
        "opening a file": {"commands": [{"command": "doc.open", "params": {"path": "/etc/hosts"}}]},
        "a render": {"commands": [{"command": "render.start", "params": {}}]},
        "a DXF read in a sketch": {"commands": [{"command": "sketch.insert_dxf", "params": {"path": "/tmp/a.dxf"}}]},
        "a path deep in the params": {"commands": [{"command": "motion.export", "params": {"study": "s", "options": [{"path": "/tmp/m.csv"}]}}]},
        "params that are not an object": {"commands": [{"command": "solid.box", "params": [1, 2, 3]}]},
        "no commands": {"commands": []},
        "broken JSON": '{"commands": [',
    }
    for why, script in refused.items():
        with pytest.raises(solidcraft.ScriptRejected):
            solidcraft.check_script(script)
            pytest.fail(why + " was let through")


def test_parameters_take_new_values_in_their_own_unit():
    commands = solidcraft.check_script(
        {
            "commands": [
                {"command": "parameters.add", "params": {"name": "width", "expression": "60 mm"}},
                {"command": "parameters.add", "params": {"name": "sweep", "expression": "360 deg"}},
                {"command": "parameters.add", "params": {"name": "count", "expression": "4"}},
                {"command": "parameters.change", "params": {"name": "width", "expression": "70 mm"}},
                {"command": "solid.box", "params": {"length": "width", "width": 10, "height": 10}},
            ]
        }
    )
    changed = solidcraft.with_params(commands, {"width": 85, "sweep": 180, "count": 6})
    # The script stays as written and one change follows it, as moving the parameters in SolidCraft does.
    assert changed[:-1] == commands
    assert changed[-1] == {"command": "parameters.change", "params": {"changes": {"width": "85 mm", "sweep": "180 deg", "count": "6"}}}
    assert solidcraft.with_params(commands, {}) == commands
    with pytest.raises(ValueError, match="height is not a parameter the script sets: it sets count, sweep, width"):
        solidcraft.with_params(commands, {"height": 5})


# --- Without solidcraft-cli -------------------------------------------------------------------------------------------


def test_without_solidcraft_cli_both_tools_say_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLIDCRAFT_CLI", str(tmp_path / "solidcraft-cli"))
    assert solidcraft.cli() is None
    assert "not an executable file" in solidcraft.missing()
    ctx = _bench(tmp_path)
    part = asyncio.run(call_tool(ctx, "solidcraft_part", {"name": "Linkage", "template": "four_bar"}))
    assert part["ok"] is False
    assert "setup_solidcraft.sh" in part["error"]
    assert asyncio.run(call_tool(ctx, "export_urdf", {}))["error"].startswith("No SolidCraft design yet")
    ctx.state.solidcraft = {"name": "Linkage"}
    robot = asyncio.run(call_tool(ctx, "export_urdf", {}))
    assert robot["ok"] is False and "setup_solidcraft.sh" in robot["error"]


def test_a_solidcraft_cli_of_another_version_is_not_used(tmp_path, monkeypatch):
    fake = tmp_path / "solidcraft-cli"
    fake.write_text("#!/bin/sh\necho 'solidcraft-cli 0.22.1'\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("SOLIDCRAFT_CLI", str(fake))
    assert solidcraft.cli() is None
    assert "version 0.22.1" in solidcraft.missing() and solidcraft.VERSION in solidcraft.missing()


def test_the_cad_agent_works_from_solidcraft_skills():
    text = tool._system()[0]["text"]
    for skill in ("solidcraft-modeling", "solidcraft-mechanisms"):
        skill_md = (solidcraft.SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
        assert skill_md.startswith("---\nname: " + skill + "\n")
        assert skill_md in text
        assert (solidcraft.SKILLS_DIR / skill / "reference.md").read_text(encoding="utf-8") in text
    assert "Copyright (c) 2026 SolidCraft contributors" in (solidcraft.SOLIDCRAFT_DIR / "LICENSE-SolidCraft").read_text(encoding="utf-8")
    assert "motion.study" in text and "no file" in text


# --- SolidCraft's URDF in MuJoCo, from recorded exports ---------------------------------------------------------------


def test_a_loop_closed_by_a_hinge_runs_in_mujoco_with_all_joints(tmp_path):
    robot = _robot("four-bar", tmp_path)
    converted, report = _mujoco(robot, tmp_path)
    # The URDF is a tree without the hinge that closes the loop; MuJoCo has it back.
    assert "Coupler_to_rocker" not in converted["urdf_joints"]
    assert sorted(converted["joints"]) == ["Coupler_to_rocker", "Crank_drive", "Crank_to_coupler", "Rocker_pivot"]
    assert converted["loops_closed"] == [{"joint": "Coupler to rocker", "type": "revolute", "parts": ["Coupler", "Rocker"]}]
    root = ET.parse(tmp_path / "robot.mjcf.xml").getroot()
    assert root.find("equality/weld").get("body2") == "loop_Coupler_to_rocker"
    assert report["passed"], report
    assert report["drivers"] == ["Crank_drive"] and report["samples"] == 13
    travel = {row["joint"]: row for row in report["travel"]}
    assert travel["Crank_drive"]["travel"] == pytest.approx(360.0, abs=0.01)
    assert all(row["moved"] for row in report["travel"])
    assert report["deviation_mm"] < 0.001 and report["loop_gap_mm"] < 0.001
    assert report["mass_error_pct"] < 1.0 and report["total_mass_g"]["error_pct"] < 1.0


def test_a_loop_closed_by_a_slider_and_a_mirrored_panel_run_in_mujoco(tmp_path):
    robot = _robot("actuator-panel", tmp_path)
    converted, report = _mujoco(robot, tmp_path)
    assert converted["loops_closed"] == [{"joint": "Stroke", "type": "slider", "parts": ["Actuator_barrel", "Actuator_rod"]}]
    assert converted["couplings"] == [{"link": "Hinge drives Hinge 2", "ratio": -1.0, "unit": "deg per deg"}]
    joints = {element.get("name"): element for element in ET.parse(tmp_path / "robot.mjcf.xml").getroot().iter("joint") if element.get("name")}
    # The actuator's stroke is a MuJoCo slide with its limits, and every joint starts where the design was built.
    assert joints["Stroke"].get("type") == "slide"
    assert [float(v) for v in joints["Stroke"].get("range").split()] == pytest.approx([-0.005, 0.01])
    assert float(joints["Stroke"].get("ref")) == pytest.approx(0.0076268, abs=1e-6)
    assert float(joints["Hinge"].get("ref")) == pytest.approx(0.3490659, abs=1e-6)
    assert report["passed"], report
    assert report["checks"]["as_built"] and report["com_error_mm"] < 0.01
    travel = {row["joint"]: row for row in report["travel"]}
    assert travel["Hinge"]["travel"] == pytest.approx(25.0, abs=0.01)
    assert travel["Hinge_2"]["travel"] == pytest.approx(25.0, abs=0.01)
    assert travel["Stroke"]["unit"] == "mm" and travel["Stroke"]["travel"] > 5.0
    assert report["coupling_error"] < 1e-5


def test_without_its_loop_the_rocker_stays_behind(tmp_path):
    robot = _robot("four-bar", tmp_path)
    mjcf = tmp_path / "robot.mjcf.xml"
    converted = solidcraft_mjcf.mjcf_from_urdf(robot, mjcf)
    root = ET.parse(mjcf).getroot()
    root.remove(root.find("equality"))
    mjcf.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
    report = solidcraft_mjcf.check_mjcf(robot, mjcf, converted)
    assert not report["checks"]["follows_study"]
    assert report["deviation_mm"] > 1.0
    assert not {row["joint"]: row for row in report["travel"]}["Rocker_pivot"]["moved"]


def test_a_wrong_mass_or_no_motion_study_fails_the_check(tmp_path):
    def heavier(fixture):
        body = next(row for row in fixture["properties"]["bodies"] if row["name"] == "Rocker bar")
        body["mass_g"] *= 1.05

    report = _mujoco(_robot("four-bar", tmp_path, heavier), tmp_path)[1]
    assert not report["checks"]["mass_within_1pct"] and report["mass_error_pct"] > 1.0
    assert report["checks"]["follows_study"]

    def unstudied(fixture):
        fixture["study"], fixture["motion"] = None, None

    report = _mujoco(_robot("four-bar", tmp_path, unstudied), tmp_path)[1]
    assert not report["checks"]["follows_study"] and report["samples"] == 0
    assert report["checks"]["loops_closed"] and report["checks"]["as_built"]


def test_a_slider_of_a_solidcraft_design_rebuilds_it(monkeypatch):
    session = Session()
    session.state.cad_builds = 3
    session.state.solidcraft = {"name": "Two-finger gripper", "cad_build": 3, "files": {"step": "solidcraft-two-finger-gripper.step"}}
    calls = []

    async def rebuild(ctx, changes):
        calls.append(changes)
        return {"ok": True, "detail": "SolidCraft 0.23.0, 34.0 g PLA"}

    monkeypatch.setattr(tool, "rebuild_solidcraft", rebuild)
    assert asyncio.run(session.update_params({"name": "jaw_opening", "value": 60}))["ok"]
    assert calls == [{"jaw_opening": 60}]
    # A newer CAD build takes the sliders back.
    session.state.cad_builds = 4
    assert not tool.is_current(session.state)


# --- With solidcraft-cli: the acceptance ------------------------------------------------------------------------------


def _build_and_export(tmp_path: Path, template: str) -> tuple[Ctx, dict, dict]:
    ctx = _bench(tmp_path)
    part = asyncio.run(call_tool(ctx, "solidcraft_part", {"name": "", "template": template}))
    robot = asyncio.run(call_tool(ctx, "export_urdf", {}))
    return ctx, part, robot


@needs_cli
def test_the_four_bar_from_the_example_runs_in_mujoco_with_all_joints(tmp_path):
    ctx, part, robot = _build_and_export(tmp_path, "four_bar")
    assert part["ok"] and part["source"] == "solidcraft"
    assert [row["name"] for row in part["parts"]] == ["Ground", "Crank", "Coupler", "Rocker"]
    assert len(part["joints"]) == 4 and part["motion_studies"][0]["name"] == "Chebyshev cycle"
    assert part[tool.IMAGE].startswith("iVBORw0KGgo")
    stem = ctx.state.solidcraft["stem"]
    for suffix in (".step", ".stl", ".glb", ".solidcraft", ".json", ".png"):
        assert (tmp_path / (stem + suffix)).is_file(), suffix
    cad = next(ev for ev in ctx.bus.events if ev.get("type") == "cad")
    assert cad["source"] == "solidcraft" and cad["design_url"].endswith(".solidcraft?build=1")
    assert "unit_length" in cad["params"]
    assert robot["ok"] and robot["result"] == "pass", robot["detail"]
    assert all(robot["checks"].values())
    joints = {row["name"]: row for row in robot["joints"]}
    assert all(row["in_mujoco"] for row in joints.values())
    assert joints["Coupler to rocker"] == {**joints["Coupler to rocker"], "in_urdf": False, "closes_loop": True}
    assert robot["loop_gap_mm"] < 0.01 and robot["deviation_mm"] < 0.1
    assert all(row["error_pct"] < 1.0 for row in robot["masses"])
    for url in [robot["files"]["urdf"], robot["files"]["mjcf"], *robot["files"]["meshes"]]:
        assert (tmp_path / url.rsplit("/", 1)[1]).is_file()
    # A longer unit length scales the whole linkage through SolidCraft's timeline; the picked pins follow.
    longer = asyncio.run(tool.rebuild_solidcraft(ctx, {"unit_length": 28}))
    assert longer["ok"], longer.get("error")
    assert longer["bbox_mm"][3] == pytest.approx(114.0, abs=0.01) and longer["mass_g"] > part["mass_g"]
    assert asyncio.run(call_tool(ctx, "export_urdf", {}))["result"] == "pass"


@needs_cli
def test_the_two_finger_gripper_runs_in_mujoco_with_its_gears(tmp_path):
    ctx, part, robot = _build_and_export(tmp_path, "two_finger_gripper")
    assert part["ok"] and part["motion_links"] == [{"drives": "Finger L pivot", "follows": "Finger R pivot", "ratio": -1.0, "coupling": "gear"}]
    assert robot["result"] == "pass", robot["detail"]
    assert robot["couplings"] == [{"link": "Finger L pivot drives Finger R pivot", "ratio": -1.0, "unit": "deg per deg"}]
    assert {row["name"]: row["travel"]["value"] for row in robot["joints"]} == {"Finger L pivot": 50.0, "Finger R pivot": 50.0}
    assert all(row["error_pct"] < 1.0 for row in robot["masses"])
    # A servo's limits go into the URDF; a limit that is not positive is refused.
    limited = asyncio.run(call_tool(ctx, "export_urdf", {"effort": 0.25, "velocity": 5.2}))
    urdf = (tmp_path / limited["files"]["urdf"].rsplit("/", 1)[1]).read_text(encoding="utf-8")
    assert 'effort="0.25" velocity="5.2"' in urdf and not any("effort and velocity" in w for w in limited["warnings"])
    assert asyncio.run(call_tool(ctx, "export_urdf", {"effort": -1}))["ok"] is False


@needs_cli
def test_a_slider_rebuilds_the_gripper_through_its_timeline(tmp_path):
    ctx, part, _robot_result = _build_and_export(tmp_path, "two_finger_gripper")
    wider = asyncio.run(tool.rebuild_solidcraft(ctx, {"jaw_opening": 60}))
    assert wider["ok"] and wider["mass_g"] > part["mass_g"]
    assert ctx.state.solidcraft["params"] == {"jaw_opening": 60.0}
    assert wider["sliders"]["jaw_opening"]["value"] == 60.0
    assert '"jaw_opening": "60 mm"' in (tmp_path / (ctx.state.solidcraft["stem"] + ".json")).read_text(encoding="utf-8")
    robot = asyncio.run(call_tool(ctx, "export_urdf", {}))
    assert robot["result"] == "pass", robot["detail"]
    with pytest.raises(ValueError):
        asyncio.run(tool.rebuild_solidcraft(ctx, {"jaw_opening": 500}))


@needs_cli
def test_the_cad_agent_writes_a_script_and_fixes_it_from_solidcraft_error(tmp_path, monkeypatch):
    good = tool.library_script("two_finger_gripper")
    broken = copy.deepcopy(good)
    broken["commands"].insert(13, {"command": "solid.fillet", "params": {"edges": [[400, 400, 400]], "radius": 2}})
    calls = []

    def write(model, effort, **kwargs):
        calls.append({"prompt": kwargs["messages"][0]["content"], "system": kwargs["system"][0]["text"]})
        script = broken if len(calls) == 1 else good
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="```json\n" + json.dumps(script) + "\n```")])

    monkeypatch.setattr("pai_agent.agents.create_message", write)
    monkeypatch.setattr(tool, "claude_enabled", lambda: True)
    ctx = _bench(tmp_path)
    args = {"name": "Gripper", "description": "Two fingers on meshing gears, closed by one servo", "params": {"jaw_opening": 55}}
    result = asyncio.run(call_tool(ctx, "solidcraft_part", args))
    assert result["ok"], result.get("error")
    assert [row["ok"] for row in result["attempts"]] == [False, True]
    assert '"jaw_opening": 55' in calls[0]["prompt"] and "solidcraft-mechanisms" in calls[0]["system"]
    assert "Your last script failed in SolidCraft" in calls[1]["prompt"] and "step 14 (solid.fillet)" in calls[1]["prompt"]
    assert ctx.state.solidcraft["generated"] and ctx.state.solidcraft["params"] == {"jaw_opening": 55.0}
    cad = next(ev for ev in ctx.bus.events if ev.get("type") == "cad")
    assert cad["part"]["generated"] and cad["part"]["attempts"] == 2
    assert [ev["status"] for ev in ctx.bus.events if ev.get("type") == "agent"][-1] == "done"


@needs_cli
def test_a_template_parameter_with_a_wrong_name_is_refused_at_once(tmp_path):
    result = asyncio.run(call_tool(_bench(tmp_path), "solidcraft_part", {"name": "Gripper", "template": "two_finger_gripper", "params": {"jaw_width": 60}}))
    assert result["ok"] is False and "jaw_width is not a parameter the script sets: it sets" in result["error"]
    assert "jaw_opening" in result["error"]


@needs_cli
def test_solidcraft_errors_come_back_with_their_step(tmp_path):
    script = copy.deepcopy(json.loads((solidcraft.LIBRARY_DIR / "two-finger-gripper.json").read_text(encoding="utf-8")))
    script["commands"].insert(13, {"command": "solid.fillet", "params": {"edges": [[400, 400, 400]], "radius": 2}})
    result = asyncio.run(call_tool(_bench(tmp_path), "solidcraft_part", {"name": "Broken gripper", "script": script}))
    assert result["ok"] is False
    assert "step 14 (solid.fillet)" in result["error"] and len(result["attempts"]) == 1


def test_the_explode_view_gets_each_joints_axis_place_and_the_parts_on_either_side():
    fixture = json.loads((FIXTURES / "actuator-panel.json").read_text(encoding="utf-8"))
    rows = {row["name"]: row for row in tool.explode_joints(fixture["components"], fixture["joints"]["joints"])}
    hinge = rows["Hinge"]
    assert hinge["axis"] == [1.0, 0.0, 0.0] and hinge["at_mm"] == [0.0, 0.0, 0.0]
    assert hinge["moving"] == {"part": "Wing", "bodies": ["Panel"]} and hinge["fixed"] == {"part": "Frame", "bodies": ["Post", "Base"]}
    # The rod slides out of its barrel along the stroke's own axis.
    assert rows["Stroke"]["axis"] == pytest.approx([0.0, 0.489196, 0.872174]) and rows["Stroke"]["fixed"]["part"] == "Actuator barrel"

