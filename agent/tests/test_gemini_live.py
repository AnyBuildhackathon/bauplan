"""Voice gateway auth, isolation, tool routing and transcript ownership, without paid calls."""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pai_agent import gemini_live as live
from pai_agent.bus import EventBus
from pai_agent.state import BuildState


def session(tmp_path):
    state = BuildState(session_id="voice-test", directory=tmp_path)
    return SimpleNamespace(
        state=state,
        bus=EventBus(),
        question=None,
        _busy=lambda: False,
        task=None,
    )


@pytest.mark.parametrize(
    "provider,env,expected",
    [
        ("studio", {"GEMINI_API_KEY": "private-key"}, True),
        ("studio", {}, False),
        ("vertex", {"GOOGLE_CLOUD_PROJECT": "project-123"}, True),
        ("vertex", {}, False),
    ],
)
def test_capability(provider, env, expected):
    with (
        patch.dict(os.environ, {"GEMINI_LIVE_PROVIDER": provider, **env}, clear=True),
        patch.object(live.shutil, "which", return_value="gcloud"),
    ):
        assert live.available() is expected


def test_vertex_auth_uses_refreshed_gcloud_token_per_connection():
    async def run():
        process = SimpleNamespace(
            returncode=0,
            communicate=AsyncMock(return_value=(b"private-oauth-token\n", b"")),
        )
        with (
            patch.dict(
                os.environ,
                {
                    "GEMINI_LIVE_PROVIDER": "vertex",
                    "GOOGLE_CLOUD_PROJECT": "project-123",
                },
                clear=True,
            ),
            patch.object(
                live.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
            ) as spawn,
        ):
            for _ in range(2):
                endpoint, headers, model = await live.connection()
                assert endpoint.startswith(
                    "wss://us-central1-aiplatform.googleapis.com/"
                )
                assert headers == {"Authorization": "Bearer private-oauth-token"}
                assert (
                    model
                    == "projects/project-123/locations/us-central1/publishers/google/models/gemini-3.8-live"
                )
            assert spawn.await_count == 2
            assert spawn.call_args.args == (
                "gcloud",
                "auth",
                "print-access-token",
                "--quiet",
            )

    asyncio.run(run())


def test_studio_key_stays_in_header():
    async def run():
        with patch.dict(
            os.environ,
            {"GEMINI_LIVE_PROVIDER": "studio", "GEMINI_API_KEY": "private-key"},
            clear=True,
        ):
            endpoint, headers, model = await live.connection()
            assert "private-key" not in endpoint
            assert headers == {"x-goog-api-key": "private-key"}
            assert model == "models/" + live.MODEL

    asyncio.run(run())


def test_transcripts_reach_chat_and_durable_log(tmp_path):
    async def run():
        s = session(tmp_path)
        await live.record(s, "user", "Make it lighter", "reson8")
        await live.record(s, "agent", "I'll ask Claude to check it.", "gemini")
        assert [e["role"] for e in s.bus.events] == ["user", "agent"]
        rows = [
            json.loads(row)
            for row in (tmp_path / "voice_conversation.jsonl").read_text().splitlines()
        ]
        assert [r["source"] for r in rows] == ["reson8", "gemini"]

    asyncio.run(run())


def test_engineer_waits_for_result_without_duplicating_user(tmp_path):
    async def run():
        s = session(tmp_path)

        async def work():
            await asyncio.sleep(0)
            s.state.metrics = {"weight_g": 42}

        async def start(*args, **kwargs):
            assert args == ("Make a phone stand",)
            assert kwargs == {"voice": True, "record_user": False}
            s.task = asyncio.create_task(work())
            return {"status": "started", "mode": "mock"}

        s.start = start
        result = await live.execute(s, "engineer", {"request": "Make a phone stand"})
        assert result["current"]["metrics"] == {"weight_g": 42}
        assert s.bus.events == []
        assert (await live.execute(s, "unknown", {}))["ok"] is False

    asyncio.run(run())


def test_voice_defaults_to_fenrir_and_env_overrides():
    with patch.dict(os.environ, {}, clear=True):
        assert live.voice() == "Fenrir"
        voice_config = live.setup(session(Path("/tmp")))["setup"]["generationConfig"]
        assert voice_config["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"] == {"voiceName": "Fenrir"}
    with patch.dict(os.environ, {"GEMINI_LIVE_VOICE": "Puck"}, clear=True):
        assert live.voice() == "Puck"


def client(tmp_path):
    app = FastAPI()
    app.include_router(live.router)
    app.state.session = session(tmp_path)
    return TestClient(app)


def test_websocket_checks_access_code_and_origin(tmp_path):
    with (
        patch.dict(
            os.environ,
            {"ANYBUILD_ACCESS_CODE": "secret", "GEMINI_API_KEY": "private"},
            clear=True,
        ),
        client(tmp_path) as c,
        pytest.raises(WebSocketDisconnect),
        c.websocket_connect(
            "/api/voice/live", headers={"origin": "http://127.0.0.1:5229"}
        ),
    ):
        pass
    with (
        patch.dict(os.environ, {"GEMINI_API_KEY": "private"}, clear=True),
        client(tmp_path) as c,
        pytest.raises(WebSocketDisconnect),
        c.websocket_connect(
            "/api/voice/live", headers={"origin": "https://untrusted.example"}
        ),
    ):
        pass


def test_upstream_errors_are_redacted_and_fallback_releases_session(tmp_path):
    with (
        patch.dict(os.environ, {"GEMINI_API_KEY": "private"}, clear=True),
        patch.object(
            live,
            "connection",
            AsyncMock(side_effect=RuntimeError("private credential")),
        ),
        client(tmp_path) as c,
    ):
        with c.websocket_connect("/api/voice/live") as ws:
            message = ws.receive_json()
            assert message["type"] == "error"
            assert "private" not in json.dumps(message)
        assert not c.app.state.session.live_voice


def test_note_uses_existing_jamie_adapter(tmp_path):
    with client(tmp_path) as c:
        c.app.state.session.state.meetings["review"] = {"id": "review"}
        c.app.state.session._ctx = lambda **kw: "ctx"
        with patch(
            "pai_agent.tools.jamie._write", AsyncMock(return_value={"ok": True})
        ) as write:
            response = c.post(
                "/api/voice/note",
                json={"meeting_id": "review", "text": "You: Make it lighter"},
            )
            assert response.status_code == 200
            assert write.call_args.args[1] == "note"
            assert write.call_args.args[2]["meeting_id"] == "review"
        assert (
            c.post(
                "/api/voice/note", json={"meeting_id": "missing", "text": "Hi"}
            ).status_code
            == 400
        )


class FakeUpstream:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def recv(self):
        return '{"setupComplete": {}}'

    def __aiter__(self):
        return self

    async def __anext__(self):
        return json.dumps(await self.queue.get())

    async def send(self, raw):
        data = json.loads(raw)
        self.sent.append(data)
        if "realtimeInput" in data:
            await self.queue.put(
                {
                    "toolCall": {
                        "functionCalls": [
                            {"id": "state-1", "name": "product_state", "args": {}}
                        ]
                    }
                }
            )
        elif "toolResponse" in data:
            await self.queue.put(
                {
                    "serverContent": {
                        "inputTranscription": {"text": "Gemini heard the user"},
                        "outputTranscription": {"text": "Here is the actual state."},
                        "modelTurn": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "data": "AAAA",
                                        "mimeType": "audio/pcm;rate=24000",
                                    }
                                }
                            ]
                        },
                        "turnComplete": True,
                    }
                }
            )


@pytest.mark.parametrize("reson8", [True, False])
def test_gateway_audio_tools_transcript_ownership_and_reconnect(tmp_path, reson8):
    upstreams = []

    def connect(*args, **kwargs):
        upstream = FakeUpstream()
        upstreams.append(upstream)
        return upstream

    with (
        patch.dict(os.environ, {"GEMINI_API_KEY": "private"}, clear=True),
        patch.object(live, "connect", connect),
        client(tmp_path) as c,
    ):
        for _ in range(2):
            with c.websocket_connect("/api/voice/live") as ws:
                assert ws.receive_json()["type"] == "ready"
                if reson8:
                    ws.send_json({"type": "transcriber", "source": "reson8"})
                    ws.send_json(
                        {"type": "transcript", "text": "Reson8 heard the user"}
                    )
                ws.send_bytes(bytes(3200))
                assert ws.receive_json()["type"] == "input"
                assert ws.receive_json() == {
                    "type": "audio",
                    "data": "AAAA",
                    "sample_rate": 24000,
                }
                assert ws.receive_json()["type"] == "turn_complete"
        events = c.app.state.session.bus.events
        users = [e["text"] for e in events if e.get("role") == "user"]
        assert (
            users
            == ["Reson8 heard the user" if reson8 else "Gemini heard the user"] * 2
        )
        assert len([e for e in events if e.get("role") == "agent"]) == 2
        assert all(
            any("toolResponse" in d for d in upstream.sent) for upstream in upstreams
        )
