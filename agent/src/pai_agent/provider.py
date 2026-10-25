"""Which Claude runs the bench: the paid API key, the local Claude Code subscription, or the mock.

`PAI_LLM_PROVIDER` (api, subscription or auto, default auto) or the Settings panel picks it:

- api: the Anthropic API with `ANTHROPIC_API_KEY`; without a key the mock stories run.
- subscription: every Claude call goes through the Claude Code installed and logged in on this
  machine (`subscription.py`), billed to that login's plan; without a logged-in `claude` the mock runs.
- auto: api when a key is set, else the subscription when Claude Code is logged in, else the mock.

A public deployment (`ANYBUILD_ACCESS_CODE` set) never runs on someone's personal subscription:
it is refused there and the reason shows in the status. `PAI_FORCE_MOCK=1` still wins over all.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from pai_agent.env import load_env

CHOICES = ("auto", "api", "subscription")
PUBLIC_REFUSAL = (
    "The subscription runs only on a local machine: this server has ANYBUILD_ACCESS_CODE set, "
    "so it is public and uses the API key."
)
_STATUS_TTL_S = 120.0

_override: str | None = None
_status: tuple[float, dict] | None = None


def requested() -> str:
    """The provider asked for: the Settings choice, else PAI_LLM_PROVIDER, else auto."""

    if _override is not None:
        return _override
    load_env()
    value = os.environ.get("PAI_LLM_PROVIDER", "").strip().lower()
    return value if value in CHOICES else "auto"


def choose(value: str) -> None:
    """The Settings choice; raises ValueError for an unknown value or the subscription on a public server."""

    global _override
    value = str(value).strip().lower()
    if value not in CHOICES:
        raise ValueError("llm_provider must be one of " + ", ".join(CHOICES) + ".")
    if value == "subscription" and public():
        raise ValueError(PUBLIC_REFUSAL)
    _override = value


def reset_choice() -> None:
    global _override
    _override = None


def public() -> bool:
    load_env()
    return bool(os.environ.get("ANYBUILD_ACCESS_CODE", "").strip())


def forced_mock() -> bool:
    load_env()
    return os.environ.get("PAI_FORCE_MOCK", "").strip().lower() in {"1", "true", "yes"}


def api_key_set() -> bool:
    load_env()
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def cli_path() -> str | None:
    """The `claude` on PATH, else the default install in ~/.local/bin, else the SDK's bundled copy."""

    found = shutil.which("claude")
    if found:
        return found
    home = Path.home() / ".local" / "bin" / "claude"
    if home.is_file():
        return str(home)
    try:
        import claude_agent_sdk
    except ImportError:
        return None
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    return str(bundled) if bundled.is_file() else None


def subscription_status(refresh: bool = False) -> dict:
    """{available, detail, plan}: Claude Code present and logged in to a claude.ai plan. Cached for two minutes.

    `claude auth status` reads the local login only; it makes no model call.
    """

    global _status
    if not refresh and _status is not None and time.monotonic() - _status[0] < _STATUS_TTL_S:
        return _status[1]
    result = _probe()
    _status = (time.monotonic(), result)
    return result


def _probe() -> dict:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return {"available": False, "detail": "claude-agent-sdk is not installed in the agent environment (uv sync)."}
    path = cli_path()
    if path is None:
        return {"available": False, "detail": "Claude Code is not installed: no claude command found."}
    try:
        done = subprocess.run(
            [path, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=15,
            # The status the subscription run will see: without an API key in the environment.
            env=clean_env(os.environ),
        )
        info = json.loads(done.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"available": False, "detail": "Claude Code login status unavailable: " + type(exc).__name__ + "."}
    if not info.get("loggedIn"):
        return {"available": False, "detail": "Claude Code is not logged in: run claude and /login."}
    if info.get("authMethod") != "claude.ai":
        return {"available": False, "detail": "Claude Code is logged in with " + str(info.get("authMethod")) + ", not a Claude subscription."}
    plan = str(info.get("subscriptionType") or "")
    return {"available": True, "detail": "Claude Code " + ("(" + plan + " plan) " if plan else "") + "is logged in.", "plan": plan}


# What must never reach the Claude Code process: with any of these it would bill the API key or another backend.
STRIPPED = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")


def clean_env(base: dict | os._Environ) -> dict:
    """`base` without the API credentials, and not marked as a session nested in another Claude Code."""

    return {key: value for key, value in base.items() if key not in STRIPPED and key != "CLAUDECODE"}


def active() -> str:
    """api, subscription or mock: what the next Claude call uses."""

    if forced_mock():
        return "mock"
    wanted = requested()
    if wanted == "api":
        return "api" if api_key_set() else "mock"
    if wanted == "subscription":
        if public():
            return "api" if api_key_set() else "mock"
        return "subscription" if subscription_status()["available"] else "mock"
    if api_key_set():
        return "api"
    if not public() and subscription_status()["available"]:
        return "subscription"
    return "mock"


def describe() -> dict:
    """The provider for the status and the settings: what was asked, what runs and why."""

    wanted = requested()
    running = active()
    if running == "api":
        detail = "Claude through the Anthropic API key."
    elif running == "subscription":
        detail = "Claude through your local Claude Code login, on its subscription. " + subscription_status()["detail"]
    elif forced_mock():
        detail = "PAI_FORCE_MOCK=1: the scripted offline build runs."
    elif wanted == "api" or public():
        detail = "No ANTHROPIC_API_KEY: the scripted offline build runs."
    else:
        detail = "No API key and no logged-in Claude Code: the scripted offline build runs. " + subscription_status()["detail"]
    if wanted == "subscription" and public():
        detail = PUBLIC_REFUSAL + " " + detail
    return {"requested": wanted, "active": running, "detail": detail, "public": public()}


def billing() -> str:
    """How a Claude call is paid: "subscription" or "api" (the mock reports api-priced sample numbers)."""

    return "subscription" if active() == "subscription" else "api"
