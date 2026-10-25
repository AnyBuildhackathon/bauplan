"""Seeds the community feed from the library builds, with their real numbers.

    cd agent && uv run python scripts/seed_community.py

Builds every seed's library item through the same tools as the bench (mock mode, no keys) and
writes agent/data/community/<id>/entry.json with the build's mass, cost, part count, checks,
bill of materials and versions. Then writes web/public/community/feed.json and the renders it
needs, so the dashboard can show the same feed while the backend is offline. Needs freecadcmd.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil

os.environ["PAI_FORCE_MOCK"] = "1"

from pai_agent.bus import EventBus
from pai_agent.community import (
    SEEDS_DIR,
    _metrics,
    _product_label,
    list_entries,
    thumbnail,
)
from pai_agent.context import Ctx
from pai_agent.paths import REPO_ROOT, SESSIONS_DIR
from pai_agent.references import build_reference
from pai_agent.state import BuildState

WEB_DIR = REPO_ROOT / "web" / "public" / "community"
# Renders the web app already ships; the other seeds copy theirs next to feed.json.
WEB_RENDERS = {
    "micro-drone": "/models/hero-drone-thumb.jpg",
    "robot-gripper": "/models/robot-gripper-thumb.jpg",
}

SEEDS = [
    {
        "id": "micro-fpv-toothpick",
        "base": "micro-drone",
        "title": "1S micro FPV toothpick",
        "description": 'The 1S 2-inch toothpick from Mediocre Nerd\'s "Build a Micro FPV Drone for $59" video, part for part: '
        "Twiglet carbon frame, 1103 motors, Caddx Ant camera, Matrix 1S AIO. Passes the MuJoCo gust test.",
        "author": "AnyBuild team",
        "published_at": "2026-10-21T19:12:00",
        "remixes": 14,
    },
    {
        "id": "two-finger-gripper",
        "base": "robot-gripper",
        "title": "Two-finger gripper for a desktop arm",
        "description": "Gear-driven parallel gripper that picks up a 200 g soda can. Servo pocket sized in FreeCAD, grip checked in MuJoCo through lift and shake.",
        "author": "jonas_robotics",
        "published_at": "2026-10-22T10:40:00",
        "remixes": 9,
    },
    {
        "id": "desk-phone-stand",
        "base": "phone-stand",
        "title": "Desk phone stand, 65 degrees",
        "description": "Two PETG parts and four rubber feet. Holds a 200 g phone and does not tip when you tap the screen.",
        "author": "lena.prints",
        "published_at": "2026-10-22T16:05:00",
        "remixes": 6,
    },
    {
        "id": "quiet-desk-fan",
        "base": "desk-fan",
        "title": "Quiet USB desk fan",
        "description": "An 80 mm USB fan on a printed neck, bracket and 150 mm base. 280 g in total and it takes a light bump without tipping.",
        "author": "maker.kai",
        "published_at": "2026-10-23T09:30:00",
        "remixes": 4,
    },
    {
        "id": "plant-watering-robot",
        "base": "plant-waterer",
        "title": "Plant-watering robot",
        "description": "1 litre printed tank, 5 V pump, capacitive soil sensor and an ESP32 on one 18650. Runs about a month and stays stable with a full tank.",
        "author": "studio_fern",
        "published_at": "2026-10-23T21:15:00",
        "remixes": 2,
    },
]


async def build(seed: dict) -> dict:
    folder = SESSIONS_DIR / ("seed-" + seed["id"])
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    state = BuildState(session_id=folder.name, directory=folder)
    result = await build_reference(Ctx(EventBus(), state, auto_steps=False), seed["base"])
    bom = (state.bom or {}).get("items", [])
    entry = {
        **seed,
        "product": state.product,
        "product_label": _product_label(state),
        "remixed_from": None,
        "metrics": _metrics(state),
        "bom": [
            {
                "name": item.get("name"),
                "qty": item.get("qty"),
                "unit_price_eur": item.get("unit_price_eur"),
            }
            for item in bom
        ],
        "versions": json.loads(json.dumps(state.versions, default=str)),
        "files": [],
    }
    shutil.rmtree(folder, ignore_errors=True)
    print(f"{seed['id']}: {result['requirements_passed']}/{result['requirements']} checks, {entry['metrics']}")
    return entry


async def main() -> None:
    for seed in SEEDS:
        entry = await build(seed)
        target = SEEDS_DIR / seed["id"]
        target.mkdir(parents=True, exist_ok=True)
        (target / "entry.json").write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    shutil.rmtree(WEB_DIR, ignore_errors=True)
    WEB_DIR.mkdir(parents=True)
    feed = []
    seeds = {seed["id"]: seed for seed in SEEDS}
    for row in list_entries():
        if row["id"] not in seeds:
            continue
        base = seeds[row["id"]]["base"]
        if base in WEB_RENDERS:
            row["thumbnail_url"] = WEB_RENDERS[base]
        else:
            path = thumbnail(row["id"])
            assert path is not None, row["id"]
            shutil.copyfile(path, WEB_DIR / (row["id"] + ".png"))
            row["thumbnail_url"] = "/community/" + row["id"] + ".png"
        feed.append(row)
    (WEB_DIR / "feed.json").write_text(json.dumps(feed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
