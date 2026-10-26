"""SparkBench, run headless in its own Node process for circuit_design (`tools/circuit.py`).

SparkBench (github.com/dennisonbertram/sparkbench, MIT) wires ESP32 and Raspberry Pi Pico circuits to real pins,
writes their MicroPython and runs it in its simulator. AnyBuild uses a checkout pinned to COMMIT, which
agent/scripts/setup_sparkbench.sh installs into ~/.cache/anybuild/sparkbench/<commit> (SPARKBENCH_DIR names another
folder), and agent/sparkbench/bridge.ts, which drives SparkBench's own planner, checks, acceptance tests and
simulator and writes the files. A run needs no network and no key. The files land flat in the session directory,
because /files/{bucket}/{name} serves one level; the KiCad project and the firmware also come zipped with their
real names. An identical request reuses the last result from agent/runs/cache/circuits (PAI_CACHE=0 turns it off).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import tempfile
import zipfile
from pathlib import Path

from pai_agent import cache
from pai_agent.paths import AGENT_ROOT

COMMIT = "6dd92371aeb2ae6cc5c2dbe04a1fc84a448d315a"
REPOSITORY = "https://github.com/dennisonbertram/sparkbench"
BRIDGE = AGENT_ROOT / "sparkbench" / "bridge.ts"
_TSX = AGENT_ROOT / "sparkbench" / "node_modules" / "tsx" / "dist" / "cli.mjs"
INSTALL_HINT = "Install it once with bash agent/scripts/setup_sparkbench.sh (Node.js 20 or newer, needs the network)."
# A run takes one to two seconds; this only stops a stuck one.
TIMEOUT_S = 60.0
# The environment the bridge gets: no keys, it needs none.
_ENV_KEYS = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
# Where Homebrew puts Node.js, for a server started without the shell's PATH.
_KNOWN_NODE = ("/opt/homebrew/bin/node", "/usr/local/bin/node")
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

# Where each file kind lands, after the caller's prefix such as circuit-v1.
FILES = {
    "schematic_svg": "-schematic.svg",
    "breadboard_svg": "-breadboard.svg",
    "kicad_sch": ".kicad_sch",
    "kicad_zip": "-kicad.zip",
    "netlist": ".net",
    "spice": ".cir",
    "bom_csv": "-bom.csv",
    "firmware_main": "-main.py",
    "firmware_zip": "-firmware.zip",
    "build_md": "-build.md",
    "simulation_log": "-simulation.log",
    "sparkbench_project": "-sparkbench.json",
}
# Copied as they are, by the bridge's file kind.
_COPIED = {"schematic_svg", "breadboard_svg", "kicad_sch", "netlist", "spice", "bom_csv", "build_md", "simulation_log"}


class SparkBenchFailed(Exception):
    pass


def checkout() -> Path:
    own = os.environ.get("SPARKBENCH_DIR", "").strip()
    if own:
        return Path(own).expanduser()
    base = os.environ.get("XDG_CACHE_HOME", "").strip() or str(Path.home() / ".cache")
    return Path(base) / "anybuild" / "sparkbench" / COMMIT


def node() -> str | None:
    return shutil.which("node") or next((path for path in _KNOWN_NODE if os.access(path, os.X_OK)), None)


def missing() -> str | None:
    """Why SparkBench cannot run on this machine, or None when it can."""

    root = checkout()
    if node() is None:
        return "Node.js is not installed"
    if not (root / "src" / "core" / "planner.ts").is_file():
        return "there is no SparkBench checkout in " + str(root)
    if not (root / "node_modules").is_dir():
        return "SparkBench's npm packages are not installed in " + str(root)
    if not _TSX.is_file():
        return "the bridge's tsx is not installed in " + str(_TSX.parents[2])
    return None


def head(root: Path | None = None) -> str:
    """The commit the checkout is at, read from its .git folder; "unknown" without one."""

    git = (root or checkout()) / ".git"
    try:
        ref = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not ref.startswith("ref: "):
            return ref
        name = ref[5:]
        if (git / name).is_file():
            return (git / name).read_text(encoding="utf-8").strip()
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + name):
                return line.split(" ", 1)[0]
    except OSError:
        pass
    return "unknown"


def source() -> str:
    return "sparkbench@" + head()[:7]


async def design(request: dict, directory: Path, prefix: str) -> dict:
    """Runs the bridge on the request, or reuses an identical earlier run, and puts the files in directory.

    Returns the bridge's result: `ok`, and on success the circuit, `files` (kind to file name in directory) and
    `cached`. A request SparkBench rejects (a board out of pins) comes back as ok false with its words.
    Raises SparkBenchFailed when the bridge itself fails or runs longer than TIMEOUT_S.
    """

    root = checkout()
    entry = cache.key("circuit", head(root), cache.digest(BRIDGE), cache.digest(Path(__file__)), cache.tool_version(node()), request)
    targets = {"circuit" + suffix: directory / (prefix + suffix) for suffix in FILES.values()}
    meta = cache.restore("circuits", entry, targets)
    if meta is not None:
        return {**meta, "files": {kind: prefix + suffix for kind, suffix in FILES.items()}, "cached": True}
    with tempfile.TemporaryDirectory(prefix="anybuild-circuit-") as tmp:
        work = Path(tmp)
        out = work / "out"
        (work / "request.json").write_text(json.dumps({**request, "out": str(out)}), encoding="utf-8")
        await _run(root, work / "request.json")
        try:
            result = json.loads((out / "result.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SparkBenchFailed("SparkBench wrote no result: " + str(exc)) from exc
        if not result.get("ok"):
            return {**result, "cached": False}
        made = result.pop("files")
        directory.mkdir(parents=True, exist_ok=True)
        for kind in _COPIED:
            shutil.copyfile(out / made[kind], directory / (prefix + FILES[kind]))
        shutil.copyfile(out / "firmware" / "main.py", directory / (prefix + FILES["firmware_main"]))
        shutil.copyfile(out / made["project_json"], directory / (prefix + FILES["sparkbench_project"]))
        _zip(directory / (prefix + FILES["firmware_zip"]), out, {Path(name).name: name for name in made["firmware"]})
        stem = Path(made["kicad_sch"]).stem
        kicad = [made["kicad_pro"], made["kicad_sch"], made["netlist"], *made["footprints"]]
        _zip(directory / (prefix + FILES["kicad_zip"]), out, {stem + "/" + name: name for name in kicad})
    cache.store("circuits", entry, {"circuit" + suffix: directory / (prefix + suffix) for suffix in FILES.values()}, result)
    return {**result, "files": {kind: prefix + suffix for kind, suffix in FILES.items()}, "cached": False}


async def _run(root: Path, request: Path) -> None:
    binary = node()
    if binary is None:
        raise SparkBenchFailed("Node.js is not installed")
    env = {key: os.environ[key] for key in _ENV_KEYS if key in os.environ}
    env["SPARKBENCH_DIR"] = str(root)
    process = await asyncio.create_subprocess_exec(
        binary,
        str(_TSX),
        str(BRIDGE),
        str(request),
        cwd=root,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # tsx starts the script in a child process: the whole group stops on a timeout or a stopped run.
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), TIMEOUT_S)
    except (TimeoutError, asyncio.CancelledError) as exc:
        _kill(process)
        await process.wait()
        if isinstance(exc, TimeoutError):
            raise SparkBenchFailed(f"SparkBench ran longer than {TIMEOUT_S:g} s") from exc
        raise
    if process.returncode != 0:
        tail = (stderr or stdout or b"").decode("utf-8", "replace").strip()[-600:]
        raise SparkBenchFailed(f"SparkBench stopped with exit code {process.returncode}: {tail or 'no output'}")


def _kill(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _zip(path: Path, root: Path, members: dict[str, str]) -> None:
    """A zip that is the same bytes for the same files: fixed dates and modes, sorted names."""

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, _ZIP_TIME)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (root / members[name]).read_bytes())
