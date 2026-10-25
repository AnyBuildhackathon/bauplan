"""Any physical product: spec, bought parts, assembly and parameter changes.

product_spec validates the spec Claude writes and starts the build. cad_part builds
each printed part of it, part_pick binds each bought part to a catalog item, a part found and
validated on the web (`web` true, `pai_agent.web_parts`), or an honest estimate, assemble puts everything together, and the checks in
pai_agent.tools.checks judge the requirements. cad_update changes a printed part's
numbers, rebuilds it from the same script, reassembles and reruns every check so far.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

from pai_agent import assembly as asm
from pai_agent import web_parts
from pai_agent.context import Ctx
from pai_agent.paths import DATA_DIR, PARTS_PATH, REPO_ROOT
from pai_agent.pricing import price
from pai_agent.requirements import attribute, keep_user_limits
from pai_agent.spec import SpecError, find_part, part_of, slug, validate_spec

_CATALOGS: list[dict] | None = None
SPEC_FIELDS = (
    "mass_g", "size_mm", "voltage_v", "power_w", "sleep_power_w", "capacity_mah", "capacity_wh", "stall_torque_nm", "stall_torque_kgcm",
    "rpm", "flow_l_min", "airflow_m3h", "thrust_g", "pull_force_n", "current_a", "max_current_a", "stall_current_a", "holding_torque_nm",
    "range_cm", "diameter_mm", "voltage_min_v", "voltage_max_v",
)


def _fail(message: str, **extra) -> dict:
    return {"ok": False, "error": message, "detail": message[:160], **extra}


def catalog_items() -> list[dict]:
    """Every catalog the repo has, flattened: generic hobby parts, the gripper parts, the maker parts
    from real product pages, the drone parts; then the parts found on the web so far."""

    global _CATALOGS
    if _CATALOGS is None:
        items = []
        sources = [DATA_DIR / "catalogs" / "generic.json", DATA_DIR / "catalogs" / "gripper.json", DATA_DIR / "catalogs" / "makers.json", PARTS_PATH]
        for path in sources:
            data = json.loads(path.read_text(encoding="utf-8"))
            for part in data["parts"]:
                item = {k: v for k, v in part.items() if k not in {"bom_qty", "scene_target", "price_is_sample"}}
                if "size_mm" not in item and all(k in part for k in ("length_mm", "width_mm", "height_mm")):
                    item["size_mm"] = [part["length_mm"], part["width_mm"], part["height_mm"]]
                item["catalog"] = path.stem if path.stem != "parts" else "drone"
                items.append(item)
        _CATALOGS = items
    known = {item["id"] for item in _CATALOGS}
    found = []
    for part in web_parts.found_parts():
        if part["id"] in known:
            continue
        item = {k: v for k, v in part.items() if k not in {"bom_qty", "scene_target", "price_is_sample"}}
        if "size_mm" not in item and all(k in part for k in ("length_mm", "width_mm", "height_mm")):
            item["size_mm"] = [part["length_mm"], part["width_mm"], part["height_mm"]]
        item["catalog"] = "web"
        found.append(item)
    return _CATALOGS + found


def _search(query: str, category: str) -> list[dict]:
    words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if len(w) >= 2]
    scored = []
    for item in catalog_items():
        haystack = " ".join([item["id"], item["name"], item.get("category", ""), item.get("note", ""), *item.get("aliases", [])]).lower()
        score = sum(2 if w in " ".join(item.get("aliases", [])).lower() or w in item["name"].lower() else 1 for w in words if w in haystack)
        if category and item.get("category") == category:
            score += 3
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda row: -row[0])
    return [item for _score, item in scored[:6]]


def _public(item: dict) -> dict:
    shown = {k: item[k] for k in ("id", "name", "category", "unit_price_eur", "shop", "note", "provenance", "source_url", "checked", "estimated") if k in item}
    shown.update({k: item[k] for k in SPEC_FIELDS if k in item})
    return shown


def _quote(state) -> dict:
    spec = state.spec or {}
    return {"text": spec.get("quote") or spec.get("function") or "", "speaker": "You", "time": spec.get("_time", "")}


def _requirement_rows(state, spec: dict) -> list[dict]:
    rows = []
    for requirement in spec["requirements"]:
        said = attribute(state, requirement["quote"], requirement.get("proposed", False))
        rows.append({**requirement, **said, "changed_from": None})
    return rows


def require_spec(state) -> dict:
    if state.product != "generic" or not state.spec:
        raise ValueError("Call product_spec first: this tool works on the product spec.")
    return state.spec


async def product_spec(ctx: Ctx, args: dict) -> dict:
    try:
        spec = validate_spec(args)
    except SpecError as exc:
        return _fail(
            "The spec has " + str(len(exc.problems)) + " problem(s). Fix them and call product_spec again: " + " | ".join(exc.problems),
            problems=exc.problems,
        )
    state = ctx.state
    stamp = time.strftime("%H:%M")
    spec["_time"] = stamp
    # A spec that keeps the name or any part id revises the product on the bench (a reference being changed).
    revision = state.spec is not None and (
        state.spec["id"] == spec["id"] or bool({p["id"] for p in state.spec["parts"]} & {p["id"] for p in spec["parts"]})
    )
    if revision:
        spec["id"] = state.spec["id"]
        refused = keep_user_limits(state, state.requirements, _requirement_rows(state, spec))
        if refused:
            return _fail("A requirement the user typed cannot be loosened: " + " | ".join(refused), problems=refused)
    if not revision:
        state.selected = {}
        state.metrics = {}
        state.last_sim = None
        state.sim_run = 0
        state.missions = {}
        state.stl_path = None
        state.part = None
        state.frame_mass_g = None
        state.bom = None
        state.built = {}
        state.picked = {}
        state.checks = {}
    rebuild: list[str] = []
    previous_checks: dict = {}
    if revision:
        # A revised spec keeps what still holds: a printed part with the same description and material keeps its
        # script (new numbers rebuild it below, without Claude), a part that is still bought keeps its pick.
        before = {p["id"]: p for p in state.spec["parts"]}
        built, picked = {}, {}
        for part in spec["parts"]:
            old = before.get(part["id"])
            if old is None or old["kind"] != part["kind"]:
                continue
            if part["kind"] == "printed" and part["id"] in state.built:
                if (old["description"], old["material"]) != (part["description"], part["material"]):
                    continue
                info = state.built[part["id"]]
                built[part["id"]] = info
                if any(info["params"].get(k) != v for k, v in part["params"].items()):
                    rebuild.append(part["id"])
            elif part["kind"] == "bought" and part["id"] in state.picked:
                picked[part["id"]] = state.picked[part["id"]]
        state.built = built
        state.picked = picked
        previous_checks = state.checks
        state.checks = {}
    state.product = "generic"
    state.spec = spec
    state.assembly = None
    state.assembly_stale = True
    state.bom = None
    rows = _requirement_rows(state, spec)
    if revision:
        # Same limits keep the user's quote; looser ones were refused above or have their consent.
        keep_user_limits(state, state.requirements, rows)
    state.requirements = rows
    state.relax_consent = False
    await ctx.emit(
        {"type": "product", "id": spec["id"], "label": spec["name"], "kind": "generic", "requirements": [r["id"] for r in spec["requirements"]]}
    )
    await emit_cards(ctx)
    from pai_agent.tools.cad_part import cad_part

    for part_id in rebuild:
        info = state.built[part_id]
        part = part_of(spec, part_id)
        result = await cad_part(
            ctx,
            {
                "part_id": part_id,
                "script": info["script"],
                "params": {**info["params"], **part["params"]},
                "_sliders": {k: dict(v) for k, v in info["sliders"].items()},
                "_generated": info["generated"],
            },
        )
        if result.get("ok") is False:
            state.built.pop(part_id, None)
    printed = [p for p in spec["parts"] if p["kind"] == "printed"]
    bought = [p for p in spec["parts"] if p["kind"] == "bought"]
    to_build = [p["id"] for p in printed if p["id"] not in state.built]
    to_pick = [p["id"] for p in bought if p["id"] not in state.picked]
    if state.built:
        await ensure_assembly(ctx)
    rechecked = []
    if revision and previous_checks and not to_build and not to_pick:
        # A revision that keeps every part (a new limit, new wording) is judged again at once,
        # so no requirement row is left blank after the checks already ran.
        state.checks = previous_checks
        rechecked = await rerun_checks(ctx)
    return {
        "ok": True,
        "detail": spec["name"] + ": " + str(len(printed)) + " printed, " + str(len(bought)) + " bought, " + str(len(spec["requirements"])) + " requirements",
        "product": spec["id"],
        "parts": [{"id": p["id"], "kind": p["kind"], "name": p["name"]} for p in spec["parts"]],
        "requirements": [{k: r[k] for k in ("id", "check", "text")} for r in spec["requirements"]],
        "kept": sorted(set(state.built) | set(state.picked)),
        "rebuilt_with_new_params": rebuild,
        "to_build": to_build,
        "to_pick": to_pick,
        "rechecked": rechecked,
        "next": "cad_part for each part in to_build, part_pick for each in to_pick, then assemble and the checks."
        if to_build or to_pick
        else "Every part is kept and the earlier checks ran again (rechecked); run any new check the revised requirements need.",
    }


async def part_pick(ctx: Ctx, args: dict) -> dict:
    try:
        spec = require_spec(ctx.state)
    except ValueError as exc:
        return _fail(str(exc))
    part = find_part(spec, str(args.get("part_id") or ""), "bought")
    part_id = part["id"] if part else ""
    if part is None:
        bought = ", ".join(p["id"] for p in spec["parts"] if p["kind"] == "bought") or "none"
        return _fail("part_id must be a bought part of the spec. Bought parts: " + bought + ".")
    reason = str(args.get("reason") or "").strip()
    select_id = str(args.get("select_id") or "").strip()
    estimate = args.get("estimate")
    if args.get("web") and not select_id and not isinstance(estimate, dict):
        need = str(args.get("query") or part["query"] or part["name"])
        discovered = await web_parts.discover(str(args.get("category") or part.get("category") or "part"), need)
        if not discovered.get("ok"):
            return _fail(discovered["error"], problems=discovered.get("problems", []))
        found = discovered["part"]
        return {
            "ok": True,
            "detail": part["name"] + ": web find " + found["name"],
            "matches": [_public({**found, "size_mm": found.get("size_mm")})],
            "source": web_parts.provenance_line(found),
            "next": "part_pick again with select_id " + found["id"] + " to use it.",
        }
    if not select_id and not isinstance(estimate, dict):
        query = str(args.get("query") or part["query"] or part["name"])
        matches = _search(query, str(args.get("category") or part.get("category") or ""))
        return {
            "ok": True,
            "detail": part["name"] + ": " + str(len(matches)) + " catalog match(es)",
            "matches": [_public(m) for m in matches],
            "next": "part_pick again with select_id, or with estimate {name, mass_g, unit_price_eur} when nothing fits.",
        }
    if select_id:
        item = next((dict(m) for m in catalog_items() if m["id"] == select_id), None)
        if item is None:
            return _fail("select_id " + select_id + " is not in the catalogs. Search with part_pick and a query first.")
        item["price_source"] = "catalog" if item.get("price_is_sample") is False else "sample"
    else:
        name = str(estimate.get("name") or part["name"]).strip()
        try:
            item = {
                "id": "est-" + slug(name),
                "name": name,
                "category": part.get("category") or "estimate",
                "mass_g": float(estimate["mass_g"]),
                "unit_price_eur": float(estimate["unit_price_eur"]),
                "shop": str(estimate.get("shop") or "estimate"),
                "url": str(estimate.get("url") or ""),
                "note": str(estimate.get("note") or "No catalog part fits; mass and price are estimates."),
                "price_source": "estimated",
            }
        except (KeyError, TypeError, ValueError):
            return _fail("estimate needs name, mass_g and unit_price_eur as numbers.")
        for key in SPEC_FIELDS:
            if key in estimate and key not in item:
                item[key] = estimate[key]
    item = price({**item, "query": part["query"], "reason": reason})
    ctx.state.picked[part_id] = item
    ctx.state.assembly_stale = True
    ctx.state.bom = None
    await ctx.emit(
        {
            "type": "part",
            "category": part_id,
            "id": item["id"],
            "name": item["name"],
            "mass_g": item.get("mass_g"),
            "size_mm": item.get("size_mm"),
            "diameter_mm": None,
            "why": _quote(ctx.state),
            "reason": reason,
            "warnings": [],
        }
    )
    result = {
        "ok": True,
        "detail": part["name"] + ": " + item["name"] + (" (estimated price)" if item["price_source"] == "estimated" else ""),
        "picked": _public(item),
        "price_source": item["price_source"],
    }
    if ctx.state.checks:
        result["checks"] = await rerun_checks(ctx)
    return result


async def ensure_assembly(ctx: Ctx) -> dict:
    state = ctx.state
    if state.assembly is not None and not state.assembly_stale:
        return state.assembly
    spec = require_spec(state)
    built = await asyncio.to_thread(asm.build, spec, state.built, state.picked, Path(state.directory))
    state.assembly = built
    state.assembly_stale = False
    state.stl_path = (Path(state.directory) / built["stl"]).relative_to(REPO_ROOT).as_posix()
    state.cad_builds += 1
    await _emit_assembly(ctx)
    await emit_cards(ctx)
    return built


def _sliders(state) -> dict:
    sliders = {}
    for part in state.spec["parts"]:
        info = state.built.get(part["id"])
        if not info:
            continue
        for key, slider in info["sliders"].items():
            label = part["name"] + " · " + re.sub(r"_(mm|deg|g)$", "", key).replace("_", " ")
            sliders[part["id"] + "." + key] = {**slider, "label": label}
    return sliders


def _tree(state) -> list[dict]:
    spec = state.spec
    groups = {a["id"]: {"id": a["id"], "label": a["name"], "children": []} for a in spec["assemblies"]}
    loose = []
    for part in spec["parts"]:
        tag = {"printed": "", "bought": " (bought)", "external": " (load)"}[part["kind"]]
        label = part["name"] + (" ×" + str(part["qty"]) if part["qty"] > 1 else "") + tag
        if part["kind"] == "printed":
            info = state.built.get(part["id"])
            label += " · " + (f"{info['mass_g']:.0f} g {info['material']}" if info else "not built")
        elif part["kind"] == "bought":
            item = state.picked.get(part["id"])
            label += " · " + (item["name"] if item else "not picked")
        node = {"id": part["id"], "label": label, "children": []}
        (groups[part["assembly"]]["children"] if part["assembly"] in groups else loose).append(node)
    return [{"id": spec["id"], "label": spec["name"], "children": [*groups.values(), *loose]}]


async def _emit_assembly(ctx: Ctx) -> None:
    state = ctx.state
    built = state.assembly
    n = state.cad_builds
    session = state.session_id
    directory = Path(state.directory)
    scripts = []
    for part in state.spec["parts"]:
        info = state.built.get(part["id"])
        if info:
            scripts.append("# ---- " + part["name"] + " (" + part["id"] + ", " + info["material"] + ") ----\n" + info["script"])
    (directory / "assembly-scripts.py").write_text("\n\n".join(scripts), encoding="utf-8")
    materials = sorted({info["material"] for info in state.built.values()})
    attempts = sum(info["attempts"] for info in state.built.values())
    await ctx.emit(
        {
            "type": "cad",
            "source": "freecad",
            "tree": _tree(state),
            "params": _sliders(state),
            "glb_url": "/files/" + session + "/" + built["glb"] + "?build=" + str(n),
            "stl_url": "/files/" + session + "/" + built["stl"] + "?build=" + str(n),
            "step_url": None,
            "view_png_url": None,
            "script_url": "/files/" + session + "/assembly-scripts.py?build=" + str(n),
            "part": {
                "name": state.spec["name"],
                "material": " + ".join(materials),
                "mass_g": built["printed_mass_g"],
                "bbox_mm": built["bbox_mm"],
                "attempts": attempts,
                "generated": any(info["generated"] for info in state.built.values()),
            },
            "assembly": True,
            "bodies": _bodies(state),
        }
    )


def _bodies(state) -> list[dict]:
    """One row per GLB node: which spec part it is, its assembly group and its mass, for the explode view."""

    parts = {part["id"]: part for part in state.spec["parts"]}
    rows = []
    for body in state.assembly.get("bodies", []):
        if not body.get("stl"):
            continue
        part = parts.get(body["part_id"], {})
        rows.append(
            {
                "name": body["name"],
                "part_id": body["part_id"],
                "part_name": part.get("name", body["name"]),
                "kind": body["kind"],
                "group": part.get("assembly") or None,
                "mass_g": round(float(body.get("mass_g") or 0.0), 1),
            }
        )
    return rows


async def assemble(ctx: Ctx, args: dict) -> dict:
    try:
        spec = require_spec(ctx.state)
    except ValueError as exc:
        return _fail(str(exc))
    for part_id, placement in (args.get("placements") or {}).items():
        part = part_of(spec, slug(part_id))
        if part is None or not isinstance(placement, dict):
            return _fail("placements keys must be part ids of the spec, values {position_mm, rotation_deg}.")
        for key in ("position_mm", "rotation_deg"):
            value = placement.get(key)
            if value is not None:
                if not isinstance(value, list) or len(value) != 3:
                    return _fail(key + " must be three numbers.")
                part[key] = [float(v) for v in value]
    missing = [p["name"] for p in spec["parts"] if p["kind"] == "printed" and p["id"] not in ctx.state.built]
    unpicked = [p["name"] for p in spec["parts"] if p["kind"] == "bought" and p["id"] not in ctx.state.picked]
    ctx.state.assembly_stale = True
    ctx.state.bom = None
    try:
        built = await ensure_assembly(ctx)
    except ValueError as exc:
        return _fail(str(exc))
    detail = (
        f"{built['product_mass_g']:.0f} g, {built['cost_eur']:.2f} €, "
        + " x ".join(f"{v:.0f}" for v in built["size_mm"])
        + " mm"
    )
    return {
        "ok": True,
        "detail": detail,
        "product_mass_g": built["product_mass_g"],
        "total_mass_g_with_loads": built["total_mass_g"],
        "cost_eur": built["cost_eur"],
        "size_mm": built["size_mm"],
        "bbox_mm": built["bbox_mm"],
        "com_mm": built["com_mm"],
        "footprint_mm": built["footprint_mm"],
        "parts": [{k: b[k] for k in ("part_id", "name", "kind", "mass_g", "bbox_mm")} for b in built["bodies"]],
        "not_built": missing,
        "not_picked": unpicked,
        "warnings": built["warnings"],
    }


async def cad_update(ctx: Ctx, args: dict) -> dict:
    """Changes numbers of a built printed part: same script, new params, then reassemble and recheck."""

    from pai_agent.tools.cad_part import cad_part

    try:
        spec = require_spec(ctx.state)
    except ValueError as exc:
        return _fail(str(exc))
    found = find_part(spec, str(args.get("part_id") or ""), "printed")
    part_id = found["id"] if found else slug(args.get("part_id") or "")
    info = ctx.state.built.get(part_id)
    if info is None:
        return _fail("part_id must be a built printed part. Built: " + (", ".join(ctx.state.built) or "none") + ".")
    changes = args.get("params")
    if not isinstance(changes, dict) or not changes:
        return _fail("params must name the numbers to change, e.g. {\"depth_mm\": 110}.")
    params = dict(info["params"])
    sliders = {k: dict(v) for k, v in info["sliders"].items()}
    for key, value in changes.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            return _fail(str(key) + " must be a number.")
        if key not in params:
            return _fail(str(key) + " is not a parameter of " + info["name"] + ". Parameters: " + ", ".join(params) + ".")
        params[key] = number
        slider = sliders.get(key)
        if slider is not None:
            slider["min"] = min(slider["min"], round(number * 0.5, 1))
            slider["max"] = max(slider["max"], round(number * 1.5, 1))
    part = part_of(spec, part_id)
    if part is not None and part.get("size_mm"):
        # The envelope check follows the change: a deeper base is meant to be deeper.
        scale = max(abs(params[k]) / max(abs(info["params"][k]), 1e-6) for k in changes)
        part["size_mm"] = [round(v * max(scale, 1.0), 2) for v in part["size_mm"]]
    result = await cad_part(
        ctx,
        {
            "part_id": part_id,
            "name": info["name"],
            "material": info["material"],
            "script": info["script"],
            "params": params,
            "_sliders": sliders,
            "_generated": info["generated"],
        },
    )
    if result.get("ok") is False:
        return result
    out = {"ok": True, "detail": info["name"] + ": " + ", ".join(f"{k} {float(v):g}" for k, v in changes.items()), "part": result}
    if ctx.state.checks:
        out["checks"] = await rerun_checks(ctx)
    else:
        await ensure_assembly(ctx)
    return out


async def rerun_checks(ctx: Ctx) -> list[dict]:
    """Runs every check again that has run before, in the same order, with the same arguments."""

    from pai_agent.tools.checks import CHECK_TOOLS as BASE
    from pai_agent.tools.checks_more import CHECK_TOOLS as MORE

    CHECK_TOOLS = {**BASE, **MORE}
    await ensure_assembly(ctx)
    results = []
    for key, entry in list(ctx.state.checks.items()):
        function = CHECK_TOOLS[entry["tool"]]
        result = await function(ctx, dict(entry["args"]))
        results.append({"check": key, "result": result.get("result"), "detail": result.get("detail")})
    return results


async def emit_cards(ctx: Ctx) -> None:
    from pai_agent.tools.checks import metric_cards

    cards = metric_cards(ctx.state)
    built = ctx.state.assembly or {}
    await ctx.emit(
        {
            "type": "metrics",
            "weight_g": built.get("product_mass_g", 0.0),
            "price_eur": next((c["value"] for c in cards if c["key"] == "cost_eur"), built.get("cost_eur", 0.0)),
            "cards": cards,
        }
    )
