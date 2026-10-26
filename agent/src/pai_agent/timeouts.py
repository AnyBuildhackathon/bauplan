"""Per-tool time budgets, so a stuck tool degrades with a clear message instead of freezing the run.

call_tool wraps every tool in its budget. Most tools already bound their own subprocess or network
call (FreeCAD 60 s per script, Blender 180 s, Isaac by ISAAC_TIMEOUT_S);
the budget here is the backstop above that, sized so it never cuts a healthy run short.
PAI_TIMEOUT_<TOOL> (for example PAI_TIMEOUT_BLENDER_RENDER=30) overrides one tool,
PAI_TOOL_TIMEOUT_S the default for tools without their own entry. 0 turns a budget off.
On the local Claude Code subscription the tools that wait for Claude get twice their budget:
each Claude call there starts a Claude Code process.
"""

from __future__ import annotations

import os

DEFAULT_S = 120.0

BUDGET_S = {
    # FreeCAD: up to three script attempts plus the simplified-block fallback.
    "cad_part": 300.0,
    # SolidCraft: up to three script attempts, two runs of about a second each per attempt.
    "solidcraft_part": 300.0,
    # SolidCraft writes the URDF in a second; MuJoCo reads it and drives the motion study in a few more.
    "export_urdf": 120.0,
    # A change reruns every check, the FEM too.
    "cad_update": 480.0,
    "cad_frame": 200.0,
    "assemble": 120.0,
    "reference_load": 600.0,
    # Blender renders in about 20 s; its own subprocess timeout is 180 s.
    "blender_render": 200.0,
    "product_usd": 150.0,
    # MuJoCo and the analytic checks take seconds.
    "simulate_drone": 60.0,
    "simulate_grip": 60.0,
    "simulate_assembly": 60.0,
    # robouse tasks check runs two trials of about 15 s; Claude Code as the policy has its own limit of at most 900 s.
    "robouse_trial": 1200.0,
    # The browser runs wait for a dashboard tab: claim, run and stall limits sit inside this.
    "train_in_browser": 320.0,
    "stress_test": 320.0,
    # Training on the missions stops itself after PAI_TRAIN_BACKEND_S (120 s); the validation flights and 50 stress worlds follow.
    "train_controller": 600.0,
    # Isaac bounds its SSH job with ISAAC_TIMEOUT_S (900 s training, 300 s tests) plus copies.
    "isaac_train": 1200.0,
    "isaac_lab_train": 1200.0,
    "isaac_test": 600.0,
    "isaac_sim_render": 600.0,
    "isaac_lab_status": 30.0,
    # Live shop prices search the web per line, 45 s each at most.
    "bom_build": 120.0,
    # A slicer takes seconds to a minute per part; its own subprocess timeout is 180 s.
    "print_prep": 300.0,
    # A first SimReady object downloads its package, CoACD splits a container (PAI_SIMREADY_DECOMPOSE_S,
    # 180 s at most) and Blender writes the GLB (180 s at most); a cached object takes a second.
    "scene_object": 420.0,
    # FEM meshes and solves each load case in CalculiX (150 s each at most); a material change reruns it.
    "fem_check": 420.0,
    "material_pick": 420.0,
    # A web part search asks the distributors, then reads shop pages and datasheets for up to 180 s.
    "part_pick": 210.0,
    "parts_search": 210.0,
    # A delegated parts job may run more than one web part search.
    "delegate": 480.0,
    # Pressing Rebuild runs FreeCAD and the test inside the call; the other controls return at once.
    "ui_control": 400.0,
    "ui_point_at": 10.0,
    "ui_draw": 10.0,
    "mascot_say": 10.0,
}

# The tools whose time is mostly Claude's: slower on the subscription (`provider.py`).
CLAUDE_BOUND = {"cad_part", "solidcraft_part", "cad_update", "bom_build", "part_pick", "parts_search", "delegate", "sketch_to_spec", "optimize_design"}

# What takes over when the tool's own fallback did not get there in time.
FALLBACKS = {
    "blender_render": "the recorded still stands in",
    "isaac_test": "ask again for the recorded result",
    "isaac_train": "ask again for the recorded result",
    "isaac_lab_train": "ask again for the recorded result",
    "isaac_sim_render": "ask again for the recorded result",
}

# What the room hears about, by tool: the tool name means nothing on stage.
LABELS = {
    "cad_part": "FreeCAD",
    "cad_update": "FreeCAD",
    "cad_frame": "FreeCAD",
    "solidcraft_part": "SolidCraft",
    "export_urdf": "SolidCraft",
    "blender_render": "Blender",
    "product_usd": "Blender",
    "simulate_drone": "MuJoCo",
    "simulate_grip": "MuJoCo",
    "simulate_assembly": "MuJoCo",
    "robouse_trial": "Robo Use",
    "train_in_browser": "The browser training",
    "stress_test": "The stress test",
    "isaac_train": "Isaac Lab",
    "isaac_lab_train": "Isaac Lab",
    "isaac_test": "Isaac Sim",
    "isaac_sim_render": "Isaac Sim",
    "isaac_lab_status": "Isaac Lab",
    "bom_build": "The price search",
    "parts_search": "The parts search",
    "part_pick": "The parts search",
    "delegate": "The sub-agent",
}


def _seconds(raw: str | None) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def limit(name: str) -> float | None:
    """Seconds this tool may take, or None for no limit."""

    if name == "ask_user":
        from pai_agent.session import ask_timeout

        # The question closes itself with its default; this only catches a lost answer future.
        return ask_timeout() + 30.0
    own = _seconds(os.environ.get("PAI_TIMEOUT_" + name.upper()))
    if own is None:
        own = BUDGET_S.get(name)
        if own is None:
            own = _seconds(os.environ.get("PAI_TOOL_TIMEOUT_S"))
        if own is None:
            own = DEFAULT_S
        if own and name in CLAUDE_BOUND:
            from pai_agent.provider import active

            if active() == "subscription":
                own *= 2
    return own or None


def timed_out(name: str, seconds: float) -> str:
    """The message for the tool event, the chat and the model: what stopped and why."""

    who = LABELS.get(name, name)
    then = FALLBACKS.get(name, "it was stopped so the run does not hang")
    return f"{who} took longer than {seconds:g} s ({name}); {then}."


def model_timeout() -> float:
    """Seconds a streamed orchestrator model round may go without any progress (PAI_MODEL_TIMEOUT_S, default 90)."""

    return _seconds(os.environ.get("PAI_MODEL_TIMEOUT_S")) or 90.0


def round_limit() -> float:
    """Seconds one streamed orchestrator model round may take in all (PAI_MODEL_ROUND_MAX_S, default 600)."""

    return _seconds(os.environ.get("PAI_MODEL_ROUND_MAX_S")) or 600.0
