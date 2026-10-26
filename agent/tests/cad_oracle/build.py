"""Builds a reference part through the AnyBuild code a real build runs, and says what it wrote.

Each builder runs one CAD path into a directory and returns an Output: the STEP files, the STL that
print preparation slices, the GLB the 3D view shows, one STL per body, the numbers AnyBuild reported,
and for every STL the deflection it was written with, so the oracle knows how far a mesh may sit from
the exact solid. The paths:

- `freecad`: a part script in the FreeCAD harness (`cad_script.run_script`), the way `cad_part` runs
  the scripts Mechanic writes, the library templates and the reference builds' scripts, with their
  standard parts (`pai_agent.fasteners`) when the script has some;
- `block`: the CadQuery stand-in without FreeCAD (`cad_script.run_block`);
- `standard_part`: one screw, nut, washer or insert from `pai_agent.fasteners.hardware`;
- `drone_frame`: the drone's carbon frame from the CadQuery fallback (`drone_assembly`);
- `hero_frame`: the drone's carbon frame as headless FreeCAD builds it (`freecad_run.build_with_freecad`);
- `solidcraft`: a SolidCraft command script (`solidcraft.build`).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# Linear and angular deflection of each writer's STL (mm, rad), as the code under test sets them.
FREECAD_ANGULAR = 0.35  # agent/freecad/part_harness.py: MeshPart.meshFromShape(..., AngularDeflection=0.35)
CADQUERY_DEFAULT = (0.1, 0.1)  # cadquery.exporters.export without tolerances (run_block, drone_assembly)
HARDWARE_MESH = (0.02, 0.2)  # hardware.write_meshes
HERO_FRAME_MESH = (0.03, 0.3)  # agent/freecad/frame_build.py, export()
# SolidCraft 0.23 does not say; its cylinders come out within 0.002 mm of the solid, so this leaves room.
SOLIDCRAFT_MESH = (0.02, 0.1)


def freecad_deflection(bbox: list[float]) -> float:
    """The harness meshes each part to max(0.02, its bounding box diagonal / 800) mm.

    It takes the diagonal of FreeCAD's BoundBox before meshing, which bounds a circle by the octagon around it,
    up to 1 / cos(22.5 deg) = 8 % over the exact box this gets; 10 % covers that."""

    return max(0.02, 1.1 * max(math.dist(bbox[:3], bbox[3:]), 1.0) / 800.0)


@dataclass
class Body:
    name: str
    stl: Path
    # The STEP file that holds this body exactly; None for a part shown only for reference (a bought servo).
    step: Path | None
    printed: bool
    # What AnyBuild reports for the body: volume_mm3, bbox_mm, com_mm, mass_g (left out when it reports none).
    reported: dict
    deflection_mm: float
    angular_rad: float
    density_g_cm3: float | None = None


@dataclass
class Output:
    # The STEP of the printed part, the one the formulas and records describe.
    step: Path
    # Every printed body in one file, as print preparation slices it.
    stl: Path | None
    glb: Path | None
    bodies: list[Body]
    # The build's totals: volume_mm3, mass_g, bbox_mm.
    reported: dict
    # How far AnyBuild's own numbers may sit from the exact solid, relative; 0 means exact up to their rounding.
    reported_rel: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def printed(self) -> list[Body]:
        return [body for body in self.bodies if body.printed]


Builder = Callable[[Path], Output]


def _entries(fasteners: list | None, owner: str) -> list[dict] | None:
    """Standard part entries as cad_part checks them; one it refuses fails the build."""

    from pai_agent.fasteners import hardware

    if not fasteners:
        return None
    items, problems = hardware.normalize(fasteners, owner)
    if problems:
        raise ValueError(" ".join(problems))
    return items


def freecad(script: str, stem: str, *, params: dict | None = None, material: str = "PLA", template: str | None = None, fasteners: list | None = None) -> Builder:
    """A part script built as cad_part builds it: PARAMS (or a template's) resolved, standard parts normalized."""

    def build(directory: Path) -> Output:
        from pai_agent import part_params
        from pai_agent.cad_script import density, run_script
        from pai_agent.fasteners import hardware
        from pai_agent.tools import cad_part

        found = part_params.declaration(script)
        entries, contract = found if found is not None else (cad_part.template_params(template), None)
        values = part_params.resolve(entries, params or {}, {}).values
        # The time limit only stops a stuck build; on a busy machine several FreeCAD builds at once take longer than one.
        made = run_script(script, values, directory, stem, material, timeout_s=300, contract=contract, fasteners=_entries(fasteners, stem))
        bodies = [
            Body(
                row["name"], directory / row["stl"], None if row["reference"] else made.step, not row["reference"], row,
                freecad_deflection(row["bbox_mm"]), FREECAD_ANGULAR, density(row["material"]),
            )
            for row in made.parts
        ]
        bodies += _standard_parts(made.hardware, directory / hardware.step_name(stem))
        reported = {"volume_mm3": made.volume_mm3, "mass_g": made.mass_g, "bbox_mm": made.bbox_mm}
        return Output(made.step, made.stl, made.glb, bodies, reported, notes=list(made.hardware_warnings))

    return build


def block(size: list[float], stem: str, *, material: str = "PLA", fasteners: list | None = None) -> Builder:
    """The block CadQuery builds for a part when FreeCAD is missing, with its standard parts' holes."""

    def build(directory: Path) -> Output:
        from pai_agent.cad_script import density, run_block
        from pai_agent.fasteners import hardware

        made = run_block(size, None, directory, stem, material, _entries(fasteners, stem))
        row = made.parts[0]
        bodies = [Body(row["name"], directory / row["stl"], made.step, True, row, *CADQUERY_DEFAULT, density(material))]
        bodies += _standard_parts(made.hardware, directory / hardware.step_name(stem))
        reported = {"volume_mm3": made.volume_mm3, "mass_g": made.mass_g, "bbox_mm": made.bbox_mm}
        return Output(made.step, made.stl, made.glb, bodies, reported, notes=list(made.hardware_warnings))

    return build


def _standard_parts(rows: list[dict], step: Path) -> list[Body]:
    from pai_agent.fasteners import hardware

    return [
        Body(row["name"], step.parent / row["stl"], step, False, row, *HARDWARE_MESH, hardware.DENSITY[row["material"]])
        for row in rows
    ]


def standard_part(entry: dict, stem: str) -> Builder:
    """One standard part as a build writes it for the 3D view and the export: its STL and the part's hardware STEP."""

    def build(directory: Path) -> Output:
        from pai_agent.fasteners import hardware

        directory.mkdir(parents=True, exist_ok=True)
        rows = hardware.write_meshes(hardware.build(_entries([entry], stem)), directory, stem)
        step = directory / hardware.step_name(stem)
        bodies = _standard_parts(rows, step)
        reported = {"volume_mm3": sum(row["volume_mm3"] for row in rows), "mass_g": sum(row["mass_g"] for row in rows)}
        return Output(step, None, None, bodies, reported)

    return build


def drone_frame(params: dict) -> Builder:
    """The carbon frame plate the CadQuery fallback writes as frame.step and frame.stl (drone_assembly.build)."""

    def build(directory: Path) -> Output:
        from pai_agent import drone_assembly

        frame = drone_assembly.write_frame(directory, params)
        step, stl = directory / "frame.step", directory / "frame.stl"
        reported = {"mass_g": float(frame.val().Volume()) * drone_assembly._CARBON_G_PER_MM3}
        body = Body("Frame", stl, step, True, {}, *CADQUERY_DEFAULT, drone_assembly._CARBON_G_PER_MM3 * 1000.0)
        return Output(step, stl, None, [body], reported)

    return build


def hero_frame(params: dict) -> Builder:
    """The X-frame plate headless FreeCAD writes as frame.step and frame.stl around the whole drone (frame_build.py)."""

    def build(directory: Path) -> Output:
        from pai_agent import freecad_run

        mass = freecad_run.build_with_freecad(directory, params)
        step, stl = directory / "frame.step", directory / "frame.stl"
        # frame_build weighs the plate at 1.55 g/cm3, carbon plate.
        body = Body("Frame", stl, step, True, {}, *HERO_FRAME_MESH, 1.55)
        return Output(step, stl, None, [body], {"mass_g": mass})

    return build


def solidcraft(script: dict, stem: str, *, material: str = "PLA") -> Builder:
    """A SolidCraft command script built as solidcraft_part builds it: the material on every body, then the exports."""

    def build(directory: Path) -> Output:
        from pai_agent import solidcraft as engine
        from pai_agent.cad_script import density

        commands = engine.check_script(script)
        made = engine.build(commands, material, density(material), directory, stem, stem)
        step = made.files["step"]
        bodies = [
            Body(row["name"], directory / row["stl"], step, row["closed"], {k: row[k] for k in ("volume_mm3", "mass_g", "bbox_mm")}, *SOLIDCRAFT_MESH, density(material))
            for row in made.bodies
            if row.get("stl")
        ]
        reported = {"volume_mm3": made.volume_mm3, "mass_g": made.mass_g, "bbox_mm": made.bbox_mm}
        # SolidCraft measures on its own triangulation: its volumes sit up to about 0.02 % under the exact solid.
        return Output(step, made.files["stl"], made.files["glb"], bodies, reported, reported_rel=5e-4, notes=list(made.warnings))

    return build
