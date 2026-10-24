"""STL to GLB, and a tiny PNG writer for the recorded render stand-in."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path


def read_stl_vertices(path: Path) -> list[tuple[float, float, float]]:
    data = path.read_bytes()
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if count > 0 and len(data) >= 84 + count * 50:
            vertices = []
            offset = 84
            for _ in range(count):
                numbers = struct.unpack_from("<12f", data, offset)
                vertices.extend(
                    (
                        (numbers[3], numbers[4], numbers[5]),
                        (numbers[6], numbers[7], numbers[8]),
                        (numbers[9], numbers[10], numbers[11]),
                    )
                )
                offset += 50
            return vertices
    return _ascii_vertices(data.decode("utf-8", errors="ignore"))


def _ascii_vertices(text: str) -> list[tuple[float, float, float]]:
    vertices = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "vertex":
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
    return vertices


def stl_to_glb(stl_path: Path, glb_path: Path) -> None:
    vertices = read_stl_vertices(stl_path)
    if len(vertices) < 3:
        raise ValueError("STL ohne Dreiecke: " + str(stl_path))
    positions = b"".join(struct.pack("<fff", *vertex) for vertex in vertices)
    indices = b"".join(struct.pack("<I", index) for index in range(len(vertices)))
    if len(positions) % 4:
        positions += b"\x00" * (4 - len(positions) % 4)
    xs = [vertex[0] for vertex in vertices]
    ys = [vertex[1] for vertex in vertices]
    zs = [vertex[2] for vertex in vertices]
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(positions) + len(indices)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions), "target": 34962},
            {
                "buffer": 0,
                "byteOffset": len(positions),
                "byteLength": len(indices),
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(vertices),
                "type": "VEC3",
                "min": [min(xs), min(ys), min(zs)],
                "max": [max(xs), max(ys), max(zs)],
            },
            {
                "bufferView": 1,
                "componentType": 5125,
                "count": len(vertices),
                "type": "SCALAR",
            },
        ],
    }
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    binary = positions + indices
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)
    chunks = _chunk(b"JSON", payload) + _chunk(b"BIN\x00", binary)
    glb = b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks
    glb_path.write_bytes(glb)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + tag + data


def write_solid_png(path: Path, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)
