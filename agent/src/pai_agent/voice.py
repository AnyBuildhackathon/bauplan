"""Voice for the side chat: Reson8 listens, Bolzen speaks.

Reson8 (https://docs.reson8.dev) is realtime speech-to-text over a WebSocket. The
browser never sees the API key: it asks this backend for a short-lived token from
POST /v1/auth/token and opens wss://api.reson8.dev/v1/speech-to-text/realtime with
the subprotocols ["bearer", token]. Without RESON8_API_KEY the browser uses its own
speech recognition. Bolzen speaks through the browser's speech synthesis, or through
ElevenLabs when ELEVENLABS_API_KEY is set. Key values are never logged or returned.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

RESON8_TOKEN_URL = "https://api.reson8.dev/v1/auth/token"
RESON8_REALTIME_URL = "wss://api.reson8.dev/v1/speech-to-text/realtime"
_ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128"
# A stock ElevenLabs voice; eleven_multilingual_v2 speaks German with it.
_DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"


class VoiceError(Exception):
    pass


def _key(name: str) -> str:
    return os.environ.get(name, "").strip()


def capabilities() -> dict:
    return {
        "stt": "reson8" if _key("RESON8_API_KEY") else "browser",
        "tts": "elevenlabs" if _key("ELEVENLABS_API_KEY") else "browser",
        "realtime_url": RESON8_REALTIME_URL,
        "language": os.environ.get("RESON8_LANGUAGE", "").strip() or "de",
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
        raise VoiceError("RESON8_API_KEY fehlt")
    raw = await asyncio.to_thread(_post, RESON8_TOKEN_URL, {"Authorization": "ApiKey " + key}, None, 10)
    body = json.loads(raw)
    token = body.get("access_token")
    if not token:
        raise VoiceError("Reson8 hat kein Token geschickt")
    return {"access_token": token, "expires_in": int(body.get("expires_in") or 600)}


async def elevenlabs_speech(text: str) -> bytes:
    key = _key("ELEVENLABS_API_KEY")
    if not key:
        raise VoiceError("ELEVENLABS_API_KEY fehlt")
    voice = _key("ELEVENLABS_VOICE_ID") or _DEFAULT_VOICE
    payload = json.dumps({"text": text[:600], "model_id": _key("ELEVENLABS_MODEL") or "eleven_multilingual_v2"}).encode("utf-8")
    headers = {"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    return await asyncio.to_thread(_post, _ELEVEN_URL.format(voice=voice), headers, payload, 20)
