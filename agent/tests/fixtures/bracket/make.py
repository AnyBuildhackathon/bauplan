"""Writes the test bracket of the SOMA review (report section 2.12) as binary STL: `python make.py` here.

A base plate 60 x 30 x 4 mm, a wall 4 mm thick and 40 mm high, on top of it a 30 x 30 x 3 mm shelf whose
900 mm2 underside hangs out at 90 degrees, a 0.8 mm rib, and a 6.0 mm pin in a 6.4 mm hole, so the
pin has 0.2 mm all round. CadQuery, tessellated to 0.01 mm.
"""

import struct
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent


def write_stl(path: Path, shape) -> None:
    vertices, triangles = shape.tessellate(0.01, 0.1)
    points = [v.toTuple() for v in vertices]
    out = bytearray(b"AnyBuild test bracket".ljust(80, b" ") + struct.pack("<I", len(triangles)))
    for a, b, c in triangles:
        out += struct.pack("<3f", 0.0, 0.0, 0.0) + struct.pack("<9f", *points[a], *points[b], *points[c]) + b"\0\0"
    path.write_bytes(bytes(out))


base = cq.Workplane("XY").box(60, 30, 4, centered=(True, True, False))
wall = cq.Workplane("XY").box(4, 30, 40, centered=(False, True, False)).translate((-30, 0, 4))
shelf = cq.Workplane("XY").box(30, 30, 3, centered=(False, True, False)).translate((-26, 0, 41))
rib = cq.Workplane("XY").box(0.8, 30, 10, centered=(False, True, False)).translate((10, 0, 4))
hole = cq.Workplane("XY").circle(3.2).extrude(4).translate((20, 0, 0))
bracket = base.union(wall).union(shelf).union(rib).cut(hole)
pin = cq.Workplane("XY").circle(3.0).extrude(12).translate((20, 0, -4))
write_stl(HERE / "bracket.stl", bracket.val())
write_stl(HERE / "pin.stl", pin.val())
