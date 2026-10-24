"""Checks the community without a network: the seeded feed, a remix, publishing it and remixing that.

    cd agent && uv run python scripts/smoke_community.py

Remixes the desk fan seed through the same tools as the bench (mock mode), publishes the build
as a remix into a temporary folder, checks the link back and the original's remix count, then
rebuilds the published entry from its own stored spec and scripts. Needs freecadcmd or CadQuery.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["PAI_FORCE_MOCK"] = "1"

from pai_agent import community
from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.orchestrator import run_remix
from pai_agent.paths import SESSIONS_DIR
from pai_agent.state import BuildState
from pai_agent.tools.jamie import init_timeline


def check(condition: bool, message: str) -> None:
    print(("ok   " if condition else "FAIL ") + message)
    if not condition:
        sys.exit(1)


def fresh(name: str) -> BuildState:
    folder = SESSIONS_DIR / ("smoke-community-" + name)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    state = BuildState(session_id=folder.name, directory=folder)
    init_timeline(state)
    return state


async def main() -> None:
    community.PUBLISHED_DIR = Path(tempfile.mkdtemp(prefix="community-"))
    try:
        feed = community.list_entries()
        ids = [row["id"] for row in feed]
        check(
            len(feed) >= 4 and all(row["seed"] for row in feed),
            f"the feed starts with {len(feed)} seeds",
        )
        check(
            all(row["thumbnail_url"] and row["metrics"].get("cost_eur") for row in feed),
            "every seed has a render and real numbers",
        )
        popular = [row["remixes"] for row in community.list_entries("popular")]
        check(popular == sorted(popular, reverse=True), "popular sorts by remix count")
        check(
            [row["id"] for row in community.list_entries(query="fan")] == ["quiet-desk-fan"],
            "search finds the desk fan",
        )
        before = community.get_entry("quiet-desk-fan")
        assert before is not None and "quiet-desk-fan" in ids

        state = fresh("remix")
        bus = EventBus()
        await run_remix(Ctx(bus, state, auto_steps=False), before)
        check(
            state.remixed_from
            == {
                "id": "quiet-desk-fan",
                "title": before["title"],
                "author": before["author"],
            },
            "the remix knows its original",
        )
        check(
            any(ev.get("type") == "remix" and ev.get("id") == "quiet-desk-fan" for ev in bus.events),
            "the bench gets a remix event",
        )
        check(
            state.bom is not None and state.finished,
            "the remix is built and has a bill of materials",
        )

        try:
            community.publish(state, "", "", "")
            check(False, "a title and an author are required")
        except ValueError:
            check(True, "a title and an author are required")
        row = community.publish(state, "Desk fan with a taller neck", "Remixed in the smoke test.", "smoke")
        check(
            row["remixed_from"] is not None and row["remixed_from"]["id"] == "quiet-desk-fan",
            "the published remix links back",
        )
        check(
            row["base"] is None and (community.PUBLISHED_DIR / row["id"] / "reference.json").is_file(),
            "a spec product keeps its own spec and scripts",
        )
        check(
            any(f["name"].startswith("studio-v") for f in row["files"]) and row["thumbnail_url"],
            "the renders are kept",
        )
        after = community.get_entry("quiet-desk-fan")
        assert after is not None
        check(
            after["remixes"] == before["remixes"] + 1,
            f"the original's remix count went {before['remixes']} -> {after['remixes']}",
        )
        check(
            community.list_entries()[0]["id"] == row["id"],
            "the new entry is first under new",
        )

        again = fresh("again")
        result = await community.build_entry(Ctx(EventBus(), again, auto_steps=False), row["id"])
        check(
            result["requirements_passed"] == result["requirements"],
            f"the published entry rebuilds from its own folder ({result['requirements_passed']}/{result['requirements']})",
        )
    finally:
        shutil.rmtree(community.PUBLISHED_DIR, ignore_errors=True)
        for name in ("remix", "again"):
            shutil.rmtree(SESSIONS_DIR / ("smoke-community-" + name), ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
