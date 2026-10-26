"""SolidCraft, run as its own program: parts with joints, mechanisms and their robot descriptions.

SolidCraft (github.com/tangency-labs/solidcraft, MIT OR Apache-2.0) is parametric CAD in Rust: a feature
timeline over named parameters, components placed by joints, motion links and studies, and a URDF export.
AnyBuild runs its headless `solidcraft-cli` at VERSION. agent/scripts/setup_solidcraft.sh installs the
release binary outside the repository, in ~/.cache/anybuild/solidcraft/<version> (SOLIDCRAFT_DIR names
another folder, SOLIDCRAFT_CLI another binary); nothing of SolidCraft is linked in or shipped.
`PAI_CAD_ENGINE=solidcraft` gives Mechanic the tools built on it (`tools/solidcraft_part.py`).

A design is a command script, {"commands": [...]}, the commands SolidCraft's own interface runs.
`check_script` lets through only commands that model, assemble, move and measure, never one that names
a path. Every run happens in a fresh scratch folder with a scrubbed environment, on macOS inside
sandbox-exec (no network, writes only there). `build` runs a script twice: once to learn its bodies,
then with the build material on every body the script left at SolidCraft's default and AnyBuild's
inspections and exports appended, giving STEP, STL, one STL per body, a GLB, the saved .solidcraft
design and a picture, with what SolidCraft measured: bodies, components, joints and motion links,
motion studies and parameters.

`export_robot` writes the URDF with SolidCraft's own exporter (one link per part with its mesh, mass and
inertia) and reads, in the same run, what the MJCF needs: the joints with their frames and values, the
components, every body's mass and centre of mass, and the poses of the motion study.
`solidcraft_mjcf.py` turns that URDF into MJCF and runs it in MuJoCo.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pai_agent.mesh_export import stls_to_glb
from pai_agent.paths import AGENT_ROOT

log = logging.getLogger(__name__)

VERSION = "0.23.0"
REPOSITORY = "https://github.com/tangency-labs/solidcraft"
INSTALL_HINT = (
    "Install it once with bash agent/scripts/setup_solidcraft.sh (needs the network), "
    "or set SOLIDCRAFT_CLI to a solidcraft-cli " + VERSION + "."
)
ENGINES = ("freecad", "solidcraft")
SOLIDCRAFT_DIR = AGENT_ROOT / "solidcraft"
SKILLS_DIR = SOLIDCRAFT_DIR / "skills"
LIBRARY_DIR = SOLIDCRAFT_DIR / "library"
# A design builds in about a second and draws in a fraction of one; this only stops a stuck run.
TIMEOUT_S = 60
MAX_COMMANDS = 2000
MAX_SCRIPT_CHARS = 400_000
SNAPSHOT_SIZE = (1024, 768)
# The environment a run gets: no keys, it needs none.
_ENV = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}

# What a script may run: modelling, assembly, joints, motion and measuring. File, document, view, render, canvas,
# browser and app commands are not needed for a build, and AnyBuild assigns the material, exports and draws itself.
_NAMESPACES = {
    "appearance", "assembly", "body", "component", "config", "construct", "contact", "edit", "explode", "expr", "face",
    "frame", "inspect", "joint", "material", "mesh", "model", "motion", "occurrence", "parameters", "parts", "plastic",
    "sheet", "sketch", "solid", "surface", "timeline",
}
_COMMANDS = {"file.new", "document.units", "document.inspect", "document.metadata", "document.metadata.set"}
# Anything that reads or writes a file names it; no command of a design may.
_PATH_KEYS = {"path", "paths", "dir", "folder", "file"}

_warned_engine: set[str] = set()


class SolidCraftFailed(Exception):
    """solidcraft-cli ran and reported an error, or did not run at all; the message is for the agent."""


class ScriptRejected(Exception):
    """The script breaks AnyBuild's rules for a design; it never ran."""


def engine() -> str:
    """The CAD engine set by PAI_CAD_ENGINE: freecad (the default) or solidcraft."""

    value = os.environ.get("PAI_CAD_ENGINE", "").strip().lower() or "freecad"
    if value in ENGINES:
        return value
    if value not in _warned_engine:
        _warned_engine.add(value)
        log.warning("PAI_CAD_ENGINE=%s is neither freecad nor solidcraft; FreeCAD stays the engine.", value)
    return "freecad"


def install_dir() -> Path:
    own = os.environ.get("SOLIDCRAFT_DIR", "").strip()
    if own:
        return Path(own).expanduser()
    base = os.environ.get("XDG_CACHE_HOME", "").strip() or str(Path.home() / ".cache")
    return Path(base) / "anybuild" / "solidcraft" / VERSION


def _candidates() -> list[Path]:
    own = os.environ.get("SOLIDCRAFT_CLI", "").strip()
    if own:
        return [Path(own).expanduser()]
    found = [install_dir() / "solidcraft-cli"]
    on_path = shutil.which("solidcraft-cli")
    if on_path:
        found.append(Path(on_path))
    return found


_versions: dict[tuple[str, int], str] = {}


def _version(path: Path) -> str:
    """What `solidcraft-cli --version` says, once per binary file."""

    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return ""
    if key not in _versions:
        try:
            done = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL, check=False)
            text = done.stdout.strip() if done.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            text = ""
        _versions[key] = text.removeprefix("solidcraft-cli").strip()
    return _versions[key]


def _usable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def cli() -> Path | None:
    """The pinned solidcraft-cli on this machine, or None."""

    return next((path for path in _candidates() if _usable(path) and _version(path) == VERSION), None)


def missing() -> str | None:
    """Why SolidCraft cannot run on this machine, or None when it can."""

    candidates = _candidates()
    for path in candidates:
        if _usable(path) and _version(path) == VERSION:
            return None
    for path in candidates:
        if _usable(path):
            found = _version(path) or "unknown"
            return f"the solidcraft-cli at {path} is version {found}, and AnyBuild is pinned to {VERSION}"
    if os.environ.get("SOLIDCRAFT_CLI", "").strip():
        return f"SOLIDCRAFT_CLI names {candidates[0]}, which is not an executable file"
    return f"solidcraft-cli {VERSION} is not installed"


def source() -> str:
    return "solidcraft@" + VERSION


# --- Scripts ----------------------------------------------------------------------------------------------------


def check_script(script: object) -> list[dict]:
    """The script's commands, after AnyBuild's rules; raises ScriptRejected with a message the agent can act on.

    A script is {"commands": [...]} (a bare list or its JSON text works too); each command is
    {"command": "namespace.name", "params": {...}}.
    """

    if isinstance(script, str):
        if len(script) > MAX_SCRIPT_CHARS:
            raise ScriptRejected(f"The script is longer than {MAX_SCRIPT_CHARS} characters.")
        try:
            script = json.loads(script)
        except ValueError as exc:
            raise ScriptRejected("The script is not valid JSON: " + str(exc)) from exc
    commands = script.get("commands") if isinstance(script, dict) else script
    if not isinstance(commands, list) or not commands:
        raise ScriptRejected('A script is {"commands": [{"command": ..., "params": {...}}, ...]} with at least one command.')
    if len(commands) > MAX_COMMANDS:
        raise ScriptRejected(f"The script has {len(commands)} commands; keep it under {MAX_COMMANDS}.")
    out = []
    for number, row in enumerate(commands, 1):
        if not isinstance(row, dict) or not isinstance(row.get("command"), str):
            raise ScriptRejected(f'Step {number} is not {{"command": "...", "params": {{...}}}}.')
        name = row["command"].strip()
        params = row.get("params")
        params = {} if params is None else params
        if not isinstance(params, dict):
            raise ScriptRejected(f"Step {number} ({name}): params must be an object.")
        if name not in _COMMANDS and name.split(".")[0] not in _NAMESPACES:
            raise ScriptRejected(
                f"Step {number} ({name}): a design may only model, assemble, move and measure "
                "(sketch, solid, surface, construct, parameters, component, occurrence, joint, motion, contact, material, appearance, inspect ...); "
                "AnyBuild exports, saves and draws the design itself."
            )
        key = _path_key(params)
        if key:
            raise ScriptRejected(f"Step {number} ({name}): `{key}` names a file; a design may not read or write files.")
        out.append({"command": name, "params": params})
    return out


def _path_key(value: object) -> str | None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in _PATH_KEYS:
                return key
            found = _path_key(inner)
            if found:
                return found
    elif isinstance(value, list):
        for inner in value:
            found = _path_key(inner)
            if found:
                return found
    return None


_NUMBER = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*([A-Za-z]*)\s*$")


def with_params(commands: list[dict], values: dict[str, float]) -> list[dict]:
    """The commands, then one parameters.change that gives user parameters new values.

    That is what moving a parameter in SolidCraft does: the timeline rebuilds, and the faces and edges the script
    picked follow the geometry. Writing a value into the script instead would resolve its picks again at the new
    size, where a point picked on the old geometry can miss (the four-bar's coupler pins do).
    A value is a number in the parameter's own unit: the unit of the number the script last set it to (20 mm,
    360 deg), or that command's `unit`, else mm. Raises ValueError for a name no command of the script sets.
    """

    if not values:
        return list(commands)

    def expression(old: object, unit: object, value: float) -> str:
        match = _NUMBER.match(str(old))
        own = match.group(1) if match and match.group(1) else (str(unit) if unit is not None else ("" if match else "mm"))
        return f"{float(value):g} {own}".strip()

    changes = {}
    for name, value in values.items():
        for row in reversed(commands):
            params = row["params"]
            if row["command"] in ("parameters.add", "parameters.change") and params.get("name") == name and "expression" in params:
                changes[name] = expression(params["expression"], params.get("unit"), value)
                break
            if row["command"] == "parameters.change" and isinstance(params.get("changes"), dict) and name in params["changes"]:
                changes[name] = expression(params["changes"][name], None, value)
                break
        else:
            known = sorted({str(row["params"]["name"]) for row in commands if row["command"] == "parameters.add" and row["params"].get("name")})
            raise ValueError(f"{name} is not a parameter the script sets" + (": it sets " + ", ".join(known) + "." if known else "."))
    return [*commands, {"command": "parameters.change", "params": {"changes": changes}}]


def design_name(commands: list[dict], fallback: str) -> str:
    """The name file.new gives the design, else the fallback."""

    for row in commands:
        if row["command"] == "file.new" and str(row["params"].get("name") or "").strip():
            return str(row["params"]["name"]).strip()
    return fallback


# --- Running solidcraft-cli ---------------------------------------------------------------------------------------


def _sandbox_profile(work: Path) -> str:
    return (
        "(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n"
        f'(allow file-write* (subpath "{work}") (subpath "/private/var/folders") (subpath "/dev"))\n'
    )


def _run(args: list[str], work: Path, timeout_s: float = TIMEOUT_S) -> None:
    """solidcraft-cli with args in work; raises SolidCraftFailed with SolidCraft's own words."""

    binary = cli()
    if binary is None:
        raise SolidCraftFailed("SolidCraft is not installed on this machine: " + str(missing()) + ". " + INSTALL_HINT)
    command = [str(binary), *args]
    sandbox = shutil.which("sandbox-exec")
    if sandbox:
        (work / "sandbox.sb").write_text(_sandbox_profile(work), encoding="utf-8")
        command = [sandbox, "-f", str(work / "sandbox.sb"), *command]
    env = {**_ENV, "HOME": str(work), "TMPDIR": str(work)}
    # Output goes to files, not pipes, so a child that keeps a pipe open cannot hang the run.
    with open(work / "stdout.txt", "wb") as out, open(work / "stderr.txt", "wb") as err:
        process = subprocess.Popen(command, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
        try:
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise SolidCraftFailed(f"SolidCraft ran longer than {timeout_s:g} s.") from exc
    if process.returncode != 0:
        text = (work / "stderr.txt").read_text(encoding="utf-8", errors="replace").strip()
        lines = [line.removeprefix("error:").strip() for line in text.splitlines() if line.strip()]
        raise SolidCraftFailed(" ".join(lines)[:800] or f"solidcraft-cli stopped with exit code {process.returncode}.")


def _results(commands: list[dict], work: Path, save: bool = False) -> list:
    """Runs the commands as one script and returns each command's result, in order."""

    (work / "script.json").write_text(json.dumps({"commands": commands}), encoding="utf-8")
    args = ["run", "script.json", "--results", "--json-out", "results.json"]
    if save:
        args += ["--save", "design.solidcraft"]
    _run(args, work)
    rows = json.loads((work / "results.json").read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) != len(commands):
        raise SolidCraftFailed("SolidCraft returned no result per command.")
    return rows


def _step_error(exc: SolidCraftFailed, script_steps: int) -> SolidCraftFailed:
    """A failure in a command AnyBuild appended is SolidCraft's or AnyBuild's, not the script's: it says so."""

    match = re.match(r"step (\d+) \(([^)]+)\)", str(exc))
    if match and int(match.group(1)) > script_steps:
        return SolidCraftFailed(f"The script ran, then AnyBuild's {match.group(2)} after it failed: " + str(exc))
    return exc


# --- Building a design -------------------------------------------------------------------------------------------


@dataclass
class Build:
    """What SolidCraft built and measured; the files are in the output folder under the stem."""

    name: str
    commands: list[dict]
    bodies: list[dict]
    components: list[dict]
    joints: list[dict]
    links: list[dict]
    studies: list[dict]
    parameters: list[dict]
    mass_g: float
    volume_mm3: float
    bbox_mm: list[float]
    assigned: list[str]
    files: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def material_commands(material: str, density: float, bodies: list[str]) -> list[dict]:
    """The build material on the bodies the script left at SolidCraft's default."""

    if not bodies:
        return []
    name = "AnyBuild " + material
    return [
        {"command": "material.create", "params": {"name": name, "density_g_cm3": density}},
        {"command": "material.assign", "params": {"bodies": bodies, "material": name}},
    ]


def _inspections() -> list[dict]:
    return [
        {"command": "inspect.measure", "params": {}},
        {"command": "component.list", "params": {"compact": True, "bodies": True}},
        {"command": "joint.list", "params": {}},
        {"command": "motion.list", "params": {}},
        {"command": "parameters.list", "params": {"filter": "user"}},
    ]


def build(commands: list[dict], material: str, density: float, directory: Path, stem: str, fallback_name: str) -> Build:
    """Builds the checked commands and puts STEP, STL, per-body STL, GLB, design, script and picture in directory."""

    steps = len(commands)
    with tempfile.TemporaryDirectory(prefix="pai-solidcraft-") as tmp:
        work = Path(tmp).resolve()
        first = _results(commands + [{"command": "inspect.measure", "params": {}}], work)[-1]
        assign = [row["name"] for row in first.get("bodies", []) if row.get("closed") and row.get("material") == "Default"]
        extra = material_commands(material, density, assign)
        rows = _inspections()
        names = [row["name"] for row in first.get("bodies", [])]
        unique = len(set(names)) == len(names)
        exports = [
            {"command": "file.export", "params": {"path": str(work / "part.step")}},
            {"command": "file.export", "params": {"path": str(work / "part.stl")}},
        ]
        if unique:
            exports += [{"command": "file.export", "params": {"path": str(work / f"body-{i}.stl"), "bodies": [name]}} for i, name in enumerate(names)]
        exported = {name: work / f"body-{i}.stl" for i, name in enumerate(names)} if unique else {}
        try:
            results = _results(commands + extra + rows + exports, work, save=True)
        except SolidCraftFailed as exc:
            raise _step_error(exc, steps) from exc
        start = steps + len(extra)
        measure, components, joints, studies, parameters = results[start : start + len(rows)]
        components = components.get("components", [])
        bodies = _bodies(measure, components, commands)
        drawn = _snapshot(work)
        directory.mkdir(parents=True, exist_ok=True)
        files = {
            "step": directory / (stem + ".step"),
            "stl": directory / (stem + ".stl"),
            "glb": directory / (stem + ".glb"),
            "design": directory / (stem + ".solidcraft"),
            "script": directory / (stem + ".json"),
        }
        shutil.copyfile(work / "part.step", files["step"])
        shutil.copyfile(work / "part.stl", files["stl"])
        shutil.copyfile(work / "design.solidcraft", files["design"])
        if drawn:
            files["png"] = directory / (stem + ".png")
            shutil.copyfile(work / "view.png", files["png"])
        files["script"].write_text(json.dumps({"commands": commands}, indent=1), encoding="utf-8")
        nodes = []
        for i, body in enumerate(bodies):
            if body["name"] in exported:
                kept = directory / f"{stem}-{i}.stl"
                shutil.copyfile(exported[body["name"]], kept)
                body["stl"] = kept.name
                nodes.append((body["name"], kept, body.get("color")))
        if not nodes:
            nodes.append((design_name(commands, fallback_name), files["stl"], None))
        stls_to_glb(nodes, files["glb"])
    closed = [body for body in bodies if body["closed"]]
    boxes = np.array([body["bbox_mm"] for body in bodies]) if bodies else np.zeros((1, 6))
    bbox = [float(v) for v in [*boxes[:, :3].min(axis=0), *boxes[:, 3:].max(axis=0)]]
    total = measure.get("total", {})
    warnings = [] if unique else ["Two bodies share a name, so the 3D view shows the design as one body."]
    if not drawn:
        warnings.append("SolidCraft could not draw the design on this machine, so there is no picture.")
    if total.get("open_bodies_skipped"):
        warnings.append(f"{total['open_bodies_skipped']} open surface bodies have no volume or mass.")
    return Build(
        name=design_name(commands, fallback_name),
        commands=commands,
        bodies=bodies,
        components=components,
        joints=joints.get("joints", []),
        links=joints.get("links", []) or [],
        studies=studies.get("studies", []) or [],
        parameters=parameters.get("parameters", []) or [],
        mass_g=round(float(total.get("mass_g") or sum(b["mass_g"] for b in closed)), 3),
        volume_mm3=round(float(total.get("volume_mm3") or sum(b["volume_mm3"] for b in closed)), 2),
        bbox_mm=[round(v, 3) for v in bbox],
        assigned=assign,
        files=files,
        warnings=warnings + _joint_warnings(joints),
    )


def _joint_warnings(joints: dict) -> list[str]:
    out = []
    for conflict in joints.get("conflicts") or []:
        out.append("A joint loop cannot close: " + json.dumps(conflict, ensure_ascii=False)[:200])
    for floating in joints.get("floating") or []:
        out.append("Parts joined to nothing grounded never move: " + json.dumps(floating, ensure_ascii=False)[:200])
    for error in joints.get("errors") or []:
        out.append("Joint error: " + str(error)[:200])
    return out


_PALETTE = ("#4a5563", "#328bd3", "#e3ab4b", "#3ea69b", "#d95360", "#8b7cf6", "#40b460", "#ff8a3d")


def _bodies(measure: dict, components: list[dict], commands: list[dict]) -> list[dict]:
    """Per body: its numbers from measure, the component holding it, and its colour from the script."""

    owner = {}
    for index, component in enumerate(components):
        for name in component.get("bodies") or []:
            owner[name] = (component, index)
    colours = _colours(commands)
    out = []
    for row in measure.get("bodies", []):
        component, index = owner.get(row["name"], (None, 0))
        keys = [row["name"]] + ([str(component["name"]), str(component["id"])] + [str(o["name"]) for o in component.get("occurrences") or []] if component else [])
        colour = next((colours[key] for key in keys if key in colours), None) or _PALETTE[index % len(_PALETTE)]
        box = row.get("bbox") or {"min": [0, 0, 0], "max": [0, 0, 0]}
        out.append(
            {
                "name": row["name"],
                "component": component["name"] if component and component.get("parent") is not None else None,
                "closed": bool(row.get("closed")),
                "volume_mm3": round(float(row.get("volume_mm3") or 0.0), 3),
                "mass_g": round(float(row.get("mass_g") or 0.0), 4),
                "material": row.get("material"),
                "bbox_mm": [float(v) for v in [*box["min"], *box["max"]]],
                "color": colour,
            }
        )
    return out


def _colours(commands: list[dict]) -> dict[str, str]:
    """Body or component name to the last colour appearance.assign gives it in the script."""

    out: dict[str, str] = {}
    for row in commands:
        params = row["params"]
        colour = params.get("color")
        if row["command"] != "appearance.assign" or not isinstance(colour, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
            continue
        for key in ("bodies", "components"):
            for name in params.get(key) or []:
                out[str(name)] = colour.lower()
    return out


def _snapshot(work: Path) -> bool:
    """SolidCraft's own picture of the saved design; False when it cannot draw here (the build stands without it)."""

    width, height = SNAPSHOT_SIZE
    try:
        _run(["snapshot", "design.solidcraft", "--out", "view.png", "--width", str(width), "--height", str(height), "--view", "iso"], work)
    except SolidCraftFailed as exc:
        log.warning("SolidCraft snapshot failed: %s", exc)
        return False
    return (work / "view.png").is_file()


# --- The robot description ----------------------------------------------------------------------------------------


@dataclass
class Robot:
    """SolidCraft's URDF export of a design and what the MJCF and its check need from the same run."""

    urdf: Path
    meshes: list[Path]
    joints: dict
    components: list[dict]
    properties: dict
    measure: dict
    study: dict | None
    motion: dict | None
    warnings: list[str]


def export_robot(commands: list[dict], extra: list[dict], directory: Path, stem: str, effort: float | None, velocity: float | None, study: dict | None) -> Robot:
    """The design's URDF with its STL meshes in directory, and the joints, components, masses and the
    motion study's poses read in the same run.

    extra are the material commands of its build; study is the motion study to sample ({name, steps}), if any.
    """

    steps = len(commands)
    with tempfile.TemporaryDirectory(prefix="pai-solidcraft-") as tmp:
        work = Path(tmp).resolve()
        rows = [
            {"command": "joint.list", "params": {}},
            {"command": "component.list", "params": {"compact": True, "bodies": True}},
            {"command": "component.properties", "params": {"component": "root"}},
            {"command": "inspect.measure", "params": {}},
            {"command": "motion.list", "params": {}},
        ]
        export = {"path": str(work / (stem + ".urdf"))}
        if effort is not None:
            export["effort"] = effort
        if velocity is not None:
            export["velocity"] = velocity
        tail = [{"command": "file.export", "params": export}]
        if study:
            # One sample per step up to 36, then evenly spaced: enough to follow a whole crank turn.
            samples = min(int(study.get("steps") or 1), 36) + 1
            tail.insert(0, {"command": "motion.export", "params": {"study": study["name"], "samples": samples}})
        try:
            results = _results(commands + extra + rows + tail, work)
        except SolidCraftFailed as exc:
            raise _step_error(exc, steps) from exc
        joints, components, properties, measure, studies = results[steps + len(extra) : steps + len(extra) + len(rows)]
        chosen = next((row for row in studies.get("studies") or [] if study and row.get("name") == study["name"]), None)
        motion = results[-2] if study else None
        written = results[-1]
        urdf = Path(written["path"])
        directory.mkdir(parents=True, exist_ok=True)
        meshes = []
        for name in written.get("files") or []:
            path = Path(name)
            if path.suffix.lower() == ".stl":
                shutil.copyfile(path, directory / path.name)
                meshes.append(directory / path.name)
        shutil.copyfile(urdf, directory / urdf.name)
    return Robot(
        urdf=directory / urdf.name,
        meshes=meshes,
        joints=joints,
        components=components.get("components", []),
        properties=properties,
        measure=measure,
        study=chosen,
        motion=motion,
        warnings=list(written.get("warnings") or []),
    )


def mj_name(name: str) -> str:
    """A SolidCraft name as SolidCraft's URDF writes it: A-Z a-z 0-9 and _ only."""

    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def link_names(components: list[dict]) -> dict[int, str]:
    """Occurrence id to the URDF link SolidCraft makes of it: the component's name when it is placed once,
    else the occurrence's name; the root's bodies are base_link."""

    names = {0: "base_link"}
    for component in components:
        occurrences = component.get("occurrences") or []
        for occurrence in occurrences:
            names[int(occurrence["id"])] = component["name"] if len(occurrences) == 1 else occurrence["name"]
    return names
