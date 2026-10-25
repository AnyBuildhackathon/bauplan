"""train_controller: the drone's controller trained on its own missions, then validated.

The order, back and forth:

1. Hardware check: simulate_mission flies the reference controller, the same for every build.
   A mission that fails there is the parts' fault: change parts first, nothing is trained.
2. Training on the missions themselves (`mission_train.train`), on the backend with the missions'
   MuJoCo model, so it needs no dashboard. Bounded by population, generations and a time limit
   (PAI_TRAIN_BACKEND_S, default 120 s); each generation is a `training` event, `source: "backend"`.
3. Validation: every mission again with the trained gains (each `mission` event carries the
   reference result beside it) and the stress test with the trained gains on the same model.
   The trained result decides: every mission passes and at least 90 % of the stress worlds survive.
   A pass makes the gains the validated set, the one firmware writes.
4. On a fail, back to parts (swap the part or change the dimension the result names), the
   hardware check, then train_controller again. After two failed loops the user decides (ask_user).
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid

from pai_agent.context import Ctx
from pai_agent.mission_sim import MISSIONS, AirframeError
from pai_agent.mission_train import GENERATIONS, POPULATION, TIME_LIMIT_S, train
from pai_agent.tools.mission import airframe_of, build_key, fly_missions, simulate_mission
from pai_agent.tools.physics import PhysicsError

STRESS_PASS = 0.9
MAX_LOOPS = 2
# Validated gains stay this build's while the mass is within this share of the validated mass.
MASS_DRIFT = 0.05
_ORDER = ("speed_run", "turn", "hold", "chase")


def time_limit() -> float:
    raw = os.environ.get("PAI_TRAIN_BACKEND_S", "").strip()
    try:
        return max(0.0, float(raw)) if raw else TIME_LIMIT_S
    except ValueError:
        return TIME_LIMIT_S


def _fail(message: str) -> dict:
    return {"ok": False, "error": message, "detail": message}


def validated_gains(state) -> dict | None:
    """The validated set for the build on the bench now; None when there is none or a part, the arm or the mass changed since."""

    validated = getattr(state, "validated", None)
    if not validated:
        return None
    try:
        frame = airframe_of(state)[2]
    except (PhysicsError, AirframeError, KeyError, ValueError):
        return None
    mass = float(frame["geo"]["total_mass_g"])
    if validated.get("build") != build_key(frame) or abs(mass - float(validated["mass_g"])) > MASS_DRIFT * float(validated["mass_g"]):
        return None
    return validated


def _references(state, key: str) -> dict[str, dict]:
    """The hardware check of this build per mission: the reference controller's latest result."""

    out = {}
    for mission, entry in state.missions.items():
        reference = entry if entry.get("controller", "reference") == "reference" else entry.get("reference")
        if reference and reference.get("build") == key:
            out[mission] = reference
    return out


def _metrics(terms: dict) -> dict:
    out = {}
    for term, value in terms.items():
        key = "hover_rms_error_cm" if term == "hover" else MISSIONS[term]["key"]
        out[key] = value["value"]
    return out


def _event(job: dict, status: str) -> dict:
    return {
        "type": "training",
        "status": status,
        "step": job["rollouts"],
        "reward": job["curve"][-1][1] if job["curve"] else 0,
        "curve": [list(p) for p in job["curve"]],
        "video_url": None,
        "source": "backend",
        "job_id": job["id"],
        "product": "drone",
        "missions": job["missions"],
        "population": job["population"],
        "generations": job["generations"],
        "rollouts_total": job["population"] * job["generations"],
        "generation": job["generation"],
        "best_params": job["best_params"],
        "best_metrics": job["best_metrics"],
        **({"gains": job["gains"]} if job.get("gains") else {}),
        **({"error": job["error"]} if job.get("error") else {}),
    }


async def _train(ctx: Ctx, frame: dict, limits: dict[str, float], args: dict) -> dict:
    population = max(4, min(32, int(args.get("population") or POPULATION)))
    generations = max(1, min(12, int(args.get("generations") or GENERATIONS)))
    seconds = time_limit() if args.get("time_limit_s") is None else max(0.0, float(args["time_limit_s"]))
    job = {
        "id": "mt" + uuid.uuid4().hex[:8],
        "missions": list(limits),
        "population": population,
        "generations": generations,
        "rollouts": 0,
        "generation": 0,
        "curve": [],
        "best_params": None,
        "best_metrics": None,
        "gains": None,
        "error": None,
    }
    await ctx.emit(_event(job, "running"))
    loop = asyncio.get_running_loop()
    stop = threading.Event()

    def report(progress: dict) -> None:
        job.update(rollouts=progress["rollouts"], generation=progress["generation"], curve=progress["curve"])
        job["best_params"] = {k: float(f"{v:.4g}") for k, v in progress["best_gains"].items()}
        asyncio.run_coroutine_threadsafe(ctx.emit(_event(job, "running")), loop).result()
        asyncio.run_coroutine_threadsafe(
            ctx.emit({"type": "tool", "name": "train_controller", "status": "running", "detail": f"Generation {progress['generation']}/{generations} · score {progress['best_score']:.1f}"}),
            loop,
        ).result()

    try:
        result = await asyncio.to_thread(
            train,
            frame,
            limits,
            population=population,
            generations=generations,
            # 0 means no time limit: the mock story flies the full budget for the same numbers every time.
            time_limit_s=seconds if seconds > 0 else float("inf"),
            on_generation=report,
            should_stop=stop.is_set,
        )
    except asyncio.CancelledError:
        stop.set()
        raise
    except Exception as exc:
        job["error"] = str(exc)[:200]
        await ctx.emit(_event(job, "failed"))
        raise
    job.update(rollouts=result["rollouts"], generation=result["generations"], curve=result["curve"], gains=result["gains"], best_metrics=_metrics(result["terms"]))
    job["best_params"] = {k: result["gains"][k] for k in result["gains"] if not isinstance(result["gains"][k], dict)}
    await ctx.emit(_event(job, "done"))
    return result


async def train_controller(ctx: Ctx, args: dict) -> dict:
    from pai_agent.tools.stress import stress_test

    state = ctx.state
    if state.product != "drone":
        return _fail("train_controller trains a drone's flight controller.")
    try:
        metrics, geo, frame = airframe_of(state)
    except (PhysicsError, AirframeError) as exc:
        return _fail(str(exc))
    key = build_key(frame)

    # 1. The hardware check of this build: fly what is missing, the position hold when nothing was asked.
    references = _references(state, key)
    missing = [m for m in _ORDER if m in state.missions and m not in references] or ([] if references else ["hold"])
    if missing:
        flown = await simulate_mission(ctx, {"missions": missing})
        if flown.get("ok") is False:
            return flown
        references = _references(state, key)
    missions = [m for m in _ORDER if m in references]
    broken = [m for m in missions if references[m]["result"] == "fail"]
    if broken:
        why = references[broken[0]]["why"]
        return {
            "ok": True,
            "result": "fail",
            "stage": "hardware",
            "detail": "Hardware check failed: " + ", ".join(MISSIONS[m]["label"] for m in broken),
            "missions": [{"mission": m, "reference": {"value": references[m]["value"], "result": references[m]["result"]}} for m in missions],
            "why": why,
            "next": "The parts cannot do it with the reference controller, so training cannot fix it: swap the part or change the dimension why names, physics_calc, simulate_mission, then train_controller again.",
        }

    # 2. Training on those missions.
    limits = {m: float(references[m]["limit"]) for m in missions}
    trained = await _train(ctx, frame, limits, args)
    gains = trained["gains"]

    # 3. Validation with the trained gains: the full missions, then the stress test.
    entries = [{"mission": m} for m in missions]
    flown = await fly_missions(ctx, entries, metrics, geo, frame, gains=gains)
    stress = await stress_test(ctx, {"gains": gains, "backend": True})
    if stress.get("ok") is False:
        return _fail("The stress test with the trained gains did not finish: " + str(stress.get("error")))
    survived, total = int(stress["survived"]), int(stress["total"])
    stress_ok = survived >= STRESS_PASS * total
    failed = [r for r in flown if r["result"] == "fail"]
    passed = not failed and stress_ok
    rows = [
        {
            "mission": r["mission"],
            "unit": r["unit"],
            "limit": r["limit"],
            "reference": {"value": references[r["mission"]]["value"], "result": references[r["mission"]]["result"]},
            "trained": {"value": r["value"], "result": r["result"]},
            "summary": r["summary"],
            "why": r["why"],
        }
        for r in flown
    ]
    result = {
        "ok": True,
        "result": "pass" if passed else "fail",
        "stage": "trained",
        "training": {k: trained[k] for k in ("rollouts", "generations", "score", "start_score", "seconds", "stopped_early")},
        "gains": gains,
        "missions": rows,
        "stress": {"survived": survived, "total": total, "pass": stress_ok, "needed": round(STRESS_PASS * total), "weakest": stress.get("weakest"), "explanation": stress.get("explanation")},
        "detail": f"{trained['rollouts']} training runs, score {trained['start_score']:.1f} → {trained['score']:.1f}; trained: "
        + ", ".join(MISSIONS[r["mission"]]["label"] + " " + r["result"] for r in flown)
        + f", stress {survived}/{total}",
    }
    if passed:
        state.train_loops = 0
        state.validated = {
            "build": key,
            "mass_g": round(float(geo["total_mass_g"]), 1),
            "gains": gains,
            "missions": {r["mission"]: {"value": r["value"], "unit": r["unit"]} for r in flown},
            "stress": [survived, total],
            "score": trained["score"],
        }
        result["next"] = "Validated: the firmware writes exactly these gains. Name the reference and the trained number of each mission and the stress score in one sentence, then go on."
        return result
    state.train_loops = int(getattr(state, "train_loops", 0)) + 1
    result["loop"] = state.train_loops
    result["why"] = failed[0]["why"] if failed else stress.get("explanation")
    if state.train_loops >= MAX_LOOPS:
        state.train_loops = 0
        result["next_action"] = "ask"
        result["next"] = (
            "Two loops of parts and training did not pass. ask_user whether to keep trying with other parts or accept the build as it flies now; "
            "do not lower a limit without their answer."
        )
    else:
        result["next_action"] = "parts"
        result["next"] = "The trained controller fails: back to parts. Swap the part or change the dimension why names, physics_calc, simulate_mission (the hardware check), then train_controller again."
    return result
