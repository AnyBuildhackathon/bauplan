"""Listening in the side chat: Reson8 speech-to-text.

Reson8 (https://docs.reson8.dev) is speech-to-text over a WebSocket. The browser never
sees the API key: it asks this backend for a short-lived token from POST /v1/auth/token
and opens a Reson8 socket with the subprotocols ["bearer", token]. Hands-free, that is
the Turns endpoint, which says when a turn starts (barge-in) and when it has ended (send
it); push-to-talk keeps the Realtime endpoint. Without RESON8_API_KEY the browser uses its
own speech recognition. Mechanic's only spoken voice is Gemini Live (gemini_live.py);
without it he stays silent and his text is the caption.
Key values are never logged or returned.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request


RESON8_TOKEN_URL = "https://api.reson8.dev/v1/auth/token"
RESON8_REALTIME_URL = "wss://api.reson8.dev/v1/speech-to-text/realtime"
RESON8_TURNS_URL = "wss://api.reson8.dev/v1/speech-to-text/turns"
# Words the base model gets wrong in our meetings: part names, tools and the mascot.
PHRASES = [
    "Mechanic",
    "AnyBuild",
    "Twiglet",
    "Caddx",
    "1102",
    "1103",
    "KV",
    "Gemfan",
    "BetaFPV",
    "Lava 1S",
    "FunFly 4S",
    "Tattu",
    "LiHV",
    "ELRS",
    "MuJoCo",
    "Isaac Sim",
    "Isaac Lab",
    "Omniverse",
    "FreeCAD",
    "CadQuery",
    "Blender",
    "Jamie",
    "Reson8",
    "thrust-to-weight",
]

class VoiceError(Exception):
    pass


def _key(name: str) -> str:
    return os.environ.get(name, "").strip()


def capabilities() -> dict:
    from pai_agent.gemini_live import available

    return {
        "gemini_live": available(),
        "stt": "reson8" if _key("RESON8_API_KEY") else "browser",
        "realtime_url": RESON8_REALTIME_URL,
        "turns_url": RESON8_TURNS_URL,
        "language": os.environ.get("RESON8_LANGUAGE", "").strip() or "en",
        "phrases": PHRASES,
        "custom_model_id": _key("RESON8_CUSTOM_MODEL_ID") or None,
    }


def _post(url: str, headers: dict, body: bytes | None, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body if body is not None else b"", headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise VoiceError("HTTP " + str(exc.code)) from exc


async def reson8_token() -> dict:
    key = _key("RESON8_API_KEY")
    if not key:
        raise VoiceError("RESON8_API_KEY is missing")
    raw = await asyncio.to_thread(_post, RESON8_TOKEN_URL, {"Authorization": "ApiKey " + key}, None, 10)
    body = json.loads(raw)
    token = body.get("access_token")
    if not token:
        raise VoiceError("Reson8 did not send a token")
    return {"access_token": token, "expires_in": int(body.get("expires_in") or 600)}
