"""Where Jamie calls go: the live MCP server when JAMIE_MCP_TOKEN is set, else local files.

Both backends answer the same methods with the same shapes, so the tools and the
dashboard cannot tell them apart except for the `live` flag. A live call that fails
falls back to the local path for that one call, so a stage demo never stops.

Live server: https://mcp.meetjamie.ai/mcp (Streamable HTTP, OAuth bearer token).
Tools used: list_meetings, get_meeting, get_meeting_transcript, search_meetings,
create_tasks, update_tasks, upsert_template, create_tag, add_tag_to_meetings.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from pai_agent.meetings import normalize, parse_transcript
from pai_agent.paths import MEETINGS_DIR

log = logging.getLogger(__name__)

_PROTOCOL = "2025-06-18"
_TIMEOUT_S = 5
# After a failed call the live server is skipped for this long, so a dead network costs one timeout, not one per call.
_COOLDOWN_S = 60


def endpoint() -> str:
    # Read on use, so a value from agent/.env (loaded at startup) counts.
    return os.environ.get("JAMIE_MCP_URL", "").strip() or "https://mcp.meetjamie.ai/mcp"


def token() -> str:
    return os.environ.get("JAMIE_MCP_TOKEN", "").strip()


def live_enabled() -> bool:
    return bool(token())


class JamieError(Exception):
    pass


class LocalJamie:
    """Sample meetings from agent/data/meetings and an outbox file per session."""

    live = False

    def __init__(self, outbox: Path) -> None:
        self.outbox = outbox

    def meetings(self) -> list[dict]:
        out = []
        for path in sorted(MEETINGS_DIR.glob("*.json")):
            out.append(normalize(json.loads(path.read_text(encoding="utf-8"))))
        return out

    def meeting(self, meeting_id: str) -> dict | None:
        return next((m for m in self.meetings() if m["id"] == meeting_id), None)

    def search(self, query: str) -> list[dict]:
        needle = query.lower()
        return [m for m in self.meetings() if needle in json.dumps(m, ensure_ascii=False).lower()]

    def write(self, tool: str, arguments: dict) -> dict:
        entries = []
        if self.outbox.is_file():
            entries = json.loads(self.outbox.read_text(encoding="utf-8")).get("calls", [])
        result: dict = {"ok": True}
        if tool == "create_tasks":
            result["ids"] = [f"local-{len(entries)}-{index}" for index, _ in enumerate(arguments.get("tasks", []))]
        entries.append({"tool": tool, "arguments": arguments, "at": time.strftime("%H:%M:%S"), "result": result})
        payload = {
            "mcp_endpoint": endpoint(),
            "delivered": False,
            "reason": "JAMIE_MCP_TOKEN ist leer, die Aufrufe liegen nur in dieser Datei.",
            "calls": entries,
        }
        self.outbox.parent.mkdir(parents=True, exist_ok=True)
        self.outbox.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result


class LiveJamie:
    """A small MCP client over Streamable HTTP. No SDK, one session per process."""

    live = True

    def __init__(self, local: LocalJamie) -> None:
        self.local = local
        self._session: str | None = None
        self._tools: dict[str, dict] | None = None
        self._next = 0
        self._down_until = 0.0

    # --- transport -------------------------------------------------------------

    def _post(self, payload: dict) -> dict | None:
        headers = {
            "Authorization": "Bearer " + token(),
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": _PROTOCOL,
        }
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        if time.monotonic() < self._down_until:
            raise JamieError("Jamie war eben nicht erreichbar, lokal weiter")
        request = urllib.request.Request(endpoint(), data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
                self._session = response.headers.get("Mcp-Session-Id", self._session)
                content_type = response.headers.get("Content-Type", "")
                text = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code >= 500 or exc.code in (401, 403):
                self._down_until = time.monotonic() + _COOLDOWN_S
            raise JamieError(f"HTTP {exc.code}") from exc
        except (OSError, TimeoutError) as exc:
            self._down_until = time.monotonic() + _COOLDOWN_S
            raise JamieError("Jamie nicht erreichbar: " + str(exc)) from exc
        if "id" not in payload:
            return None
        if "text/event-stream" in content_type:
            for line in text.splitlines():
                if line.startswith("data:"):
                    message = json.loads(line[5:].strip())
                    if message.get("id") == payload["id"]:
                        return message
            raise JamieError("keine Antwort im Stream")
        return json.loads(text) if text.strip() else None

    def _rpc(self, method: str, params: dict) -> dict:
        self._next += 1
        message = self._post({"jsonrpc": "2.0", "id": self._next, "method": method, "params": params}) or {}
        if "error" in message:
            raise JamieError(str(message["error"].get("message") or message["error"]))
        return message.get("result") or {}

    def _ensure(self) -> None:
        if self._tools is not None:
            return
        self._rpc(
            "initialize",
            {"protocolVersion": _PROTOCOL, "capabilities": {}, "clientInfo": {"name": "bauplan", "version": "0.1"}},
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        listed = self._rpc("tools/list", {})
        self._tools = {tool["name"]: tool for tool in listed.get("tools", [])}

    def call(self, name: str, wanted: dict) -> object:
        self._ensure()
        assert self._tools is not None
        if name not in self._tools:
            raise JamieError(name + " fehlt auf dem Jamie-Server")
        arguments = _fit(wanted, self._tools[name].get("inputSchema") or {})
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise JamieError(_text(result)[:200] or name + " fehlgeschlagen")
        return _payload(result)

    def has(self, name: str) -> bool:
        self._ensure()
        return bool(self._tools and name in self._tools)

    # --- the same methods as LocalJamie --------------------------------------------

    def meetings(self) -> list[dict]:
        found = self.call("list_meetings", {"limit": 20})
        return [_meeting(item) for item in _items(found)]

    def meeting(self, meeting_id: str) -> dict | None:
        raw = self.call("get_meeting", {"meeting_id": meeting_id})
        meeting = _meeting(raw if isinstance(raw, dict) else {"id": meeting_id, "transcript": str(raw)})
        if not meeting["utterances"]:
            transcript = self.call("get_meeting_transcript", {"meeting_id": meeting_id})
            text = transcript if isinstance(transcript, str) else json.dumps(transcript, ensure_ascii=False)
            if isinstance(transcript, dict):
                meeting["utterances"] = _segments(transcript) or parse_transcript(text)
            else:
                meeting["utterances"] = parse_transcript(text)
        meeting["id"] = meeting["id"] or meeting_id
        return meeting

    def search(self, query: str) -> list[dict]:
        return [_meeting(item) for item in _items(self.call("search_meetings", {"query": query}))]

    def write(self, tool: str, arguments: dict) -> dict:
        """Writes live; a failure raises and the caller logs the call to the local outbox instead."""

        if tool == "note":
            out = self._note(arguments)
        else:
            result = self.call(tool, arguments)
            out = {"ok": True, "live": True}
            if tool == "create_tasks":
                out["ids"] = [str(item.get("id")) for item in _items(result) if isinstance(item, dict) and item.get("id")]
        self.local.write(tool, {**arguments, "_delivered": True})
        return out

    def _note(self, arguments: dict) -> dict:
        # Jamie documents no note tool; when the server has one we use it, else the note becomes a task.
        for name in ("create_note", "add_note", "add_meeting_note"):
            if self.has(name):
                self.call(name, {"meeting_id": arguments["meeting_id"], "text": arguments["text"], "content": arguments["text"]})
                return {"ok": True, "live": True, "as": name}
        self.call(
            "create_tasks",
            {
                "meeting_id": arguments["meeting_id"],
                "tasks": [{"title": arguments["title"], "description": arguments["text"]}],
            },
        )
        return {"ok": True, "live": True, "as": "create_tasks"}


def backend(outbox: Path) -> LocalJamie | LiveJamie:
    local = LocalJamie(outbox)
    return LiveJamie(local) if live_enabled() else local


# --- schema fitting and result shapes --------------------------------------------

_ALIASES = {
    "meeting_id": ("meeting_id", "meetingId", "id", "meeting"),
    "meeting_ids": ("meeting_ids", "meetingIds", "meetings", "ids"),
    "query": ("query", "q", "search", "text"),
    "limit": ("limit", "page_size", "pageSize", "max_results"),
    "tasks": ("tasks", "items"),
    "task_ids": ("task_ids", "taskIds", "ids"),
    "tag": ("tag", "tag_id", "tagId", "name", "tag_name"),
    "name": ("name", "title"),
    "description": ("description", "instructions", "prompt"),
    "sections": ("sections", "fields", "content"),
    "title": ("title", "name"),
    "assignee": ("assignee", "assignee_name", "owner"),
    "due_date": ("due_date", "dueDate", "due"),
    "done": ("done", "completed", "is_completed"),
    "status": ("status",),
    "color": ("color",),
    "text": ("text", "content", "body", "note"),
    "content": ("content",),
}


def _fit(wanted: dict, schema: dict) -> dict:
    """Renames our argument names to whatever the server's input schema calls them."""

    properties = schema.get("properties") or {}
    if not properties:
        return dict(wanted)
    out = {}
    for key, value in wanted.items():
        target = next((name for name in _ALIASES.get(key, (key,)) if name in properties), None)
        if target is None or target in out:
            continue
        item_schema = (properties[target].get("items") or {}) if isinstance(properties[target], dict) else {}
        if isinstance(value, list) and value and isinstance(value[0], dict) and item_schema.get("properties"):
            value = [_fit(entry, item_schema) for entry in value]
        out[target] = value
    return out


def _text(result: dict) -> str:
    return "\n".join(str(part.get("text", "")) for part in result.get("content", []) if isinstance(part, dict))


def _payload(result: dict) -> object:
    if "structuredContent" in result:
        return result["structuredContent"]
    text = _text(result)
    try:
        return json.loads(text)
    except ValueError:
        return text


def _items(found: object) -> list:
    if isinstance(found, list):
        return found
    if isinstance(found, dict):
        for key in ("meetings", "results", "items", "data", "tasks"):
            if isinstance(found.get(key), list):
                return found[key]
        return [found]
    return []


def _segments(raw: dict) -> list[dict]:
    segments = raw.get("transcript") or raw.get("segments") or raw.get("utterances")
    if not isinstance(segments, list):
        return []
    out = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = segment.get("text") or segment.get("content")
        if not text:
            continue
        stamp = str(segment.get("time") or segment.get("timestamp") or segment.get("start") or "")
        out.append(
            {
                "speaker": str(segment.get("speaker") or segment.get("speaker_name") or "Jemand"),
                "time": stamp[11:16] if "T" in stamp else stamp[:5],
                "text": str(text),
                "about": [],
                "tone": None,
            }
        )
    return out


def _meeting(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return normalize({"transcript": str(raw)})
    started = str(raw.get("start_time") or raw.get("started_at") or raw.get("date") or raw.get("created_at") or "")
    meeting = normalize(
        {
            "id": raw.get("id") or raw.get("meeting_id"),
            "title": raw.get("title") or raw.get("name"),
            "kind": "review" if "review" in str(raw.get("title") or "").lower() else "kickoff",
            "date": started[:10],
            "time": started[11:16] if "T" in started else "",
            "utterances": _segments(raw),
        }
    )
    if not meeting["utterances"] and isinstance(raw.get("transcript"), str):
        meeting["utterances"] = parse_transcript(raw["transcript"])
    return meeting
