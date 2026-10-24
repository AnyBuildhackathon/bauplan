"""Jamie as the backbone of a build.

Meetings drive every version: the kickoff gives the requirements, earlier meetings
give warnings about parts, a review changes requirements or complains about a part,
and each finished build is written back to its meeting as a note, tags and order tasks.
Calls go to the live Jamie MCP server only when JAMIE_MCP_TOKEN is set; otherwise
they land in the session's local outbox. The events look the same either way.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from pathlib import Path

from pai_agent.context import Ctx, de
from pai_agent.jamie_client import JamieError, LiveJamie, LocalJamie, backend, endpoint, live_enabled
from pai_agent.meetings import (
    LIMIT_KEY,
    complaints_from,
    conflicts,
    notes_about,
    requirements_from,
    short_date,
    week_before,
)
from pai_agent.requirements import emit_requirement, met_for
from pai_agent.state import BuildState
from pai_agent.tools.parts import catalog

log = logging.getLogger(__name__)

PROJECT_TAG = "drohne"
TEMPLATES = (
    {
        "name": "Hardware-Anforderungen",
        "description": "Bauplan liest daraus Budget, Flugzeit und Gewicht, jedes Feld mit dem Satz, aus dem es kommt.",
        "sections": ["Budget (max. €)", "Flugzeit (min. Minuten)", "Gewicht (max. g)", "Weitere Vorgaben", "Wer bestellt was"],
    },
    {
        "name": "Drohnen-Review",
        "description": "Was sich seit der letzten Version ändern soll. Bauplan baut danach neu und schreibt die Differenz zurück.",
        "sections": ["Neue Vorgaben", "Probleme mit Teilen", "Entscheidungen", "Nächste Schritte"],
    },
)
_CATEGORY_LABEL = {
    "motor": "Motor",
    "propeller": "Propeller",
    "battery": "Akku",
    "flight_controller": "Flugregler",
    "frame": "Rahmen",
}
_DEFAULT_OWNER = {"motor": "Lea", "flight_controller": "Lea", "battery": "Ben", "propeller": "Ben", "frame": "Ben"}

_clients: dict[str, LocalJamie | LiveJamie] = {}


def forget_client(session_id: str) -> None:
    _clients.pop(session_id, None)


def _client(state: BuildState) -> LocalJamie | LiveJamie:
    key = state.session_id
    if key not in _clients:
        _clients[key] = backend(Path(state.directory) / "jamie_outbox.json")
    return _clients[key]


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message}


async def _read(state: BuildState, method: str, *args) -> tuple[object, bool]:
    """Runs a read on the live server, or locally when there is no token or the call fails."""

    client = _client(state)
    if isinstance(client, LiveJamie):
        try:
            return await asyncio.to_thread(getattr(client, method), *args), True
        except (JamieError, OSError, ValueError) as exc:
            log.warning("Jamie live %s fiel aus: %s", method, exc)
        except Exception as exc:  # network errors and unexpected shapes
            log.warning("Jamie live %s fiel aus: %s", method, exc)
        client = client.local
    return await asyncio.to_thread(getattr(client, method), *args), False


async def _write(ctx: Ctx, tool: str, arguments: dict, detail: str) -> dict:
    client = _client(ctx.state)
    result: dict
    try:
        result = await asyncio.to_thread(client.write, tool, arguments)
    except Exception as exc:
        log.warning("Jamie live %s fiel aus: %s", tool, exc)
        local = client.local if isinstance(client, LiveJamie) else client
        result = await asyncio.to_thread(local.write, tool, arguments)
        detail += " · lokal, Jamie nicht erreichbar" if isinstance(client, LiveJamie) else " · lokale Outbox"
    else:
        if not client.live:
            detail += " · lokale Outbox"
    await ctx.emit({"type": "jamie", "action": tool, "status": "ok" if result.get("ok") else "error", "detail": detail})
    return result


# --- the meeting timeline -----------------------------------------------------------


def init_timeline(state: BuildState) -> None:
    """The kickoff is recorded, the reviews are still ahead. Archive meetings join when searched."""

    live = live_enabled()
    for meeting in LocalJamie(Path(state.directory) / "jamie_outbox.json").meetings():
        # With live Jamie the sample meetings only lend their timeline slots, never their sentences.
        if not live:
            state.meeting_cache[meeting["id"]] = meeting
        if meeting["kind"] == "archive":
            continue
        state.meetings[meeting["id"]] = {
            "id": meeting["id"],
            "title": meeting["title"],
            "kind": meeting["kind"],
            "date": meeting["date"],
            "time": meeting["time"],
            "status": "done" if meeting["kind"] == "kickoff" else "next",
            "version": None,
            "tags": [],
        }


def meeting_event(meta: dict) -> dict:
    event = {"type": "meeting", **{key: meta[key] for key in ("id", "title", "kind", "date", "time", "status", "version")}, "tags": list(meta["tags"])}
    if meta.get("replaces"):
        event["replaces"] = meta["replaces"]
    return event


async def emit_meeting(ctx: Ctx, meeting_id: str) -> None:
    meta = ctx.state.meetings.get(meeting_id)
    if meta:
        await ctx.emit(meeting_event(meta))


def resolve_meeting(state: BuildState, meeting_id: str, title: str) -> dict:
    """Finds the timeline slot for a webhook.

    A known id is that meeting. Without an id, the title picks the next slot of its kind.
    An unknown live id takes over the next slot of its kind; `replaces` tells the dashboard
    which station it stands in for.
    """

    if meeting_id in state.meetings:
        return state.meetings[meeting_id]
    kind = "review" if "review" in title.lower() else "kickoff"
    slots = sorted(
        (meta for meta in state.meetings.values() if meta["kind"] == kind and (kind == "kickoff" or meta["status"] != "done")),
        key=lambda meta: (meta["date"], meta["time"]),
    )
    slot = slots[0] if slots else None
    if not meeting_id and slot is not None:
        return slot
    meta = {
        "id": meeting_id or ("review-" if kind == "review" else "kickoff-") + date.today().isoformat(),
        "title": title or ("Review" if kind == "review" else "Kickoff"),
        "kind": kind,
        "date": date.today().isoformat(),
        "time": "",
        "status": "next",
        "version": None,
        "tags": [],
    }
    if slot is not None:
        state.meetings.pop(slot["id"], None)
        meta["date"], meta["time"] = slot["date"], slot["time"]
        meta["replaces"] = slot["id"]
    state.meetings[meta["id"]] = meta
    return meta


async def load_meeting(state: BuildState, meeting_id: str) -> dict | None:
    meeting, live = await _read(state, "meeting", meeting_id)
    if isinstance(meeting, dict) and not meeting.get("utterances"):
        meeting = None
    state.last_read_live = live and meeting is not None
    if meeting is None and live:
        meeting = await asyncio.to_thread(_client(state).local.meeting, meeting_id)  # type: ignore[union-attr]
    if meeting is None:
        meeting = state.meeting_cache.get(meeting_id)
    if meeting is None:
        meeting = _sample_for(state, meeting_id)
    if isinstance(meeting, dict):
        state.meeting_cache[meeting_id] = meeting
        meta = state.meetings.get(meeting_id)
        if meta and meeting.get("title") and meeting["title"] != "Meeting":
            meta["title"] = meeting["title"]
    return meeting if isinstance(meeting, dict) else None


def _sample_for(state: BuildState, meeting_id: str) -> dict | None:
    """A meeting Jamie cannot hand over (no token, or offline) is read from the sample of its kind."""

    meta = state.meetings.get(meeting_id)
    if meta is None:
        return None
    samples = LocalJamie(Path(state.directory) / "jamie_outbox.json").meetings()
    sample = next((m for m in samples if m["kind"] == meta["kind"] and m["utterances"]), None)
    if sample is None:
        return None
    log.warning("Meeting %s fehlt bei Jamie, nehme das Beispiel %s", meeting_id, sample["id"])
    return {**sample, "id": meeting_id}


def _known(state: BuildState) -> list[dict]:
    """Meetings that may hold sentences about parts: everything read so far, oldest first."""

    meetings = [m for m in state.meeting_cache.values() if not m.get("planned")]
    return sorted(meetings, key=lambda m: (m.get("date", ""), m.get("time", "")))


# --- tools -------------------------------------------------------------------------


async def jamie_templates(ctx: Ctx, args: dict) -> dict:
    del args
    if ctx.state.templates_ready:
        return {"ok": True, "detail": "Vorlagen stehen schon", "templates": [t["name"] for t in TEMPLATES]}
    for template in TEMPLATES:
        await _write(ctx, "upsert_template", dict(template), "Vorlage „" + template["name"] + "“")
    ctx.state.templates_ready = True
    return {"ok": True, "detail": "Vorlagen Hardware-Anforderungen und Drohnen-Review", "templates": [t["name"] for t in TEMPLATES]}


async def _find_kickoff(state: BuildState, meeting_id: str) -> dict | None:
    """The kickoff to build from; `state.last_read_live` says whether Jamie handed it over live."""
    if meeting_id:
        return await load_meeting(state, meeting_id)
    client = _client(state)
    if isinstance(client, LiveJamie):
        found, live = await _read(state, "search", "Kickoff")
        hits = [m for m in found if "kickoff" in m["title"].lower()] if live and isinstance(found, list) else []
        if hits:
            newest = sorted(hits, key=lambda m: (m["date"], m["time"]))[-1]
            meta = resolve_meeting(state, newest["id"], newest["title"])
            meta["status"] = "done"
            return await load_meeting(state, newest["id"])
    kickoff = next((meta for meta in state.meetings.values() if meta["kind"] == "kickoff"), None)
    return await load_meeting(state, kickoff["id"]) if kickoff else None


async def jamie_requirements(ctx: Ctx, args: dict) -> dict:
    meeting = await _find_kickoff(ctx.state, str(args.get("meeting_id") or ""))
    if meeting is None:
        return _fail("Kein Kickoff-Meeting gefunden.")
    live = ctx.state.last_read_live
    requirements, source = requirements_from(meeting)
    ctx.state.requirements = requirements
    for requirement in requirements:
        await emit_requirement(ctx, requirement, None)
    meta = ctx.state.meetings.get(meeting["id"])
    if meta:
        meta["status"] = "done"
        await emit_meeting(ctx, meeting["id"])
    detail = meeting["title"] + ", " + str(len(requirements)) + " Vorgaben"
    await ctx.emit({"type": "jamie", "action": "requirements", "status": "ok", "detail": detail})
    return {
        "ok": True,
        "detail": detail,
        "meeting_id": meeting["id"],
        "title": meeting["title"],
        "requirements": [
            {key: item.get(key) for key in ("id", "text", "source_quote", "speaker", "time")} for item in requirements
        ],
        "template": "Hardware-Anforderungen" if source == "template" else None,
        "requirements_source": source,
        "owners": meeting.get("owners") or _DEFAULT_OWNER,
        "mcp_endpoint": endpoint(),
        "live": live,
    }


async def jamie_search(ctx: Ctx, args: dict) -> dict:
    query = str(args.get("query", "")).strip()
    if not query:
        return _fail("query fehlt.")
    found, _live = await _read(ctx.state, "search", query)
    hits = []
    needle = query.lower()
    for meeting in found if isinstance(found, list) else []:
        ctx.state.meeting_cache.setdefault(meeting["id"], meeting)
        quotes = [
            {"speaker": u["speaker"], "time": u["time"], "text": u["text"]}
            for u in meeting["utterances"]
            if needle in u["text"].lower()
        ]
        hits.append({"id": meeting["id"], "title": meeting["title"], "date": meeting["date"], "quotes": quotes})
        if meeting["kind"] == "archive":
            await ctx.emit(
                {
                    "type": "meeting",
                    "id": meeting["id"],
                    "title": meeting["title"],
                    "kind": "archive",
                    "date": meeting["date"],
                    "time": meeting["time"],
                    "status": "done",
                    "version": None,
                    "tags": [],
                }
            )
    detail = str(len(hits)) + " Treffer für „" + query + "“"
    await ctx.emit({"type": "jamie", "action": "search", "status": "ok", "detail": detail})
    return {"ok": True, "detail": detail, "query": query, "meetings": hits}


def part_notes(state: BuildState, part: dict) -> list[dict]:
    return notes_about(part, _known(state))


async def _last_week_part(state: BuildState, meeting: dict, category: str) -> dict | None:
    """'Der Motor von letzter Woche': the part of that category named in a meeting 4 to 10 days earlier."""

    start, end = week_before(meeting.get("date", ""))
    candidates = [part for part in catalog()["parts"] if part["category"] == category]
    if isinstance(_client(state), LiveJamie):
        for part in candidates:
            found, live = await _read(state, "search", (part.get("aliases") or [part["name"]])[0])
            for hit in found if live and isinstance(found, list) else []:
                state.meeting_cache.setdefault(hit["id"], hit)
    for older in reversed(_known(state)):
        if not (start <= older.get("date", "") <= end):
            continue
        for part in candidates:
            notes = notes_about(part, [older])
            if notes:
                return {"part_id": part["id"], "name": part["name"], "quote": notes[0], "date": older["date"]}
    return None


async def jamie_meeting(ctx: Ctx, args: dict) -> dict:
    meeting_id = str(args.get("meeting_id") or "").strip()
    if not meeting_id:
        return _fail("meeting_id fehlt.")
    meeting = await load_meeting(ctx.state, meeting_id)
    if meeting is None:
        return _fail("Meeting " + meeting_id + " nicht gefunden.")
    incoming, _source = requirements_from(meeting)
    current = {item["id"]: item for item in ctx.state.requirements}
    changes = [
        {
            "id": item["id"],
            "text": item["text"],
            "before": current[item["id"]]["text"] if item["id"] in current else None,
            "quote": {"text": item["source_quote"], "speaker": item["speaker"], "time": item["time"]},
        }
        for item in incoming
        if item["id"] not in current or current[item["id"]]["text"] != item["text"]
    ]
    found_conflicts = conflicts(ctx.state.requirements, incoming)
    complaints = complaints_from(meeting)
    for complaint in complaints:
        if complaint["last_week"]:
            complaint["refers_to"] = await _last_week_part(ctx.state, meeting, complaint["category"])
    ctx.state.complaints = complaints
    meta = ctx.state.meetings.get(meeting["id"])
    if meta:
        meta["status"] = "done"
        await emit_meeting(ctx, meeting["id"])
    detail = (
        meeting["title"]
        + " · "
        + str(len(changes))
        + (" Änderung" if len(changes) == 1 else " Änderungen")
        + ", "
        + str(len(complaints))
        + (" Beschwerde" if len(complaints) == 1 else " Beschwerden")
    )
    await ctx.emit({"type": "jamie", "action": "get_meeting", "status": "ok", "detail": detail})
    return {
        "ok": True,
        "detail": detail,
        "meeting_id": meeting["id"],
        "title": meeting["title"],
        "date": meeting["date"],
        "changes": changes,
        "conflicts": [
            {
                "id": item["id"],
                "unit": {"flight_time": "Minuten", "budget": "€", "weight": "g"}.get(item["id"], ""),
                "old": {key: item["old"].get(key) for key in ("text", "source_quote", "speaker", "time", "meeting_title")}
                | {"limit": item["old"].get(LIMIT_KEY[item["id"]])},
                "new": {key: item["new"].get(key) for key in ("text", "source_quote", "speaker", "time", "meeting_title")}
                | {"limit": item["new"].get(LIMIT_KEY[item["id"]])},
            }
            for item in found_conflicts
        ],
        "complaints": complaints,
    }


async def requirements_accept(ctx: Ctx, args: dict) -> dict:
    meeting_id = str(args.get("meeting_id") or "").strip()
    meeting = await load_meeting(ctx.state, meeting_id) if meeting_id else None
    if meeting is None:
        return _fail("meeting_id fehlt oder ist unbekannt.")
    wanted = args.get("ids")
    incoming, _source = requirements_from(meeting)
    accepted = []
    for item in incoming:
        if isinstance(wanted, list) and item["id"] not in wanted:
            continue
        index = next((i for i, old in enumerate(ctx.state.requirements) if old["id"] == item["id"]), None)
        if index is None:
            ctx.state.requirements.append(item)
        else:
            old = ctx.state.requirements[index]
            if old["text"] == item["text"]:
                continue
            item["changed_from"] = old["text"]
            ctx.state.requirements[index] = item
        accepted.append(item["id"])
        await emit_requirement(ctx, item, met_for(ctx.state, item))
    detail = "Übernommen: " + (", ".join(accepted) if accepted else "nichts")
    return {"ok": True, "detail": detail, "accepted": accepted}


def _due(meeting: dict | None, days: int = 3) -> str:
    """ISO date a few days after the meeting; the dashboard shows it as 27.10."""

    try:
        anchor = date.fromisoformat((meeting or {}).get("date", ""))
    except ValueError:
        anchor = date.today()
    return (anchor + timedelta(days=days)).isoformat()


def _owners(state: BuildState) -> dict:
    for meeting in _known(state):
        if meeting.get("kind") == "kickoff" and meeting.get("owners"):
            return {**_DEFAULT_OWNER, **meeting["owners"]}
    return dict(_DEFAULT_OWNER)


def current_meeting_id(state: BuildState) -> str:
    done = [meta for meta in state.meetings.values() if meta["status"] == "done" and meta["kind"] != "archive"]
    done.sort(key=lambda meta: (meta["date"], meta["time"]))
    return done[-1]["id"] if done else ""


async def jamie_create_tasks(ctx: Ctx, args: dict) -> dict:
    if not ctx.state.bom:
        return _fail("Keine Stückliste. Erst bom_build aufrufen.")
    meeting_id = str(args.get("meeting_id") or current_meeting_id(ctx.state))
    meeting = ctx.state.meeting_cache.get(meeting_id)
    owners = _owners(ctx.state)
    keep = {task["part_id"]: task for task in ctx.state.tasks}
    tasks = []
    new = []
    for category in ("motor", "propeller", "battery", "flight_controller", "frame"):
        part = ctx.state.selected.get(category)
        if part is None:
            continue
        if part["id"] in keep:
            tasks.append(keep.pop(part["id"]))
            continue
        qty = int(part["bom_qty"])
        title = ("Drucken: " + part["name"]) if category == "frame" else ("Bestellen: " + part["name"] + (f" ({qty}×)" if qty > 1 else ""))
        task = {
            "id": f"t{len(ctx.state.tasks) + len(new) + 1}-{category}",
            "title": title,
            "assignee": owners.get(category, "Lea"),
            "due": _due(meeting),
            "done": False,
            "part_category": category,
            "part_id": part["id"],
            "meeting_id": meeting_id,
            "jamie_id": None,
        }
        tasks.append(task)
        new.append(task)
    dropped = list(keep.values())
    if new:
        result = await _write(
            ctx,
            "create_tasks",
            {
                "meeting_id": meeting_id,
                "tasks": [
                    {
                        "title": task["title"],
                        "description": task["title"] + ". Aus Bauplan, Preis ist eine Stichprobe.",
                        "assignee": task["assignee"],
                        "due_date": task["due"],
                    }
                    for task in new
                ],
            },
            str(len(new)) + (" Aufgabe" if len(new) == 1 else " Aufgaben") + " für " + ", ".join(sorted({t["assignee"] for t in new})),
        )
        for task, jamie_id in zip(new, result.get("ids") or []):
            task["jamie_id"] = jamie_id
    if dropped:
        await _write(
            ctx,
            "update_tasks",
            {"task_ids": [t["jamie_id"] or t["id"] for t in dropped], "done": True},
            str(len(dropped)) + " alte Aufgaben geschlossen",
        )
    ctx.state.tasks = tasks
    await emit_tasks(ctx)
    detail = str(len(new)) + " neue Aufgaben, " + str(len(tasks) - len(new)) + " bleiben"
    return {"ok": True, "detail": detail, "task_count": len(tasks), "new": len(new), "closed": len(dropped)}


async def emit_tasks(ctx: Ctx) -> None:
    await ctx.emit(
        {
            "type": "tasks",
            "meeting_id": current_meeting_id(ctx.state),
            "items": [
                {key: task[key] for key in ("id", "title", "assignee", "done", "part_category")} | {"due": short_date(task["due"])}
                for task in ctx.state.tasks
            ],
            # Live only when every task really sits in Jamie, not in the outbox after a fallback.
            "live": bool(ctx.state.tasks) and all(t["jamie_id"] and not str(t["jamie_id"]).startswith("local-") for t in ctx.state.tasks),
        }
    )


async def set_task_done(ctx: Ctx, task_id: str, done: bool) -> dict:
    task = next((t for t in ctx.state.tasks if t["id"] == task_id), None)
    if task is None:
        return _fail("Unbekannte Aufgabe.")
    task["done"] = done
    await _write(
        ctx,
        "update_tasks",
        {"task_ids": [task["jamie_id"] or task["id"]], "done": done},
        ("Bestellt: " if done else "Wieder offen: ") + task["title"].split(": ", 1)[-1],
    )
    await emit_tasks(ctx)
    return {"ok": True}


_DIFF_KEYS = (
    ("weight_g", "Gewicht", "g", 1),
    ("flight_time_min", "Flugzeit", "min", 1),
    ("price_eur", "Preis", "€", 2),
    ("thrust_to_weight", "Schub/Gewicht", ": 1", 2),
)


async def version_commit(ctx: Ctx, args: dict) -> dict:
    state = ctx.state
    if not state.metrics or not state.selected:
        return _fail("Noch keine gerechnete Drohne. Erst physics_calc.")
    meeting_id = str(args.get("meeting_id") or current_meeting_id(state))
    meta = state.meetings.get(meeting_id)
    title = meta["title"] if meta else "Meeting"
    previous = state.versions[-1] if state.versions else None
    n = len(state.versions) + 1
    parts = {category: part["name"] for category, part in state.selected.items()}
    diff = []
    if previous:
        for key, label, unit, _digits in _DIFF_KEYS:
            if previous[key] != state.metrics[key]:
                diff.append({"key": key, "label": label, "before": previous[key], "after": state.metrics[key], "unit": unit})
        for category, name in parts.items():
            before = previous["parts"].get(category)
            if before and before != name:
                diff.append({"key": "part:" + category, "label": _CATEGORY_LABEL[category], "before": before, "after": name, "unit": ""})
    summary = (
        de(state.metrics["weight_g"], 1)
        + " g · "
        + de(state.metrics["flight_time_min"], 1)
        + " min · "
        + de(state.metrics["price_eur"], 2)
        + " €"
    )
    version = {
        "n": n,
        "meeting_id": meeting_id,
        "meeting_title": title,
        "weight_g": state.metrics["weight_g"],
        "thrust_to_weight": state.metrics["thrust_to_weight"],
        "flight_time_min": state.metrics["flight_time_min"],
        "price_eur": state.metrics["price_eur"],
        "sim": state.last_sim["result"] if state.last_sim else None,
        "parts": parts,
        "diff": diff,
        "summary": summary,
    }

    lines = ["Bauplan v" + str(n) + " aus " + title + ": " + summary + "."]
    for item in diff:
        if item["unit"]:
            digits = next(d for k, _l, _u, d in _DIFF_KEYS if k == item["key"])
            lines.append(item["label"] + " " + de(item["before"], digits) + " → " + de(item["after"], digits) + " " + item["unit"])
        else:
            lines.append(item["label"] + ": " + item["before"] + " → " + item["after"])
    note = "\n".join(lines)
    version["note"] = note
    state.versions.append(version)
    await ctx.emit({"type": "version", **version})

    for tag in (PROJECT_TAG, f"{PROJECT_TAG}-v{n}"):
        if tag not in state.tags:
            await _write(ctx, "create_tag", {"name": tag}, "Tag " + tag)
            state.tags.add(tag)
        await _write(ctx, "add_tag_to_meetings", {"tag": tag, "meeting_ids": [meeting_id]}, tag + " an " + title)
        if meta and tag not in meta["tags"]:
            meta["tags"].append(tag)
    if meta:
        meta["version"] = n
        await emit_meeting(ctx, meeting_id)

    await _write(
        ctx,
        "note",
        {"meeting_id": meeting_id, "title": "Bauplan v" + str(n), "text": note},
        "Notiz an " + title + (": Differenz zu v" + str(n - 1) if previous else ""),
    )
    return {"ok": True, "detail": "Version " + str(n) + " · " + summary, "version": n, "diff": diff, "note": note}


def requirement_quote(state: BuildState, requirement_id: str) -> dict | None:
    item = next((r for r in state.requirements if r["id"] == requirement_id), None)
    if not item:
        return None
    return {
        "text": item["source_quote"],
        "speaker": item.get("speaker", ""),
        "time": item.get("time", ""),
        "meeting_id": item.get("meeting_id", ""),
        "meeting_title": item.get("meeting_title", ""),
    }


def limit_of(state: BuildState, requirement_id: str) -> float | None:
    item = next((r for r in state.requirements if r["id"] == requirement_id), None)
    key = LIMIT_KEY.get(requirement_id)
    return float(item[key]) if item and key and key in item else None


_DEFAULT_BECAUSE = {"battery": "flight_time", "frame": "printable", "flight_controller": "weight", "motor": "hover", "propeller": "hover"}


def _warnings(state: BuildState, part: dict) -> list[dict]:
    out = [
        {key: note[key] for key in ("text", "speaker", "time", "meeting_id", "meeting_title")} | {"note": short_date(note["date"])}
        for note in part_notes(state, part)
        if note["tone"] == "warning"
    ]
    for complaint in state.complaints:
        refers = complaint.get("refers_to") or {}
        if refers.get("part_id") == part["id"]:
            out.append(complaint["quote"] | {"note": "gemeint: " + _CATEGORY_LABEL[part["category"]] + " vom " + short_date(refers.get("date", ""))})
    return out


async def emit_part(ctx: Ctx, part: dict, because: str = "", reason: str = "", considered: bool = False) -> dict:
    """Announces a chosen part with the Jamie sentence behind it and warnings from earlier meetings."""

    state = ctx.state
    category = part["category"]
    warnings = _warnings(state, part)
    why = None
    if because == "complaint":
        complaint = next((c for c in state.complaints if c["category"] == category), None)
        why = complaint["quote"] if complaint else None
    elif because:
        why = requirement_quote(state, because)
    if why is None and not considered:
        good = [n for n in part_notes(state, part) if n["tone"] in {"praise", "fact"}]
        if good:
            why = {key: good[-1][key] for key in ("text", "speaker", "time", "meeting_id", "meeting_title")}
        else:
            why = requirement_quote(state, _DEFAULT_BECAUSE.get(category, "hover"))
    event = {
        "type": "part",
        "category": category,
        "id": part["id"],
        "name": part["name"],
        "why": why,
        "reason": reason,
        "warnings": warnings,
        "considered": considered,
        "mass_g": part.get("mass_g"),
        "size_mm": [part[k] for k in ("length_mm", "width_mm", "height_mm")] if "length_mm" in part else None,
        "diameter_mm": part.get("diameter_mm"),
    }
    if not considered:
        state.reasons[category] = event
    await ctx.emit(event)
    return event


async def warn_candidates(ctx: Ctx, parts: list[dict]) -> list[dict]:
    """While choosing, a candidate someone warned about shows that warning once."""

    shown = []
    for part in parts:
        key = "warned:" + part["id"]
        if key in ctx.state.reasons or part["id"] == ctx.state.selected.get(part["category"], {}).get("id"):
            continue
        if _warnings(ctx.state, part):
            ctx.state.reasons[key] = {}
            shown.append(await emit_part(ctx, part, considered=True))
    return shown
