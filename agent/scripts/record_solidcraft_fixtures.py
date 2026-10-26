"""Records what SolidCraft exports for two mechanisms, so the MJCF tests run without solidcraft-cli.

    cd agent && uv run python scripts/record_solidcraft_fixtures.py

Needs solidcraft-cli (bash agent/scripts/setup_solidcraft.sh). For each design it runs `solidcraft.export_robot`
with the build material and writes tests/fixtures/solidcraft/<name>.json: the URDF, with each STL mesh replaced
by the box around it (the checks never collide the parts with each other, so the boxes only keep the file small),
and everything SolidCraft returned with it: joints, components, masses, the motion study and its poses.
- four-bar: SolidCraft's example examples/chebyshev-motion-trace.json (agent/solidcraft/library), a loop closed by
  a hinge.
- actuator-panel: the worked example of SolidCraft's solidcraft-mechanisms skill (agent/solidcraft/skills), a loop
  closed by the actuator's slider and a mirrored panel on a motion link, driven to 20 degrees before export, with a
  motion study added.
"""

from __future__ import annotations

import json
import math
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from pai_agent import solidcraft
from pai_agent.cad_script import DENSITY_G_CM3
from pai_agent.mesh_export import read_stl_vertices

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "solidcraft"
# Fewer samples than a live check takes keep the fixture small; the study still runs end to end.
SAMPLES = 12


def _panel() -> list[dict]:
    reference = (solidcraft.SKILLS_DIR / "solidcraft-mechanisms" / "reference.md").read_text(encoding="utf-8")
    block = re.search(r'```json\n(\{"commands":\[.*?\]\})\n```', reference, re.DOTALL)
    if block is None:
        raise SystemExit("The worked example is missing from solidcraft-mechanisms/reference.md.")
    commands = json.loads(block.group(1))["commands"]
    return commands + [
        {"command": "joint.drive", "params": {"joint": "Hinge", "value": 20}},
        {"command": "motion.study", "params": {"name": "Open", "steps": 24, "keys": [{"joint": "Hinge", "points": [[0, 20], [12, 0], [24, 25]]}]}},
    ]


def _rpy(values: list[float]) -> np.ndarray:
    r, p, y = values
    rx = np.array([[1, 0, 0], [0, math.cos(r), -math.sin(r)], [0, math.sin(r), math.cos(r)]])
    ry = np.array([[math.cos(p), 0, math.sin(p)], [0, 1, 0], [-math.sin(p), 0, math.cos(p)]])
    rz = np.array([[math.cos(y), -math.sin(y), 0], [math.sin(y), math.cos(y), 0], [0, 0, 1]])
    return rz @ ry @ rx


def _boxes(urdf: Path) -> str:
    """The URDF with every mesh as the box around it, placed where the mesh sat."""

    tree = ET.parse(urdf)
    for owner in [*tree.getroot().iter("visual"), *tree.getroot().iter("collision")]:
        geometry = owner.find("geometry")
        mesh = geometry.find("mesh") if geometry is not None else None
        if mesh is None:
            continue
        points = np.array(read_stl_vertices(urdf.parent / mesh.get("filename")))
        low, high = points.min(axis=0), points.max(axis=0)
        origin = owner.find("origin")
        xyz = np.array([float(v) for v in origin.get("xyz", "0 0 0").split()])
        rpy = [float(v) for v in origin.get("rpy", "0 0 0").split()]
        centre = xyz + _rpy(rpy) @ ((low + high) / 2.0)
        origin.set("xyz", " ".join(f"{v:.9g}" for v in centre))
        geometry.remove(mesh)
        ET.SubElement(geometry, "box", {"size": " ".join(f"{max(v, 1e-4):.9g}" for v in high - low)})
    return ET.tostring(tree.getroot(), encoding="unicode")


def record(name: str, commands: list[dict]) -> None:
    commands = solidcraft.check_script({"commands": commands})
    with tempfile.TemporaryDirectory(prefix="pai-record-") as tmp:
        work = Path(tmp)
        build = solidcraft.build(commands, "PLA", DENSITY_G_CM3["PLA"], work / "part", "part", name)
        extra = solidcraft.material_commands("PLA", DENSITY_G_CM3["PLA"], build.assigned)
        study = {"name": build.studies[0]["name"], "steps": SAMPLES} if build.studies else None
        robot = solidcraft.export_robot(commands, extra, work / "robot", name, None, None, study)
        fixture = {
            "source": "solidcraft-cli " + solidcraft.VERSION + ", recorded by agent/scripts/record_solidcraft_fixtures.py",
            "urdf": _boxes(robot.urdf),
            "joints": robot.joints,
            "components": robot.components,
            "properties": robot.properties,
            "measure": robot.measure,
            "study": robot.study,
            "motion": robot.motion,
            "warnings": robot.warnings,
        }
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / (name + ".json")).write_text(json.dumps(fixture, indent=1) + "\n", encoding="utf-8")
    print("wrote", FIXTURES / (name + ".json"))


def main() -> None:
    why = solidcraft.missing()
    if why:
        raise SystemExit("SolidCraft is not installed: " + why + ". " + solidcraft.INSTALL_HINT)
    four_bar = json.loads((solidcraft.LIBRARY_DIR / "chebyshev-motion-trace.json").read_text(encoding="utf-8"))["commands"]
    record("four-bar", four_bar)
    record("actuator-panel", _panel())


if __name__ == "__main__":
    sys.exit(main())
