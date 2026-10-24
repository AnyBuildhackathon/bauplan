"""Warms the slow first calls at server start, so the first build on stage does not pay for them.

CadQuery's first import costs about 6 s, MuJoCo's and the Anthropic SDK's about a second each, and
a cold freecadcmd or Blender start reads hundreds of megabytes from disk. This runs once in a
background thread right after startup; a request that arrives first simply waits for the import
itself. PAI_WARM=0 turns it off.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

log = logging.getLogger(__name__)


def enabled() -> bool:
    return os.environ.get("PAI_WARM", "").strip().lower() not in {"0", "false", "no", "off"}


def warm() -> dict[str, float]:
    """Imports and starts each tool once; returns the seconds each took. Failures are only logged."""

    spent: dict[str, float] = {}

    def step(name: str, work) -> None:
        started = time.perf_counter()
        try:
            work()
        except Exception as exc:  # A warm-up never breaks the server.
            log.info("warm-up %s skipped: %s", name, exc)
            return
        spent[name] = round(time.perf_counter() - started, 2)

    def cadquery() -> None:
        import cadquery as cq

        cq.Workplane("XY").box(1, 1, 1).val().Volume()

    def mujoco() -> None:
        import mujoco as mj

        mj.MjModel.from_xml_string("<mujoco><worldbody><geom size='1'/></worldbody></mujoco>")

    def anthropic() -> None:
        import anthropic  # noqa: F401

    def freecad() -> None:
        from pai_agent.freecad_run import find_freecadcmd

        binary = find_freecadcmd()
        if binary:
            subprocess.run([binary, "--version"], capture_output=True, timeout=60, check=False)

    def blender() -> None:
        from pai_agent.tools.blender import find_blender

        binary = find_blender()
        if binary:
            subprocess.run([binary, "-b", "--factory-startup", "--version"], capture_output=True, timeout=60, check=False)

    for name, work in (("cadquery", cadquery), ("mujoco", mujoco), ("anthropic", anthropic), ("freecad", freecad), ("blender", blender)):
        step(name, work)
    log.info("warm-up done: %s", spent)
    return spent
