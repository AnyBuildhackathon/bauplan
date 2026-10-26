"""Training in the browser: 1,024 MuJoCo WASM rollouts, run by the open dashboard.

The backend does not simulate here. `train_in_browser` publishes a queued `training`
event that carries the product spec (parts, masses, thrust, arm length). The first
dashboard tab that sees it claims the job, builds the MJCF, runs an evolution
strategy in Web Workers, and posts each generation back to `/api/training/...`.
Those posts are re-published as `training` events, so every client, Mechanic and the
panel see the same curve. The final event carries the trained gains.
"""

from __future__ import annotations

import asyncio
import math
import os
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from pai_agent.context import Ctx
from pai_agent.tools.physics import PhysicsError, compute

POPULATION = 64
GENERATIONS = 16
# Nominal small drone for a run before anything is built (the mock v1: 36.7 g, 4 x 1102 motors).
_NOMINAL = {"weight_g": 36.7, "thrust_g": 4 * 28.0, "arm_length_mm": 36.0}
# Nominal gripper: the brief's 200 g, 66 mm part, an MG996R on the 70 mm finger, printed TPU pads.
_NOMINAL_GRIP = {"payload_g": 200.0, "width_mm": 66.0, "max_force_n": 4.5, "friction": 0.8}

# job_id -> job record; a reset makes a new session id, which orphans older jobs.
_JOBS: dict[str, dict] = {}
_LATEST: dict[str, str] = {}


def claim_timeout() -> float:
    raw = os.environ.get("PAI_TRAIN_CLAIM_TIMEOUT_S", "").strip() or "20"
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 20.0


def run_timeout() -> float:
    raw = os.environ.get("PAI_TRAIN_TIMEOUT_S", "").strip() or "240"
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 240.0


def stall_timeout() -> float:
    raw = os.environ.get("PAI_TRAIN_STALL_S", "").strip() or "30"
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 30.0


def _parts(state) -> list[dict]:
    parts = []
    for category, part in state.selected.items():
        mass = float(part.get("mass_g") or 0)
        if category == "frame" and state.frame_mass_g is not None:
            mass = float(state.frame_mass_g)
        parts.append({"category": category, "name": str(part.get("name", category)), "qty": int(part.get("bom_qty") or 1), "mass_g": round(mass, 2)})
    return parts


def _gripper_spec(state) -> dict:
    """The grip test's inputs: the object from the brief, the finger force the servo holds, pad friction."""

    from pai_agent.tools.gripper import compute_grip

    brief = state.brief or {}
    try:
        metrics = compute_grip(state)
    except (KeyError, ValueError):
        return {
            "product": "gripper",
            "nominal": True,
            "label": "nominal gripper (nothing built yet)",
            "payload_g": float(brief.get("object_mass_g") or _NOMINAL_GRIP["payload_g"]),
            "width_mm": float(brief.get("object_width_mm") or _NOMINAL_GRIP["width_mm"]),
            "max_force_n": _NOMINAL_GRIP["max_force_n"],
            "friction": _NOMINAL_GRIP["friction"],
            "parts": [],
        }
    version = len(state.versions)
    return {
        "product": "gripper",
        "nominal": False,
        "label": ("v" + str(version) if version else "current build") + " · " + str(state.selected["servo"]["name"]),
        "payload_g": float(brief.get("object_mass_g") or _NOMINAL_GRIP["payload_g"]),
        "width_mm": float(brief.get("object_width_mm") or _NOMINAL_GRIP["width_mm"]),
        "max_force_n": float(metrics["grip_force_n"]),
        "friction": float(metrics["friction"]),
        "parts": _parts(state),
    }


def product_spec(ctx: Ctx) -> dict:
    """What the browser needs to build the MJCF: for the drone total mass, thrust, arm, and the parts."""

    state = ctx.state
    if getattr(state, "product", "drone") == "gripper":
        return _gripper_spec(state)
    arm = float((state.cad_params or {}).get("arm_length_mm") or _NOMINAL["arm_length_mm"])
    try:
        metrics = compute(state)
    except PhysicsError:
        return {
            "product": "drone",
            "nominal": True,
            "label": "nominal drone (nothing built yet)",
            "mass_g": _NOMINAL["weight_g"],
            "thrust_g": _NOMINAL["thrust_g"],
            "motors": 4,
            "arm_length_mm": arm,
            "parts": [],
        }
    parts = _parts(state)
    motors = int(state.selected.get("motor", {}).get("bom_qty") or 4)
    version = len(state.versions)
    return {
        "product": "drone",
        "nominal": False,
        "label": ("v" + str(version) if version else "current build") + " · " + f"{metrics['weight_g']:g} g",
        "mass_g": float(metrics["weight_g"]),
        "thrust_g": float(metrics["thrust_g"]),
        "motors": motors,
        "arm_length_mm": arm,
        "parts": parts,
    }


def _event(job: dict, status: str) -> dict:
    curve = job["curve"]
    return {
        "type": "training",
        "status": status,
        "step": job["step"],
        "reward": curve[-1][1] if curve else 0,
        "curve": [list(point) for point in curve],
        "video_url": None,
        "source": "browser",
        "job_id": job["id"],
        "product": job["spec"]["product"],
        "spec": job["spec"],
        "population": job["population"],
        "generations": job["generations"],
        "rollouts_total": job["population"] * job["generations"],
        "generation": job["generation"],
        "best_params": job["best_params"],
        "best_metrics": job["best_metrics"],
        **({"error": job["error"]} if job.get("error") else {}),
        **({"gains": job["gains"]} if job.get("gains") else {}),
    }


async def train_in_browser(ctx: Ctx, args: dict) -> dict:
    product = getattr(ctx.state, "product", "drone")
    if product not in {"drone", "gripper"}:
        message = "Browser training covers the drone and the gripper, not a " + str(product) + " product yet."
        return {"ok": False, "error": message, "detail": message}
    population = int(args.get("population") or POPULATION)
    generations = int(args.get("generations") or GENERATIONS)
    population = max(8, min(256, population))
    generations = max(2, min(64, generations))
    spec = product_spec(ctx)
    job = {
        "id": "bt" + uuid.uuid4().hex[:8],
        "session_id": ctx.state.session_id,
        "spec": spec,
        "population": population,
        "generations": generations,
        "status": "queued",
        "client": None,
        "step": 0,
        "generation": 0,
        "curve": [],
        "best_params": None,
        "best_metrics": None,
        "seen": 0.0,
        "error": None,
        "gains": None,
        "claimed": asyncio.Event(),
        "finished": asyncio.Event(),
        "bus": ctx.bus,
    }
    _JOBS[job["id"]] = job
    _LATEST[ctx.state.session_id] = job["id"]
    await ctx.emit(_event(job, "queued"))

    try:
        await asyncio.wait_for(job["claimed"].wait(), timeout=claim_timeout())
    except TimeoutError:
        job["status"] = "failed"
        job["error"] = "no_browser"
        await ctx.emit(_event(job, "failed"))
        message = "No dashboard picked up the run. Open the dashboard and ask again."
        return {"ok": False, "error": message, "detail": message, "job_id": job["id"]}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + run_timeout()
    while not job["finished"].is_set():
        now = loop.time()
        # A tab that was closed or reloaded stops reporting; fail instead of waiting out the run.
        error = "timeout" if now >= deadline else "browser_gone" if now - job["seen"] > stall_timeout() else None
        if error:
            job["status"] = "failed"
            job["error"] = error
            await ctx.emit(_event(job, "failed"))
            message = "The browser run did not finish in time." if error == "timeout" else "The dashboard tab running the training went away."
            return {"ok": False, "error": message, "detail": message, "job_id": job["id"]}
        try:
            await asyncio.wait_for(job["finished"].wait(), timeout=min(1.0, deadline - now))
        except TimeoutError:
            pass
    if job["status"] != "done":
        message = "The browser run failed."
        return {"ok": False, "error": message, "detail": message, "job_id": job["id"]}
    metrics = job["best_metrics"] or {}
    detail = f"{job['step']:,} rollouts · score {job['curve'][-1][1]:.1f}" if job["curve"] else f"{job['step']:,} rollouts"
    return {
        "ok": True,
        "detail": detail,
        "training_status": "done",
        "job_id": job["id"],
        "rollouts": job["step"],
        "best_score": job["curve"][-1][1] if job["curve"] else 0,
        "best_params": job["best_params"],
        "best_metrics": metrics,
        "gains": job["gains"],
        "curve": job["curve"],
    }


def latest_job(session_id: str) -> dict | None:
    job_id = _LATEST.get(session_id)
    job = _JOBS.get(job_id or "")
    if job is None:
        return None
    return {key: value for key, value in _event(job, job["status"]).items() if key != "type"}


# --- HTTP: the browser claims the job and reports each generation -------------

router = APIRouter()


class ClaimIn(BaseModel):
    client: str


class ProgressIn(BaseModel):
    client: str
    status: str
    step: int = 0
    generation: int = 0
    best_score: float | None = None
    best_params: dict[str, float] | None = None
    best_metrics: dict[str, float | bool] | None = None
    # Final gains for other modules: numbers, or one level of named numbers (roll: {p, i}).
    gains: dict[str, int | float | dict[str, int | float]] | None = None
    error: str | None = None


def _job_for(request: Request, job_id: str) -> dict:
    job = _JOBS.get(job_id)
    if job is None or job["session_id"] != request.app.state.session.state.session_id:
        raise HTTPException(status_code=404, detail="unknown training job")
    return job


@router.post("/api/training/{job_id}/claim")
async def claim(job_id: str, body: ClaimIn, request: Request) -> dict:
    job = _job_for(request, job_id)
    if job["client"] not in (None, body.client) or job["status"] not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="already claimed")
    job["client"] = body.client
    job["seen"] = asyncio.get_running_loop().time()
    job["claimed"].set()
    return {"ok": True, "job_id": job_id, "spec": job["spec"], "population": job["population"], "generations": job["generations"]}


@router.post("/api/training/{job_id}/progress")
async def progress(job_id: str, body: ProgressIn, request: Request) -> dict:
    job = _job_for(request, job_id)
    if job["client"] != body.client:
        raise HTTPException(status_code=409, detail="claimed by another client")
    if job["status"] in {"done", "failed"}:
        raise HTTPException(status_code=409, detail="job is over")
    if body.status not in {"running", "done", "failed"}:
        raise HTTPException(status_code=400, detail="status is running, done or failed")
    job["seen"] = asyncio.get_running_loop().time()
    job["step"] = max(0, int(body.step))
    job["generation"] = max(0, int(body.generation))
    if body.best_score is not None and math.isfinite(body.best_score):
        point = [job["step"], round(float(body.best_score), 2)]
        if not job["curve"] or job["curve"][-1][0] != point[0]:
            job["curve"].append(point)
    if body.best_params is not None:
        job["best_params"] = {key: round(float(value), 5) for key, value in body.best_params.items()}
    if body.best_metrics is not None:
        job["best_metrics"] = body.best_metrics
    if body.gains is not None and body.status == "done":
        job["gains"] = body.gains
    job["status"] = body.status
    if body.error:
        job["error"] = body.error[:200]
    await job["bus"].publish(_event(job, body.status))
    if body.status in {"done", "failed"}:
        job["finished"].set()
    return {"ok": True}


@router.get("/api/training/browser")
async def latest(request: Request) -> dict:
    job = latest_job(request.app.state.session.state.session_id)
    return {"ok": True, "job": job}


# --- mock: "train it" without a key ------------------------------------------


_MOCK_LINES = {
    "drone": (
        "Training the hover controller: 1,024 MuJoCo runs, right in your browser.",
        "I start 64 controller candidates for 16 generations, 1,024 MuJoCo simulations in the browser. "
        "Each one has to hold its position for 10 seconds, 15 % heavier than it expects and with a gust from the side.",
        "Trained. The best controller holds its spot.",
    ),
    "gripper": (
        "Training the grasp: 1,024 MuJoCo runs, right in your browser.",
        "I start 64 grasps for 16 generations, 1,024 MuJoCo simulations in the browser. "
        "Each one squeezes, lifts the part 15 cm and shakes it; the least force and the shortest cycle that still hold win.",
        "Trained. The grasp holds with less force.",
    ),
}


def _result_line(product: str, result: dict) -> str:
    metrics = result.get("best_metrics") or {}
    exported = result.get("gains") or {}
    line = f"Done after {int(result.get('rollouts') or 0):,} simulations. Best score {float(result.get('best_score') or 0):.1f}."
    if product == "gripper":
        if metrics.get("slip_mm") is not None:
            held = "It holds" if metrics.get("held") else "It still slips"
            line += f" {held} with {float(metrics.get('force_n') or 0):.1f} N per finger, {float(metrics['slip_mm']):.1f} mm slip, lifted after {float(metrics.get('cycle_s') or 0):.2f} s."
        if exported:
            line += f" For the sketch: squeeze {exported.get('squeeze')}, ramp {exported.get('ramp_ms')} ms, settle {exported.get('settle_ms')} ms, lift {exported.get('lift_ms')} ms."
        return line
    if metrics.get("rms_error_cm") is not None and metrics.get("max_tilt_deg") is not None:
        line += f" It holds position within {float(metrics['rms_error_cm']):.1f} cm RMS and tilts at most {float(metrics['max_tilt_deg']):.0f}°."
    params = result.get("best_params") or {}
    if params:
        line += " Gains: " + ", ".join(f"{key} {value:g}" for key, value in params.items()) + "."
    return line


async def run_mock_training(ctx: Ctx, offer_stress: bool = True) -> None:
    from pai_agent.tools.registry import call_tool

    product = "gripper" if getattr(ctx.state, "product", "drone") == "gripper" else "drone"
    start, plan, done = _MOCK_LINES[product]
    await ctx.step("training", "running")
    await call_tool(ctx, "mascot_say", {"state": "erklaert", "say": start})
    await ctx.chat("agent", plan)
    result = await call_tool(ctx, "train_in_browser", {})
    if result.get("ok") is False:
        await ctx.step("training", "failed")
        await call_tool(ctx, "mascot_say", {"state": "besorgt", "say": "No browser took the run."})
        await ctx.chat("agent", str(result.get("error") or "The training did not run."))
        return
    await ctx.step("training", "done")
    await call_tool(ctx, "mascot_say", {"state": "freut_sich", "say": done})
    await ctx.chat("agent", _result_line(product, result))
    if offer_stress and product == "drone" and getattr(ctx.state, "last_stress", None):
        await ctx.chat("agent", "The last stress test flew the old gains. Say “stress test it again” to fly the trained ones.")
