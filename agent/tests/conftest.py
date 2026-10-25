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
def _sessions(request, tmp_path, monkeypatch):
    if request.node.get_closest_marker("history") is None:
        monkeypatch.setattr("pai_agent.session.Session.save_chat", lambda self: None)
        return None
    monkeypatch.setattr("pai_agent.history.SESSIONS_DIR", tmp_path)
    monkeypatch.setattr("pai_agent.session.SESSIONS_DIR", tmp_path)
    return tmp_path
