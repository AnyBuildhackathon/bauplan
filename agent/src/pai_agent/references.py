"""The library: reference builds and saved projects, to start from instead of from scratch.

A reference is a known product with all its real parts; a project is a build a user saved
from a session. Both are folders with reference.json and one FreeCAD script per printed part,
references under agent/data/references/<id>/ (in the repository), projects under
agent/runs/library/<id>/ (local, not committed):

    {"id", "name", "summary",
     "spec": {... what product_spec takes ...},
     "scripts": {part_id: {"file": "base.py", "generated": true}},
     "picks": {part_id: {"select_id": "..."} or {"estimate": {...}}, "reason": "..."},
     "checks": [{"tool": "check_tip_over", "args": {}}, ...],
     "kind": "reference" | "project", "saved_at": "..."}

and an optional thumbnail.png next to it.

Loading one runs the same tools as any build (product_spec, cad_part with the stored
scripts, part_pick, assemble, the checks, Blender and the bill of materials), so it works
without a key, and the user then changes it in the chat with live Claude. save_reference
turns the current build into a new reference, so the registry grows with every product.

A product that has its own code is a code reference instead: the micro FPV drone is built
by the drone flow from the drone catalog (agent/data/parts.json) and the robot gripper by
the gripper flow, so the library never copies their parts and picks up whatever that code builds.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from pai_agent.paths import DATA_DIR, REPO_ROOT, RUNS_DIR

REFERENCES_DIR = DATA_DIR / "references"
PROJECTS_DIR = RUNS_DIR / "library"
GRIPPER_REQUEST = "Design a robot gripper for our arm that picks up a 200 g soda can, 66 mm wide. Keep it under 150 g and 30 €."


async def _build_drone(ctx) -> None:
    from pai_agent.mock_story import run_mock

    await run_mock(ctx)


async def _build_gripper(ctx) -> None:
    from pai_agent.mock_gripper import run_gripper_mock

    await ctx.chat("user", GRIPPER_REQUEST)
    await run_gripper_mock(ctx, GRIPPER_REQUEST)


def _gripper_summary() -> str:
    from pai_agent.tools.gripper import gripper_catalog

    servos = sum(1 for p in gripper_catalog()["parts"] if p["category"] == "servo")
    return "Two-finger gear gripper for a robot arm, built by the gripper flow: " + str(servos) + " servos to choose from, the MuJoCo grip test and the servo pocket sized in FreeCAD."


def _drone_summary() -> str:
    return (
        "The 1S 2-inch toothpick from Mediocre Nerd's \"Build a Micro FPV Drone for $59\" video, built by the drone flow "
        "from its catalog: Twiglet 2\" carbon frame, 1103 15000KV motors, Gemfan 2020 four-blade props, Caddx Ant camera, "
        "BetaFPV Matrix 1S 5in1 V2, canopy with battery holder, M1.4 bolts and a 1S pack, with the MuJoCo gust test."
    )


# Products whose own code builds them. Each entry: name, summary(), build(ctx), printed and bought counts.
CODE_REFERENCES = {
    "micro-drone": {
        "name": "Micro FPV drone ($59 video build)",
        "product": "drone",
        "summary": _drone_summary,
        "build": _build_drone,
        # The Twiglet frame is modelled in FreeCAD but bought in carbon, like every other part.
        "printed": 0,
        "bought": 8,
        # The kickoff's studio render, written by agent/scripts/record_demo.py.
        "thumbnail": REPO_ROOT / "web" / "public" / "models" / "hero-drone-thumb.jpg",
    },
    "robot-gripper": {
        "name": "Robot gripper",
        "product": "gripper",
        "summary": _gripper_summary,
        "build": _build_gripper,
        "printed": 1,
        "bought": 4,
        # Blender's studio render of the gripper flow's FreeCAD assembly.
        "thumbnail": REPO_ROOT / "web" / "public" / "models" / "robot-gripper-thumb.jpg",
    },
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "reference"


def _code_thumbnail(ref_id: str) -> Path | None:
    path = CODE_REFERENCES.get(ref_id, {}).get("thumbnail")
    return path if path is not None and path.is_file() else None


def thumbnail_of(ref_id: str) -> Path | None:
    """The library thumbnail: a code reference's render, else thumbnail.png in the item's folder."""

    code = _code_thumbnail(_slug(ref_id))
    if code is not None:
        return code
    folder = folder_of(ref_id)
    return folder / "thumbnail.png" if folder is not None and (folder / "thumbnail.png").is_file() else None


def folder_of(ref_id: str) -> Path | None:
    for root in (REFERENCES_DIR, PROJECTS_DIR):
        folder = root / _slug(ref_id)
        if (folder / "reference.json").is_file():
            return folder
    return None


def name_of(ref_id: str) -> str:
    """The library item's display name, or the id itself when there is none."""

    code = CODE_REFERENCES.get(_slug(ref_id))
    if code is not None:
        return code["name"]
    ref = _read(ref_id)
    return str(ref.get("name") or ref_id) if ref else ref_id


def _read(ref_id: str) -> dict | None:
    folder = folder_of(ref_id)
    return None if folder is None else json.loads((folder / "reference.json").read_text(encoding="utf-8"))


def _row(ref: dict, folder: Path, kind: str) -> dict:
    parts = ref["spec"]["parts"]
    return {
        "id": ref["id"],
        "name": ref["name"],
        "summary": ref.get("summary", ""),
        "kind": ref.get("kind", kind),
        "source": "saved" if kind == "project" else "registry",
        "product": "generic",
        "printed": sum(1 for p in parts if p["kind"] == "printed"),
        "bought": sum(1 for p in parts if p["kind"] == "bought"),
        "requirements": len(ref["spec"].get("requirements", [])),
        "thumbnail_url": "/api/library/" + ref["id"] + "/thumbnail" if (folder / "thumbnail.png").is_file() else None,
        "saved_at": ref.get("saved_at"),
    }


def list_references() -> list[dict]:
    """Code references first (the drone, then the gripper), then the registry, then saved projects, newest first."""

    rows = [
        {
            "id": ref_id,
            "name": ref["name"],
            "summary": ref["summary"](),
            "kind": "reference",
            "source": "code",
            "product": ref["product"],
            "printed": ref["printed"],
            "bought": ref["bought"],
            "requirements": None,
            "thumbnail_url": "/api/library/" + ref_id + "/thumbnail" if _code_thumbnail(ref_id) else None,
            "saved_at": None,
        }
        for ref_id, ref in CODE_REFERENCES.items()
    ]
    for path in sorted(REFERENCES_DIR.glob("*/reference.json")) if REFERENCES_DIR.is_dir() else []:
        rows.append(_row(json.loads(path.read_text(encoding="utf-8")), path.parent, "reference"))
    projects = []
    for path in PROJECTS_DIR.glob("*/reference.json") if PROJECTS_DIR.is_dir() else []:
        projects.append(_row(json.loads(path.read_text(encoding="utf-8")), path.parent, "project"))
    return rows + sorted(projects, key=lambda row: row["saved_at"] or "", reverse=True)


async def build_reference(ctx, ref_id: str) -> dict:
    """Builds a reference through the normal tools. Raises ValueError for an unknown id or a failing tool."""

    code = CODE_REFERENCES.get(_slug(ref_id))
    if code is not None:
        await code["build"](ctx)
        state = ctx.state
        return {
            "ok": True,
            "id": _slug(ref_id),
            "name": code["name"],
            "product_mass_g": state.metrics.get("weight_g"),
            "cost_eur": (state.bom or {}).get("total_eur", state.metrics.get("price_eur")),
            "requirements_passed": sum(1 for r in state.requirements if r.get("_met") is True),
            "requirements": len(state.requirements),
        }
    ref = _read(ref_id)
    if ref is None:
        known = ", ".join(r["id"] for r in list_references()) or "none"
        raise ValueError("No reference " + str(ref_id) + ". References: " + known + ".")
    folder = folder_of(ref["id"])
    assert folder is not None
    return await build_folder(ctx, folder)


async def build_folder(ctx, folder: Path) -> dict:
    """Builds the reference.json in folder (a library item or a published community project) through the normal tools."""

    from pai_agent.tools.registry import call_tool

    ref = json.loads((folder / "reference.json").read_text(encoding="utf-8"))

    async def need(name: str, args: dict) -> dict:
        result = await call_tool(ctx, name, args)
        if result.get("ok") is False:
            raise ValueError(name + " failed for the reference: " + str(result.get("error")))
        return result

    await need("product_spec", ref["spec"])
    for part in ref["spec"]["parts"]:
        if part["kind"] != "printed":
            continue
        entry = ref["scripts"][part["id"]]
        script = (folder / entry["file"]).read_text(encoding="utf-8")
        await need("cad_part", {"part_id": part["id"], "script": script, "_generated": bool(entry.get("generated"))})
    for part_id, pick in ref.get("picks", {}).items():
        await need("part_pick", {"part_id": part_id, **pick})
    await need("assemble", {})
    for check in ref.get("checks", []):
        await need(check["tool"], check.get("args", {}))
    await call_tool(ctx, "blender_render", {})
    bom = await need("bom_build", {})
    # Products without electronics have no plan; that is no failure of the reference.
    await call_tool(ctx, "electronics_plan", {})
    state = ctx.state
    passed = sum(1 for r in state.requirements if r.get("_met") is True)
    built = state.assembly or {}
    return {
        "ok": True,
        "id": ref["id"],
        "name": ref["name"],
        "product_mass_g": built.get("product_mass_g"),
        "cost_eur": bom["total_eur"],
        "requirements_passed": passed,
        "requirements": len(state.requirements),
    }


def save_reference(state, ref_id: str | None = None, name: str | None = None, summary: str = "", kind: str = "project") -> dict:
    """Writes the current product build into the library, as a project by default. Returns its row."""

    name = (name or (state.spec or {}).get("name") or "").strip()
    ref_id = _slug(ref_id or name)
    if ref_id in CODE_REFERENCES or (kind == "project" and (REFERENCES_DIR / ref_id).is_dir()):
        raise ValueError(ref_id + " is a reference build; save the project under another id.")
    write_snapshot(state, (REFERENCES_DIR if kind == "reference" else PROJECTS_DIR) / ref_id, ref_id, name, summary, kind)
    return next(row for row in list_references() if row["id"] == ref_id)


def write_snapshot(state, folder: Path, ref_id: str, name: str, summary: str = "", kind: str = "project") -> dict:
    """Writes the current product build into folder as reference.json, one script per printed part and the latest render."""

    if state.product != "generic" or not state.spec:
        raise ValueError("Only a product built from a spec can be saved as a reference.")
    spec = json.loads(json.dumps({k: v for k, v in state.spec.items() if not k.startswith("_") and k != "id"}))
    printed = [p for p in spec["parts"] if p["kind"] == "printed"]
    missing = [p["name"] for p in printed if p["id"] not in state.built]
    unpicked = [p["name"] for p in spec["parts"] if p["kind"] == "bought" and p["id"] not in state.picked]
    if missing or unpicked:
        raise ValueError("Finish the build first: " + ", ".join(missing + unpicked) + ".")
    name = name or spec["name"]
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    scripts = {}
    for part in printed:
        info = state.built[part["id"]]
        part["params"] = dict(info["params"])
        file = part["id"] + ".py"
        (folder / file).write_text(info["script"].rstrip("\n") + "\n", encoding="utf-8")
        scripts[part["id"]] = {"file": file, "generated": bool(info.get("generated"))}
    picks = {}
    for part_id, item in state.picked.items():
        if item.get("price_source") == "estimated" or str(item.get("id", "")).startswith("est-"):
            keep = {k: v for k, v in item.items() if k not in {"id", "category", "price_source", "query", "catalog", "reason"}}
            picks[part_id] = {"estimate": keep}
        else:
            picks[part_id] = {"select_id": item["id"]}
        if item.get("reason"):
            picks[part_id]["reason"] = item["reason"]
    checks = [{"tool": entry["tool"], "args": entry["args"]} for entry in state.checks.values()]
    ref = {
        "id": ref_id,
        "name": name,
        "summary": summary or spec["function"],
        "spec": spec,
        "scripts": scripts,
        "picks": picks,
        "checks": checks,
        "kind": kind,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    renders = sorted(Path(state.directory).glob("studio-v*.png"))
    if renders:
        shutil.copyfile(renders[-1], folder / "thumbnail.png")
    (folder / "reference.json").write_text(json.dumps(ref, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ref


def build_context(state) -> str:
    """What Claude needs to know about a build it did not make itself (a loaded reference)."""

    if state.product != "generic":
        lines = ["The bench already holds this " + state.product + " build, made by its own flow:"]
        lines += ["Part " + category + ": " + part["name"] + " (" + part["id"] + ")" for category, part in state.selected.items()]
        lines.append("Numbers: " + json.dumps({k: v for k, v in state.metrics.items() if k != "warnings"}))
        if state.cad_params:
            lines.append("Frame: " + json.dumps(state.cad_params))
        for requirement in state.requirements:
            lines.append("Requirement " + requirement["id"] + ": " + str(requirement.get("_met")))
        return "\n".join(lines) + "\n\nThe user's request about it:\n"
    spec = {k: v for k, v in state.spec.items() if not k.startswith("_")}
    lines = ["The bench already holds this product build (spec as product_spec took it):", json.dumps(spec, ensure_ascii=False)]
    for part_id, info in state.built.items():
        lines.append("Built " + part_id + ": " + f"{info['mass_g']:.0f} g {info['material']}, params " + json.dumps(info["params"]))
    for part_id, item in state.picked.items():
        lines.append("Picked " + part_id + ": " + item["name"] + " (" + str(item.get("id")) + ")")
    for key, entry in state.checks.items():
        lines.append("Check " + key + " ran with " + json.dumps(entry["args"]))
    for requirement in state.requirements:
        lines.append("Requirement " + requirement["id"] + ": " + str(requirement.get("_met")) + " " + str(requirement.get("_detail") or ""))
    return "\n".join(lines) + "\n\nThe user's request about it:\n"
