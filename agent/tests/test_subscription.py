"""The subscription provider: provider selection, the public-deployment refusal, the API-key
stripping, and an agent run against a fake Claude Code that calls the app's tools through the
SDK's in-process MCP server, so the tool round trip and the event mapping are the real ones."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from pai_agent import provider, settings, subscription
from pai_agent.agents import AgentRun
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState

LOGGED_IN = {"available": True, "detail": "Claude Code (max plan) is logged in.", "plan": "max"}
LOGGED_OUT = {"available": False, "detail": "Claude Code is not logged in: run claude and /login."}


@pytest.fixture
def clean(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "PAI_FORCE_MOCK", "ANYBUILD_ACCESS_CODE", "PAI_LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(provider, "load_env", lambda: None)
    return monkeypatch


def _login(monkeypatch, status: dict) -> None:
    monkeypatch.setattr(provider, "subscription_status", lambda refresh=False: status)


# ---------------------------------------------------------------- provider selection


def test_auto_takes_the_api_key_first(clean):
    clean.setenv("ANTHROPIC_API_KEY", "sk-test")
    _login(clean, LOGGED_IN)
    assert provider.requested() == "auto"
    assert provider.active() == "api"


def test_auto_without_a_key_takes_the_logged_in_subscription(clean):
    _login(clean, LOGGED_IN)
    assert provider.active() == "subscription"
    assert provider.billing() == "subscription"


def test_auto_without_key_or_login_is_the_mock(clean):
    _login(clean, LOGGED_OUT)
    assert provider.active() == "mock"
    assert "not logged in" in provider.describe()["detail"]


def test_api_without_a_key_is_the_mock_even_when_logged_in(clean):
    clean.setenv("PAI_LLM_PROVIDER", "api")
    _login(clean, LOGGED_IN)
    assert provider.active() == "mock"


def test_subscription_wins_over_a_key_when_asked_for(clean):
    clean.setenv("PAI_LLM_PROVIDER", "subscription")
    clean.setenv("ANTHROPIC_API_KEY", "sk-test")
    _login(clean, LOGGED_IN)
    assert provider.active() == "subscription"


def test_force_mock_wins_over_everything(clean):
    clean.setenv("PAI_FORCE_MOCK", "1")
    clean.setenv("ANTHROPIC_API_KEY", "sk-test")
    _login(clean, LOGGED_IN)
    assert provider.active() == "mock"


def test_the_settings_choice_overrides_the_environment(clean):
    clean.setenv("PAI_LLM_PROVIDER", "api")
    _login(clean, LOGGED_IN)
    body = settings.update({"llm_provider": "subscription"})
    assert body["llm_provider"] == "subscription"
    assert body["provider"]["active"] == "subscription"
    assert provider.active() == "subscription"
    with pytest.raises(ValueError):
        settings.update({"llm_provider": "cloud"})


def test_unknown_env_value_means_auto(clean):
    clean.setenv("PAI_LLM_PROVIDER", "both")
    assert provider.requested() == "auto"


# ---------------------------------------------------------------- the public deployment


def test_a_public_server_refuses_the_subscription_in_settings(clean):
    clean.setenv("ANYBUILD_ACCESS_CODE", "stage")
    _login(clean, LOGGED_IN)
    with pytest.raises(ValueError, match="ANYBUILD_ACCESS_CODE"):
        settings.update({"llm_provider": "subscription"})
    assert provider.requested() == "auto"


def test_a_public_server_never_runs_on_the_subscription(clean):
    clean.setenv("ANYBUILD_ACCESS_CODE", "stage")
    clean.setenv("PAI_LLM_PROVIDER", "subscription")
    _login(clean, LOGGED_IN)
    assert provider.active() == "mock"
    described = provider.describe()
    assert described["detail"].startswith(provider.PUBLIC_REFUSAL)
    clean.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert provider.active() == "api"


def test_auto_on_a_public_server_without_a_key_is_the_mock(clean):
    clean.setenv("ANYBUILD_ACCESS_CODE", "stage")
    _login(clean, LOGGED_IN)
    assert provider.active() == "mock"


# ---------------------------------------------------------------- API-key stripping


def test_clean_env_drops_every_credential(clean):
    env = {"ANTHROPIC_API_KEY": "sk", "ANTHROPIC_AUTH_TOKEN": "t", "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDECODE": "1", "PATH": "/bin"}
    assert provider.clean_env(env) == {"PATH": "/bin"}


def test_the_launcher_starts_claude_without_the_api_key(clean, tmp_path):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\nenv\n", encoding="utf-8")
    fake.chmod(0o700)
    clean.setattr(provider, "cli_path", lambda: str(fake))
    clean.setattr(subscription, "HOME", tmp_path / "home")
    env = {**os.environ, "ANTHROPIC_API_KEY": "sk-ant-must-not-leak", "ANTHROPIC_AUTH_TOKEN": "tok", "CLAUDECODE": "1"}
    seen = subprocess.run([subscription.launcher()], env=env, capture_output=True, text=True, check=True).stdout
    names = {line.split("=", 1)[0] for line in seen.splitlines()}
    assert "ANTHROPIC_API_KEY" not in names and "ANTHROPIC_AUTH_TOKEN" not in names and "CLAUDECODE" not in names
    assert "sk-ant-must-not-leak" not in seen
    assert "PATH" in names


def test_the_login_probe_runs_without_the_api_key(clean):
    clean.setenv("ANTHROPIC_API_KEY", "sk-ant-must-not-leak")
    clean.setattr(provider, "cli_path", lambda: "/usr/local/bin/claude")
    seen = {}

    def run(command, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(stdout=json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro"}))

    clean.setattr(provider.subprocess, "run", run)
    status = provider._probe()
    assert status["available"] is True and status["plan"] == "pro"
    assert "ANTHROPIC_API_KEY" not in seen["env"]


def test_a_login_with_an_api_key_is_no_subscription(clean):
    clean.setattr(provider, "cli_path", lambda: "/usr/local/bin/claude")
    clean.setattr(provider.subprocess, "run", lambda command, **kwargs: SimpleNamespace(stdout=json.dumps({"loggedIn": True, "authMethod": "api_key"})))
    assert provider._probe()["available"] is False


def test_a_run_that_would_bill_an_api_key_is_refused():
    with pytest.raises(subscription.SubscriptionError, match="API key"):
        subscription._guard(SimpleNamespace(data={"apiKeySource": "ANTHROPIC_API_KEY"}))
    subscription._guard(SimpleNamespace(data={"apiKeySource": "none"}))


def test_options_keep_the_users_setup_out(clean, tmp_path):
    clean.setattr(provider, "cli_path", lambda: "/usr/local/bin/claude")
    clean.setattr(subscription, "HOME", tmp_path)
    opts = subscription.options(system="Mechanic", model="claude-opus-5-5", effort="high", tools=("assemble",), max_turns=40)
    assert opts.setting_sources == [] and opts.strict_mcp_config is True
    assert opts.tools == [] and opts.allowed_tools == ["mcp__anybuild__assemble"]
    assert opts.permission_mode == "dontAsk" and opts.effort == "high"
    assert opts.cli_path == str(tmp_path / "claude")


# ---------------------------------------------------------------- a fake Claude Code


class FakeClaude:
    """A transport that plays Claude Code: it answers the SDK's handshake, calls the given tools
    through the SDK's MCP control messages and streams assistant, user and result frames."""

    def __init__(self, calls: list[tuple[str, dict]], text: str = "Building it.", api_key_source: str = "none") -> None:
        self.calls = calls
        self.text = text
        self.api_key_source = api_key_source
        self.frames: asyncio.Queue = asyncio.Queue()
        self.waiting: dict[str, asyncio.Future] = {}
        self.results: list[dict] = []
        self.ready = False

    async def connect(self) -> None:
        self.ready = True

    def is_ready(self) -> bool:
        return self.ready

    async def write(self, data: str) -> None:
        for line in data.splitlines():
            message = json.loads(line)
            if message.get("type") == "control_request":
                await self.frames.put({"type": "control_response", "response": {"subtype": "success", "request_id": message["request_id"], "response": {}}})
            elif message.get("type") == "control_response":
                future = self.waiting.pop(message["response"]["request_id"], None)
                if future is not None:
                    future.set_result(message["response"])
            elif message.get("type") == "user":
                asyncio.ensure_future(self.play())

    async def rpc(self, key: str, message: dict) -> dict:
        future = asyncio.get_running_loop().create_future()
        self.waiting[key] = future
        await self.frames.put({"type": "control_request", "request_id": key, "request": {"subtype": "mcp_message", "server_name": "anybuild", "message": message}})
        return (await future)["response"]["mcp_response"]

    async def call(self, n: int, name: str, args: dict) -> dict:
        request = {"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": name, "arguments": args}}
        return (await self.rpc("mcp-" + str(n), request))["result"]

    async def play(self) -> None:
        usage = {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0}
        # Claude Code's MCP client handshake with the in-process server, then the run.
        hello = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "fake-claude", "version": "1"}}
        await self.rpc("mcp-init", {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": hello})
        await self.rpc("mcp-ready", {"jsonrpc": "2.0", "method": "notifications/initialized"})
        await self.frames.put({"type": "system", "subtype": "init", "session_id": "sess-1", "apiKeySource": self.api_key_source, "tools": []})
        for n, (name, args) in enumerate(self.calls, 1):
            content = [{"type": "text", "text": self.text}] if n == 1 else []
            content.append({"type": "tool_use", "id": "tu" + str(n), "name": "mcp__anybuild__" + name, "input": args})
            await self.frames.put({"type": "assistant", "message": {"id": "m" + str(n), "model": "claude-opus-5-5", "content": content, "usage": usage}, "parent_tool_use_id": None, "session_id": "sess-1"})
            result = await self.call(n, name, args)
            self.results.append(result)
            await self.frames.put({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu" + str(n), "content": result["content"]}]}, "parent_tool_use_id": None, "session_id": "sess-1"})
        await self.frames.put({"type": "assistant", "message": {"id": "m-end", "model": "claude-opus-5-5", "content": [{"type": "text", "text": "Done: it holds."}], "usage": usage}, "parent_tool_use_id": None, "session_id": "sess-1"})
        total = {key: value * (len(self.calls) + 1) for key, value in usage.items()}
        await self.frames.put({"type": "result", "subtype": "success", "is_error": False, "duration_ms": 5, "duration_api_ms": 4, "num_turns": len(self.calls) + 1, "session_id": "sess-1", "result": "Done: it holds.", "usage": total})
        await self.frames.put(None)

    async def read_messages(self):
        while True:
            frame = await self.frames.get()
            if frame is None:
                return
            yield frame

    async def end_input(self) -> None:
        pass

    async def close(self) -> None:
        self.ready = False


@pytest.fixture
def fake_cli(clean, tmp_path):
    """Runs subscription calls against a FakeClaude instead of the real Claude Code."""

    import claude_agent_sdk

    holder: dict = {}
    real = claude_agent_sdk.query

    def query(*, prompt, options=None, transport=None):
        holder["options"] = options
        return real(prompt=prompt, options=options, transport=holder["fake"])

    clean.setattr(claude_agent_sdk, "query", query)
    clean.setattr(provider, "cli_path", lambda: "/usr/local/bin/claude")
    clean.setattr(subscription, "HOME", tmp_path / "home")
    _login(clean, LOGGED_IN)
    return holder


def _ctx(tmp_path) -> Ctx:
    return Ctx(EventBus(), BuildState(session_id="t", directory=tmp_path), auto_steps=False)


def test_a_tool_round_trips_through_the_mcp_server(fake_cli, tmp_path):
    from pai_agent.tools.registry import SCHEMAS

    ctx = _ctx(tmp_path)
    ctx.pending.append("make it blue")
    fake = fake_cli["fake"] = FakeClaude([("mascot_say", {"state": "freut_sich", "say": "Looks solid."})])
    run = AgentRun(ctx, "orchestrator", "Orchestrator", "claude-opus-5-5", "high", "build")
    chat: list[str] = []

    async def on_text(text: str) -> None:
        chat.append(text)

    schemas = [schema for schema in SCHEMAS if schema["name"] == "mascot_say"]
    outcome = asyncio.run(subscription.run_agent(ctx, run, system="Mechanic", prompt="Build it.", schemas=schemas, max_turns=40, on_text=on_text))

    assert outcome == {"ok": True, "text": "Done: it holds.", "session_id": "sess-1", "error": None}
    # The tool ran in this process through call_tool: its card and its mascot event are on the bus.
    events = ctx.bus.events
    assert any(e["type"] == "tool" and e["name"] == "mascot_say" and e["status"] == "running" for e in events)
    assert any(e["type"] == "mascot" and e.get("say") == "Looks solid." for e in events)
    # Its JSON result went back to Claude Code, with what the person said meanwhile.
    result = fake.results[0]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"])["ok"] is True
    assert result["content"][1]["text"] == "The person said while you worked: make it blue"
    # Streamed text reached the chat callback; rounds, tokens and the call log are on the agent.
    assert chat == ["Building it.", "Done: it holds."]
    assert run.rounds == 2 and run.usage["output_tokens"] == 40 and run.usage["cache_read_tokens"] == 2000
    assert [call["tool"] for call in run.calls] == ["mascot_say"]
    assert fake_cli["options"].allowed_tools == ["mcp__anybuild__mascot_say"]


def test_a_failing_tool_comes_back_as_an_error_the_model_reads(fake_cli, tmp_path):
    from pai_agent.tools.registry import SCHEMAS

    ctx = _ctx(tmp_path)
    fake = fake_cli["fake"] = FakeClaude([("assemble", {})])
    run = AgentRun(ctx, "checks", "Analysis agent", "claude-sonnet-5-5", "medium", "checks")
    schemas = [schema for schema in SCHEMAS if schema["name"] == "assemble"]
    asyncio.run(subscription.run_agent(ctx, run, system="checks", prompt="Assemble.", schemas=schemas, max_turns=12))
    assert fake.results[0]["isError"] is True
    assert json.loads(fake.results[0]["content"][0]["text"])["ok"] is False


def test_cad_views_picture_reaches_claude_code_as_mcp_image_content(fake_cli, tmp_path):
    import base64
    import struct

    from pai_agent import assembly as asm
    from pai_agent.mesh_export import stls_to_glb
    from pai_agent.tools.registry import SCHEMAS

    asm.write_stl(tmp_path / "part-block.stl", asm.box_triangles([30.0, 20.0, 10.0], (0.0, 0.0, 5.0), asm.rotation(None)))
    stls_to_glb([("Block", tmp_path / "part-block.stl", "#ff8a3d")], tmp_path / "part-block.glb")
    ctx = _ctx(tmp_path)
    ctx.state.product = "gripper"
    ctx.state.part = {"name": "Block", "parts": [{"name": "Block", "reference": False}]}
    ctx.state.stl_path = str(tmp_path / "part-block.stl")
    fake = fake_cli["fake"] = FakeClaude([("cad_view", {"view": "iso"})])
    run = AgentRun(ctx, "orchestrator", "Orchestrator", "claude-opus-5-5", "high", "build")
    schemas = [schema for schema in SCHEMAS if schema["name"] == "cad_view"]
    asyncio.run(subscription.run_agent(ctx, run, system="Mechanic", prompt="Look at it.", schemas=schemas, max_turns=40))
    # The SDK's in-process server passes the picture on as MCP image content, next to the JSON that names the parts.
    text, image = fake.results[0]["content"]
    assert json.loads(text["text"])["parts"] == [{"number": 1, "name": "Block", "color": "orange"}]
    assert image["type"] == "image" and image["mimeType"] == "image/png"
    png = base64.b64decode(image["data"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (1024, 768)


def test_the_agent_event_says_subscription_instead_of_a_cost(fake_cli, tmp_path):
    ctx = _ctx(tmp_path)
    fake_cli["fake"] = FakeClaude([])
    run = AgentRun(ctx, "orchestrator", "Orchestrator", "claude-opus-5-5", "high", "build")
    asyncio.run(subscription.run_agent(ctx, run, system="Mechanic", prompt="Hi.", schemas=[], max_turns=40))
    asyncio.run(run.emit("done", "finished"))
    event = [e for e in ctx.bus.events if e["type"] == "agent"][-1]
    assert event["billing"] == "subscription" and event["cost_usd"] == 0.0
    assert event["output_tokens"] == 20 and event["rounds"] == 1
    assert run.cost_label() == "subscription"


def test_a_run_billing_an_api_key_stops_at_init(fake_cli, tmp_path):
    ctx = _ctx(tmp_path)
    fake_cli["fake"] = FakeClaude([], api_key_source="ANTHROPIC_API_KEY")
    run = AgentRun(ctx, "orchestrator", "Orchestrator", "claude-opus-5-5", "high", "build")
    with pytest.raises(subscription.SubscriptionError):
        asyncio.run(subscription.run_agent(ctx, run, system="Mechanic", prompt="Hi.", schemas=[], max_turns=40))


def test_the_lead_loop_keeps_the_session_and_chats(fake_cli, tmp_path):
    from pai_agent.tools.registry import SCHEMAS

    ctx = _ctx(tmp_path)
    fake_cli["fake"] = FakeClaude([("mascot_say", {"state": "denkt", "say": "Hmm."})], text="On it.")
    lead = AgentRun(ctx, "orchestrator", "Orchestrator", "claude-opus-5-5", "high", "build")
    schemas = [schema for schema in SCHEMAS if schema["name"] == "mascot_say"]
    asyncio.run(subscription.lead_loop(ctx, lead, "Mechanic", schemas, "Build a phone stand.", frozenset()))
    assert ctx.state.llm_session == "sess-1"
    said = [e["text"] for e in ctx.bus.events if e["type"] == "chat" and e["role"] == "agent"]
    assert said == ["On it.", "Done: it holds."]
    assert [e for e in ctx.bus.events if e["type"] == "agent"][-1]["status"] == "done"
    # The next message resumes that conversation.
    fake_cli["fake"] = FakeClaude([])
    asyncio.run(subscription.lead_loop(ctx, lead, "Mechanic", [], "Make it taller.", frozenset()))
    assert fake_cli["options"].resume == "sess-1"


def test_one_round_returns_an_api_shaped_reply(fake_cli, tmp_path):
    tool = {"name": "propose_variant", "description": "One variant.", "input_schema": {"type": "object", "properties": {"label": {"type": "string"}}}}
    fake_cli["fake"] = FakeClaude([("propose_variant", {"label": "Light"})])
    reply = asyncio.run(subscription._one_round("claude-sonnet-5-5", "medium", system=[{"type": "text", "text": "Variant agent."}], messages=[{"role": "user", "content": "Go."}], tools=[tool]))
    use = next(block for block in reply.content if block.type == "tool_use")
    assert use.name == "propose_variant" and use.input == {"label": "Light"}
    assert use.model_dump() == {"type": "tool_use", "id": "tu1", "name": "propose_variant", "input": {"label": "Light"}}
    assert reply.stop_reason == "tool_use" and reply.usage.output_tokens == 40
    assert settings.usage_of(reply)["cache_read_tokens"] == 2000


def test_a_history_flattens_into_one_user_turn():
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
    messages = [
        {"role": "user", "content": [image, {"type": "text", "text": "Read the sketch."}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "propose_spec", "input": {"name": "Stand"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "is_error": True, "content": "No parts."}]},
    ]
    blocks = subscription._flatten(messages)
    assert blocks[0] == image
    assert blocks[2]["text"] == 'Your earlier answer called propose_spec with {"name": "Stand"}'
    assert blocks[3]["text"] == "Its result (an error): No parts."


def test_a_hit_limit_is_named_with_its_reset():
    info = SimpleNamespace(rate_limit_type="five_hour", resets_at=None)
    assert subscription.limit_note(info) == "The Claude subscription hit its 5-hour limit."


def test_frames_of_one_message_count_once_at_their_largest():
    from claude_agent_sdk import AssistantMessage, TextBlock

    stream = subscription.Stream(None, "x")
    for output in (3, 180, 40):
        stream.take(AssistantMessage(content=[TextBlock(text="a")], model="m", message_id="m1", usage={"output_tokens": output, "input_tokens": 2}))
    stream.take(AssistantMessage(content=[], model="m", message_id="m2", usage={"output_tokens": 5}))
    assert stream.rounds == 2
    assert stream.total()["output_tokens"] == 185 and stream.total()["input_tokens"] == 2
