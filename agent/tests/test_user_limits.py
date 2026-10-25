"""A limit the user typed stays theirs: a timed-out question never loosens it, and an over-budget bill of materials is not the end of a build."""

import asyncio
import tempfile
from pathlib import Path

from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools.registry import call_tool

FLY = "Build a fly hunter drone, incredibly fast, small and light, under 100 euros."
PARTS = (
    ("motor", "betafpv-0802-22000kv"),
    ("propeller", "gemfan-1614-3"),
    ("battery", "betafpv-lava-1s-450"),
    ("flight_controller", "betafpv-matrix-1s-5in1-v2"),
    ("frame", "betafpv-air75-ii"),
    ("camera", "betafpv-c03"),
)


class Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class Asker:
    """Stands for Session.ask: answers with the default, by timeout or by the person."""

    def __init__(self, by_user: bool, pick: str | None = None):
        self.answered_by_user = by_user
        self.pick = pick

    async def ask(self, question: dict) -> str:
        return self.pick or question["default_id"]


def _ctx(asker: Asker | None = None) -> Ctx:
    state = BuildState(session_id="t", directory=Path(tempfile.mkdtemp()))
    state.requests.append(FLY)
    return Ctx(Bus(), state, auto_steps=False, asker=asker.ask if asker else None)


def _run(ctx: Ctx, name: str, args: dict) -> dict:
    return asyncio.run(call_tool(ctx, name, args))


def _budget(ctx: Ctx) -> dict:
    return next(r for r in ctx.state.requirements if r["id"] == "budget")


def _brief(ctx: Ctx, limit: float, quote: str, proposed: bool = False) -> dict:
    return _run(ctx, "product_brief", {"product": "drone", "requirements": [{"id": "budget", "limit": limit, "quote": quote, "proposed": proposed}]})


def _built(ctx: Ctx) -> None:
    assert _brief(ctx, 100, "under 100 euros")["ok"]
    for category, part_id in PARTS:
        assert _run(ctx, "parts_search", {"category": category, "select_id": part_id})["ok"]


ASK = {
    "question": "Under 100 € does not fit. Keep trying, or accept 106 €?",
    "options": [{"id": "accept", "label": "Accept 106 € with this cheaper build"}, {"id": "keep", "label": "Keep trying for under 100 €"}],
    "default_id": "accept",
}


def test_typed_budget_is_the_users_with_their_limit():
    ctx = _ctx()
    _built(ctx)
    row = _budget(ctx)
    assert row["max"] == 100 and row["source"] == "user" and row["speaker"] == "You"


def test_a_timed_out_question_does_not_loosen_the_typed_budget():
    ctx = _ctx(Asker(by_user=False))
    _built(ctx)
    answer = _run(ctx, "ask_user", ASK)
    assert answer["by_user"] is False and "not the user's consent" in answer["note"]
    refused = _brief(ctx, 106, "Accept 106 € with this cheaper build", proposed=True)
    assert refused["ok"] is False and "timed out on its default is not consent" in refused["error"]
    row = _budget(ctx)
    assert row["max"] == 100 and row["source"] == "user"


def test_a_revision_never_relabels_the_users_budget_as_proposed():
    ctx = _ctx()
    _built(ctx)
    assert _brief(ctx, 100, "Mechanic keeps the budget", proposed=True)["ok"]
    row = _budget(ctx)
    assert row["source"] == "user" and row["source_quote"] == "under 100 euros"


def test_the_users_own_answer_may_loosen_it_and_it_stays_theirs():
    ctx = _ctx(Asker(by_user=True, pick="accept"))
    _built(ctx)
    answer = _run(ctx, "ask_user", ASK)
    assert answer["by_user"] is True
    assert _brief(ctx, 106, "Accept 106 € with this cheaper build", proposed=True)["ok"]
    row = _budget(ctx)
    assert row["max"] == 106 and row["source"] == "user" and "106" in row["source_quote"]
    # The consent is used up: a second loosening needs a new answer.
    assert _brief(ctx, 120, "more", proposed=True)["ok"] is False


def test_a_newly_typed_limit_needs_no_question():
    ctx = _ctx()
    _built(ctx)
    ctx.state.requests.append("Fine, make it under 130 euros.")
    assert _brief(ctx, 130, "under 130 euros")["ok"]
    assert _budget(ctx)["max"] == 130 and _budget(ctx)["source"] == "user"


def test_over_budget_bill_of_materials_says_not_to_finish(monkeypatch):
    monkeypatch.setattr("pai_agent.tools.bom.live_prices_enabled", lambda: False)
    ctx = _ctx()
    _built(ctx)
    assert _run(ctx, "physics_calc", {})["ok"]
    result = _run(ctx, "bom_build", {})
    assert result["ok"] is True
    assert result["over_budget"]["limit_eur"] == 100 and result["over_budget"]["total_eur"] > 100
    assert "Do not finish here" in result["next"]
    assert _budget(ctx)["_met"] is False


def test_a_build_inside_the_budget_gets_no_warning(monkeypatch):
    monkeypatch.setattr("pai_agent.tools.bom.live_prices_enabled", lambda: False)
    ctx = _ctx()
    ctx.state.requests.append("under 200 euros")
    assert _brief(ctx, 200, "under 200 euros")["ok"]
    for category, part_id in PARTS:
        _run(ctx, "parts_search", {"category": category, "select_id": part_id})
    _run(ctx, "physics_calc", {})
    result = _run(ctx, "bom_build", {})
    assert "over_budget" not in result
