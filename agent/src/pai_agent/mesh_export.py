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


def stls_to_glb(parts: list[tuple[str, Path, str | None]], glb_path: Path) -> None:
    """Several named STLs into one GLB, one node per part, with an optional hex color each.

    A material named `pai:<hex>` tells the CAD view to keep that color instead of its neutral grey.
    """

    positions = b""
    indices = b""
    views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []
    materials: list[dict] = []
    nodes: list[dict] = []
    for name, path, color in parts:
        vertices = read_stl_vertices(path)
        if len(vertices) < 3:
            continue
        pos = b"".join(struct.pack("<fff", *vertex) for vertex in vertices)
        idx = b"".join(struct.pack("<I", index) for index in range(len(vertices)))
        views.append({"buffer": 0, "byteOffset": len(positions), "byteLength": len(pos), "target": 34962})
        positions += pos
        views.append({"buffer": 0, "byteOffset": len(indices), "byteLength": len(idx), "target": 34963, "_indices": True})
        indices += idx
        xs, ys, zs = zip(*vertices)
        accessors.append(
            {
                "bufferView": len(views) - 2,
                "componentType": 5126,
                "count": len(vertices),
                "type": "VEC3",
                "min": [min(xs), min(ys), min(zs)],
                "max": [max(xs), max(ys), max(zs)],
            }
        )
        accessors.append({"bufferView": len(views) - 1, "componentType": 5125, "count": len(vertices), "type": "SCALAR"})
        primitive = {"attributes": {"POSITION": len(accessors) - 2}, "indices": len(accessors) - 1}
        if color:
            rgb = _hex_rgb(color)
            if rgb is not None:
                materials.append({"name": "pai:" + color, "pbrMetallicRoughness": {"baseColorFactor": [*rgb, 1.0], "roughnessFactor": 0.6}})
                primitive["material"] = len(materials) - 1
        meshes.append({"name": name, "primitives": [primitive]})
        nodes.append({"name": name, "mesh": len(meshes) - 1})
    if not nodes:
        raise ValueError("No part has triangles.")
    # Index views follow all position bytes in the one buffer.
    for view in views:
        if view.pop("_indices", False):
            view["byteOffset"] += len(positions)
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "buffers": [{"byteLength": len(positions) + len(indices)}],
        "bufferViews": views,
        "accessors": accessors,
    }
    if materials:
        document["materials"] = materials
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    binary = positions + indices
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)
    chunks = _chunk(b"JSON", payload) + _chunk(b"BIN\x00", binary)
    glb_path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(chunks)) + chunks)


def _hex_rgb(color: str) -> tuple[float, float, float] | None:
    value = color.strip().lstrip("#")
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None
