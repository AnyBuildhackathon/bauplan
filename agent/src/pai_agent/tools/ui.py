"""Pointer, drawings, and the mascot. Targets match the 3D scene."""

from __future__ import annotations

from pai_agent.context import Ctx
from pai_agent.scene import DRAW_KINDS, MASCOT_STATES, TARGETS


def _bad_target(target: object) -> dict | None:
    if target not in TARGETS:
        message = "target must be one of " + ", ".join(TARGETS) + "."
        return {"ok": False, "error": message, "detail": message}
    return None


async def ui_point_at(ctx: Ctx, args: dict) -> dict:
    target = args.get("target")
    invalid = _bad_target(target)
    if invalid:
        return invalid
    label = str(args.get("label", ""))
    await ctx.emit({"type": "point", "target": target, "label": label})
    return {"ok": True, "detail": str(target)}


async def ui_draw(ctx: Ctx, args: dict) -> dict:
    kind = args.get("kind")
    target = args.get("target")
    if kind not in DRAW_KINDS:
        message = "kind must be halo, arrow, circle or note."
        return {"ok": False, "error": message, "detail": message}
    invalid = _bad_target(target)
    if invalid:
        return invalid
    text = str(args.get("text", ""))
    await ctx.emit({"type": "draw", "kind": kind, "target": target, "text": text})
    return {"ok": True, "detail": str(kind) + " " + str(target)}


async def mascot_say(ctx: Ctx, args: dict) -> dict:
    state = args.get("state")
    say = str(args.get("say", "")).strip()
    if state not in MASCOT_STATES:
        message = "state must be ruhig, denkt, erklaert, freut_sich or besorgt."
        return {"ok": False, "error": message, "detail": message}
    if not say:
        message = "say is missing."
        return {"ok": False, "error": message, "detail": message}
    await ctx.emit({"type": "mascot", "state": state, "say": say})
    return {"ok": True, "detail": str(state)}
