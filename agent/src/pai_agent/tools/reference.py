"""`reference_load`: Claude's door to the library of reference builds (`references.py`).

Without an id it lists the references. With an id and a live key it returns the reference's
spec and parts as a request, so the orchestrator rebuilds it fresh with the live tools rather
than replaying a saved run. Without a key it puts the saved build on the bench through the
same tools, so the offline demo can start from a known product.
"""

from __future__ import annotations

from pai_agent.context import Ctx
from pai_agent.env import claude_enabled
from pai_agent.references import build_reference, list_references, reference_brief


async def reference_load(ctx: Ctx, args: dict) -> dict:
    ref_id = str(args.get("id") or "").strip()
    if not ref_id:
        rows = list_references()
        return {"ok": True, "detail": str(len(rows)) + " reference build(s)", "references": rows}
    # A live key must not replay the saved story. Hand the spec back so the orchestrator builds it.
    if claude_enabled():
        try:
            visible, model = reference_brief(ref_id)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "detail": str(exc)[:160]}
        return {"ok": True, "id": ref_id, "detail": visible, "request": model}
    try:
        result = await build_reference(ctx, ref_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "detail": str(exc)[:160]}
    ctx.state.finished = True
    detail = result["name"] + f": {float(result['product_mass_g'] or 0):.0f} g, {float(result['cost_eur'] or 0):.2f} €, " + f"{result['requirements_passed']}/{result['requirements']} requirements pass"
    return {**result, "detail": detail}
