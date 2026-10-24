"""Reading Jamie meetings: requirements, complaints, and what was said about a part.

The same code reads the local sample meetings and live Jamie transcripts.
A meeting is normalized to {id, title, kind, date, time, utterances, template}.
Each utterance is {speaker, time, text}, optionally with `about` (part ids) and `tone`.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_NUMBER_WORDS = {
    "fünf": 5,
    "five": 5,
    "acht": 8,
    "eight": 8,
    "zehn": 10,
    "ten": 10,
    "elf": 11,
    "eleven": 11,
    "zwölf": 12,
    "twelve": 12,
    "fünfzehn": 15,
    "fifteen": 15,
    "zwanzig": 20,
    "twenty": 20,
    "dreißig": 30,
    "thirty": 30,
    "fünfzig": 50,
    "fifty": 50,
    "achtzig": 80,
    "eighty": 80,
    "hundert": 100,
    "hundred": 100,
}
_NUMBER = r"(\d+(?:[.,]\d+)?|" + "|".join(_NUMBER_WORDS) + r")"
_NEGATIVE = re.compile(
    r"zu laut|laut|pfeift|nicht|kaputt|heiß|warm|bricht|hebt nicht|zu schwer|wackelt|vibriert|too loud|loud|whistl|broken|hot|too heavy|wobbl|vibrat|won't lift|will not lift",
    re.IGNORECASE,
)
_LAST_WEEK = re.compile(r"letzte[nr]? woche|vorige[nr]? woche|vor einer woche|last week", re.IGNORECASE)

_CATEGORY_WORDS = {
    "motor": re.compile(r"\bmotor(?:en|s)?\b|\b1102\b|\bkv\b", re.IGNORECASE),
    "battery": re.compile(r"\bakku\b|\bbatterie\b|\bzelle\b|\bbatter(?:y|ies)\b|\bpack\b", re.IGNORECASE),
    "propeller": re.compile(r"\bpropeller\b|\bprops?\b|\bluftschraube", re.IGNORECASE),
    "frame": re.compile(r"\brahmen\b|\bframe\b", re.IGNORECASE),
    "flight_controller": re.compile(r"\bregler\b|\bflugcontroller\b|\baio\b|\bcontroller\b", re.IGNORECASE),
}

REQUIREMENT_TEXT = {
    "budget": "Total price under €{n}",
    "flight_time": "At least {n} minutes of flight time",
    "weight": "Total mass under {n} g",
}
LIMIT_KEY = {"budget": "max", "flight_time": "min", "weight": "max"}
REQUIREMENT_ORDER = ("budget", "flight_time", "weight", "hover", "printable")


def number(raw: str) -> float:
    word = raw.strip().lower()
    if word in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[word])
    return float(word.replace(",", "."))


def fmt_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def normalize(raw: dict) -> dict:
    utterances = []
    for item in raw.get("utterances") or []:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            continue
        utterances.append(
            {
                "speaker": str(item.get("speaker") or "Someone"),
                "time": str(item.get("time") or ""),
                "text": str(item["text"]).strip(),
                "about": list(item.get("about") or []),
                "tone": item.get("tone"),
            }
        )
    if not utterances and isinstance(raw.get("transcript"), str):
        utterances = parse_transcript(raw["transcript"])
    return {
        "id": str(raw.get("id") or ""),
        "title": str(raw.get("title") or "Meeting"),
        "kind": str(raw.get("kind") or raw.get("role") or "kickoff"),
        "date": str(raw.get("date") or ""),
        "time": str(raw.get("time") or ""),
        "planned": bool(raw.get("planned")),
        "utterances": utterances,
        "template": raw.get("summary_template") if isinstance(raw.get("summary_template"), dict) else None,
        "requirements": [item for item in raw.get("requirements") or [] if isinstance(item, dict)],
        "owners": dict(raw.get("owners") or {}),
    }


_LINE = re.compile(r"^\s*(?:\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*)?([^:\n]{1,40}?)\s*(?:\((\d{1,2}:\d{2})\))?:\s*(.+)$")


def parse_transcript(text: str) -> list[dict]:
    """Splits a plain transcript into utterances: 'Ben: …', '[09:36] Ben: …' or 'Ben (09:36): …'."""

    out = []
    for line in re.split(r"\n+|(?<=[.!?])\s+(?=[A-ZÄÖÜ][a-zäöüß]+(?: [A-ZÄÖÜ][a-zäöüß]+)?:)", text):
        match = _LINE.match(line)
        if not match:
            if out and line.strip():
                out[-1]["text"] += " " + line.strip()
            continue
        stamp = match.group(1) or match.group(3) or ""
        out.append(
            {
                "speaker": match.group(2).strip(),
                "time": stamp[:5],
                "text": match.group(4).strip(),
                "about": [],
                "tone": None,
            }
        )
    return out


def _quote(meeting: dict, utterance: dict) -> dict:
    return {
        "text": utterance["text"],
        "speaker": utterance["speaker"],
        "time": utterance["time"],
        "meeting_id": meeting["id"],
        "meeting_title": meeting["title"],
    }


def _requirement(meeting: dict, rid: str, text: str, quote: dict, limit: float | None) -> dict:
    item = {
        "id": rid,
        "text": text,
        "source_quote": quote["text"],
        "speaker": quote["speaker"],
        "time": quote["time"],
        "meeting_id": meeting["id"],
        "meeting_title": meeting["title"],
    }
    if limit is not None and rid in LIMIT_KEY:
        item[LIMIT_KEY[rid]] = limit
    return item


def requirements_from(meeting: dict) -> tuple[list[dict], str]:
    """Template fields first, then requirements listed on the meeting, then sentences in the transcript."""

    found: dict[str, dict] = {}
    source = "transcript"
    template = meeting.get("template") or {}
    fields = template.get("fields") if isinstance(template, dict) else None
    if isinstance(fields, dict):
        for rid, field in fields.items():
            if not isinstance(field, dict) or "text" not in field or "source_quote" not in field:
                continue
            quote = {"text": field["source_quote"], "speaker": field.get("speaker", ""), "time": field.get("time", "")}
            limit = field.get(LIMIT_KEY.get(rid, ""))
            found[rid] = _requirement(meeting, rid, field["text"], quote, float(limit) if limit is not None else None)
            source = "template"
    for item in meeting.get("requirements") or []:
        rid = str(item.get("id", ""))
        if not rid or rid in found or "text" not in item:
            continue
        quote = {"text": item.get("source_quote", ""), "speaker": item.get("speaker", ""), "time": item.get("time", "")}
        limit = item.get(LIMIT_KEY.get(rid, ""))
        found[rid] = _requirement(meeting, rid, item["text"], quote, float(limit) if limit is not None else None)
    for utterance in meeting.get("utterances") or []:
        for rid, limit in _sentence_requirements(utterance["text"]):
            if rid in found:
                continue
            text = REQUIREMENT_TEXT[rid].format(n=fmt_number(limit)) if limit is not None else _plain_text(rid)
            found[rid] = _requirement(meeting, rid, text, _quote(meeting, utterance), limit)
    ordered = [found[rid] for rid in REQUIREMENT_ORDER if rid in found]
    ordered += [item for rid, item in found.items() if rid not in REQUIREMENT_ORDER]
    return ordered, source


def _plain_text(rid: str) -> str:
    return {"hover": "Must lift off and hover steadily", "printable": "Print the frame ourselves, as an STL"}[rid]


def _sentence_requirements(text: str) -> list[tuple[str, float | None]]:
    found: list[tuple[str, float | None]] = []
    lowered = text.lower()
    match = re.search(_NUMBER + r"\s*(?:euro|€)", lowered)
    if match:
        found.append(("budget", number(match.group(1))))
    match = re.search(_NUMBER + r"\s*(?:minuten|minutes)", lowered)
    if match and re.search(r"flug|flieg|luft|flight|fly|air", lowered):
        found.append(("flight_time", number(match.group(1))))
    match = re.search(_NUMBER + r"\s*(?:gramm|grams|g\b)", lowered)
    if match and re.search(r"unter|maximal|höchstens|leichter|under|at most|no more than|lighter", lowered):
        found.append(("weight", number(match.group(1))))
    if re.search(r"abheb|schweb|lift off|hover", lowered):
        found.append(("hover", None))
    if re.search(r"\bstl\b|selber drucken|selbst drucken|drucken wir|print (?:it |the frame )?ourselves", lowered):
        found.append(("printable", None))
    return found


def complaints_from(meeting: dict) -> list[dict]:
    """Negative sentences about a part category, with whether they point back to last week."""

    out = []
    for utterance in meeting.get("utterances") or []:
        text = utterance["text"]
        if not _NEGATIVE.search(text):
            continue
        for category, pattern in _CATEGORY_WORDS.items():
            if pattern.search(text):
                out.append(
                    {
                        "category": category,
                        "last_week": bool(_LAST_WEEK.search(text)),
                        "loud": bool(re.search(r"laut|pfeift|loud|whistl", text, re.IGNORECASE)),
                        "quote": _quote(meeting, utterance),
                    }
                )
                break
    return out


def conflicts(current: list[dict], incoming: list[dict]) -> list[dict]:
    """Same requirement, different limit, from different meetings."""

    known = {item["id"]: item for item in current}
    out = []
    for item in incoming:
        old = known.get(item["id"])
        key = LIMIT_KEY.get(item["id"])
        if not old or not key or key not in old or key not in item:
            continue
        if float(old[key]) == float(item[key]) or old.get("meeting_id") == item.get("meeting_id"):
            continue
        out.append({"id": item["id"], "old": old, "new": item})
    return out


def notes_about(part: dict, meetings: list[dict]) -> list[dict]:
    """Every sentence that names this part, newest meeting last, with a tone."""

    aliases = [alias.lower() for alias in part.get("aliases") or []]
    out = []
    for meeting in meetings:
        for utterance in meeting.get("utterances") or []:
            named = part["id"] in utterance.get("about", [])
            if not named:
                lowered = utterance["text"].lower()
                named = any(alias in lowered for alias in aliases)
            if not named:
                continue
            tone = utterance.get("tone") or ("warning" if _NEGATIVE.search(utterance["text"]) else "fact")
            out.append({**_quote(meeting, utterance), "tone": tone, "date": meeting.get("date", "")})
    return out


def week_before(day: str) -> tuple[str, str]:
    """The window 'last week' means, seen from a meeting date: 4 to 10 days back."""

    try:
        anchor = date.fromisoformat(day)
    except ValueError:
        anchor = date.today()
    return (anchor - timedelta(days=10)).isoformat(), (anchor - timedelta(days=4)).isoformat()


def short_date(day: str) -> str:
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        return day
    return f"{parsed.day} {parsed.strftime('%b')}"
