"""Builds the gripper template in FreeCAD and writes it as one MuJoCo MJCF file (pai_agent/mjcf_export.py).

    cd agent && uv run python scripts/export_gripper_mjcf.py --out hand.xml
    cd agent && uv run python scripts/export_gripper_mjcf.py --servo towerpro-sg90 --pads pads-silicone --param finger_length_mm=80 --out hand.xml
    cd agent && uv run python scripts/export_gripper_mjcf.py --example

The servo pocket follows the chosen servo, as in the app. --example rewrites the example hand that the
anybuild-robouse package ships and tests with (MG996R, printed TPU pads, the template's default sizes).
Needs freecadcmd.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from types import SimpleNamespace

from pai_agent.cad_script import run_script
from pai_agent.mjcf_export import write_hand
from pai_agent.paths import REPO_ROOT
from pai_agent.tools.cad_part import LIBRARY, library_script
from pai_agent.tools.gripper import gripper_catalog, servo_params

EXAMPLE = REPO_ROOT / "anybuild-robouse" / "src" / "anybuild_robouse" / "data" / "example_hand.xml"


def build_hand(servo_id: str, pads_id: str, params: dict[str, float], out: Path) -> Path:
    catalog = {part["id"]: part for part in gripper_catalog()["parts"]}
    servo, pads = catalog[servo_id], catalog[pads_id]
    if servo["category"] != "servo" or pads["category"] != "pads":
        raise SystemExit("--servo must name a servo and --pads a pad set from agent/data/catalogs/gripper.json.")
    values = {key: default for key, (default, _low, _high) in LIBRARY["gripper"]["params"].items()}
    values.update(params)
    values.update(servo_params(SimpleNamespace(selected={"servo": servo})))
    with tempfile.TemporaryDirectory(prefix="pai-hand-") as work:
        build = run_script(library_script("gripper"), values, Path(work), "gripper")
        return write_hand(build, servo, pads, out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--servo", default="towerpro-mg996r", help="servo id from the gripper catalog")
    parser.add_argument("--pads", default="pads-tpu-printed", help="pad id from the gripper catalog")
    parser.add_argument("--param", action="append", default=[], metavar="NAME=MM", help="template parameter, repeatable")
    parser.add_argument("--out", type=Path, help="MJCF file to write")
    parser.add_argument("--example", action="store_true", help="rewrite anybuild-robouse's example hand")
    args = parser.parse_args()
    if args.example == bool(args.out):
        parser.error("give --out PATH or --example")
    params = {}
    for item in args.param:
        name, _, value = item.partition("=")
        if name not in LIBRARY["gripper"]["params"]:
            parser.error(name + " is not a gripper parameter: " + ", ".join(LIBRARY["gripper"]["params"]))
        params[name] = float(value)
    if args.example and (params or args.servo != "towerpro-mg996r" or args.pads != "pads-tpu-printed"):
        parser.error("--example always uses the defaults")
    path = build_hand(args.servo, args.pads, params, EXAMPLE if args.example else args.out)
    print("wrote", path, f"({path.stat().st_size / 1000:.0f} kB)")


if __name__ == "__main__":
    main()
