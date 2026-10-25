"""Which Claude runs where: the orchestrator, the sub-agents it delegates to, and what they cost.

Defaults come from the environment and can be changed at runtime through POST /api/settings
(the settings control in the dashboard), including `llm_provider`: the API key, the local Claude
Code subscription or auto (`provider.py`). Never holds or logs a key.
"""

from __future__ import annotations

import os

from pai_agent.env import load_env

MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MODEL_LABELS = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5", "claude-haiku-5-5": "Haiku 5.5", "claude-fable-5-1": "Fable 5.1"}
# USD per million tokens: input, output, cache read, cache write (5 minutes).
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5),
}

_overrides: dict = {}


def _env(name: str, default: str) -> str:
    load_env()
    return os.environ.get(name, "").strip() or default


def current() -> dict:
    values = {
        "orchestrator_model": _env("PAI_ORCHESTRATOR_MODEL", _env("ANTHROPIC_MODEL", "claude-opus-5-5")),
        "orchestrator_effort": _env("PAI_ORCHESTRATOR_EFFORT", "high"),
        "subagent_model": _env("PAI_SUBAGENT_MODEL", "claude-sonnet-5-5"),
        "subagent_effort": _env("PAI_SUBAGENT_EFFORT", "medium"),
        "delegation": _env("PAI_DELEGATION", "1").lower() not in {"0", "false", "no", "off"},
    }
    values.update(_overrides)
    return values


def update(body: dict) -> dict:
    """Validates and applies a partial change. Raises ValueError with the allowed values."""

    changes = {}
    for key in ("orchestrator_model", "subagent_model"):
        if key in body:
            value = str(body[key]).strip()
            if not value.startswith("claude-"):
                raise ValueError(key + " must be a Claude model id such as " + ", ".join(MODELS) + ".")
            changes[key] = value
    for key in ("orchestrator_effort", "subagent_effort"):
        if key in body:
            value = str(body[key]).strip().lower()
            if value not in EFFORTS:
                raise ValueError(key + " must be one of " + ", ".join(EFFORTS) + ".")
            changes[key] = value
    if "delegation" in body:
        changes["delegation"] = bool(body["delegation"])
    if "llm_provider" in body:
        from pai_agent import provider

        provider.choose(body["llm_provider"])
        provider.subscription_status(refresh=True)
    _overrides.update(changes)
    return public()


def public() -> dict:
    from pai_agent import provider

    return {
        **current(),
        "models": [{"id": m, "label": MODEL_LABELS[m]} for m in MODELS],
        "efforts": list(EFFORTS),
        "llm_provider": provider.requested(),
        "provider": provider.describe(),
        "providers": [
            {"id": "auto", "label": "Auto"},
            {"id": "api", "label": "API key"},
            {"id": "subscription", "label": "My Claude subscription (local)"},
        ],
    }


def label(model: str) -> str:
    return MODEL_LABELS.get(model, model)


def usage_of(response) -> dict:
    usage = getattr(response, "usage", None)
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "cache_read_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        "cache_write_tokens": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
    }


def add_usage(total: dict, more: dict) -> dict:
    for key, value in more.items():
        total[key] = total.get(key, 0) + value
    return total


def cost_usd(model: str, usage: dict) -> float:
    price = PRICES.get(model, PRICES["claude-opus-5-5"])
    return round(
        (
            usage.get("input_tokens", 0) * price[0]
            + usage.get("output_tokens", 0) * price[1]
            + usage.get("cache_read_tokens", 0) * price[2]
            + usage.get("cache_write_tokens", 0) * price[3]
        )
        / 1_000_000,
        5,
    )
