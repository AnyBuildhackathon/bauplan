"""Check adapters: the engines behind AnyBuild's checks, whether each is on this machine, and how each last ran.

Every check runs on a real engine: FreeCAD builds the parts, gmsh and CalculiX solve their FEM,
Blender renders, MuJoCo flies, grips, pushes and drops, the slicer plans the print, SparkBench,
KiCad, ngspice and Freerouting take the electronics, Robo Use judges a gripper from outside and
Isaac runs on a GPU pod. `report()` says for each one whether it is installed, where, which
version, what happens without it and how to install it.

It never starts a tool. It reads PATH, the usual application and bin folders and version files
(an app's Info.plist, a Homebrew or nvm folder, a package's dist-info), so it answers within
milliseconds. The two probes that talk to something are bounded: the open FreeCAD window is a
local port check, and the Isaac row reuses the cached SSH probe of `GET /api/status`, waits at
most `BUDGET_S` for a new one and answers the last known state, or `available: null`, meanwhile.

Each engine is looked up where the code that runs it looks: FreeCAD, Blender, CalculiX and the
slicer through their tools' own finders, SparkBench and Node.js as `circuit_design` finds them
(`sparkbench.py`), KiCad, ngspice, Java and Freerouting the way SparkBench's server finds them
(`server/api.ts`, `server/pcb.ts`), and Robo Use as `robouse_trial` finds it (`tools/robouse_trial.py`).

`RunLog` keeps each adapter's last run (when, whether it passed, one line) for this machine,
not per chat, in agent/runs/adapters.json, so it outlasts a reset and a restart. `watch` follows
the event stream like a dashboard and records only what happens live, never a replayed backlog.
GET /api/adapters serves both (docs/events.md, Check adapters).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import plistlib
import re
import shutil
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import metadata, util
from pathlib import Path

from pai_agent import fem, sparkbench, status
from pai_agent.freecad_run import find_freecadcmd, gui_mode, rpc_available
from pai_agent.paths import REPO_ROOT, RUNS_DIR
from pai_agent.tools.blender import find_blender
from pai_agent.tools.isaac import ssh_setting
from pai_agent.tools.print_prep import find_slicer
from pai_agent.tools.robouse_trial import robouse_cli

log = logging.getLogger(__name__)

DOMAINS = ("mechanics", "electronics", "simulation", "manufacturing")
# Seconds the Isaac row waits for a new SSH probe before it answers the last known state.
BUDGET_S = 0.2
# Searched after PATH for command-line tools: SparkBench's server never reads PATH for ngspice or
# kicad-cli, and a backend started from a GUI often lacks Homebrew on PATH.
BIN_DIRS = (Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/usr/bin"))
# macOS application folders; the user's own ~/Applications is searched first.
APP_DIRS = (Path("/Applications"),)
# Java for Freerouting comes from exactly these, never from PATH, in SparkBench's PCB job.
JAVA_PATHS = (
    Path("/opt/homebrew/opt/openjdk/bin/java"),
    Path("/usr/local/opt/openjdk/bin/java"),
    Path("/usr/lib/jvm/default-java/bin/java"),
)
JAVA_MIN = 21
FREEROUTING_JAR = "freerouting-2.5.0.jar"


@dataclass
class Found:
    """What one lookup saw. `available` is None while a slow probe still runs."""

    available: bool | None
    detail: str
    hint: str
    version: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class Adapter:
    id: str
    name: str
    domain: str
    provides: tuple[str, ...]
    probe: Callable[[], Found] | Callable[[], Awaitable[Found]]
    # Runs on another machine: available means reachable, not installed here.
    remote: bool = False


def _mac() -> bool:
    return sys.platform == "darwin"


def _home(path: str | Path) -> str:
    """A path for the answer, with the home folder as ~, so it never carries the user name."""

    text = str(path)
    home = str(Path.home())
    if home not in ("", "/") and (text == home or text.startswith(home + os.sep)):
        return "~" + text[len(home):]
    return text


def _homes(text: str) -> str:
    """`_home` for every path inside a sentence."""

    home = str(Path.home())
    return text.replace(home + os.sep, "~" + os.sep) if home not in ("", "/") else text


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _which(name: str) -> str | None:
    """`name` on PATH, else in the usual bin folders."""

    found = shutil.which(name)
    if found:
        return found
    for folder in BIN_DIRS:
        if _executable(folder / name):
            return str(folder / name)
    return None


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def _off(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "off"


def _app(path: str | Path) -> Path | None:
    """The macOS app bundle that holds `path`, if any."""

    try:
        real = Path(path).resolve()
    except (OSError, RuntimeError):
        return None
    return next((folder for folder in (real, *real.parents) if folder.suffix == ".app"), None)


def _app_version(app: Path) -> str | None:
    try:
        with open(app / "Contents" / "Info.plist", "rb") as handle:
            info = plistlib.load(handle)
    except (OSError, ValueError):
        return None
    return str(info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "").strip() or None


# A Homebrew formula or cask folder (a trailing _1 is Homebrew's own revision), or an nvm Node.
_KEG = re.compile(r"/(?:Cellar|Caskroom)/[^/]+/(\d[^/]*?)(?:_\d+)?/")
_NODE = re.compile(r"/node/v?(\d+\.\d+\.\d+)/")


def _version(path: str | Path) -> str | None:
    """A tool's version from its files: the Info.plist of the app it ships in, else the Homebrew or
    nvm folder it resolves into. Only for a tool that is its app's own product, such as kicad-cli."""

    app = _app(path)
    if app is not None:
        return _app_version(app)
    try:
        real = Path(path).resolve().as_posix()
    except (OSError, RuntimeError):
        return None
    match = _KEG.search(real) or _NODE.search(real)
    return match.group(1) if match else None


def _major(version: str | None) -> int | None:
    match = re.match(r"(\d+)", version or "")
    return int(match.group(1)) if match else None


def _package_version(venv: Path, name: str) -> str | None:
    """A package's version in a virtual environment, from its dist-info folder."""

    for info in sorted(venv.glob(f"lib/python*/site-packages/{name}-*.dist-info")):
        return info.name[len(name) + 1 : -len(".dist-info")]
    return None


def _java_major(java: Path) -> int | None:
    """The major version from the `release` file every JDK keeps next to its bin folder."""

    try:
        text = (java.resolve().parent.parent / "release").read_text(encoding="utf-8", errors="replace")
    except (OSError, RuntimeError):
        return None
    match = re.search(r'^JAVA_VERSION="(\d+)(?:\.(\d+))?', text, re.MULTILINE)
    if not match:
        return None
    major = int(match.group(1))
    # Java 8 and older call themselves 1.8.
    return int(match.group(2)) if major == 1 and match.group(2) else major


def _freecad() -> Found:
    hint = (
        "Install FreeCAD 1.0 or later with `brew install --cask freecad`"
        if _mac()
        else "Install FreeCAD 1.0 or later from freecad.org, with `freecadcmd` on PATH"
    ) + "; for the visible build, open FreeCAD with the freecad-mcp add-on."
    binary = find_freecadcmd()
    window = gui_mode() != "off" and rpc_available()
    if binary is None:
        if window:
            return Found(True, "Only the drone frame builds in FreeCAD, in the open window (freecad-mcp); freecadcmd is missing, so other parts are CadQuery blocks.", hint)
        return Found(False, "freecadcmd is missing, so CadQuery builds the drone frame and a plain block for every other part.", hint)
    if gui_mode() == "off":
        where = "FREECAD_GUI=off keeps the drone frame headless too."
    elif gui_mode() == "launch" and not window:
        where = "FREECAD_GUI=launch opens the FreeCAD window to build the drone frame visibly."
    elif window:
        where = "The open FreeCAD window builds the drone frame visibly (freecad-mcp)."
    else:
        where = "No FreeCAD window with freecad-mcp is open, so the drone frame builds headless too."
    return Found(True, "Builds every part headless in freecadcmd. " + where, hint, _version(binary), _home(binary))


def _calculix() -> Found:
    hint = (
        "Comes with FreeCAD (`brew install --cask freecad`), next to freecadcmd"
        if _mac()
        else "`sudo apt install calculix-ccx gmsh`, or FreeCAD, which ships both"
    ) + "; `PAI_CCX` and `PAI_GMSH` name other executables."
    off = next((name for name in ("PAI_CCX", "PAI_GMSH") if _off(name)), None)
    if off:
        return Found(False, f"Turned off with {off}=off, so the deflection check's beam estimate stands in for FEM.", hint)
    tools = fem.find_tools()
    if tools is None:
        return Found(False, "gmsh or CalculiX is missing, so the deflection check's beam estimate stands in for FEM.", hint)
    ccx = tools[1]
    app = _app(ccx)
    bundled = f"; both ship with FreeCAD {_app_version(app) or ''}".rstrip() if app is not None and app.name.startswith("FreeCAD") else ""
    return Found(True, "Meshes each printed part with gmsh and solves its load cases in CalculiX" + bundled + ".", hint, path=_home(ccx))


def _blender() -> Found:
    hint = "`brew install --cask blender`." if _mac() else "Install Blender from blender.org, with `blender` on PATH."
    binary = find_blender()
    if binary is None:
        return Found(False, "Blender is missing, so the render step shows a recorded still.", hint)
    return Found(True, "Renders every version's studio image headless and exports the drone as USD for Isaac.", hint, _version(binary), _home(binary))


def _sparkbench() -> Found:
    hint = "Install it once with `bash agent/scripts/setup_sparkbench.sh`, which needs Node.js 20 or newer and the network."
    root = sparkbench.checkout()
    commit = sparkbench.head(root)
    version, where = (None if commit == "unknown" else commit[:7]), (_home(root) if root.is_dir() else None)
    why = sparkbench.missing()
    if why:
        return Found(False, _homes(why[:1].upper() + why[1:]) + ", so circuit_design gives no circuit, firmware test or KiCad schematic.", hint, version, where)
    return Found(True, "Builds the firmware and the KiCad schematic of an ESP32 or Pico product and runs its acceptance tests in the simulator, headless.", hint, version, where)


def _kicad_apps() -> list[Path]:
    apps = [_env_path("KICAD_APP"), Path.home() / "Applications" / "KiCad.app"]
    for folder in APP_DIRS:
        apps += [folder / "KiCad" / "KiCad.app", folder / "KiCad.app"]
    return [app for app in apps if app is not None]


def find_kicad_cli() -> str | None:
    """kicad-cli as SparkBench's server finds it: KICAD_CLI, then the KiCad app (KICAD_APP or the
    application folders), then PATH and the usual bin folders."""

    explicit = _env_path("KICAD_CLI")
    if explicit is not None and _executable(explicit):
        return str(explicit)
    for app in _kicad_apps():
        cli = app / "Contents" / "MacOS" / "kicad-cli"
        if _executable(cli):
            return str(cli)
    return _which("kicad-cli")


def _kicad() -> Found:
    hint = (
        "Install KiCad 8 or later with `brew install --cask kicad`"
        if _mac()
        else "`sudo apt install kicad`, KiCad 8 or later"
    ) + "; `KICAD_APP` or `KICAD_CLI` point at another install."
    cli = find_kicad_cli()
    if cli is None:
        return Found(False, "Without kicad-cli there is no ERC, DRC or circuit board; SparkBench still writes the KiCad schematic.", hint)
    version = _version(cli)
    major = _major(version)
    if major is not None and major < 8:
        return Found(False, f"KiCad {version} is too old: SparkBench's boards need KiCad 8 or later.", hint, version, _home(cli))
    return Found(True, "Checks the schematic (ERC) and the board (DRC) and exports Gerbers, drill files and the board STEP.", hint, version, _home(cli))


def _ngspice() -> Found:
    hint = "`brew install ngspice`." if _mac() else "`sudo apt install ngspice`."
    binary = _which("ngspice")
    if binary is None:
        return Found(False, "Without ngspice the SPICE netlist is exported but not simulated.", hint)
    return Found(True, "Simulates the circuit's SPICE netlist in batch mode.", hint, _version(binary), _home(binary))


def find_freerouting() -> tuple[Path | None, Path | None]:
    """(jar, java) where SparkBench's PCB job takes them: FREEROUTING_JAR, else the 2.5.0 jar in
    ~/.cache/sparkbench/freerouting/; JAVA, else Homebrew's or the system's default OpenJDK."""

    jars = (_env_path("FREEROUTING_JAR"), Path.home() / ".cache" / "sparkbench" / "freerouting" / FREEROUTING_JAR)
    jar = next((path for path in jars if path is not None and path.is_file()), None)
    java = next((path for path in (_env_path("JAVA"), *JAVA_PATHS) if path is not None and _executable(path)), None)
    return jar, java


def _freerouting() -> Found:
    java_hint = "install it with `brew install openjdk`" if _mac() else "make it the default (`/usr/lib/jvm/default-java`)"
    hint = (
        f"Put `{FREEROUTING_JAR}` from github.com/freerouting/freerouting/releases in `~/.cache/sparkbench/freerouting/` "
        f"and Java {JAVA_MIN} or later beside it: {java_hint}; `FREEROUTING_JAR` and `JAVA` point at other installs."
    )
    jar, java = find_freerouting()
    if jar is None:
        return Found(False, "Without Freerouting SparkBench places a board but leaves its traces unrouted.", hint)
    match = re.search(r"(\d+\.\d+\.\d+)", jar.name)
    version, where = (match.group(1) if match else None), _home(jar)
    if java is None:
        return Found(False, f"The jar is there, but there is no Java {JAVA_MIN} or later where SparkBench looks for it.", hint, version, where)
    major = _java_major(java)
    if major is not None and major < JAVA_MIN:
        return Found(False, f"Java {major} is too old: Freerouting needs Java {JAVA_MIN} or later.", hint, version, where)
    return Found(True, "Routes the circuit board's traces offline" + (f", on Java {major}." if major else "."), hint, version, where)


def _node() -> Found:
    hint = "Install Node.js 20 or newer: `brew install node`." if _mac() else "Install Node.js 20 or newer from nodejs.org, with `node` on PATH."
    binary = sparkbench.node()
    if binary is None:
        return Found(False, "Node.js is not installed, so SparkBench cannot run.", hint)
    return Found(True, "SparkBench's headless build and its simulator run on it.", hint, _version(binary), _home(binary))


def _mujoco() -> Found:
    hint = "Part of the backend: `cd agent && uv sync`."
    if util.find_spec("mujoco") is None:
        return Found(False, "The backend environment lacks the mujoco package, so no simulation runs.", hint)
    try:
        version = metadata.version("mujoco")
    except metadata.PackageNotFoundError:
        version = None
    return Found(True, "Flies the hover test and the missions, and runs the grip, push and drop tests, in the backend.", hint, version)


def find_robouse() -> Path | None:
    """The `anybuild-robouse` command as `robouse_trial` finds it: PAI_ROBOUSE_BIN, else the bridge's own environment
    (`cd anybuild-robouse && uv sync`), else on PATH."""

    return robouse_cli()[0]


def _venv(script: Path) -> Path | None:
    try:
        root = script.resolve().parent.parent
    except (OSError, RuntimeError):
        return None
    return root if (root / "pyvenv.cfg").is_file() else None


def _robouse() -> Found:
    if (REPO_ROOT / "anybuild-robouse" / "pyproject.toml").is_file():
        hint = "`cd anybuild-robouse && uv sync`: its own environment, because Robo Use pins MuJoCo 3.3.0."
    else:
        hint = "Needs AnyBuild's Robo Use bridge, `anybuild-robouse`, in its own environment with `robouse[sim]==0.6.1`, which pins MuJoCo 3.3.0."
    if _off("PAI_ROBOUSE_BIN"):
        return Found(False, "Robo Use is turned off (PAI_ROBOUSE_BIN=off), so a gripper's independent trial is the recorded one.", hint)
    script = find_robouse()
    if script is None and os.environ.get("PAI_ROBOUSE_BIN", "").strip():
        return Found(False, "PAI_ROBOUSE_BIN names no program, so a gripper's independent trial is the recorded one.", hint)
    if script is None:
        robouse = shutil.which("robouse")
        if robouse:
            return Found(False, "Robo Use is installed, but not AnyBuild's gripper backend for it (anybuild-robouse).", hint, path=_home(robouse))
        return Found(False, "Robo Use is not installed, so no independent trial judges a designed gripper; AnyBuild's own grip test still runs.", hint)
    venv = _venv(script)
    engine = _package_version(venv, "mujoco") if venv else None
    detail = "Runs a designed gripper through Robo Use's tabletop tasks in its own environment" + (f", on MuJoCo {engine}." if engine else ".")
    return Found(True, detail, hint, _package_version(venv, "robouse") if venv else None, _home(venv or script))


# The last finished Isaac probe, answered while a new one still runs.
_isaac_seen: dict | None = None


def _remember_isaac(probe: asyncio.Future) -> None:
    global _isaac_seen
    if not probe.cancelled() and probe.exception() is None:
        _isaac_seen = probe.result()


async def _isaac() -> Found:
    hint = "Set `RUNPOD_SSH_HOST` and `RUNPOD_SSH_KEY` in `agent/.env` for a pod set up with `runpod/setup.sh`."
    host = ssh_setting("HOST")
    if not host:
        return Found(False, "No GPU host is configured, so Isaac runs fall back to recorded results.", hint)
    probe = asyncio.ensure_future(status.isaac_connection())
    probe.add_done_callback(_remember_isaac)
    try:
        connection = await asyncio.wait_for(asyncio.shield(probe), BUDGET_S)
    except TimeoutError:
        connection = _isaac_seen if _isaac_seen and _isaac_seen.get("host") == host else None
        if connection is None:
            return Found(None, f"Checking SSH to {host} …", hint)
    if connection.get("state") == "live":
        return Found(True, f"SSH to {host} works and nvidia-smi reports {connection.get('gpu') or 'a GPU'}.", hint)
    return Found(False, f"{host} is configured, but SSH or nvidia-smi failed, so Isaac runs fall back to recorded results.", hint)


def _slicer() -> Found:
    hint = (
        "`brew install --cask prusaslicer` or `brew install --cask orcaslicer`"
        if _mac()
        else "Install PrusaSlicer or OrcaSlicer, with `prusa-slicer` or `orca-slicer` on PATH"
    ) + "; `PAI_SLICER` names another executable."
    if _off("PAI_SLICER"):
        return Found(False, "Turned off with PAI_SLICER=off, so the print plan is an estimate from the mesh, with no G-code.", hint)
    found = find_slicer()
    if found is None:
        return Found(False, "Without a slicer the print plan is an estimate from the mesh, with no G-code.", hint)
    name, binary = found
    return Found(True, f"{name} slices every printed part headless: G-code, print time and filament.", hint, _version(binary), _home(binary))


# In the order the dialog shows them, grouped by domain.
ADAPTERS = (
    Adapter("freecad", "FreeCAD", "mechanics", ("Parametric CAD", "Mass from the solid"), _freecad),
    Adapter("calculix", "CalculiX and gmsh", "mechanics", ("FEM of printed parts",), _calculix),
    Adapter("blender", "Blender", "mechanics", ("Studio render", "USD for Isaac"), _blender),
    Adapter("sparkbench", "SparkBench", "electronics", ("Firmware simulation", "Acceptance tests", "KiCad schematic"), _sparkbench),
    Adapter("kicad", "KiCad CLI", "electronics", ("ERC", "DRC", "Gerbers"), _kicad),
    Adapter("ngspice", "ngspice", "electronics", ("SPICE simulation",), _ngspice),
    Adapter("freerouting", "Freerouting", "electronics", ("Autorouting",), _freerouting),
    Adapter("node", "Node.js", "electronics", ("SparkBench runtime",), _node),
    Adapter("mujoco", "MuJoCo", "simulation", ("Hover test", "Missions", "Grip test", "Push and drop"), _mujoco),
    Adapter("robouse", "Robo Use", "simulation", ("Independent grip trial",), _robouse),
    Adapter("isaac", "NVIDIA Isaac", "simulation", ("GPU wind test", "Isaac Lab training"), _isaac, remote=True),
    Adapter("slicer", "Slicer", "manufacturing", ("G-code", "Print time and filament"), _slicer),
)


async def _probe(adapter: Adapter) -> Found:
    try:
        if inspect.iscoroutinefunction(adapter.probe):
            return await adapter.probe()
        return await asyncio.to_thread(adapter.probe)
    except Exception as exc:  # noqa: BLE001 - one broken lookup must not hide the other adapters
        log.warning("Adapter lookup %s failed: %s", adapter.id, exc)
        return Found(False, f"The lookup itself failed: {type(exc).__name__}: {exc}"[:200], "")


async def report() -> list[dict]:
    """Every adapter's row, in ADAPTERS order, with its last run from the log."""

    runs = LOG.last()
    found = await asyncio.gather(*(_probe(adapter) for adapter in ADAPTERS))
    return [
        {
            "id": adapter.id,
            "name": adapter.name,
            "domain": adapter.domain,
            "provides": list(adapter.provides),
            "remote": adapter.remote,
            "available": seen.available,
            "version": seen.version,
            "path": seen.path,
            "detail": seen.detail,
            "install_hint": seen.hint,
            "last": runs.get(adapter.id),
        }
        for adapter, seen in zip(ADAPTERS, found)
    ]


def _verdict(name: str, passed: bool, text: object = None) -> str:
    return f"{name} {'passed' if passed else 'failed'}" + (f": {text}" if text else "")


def _cad_run(event: dict) -> tuple[str, bool, str] | None:
    if event.get("assembly"):
        return None  # the assembly merges parts that were each a run of their own
    what = (event.get("part") or {}).get("name") or "the drone"
    if event.get("source") == "freecad":
        return "freecad", True, f"Built {what} in " + ("the open FreeCAD window" if event.get("view_png_url") else "FreeCAD")
    if event.get("source") == "cadquery" and find_freecadcmd():
        return "freecad", False, f"FreeCAD failed or got stuck, so CadQuery built {what}"
    return None


def _render_run(event: dict) -> tuple[str, bool, str] | None:
    url = str(event.get("png_url") or "")
    if url.startswith("/files/fallback/"):
        if find_blender() is None:
            return None  # without Blender the recorded still is the plan, not a failed render
        return "blender", False, "Blender failed or took too long, so the recorded still stands in"
    return ("blender", True, "Rendered " + str(event.get("label") or "the studio image")) if url else None


def _sim_run(event: dict) -> tuple[str, bool, str] | None:
    if event.get("result") not in ("pass", "fail"):
        return None
    kind = event.get("kind")
    if kind == "grip":
        name = "Grip test"
    elif kind == "rigid":
        name = str(event.get("mode") or "rigid").capitalize() + " test"
    else:
        name = "Hover test"
    passed = event["result"] == "pass"
    return "mujoco", passed, _verdict(name, passed, event.get("summary"))


def _mission_run(event: dict) -> tuple[str, bool, str] | None:
    if event.get("result") not in ("pass", "fail"):
        return None
    name = str(event.get("label") or event.get("mission") or "Mission")
    if event.get("controller") == "trained":
        name += " with the trained controller"
    passed = event["result"] == "pass"
    return "mujoco", passed, _verdict(name, passed, event.get("summary"))


def _fem_run(event: dict) -> tuple[str, bool, str] | None:
    if event.get("result") not in ("pass", "fail"):
        return None
    passed = event["result"] == "pass"
    safety, limit = event.get("safety"), event.get("limit")
    numbers = f"safety {safety:.1f}x, needs {limit:g}x" if isinstance(safety, (int, float)) and isinstance(limit, (int, float)) else None
    return "calculix", passed, _verdict("FEM of " + str(event.get("part_name") or "a printed part"), passed, numbers)


def _print_run(event: dict) -> tuple[str, bool, str] | None:
    parts = [part for part in event.get("parts") or [] if isinstance(part, dict)]
    failed = next((part for part in parts if part.get("slicer_error")), None)
    if failed is not None:
        return "slicer", False, f"Slicing {failed.get('name') or 'a part'} failed: {str(failed['slicer_error'])[:160]}"
    if event.get("source") != "slicer" or not parts:
        return None  # no slicer here: the plan is an estimate from the mesh
    totals = event.get("totals") or {}
    count = totals.get("parts", len(parts))
    line = f"{event.get('slicer') or 'The slicer'} sliced {count} part{'' if count == 1 else 's'}"
    if isinstance(totals.get("time_min"), (int, float)) and isinstance(totals.get("filament_g"), (int, float)):
        line += f": {totals['time_min']:.0f} min, {totals['filament_g']:.0f} g of filament"
    return "slicer", True, line


def _circuit_run(event: dict) -> tuple[str, bool, str] | None:
    if not isinstance(event.get("ok"), bool):
        return None
    return "sparkbench", event["ok"], _verdict("Circuit", event["ok"], event.get("summary"))


def _trial_run(event: dict) -> tuple[str, bool, str] | None:
    if event.get("status") == "failed" and event.get("verdict") == "refused":
        return "robouse", False, str(event.get("summary") or event.get("error"))
    if event.get("status") != "done":
        return None  # running, or a recorded trial that is no run of Robo Use here
    passed = event.get("verdict") == "pass"
    return "robouse", passed, _verdict("Robo Use trial", passed, event.get("summary"))


def _isaac_run(event: dict) -> tuple[str, bool, str] | None:
    if event.get("source") != "live" or event.get("status") != "done":
        return None  # a recorded result is not a run of the pod
    what = "Isaac Lab training" if event.get("mode") == "train" else "Isaac Sim test"
    passed = event.get("passed")
    verdict = "finished" if passed is None else ("passed" if passed else "failed")
    return "isaac", passed is not False, f"{what} {verdict}" + (f": {event['detail']}" if event.get("detail") else "")


# The events that report an adapter's run. A tool that brings a new adapter adds its event here.
_RUNS: dict[str, Callable[[dict], tuple[str, bool, str] | None]] = {
    "cad": _cad_run,
    "render": _render_run,
    "sim": _sim_run,
    "mission": _mission_run,
    "fem": _fem_run,
    "print": _print_run,
    "circuit": _circuit_run,
    "trial": _trial_run,
    "omniverse": _isaac_run,
}


def run_of(event: dict) -> tuple[str, bool, str] | None:
    """(adapter id, passed, one line) when `event` reports a run of an adapter, else None."""

    reader = _RUNS.get(str(event.get("type")))
    if reader is None:
        return None
    try:
        return reader(event)
    except (TypeError, ValueError, KeyError, AttributeError):
        return None  # an event of another shape is no run


class RunLog:
    """The last run of each adapter on this machine, in a small JSON file keyed by adapter id."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def last(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {key: row for key, row in data.items() if isinstance(row, dict)}

    def record(self, event: dict) -> str | None:
        """Keeps `event` when it is an adapter run and returns that adapter's id."""

        run = run_of(event)
        if run is None:
            return None
        adapter, passed, summary = run
        # Read before writing, so a second backend on this checkout keeps the rows it wrote.
        runs = self.last()
        runs[adapter] = {"at": int(time.time()), "pass": passed, "summary": summary[:300]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        temp.write_text(json.dumps(runs, indent=1, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)
        return adapter


LOG = RunLog(RUNS_DIR / "adapters.json")


async def watch(bus) -> None:
    """Records every adapter run published on `bus`, until cancelled.

    It reads the stream the way a dashboard does. Everything before a `replayed` marker is a
    backlog: the session's events so far when it subscribes, or a saved chat's log after a `reset`
    with `replay`. Those ran before, so only the live events after the marker count."""

    live = False
    async for event in bus.stream():
        if event is None:
            continue
        kind = event.get("type")
        if kind == "replayed":
            live = True
        elif kind == "reset" and event.get("replay"):
            live = False
        elif live:
            try:
                LOG.record(event)
            except Exception:  # the log is a convenience; it never ends the watch
                log.exception("Could not record an adapter run")
