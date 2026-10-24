import asyncio
from pathlib import Path

from pai_agent.app_control import match_commands
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools.registry import call_tool


def _state(tmp_path: Path) -> BuildState:
    return BuildState(session_id="t", directory=tmp_path)


def test_dashboard_commands_match(tmp_path):
    state = _state(tmp_path)
    assert match_commands("show me the CAD", state) == [{"control": "tab:cad"}]
    assert match_commands("pull it apart", state) == [{"control": "explode", "value": 100}]
    assert match_commands("put it back together", state) == [{"control": "explode", "value": 0}]
    assert match_commands("compare v1 and v2", state) == [{"control": "panel:compare", "versions": [1, 2]}]
    assert match_commands("close the comparison", state) == [{"control": "panel:compare", "open": False}]
    assert match_commands("open the library", state) == [{"control": "view:library"}]
    assert match_commands("open the phone stand in the library", state) == [{"control": "library:phone-stand"}]
    assert match_commands("focus on the battery", state) == [{"control": "focus", "part": "battery"}]
    assert match_commands("turn on tool details", state) == [{"control": "setting:tools", "value": True}]
    assert match_commands("open the bill of materials and the build guide", state) == [{"control": "panel:guide", "open": True}]


def test_design_requests_go_to_the_orchestrator(tmp_path):
    state = _state(tmp_path)
    for text in (
        "make the CAD arm longer",
        "Build a phone stand that holds a phone",
        "stress test the drone",
        "test it in omniverse with gusty wind",
        "the review is done",
        "Load the phone stand reference and then pull it apart",
        "Why this battery? Show me the bill of materials",
        "make it lighter",
    ):
        assert match_commands(text, state) == [], text


def test_ui_control_emits_and_checks(tmp_path):
    bus = EventBus()
    ctx = Ctx(bus, _state(tmp_path), auto_steps=False)

    async def run():
        ok = await call_tool(ctx, "ui_control", {"control": "explode", "value": 60})
        no_bom = await call_tool(ctx, "ui_control", {"control": "panel:bom"})
        unknown = await call_tool(ctx, "ui_control", {"control": "tab:nowhere"})
        return ok, no_bom, unknown

    ok, no_bom, unknown = asyncio.run(run())
    assert ok["ok"] is True
    assert no_bom["ok"] is False and "bill of materials" in no_bom["error"]
    assert unknown["ok"] is False
    events = [e for e in bus.events if e.get("type") == "ui"]
    assert len(events) == 1
    assert events[0]["control"] == "explode" and events[0]["value"] == 60 and events[0]["say"]
