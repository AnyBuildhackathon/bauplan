"""Pre-renders Mechanic's spoken lines of the recorded demo with ElevenLabs.

The static demo has no backend to stream speech from, so every line the live app would say
(the mascot's speech bubble, the last sentence of a question) becomes an mp3 under
web/public/demo/voice/, named after a hash of voice, model and text, and the recording
event gets a `voice` URL. The voice and model are the live loop's (`DEFAULT_VOICE`,
`DEFAULT_TTS_MODEL` in pai_agent/voice.py), so the demo sounds like the app.

Clips are cached by that hash: rerunning the recorder reuses them, and without
ELEVENLABS_API_KEY it still attaches every clip that already exists and says which lines
have none (those stay silent in the demo, and the text is the caption).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path

from pai_agent.voice import DEFAULT_TTS_MODEL, DEFAULT_VOICE, VoiceError, _key, _post

OUT_VOICE = Path(__file__).resolve().parents[2] / "web" / "public" / "demo" / "voice"
URL_PREFIX = "/demo/voice/"
_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_64"


def _voice_and_model() -> tuple[str, str]:
    return _key("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE, _key("ELEVENLABS_MODEL") or DEFAULT_TTS_MODEL


def last_sentence(text: str) -> str:
    """The part of a question worth saying out loud; the same cut as web/src/lib/bolzenVoice.ts."""

    parts = re.split(r"\n|(?<=[.?!“])\s+", text)
    return parts[-1] if parts else text


def spoken_text(event: dict) -> str:
    """What the dashboard reads aloud for this event, or an empty string."""

    if event.get("type") == "mascot" and event.get("say"):
        return event["say"].replace("**", "").strip()
    if event.get("type") == "question" and event.get("status") == "open":
        return last_sentence(event["text"]).replace("**", "").strip()
    return ""


def _clip_name(text: str) -> str:
    voice, model = _voice_and_model()
    return hashlib.sha1(f"{voice}|{model}|{text}".encode()).hexdigest()[:12] + ".mp3"


async def _render(text: str) -> bytes:
    key = _key("ELEVENLABS_API_KEY")
    voice, model = _voice_and_model()
    body = json.dumps({"text": text, "model_id": model}).encode()
    headers = {"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    return await asyncio.to_thread(_post, _URL.format(voice=voice), headers, body, 60)


async def attach_voice(events: list[dict]) -> None:
    """Adds `voice` to every spoken event and prunes clips the recording no longer uses."""

    OUT_VOICE.mkdir(parents=True, exist_ok=True)
    answered = {e["id"] for e in events if e.get("type") == "question" and e.get("status") == "answered"}
    used: set[str] = set()
    missing: list[str] = []
    for event in events:
        text = spoken_text(event)
        if not text:
            continue
        name = _clip_name(text)
        path = OUT_VOICE / name
        if not path.is_file() and _key("ELEVENLABS_API_KEY"):
            try:
                path.write_bytes(await _render(text))
            except VoiceError as exc:
                print("voice: ElevenLabs refused", repr(text), "-", exc)
        if path.is_file():
            event["voice"] = URL_PREFIX + name
            used.add(name)
        else:
            missing.append(text)
    # The answered copy of a question only repeats the clip of its open copy.
    clips = {e["id"]: e["voice"] for e in events if e.get("type") == "question" and "voice" in e}
    for event in events:
        if event.get("type") == "question" and event["id"] in answered and event["id"] in clips:
            event.setdefault("voice", clips[event["id"]])
    for old in OUT_VOICE.glob("*.mp3"):
        if old.name not in used:
            old.unlink()
    size = sum((OUT_VOICE / n).stat().st_size for n in used)
    print(f"voice: {len(used)} clips, {size // 1024} KiB in {OUT_VOICE.parent.parent.parent.name}/public/demo/voice")
    for text in missing:
        print("voice: no clip for", repr(text), "(set ELEVENLABS_API_KEY and record again)")
