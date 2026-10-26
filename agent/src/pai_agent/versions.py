"""Version history: every rebuild is a version with its trigger, its numbers, its parts and a copy of its model.

Every product, the drone included, commits a version here after its bill of materials; `snapshot` adds
the model copy, the requirement results and what a restore needs. A restore rebuilds an old version
through the same tools as any build and commits it as a new version, so history only grows.

Each version also keeps a verdict book: what independent judges (Robo Use, `robouse_trial`) said about that
exact design, next to AnyBuild's own test in `sim`. A verdict usually arrives after its version is committed,
and the version is then published again with it; one given on a bench that is not a version yet waits for the
commit of that same design.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from pai_agent.context import Ctx

TRIGGERS = ("chat", "library", "check_failed", "restore")
# Independent judges whose verdicts a version keeps, by the tool that asks them.
JUDGES = {"robouse_trial": ("robouse", "Robo Use")}

# Drone numbers in the existing diff shape: key, label, unit.
_DRONE_NUMBERS = (
    ("weight_g", "Weight", "g"),
    ("flight_time_min", "Flight time", "min"),
    ("price_eur", "Price", "€"),
    ("thrust_to_weight", "Thrust/weight", ": 1"),
)
_PRODUCT_NUMBERS = (("weight_g", "Weight", "g"), ("price_eur", "Price", "€"))


def _last(ctx: Ctx, kind: str, test=lambda _ev: True) -> dict | None:
    return next((ev for ev in reversed(ctx.bus.events) if ev.get("type") == kind and test(ev)), None)


def _file_name(url: str | None, session_id: str) -> str | None:
    """`/files/<session>/frame.glb?build=3` -> `frame.glb`, only for this session's own files."""

    prefix = "/files/" + session_id + "/"
    if not url or not url.startswith(prefix):
        return None
    return url[len(prefix) :].split("?", 1)[0] or None


def _model_source(ctx: Ctx) -> Path | None:
    state = ctx.state
    directory = Path(state.directory)
    if state.product == "generic" and state.assembly and state.assembly.get("glb"):
        path = directory / state.assembly["glb"]
        return path if path.is_file() else None
    if state.product == "drone":
        path = directory / "frame.glb"
        return path if path.is_file() else None
    cad = _last(ctx, "cad", lambda ev: bool(ev.get("glb_url")))
    name = _file_name((cad or {}).get("glb_url"), state.session_id)
    path = directory / name if name else None
    return path if path is not None and path.is_file() else None


def _parts(state) -> dict[str, str]:
    if state.product == "generic" and state.spec:
        out = {}
        for part in state.spec["parts"]:
            picked = state.picked.get(part["id"])
            out[part["id"]] = picked["name"] if part["kind"] == "bought" and picked else part["name"]
        return out
    return {category: part["name"] for category, part in state.selected.items()}


def _params(state) -> dict[str, float]:
    if state.product == "generic":
        return {
            part_id + "." + name: value
            for part_id, info in state.built.items()
            for name, value in (info.get("params") or {}).items()
            if isinstance(value, (int, float))
        }
    if state.product == "drone":
        return {name: value for name, value in state.cad_params.items() if isinstance(value, (int, float))}
    params = (state.part or {}).get("params") or {}
    # The gripper's servo pocket follows the chosen servo (tools/gripper.servo_params): the servo is the part row, not a dimension.
    return {name: value for name, value in params.items() if isinstance(value, (int, float)) and not name.startswith("servo_")}


def _param_label(name: str) -> str:
    """'finger_length_mm' -> 'Finger length', a product's 'base.length_mm' -> 'Base length'."""

    words = re.sub(r"_(mm|deg|g)$", "", name).replace(".", " ").replace("_", " ")
    return words[:1].upper() + words[1:]


def _requirements(state) -> list[dict]:
    return [
        {"id": r["id"], "text": r.get("text", r["id"]), "met": r.get("_met"), "detail": r.get("_detail") or ""}
        for r in state.requirements
    ]


def diff(previous: dict | None, current: dict) -> list[dict]:
    """Rows `{key, label, before, after, unit}`: numbers, swapped parts, CAD parameters, flipped requirements and verdicts."""

    if not previous:
        return []
    rows = []
    numbers = _DRONE_NUMBERS if current.get("product", "drone") == "drone" else _PRODUCT_NUMBERS
    for key, label, unit in numbers:
        before, after = previous.get(key), current.get(key)
        if isinstance(before, (int, float)) and isinstance(after, (int, float)) and before != after:
            rows.append({"key": key, "label": label, "before": before, "after": after, "unit": unit})
    old_cards = {card["key"]: card for card in previous.get("cards") or [] if "key" in card}
    for card in current.get("cards") or []:
        old = old_cards.get(card.get("key"))
        if old and isinstance(old.get("value"), (int, float)) and isinstance(card.get("value"), (int, float)) and old["value"] != card["value"]:
            if card["key"] not in {row["key"] for row in rows}:
                rows.append({"key": card["key"], "label": card.get("label", card["key"]), "before": old["value"], "after": card["value"], "unit": card.get("unit", "")})
    before_parts = previous.get("parts") or {}
    for category, name in (current.get("parts") or {}).items():
        before = before_parts.get(category)
        if before and before != name:
            rows.append({"key": "part:" + category, "label": category.replace("_", " ").capitalize(), "before": before, "after": name, "unit": ""})
    before_params = previous.get("params") or {}
    for name, value in (current.get("params") or {}).items():
        before = before_params.get(name)
        if isinstance(before, (int, float)) and before != value:
            unit = "mm" if name.endswith("_mm") else ""
            rows.append({"key": "param:" + name, "label": _param_label(name), "before": before, "after": value, "unit": unit})
    before_reqs = {r["id"]: r for r in previous.get("requirements") or []}
    for requirement in current.get("requirements") or []:
        old = before_reqs.get(requirement["id"])
        if old is None or old.get("met") is None or requirement.get("met") is None or old["met"] == requirement["met"]:
            continue
        rows.append(
            {
                "key": "req:" + requirement["id"],
                "label": requirement["text"],
                "before": "pass" if old["met"] else "fail",
                "after": "pass" if requirement["met"] else "fail",
                "unit": "",
            }
        )
    before_verdicts = {_verdict_key(v): v for v in previous.get("verdicts") or []}
    for verdict in current.get("verdicts") or []:
        old = before_verdicts.get(_verdict_key(verdict))
        if old is None or verdict_text(old) == verdict_text(verdict):
            continue
        rows.append({"key": "verdict:" + _verdict_key(verdict), "label": verdict["label"], "before": verdict_text(old), "after": verdict_text(verdict), "unit": ""})
    return rows


# The verdict book (docs/events.md, version: verdicts).


def _verdict_key(verdict: dict) -> str:
    """One entry per judge and policy: the reference solution's verdict and Claude Code's are kept apart."""

    harness = verdict.get("harness") or "oracle"
    return verdict["judge"] + ("" if harness == "oracle" else ":" + harness)


def verdict_text(verdict: dict) -> str:
    """'pass, reward 1', 'fail, reward 0', 'not counted' or 'cannot take the object'."""

    outcome = verdict.get("verdict")
    if outcome == "invalid":
        return "not counted"
    if outcome == "refused":
        return "cannot take the object"
    reward = verdict.get("reward")
    return str(outcome) + (f", reward {reward:g}" if isinstance(reward, (int, float)) else "")


def verdict_of(event: dict | None) -> dict | None:
    """The verdict book entry for a finished trial event, or None when it judged nothing about this build.

    A trial counts when it ran on this build, when it was recorded earlier on this same design, or when the task
    generator refused this design; a recorded trial of another design, one still running and one that could not
    run say nothing about the version on the bench.
    """

    if not event or event.get("type") != "trial" or event.get("status") == "running":
        return None
    recorded = event.get("recorded") or {}
    if event.get("status") == "recorded" and not recorded.get("matches_build"):
        return None
    if event.get("status") == "failed" and event.get("verdict") != "refused":
        return None
    if event.get("verdict") not in {"pass", "fail", "invalid", "refused"}:
        return None
    judge, label = JUDGES["robouse_trial"]
    harness = str(event.get("harness") or "oracle")
    return {
        "judge": judge,
        "label": label + ("" if harness == "oracle" else ", Claude Code" if harness == "claude-code" else ", " + harness),
        "trial_id": event.get("id"),
        "harness": harness,
        "verdict": event["verdict"],
        "reward": event.get("reward") if event.get("verdict") != "refused" else None,
        "status": event.get("status"),
        "summary": str(event.get("summary") or ""),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _file_verdict(version: dict, verdict: dict) -> None:
    """Adds a verdict to a version's book; a newer one of the same judge and policy replaces the older."""

    key = _verdict_key(verdict)
    version["verdicts"] = [v for v in version.get("verdicts") or [] if _verdict_key(v) != key] + [verdict]


def _bench(state) -> dict:
    """What a version stands for when a judge looks at it: its parts and CAD parameters."""

    return {"parts": _parts(state), "params": _params(state)}


async def record_verdict(ctx: Ctx, result: dict) -> dict | None:
    """Files a finished trial in the verdict book of the version it judged and publishes that version again.

    The trial names the bench version it ran on (`bench_version`). When that version is committed, the verdict joins
    it now; when the bench is not a version yet, it waits for the commit of this same design (`commit`), and a design
    that changes before its commit drops it. Returns the version it joined, else None.
    """

    state = ctx.state
    event = _last(ctx, "trial", lambda ev: ev.get("id") == result.get("id"))
    verdict = verdict_of(event)
    if verdict is None or event is None:
        return None
    n = event.get("version")
    version = next((v for v in state.versions if v["n"] == n), None)
    if version is None:
        key = _verdict_key(verdict)
        state.pending_verdicts = [v for v in state.pending_verdicts if _verdict_key(v) != key] + [{**verdict, "n": n, "bench": _bench(state)}]
        return None
    _file_verdict(version, verdict)
    if verdict["verdict"] in {"fail", "refused"}:
        # The next version this run commits answers this verdict (_trigger).
        ctx.verdict_failed = n
    previous = next((v for v in state.versions if v["n"] == n - 1), None)
    version["diff"] = diff(previous, version)
    await ctx.emit({"type": "version", **version})
    return version


def _take_pending(state, version: dict) -> list[dict]:
    """The waiting verdicts given on exactly this design, for its commit; the rest judged a bench that changed."""

    bench = {"parts": version.get("parts") or {}, "params": version.get("params") or {}}
    book: dict = {"verdicts": []}
    for verdict in state.pending_verdicts:
        if verdict.get("n") == version["n"] and verdict.get("bench") == bench:
            _file_verdict(book, {k: v for k, v in verdict.items() if k not in {"n", "bench"}})
    state.pending_verdicts = []
    return book["verdicts"]


def _write_restorable(state, folder: Path) -> None:
    """A generic product as references.save_reference writes it: spec, part scripts, picks and checks."""

    spec = json.loads(json.dumps({k: v for k, v in state.spec.items() if not k.startswith("_") and k != "id"}))
    folder.mkdir(parents=True, exist_ok=True)
    scripts = {}
    for part in spec["parts"]:
        info = state.built.get(part["id"])
        if part["kind"] != "printed" or info is None:
            continue
        part["params"] = dict(info["params"])
        file = part["id"] + ".py"
        (folder / file).write_text(info["script"].rstrip("\n") + "\n", encoding="utf-8")
        scripts[part["id"]] = {"file": file, "generated": bool(info.get("generated"))}
    picks = {}
    for part_id, item in state.picked.items():
        if item.get("price_source") == "estimated" or str(item.get("id", "")).startswith("est-"):
            picks[part_id] = {"estimate": {k: v for k, v in item.items() if k not in {"id", "category", "price_source", "query", "catalog", "reason"}}}
        else:
            picks[part_id] = {"select_id": item["id"]}
    checks = [{"tool": entry["tool"], "args": entry["args"]} for entry in state.checks.values()]
    ref = {"spec": spec, "scripts": scripts, "picks": picks, "checks": checks}
    (folder / "reference.json").write_text(json.dumps(ref, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def snapshot(ctx: Ctx, version: dict, trigger: str, label: str | None = None, restored_from: int | None = None) -> dict:
    """Adds the trigger, the numbers, the requirement results and a copy of the model to a version, in place."""

    state = ctx.state
    n = version["n"]
    directory = Path(state.directory)
    version["trigger"] = trigger if trigger in TRIGGERS else "chat"
    version["product"] = state.product
    version["label"] = label or ""
    version["requirements"] = _requirements(state)
    version["params"] = _params(state)
    version["restored_from"] = restored_from
    version["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if state.product != "drone":
        metrics = _last(ctx, "metrics") or {}
        version["cards"] = metrics.get("cards") or []
    if state.product == "generic" and state.spec:
        version["nodes"] = {part["id"]: part["name"] for part in state.spec["parts"]}
    files = {"glb_url": None, "render_url": None}
    source = _model_source(ctx)
    if source is not None:
        copy = "v" + str(n) + "-" + source.name
        try:
            shutil.copyfile(source, directory / copy)
            files["glb_url"] = "/files/" + state.session_id + "/" + copy
        except OSError:
            pass
    render = _last(ctx, "render", lambda ev: bool(ev.get("png_url")))
    if render:
        files["render_url"] = render["png_url"]
    version["files"] = files
    # What a restore needs and the event does not carry: catalog ids and the frame, or the generic build.
    restore = {"part_ids": {category: part["id"] for category, part in state.selected.items() if part.get("id")}, "cad_params": dict(state.cad_params)}
    if state.product == "generic" and state.spec:
        _write_restorable(state, directory / "versions" / ("v" + str(n)))
        restore["folder"] = str(directory / "versions" / ("v" + str(n)))
    state.version_files[n] = restore
    return version


def _trigger(ctx: Ctx, version: dict, previous: dict | None) -> str:
    trigger = getattr(ctx, "trigger", None) or "chat"
    if trigger == "chat" and previous:
        # A rebuild that fixes a requirement the last version failed answers that failed check.
        failed = {r["id"] for r in previous.get("requirements") or [] if r.get("met") is False}
        if any(r["id"] in failed and r.get("met") is True for r in version.get("requirements") or []):
            return "check_failed"
        # So does a rebuild in the run where an independent judge failed the last version (the fix loop).
        if getattr(ctx, "verdict_failed", None) == previous["n"]:
            return "check_failed"
    return trigger


def bench_version(state) -> int:
    """The number of the version on the bench: the one its bill of materials committed, or the next one.

    A part swapped or a dimension changed since that commit makes the bench the next version, even before its
    bill of materials: a test run on it then judges the design that comes next, not the one committed."""

    if state.versions and (state.bom or {}).get("version") == len(state.versions):
        last = state.versions[-1]
        if _bench(state) == {"parts": last.get("parts") or {}, "params": last.get("params") or {}}:
            return len(state.versions)
    return len(state.versions) + 1


async def commit(ctx: Ctx, label: str | None = None, restored_from: int | None = None) -> dict:
    """Commits the bench as the next version and publishes it."""

    state = ctx.state
    previous = state.versions[-1] if state.versions else None
    metrics = _last(ctx, "metrics") or {}
    built = state.assembly or {}
    if state.product == "drone":
        numbers = {key: state.metrics.get(key) for key, _label, _unit in _DRONE_NUMBERS}
    else:
        numbers = {
            "weight_g": built.get("product_mass_g", metrics.get("weight_g")),
            "price_eur": (state.bom or {}).get("total_eur", metrics.get("price_eur", built.get("cost_eur"))),
            "thrust_to_weight": None,
            "flight_time_min": None,
        }
    n = len(state.versions) + 1
    version = {
        "n": n,
        **numbers,
        "sim": state.last_sim["result"] if state.last_sim else None,
        "parts": _parts(state),
        "diff": [],
        "summary": "",
    }
    trigger = "restore" if restored_from else (getattr(ctx, "trigger", None) or "chat")
    snapshot(ctx, version, trigger, label, restored_from)
    if not restored_from:
        version["trigger"] = _trigger(ctx, version, previous)
    # Verdicts given on this design before its bill of materials; the ones given after it arrive through record_verdict.
    version["verdicts"] = _take_pending(state, version)
    version["diff"] = diff(previous, version)
    weight, price = version.get("weight_g"), version.get("price_eur")
    pieces = [f"{weight:.1f} g" if isinstance(weight, (int, float)) else ""]
    if isinstance(version.get("flight_time_min"), (int, float)):
        pieces.append(f"{version['flight_time_min']:.1f} min")
    pieces.append(f"{price:.2f} €" if isinstance(price, (int, float)) else "")
    version["summary"] = " · ".join(p for p in pieces if p)
    state.versions.append(version)
    if state.bom is not None:
        # The tools after the bill of materials (build guide, firmware) describe this version, not the next.
        state.bom["version"] = n
    await ctx.emit({"type": "version", **version})
    return version


async def after_tool(ctx: Ctx, name: str, args: dict, result: dict) -> None:
    """Hooked into call_tool: every product commits a version after its bill of materials, and an independent
    judge's verdict lands in the book of the version it judged."""

    if name == "bom_build":
        await commit(ctx, label=getattr(ctx, "label", None), restored_from=getattr(ctx, "restored_from", None))
    elif name in JUDGES:
        await record_verdict(ctx, result)


def public(version: dict) -> dict:
    return {key: value for key, value in version.items() if key != "type"}


async def restore(ctx: Ctx, n: int) -> dict:
    """Rebuilds version n through the normal tools and commits it as a new version with restored_from n."""

    from pai_agent.tools.registry import call_tool

    state = ctx.state
    old = next((v for v in state.versions if v["n"] == n), None)
    saved = state.version_files.get(n)
    if old is None or saved is None:
        raise ValueError("No version " + str(n) + " to restore.")
    ctx.trigger = "restore"
    ctx.restored_from = n
    ctx.label = "Restored v" + str(n)

    async def need(name: str, args: dict) -> dict:
        result = await call_tool(ctx, name, args)
        if result.get("ok") is False:
            raise ValueError(name + " failed while restoring v" + str(n) + ": " + str(result.get("error")))
        return result

    if old.get("product", "drone") == "generic":
        folder = Path(saved["folder"])
        ref = json.loads((folder / "reference.json").read_text(encoding="utf-8"))
        await need("product_spec", ref["spec"])
        for part in ref["spec"]["parts"]:
            entry = ref["scripts"].get(part["id"])
            if part["kind"] != "printed" or entry is None:
                continue
            script = (folder / entry["file"]).read_text(encoding="utf-8")
            await need("cad_part", {"part_id": part["id"], "script": script, "_generated": bool(entry.get("generated"))})
        for part_id, pick in ref.get("picks", {}).items():
            await need("part_pick", {"part_id": part_id, **pick})
        await need("assemble", {})
        for check in ref.get("checks", []):
            await need(check["tool"], check.get("args", {}))
        await call_tool(ctx, "blender_render", {})
        # bom_build commits the version through after_tool.
        await need("bom_build", {})
        return state.versions[-1]
    if old.get("product", "drone") != "drone":
        raise ValueError("Restoring a " + str(old.get("product")) + " build is not supported yet.")
    skipped = []
    for category, part_id in saved["part_ids"].items():
        result = await call_tool(ctx, "parts_search", {"category": category, "query": "", "select_id": part_id, "reason": "Restored from v" + str(n) + "."})
        if result.get("ok") is False:
            skipped.append(category)
    if skipped:
        await ctx.chat("agent", "Restoring v" + str(n) + " skipped " + ", ".join(skipped) + ": the catalog no longer has those parts.")
    await need("physics_calc", {})
    if saved["cad_params"]:
        await need("cad_frame", dict(saved["cad_params"]))
    await call_tool(ctx, "simulate_drone", {})
    await call_tool(ctx, "blender_render", {})
    # bom_build commits the version through after_tool.
    await need("bom_build", {})
    return state.versions[-1]
