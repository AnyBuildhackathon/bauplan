"""Runs the bench: each prompt goes through the real flow (orchestrator, tools, checks) on its own fresh bench.

    uv run python -m bench.run                 # live with ANTHROPIC_API_KEY, else mock (the recorded subset)
    uv run python -m bench.run --limit 8 -j 3  # the first 8 prompts, three at a time
    uv run python -m bench.run --only phone-stand,desk-lamp --timeout 600 --budget 3600

Writes bench/results/<mode>.json, which GET /api/bench serves to the Bench drawer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
PROMPTS_PATH = BENCH_DIR / "prompts.json"
RESULTS_DIR = BENCH_DIR / "results"


def load_prompts() -> list[dict]:
    return json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))


async def run_one(item: dict, timeout: float) -> dict:
    """One prompt on a fresh bench. Questions take their default answer: nobody sits at a bench run."""

    from bench.judge import judge, retries, usage
    from pai_agent.bus import EventBus
    from pai_agent.context import Ctx
    from pai_agent.orchestrator import run_prompt
    from pai_agent.session import _new_state

    bus = EventBus()
    state = _new_state()

    async def asker(question: dict) -> str:
        return str(question.get("default_id") or question["options"][0]["id"])

    ctx = Ctx(bus, state, auto_steps=True, asker=asker)
    ctx.trigger = "chat"
    ctx.label = "Bench: " + item["title"]
    started = time.monotonic()
    status, error = "done", None
    try:
        await asyncio.wait_for(run_prompt(ctx, item["prompt"], []), timeout)
    except TimeoutError:
        status, error = "timeout", f"stopped after {timeout:g} s"
    except Exception as exc:  # noqa: BLE001 - a crashed run is a failed result, the bench goes on
        status, error = "error", str(exc)[:300]
    elapsed = time.monotonic() - started
    events = list(bus.events)
    checks = [judge(check, state, events) for check in item["checks"]]
    passed = sum(1 for c in checks if c["pass"])
    version = next((e for e in reversed(events) if e.get("type") == "version"), {})
    return {
        "id": item["id"],
        "title": item["title"],
        "category": item.get("category", ""),
        "prompt": item["prompt"],
        "status": status,
        "error": error,
        "pass": status == "done" and passed == len(checks),
        "checks": checks,
        "checks_passed": passed,
        "checks_total": len(checks),
        "time_s": round(elapsed, 1),
        **retries(events),
        **usage(events),
        "product": (state.spec or {}).get("name") or version.get("label") or state.product,
        "mass_g": _mass(state),
        "parts_eur": (state.bom or {}).get("total_eur"),
        "session_id": state.session_id,
    }


def _mass(state) -> float | None:
    for key in ("product_mass_g", "weight_g", "mass_g"):
        value = (state.metrics or {}).get(key)
        if isinstance(value, (int, float)):
            return round(float(value), 1)
    totals = (state.checks or {}).get("totals") or {}
    value = totals.get("product_mass_g") or totals.get("mass_g")
    return round(float(value), 1) if isinstance(value, (int, float)) else None


async def run_bench(items: list[dict], concurrency: int, timeout: float, budget: float) -> list[dict]:
    """At most `concurrency` runs at once, each in its own process: the CAD kernels are not safe to share between runs.
    A prompt that cannot start before the budget runs out is skipped."""

    gate = asyncio.Semaphore(max(1, concurrency))
    deadline = time.monotonic() + budget

    async def one(item: dict) -> dict:
        async with gate:
            left = deadline - time.monotonic()
            if left <= 1:
                return _skipped(item)
            result = await _in_worker(item, min(timeout, left))
            mark = "PASS" if result["pass"] else result["status"].upper() if result["status"] != "done" else "FAIL"
            print(f"  {mark:<7} {item['id']:<18} {result['checks_passed']}/{result['checks_total']} checks  {result['time_s']:>6.1f} s  ${result['cost_usd']:.3f}", flush=True)
            return result

    return list(await asyncio.gather(*(one(item) for item in items)))


async def _in_worker(item: dict, timeout: float) -> dict:
    """`bench.run --worker <id>` runs one prompt and writes its result; the parent kills it a little after its own timeout."""

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.json"
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "bench.run", "--worker", item["id"], "--timeout", str(timeout), "--out", str(out),
            cwd=str(BENCH_DIR.parent),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout + 30)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return {**_skipped(item), "status": "timeout", "error": f"stopped after {timeout:g} s", "time_s": round(time.monotonic() - started, 1)}
        if out.is_file():
            return json.loads(out.read_text(encoding="utf-8"))
        tail = (err or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or ["worker exited " + str(proc.returncode)]
        return {**_skipped(item), "status": "error", "error": tail[0][:300], "time_s": round(time.monotonic() - started, 1)}


def _skipped(item: dict) -> dict:
    return {
        "id": item["id"],
        "title": item["title"],
        "category": item.get("category", ""),
        "prompt": item["prompt"],
        "status": "skipped",
        "error": "time budget used up",
        "pass": False,
        "checks": [],
        "checks_passed": 0,
        "checks_total": len(item["checks"]),
        "time_s": 0.0,
        "tool_calls": 0,
        "tool_errors": 0,
        "fixes": 0,
        "retries": 0,
        "cad_fallbacks": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cost_usd": 0.0,
        "agents": 0,
        "model_rounds": 0,
        "product": None,
        "mass_g": None,
        "parts_eur": None,
        "session_id": None,
    }


def summarize(results: list[dict]) -> dict:
    ran = [r for r in results if r["status"] != "skipped"]
    valid = [r for r in ran if r["pass"]]
    cost = sum(r["cost_usd"] for r in ran)
    checks_total = sum(r["checks_total"] for r in ran)
    return {
        "prompts": len(results),
        "ran": len(ran),
        "passed": len(valid),
        "pass_rate": round(len(valid) / len(ran), 3) if ran else 0.0,
        "checks_passed": sum(r["checks_passed"] for r in ran),
        "checks_total": checks_total,
        "check_pass_rate": round(sum(r["checks_passed"] for r in ran) / checks_total, 3) if checks_total else 0.0,
        "cost_usd": round(cost, 4),
        "cost_per_product_usd": round(cost / len(ran), 4) if ran else 0.0,
        "cost_per_valid_product_usd": round(cost / len(valid), 4) if valid else None,
        "time_s": round(sum(r["time_s"] for r in ran), 1),
        "retries": sum(r["retries"] for r in ran),
        "cad_fallbacks": sum(r["cad_fallbacks"] for r in ran),
        "input_tokens": sum(r["input_tokens"] for r in ran),
        "output_tokens": sum(r["output_tokens"] for r in ran),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench.run", description="AnyBuild Bench: build every prompt and judge its checks.")
    parser.add_argument("--mock", action="store_true", help="force mock mode (PAI_FORCE_MOCK=1) even with a key")
    parser.add_argument("--all", action="store_true", help="in mock mode, also run prompts without a recorded mock (they fall back to the drone story)")
    parser.add_argument("--only", default="", help="comma-separated prompt ids")
    parser.add_argument("--limit", type=int, default=0, help="run only the first N selected prompts")
    parser.add_argument("-j", "--concurrency", type=int, default=2, help="runs at the same time (default 2)")
    parser.add_argument("--timeout", type=float, default=900, help="seconds one prompt may take (default 900)")
    parser.add_argument("--budget", type=float, default=3600, help="seconds for the whole bench; later prompts are skipped (default 3600)")
    parser.add_argument("--out", default="", help="results file (default bench/results/<mode>.json)")
    parser.add_argument("--worker", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.mock:
        os.environ["PAI_FORCE_MOCK"] = "1"
    os.environ.setdefault("PAI_WARM", "0")
    from pai_agent import settings
    from pai_agent.env import claude_enabled

    live = claude_enabled()
    mode = "live" if live else "mock"
    items = load_prompts()
    if args.worker:
        item = next(item for item in items if item["id"] == args.worker)
        result = asyncio.run(run_one(item, args.timeout))
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")
        return 0
    if args.only:
        wanted = {p.strip() for p in args.only.split(",") if p.strip()}
        unknown = wanted - {item["id"] for item in items}
        if unknown:
            parser.error("unknown prompt id(s): " + ", ".join(sorted(unknown)))
        items = [item for item in items if item["id"] in wanted]
    elif not live and not args.all:
        # Without a key only the products the mock story has recorded give a meaningful result.
        items = [item for item in items if item.get("mock")]
    if args.limit:
        items = items[: args.limit]
    config = settings.current()
    print(f"AnyBuild Bench · {mode} · {len(items)} prompt(s) · {args.concurrency} at a time · budget {args.budget:g} s", flush=True)
    started = datetime.now(timezone.utc)
    results = asyncio.run(run_bench(items, args.concurrency, args.timeout, args.budget))
    report = {
        "mode": mode,
        "note": None if live else "Mock run: the recorded mock story without Claude, not a measure of the live agent.",
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "orchestrator_model": config["orchestrator_model"] if live else None,
        "subagent_model": config["subagent_model"] if live else None,
        "concurrency": args.concurrency,
        "prompts_total": len(load_prompts()),
        "timeout_s": args.timeout,
        "budget_s": args.budget,
        "summary": summarize(results),
        "results": results,
    }
    out = Path(args.out) if args.out else RESULTS_DIR / (mode + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(out)
    s = report["summary"]
    print(f"{s['passed']}/{s['ran']} valid products ({s['pass_rate']:.0%}), {s['checks_passed']}/{s['checks_total']} checks, ${s['cost_usd']:.2f} total, ${s['cost_per_product_usd']:.3f} per product", flush=True)
    print("Results: " + str(out), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
