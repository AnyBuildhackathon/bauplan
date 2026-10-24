"""Records the mock story as the dashboard's demo fixture, so ?demo shows exactly the backend's numbers.

Runs the kickoff build, marks the review live, runs the review build, and writes:
- web/src/events/recording.json, the events in order, with file URLs pointing at /demo/run/
- web/public/demo/run/, a copy of every CAD part and render the events name

Run it again whenever the story, the catalog or the physics change:

    cd agent && uv run python scripts/record_demo.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT.parent / "web"
OUT_JSON = WEB / "src" / "events" / "recording.json"
OUT_FILES = WEB / "public" / "demo" / "run"
KICKOFF = "kickoff-drohne-2026-10-24"
REVIEW = "review-drohne-2026-10-24"


async def record() -> list[dict]:
    os.environ["PAI_FORCE_MOCK"] = "1"
    os.environ["DEMO_PACE_S"] = "0"
    os.environ["PAI_ASK_TIMEOUT_S"] = "0"
    os.environ.pop("JAMIE_MCP_TOKEN", None)
    # The recording takes the headless FreeCAD path even when the FreeCAD window is open.
    os.environ["FREECAD_MCP_URL"] = "http://127.0.0.1:1"

    from pai_agent.session import Session

    session = Session()
    copied: dict[str, str] = {}
    recorded: list[dict] = []
    publish = session.bus.publish

    async def keep(event: dict) -> None:
        recorded.append(_rewrite(event, session, copied))
        await publish(event)

    session.bus.publish = keep  # type: ignore[method-assign]
    await session.bootstrap()
    await session.start_from_meeting(KICKOFF, "Kickoff Drohne")
    assert session.task is not None
    await session.task
    await session.meeting_started(REVIEW, "Review 1")
    await session.start_from_meeting(REVIEW, "Review 1")
    await session.task
    return recorded


def _rewrite(event: dict, session, copied: dict[str, str]) -> dict:
    """Copies files the event names into web/public/demo/run and points the event at the copies."""

    text = json.dumps(event, ensure_ascii=False)
    session_id = session.state.session_id
    directory = Path(session.state.directory)

    def local(match: re.Match) -> str:
        name = match.group(1)
        stem, dot, suffix = name.partition(".")
        build = match.group(2) or ""
        target = stem + (("-" + build) if build else "") + dot + suffix
        if target not in copied:
            source = directory / name
            copied[target] = target
            if source.is_file():
                # An unchanged part from an earlier build points at the earlier copy.
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                if digest in copied:
                    copied[target] = copied[digest]
                else:
                    OUT_FILES.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, OUT_FILES / target)
                    copied[digest] = target
        return "/demo/run/" + copied[target]

    stl = "/files/" + session_id + "/frame.stl?build=" + str(session.state.cad_builds)
    text = re.sub(r"agent/runs/sessions/" + session_id + r"/frame\.stl", stl, text)
    text = re.sub(r"/files/" + session_id + r"/([A-Za-z0-9._-]+)(?:\?build=(\d+))?", local, text)
    fallback = re.compile(r"/files/fallback/([A-Za-z0-9._-]+)")
    for name in fallback.findall(text):
        OUT_FILES.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "runs" / "fallback" / name, OUT_FILES / name)
    text = fallback.sub(r"/demo/run/\1", text)
    return json.loads(text)


def main() -> None:
    if OUT_FILES.is_dir():
        shutil.rmtree(OUT_FILES)
    events = asyncio.run(record())
    # Bulky trajectories stay, but with fewer digits.
    OUT_JSON.write_text(json.dumps(events, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    versions = [e for e in events if e["type"] == "version"]
    print(
        "recorded",
        len(events),
        "events,",
        " | ".join(f"v{v['n']} {v['weight_g']} g {v['flight_time_min']} min {v['price_eur']} €" for v in versions),
        "->",
        OUT_JSON.relative_to(ROOT.parent),
    )


if __name__ == "__main__":
    main()
