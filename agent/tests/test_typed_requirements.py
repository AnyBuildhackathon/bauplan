"""Requirements come from what the user typed: their numbers, their words, and nothing attributed to them that they did not say."""

import asyncio
import tempfile
from pathlib import Path

from pai_agent.context import Ctx
from pai_agent.mock_story import limits_from_text
from pai_agent.requirements import attribute
from pai_agent.state import BuildState
from pai_agent.tools.registry import SCHEMAS, TOOLS, call_tool

FLY = "I want to build a drone that hunts flies under 150 euros"


class Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _ctx(*requests: str) -> Ctx:
    state = BuildState(session_id="t", directory=Path(tempfile.mkdtemp()))
    state.requests.extend(requests)
    return Ctx(Bus(), state, auto_steps=False)


def _rows(ctx: Ctx) -> dict:
    return {event["id"]: event for event in ctx.bus.events if event.get("type") == "requirement"}


def test_no_jamie_tool_is_left():
    names = set(TOOLS) | {schema["name"] for schema in SCHEMAS}
    assert not [name for name in names if "jamie" in name or name in {"version_commit", "requirements_accept"}]


def test_typed_budget_becomes_the_drone_budget():
    ctx = _ctx(FLY)
    args = {"product": "drone", "requirements": [{"id": "budget", "limit": 150, "quote": "under 150 euros"}]}
    result = asyncio.run(call_tool(ctx, "product_brief", args))
    assert result["ok"] is not False
    rows = _rows(ctx)
    assert rows["budget"]["text"] == "Total price under €150"
    assert rows["budget"]["source"] == "user" and rows["budget"]["speaker"] == "You"
    assert rows["budget"]["source_quote"] == "under 150 euros"
    # Nothing typed for these: they are Mechanic's proposals, not anyone's sentence.
    for rid in ("hover", "printable"):
        assert rows[rid]["source"] == "proposed" and rows[rid]["speaker"] == "Mechanic"
    assert "flight_time" not in rows and "weight" not in rows
    assert ctx.state.requirements[0]["max"] == 150


def test_a_quote_the_user_never_typed_is_shown_as_proposed():
    ctx = _ctx(FLY)
    args = {"product": "drone", "requirements": [{"id": "budget", "limit": 120, "quote": "The parts have to stay under 120 euro"}]}
    asyncio.run(call_tool(ctx, "product_brief", args))
    budget = _rows(ctx)["budget"]
    assert budget["source"] == "proposed" and budget["speaker"] == "Mechanic"


def test_proposed_limits_are_labelled_as_mechanic():
    ctx = _ctx(FLY)
    args = {
        "product": "drone",
        "requirements": [
            {"id": "budget", "limit": 150, "quote": "under 150 euros"},
            {"id": "weight", "limit": 60, "quote": "A fly hunter has to be a light indoor micro.", "proposed": True},
        ],
    }
    asyncio.run(call_tool(ctx, "product_brief", args))
    weight = _rows(ctx)["weight"]
    assert weight["source"] == "proposed" and weight["speaker"] == "Mechanic"
    assert weight["source_quote"] == "A fly hunter has to be a light indoor micro."


def test_attribute_matches_words_not_formatting():
    state = BuildState(session_id="t", directory=Path(tempfile.mkdtemp()), requests=["Make it fly  10 Minutes, please."])
    assert attribute(state, "fly 10 minutes", False)["source"] == "user"
    assert attribute(state, "fly 12 minutes", False)["source"] == "proposed"
    assert attribute(state, "fly 10 minutes", True)["source"] == "proposed"


def test_limits_from_text_reads_the_typed_numbers():
    assert limits_from_text(FLY) == [{"id": "budget", "limit": 150.0, "quote": "under 150 euros"}]
    found = {item["id"]: item for item in limits_from_text("A quad under 50 g for €90 that flies at least ten minutes")}
    assert found["budget"]["limit"] == 90 and found["weight"]["limit"] == 50 and found["flight_time"]["limit"] == 10
    assert limits_from_text("a phone stand for my desk") == []


def test_generic_spec_requirements_keep_the_users_words():
    ctx = _ctx("a phone stand for my desk under 20 euros")
    spec = {
        "name": "Phone stand",
        "function": "Holds a phone on a desk.",
        "quote": "a phone stand for my desk under 20 euros",
        "requirements": [
            {"text": "Costs under 20 €", "check": "cost", "max": 20, "unit": "eur", "quote": "under 20 euros"},
            {"text": "Weighs under 300 g", "check": "mass", "max": 300, "unit": "g", "quote": "A desk stand stays light enough to move.", "proposed": True},
        ],
        "parts": [
            {"name": "Base", "kind": "printed", "material": "PLA", "description": "Flat base plate 80 by 100 mm, 5 mm thick, on the desk.", "size_mm": [80, 100, 5], "position_mm": [0, 0, 2.5], "params": {"width_mm": 80}},
        ],
    }
    assert asyncio.run(call_tool(ctx, "product_spec", spec)).get("ok") is not False
    rows = {row["check"]: row for row in ctx.state.requirements}
    assert rows["cost"]["source"] == "user" and rows["cost"]["speaker"] == "You"
    assert rows["mass"]["source"] == "proposed" and rows["mass"]["speaker"] == "Mechanic"


def test_parts_search_matches_words_and_falls_back_to_the_category():
    ctx = _ctx(FLY)
    found = asyncio.run(call_tool(ctx, "parts_search", {"category": "motor", "query": "motor 1103 micro brushless"}))
    assert found["ok"] is not False and found["parts"][0]["id"] == "generic-1103-15000kv"
    nothing = asyncio.run(call_tool(ctx, "parts_search", {"category": "camera", "query": "thermal imager"}))
    assert nothing["ok"] is not False and nothing["parts"] and "whole category" in nothing["detail"]


def test_bill_of_materials_closes_its_step_in_live_runs():
    from pai_agent.tools.registry import _advance

    ctx = Ctx(Bus(), BuildState(session_id="t", directory=Path(tempfile.mkdtemp())), auto_steps=True)
    for name in ("bom_build", "print_prep"):
        asyncio.run(_advance(ctx, name, {}, started=True))
        asyncio.run(_advance(ctx, name, {"ok": True}, started=False))
    steps = [e for e in ctx.bus.events if e.get("type") == "step" and e["id"] == "stueckliste"]
    assert steps[-1]["status"] == "done"
