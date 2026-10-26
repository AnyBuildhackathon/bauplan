"""A CAD slider rebuild ends the tool cards its progress lines opened, with the rebuild's result."""

import asyncio
from unittest.mock import patch

from pai_agent.session import Session


def _slider_session() -> Session:
    session = Session()
    # The newest CAD build is a generated part, so the slider rebuilds it (Session._part_is_current).
    session.state.part = {"name": "Robot gripper", "params": {"finger_length_mm": 70.0}}
    session.state.stl_path = "agent/runs/sessions/test/part-robot-gripper.stl"
    return session


def _tools(session: Session) -> list[dict]:
    return [ev for ev in session.bus.events if ev.get("type") == "tool"]


def test_a_slider_rebuild_closes_the_freecad_card_it_opened():
    session = _slider_session()

    async def rebuild(ctx, changes):
        await ctx.emit({"type": "tool", "name": "cad_part", "status": "running", "detail": "freecadcmd builds Robot gripper"})
        return {"ok": True, "detail": "FreeCAD headless, 60.0 g PLA"}

    with patch("pai_agent.tools.cad_part.rebuild_part", rebuild):
        result = asyncio.run(session.update_params({"finger_length_mm": 85}))
    assert result["ok"]
    assert [(ev["name"], ev["status"]) for ev in _tools(session)] == [("cad_part", "running"), ("cad_part", "ok")]
    assert _tools(session)[-1]["detail"] == "FreeCAD headless, 60.0 g PLA"


def test_a_failed_rebuild_ends_its_card_as_an_error():
    session = _slider_session()

    async def rebuild(ctx, changes):
        await ctx.emit({"type": "tool", "name": "cad_part", "status": "running", "detail": "freecadcmd builds Robot gripper"})
        return {"ok": False, "error": "FreeCAD stopped"}

    with patch("pai_agent.tools.cad_part.rebuild_part", rebuild):
        asyncio.run(session.update_params({"finger_length_mm": 85}))
    assert [(ev["status"], ev["detail"]) for ev in _tools(session)][-1] == ("error", "FreeCAD stopped")


def test_a_rebuild_without_progress_adds_no_card():
    session = _slider_session()

    async def rebuild(ctx, changes):
        return {"ok": True, "detail": "reused the identical FreeCAD build"}

    with patch("pai_agent.tools.cad_part.rebuild_part", rebuild):
        asyncio.run(session.update_params({"finger_length_mm": 85}))
    assert _tools(session) == []
