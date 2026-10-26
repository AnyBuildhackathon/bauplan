"""Runs a generated FreeCAD part script headless, sandboxed, with a timeout.

The script is checked statically first (imports, dunder access, file and process
calls), then runs under freecadcmd in a fresh temp directory with a scrubbed
environment, so no API key ever reaches it. On macOS, sandbox-exec also denies
network access and writes outside that directory. The harness in
agent/freecad/part_harness.py exports STL, STEP and per-part volumes.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pai_agent.freecad_run import find_freecadcmd
from pai_agent.mesh_export import stls_to_glb
from pai_agent.paths import AGENT_ROOT

HARNESS = AGENT_ROOT / "freecad" / "part_harness.py"
TIMEOUT_S = 60

# g/cm3. A part may name its own material; everything else uses the build material.
DENSITY_G_CM3 = {
    "PLA": 1.24,
    "PETG": 1.27,
    "ABS": 1.04,
    "ASA": 1.07,
    "NYLON": 1.14,
    "TPU": 1.21,
    "ALUMINIUM": 2.70,
    "STEEL": 7.85,
}
_ALLOWED_IMPORTS = {"FreeCAD", "Part", "math"}
_BANNED_NAMES = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "input",
    "breakpoint",
    "exit",
    "quit",
}
_BANNED_ATTRS = {"exportStep", "exportStl", "exportBrep", "exportIges", "saveAs", "write", "read"}


class ScriptRejected(Exception):
    """The script breaks the sandbox rules; it never ran."""


class ScriptFailed(Exception):
    """The script ran and FreeCAD reported an error (message is for the agent)."""


@dataclass
class PartBuild:
    parts: list[dict]
    bbox_mm: list[float]
    volume_mm3: float
    mass_g: float
    stl: Path
    step: Path
    glb: Path
    # What a template declares for simulation (joints, tool, collision, grip_surfaces); see pai_agent/mjcf_export.py.
    sim: dict | None = None


def density(material: str | None) -> float:
    key = (material or "PLA").strip().upper().replace("ALUMINUM", "ALUMINIUM")
    if key not in DENSITY_G_CM3:
        raise ValueError("Unknown material " + str(material) + ". Known: " + ", ".join(sorted(DENSITY_G_CM3)))
    return DENSITY_G_CM3[key]


def check_script(source: str) -> None:
    """Static sandbox check. Raises ScriptRejected with a message the agent can act on."""

    if len(source) > 40_000:
        raise ScriptRejected("The script is longer than 40000 characters.")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ScriptRejected("SyntaxError line " + str(exc.lineno) + ": " + str(exc.msg)) from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in _ALLOWED_IMPORTS:
                    raise ScriptRejected("Import of " + alias.name + " is not allowed. Use FreeCAD, Part and math only.")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in _ALLOWED_IMPORTS or node.level:
                raise ScriptRejected("Import from " + str(node.module) + " is not allowed. Use FreeCAD, Part and math only.")
        elif isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            raise ScriptRejected(node.id + " is not available in a part script.")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in _BANNED_ATTRS:
                raise ScriptRejected("Attribute ." + node.attr + " is not allowed; the harness exports the parts itself.")


def _sandbox_profile(work: Path) -> str:
    return (
        "(version 1)\n(allow default)\n(deny network*)\n(deny file-write*)\n"
        f'(allow file-write* (subpath "{work}") (subpath "/private/var/folders") (subpath "/dev"))\n'
    )


def check_geometry(result: dict, expected_mm: list[float] | None = None) -> None:
    """Rejects geometry a live build must not continue with: wrong units, slivers, the wrong size."""

    box = result["bbox_mm"]
    size = [box[i + 3] - box[i] for i in range(3)]
    if max(size) > 2000:
        raise ScriptFailed(
            "The part is " + " x ".join(f"{v:.0f}" for v in size) + " mm, over 2 m. Units are millimetres; check the numbers."
        )
    for row in result["parts"]:
        part = [row["bbox_mm"][i + 3] - row["bbox_mm"][i] for i in range(3)]
        if min(part) < 0.2:
            raise ScriptFailed("parts[" + repr(row["name"]) + "] is only " + f"{min(part):.2f}" + " mm thick somewhere; make every wall at least 0.8 mm.")
    if expected_mm:
        largest, wanted = max(size), max(expected_mm)
        if not 0.4 * wanted <= largest <= 2.5 * wanted:
            raise ScriptFailed(
                "The part is " + " x ".join(f"{v:.0f}" for v in size) + " mm, but the spec expects about "
                + " x ".join(f"{v:.0f}" for v in expected_mm) + " mm. Build it at the specified size."
            )


def run_script(
    source: str,
    params: dict,
    out_dir: Path,
    stem: str,
    material: str = "PLA",
    timeout_s: int = TIMEOUT_S,
    expected_mm: list[float] | None = None,
) -> PartBuild:
    """Builds the script in a temp dir, then copies STL, STEP and GLB to out_dir/stem.*"""

    check_script(source)
    base_density = density(material)
    binary = find_freecadcmd()
    if binary is None:
        raise ScriptFailed("freecadcmd is not installed, so generated parts cannot be built on this machine.")
    work = Path(tempfile.mkdtemp(prefix="pai-part-")).resolve()
    try:
        (work / "part_script.py").write_text(source, encoding="utf-8")
        (work / "params.json").write_text(json.dumps(params), encoding="utf-8")
        command = [binary, str(HARNESS)]
        sandbox = shutil.which("sandbox-exec")
        if sandbox:
            (work / "sandbox.sb").write_text(_sandbox_profile(work), encoding="utf-8")
            command = [sandbox, "-f", str(work / "sandbox.sb"), *command]
        env = {"PATH": "/usr/bin:/bin", "HOME": str(work), "TMPDIR": str(work), "LANG": "en_US.UTF-8", "PAI_PART_DIR": str(work)}
        # Output goes to files, not pipes: a FreeCAD helper that keeps a pipe open must not hang the build.
        with open(work / "stdout.txt", "wb") as log:
            process = subprocess.Popen(
                command, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
            )
            try:
                process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired as exc:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise ScriptFailed("The script ran longer than " + str(timeout_s) + " s. Use fewer boolean operations.") from exc
        result_path = work / "result.json"
        if not result_path.is_file():
            tail = (work / "stdout.txt").read_text(encoding="utf-8", errors="ignore").strip()[-400:]
            raise ScriptFailed("FreeCAD wrote no result. " + tail)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("ok"):
            raise ScriptFailed(str(result.get("error")) + "\n" + str(result.get("traceback") or ""))
        check_geometry(result, expected_mm)

        out_dir.mkdir(parents=True, exist_ok=True)
        mass = 0.0
        for row in result["parts"]:
            row_density = density(row.get("material")) if row.get("material") else base_density
            row["material"] = (row.get("material") or material).upper()
            row["mass_g"] = round(row["volume_mm3"] / 1000.0 * row_density, 2)
            if not row.get("reference"):
                mass += row["mass_g"]
        stl = out_dir / (stem + ".stl")
        step = out_dir / (stem + ".step")
        glb = out_dir / (stem + ".glb")
        shutil.copyfile(work / "part.stl", stl)
        shutil.copyfile(work / "part.step", step)
        for index, row in enumerate(result["parts"]):
            # Per-part meshes stay next to the part, for the colored GLB and the Blender render.
            kept = out_dir / (stem + "-" + str(index) + ".stl")
            shutil.copyfile(work / row["stl"], kept)
            row["stl"] = kept.name
        stls_to_glb([(row["name"], out_dir / row["stl"], row.get("color")) for row in result["parts"]], glb)
        (out_dir / (stem + ".py")).write_text(source, encoding="utf-8")
        return PartBuild(
            parts=result["parts"],
            bbox_mm=result["bbox_mm"],
            volume_mm3=float(result["volume_mm3"]),
            mass_g=round(mass, 2),
            stl=stl,
            step=step,
            glb=glb,
            sim=result.get("sim"),
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_script_cached(
    source: str,
    params: dict,
    out_dir: Path,
    stem: str,
    material: str = "PLA",
    expected_mm: list[float] | None = None,
) -> tuple[PartBuild, bool]:
    """run_script, but an identical script, parameters and material reuse the last FreeCAD result. Returns (build, cached)."""

    from pai_agent import cache

    entry = cache.key("part", source, params, material.upper(), expected_mm, cache.digest(HARNESS), cache.tool_version(find_freecadcmd()))
    meta = cache.restore("parts", entry, {})
    if meta is not None:
        names = ["part.stl", "part.step", "part.glb"] + [row["stl"] for row in meta["parts"]]
        targets = {name: out_dir / name.replace("part", stem, 1) for name in names}
        if cache.restore("parts", entry, targets) is not None:
            parts = [{**row, "stl": row["stl"].replace("part", stem, 1)} for row in meta["parts"]]
            (out_dir / (stem + ".py")).write_text(source, encoding="utf-8")
            return PartBuild(parts, meta["bbox_mm"], meta["volume_mm3"], meta["mass_g"], out_dir / (stem + ".stl"), out_dir / (stem + ".step"), out_dir / (stem + ".glb"), meta.get("sim")), True
    build = run_script(source, params, out_dir, stem, material, expected_mm=expected_mm)
    files = {"part.stl": build.stl, "part.step": build.step, "part.glb": build.glb}
    rows = []
    for row in build.parts:
        cached_name = "part" + row["stl"][len(stem):]
        files[cached_name] = out_dir / row["stl"]
        rows.append({**row, "stl": cached_name})
    cache.store("parts", entry, files, {"parts": rows, "bbox_mm": build.bbox_mm, "volume_mm3": build.volume_mm3, "mass_g": build.mass_g, "sim": build.sim})
    return build, False


def freecad_unavailable(error: str | None) -> bool:
    """FreeCAD is missing or stuck, as opposed to a script it rejected."""

    return find_freecadcmd() is None or "ran longer than" in str(error or "")


def run_block(size: list[float], center: list[float] | None, out_dir: Path, stem: str, material: str = "PLA") -> PartBuild:
    """Without a working FreeCAD, CadQuery builds the part's envelope as a plain block, so the assembly and checks go on."""

    import cadquery as cq
    from cadquery import exporters

    sx, sy, sz = (float(v) for v in size[:3])
    cx, cy, cz = (float(v) for v in (center or (0.0, 0.0, sz / 2.0))[:3])
    block = cq.Workplane("XY").box(sx, sy, sz).translate((cx, cy, cz))
    out_dir.mkdir(parents=True, exist_ok=True)
    stl = out_dir / (stem + ".stl")
    step = out_dir / (stem + ".step")
    glb = out_dir / (stem + ".glb")
    kept = out_dir / (stem + "-0.stl")
    exporters.export(block, str(stl))
    exporters.export(block, str(step))
    shutil.copyfile(stl, kept)
    stls_to_glb([("Block", kept, None)], glb)
    volume = sx * sy * sz
    mass = round(volume / 1000.0 * density(material), 2)
    bbox = [cx - sx / 2, cy - sy / 2, cz - sz / 2, cx + sx / 2, cy + sy / 2, cz + sz / 2]
    row = {"name": "Block", "volume_mm3": round(volume, 2), "mass_g": mass, "material": material.upper(), "reference": False, "bbox_mm": bbox, "stl": kept.name, "color": None}
    (out_dir / (stem + ".py")).write_text(
        "# Simplified block: FreeCAD was not available, CadQuery built the part's envelope.\n"
        f"shape = Part.makeBox({sx:g}, {sy:g}, {sz:g}, Vector({cx - sx / 2:g}, {cy - sy / 2:g}, {cz - sz / 2:g}))\n",
        encoding="utf-8",
    )
    return PartBuild(parts=[row], bbox_mm=bbox, volume_mm3=round(volume, 2), mass_g=mass, stl=stl, step=step, glb=glb)
