"""Sketch to build: a photo of a hand sketch becomes a validated product spec.

The dashboard uploads the photo (POST /api/sketch); store_sketch checks it and keeps it in the
session folder as sketch-<n>.<ext>. sketch_to_spec sends it to Claude vision, which reads the
product, every written dimension, the parts and the requirements off the paper and answers with
a spec that spec.py validates. The orchestrator then calls product_spec with it, so a sketch
starts the same any-product flow as a typed request, and FreeCAD builds it from there.
Without a key, the recorded reading of the sample sketch stands in for the vision call.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
from pathlib import Path

from pai_agent.context import Ctx
from pai_agent.env import claude_enabled
from pai_agent.paths import DATA_DIR

SKETCH_DIR = DATA_DIR / "sketches"
SAMPLE = SKETCH_DIR / "phone-stand.png"
RECORDED = SKETCH_DIR / "phone-stand.json"
MAX_BYTES = 8 * 1024 * 1024
# The mock reads the sample sketch with a short pause, like a vision call would take.
MOCK_PAUSE_S = 1.5
# Claude vision answers once and may correct a rejected spec this often.
RETRIES = 2
_DATA_URL = re.compile(r"^data:(image/[a-z0-9+.-]+);base64,(.*)$", re.IGNORECASE | re.DOTALL)
_NAME = re.compile(r"^sketch-\d+\.(png|jpg|webp)$")

_PROMPT = """This is a photo of a hand sketch of a physical product someone wants built.
Read it like an engineer and answer with propose_spec.
read: every written dimension and label, one entry each, with its unit as written and your confidence (high, medium, low).
unreadable: what you cannot read or make out.
spec: a full product_spec. Keep the sketched numbers; where the sketch gives none, choose a sensible value,
mark it as a guess in that part's description and add it to read with confidence low.
Requirements each name the check that judges it and a limit from the notes (mass and cost always,
tip_over for anything that stands, deflection for arms and shelves, stability for anything on a table).
Coordinates as in product_spec: millimetres, Z up, the product stands on Z = 0 centred on X = Y = 0, -Y is the front.
Printed parts get size_mm and params with the sketched dimensions; they become sliders.
summary: one sentence on what you read and what you guessed.
If the photo is not a sketch of a product, leave spec empty and say what you see in unreadable. Write English."""


def _kind(data: bytes) -> str | None:
    """The image type from its first bytes; the browser's media type is not trusted."""

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp" and data[8:12] in {b"heic", b"heix", b"mif1", b"msf1", b"hevc"}:
        return "heic"
    return None


_MEDIA = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def decode_image(raw: str) -> bytes:
    """A data URL or plain base64 from the browser, as bytes. Raises ValueError with a message for the user."""

    text = (raw or "").strip()
    match = _DATA_URL.match(text)
    if match:
        text = match.group(2)
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("The sketch is not valid base64 image data.") from exc
    if not data:
        raise ValueError("The sketch is empty.")
    return data


def store_sketch(state, data: bytes) -> str:
    """Checks the photo (PNG, JPEG or WebP by its bytes, at most 8 MB) and writes sketch-<n>.<ext> into the session."""

    if len(data) > MAX_BYTES:
        raise ValueError("The sketch is larger than 8 MB. Take the photo smaller.")
    kind = _kind(data)
    if kind == "heic":
        raise ValueError("Please send PNG or JPEG: HEIC photos are not supported yet.")
    if kind is None:
        raise ValueError("The sketch must be a PNG, JPEG or WebP photo.")
    count = len(list(state.directory.glob("sketch-*")))
    name = "sketch-" + str(count + 1) + "." + kind
    (state.directory / name).write_bytes(data)
    return name


def sketch_url(state, name: str) -> str:
    return "/files/" + state.session_id + "/" + name


def sketch_event(state, name: str, status: str, **extra) -> dict:
    return {"type": "sketch", "id": Path(name).stem, "url": sketch_url(state, name), "status": status, **extra}


def recorded() -> dict:
    return json.loads(RECORDED.read_text(encoding="utf-8"))


async def sketch_to_spec(ctx: Ctx, args: dict) -> dict:
    from pai_agent.spec import SpecError, validate_spec

    state = ctx.state
    name = str(args.get("sketch") or "").strip()
    if not name:
        # The newest sketch on the bench when Claude leaves the file name out.
        names = sorted(state.directory.glob("sketch-*"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
        name = names[-1].name if names else ""
    path = state.directory / name
    if not _NAME.fullmatch(name) or not path.is_file():
        return {"ok": False, "error": "No sketch " + (name or "") + " on the bench. Ask the user to drop a photo of the sketch into the chat."}
    note = str(args.get("note") or "").strip()
    if claude_enabled():
        result = await _read_with_claude(ctx, path, note)
    else:
        await asyncio.sleep(MOCK_PAUSE_S)
        record = recorded()
        result = {
            "ok": True,
            "spec": {**record["spec"], "quote": note or record["spec"]["quote"]},
            "read": record["read"],
            "unreadable": record.get("unreadable", []),
            "summary": record["summary"],
            "source": "recorded",
        }
    if result.get("ok"):
        try:
            result["spec_id"] = validate_spec(result["spec"])["id"]
        except SpecError as exc:
            result = {"ok": False, "error": "The spec from the sketch has problems: " + " | ".join(exc.problems), "unreadable": result.get("unreadable", [])}
    if not result.get("ok"):
        await ctx.emit(sketch_event(state, name, "failed", note=note, error=result["error"], unreadable=result.get("unreadable", [])))
        return result
    await ctx.emit(
        sketch_event(
            state,
            name,
            "read",
            note=note,
            summary=result["summary"],
            read=result["read"],
            unreadable=result["unreadable"],
            product=result["spec_id"],
            source=result["source"],
        )
    )
    return {
        **result,
        "detail": result["summary"],
        "next": "Say in one sentence what you read and what you guessed, then call product_spec with this spec.",
    }


async def _read_with_claude(ctx: Ctx, path: Path, note: str) -> dict:
    """One vision call with a forced propose_spec; a spec spec.py rejects goes back with its problems."""

    from pai_agent import settings
    from pai_agent.agents import AgentRun
    from pai_agent.spec import SpecError, validate_spec
    from pai_agent.tools.registry import SCHEMAS

    data = path.read_bytes()
    spec_schema = next(schema["input_schema"] for schema in SCHEMAS if schema["name"] == "product_spec")
    reading = {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "value": {"type": "string"},
            "unit": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["label", "value"],
    }
    tool = {
        "name": "propose_spec",
        "description": "What the sketch shows: the readings, what is unreadable, a one-sentence summary and the full product spec.",
        "input_schema": {
            "type": "object",
            "properties": {
                "read": {"type": "array", "items": reading},
                "unreadable": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
                "spec": spec_schema,
            },
            "required": ["read", "summary", "spec"],
        },
    }
    image = {"type": "base64", "media_type": _MEDIA[_kind(data) or "png"], "data": base64.b64encode(data).decode("ascii")}
    text = _PROMPT + ("\nThe person who drew it adds: " + note if note else "")
    messages: list[dict] = [{"role": "user", "content": [{"type": "image", "source": image}, {"type": "text", "text": text}]}]
    model = settings.current()["orchestrator_model"]
    run = AgentRun(ctx, "sketch", "Vision agent", model, "medium", "read the hand sketch " + path.name)
    await run.emit("running", "reads the sketch")
    problems: list[str] = []
    unreadable: list[str] = []
    for _attempt in range(1 + RETRIES):
        try:
            response = await asyncio.to_thread(_create, model, messages, tool)
        except Exception as exc:
            await run.emit("error", str(exc)[:160])
            return {"ok": False, "error": "Claude vision did not answer: " + str(exc)}
        run.count(response)
        block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
        if block is None:
            break
        answer = block.input if isinstance(block.input, dict) else {}
        unreadable = [str(item) for item in answer.get("unreadable") or []]
        spec = answer.get("spec") if isinstance(answer.get("spec"), dict) else {}
        if not spec.get("parts"):
            await run.emit("done", "no product in the photo")
            seen = "; ".join(unreadable) or "no product sketch"
            return {"ok": False, "error": "I could not read a product from this photo: " + seen + ". What is it, and which sizes matter?", "unreadable": unreadable}
        spec.setdefault("quote", note or "Hand sketch")
        try:
            validate_spec(spec)
        except SpecError as exc:
            problems = exc.problems
            messages.append({"role": "assistant", "content": [block.model_dump(exclude_none=True)]})
            feedback = "The spec has problems. Fix all of them and call propose_spec again: " + " | ".join(problems)
            messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": feedback}]})
            await run.emit("running", str(len(problems)) + " problem(s), fixing")
            continue
        read = [item for item in answer.get("read") or [] if isinstance(item, dict) and item.get("label")]
        await run.emit("done", str(spec.get("name") or "spec") + " from the sketch")
        return {"ok": True, "spec": spec, "read": read, "unreadable": unreadable, "summary": str(answer.get("summary") or ""), "source": "claude"}
    await run.emit("error", "no valid spec")
    detail = (" Last problems: " + " | ".join(problems)) if problems else ""
    return {"ok": False, "error": "Claude vision could not turn the sketch into a valid spec." + detail, "unreadable": unreadable}


def _create(model: str, messages: list[dict], tool: dict):
    import anthropic

    # A forced tool call returns the spec as JSON. Forced tool use does not combine with extended thinking, so none here.
    return anthropic.Anthropic().messages.create(
        model=model,
        max_tokens=8000,
        output_config={"effort": "medium"},
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=messages,
    )
