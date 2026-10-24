"""Voice for the side chat: Reson8 listens, Mechanic speaks.

Reson8 (https://docs.reson8.dev) is speech-to-text over a WebSocket. The browser never
sees the API key: it asks this backend for a short-lived token from POST /v1/auth/token
and opens a Reson8 socket with the subprotocols ["bearer", token]. Hands-free, that is
the Turns endpoint, which says when a turn starts (barge-in) and when it has ended (send
it); push-to-talk keeps the Realtime endpoint. Without RESON8_API_KEY the browser uses its
own speech recognition. Mechanic speaks through ElevenLabs when ELEVENLABS_API_KEY is set,
streamed sentence by sentence as raw PCM, else he stays silent and his text is the caption
(never the system voice). The recorded demo plays pre-rendered ElevenLabs clips instead.
Key values are never logged or returned.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import AsyncIterator

log = logging.getLogger(__name__)

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

_ELEVEN_STREAM_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream"
# "Roger", a stock ElevenLabs voice: a confident, laid-back American male. Not a clone of anyone.
DEFAULT_VOICE = "CwhRBWXzGAHq8TQ4Fs17"
DEFAULT_TTS_MODEL = "eleven_flash_v2_5"
TTS_SAMPLE_RATE = 24000


class VoiceError(Exception):
    pass


_http = None


def _client():
    """One pooled client, so each sentence reuses the open TLS connection to ElevenLabs."""

    import httpx2 as httpx

    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5))
    return _http


async def warm_elevenlabs() -> None:
    """Opens the connection before the first sentence needs it. Errors do not matter here."""

    key = _key("ELEVENLABS_API_KEY")
    if not key:
        return
    try:
        await _client().get("https://api.elevenlabs.io/v1/models", headers={"xi-api-key": key})
    except Exception:
        log.info("ElevenLabs warm-up failed")


def _key(name: str) -> str:
    return os.environ.get(name, "").strip()


def capabilities() -> dict:
    return {
        "stt": "reson8" if _key("RESON8_API_KEY") else "browser",
        "tts": "elevenlabs" if _key("ELEVENLABS_API_KEY") else "none",
        "realtime_url": RESON8_REALTIME_URL,
        "turns_url": RESON8_TURNS_URL,
        "language": os.environ.get("RESON8_LANGUAGE", "").strip() or "en",
        "phrases": PHRASES,
        "custom_model_id": _key("RESON8_CUSTOM_MODEL_ID") or None,
        "tts_sample_rate": TTS_SAMPLE_RATE,
        # With a Claude key the backend writes Mechanic's spoken lines (`say` events).
        "narrator": bool(_key("ANTHROPIC_API_KEY")),
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


async def elevenlabs_stream(text: str, previous_text: str = "") -> AsyncIterator[bytes]:
    """Opens an ElevenLabs stream for one sentence and yields 16-bit mono PCM at TTS_SAMPLE_RATE.

    The request is sent before the first chunk is yielded, so a missing key or an HTTP error
    raises VoiceError while the caller can still answer with a status code.
    """

    import httpx2 as httpx

    key = _key("ELEVENLABS_API_KEY")
    if not key:
        raise VoiceError("ELEVENLABS_API_KEY is missing")
    voice = _key("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
    payload: dict = {"text": text[:600], "model_id": _key("ELEVENLABS_MODEL") or DEFAULT_TTS_MODEL}
    if previous_text:
        # The sentence before keeps the intonation of one reply continuous across requests.
        payload["previous_text"] = previous_text[-400:]
    client = _client()
    request = client.build_request(
        "POST",
        _ELEVEN_STREAM_URL.format(voice=voice),
        params={"output_format": "pcm_" + str(TTS_SAMPLE_RATE)},
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        json=payload,
    )
    try:
        response = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        raise VoiceError("ElevenLabs is unreachable") from exc
    if response.status_code != 200:
        await response.aclose()
        raise VoiceError("HTTP " + str(response.status_code))

    async def chunks() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()

    return chunks()
