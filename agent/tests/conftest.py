"""Tests save no chats, so test runs never show in the app's chat history; `history` tests opt in."""

from __future__ import annotations

import pytest


def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "history: the test saves chats, into a temporary sessions directory")


@pytest.fixture(autouse=True)
def _provider(monkeypatch):
    """Tests run on the API provider: without a key that is the mock, never this machine's Claude subscription."""

    from pai_agent import provider

    monkeypatch.setenv("PAI_LLM_PROVIDER", "api")
    provider.reset_choice()
    yield
    provider.reset_choice()


@pytest.fixture(autouse=True)
def _parts_offline(tmp_path, monkeypatch):
    """Learned parts, distributor caches and exchange rates stay in the test's directory; no distributor
    credentials from agent/.env, no network for the ECB file (its built-in rates of 2026-10-23 apply)."""

    from pai_agent import currency, distributors, learned_parts, settings

    monkeypatch.setattr(settings, "_overrides", {})
    monkeypatch.setenv("PAI_LEARNED_PARTS", str(tmp_path / "learned" / "parts.json"))
    monkeypatch.setenv("PAI_ALLOW_ESTIMATED", "0")
    for name in ("DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET", "NEXAR_CLIENT_ID", "NEXAR_CLIENT_SECRET", "MOUSER_API_KEY"):
        monkeypatch.setenv(name, "")
    monkeypatch.setattr(distributors, "CACHE_DIR", tmp_path / "distributors")
    monkeypatch.setattr(currency, "CACHE_PATH", tmp_path / "ecb_rates.json")

    def offline():
        raise OSError("tests do not fetch the ECB file")

    monkeypatch.setattr(currency, "_fetch", offline)
    learned_parts.reset()
    currency.reset()
    distributors.reset()
    yield
    learned_parts.reset()
    currency.reset()
    distributors.reset()


@pytest.fixture(autouse=True)
def _sessions(request, tmp_path, monkeypatch):
    if request.node.get_closest_marker("history") is None:
        monkeypatch.setattr("pai_agent.session.Session.save_chat", lambda self: None)
        return None
    monkeypatch.setattr("pai_agent.history.SESSIONS_DIR", tmp_path)
    monkeypatch.setattr("pai_agent.session.SESSIONS_DIR", tmp_path)
    return tmp_path
