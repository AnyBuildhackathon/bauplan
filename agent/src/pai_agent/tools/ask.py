"""`ask_user`: Mechanic asks the room a multiple-choice question before building on a contradiction.

Typical use is two meetings that disagree (the kickoff says 8 minutes of flight time, the
review says 10). The question goes through `ctx.asker` (`Session.ask`), which shows it in the
chat and waits for a click, a spoken or typed answer, or the timeout; the default option is
the newer statement. Without an asker (a sub-agent or a test) the default is taken at once.
"""

from __future__ import annotations

from pai_agent.context import Ctx


async def ask_user(ctx: Ctx, args: dict) -> dict:
    text = str(args.get("question") or "").strip()
    raw = args.get("options") or []
    options = []
    for index, option in enumerate(raw):
        if isinstance(option, dict) and option.get("label"):
            options.append({"id": str(option.get("id") or index), "label": str(option["label"])})
        elif isinstance(option, str) and option.strip():
            options.append({"id": str(index), "label": option.strip()})
    if not text or len(options) < 2:
        message = "question and at least two options are required."
        return {"ok": False, "error": message, "detail": message}
    default = str(args.get("default_id") or options[0]["id"])
    if default not in {option["id"] for option in options}:
        default = options[0]["id"]
    if ctx.asker is None:
        answer = default
    else:
        answer = await ctx.asker({"text": text, "options": options, "default_id": default})
    label = next(option["label"] for option in options if option["id"] == answer)
    return {"ok": True, "detail": "Answer: " + label, "answer_id": answer, "answer": label}
