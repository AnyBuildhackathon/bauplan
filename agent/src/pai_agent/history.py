"""Chat history: every conversation is saved in its session directory, so an old chat can be reopened.

A saved chat is three files next to the session's CAD and render files: `chat.json` (title, times,
product, counts), `events.json` (the event log the bench replays) and `state.pkl` (the build state
and Claude's message history, so the reopened chat can go on building). The files the events point
to (`/files/<session>/...`) stay in the same directory, so a reopened chat shows its product again.
"""

from __future__ import annotations

import json
import os
import pickle
import time
from dataclasses import fields
from pathlib import Path

from pai_agent.paths import SESSIONS_DIR
from pai_agent.state import BuildState

META = "chat.json"
EVENTS = "events.json"
STATE = "state.pkl"
TITLE_MAX = 60
LIST_MAX = 100


def _first_user_text(events: list[dict]) -> str:
    for ev in events:
        if ev.get("type") == "chat" and ev.get("role") == "user" and str(ev.get("text") or "").strip():
            return " ".join(str(ev["text"]).split())
    return ""


def _product_label(events: list[dict]) -> str:
    label = ""
    for ev in events:
        if ev.get("type") == "product" and ev.get("label"):
            label = str(ev["label"])
    return label


def worth_saving(events: list[dict]) -> bool:
    """A chat someone started: a user message or a version. The empty bench after a reset is not one."""

    return any((ev.get("type") == "chat" and ev.get("role") == "user") or ev.get("type") == "version" for ev in events)


def title_of(events: list[dict], state: BuildState) -> str:
    text = _first_user_text(events)
    if not text:
        meeting = next((ev for ev in events if ev.get("type") == "meeting" and ev.get("status") == "done"), None)
        text = str((meeting or {}).get("title") or "") or _product_label(events) or "Untitled build"
    return text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1].rstrip() + "…"


def save(state: BuildState, events: list[dict], messages: list[dict], created_at: float) -> dict | None:
    """Writes the chat of `state`'s session; returns its list entry, or None when nothing was started."""

    if not worth_saving(events):
        return None
    directory = Path(state.directory)
    directory.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": state.session_id,
        "title": title_of(events, state),
        "product": _product_label(events) or ("Drone" if state.product == "drone" and state.versions else ""),
        "created_at": int(created_at),
        "updated_at": int(time.time()),
        "messages": sum(1 for ev in events if ev.get("type") == "chat"),
        "versions": len(state.versions),
    }
    _write(directory / EVENTS, json.dumps(events, ensure_ascii=False, default=str).encode("utf-8"))
    _write(directory / STATE, pickle.dumps({"state": state, "messages": messages}))
    _write(directory / META, json.dumps(meta, ensure_ascii=False).encode("utf-8"))
    return meta


def _write(path: Path, data: bytes) -> None:
    # Write then rename, so a crash mid-save never leaves a half chat behind.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _session_dir(chat_id: str) -> Path | None:
    if not chat_id.isalnum() or len(chat_id) > 32:
        return None
    directory = SESSIONS_DIR / chat_id
    return directory if (directory / META).is_file() else None


def list_chats() -> list[dict]:
    """Saved chats, newest first."""

    rows = []
    if not SESSIONS_DIR.is_dir():
        return rows
    for path in SESSIONS_DIR.glob("*/" + META):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    rows.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
    return rows[:LIST_MAX]


def transcript(chat_id: str) -> dict | None:
    """One saved chat with its chat lines, for reading without opening it on the bench."""

    directory = _session_dir(chat_id)
    if directory is None:
        return None
    try:
        meta = json.loads((directory / META).read_text(encoding="utf-8"))
        events = json.loads((directory / EVENTS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    lines = [{"role": ev["role"], "text": ev.get("text", "")} for ev in events if ev.get("type") == "chat" and ev.get("role") in ("user", "agent")]
    return {**meta, "chat": lines}


def load(chat_id: str) -> tuple[BuildState, list[dict], list[dict], float] | None:
    """(state, messages, events, created_at) of a saved chat, or None when it is missing or unreadable."""

    directory = _session_dir(chat_id)
    if directory is None:
        return None
    try:
        meta = json.loads((directory / META).read_text(encoding="utf-8"))
        events = json.loads((directory / EVENTS).read_text(encoding="utf-8"))
        saved = pickle.loads((directory / STATE).read_bytes())
    except (OSError, ValueError, pickle.UnpicklingError, AttributeError, EOFError):
        return None
    # Fields added to BuildState after the chat was saved get their defaults.
    state = BuildState(session_id=chat_id, directory=directory)
    known = {f.name for f in fields(BuildState)}
    for name, value in vars(saved["state"]).items():
        if name in known:
            setattr(state, name, value)
    state.session_id = chat_id
    state.directory = directory
    return state, list(saved.get("messages") or []), [_settled(ev) for ev in events], float(meta.get("created_at") or time.time())


def _settled(ev: dict) -> dict:
    """A chat saved mid-run can hold an open question or a running step; reopened, nothing waits on them."""

    if ev.get("type") == "question" and ev.get("status") == "open":
        return {**ev, "status": "answered", "answer_id": ev.get("default_id")}
    return ev
