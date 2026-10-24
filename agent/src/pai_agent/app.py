"""HTTP surface. Event shapes live in docs/events.md."""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from pai_agent.env import claude_enabled, load_env
from pai_agent.paths import FALLBACK_DIR, REPO_ROOT, SESSIONS_DIR
from pai_agent.session import Session
from pai_agent.tools.browser_train import router as browser_train_router
from pai_agent.tools.stress import router as stress_router


class PromptIn(BaseModel):
    text: str


class AnswerIn(BaseModel):
    id: str
    answer_id: str


class TaskIn(BaseModel):
    done: bool


class SpeakIn(BaseModel):
    text: str
    # The sentence spoken just before, so one reply keeps a continuous intonation.
    previous_text: str = ""


@asynccontextmanager
async def _lifespan(app: FastAPI):
    load_env()
    session = Session()
    app.state.session = session
    await session.bootstrap()
    from pai_agent import warm

    if warm.enabled():
        app.state.warm = asyncio.create_task(asyncio.to_thread(warm.warm))
    yield
    await session.shutdown()


app = FastAPI(title="Physical AI Agent", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    # The dashboard and the Mac app run on localhost, on whatever port Vite or Tauri picked.
    allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|tauri://localhost)$",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(browser_train_router)
app.include_router(stress_router)


@app.get("/api/health")
async def health(request: Request) -> dict:
    # busy tells tests and the profiler when a run has finished.
    return {"ok": True, "mode": "claude" if claude_enabled() else "mock", "busy": request.app.state.session._busy()}


@app.post("/api/prompt")
async def prompt(body: PromptIn, request: Request) -> dict:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    return await request.app.state.session.start(text)


@app.post("/api/reset")
async def reset(request: Request) -> dict:
    _require_json(request)
    await request.app.state.session.reset()
    return {"ok": True}


@app.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    session = request.app.state.session

    async def generate():
        async for event in session.bus.stream():
            if await request.is_disconnected():
                break
            if event is None:
                yield ": keepalive\n\n"
                continue
            yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/voice")
async def voice() -> dict:
    from pai_agent.voice import capabilities

    return capabilities()


@app.post("/api/voice/token")
async def voice_token() -> dict:
    from pai_agent.voice import VoiceError, reson8_token

    try:
        return await reson8_token()
    except VoiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Reson8 is unreachable") from exc


@app.post("/api/voice/warm")
async def voice_warm(request: Request) -> dict:
    await request.app.state.session.voice.warm()
    return {"ok": True}


@app.post("/api/voice/speak")
async def voice_speak(body: SpeakIn) -> StreamingResponse:
    from pai_agent.voice import TTS_SAMPLE_RATE, VoiceError, elevenlabs_stream

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        chunks = await elevenlabs_stream(text, body.previous_text.strip())
    except VoiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="ElevenLabs is unreachable") from exc
    return StreamingResponse(
        chunks,
        media_type="audio/pcm",
        headers={"X-Sample-Rate": str(TTS_SAMPLE_RATE), "Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/artifacts/frame.stl")
async def frame_stl(request: Request) -> FileResponse:
    state = request.app.state.session.state
    if not state.stl_path:
        raise HTTPException(status_code=404)
    path = (REPO_ROOT / state.stl_path).resolve()
    if not _under(path, SESSIONS_DIR) or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="model/stl", filename="frame.stl")


@app.get("/api/artifacts/fallback-training.mp4")
async def fallback_video() -> FileResponse:
    path = FALLBACK_DIR / "hover.mp4"
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="video/mp4", filename="hover.mp4")


@app.get("/api/artifacts/training.mp4")
async def training_video(request: Request) -> FileResponse:
    state = request.app.state.session.state
    if not state.training_video:
        raise HTTPException(status_code=404)
    path = Path(state.training_video).resolve()
    if not _under(path, SESSIONS_DIR) or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="video/mp4", filename="training.mp4")


_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def _require_json(request: Request) -> None:
    """State-changing calls must say application/json, so a web page cannot fire them as a plain cross-site form post."""

    if "application/json" not in request.headers.get("content-type", "").lower():
        raise HTTPException(status_code=415, detail="Content-Type application/json required")


def _check_webhook_secret(request: Request) -> None:
    """With JAMIE_WEBHOOK_SECRET set, the webhook needs it in X-Jamie-Secret or ?secret=, for tunnels to this port."""

    import hmac

    secret = os.environ.get("JAMIE_WEBHOOK_SECRET", "").strip()
    if not secret:
        return
    given = request.headers.get("x-jamie-secret") or request.query_params.get("secret") or ""
    if not hmac.compare_digest(given.encode("utf-8"), secret.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Webhook secret fehlt oder stimmt nicht")


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _meeting_event(body: dict) -> str:
    raw = str(body.get("event") or body.get("type") or "")
    folded = raw.strip().lower().replace("_", " ").replace(".", " ")
    return " ".join(folded.split())


def _media(name: str) -> str:
    return {
        ".stl": "model/stl",
        ".step": "model/step",
        ".stp": "model/step",
        ".glb": "model/gltf-binary",
        ".png": "image/png",
        ".mp4": "video/mp4",
        ".json": "application/json",
        ".zip": "application/zip",
        ".fcstd": "application/octet-stream",
        ".py": "text/plain; charset=utf-8",
    }.get(Path(name).suffix.lower(), "application/octet-stream")


@app.post("/api/webhooks/jamie")
async def jamie_webhook(request: Request) -> dict:
    _check_webhook_secret(request)
    _require_json(request)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="JSON object required") from exc
    if not isinstance(body, dict):
        return {"ok": True, "status": "ignored"}
    event = _meeting_event(body)
    meeting = body.get("meeting") if isinstance(body.get("meeting"), dict) else {}
    meeting_id = str(body.get("meeting_id") or meeting.get("id") or "")
    title = str(body.get("title") or meeting.get("title") or "")
    session = request.app.state.session
    if event == "meeting started":
        return await session.meeting_started(meeting_id, title)
    if event != "meeting ended":
        return {"ok": True, "status": "ignored"}
    result = await session.start_from_meeting(meeting_id, title)
    return {"ok": True, "trigger": "webhook", **result}


@app.post("/api/answer")
async def answer(body: AnswerIn, request: Request) -> dict:
    if not await request.app.state.session.answer(body.id, body.answer_id):
        raise HTTPException(status_code=409, detail="Keine offene Frage mit dieser Antwort.")
    return {"ok": True}


@app.post("/api/tasks/{task_id}")
async def task_done(task_id: str, body: TaskIn, request: Request) -> dict:
    result = await request.app.state.session.toggle_task(task_id, body.done)
    if result.get("ok") is False:
        raise HTTPException(status_code=404, detail=str(result.get("error")))
    return {"ok": True}


@app.post("/api/cad/params")
async def cad_params(request: Request) -> dict:
    _require_json(request)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="JSON object required") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    result = await request.app.state.session.update_params(body)
    if result.get("ok") is False:
        raise HTTPException(status_code=409 if result.get("busy") else 400, detail=str(result.get("error") or "bad params"))
    return {"ok": True, "source": result.get("source"), "mass_g": result.get("mass_g")}


class LibraryIn(BaseModel):
    id: str | None = None
    name: str | None = None
    summary: str = ""


@app.get("/api/library")
async def library() -> dict:
    from pai_agent.references import list_references

    return {"ok": True, "items": list_references()}


@app.post("/api/library/{item_id}/open")
async def library_open(item_id: str, request: Request) -> dict:
    _require_json(request)
    from pai_agent.references import list_references

    if item_id not in {row["id"] for row in list_references()}:
        raise HTTPException(status_code=404, detail="unknown library item")
    return await request.app.state.session.start_reference(item_id)


@app.get("/api/library/{item_id}/thumbnail")
async def library_thumbnail(item_id: str) -> FileResponse:
    from pai_agent.references import thumbnail_of

    path = thumbnail_of(item_id)
    if path is None:
        raise HTTPException(status_code=404, detail="no thumbnail")
    return FileResponse(path, media_type="image/png")


@app.post("/api/library")
async def library_save(body: LibraryIn, request: Request) -> dict:
    _require_json(request)
    result = request.app.state.session.save_reference(body.id, body.name, body.summary)
    if result.get("ok") is False:
        raise HTTPException(status_code=409 if result.get("busy") else 400, detail=str(result["error"]))
    return result


@app.get("/api/settings")
async def settings_get() -> dict:
    from pai_agent import settings

    return {"ok": True, **settings.public()}


@app.post("/api/settings")
async def settings_post(request: Request) -> dict:
    _require_json(request)
    from pai_agent import settings

    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        return {"ok": True, **settings.update(body)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/cad/open")
async def cad_open(request: Request) -> dict:
    _require_json(request)
    return await request.app.state.session.open_current()


@app.get("/files/{bucket}/{name}")
async def files(bucket: str, name: str) -> FileResponse:
    if not _FILE_NAME.fullmatch(bucket) or not _FILE_NAME.fullmatch(name):
        raise HTTPException(status_code=404)
    if bucket == "fallback":
        root = FALLBACK_DIR
        path = (root / name).resolve()
    else:
        root = SESSIONS_DIR
        path = (root / bucket / name).resolve()
    if not _under(path, root) or not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type=_media(name), filename=name)


def main() -> None:
    import logging

    import uvicorn

    load_env()
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("PORT", "8100"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
