"""Stress test: the current product in 50 randomized MuJoCo worlds.

For the drone, each world draws its own mass (+-15 %), motor strength (-25..0 %),
a wind gust of up to 6 m/s with a downdraft share, and sensor noise. The drone
hovers 1 m up for 10 s and the gust hits it. A world is survived when it never
crashes, never drifts more than 0.35 m off its spot, and is back at height
for the last half second. The gripper's worlds (pad friction, servo strength,
payload, arm shake, servo jitter) live in stress_grip.py and run here in the backend.

The drone's worlds fly in the browser, on the MuJoCo WASM workers of the training
module (`web/src/sim`): `stress_test` publishes a queued `stress` event, the first
dashboard tab that sees it claims the job, flies the seeded worlds with the
training module's drone episode, and posts the outcomes back to `/api/stress/...`.
The backend keeps the worlds, the scoring, the worst world and the weak point.

The controller is the trained one: the `gains` of the last `training` event (the
same source firmware reads), or the tool's `gains` argument; without a training
result the default gains below fly and the card says so.
"""

from __future__ import annotations

import asyncio
import math
import random
import re
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, fields

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from pai_agent.context import Ctx
from pai_agent.tools.browser_train import (
    claim_timeout,
    product_spec,
    run_timeout,
    stall_timeout,
)
from pai_agent.tools.physics import PhysicsError, compute

# The browser drone hovers at 1 m (DRONE_TARGET in web/src/sim/drone.ts).
_TARGET_Z = 1.0
_DRIFT_LIMIT_M = 0.35
# Lost height that still counts as holding it in the last half second, and the drop that uses up the margin.
_SAG_M = 0.15
_DROP_M = 0.42

WORLDS = 50
SEED = 7


@dataclass(frozen=True)
class ControllerGains:
    """Cascaded hover controller in the training module's exported units: height and position in 1/s^2, 1/s^3 and 1/s, attitude in N m/rad and N m s/rad."""

    kp_z: float = 16.0
    ki_z: float = 0.0
    kd_z: float = 7.0
    # A soft position hold, as an untuned flight controller ships; training stiffens it.
    kp_xy: float = 0.35
    kd_xy: float = 0.30
    kp_att: float = 0.0016
    kd_att: float = 0.00018


def gains_from(raw: dict | None) -> tuple[ControllerGains, bool]:
    """Known keys override the defaults; anything else (the Betaflight roll and pitch) is ignored. True when any key was taken."""

    if not isinstance(raw, dict):
        return ControllerGains(), False
    known = {f.name for f in fields(ControllerGains)}
    picked: dict[str, float] = {}
    for key, value in raw.items():
        if key in known and isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if math.isfinite(number) and number > 0:
                picked[key] = number
    return ControllerGains(**picked), bool(picked)


def trained_gains(ctx: Ctx, override: dict | None) -> tuple[ControllerGains, str]:
    """The gains to stress: the tool argument, then the `gains` of the last drone `training` event, else the defaults."""

    gains, found = gains_from(override)
    if found:
        return gains, "trained"
    for event in reversed(ctx.bus.events):
        if event.get("type") != "training" or not isinstance(event.get("gains"), dict):
            continue
        if event.get("product", "drone") != "drone":
            break
        gains, found = gains_from(event["gains"])
        if found:
            return gains, "trained"
        break
    return ControllerGains(), "default"


@dataclass(frozen=True)
class World:
    i: int
    mass_scale: float
    motor_scale: float
    gust_mps: float
    gust_dir_deg: float
    gust_start_s: float
    gust_len_s: float
    downdraft_share: float
    noise_m: float


def sample_worlds(n: int = WORLDS, seed: int = SEED) -> list[World]:
    rng = random.Random(seed)
    worlds = []
    for i in range(n):
        worlds.append(
            World(
                i=i + 1,
                mass_scale=rng.uniform(0.85, 1.15),
                motor_scale=rng.uniform(0.75, 1.0),
                gust_mps=rng.uniform(0.0, 6.0),
                gust_dir_deg=rng.uniform(0.0, 360.0),
                gust_start_s=rng.uniform(1.6, 2.4),
                gust_len_s=rng.uniform(0.8, 2.0),
                downdraft_share=rng.uniform(0.2, 0.6),
                noise_m=rng.uniform(0.0, 0.02),
            )
        )
    return worlds


def browser_outcome(metrics: dict, trajectory: list) -> dict:
    """One world as the browser flew it: its readouts become pass, reason and margin."""

    def number(key: str) -> float:
        value = metrics.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else float("nan")

    drift, low, tail = number("drift_m"), number("low_z_m"), number("tail_z_m")
    finite = all(math.isfinite(v) for v in (drift, low, tail)) and all(
        isinstance(v, (int, float)) and math.isfinite(v) for point in trajectory for v in point
    )
    if not finite or metrics.get("crashed") is True or metrics.get("error") is True:
        reason = "crashed"
    elif drift > _DRIFT_LIMIT_M:
        reason = "drifted"
    elif tail < _TARGET_Z - _SAG_M:
        reason = "sagged"
    else:
        reason = ""
    # 1 is a perfect hover; at 0 or below the world is lost.
    margin = min(1 - drift / _DRIFT_LIMIT_M, 1 - (_TARGET_Z - low) / _DROP_M) if finite else -1.0
    if reason:
        margin = min(margin, 0.0)
    return {
        "pass": not reason,
        "reason": reason,
        "drift_m": round(drift, 3) if math.isfinite(drift) else 0.0,
        "low_z_m": round(low, 3) if math.isfinite(low) else 0.0,
        "margin": round(margin, 3),
        "trajectory": trajectory,
    }


class StressError(Exception):
    """A stress test that could not finish; the message goes on the card."""


def world_row(world: World, outcome: dict) -> dict:
    return {
        "i": world.i,
        "pass": outcome["pass"],
        "reason": outcome["reason"],
        "mass_pct": round((world.mass_scale - 1) * 100, 1),
        "motor_pct": round((world.motor_scale - 1) * 100, 1),
        "gust_mps": round(world.gust_mps, 2),
        "downdraft_pct": round(world.downdraft_share * 100),
        "gust_dir_deg": round(world.gust_dir_deg),
        "gust_start_s": round(world.gust_start_s, 2),
        "gust_len_s": round(world.gust_len_s, 2),
        "noise_cm": round(world.noise_m * 100, 2),
        "drift_m": outcome["drift_m"],
        "low_z_m": outcome["low_z_m"],
        "margin": outcome["margin"],
    }


# How hard each randomized factor pushed a world, 0 (mild) to 1 (the worst draw).
_SEVERITY = {
    "gust": lambda r: r["gust_mps"] / 6.0,
    "motor": lambda r: -r["motor_pct"] / 25.0,
    "mass": lambda r: (r["mass_pct"] + 15) / 30.0,
    "noise": lambda r: r["noise_cm"] / 2.0,
}


def weakest_point(rows: list[dict]) -> tuple[str | None, str]:
    """The factor that separates lost worlds from survived ones, as one plain sentence."""

    lost = [r for r in rows if not r["pass"]]
    if not rows:
        return None, "No worlds were flown."
    if not lost:
        closest = min(rows, key=lambda r: r["margin"])
        return None, (
            f"It survived all {len(rows)} worlds; the closest call was a {closest['gust_mps']:.1f} m/s gust "
            f"with motors {abs(closest['motor_pct']):.0f} % weak, where it drifted {closest['drift_m'] * 100:.0f} cm."
        )
    kept = [r for r in rows if r["pass"]] or rows

    def mean(group: list[dict], key: str) -> float:
        return sum(_SEVERITY[key](r) for r in group) / len(group)

    key = max(_SEVERITY, key=lambda k: mean(lost, k) - mean(kept, k))
    worst = min(lost, key=lambda r: r["margin"])
    if key == "gust":
        floor = min(r["gust_mps"] for r in lost)
        windy = [r for r in rows if r["gust_mps"] >= floor]
        sentence = (
            f"Gusts are the weak point: it lost {len(lost)} of the {len(windy)} worlds with gusts of {floor:.1f} m/s or more, "
            f"so the position hold needs to be stiffer."
        )
    elif key == "motor":
        sentence = (
            f"Thrust reserve is the weak point: with motors {abs(worst['motor_pct']):.0f} % weaker, "
            f"a {worst['gust_mps']:.1f} m/s gust is more than it can fight."
        )
    elif key == "mass":
        sentence = f"Weight is the weak point: {worst['mass_pct']:+.0f} % mass leaves too little thrust to catch the gust."
    else:
        sentence = f"Sensor noise is the weak point: at {worst['noise_cm']:.1f} cm of jitter the position hold starts to wander."
    return key, sentence


@dataclass
class StressPlan:
    """What one product needs for a stress test: its worlds, where they fly, and how to read the results."""

    product: str
    base: dict
    worlds: list
    row: Callable[[object, dict], dict]
    weakest: Callable[[list[dict]], tuple[str | None, str]]
    # A backend world runner; without one the worlds fly in the browser.
    run: Callable[[object], dict] | None = None
    # What the browser builds the MJCF from (the training spec).
    spec: dict | None = None
    # Outcome fields the worst world's replay needs besides the trajectory.
    replay_keys: tuple[str, ...] = ()


def _drone_plan(ctx: Ctx, args: dict) -> StressPlan:
    try:
        metrics = compute(ctx.state)
    except PhysicsError as exc:
        raise ValueError("Build the drone first: " + str(exc)) from exc
    gains, policy = trained_gains(ctx, args.get("gains"))
    return StressPlan(
        product="drone",
        base={
            "policy": policy,
            "gains": asdict(gains),
            "weight_g": metrics["weight_g"],
            "thrust_to_weight": metrics["thrust_to_weight"],
        },
        worlds=sample_worlds(),
        row=world_row,
        weakest=weakest_point,
        spec=product_spec(ctx),
    )


def _gripper_plan(state) -> StressPlan:
    from pai_agent.tools.gripper import compute_grip
    from pai_agent.tools.stress_grip import (
        grip_row,
        grip_weakest,
        run_grip_world,
        sample_grip_worlds,
    )

    try:
        metrics = compute_grip(state)
    except ValueError as exc:
        raise ValueError("Build the gripper first: " + str(exc)) from exc
    brief = state.brief or {"object_mass_g": 200.0, "object_width_mm": 66.0}
    payload = float(brief["object_mass_g"])
    width = float(brief["object_width_mm"])
    return StressPlan(
        product="gripper",
        base={
            "policy": "design",
            "gains": {},
            "weight_g": metrics["weight_g"],
            "payload_g": payload,
            "object_width_mm": width,
            "force_n": metrics["grip_force_n"],
            "safety_factor": metrics["safety_factor"],
        },
        worlds=sample_grip_worlds(WORLDS, SEED),
        run=lambda world: run_grip_world(payload, width, metrics["grip_force_n"], metrics["friction"], world),
        row=grip_row,
        weakest=grip_weakest,
        replay_keys=("hand",),
    )


async def _backend_batches(plan: StressPlan) -> AsyncIterator[list[tuple[object, dict]]]:
    chunk = 5
    for start in range(0, len(plan.worlds), chunk):
        batch = plan.worlds[start : start + chunk]
        outcomes = await asyncio.to_thread(lambda b=batch: [plan.run(w) for w in b])
        yield list(zip(batch, outcomes))


# --- the browser runs the drone's worlds ---------------------------------------

# job_id -> job record; a reset makes a new session id, which orphans older jobs.
_JOBS: dict[str, dict] = {}


def _new_job(ctx: Ctx, plan: StressPlan) -> dict:
    job = {
        "id": "st" + uuid.uuid4().hex[:8],
        "session_id": ctx.state.session_id,
        "client": None,
        "status": "queued",
        "spec": plan.spec,
        "gains": plan.base["gains"],
        "worlds": {w.i: w for w in plan.worlds},
        "seen": 0.0,
        "claimed": asyncio.Event(),
        "inbox": asyncio.Queue(),
    }
    _JOBS[job["id"]] = job
    return job


async def _browser_batches(job: dict) -> AsyncIterator[list[tuple[object, dict]]]:
    """Waits for a dashboard tab to claim the job, then yields its outcomes as they arrive."""

    try:
        try:
            await asyncio.wait_for(job["claimed"].wait(), timeout=claim_timeout())
        except TimeoutError:
            raise StressError("no dashboard picked up the worlds. Open the dashboard and ask again.") from None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + run_timeout()
        received: set[int] = set()
        while True:
            now = loop.time()
            if now >= deadline:
                raise StressError("the browser did not finish in time.")
            # A tab that was closed or reloaded stops reporting; fail instead of waiting out the run.
            if now - job["seen"] > stall_timeout():
                raise StressError("the dashboard tab flying the worlds went away.")
            try:
                kind, payload = await asyncio.wait_for(job["inbox"].get(), timeout=min(1.0, deadline - now))
            except TimeoutError:
                continue
            if kind == "failed":
                raise StressError("the browser run failed: " + str(payload))
            if kind == "done":
                if len(received) < len(job["worlds"]):
                    raise StressError(f"the browser sent {len(received)} of {len(job['worlds'])} worlds.")
                return
            batch = []
            for result in payload:
                world = job["worlds"].get(result["i"])
                if world is None or result["i"] in received:
                    continue
                received.add(result["i"])
                batch.append((world, browser_outcome(result["metrics"], result["trajectory"])))
            if batch:
                yield batch
    finally:
        job["status"] = "over"


async def stress_test(ctx: Ctx, args: dict) -> dict:
    try:
        if getattr(ctx.state, "product", "drone") == "gripper":
            plan = _gripper_plan(ctx.state)
        else:
            plan = _drone_plan(ctx, args)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "detail": str(exc)}

    total = len(plan.worlds)
    run = getattr(ctx.state, "stress_run", 0) + 1
    ctx.state.stress_run = run
    base = {"type": "stress", "run": run, "product": plan.product, "total": total, "seed": SEED, **plan.base}
    if plan.run is None:
        job = _new_job(ctx, plan)
        base.update({"source": "browser", "job_id": job["id"], "spec": plan.spec})
        batches, first = _browser_batches(job), "queued"
    else:
        batches, first = _backend_batches(plan), "running"
    rows: list[dict] = []
    replays: dict[int, dict] = {}
    await ctx.emit({**base, "status": first, "done": 0, "survived": 0, "worlds": [], "worst": None, "weakest": None, "explanation": ""})
    try:
        async for batch in batches:
            for world, outcome in batch:
                rows.append(plan.row(world, outcome))
                replays[world.i] = {"trajectory": outcome["trajectory"], **{k: outcome[k] for k in plan.replay_keys}}
            # The browser finishes worlds in any order; the card and the score read them by number.
            rows.sort(key=lambda r: r["i"])
            survived = sum(1 for r in rows if r["pass"])
            await ctx.emit({**base, "status": "running", "done": len(rows), "survived": survived, "worlds": rows, "worst": None, "weakest": None, "explanation": ""})
            await ctx.emit({"type": "tool", "name": "stress_test", "status": "running", "detail": f"World {len(rows)}/{total} · {survived} survived"})
    except Exception as exc:
        error = f"The stress test stopped after {len(rows)} of {total} worlds: {exc}"
        survived = sum(1 for r in rows if r["pass"])
        await ctx.emit({**base, "status": "failed", "done": len(rows), "survived": survived, "worlds": rows, "worst": None, "weakest": None, "explanation": error})
        return {"ok": False, "error": error, "detail": error}

    survived = sum(1 for r in rows if r["pass"])
    worst_row = min(rows, key=lambda r: (r["pass"], r["margin"]))
    weakest, explanation = plan.weakest(rows)
    worst = {**worst_row, **replays[worst_row["i"]]}
    await ctx.emit({**base, "status": "done", "done": total, "survived": survived, "worlds": rows, "worst": worst, "weakest": weakest, "explanation": explanation})
    ctx.state.last_stress = {"survived": survived, "total": total, "weakest": weakest, "explanation": explanation, "policy": plan.base["policy"]}
    return {
        "ok": True,
        "detail": f"Survived {survived}/{total}",
        "product": plan.product,
        "survived": survived,
        "total": total,
        "policy": plan.base["policy"],
        "weakest": weakest,
        "explanation": explanation,
        "worst_world": {k: v for k, v in worst_row.items() if k != "margin"},
    }


# --- HTTP: the browser claims the drone's worlds and reports their outcomes ------

router = APIRouter()


class StressClaimIn(BaseModel):
    client: str


class StressResultIn(BaseModel):
    i: int
    metrics: dict[str, float | bool]
    # [[t, x, y, z], ...] at 20 Hz.
    trajectory: list[list[float]] = []


class StressProgressIn(BaseModel):
    client: str
    status: str
    results: list[StressResultIn] = []
    error: str | None = None


def _job_for(request: Request, job_id: str) -> dict:
    job = _JOBS.get(job_id)
    if job is None or job["session_id"] != request.app.state.session.state.session_id:
        raise HTTPException(status_code=404, detail="unknown stress job")
    return job


@router.post("/api/stress/{job_id}/claim")
async def claim(job_id: str, body: StressClaimIn, request: Request) -> dict:
    job = _job_for(request, job_id)
    if job["client"] not in (None, body.client) or job["status"] not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="already claimed")
    job["client"] = body.client
    job["status"] = "running"
    job["seen"] = asyncio.get_running_loop().time()
    job["claimed"].set()
    return {
        "ok": True,
        "job_id": job_id,
        "product": "drone",
        "spec": job["spec"],
        "gains": job["gains"],
        "seed": SEED,
        "worlds": [asdict(w) for w in job["worlds"].values()],
    }


@router.post("/api/stress/{job_id}/progress")
async def progress(job_id: str, body: StressProgressIn, request: Request) -> dict:
    job = _job_for(request, job_id)
    if job["client"] != body.client:
        raise HTTPException(status_code=409, detail="claimed by another client")
    if job["status"] != "running":
        raise HTTPException(status_code=409, detail="job is over")
    if body.status not in {"running", "done", "failed"}:
        raise HTTPException(status_code=400, detail="status is running, done or failed")
    job["seen"] = asyncio.get_running_loop().time()
    if body.results:
        job["inbox"].put_nowait(("results", [{"i": r.i, "metrics": r.metrics, "trajectory": r.trajectory[:400]} for r in body.results]))
    if body.status == "done":
        job["inbox"].put_nowait(("done", None))
    elif body.status == "failed":
        job["inbox"].put_nowait(("failed", (body.error or "failed")[:200]))
    return {"ok": True}


_STRESS = re.compile(r"\bstress", re.IGNORECASE)
_ROBUST = re.compile(r"\brobust", re.IGNORECASE)


def wants_stress(text: str, finished: bool) -> bool:
    """'Stress' asks for the stress test at any time; 'robust' only once a build has finished."""

    return bool(_STRESS.search(text) or (finished and _ROBUST.search(text)))


async def run_stress_mock(ctx: Ctx) -> None:
    """'Stress test it' without a key: the same tool, with Mechanic's lines around it."""

    from pai_agent.tools.registry import call_tool

    gripper = getattr(ctx.state, "product", "drone") == "gripper"
    product = "gripper" if gripper else "drone"
    if not ctx.state.selected:
        await call_tool(ctx, "mascot_say", {"state": "besorgt", "say": "There is nothing to stress yet. Build it first."})
        await ctx.chat("agent", "There is nothing to stress test yet. Let the kickoff build v1 first, then ask again.")
        return
    if gripper:
        intro = (
            "Stress test of the gripper design: 50 MuJoCo worlds, each with its own payload mass (±15 %), servo strength "
            "(−25…0 %), pad friction (−40…+10 %), a harder arm shake (1–2×), and servo jitter."
        )
        say = "Fifty randomized worlds. Let's see if it lets go."
    else:
        _gains, policy = trained_gains(ctx, None)
        source = "the trained controller" if policy == "trained" else "the default controller gains (no training result yet)"
        intro = (
            "Stress test with " + source + ": 50 MuJoCo worlds in your browser, each with its own mass (±15 %), "
            "motor strength (−25…0 %), a gust of up to 6 m/s, and sensor noise."
        )
        say = "Fifty randomized worlds. Let's shake it."
    await call_tool(ctx, "mascot_say", {"state": "denkt", "say": say})
    await ctx.chat("agent", intro)
    result = await call_tool(ctx, "stress_test", {})
    if result.get("ok") is False:
        await call_tool(ctx, "mascot_say", {"state": "besorgt", "say": "The stress test fell over."})
        await ctx.chat("agent", "The stress test failed: " + str(result.get("error")))
        return
    survived, total = result["survived"], result["total"]
    state = "freut_sich" if survived == total else "erklaert" if survived >= total * 0.9 else "besorgt"
    await call_tool(ctx, "mascot_say", {"state": state, "say": result["explanation"]})
    worst = result["worst_world"]
    which = "closest call" if survived == total else "worst failure"
    await ctx.chat("agent", f"The {product} survived {survived}/{total}. The {which}, world {worst['i']}, replays in the card.")
