"""Judges one finished run: each expected check passes or fails on the build state and its events."""

from __future__ import annotations

from pai_agent.state import BuildState

LABELS = {
    "built": "Build finished",
    "cad": "CAD geometry",
    "bom": "Bill of materials",
    "render": "Studio render",
}


def judge(check: str, state: BuildState, events: list[dict]) -> dict:
    """`built`, `cad`, `bom`, `render`, or `req:<id or check>`: that requirement exists and is met."""

    if check == "built":
        ok = state.finished
        return _row(check, ok, "finished" if ok else "the run did not finish")
    if check == "cad":
        ok = bool(state.stl_path)
        return _row(check, ok, "geometry written" if ok else "no CAD geometry")
    if check == "bom":
        total = (state.bom or {}).get("total_eur")
        ok = state.bom is not None
        return _row(check, ok, (f"{float(total):.2f} €" if isinstance(total, (int, float)) else "built") if ok else "no bill of materials")
    if check == "render":
        ok = any(e.get("type") == "render" for e in events)
        return _row(check, ok, "rendered" if ok else "no render")
    if check.startswith("req:"):
        key = check[4:]
        req = next((r for r in state.requirements if r.get("id") == key or r.get("check") == key), None)
        if req is None:
            return _row(check, False, "requirement missing", "Requirement " + key)
        met = req.get("_met")
        detail = req.get("_shown_detail") or req.get("_detail") or ("met" if met else "not checked" if met is None else "not met")
        return _row(check, met is True, str(detail), str(req.get("text") or key))
    raise ValueError("unknown check " + check)


def _row(check: str, ok: bool, detail: str, label: str | None = None) -> dict:
    return {"id": check, "label": label or LABELS.get(check, check), "pass": bool(ok), "detail": detail}


def usage(events: list[dict]) -> dict:
    """Tokens and cost of every agent in the run: the last `agent` event of each id carries its totals."""

    last: dict[str, dict] = {}
    for event in events:
        if event.get("type") == "agent":
            last[str(event.get("id"))] = event
    return {
        "input_tokens": sum(int(e.get("input_tokens") or 0) for e in last.values()),
        "output_tokens": sum(int(e.get("output_tokens") or 0) for e in last.values()),
        "cache_read_tokens": sum(int(e.get("cache_read_tokens") or 0) for e in last.values()),
        "cost_usd": round(sum(float(e.get("cost_usd") or 0) for e in last.values()), 4),
        "agents": len(last),
        "model_rounds": sum(int(e.get("rounds") or 0) for e in last.values()),
    }


def retries(events: list[dict]) -> dict:
    """Tool calls that came back with an error (the agent corrects and calls again) and fix rounds (cad_update)."""

    tools = [e for e in events if e.get("type") == "tool" and e.get("status") != "running"]
    errors = sum(1 for e in tools if e.get("status") == "error")
    fixes = sum(1 for e in tools if e.get("name") == "cad_update")
    # Without FreeCAD a printed part becomes a CadQuery block: its mass and shape are only rough.
    blocks = sum(1 for e in tools if e.get("status") == "ok" and "CadQuery block" in str(e.get("detail")))
    return {"tool_calls": len(tools), "tool_errors": errors, "fixes": fixes, "retries": errors + fixes, "cad_fallbacks": blocks}
