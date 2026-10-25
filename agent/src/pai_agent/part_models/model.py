"""A part model under construction: named pieces with finishes, written as GLB and STEP."""

from __future__ import annotations

from pathlib import Path

import cadquery as cq

from .glb import Finish, Mesh, write_glb
from .shapes import shape_of


class Model:
    """Named pieces of one part. Feature pieces (holes, blades, pins) carry names the checks measure."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.pieces: list[tuple[str, cq.Shape, Finish]] = []
        self.meshes: dict[int, Mesh] = {}

    def add(self, name: str, work, finish: Finish, mesh: Mesh | None = None) -> None:
        """A piece; `mesh` replaces the shape's own tessellation in the GLB (the STEP keeps the shape)."""

        if work is None:
            return
        self.pieces.append((name, shape_of(work), finish))
        if mesh is not None:
            self.meshes[len(self.pieces) - 1] = mesh

    def names(self) -> list[str]:
        return [name for name, _, _ in self.pieces]

    def bbox(self, prefixes: tuple[str, ...] | None = None) -> list[float]:
        shapes = [shape for name, shape, _ in self.pieces if prefixes is None or name.startswith(prefixes)]
        box = cq.Compound.makeCompound(shapes).BoundingBox()
        return [round(box.xlen, 3), round(box.ylen, 3), round(box.zlen, 3)]

    def rest_on_floor(self) -> None:
        """Move the part up or down so its lowest point is at z = 0 (leads and terminals included)."""

        low = cq.Compound.makeCompound([shape for _, shape, _ in self.pieces]).BoundingBox().zmin
        if abs(low) < 1e-6:
            return
        shift = cq.Vector(0, 0, -low)
        self.pieces = [(name, shape.translate(shift), fin) for name, shape, fin in self.pieces]
        for index, mesh in self.meshes.items():
            mesh.positions = [(x, y, z - low) for x, y, z in mesh.positions]

    def write(self, glb_path: Path, step_path: Path | None = None, tolerance: float | None = None) -> dict:
        size = max(self.bbox())
        # About 0.4 % of the part's size, never finer than 10 microns: smooth at any zoom, small files.
        tol = tolerance if tolerance is not None else max(0.01, min(0.15, size * 0.004))
        pieces = [(name, self.meshes.get(i, shape), fin) for i, (name, shape, fin) in enumerate(self.pieces)]
        info = write_glb(pieces, glb_path, tol)
        if step_path is not None:
            assembly = cq.Assembly(name=self.name)
            for index, (name, shape, finish) in enumerate(self.pieces):
                r, g, b = (int(finish.color.lstrip("#")[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
                assembly.add(shape, name=f"{name}_{index}", color=cq.Color(r, g, b, finish.alpha))
            step_path.parent.mkdir(parents=True, exist_ok=True)
            assembly.export(str(step_path))
            info["step_bytes"] = step_path.stat().st_size
        return info
