"""Environment loading. Never log secret values."""

from __future__ import annotations

import os

from pai_agent.paths import ENV_PATH

_LOADED = False


def load_env() -> None:
    """Fill missing variables from agent/.env. Existing variables win."""

    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    if not ENV_PATH.is_file():
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def claude_enabled() -> bool:
    load_env()
    forced = os.environ.get("PAI_FORCE_MOCK", "").strip().lower()
    if forced in {"1", "true", "yes"}:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def model_name() -> str:
    load_env()
    return os.environ.get("ANTHROPIC_MODEL", "").strip() or "claude-sonnet-5-5"


def pace_seconds() -> float:
    load_env()
    raw = os.environ.get("DEMO_PACE_S", "").strip() or "0"
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0
