"""Claude through the local Claude Code login: the subscription provider.

With `provider.active() == "subscription"` every Claude call of the app runs in the Claude Code
installed and logged in on this machine, through the Claude Agent SDK, and is billed to that
login's plan instead of `ANTHROPIC_API_KEY`:

- `run_agent` runs an agent loop (Mechanic's lead loop, a sub-agent). The app's tools from
  `tools/registry.py` are an in-process MCP server, so every call goes through the same
  `call_tool` with the same tool, step and card events as the API path. Streamed text reaches the
  chat as it is written, each model message counts as a round, and tokens come from the stream.
- `create_message` emulates one Messages round (the CAD script writer, the variant agents, the
  sketch reader, the explanations): the tools it offers only record the call, the round ends
  after the first answer, and the reply comes back shaped like an API response.
- `ask_web` answers with Claude Code's own WebSearch and WebFetch, for live prices and web parts.

Claude Code runs without the API credentials in its environment (`provider.STRIPPED`, removed by
a small launcher), without the user's settings, hooks, plugins or MCP servers, with no built-in
tools except web search where asked, and refuses to start a run its init frame says would bill
an API key. Per-step effort and thinking map onto Claude Code's own flags; cost is the plan's.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import threading
import time
from contextlib import suppress
from types import SimpleNamespace

from pai_agent import provider
from pai_agent.paths import RUNS_DIR
from pai_agent.run_control import RunStopped

log = logging.getLogger(__name__)

SERVER = "anybuild"
PREFIX = "mcp__" + SERVER + "__"
WEB_TOOLS = ("WebSearch", "WebFetch")
HOME = RUNS_DIR / "subscription"
# Short calls (a CAD script, a price search, an explanation) run at most this many Claude Code processes at once.
_SHORT = threading.BoundedSemaphore(max(1, int(os.environ.get("PAI_SUBSCRIPTION_PARALLEL", "") or 3)))
_STOPPED = {"ok": False, "error": "The user stopped the run before this tool ran."}


class SubscriptionError(RuntimeError):
    """Claude Code could not run the request on the subscription; the message says why."""


def launcher() -> str:
    """A launcher for `claude` that starts it with the API credentials removed from its environment.

    The SDK passes the server's whole environment on to Claude Code and can only add to it, so the
    launcher unsets them right before Claude Code starts: it never sees ANTHROPIC_API_KEY.
    """

    cli = provider.cli_path()
    if cli is None:
        raise SubscriptionError("Claude Code is not installed: no claude command found.")
    unset = " ".join("-u " + name for name in (*provider.STRIPPED, "CLAUDECODE"))
    text = "#!/bin/sh\n# AnyBuild: Claude Code on the local subscription, never with API credentials.\nexec env " + unset + " " + shlex.quote(cli) + ' "$@"\n'
    path = HOME / "claude"
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        HOME.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        path.chmod(0o700)
    return str(path)


def _workdir() -> str:
    # An empty working directory: no project files, no CLAUDE.md, transcripts of their own.
    work = HOME / "work"
    work.mkdir(parents=True, exist_ok=True)
    return str(work)


def options(*, system: str, model: str, effort: str | None, server=None, tools: tuple[str, ...] = (), builtin: tuple[str, ...] = (), max_turns: int, resume: str | None = None, thinking: bool = True):
    """Claude Code with Mechanic's system prompt, the given tools and nothing of the user's own setup."""

    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAgentOptions(
        system_prompt=system,
        model=model,
        effort=effort,
        thinking={"type": "adaptive"} if thinking else {"type": "disabled"},
        # Built-in tools: none, or web search; the app's tools come from the in-process server.
        tools=list(builtin),
        allowed_tools=[PREFIX + name for name in tools] + list(builtin),
        mcp_servers={SERVER: server} if server is not None else {},
        strict_mcp_config=True,
        setting_sources=[],
        # Anything not allowed above is refused without a prompt.
        permission_mode="dontAsk",
        max_turns=max_turns,
        resume=resume,
        cwd=_workdir(),
        cli_path=launcher(),
        # A FreeCAD build or a sub-agent can take minutes; Claude Code waits for the tool.
        env={"MCP_TOOL_TIMEOUT": "1800000"},
    )


def _guard(message) -> None:
    """Stops a run whose init frame says Claude Code would bill an API key."""

    source = str((message.data or {}).get("apiKeySource") or "none")
    if source != "none":
        raise SubscriptionError("Claude Code would bill an API key (" + source + "), not the subscription; the run stops.")


def usage_of(raw: dict | None) -> dict:
    raw = raw or {}
    return {
        "input_tokens": int(raw.get("input_tokens") or 0),
        "output_tokens": int(raw.get("output_tokens") or 0),
        "cache_read_tokens": int(raw.get("cache_read_input_tokens") or 0),
        "cache_write_tokens": int(raw.get("cache_creation_input_tokens") or 0),
    }


def limit_note(info) -> str:
    """What the room reads when the subscription hits its 5-hour or weekly limit."""

    window = {"five_hour": "5-hour", "seven_day": "weekly", "seven_day_opus": "weekly Opus", "seven_day_sonnet": "weekly Sonnet"}.get(str(info.rate_limit_type), "usage")
    note = "The Claude subscription hit its " + window + " limit"
    if info.resets_at:
        note += "; it resets at " + time.strftime("%H:%M", time.localtime(int(info.resets_at)))
    return note + "."


def _user(content) -> dict:
    return {"type": "user", "message": {"role": "user", "content": content}, "parent_tool_use_id": None, "session_id": ""}


async def _prompt(content):
    yield _user(content)


class Stream:
    """One Claude Code run, message by message, mapped onto the app's agent bookkeeping."""

    def __init__(self, opts, content) -> None:
        self.opts = opts
        self.content = content
        self.session_id: str | None = None
        self.usage: dict[str, dict] = {}
        self.texts: list[str] = []
        self.blocks: list = []
        self.result = None
        self.limit: str | None = None
        self.error: str | None = None

    async def messages(self):
        from claude_agent_sdk import ResultError, ResultMessage, query

        ended = False
        try:
            async for message in query(prompt=_prompt(self.content), options=self.opts):
                ended = ended or isinstance(message, ResultMessage)
                yield message
        except ResultError:
            # Claude Code exits non-zero after an error result it already sent; `failure` reads that result.
            if not ended:
                raise

    def take(self, message) -> list[str]:
        """Bookkeeping for one message; returns the text blocks it carries for the chat."""

        from claude_agent_sdk import AssistantMessage, RateLimitEvent, ResultMessage, SystemMessage, TextBlock, ToolUseBlock

        if isinstance(message, SystemMessage) and message.subtype == "init":
            _guard(message)
            self.session_id = (message.data or {}).get("session_id") or self.session_id
        elif isinstance(message, RateLimitEvent):
            if message.rate_limit_info.status == "rejected":
                self.limit = limit_note(message.rate_limit_info)
            elif message.rate_limit_info.status == "allowed_warning":
                log.warning("Claude subscription near its limit: %s", message.rate_limit_info.utilization)
        elif isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
            key = message.message_id or str(len(self.usage))
            if message.usage:
                self.usage[key] = usage_of(message.usage)
            else:
                self.usage.setdefault(key, usage_of(None))
            if message.error:
                self.error = str(message.error)
            texts = []
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    texts.append(block.text)
                    self.texts.append(block.text)
                    self.blocks.append(SimpleNamespace(type="text", text=block.text))
                elif isinstance(block, ToolUseBlock):
                    self.blocks.append(_tool_block(block))
            return texts
        elif isinstance(message, ResultMessage):
            self.result = message
            self.session_id = message.session_id or self.session_id
        return []

    @property
    def rounds(self) -> int:
        return len(self.usage)

    def total(self) -> dict:
        if self.result is not None and self.result.usage:
            return usage_of(self.result.usage)
        total: dict = {}
        for usage in self.usage.values():
            for key, value in usage.items():
                total[key] = total.get(key, 0) + value
        return total

    def failure(self) -> str | None:
        """Why the run failed, or None; running out of turns is not a failure here."""

        if self.limit:
            return self.limit
        if self.result is None:
            return self.error or "Claude Code ended without a result."
        if self.result.is_error and self.result.subtype != "error_max_turns":
            return str(self.result.result or ", ".join(self.result.errors or []) or self.error or self.result.subtype)
        return None


def _tool_block(block) -> SimpleNamespace:
    name = block.name[len(PREFIX):] if block.name.startswith(PREFIX) else block.name
    data = {"type": "tool_use", "id": block.id, "name": name, "input": dict(block.input or {})}
    return SimpleNamespace(**data, model_dump=lambda **_: dict(data))


def _payload(result: dict, heard: list[str]) -> dict:
    content = [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}]
    content += [{"type": "text", "text": "The person said while you worked: " + text} for text in heard]
    return {"content": content, "is_error": result.get("ok") is False}


def _server(handlers: dict, schemas: list[dict], parallel: frozenset = frozenset()):
    from claude_agent_sdk import SdkMcpTool, ToolAnnotations, create_sdk_mcp_server

    tools = [
        SdkMcpTool(
            name=schema["name"],
            description=schema.get("description", ""),
            input_schema=schema.get("input_schema") or {"type": "object", "properties": {}},
            handler=handlers[schema["name"]],
            # Claude Code runs read-only tools of one answer side by side: each cad_part has its own CAD agent.
            annotations=ToolAnnotations(readOnlyHint=True) if schema["name"] in parallel else None,
        )
        for schema in schemas
    ]
    return create_sdk_mcp_server(SERVER, tools=tools)


async def run_agent(ctx, run, *, system: str, prompt, schemas: list[dict], max_turns: int, on_text=None, resume: str | None = None, parallel: frozenset = frozenset()) -> dict:
    """One agent loop in Claude Code with the app's tools; returns {ok, text, session_id, error}.

    Tool calls run in this process through `call_tool` and are logged on `run` (an `agents.AgentRun`)
    like the API path's. Stop ends the run at the next tool call or while the model thinks; a model
    that sends nothing for PAI_MODEL_TIMEOUT_S while no tool runs ends it with a TimeoutError.
    """

    from pai_agent.timeouts import model_timeout
    from pai_agent.tools.registry import call_tool

    watch = {"busy": 0, "seen": time.monotonic(), "stopped": False}

    def handler(name: str):
        async def handle(args: dict) -> dict:
            watch["busy"] += 1
            try:
                await ctx.checkpoint()
                await run.use(name)
                result = await call_tool(ctx, name, args if isinstance(args, dict) else {})
                run.called(name, result)
            except RunStopped:
                watch["stopped"] = True
                result = _STOPPED
            finally:
                watch["busy"] -= 1
                watch["seen"] = time.monotonic()
            # What the person said while these tools ran reaches the model with their results.
            return _payload(result, ctx.take_pending())

        return handle

    names = [schema["name"] for schema in schemas]
    server = _server({name: handler(name) for name in names}, schemas, parallel)
    opts = options(system=system, model=run.model, effort=run.effort, server=server, tools=tuple(names), max_turns=max_turns, resume=resume)
    stream = Stream(opts, prompt)
    queue: asyncio.Queue = asyncio.Queue()
    end = object()

    async def pump() -> None:
        try:
            async for message in stream.messages():
                await queue.put(message)
        except Exception as exc:
            await queue.put(exc)
        else:
            await queue.put(end)

    task = asyncio.ensure_future(pump())
    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), 0.25)
            except TimeoutError:
                if watch["stopped"]:
                    raise RunStopped
                if watch["busy"]:
                    # A tool that runs finishes first, so nothing is left half written; Stop lands after it.
                    continue
                paused = time.monotonic()
                await ctx.checkpoint()
                if time.monotonic() - paused > 0.5:
                    watch["seen"] = time.monotonic()
                if time.monotonic() - watch["seen"] > model_timeout():
                    raise TimeoutError(f"no progress for {model_timeout():g} s (PAI_MODEL_TIMEOUT_S), the run stops here")
                continue
            watch["seen"] = time.monotonic()
            if message is end:
                break
            if isinstance(message, Exception):
                raise message
            before = stream.rounds
            for text in stream.take(message):
                if on_text is not None:
                    await on_text(text)
            if stream.rounds != before:
                run.rounds = stream.rounds
                run.usage = stream.total()
                await run.emit("running", (run.calls[-1]["detail"] if run.calls else "thinking")[:120])
        if watch["stopped"]:
            raise RunStopped
    finally:
        task.cancel()
        with suppress(BaseException):
            await task
        run.rounds = max(run.rounds, stream.rounds)
        run.usage = stream.total()
    failure = stream.failure()
    text = (stream.result.result if stream.result is not None and stream.result.result else "") or (stream.texts[-1] if stream.texts else "")
    if failure is None and stream.result is not None and stream.result.subtype == "error_max_turns":
        text = (text + " " if text else "") + "Stopped after " + str(max_turns) + " rounds."
    return {"ok": failure is None, "text": text.strip(), "session_id": stream.session_id, "error": failure}


async def lead_loop(ctx, lead, system: str, schemas: list[dict], text: str, parallel: frozenset) -> None:
    """Mechanic's lead loop on the subscription: the same tools, chat, steps and Stop as `_lead_loop`."""

    from pai_agent.tools.registry import call_tool

    async def say(chunk: str) -> None:
        if chunk.strip():
            await ctx.chat("agent", chunk.strip())

    await lead.emit("running", "plans the build")
    try:
        outcome = await run_agent(ctx, lead, system=system, prompt=text, schemas=schemas, max_turns=40, on_text=say, resume=ctx.state.llm_session, parallel=parallel)
    except RunStopped:
        raise
    except Exception as exc:
        log.exception("Claude Code run failed")
        outcome = {"ok": False, "error": str(exc) or type(exc).__name__, "session_id": None}
    if outcome.get("session_id"):
        # The next message continues this conversation, like the API path's message history.
        ctx.state.llm_session = outcome["session_id"]
    if not outcome["ok"]:
        await lead.emit("error", str(outcome["error"])[:160])
        await ctx.chat("agent", "The model request failed: " + str(outcome["error"]) + ". Send your request again.")
        await call_tool(ctx, "mascot_say", {"state": "besorgt", "say": "The model is not answering."})
        return
    await lead.emit("done", "finished in " + str(lead.rounds) + " round(s)")


def _flatten(messages: list[dict]) -> list[dict]:
    """A Messages history as one user turn: Claude Code takes user turns only, so earlier answers become text."""

    blocks: list[dict] = []
    for message in messages:
        content = message["content"] if isinstance(message["content"], list) else [{"type": "text", "text": str(message["content"])}]
        for block in content:
            kind = block.get("type")
            if message["role"] == "user" and kind in ("text", "image"):
                blocks.append(block)
            elif kind == "text":
                blocks.append({"type": "text", "text": "Your earlier answer: " + str(block.get("text", ""))})
            elif kind == "tool_use":
                blocks.append({"type": "text", "text": "Your earlier answer called " + str(block.get("name")) + " with " + json.dumps(block.get("input"), ensure_ascii=False)})
            elif kind == "tool_result":
                body = block.get("content")
                blocks.append({"type": "text", "text": "Its result" + (" (an error)" if block.get("is_error") else "") + ": " + (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False))})
    return blocks


def _text_of(system) -> str:
    if isinstance(system, list):
        return "\n\n".join(str(block.get("text", "")) for block in system if isinstance(block, dict))
    return str(system or "")


async def _one_round(model: str, effort: str | None, *, system, messages: list[dict], tools: list[dict] | None = None, tool_choice: dict | None = None, thinking: bool = True):
    """One Messages round in Claude Code; the offered tools only record the call."""

    async def record(_args: dict) -> dict:
        return {"content": [{"type": "text", "text": "Recorded."}]}

    tools = tools or []
    text = _text_of(system)
    if tool_choice and tool_choice.get("type") == "tool":
        text += "\n\nAnswer only by calling the tool " + str(tool_choice["name"]) + " exactly once."
    server = _server({tool["name"]: record for tool in tools}, tools) if tools else None
    opts = options(system=text, model=model, effort=effort, server=server, tools=tuple(tool["name"] for tool in tools), max_turns=1, thinking=thinking)
    stream = Stream(opts, _flatten(messages))
    async for message in stream.messages():
        stream.take(message)
    failure = stream.failure()
    if failure is not None and not stream.blocks:
        raise SubscriptionError(failure)
    usage = stream.total()
    return SimpleNamespace(
        content=stream.blocks,
        stop_reason="tool_use" if any(block.type == "tool_use" for block in stream.blocks) else "end_turn",
        usage=SimpleNamespace(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_input_tokens=usage.get("cache_read_tokens", 0),
            cache_creation_input_tokens=usage.get("cache_write_tokens", 0),
        ),
    )


def _short(work, timeout: float):
    """Runs one short Claude Code call to its end in this worker thread, at most _SHORT at once."""

    with _SHORT:
        return asyncio.run(asyncio.wait_for(work, timeout))


def create_message(model: str, effort: str | None, *, messages: list[dict], system="", tools: list[dict] | None = None, tool_choice: dict | None = None, thinking: bool = True, timeout: float = 300.0, **_ignored):
    """`agents.create_message` on the subscription: blocking, for a worker thread. max_tokens has no equivalent and is ignored."""

    return _short(_one_round(model, effort, system=system, messages=messages, tools=tools, tool_choice=tool_choice, thinking=thinking), timeout)


async def _web(model: str, system: str, prompt: str, max_turns: int) -> str:
    opts = options(system=system, model=model, effort="low", builtin=WEB_TOOLS, max_turns=max_turns)
    stream = Stream(opts, prompt)
    async for message in stream.messages():
        stream.take(message)
    failure = stream.failure()
    if failure is not None:
        raise SubscriptionError(failure)
    return (stream.result.result if stream.result is not None and stream.result.result else "") or "\n".join(stream.texts)


def ask_web(model: str, system: str, prompt: str, deadline: float, max_turns: int = 8) -> str:
    """The final text of a search with Claude Code's WebSearch and WebFetch; blocking, for a worker thread."""

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("no time left for the web search")
    return _short(_web(model, system, prompt, max_turns), remaining)

