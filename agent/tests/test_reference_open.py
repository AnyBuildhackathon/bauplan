"""Opening a library reference: live key runs the orchestrator, no key plays the saved build."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pai_agent.orchestrator import run_reference
from pai_agent.references import reference_brief
from pai_agent.tools.reference import reference_load


class _Ctx:
    def __init__(self) -> None:
        self.state = SimpleNamespace(started=False)
        self.lines: list[tuple[str, str]] = []

    async def step(self, *_args) -> None:
        return None

    async def chat(self, role: str, text: str, voice: bool = False) -> None:
        self.lines.append((role, text))


def test_drone_brief_names_the_catalog_parts() -> None:
    visible, model = reference_brief("micro-drone")
    assert visible.startswith("Rebuild ")
    assert "1103" in model
    assert "FunFly" in model
    assert "reference_load" in model


def test_registry_brief_uses_the_stored_request() -> None:
    visible, model = reference_brief("desk-fan")
    assert "USB desk fan" in visible
    assert "300 g" in model
    assert "Base" in model


def test_live_rebuild_calls_the_orchestrator(monkeypatch) -> None:
    seen: dict = {}

    async def claude(_ctx, text, messages) -> None:
        seen["text"] = text
        seen["messages"] = messages

    async def saved(*_args, **_kwargs):
        raise AssertionError("the saved story must not run when a live key is present")

    monkeypatch.setattr("pai_agent.orchestrator.claude_enabled", lambda: True)
    monkeypatch.setattr("pai_agent.orchestrator._run_claude", claude)
    monkeypatch.setattr("pai_agent.references.build_reference", saved)
    messages: list[dict] = []
    ctx = _Ctx()
    asyncio.run(run_reference(ctx, "micro-drone", messages))
    assert seen["messages"] is messages
    assert "1103" in seen["text"]
    assert any(role == "user" and text.startswith("Rebuild ") for role, text in ctx.lines)
    assert not any("Offline" in text for _role, text in ctx.lines)


def test_offline_rebuild_plays_the_saved_story(monkeypatch) -> None:
    seen: dict = {}

    async def saved(_ctx, ref_id):
        seen["id"] = ref_id
        return {"name": "Micro", "product_mass_g": 47, "cost_eur": 1, "requirements_passed": 1, "requirements": 1}

    async def claude(*_args):
        raise AssertionError("the live model must not run offline")

    async def on_bench(_ctx, result) -> None:
        seen["result"] = result

    monkeypatch.setattr("pai_agent.orchestrator.claude_enabled", lambda: False)
    monkeypatch.setattr("pai_agent.orchestrator._run_claude", claude)
    monkeypatch.setattr("pai_agent.orchestrator._on_bench", on_bench)
    monkeypatch.setattr("pai_agent.references.build_reference", saved)
    ctx = _Ctx()
    asyncio.run(run_reference(ctx, "micro-drone"))
    assert seen["id"] == "micro-drone"
    assert seen["result"]["name"] == "Micro"
    assert any("Offline" in text for _role, text in ctx.lines)


def test_live_reference_load_does_not_replay(monkeypatch) -> None:
    async def saved(*_args, **_kwargs):
        raise AssertionError("reference_load must not replay the saved story while a live key is present")

    monkeypatch.setattr("pai_agent.tools.reference.claude_enabled", lambda: True)
    monkeypatch.setattr("pai_agent.tools.reference.build_reference", saved)
    result = asyncio.run(reference_load(_Ctx(), {"id": "micro-drone"}))
    assert result["ok"] is True
    assert "1103" in result["request"]
    assert result["detail"].startswith("Rebuild ")
