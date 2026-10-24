"""Which fast Claude model writes Mechanic's short texts (the lesson explanations).

Mechanic's spoken voice is Gemini Live only (gemini_live.py); nothing here speaks.
"""

from __future__ import annotations

import os


def voice_model() -> str:
    return os.environ.get("ANTHROPIC_VOICE_MODEL", "").strip() or "claude-haiku-5-5"


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
