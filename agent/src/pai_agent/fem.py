"""Finite element stress analysis of one printed part on its real shape: gmsh meshes it, CalculiX solves it.

Both binaries ship inside FreeCAD (they are what FreeCAD's FEM workbench runs), so the same
freecadcmd lookup finds them; `PAI_CCX` and `PAI_GMSH` override, and `ccx`/`gmsh` on PATH work too.
The part's STEP (or a closed STL) is meshed into quadratic tetrahedra (C3D10), moved into the
assembly frame with the same rotation and offset the assembly uses, then solved as linear static
for each load case: the clamped region held, the force spread over the nodes of the loaded region.

Printed plastic is not solid plastic. The modulus is the data sheet value times the plastic share
of the section (perimeters solid, the core at the infill), and two strengths judge the result:
the layer-plane strength against the von Mises stress, and the interlayer (Z) strength against the
tension across the layers, which is the stress along the print direction. The safety factor is the
smaller of the two. Peak stresses on the clamped and loaded nodes themselves are singular (a point
load or a perfect clamp has infinite stress in theory), so the reported maximum leaves those nodes out.

Units are millimetres, newtons and MPa throughout.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np

TIMEOUT_S = 150
MAX_NODES = 60000
# gmsh's 10-node tetrahedron numbers its last two edge nodes the other way round from CalculiX.
_GMSH_TO_CCX = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]
AXES = {"x": 0, "y": 1, "z": 2}


class FemUnavailable(RuntimeError):
    pass


class FemFailed(RuntimeError):
    pass


def find_tools() -> tuple[str, str] | None:
    """(gmsh, ccx) executables, or None when either is missing."""

    found = []
    for name, env in (("gmsh", "PAI_GMSH"), ("ccx", "PAI_CCX")):
        override = os.environ.get(env, "").strip()
        if override.lower() == "off":
            return None
        path = override if override and Path(override).is_file() else shutil.which(name)
        if not path:
            from pai_agent.freecad_run import find_freecadcmd

            freecad = find_freecadcmd()
            if freecad:
                sibling = Path(freecad).resolve().parent / name
                path = str(sibling) if sibling.is_file() else None
        if not path:
            return None
        found.append(path)
    return found[0], found[1]


def mesh_size(size_mm: list[float], min_wall_mm: float | None) -> float:
    """Element size: about 30 elements along the longest side, at least two through the thinnest wall."""

    longest = max(size_mm)
    h = longest / 30.0
    if min_wall_mm:
        h = min(h, max(min_wall_mm / 1.6, 0.4))
    return round(min(max(h, 0.4), 8.0), 3)


def _geo(geometry: Path, h: float) -> str:
    head = [
        "Mesh.ElementOrder = 2;",
        "Mesh.SecondOrderLinear = 1;",
        f"Mesh.CharacteristicLengthMax = {h:g};",
        f"Mesh.CharacteristicLengthMin = {h / 5:g};",
        "Mesh.MshFileVersion = 2.2;",
        "Mesh.Optimize = 1;",
    ]
    if geometry.suffix.lower() in {".step", ".stp"}:
        return "\n".join(
            [
                'SetFactory("OpenCASCADE");',
                f'Merge "{geometry.name}";',
                # Touching solids share their faces, so a part made of several bodies meshes as one.
                "solids() = Volume{:};",
                "If (#solids() > 1)",
                "  BooleanFragments{ Volume{solids()}; Delete; }{}",
                "EndIf",
                *head,
            ]
        )
    return "\n".join(
        [
            f'Merge "{geometry.name}";',
            "ClassifySurfaces{Pi/4, 1, 1, Pi};",
            "CreateGeometry;",
            "Surface Loop(1) = Surface{:};",
            "Volume(1) = {1};",
            *head,
        ]
    )


def _read_msh(path: Path) -> tuple[np.ndarray, np.ndarray]:
    lines = path.read_text().splitlines()
    nodes_at = lines.index("$Nodes")
    count = int(lines[nodes_at + 1])
    ids = np.empty(count, dtype=np.int64)
    xyz = np.empty((count, 3))
    for i in range(count):
        parts = lines[nodes_at + 2 + i].split()
        ids[i] = int(parts[0])
        xyz[i] = [float(parts[1]), float(parts[2]), float(parts[3])]
    index = {int(v): i for i, v in enumerate(ids)}
    elements_at = lines.index("$Elements")
    total = int(lines[elements_at + 1])
    tets = []
    for i in range(total):
        parts = lines[elements_at + 2 + i].split()
        if parts[1] != "11":
            continue
        tags = int(parts[2])
        tets.append([index[int(v)] for v in parts[3 + tags : 13 + tags]])
    if not tets:
        raise FemFailed("gmsh made no volume mesh: the shape is not a closed solid.")
    return xyz, np.array(tets, dtype=np.int64)[:, _GMSH_TO_CCX]


def mesh(geometry: Path, work: Path, h: float, gmsh: str) -> tuple[np.ndarray, np.ndarray]:
    """Quadratic tetrahedra of the solid: node coordinates (n, 3) and CalculiX-ordered connectivity (m, 10)."""

    work.mkdir(parents=True, exist_ok=True)
    local = work / ("part" + geometry.suffix.lower())
    shutil.copyfile(geometry, local)
    for _attempt in range(3):
        (work / "mesh.geo").write_text(_geo(local, h), encoding="utf-8")
        done = subprocess.run([gmsh, "mesh.geo", "-3", "-o", "mesh.msh", "-v", "1", "-nt", "2"], cwd=work, capture_output=True, text=True, timeout=TIMEOUT_S)
        if done.returncode != 0 or not (work / "mesh.msh").is_file():
            raise FemFailed("gmsh failed: " + ((done.stderr or done.stdout).strip().splitlines() or ["no output"])[-1][:200])
        nodes, tets = _read_msh(work / "mesh.msh")
        if len(nodes) <= MAX_NODES:
            return nodes, tets
        h *= (len(nodes) / MAX_NODES) ** (1 / 3) * 1.1
    return nodes, tets


def _largest_connected(tets: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """Elements of the connected pieces that touch the `keep` nodes; loose bodies would float free."""

    parent = np.arange(tets.max() + 1)

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for row in tets[:, :4]:
        root = find(int(row[0]))
        for other in row[1:]:
            r = find(int(other))
            if r != root:
                parent[r] = root
    roots = {find(int(n)) for n in keep}
    mask = np.array([find(int(row[0])) in roots for row in tets])
    return tets[mask]


def select(nodes: np.ndarray, region: dict, h: float) -> np.ndarray:
    """Node indices of a region: a face of the bounding box, a box, or the nodes near a point."""

    if "face" in region:
        face = str(region["face"]).lower()
        axis = AXES[face[0]]
        depth = float(region.get("depth_mm") or 0.1)
        values = nodes[:, axis]
        if face.endswith("min"):
            return np.nonzero(values <= values.min() + depth)[0]
        return np.nonzero(values >= values.max() - depth)[0]
    if "box" in region:
        lo, hi = np.array(region["box"][:3], dtype=float), np.array(region["box"][3:], dtype=float)
        return np.nonzero(np.all((nodes >= lo) & (nodes <= hi), axis=1))[0]
    if "near" in region:
        point = np.array(region["near"], dtype=float)
        distance = np.linalg.norm(nodes - point, axis=1)
        radius = float(region.get("radius_mm") or 3 * h)
        chosen = np.nonzero(distance <= radius)[0]
        if len(chosen) < 6:
            # The point sits off the part (a load centred in the air above it): take the closest patch.
            chosen = np.argsort(distance)[: max(6, min(40, len(nodes) // 50))]
        return chosen
    raise ValueError("A region needs face, box or near.")


def _write_inp(path: Path, nodes: np.ndarray, tets: np.ndarray, modulus: float, poisson: float, fixed: np.ndarray, loads: list[tuple[np.ndarray, list[float]]]) -> None:
    out = ["*NODE, NSET=NALL"]
    out += [f"{i + 1}, {x:.6f}, {y:.6f}, {z:.6f}" for i, (x, y, z) in enumerate(nodes)]
    out.append("*ELEMENT, TYPE=C3D10, ELSET=EALL")
    out += [f"{e + 1}, " + ", ".join(str(int(n) + 1) for n in row) for e, row in enumerate(tets)]
    out.append("*NSET, NSET=FIX")
    out += [", ".join(str(int(n) + 1) for n in fixed[i : i + 12]) for i in range(0, len(fixed), 12)]
    out += ["*MATERIAL, NAME=PRINTED", "*ELASTIC", f"{modulus:.4f}, {poisson:.4f}", "*SOLID SECTION, ELSET=EALL, MATERIAL=PRINTED"]
    out += ["*BOUNDARY", "FIX, 1, 3", "*STEP", "*STATIC", "*CLOAD"]
    for region, force in loads:
        share = np.array(force, dtype=float) / max(len(region), 1)
        for n in region:
            for dof in range(3):
                if share[dof]:
                    out.append(f"{int(n) + 1}, {dof + 1}, {share[dof]:.8g}")
    out += ["*NODE FILE", "U", "*EL FILE", "S", "*END STEP"]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _read_frd(path: Path, count: int) -> tuple[np.ndarray, np.ndarray]:
    """Nodal displacement (n, 3) and stress (n, 6: xx yy zz xy yz zx) from the CalculiX result file."""

    disp = np.zeros((count, 3))
    stress = np.zeros((count, 6))
    target = None
    for line in path.read_text(errors="ignore").splitlines():
        if line.startswith(" -4"):
            name = line[3:].split()[0]
            target = disp if name == "DISP" else stress if name == "STRESS" else None
            continue
        if line.startswith(" -3"):
            target = None
            continue
        if target is not None and line.startswith(" -1"):
            node = int(line[3:13]) - 1
            width = target.shape[1]
            values = [float(line[13 + 12 * i : 25 + 12 * i]) for i in range(width)]
            if 0 <= node < count:
                target[node] = values
    return disp, stress


def von_mises(s: np.ndarray) -> np.ndarray:
    xx, yy, zz, xy, yz, zx = (s[:, i] for i in range(6))
    return np.sqrt(0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2) + 3.0 * (xy**2 + yz**2 + zx**2))


def normal_stress(s: np.ndarray, direction: np.ndarray) -> np.ndarray:
    """Stress along a unit direction: n . sigma . n, tension positive."""

    n = direction / max(np.linalg.norm(direction), 1e-12)
    xx, yy, zz, xy, yz, zx = (s[:, i] for i in range(6))
    return xx * n[0] ** 2 + yy * n[1] ** 2 + zz * n[2] ** 2 + 2 * (xy * n[0] * n[1] + yz * n[1] * n[2] + zx * n[2] * n[0])


def solve(nodes: np.ndarray, tets: np.ndarray, props: dict, fixed: np.ndarray, loads: list[tuple[np.ndarray, list[float]]], work: Path, ccx: str) -> tuple[np.ndarray, np.ndarray]:
    """One linear static solve; returns nodal displacement and stress."""

    work.mkdir(parents=True, exist_ok=True)
    for stale in work.glob("job.*"):
        stale.unlink()
    _write_inp(work / "job.inp", nodes, tets, props["modulus_mpa"], props["poisson"], fixed, loads)
    env = {**{k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "LANG"}}, "OMP_NUM_THREADS": "2", "CCX_NPROC_EQUATION_SOLVER": "2"}
    done = subprocess.run([ccx, "-i", "job"], cwd=work, capture_output=True, text=True, timeout=TIMEOUT_S, env=env)
    frd = work / "job.frd"
    if done.returncode != 0 or not frd.is_file() or frd.stat().st_size < 200:
        tail = [line for line in (done.stdout + done.stderr).splitlines() if "ERROR" in line.upper()] or (done.stdout + done.stderr).strip().splitlines() or ["no output"]
        raise FemFailed("CalculiX failed: " + tail[-1].strip()[:200])
    return _read_frd(frd, len(nodes))


def surface_triangles(tets: np.ndarray) -> np.ndarray:
    """Outer faces of the tetrahedra (corner nodes), outward wound."""

    corners = tets[:, :4]
    faces = np.concatenate([corners[:, [0, 2, 1]], corners[:, [0, 1, 3]], corners[:, [1, 2, 3]], corners[:, [0, 3, 2]]])
    keys = np.sort(faces, axis=1)
    _, first, counts = np.unique(keys, axis=0, return_index=True, return_counts=True)
    return faces[first[counts == 1]]


def colour_map(value: np.ndarray) -> np.ndarray:
    """0 (no stress) to 1 (at the allowable stress) as blue, cyan, green, yellow, red; above 1 stays red."""

    stops = np.array([[0.16, 0.33, 0.85], [0.10, 0.74, 0.85], [0.18, 0.80, 0.44], [0.98, 0.80, 0.18], [0.93, 0.20, 0.20]])
    t = np.clip(value, 0.0, 1.0) * (len(stops) - 1)
    i = np.minimum(t.astype(int), len(stops) - 2)
    f = (t - i)[:, None]
    return stops[i] * (1 - f) + stops[i + 1] * f


def write_glb(path: Path, nodes: np.ndarray, triangles: np.ndarray, colours: np.ndarray, name: str) -> None:
    """A vertex-coloured GLB of the stressed surface (flat-shaded: three vertices per triangle)."""

    positions = nodes[triangles].reshape(-1, 3).astype(np.float32)
    rgb = colours[triangles].reshape(-1, 3).astype(np.float32)
    a, b, c = positions[0::3], positions[1::3], positions[2::3]
    normal = np.cross(b - a, c - a)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    normals = np.repeat(normal, 3, axis=0).astype(np.float32)
    rgba = np.concatenate([rgb, np.ones((len(rgb), 1), dtype=np.float32)], axis=1)
    blobs = [positions.tobytes(), normals.tobytes(), rgba.tobytes()]
    offsets = np.cumsum([0] + [len(b) for b in blobs]).tolist()
    count = len(positions)
    gltf = {
        "asset": {"version": "2.0", "generator": "AnyBuild FEM"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2}, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0, "roughnessFactor": 0.7}, "doubleSided": True}],
        "buffers": [{"byteLength": offsets[-1]}],
        "bufferViews": [{"buffer": 0, "byteOffset": offsets[i], "byteLength": len(blobs[i]), "target": 34962} for i in range(3)],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3", "min": positions.min(axis=0).tolist(), "max": positions.max(axis=0).tolist()},
            {"bufferView": 1, "componentType": 5126, "count": count, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": count, "type": "VEC4"},
        ],
    }
    body = b"".join(blobs)
    body += b"\x00" * (-len(body) % 4)
    header = json.dumps(gltf, separators=(",", ":")).encode()
    header += b" " * (-len(header) % 4)
    chunks = struct.pack("<I4s", len(header), b"JSON") + header + struct.pack("<I4s", len(body), b"BIN\x00") + body
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)


def analyse(
    geometry: Path,
    transform: tuple[list[list[float]], list[float]] | None,
    props: dict,
    fixed_region: dict,
    cases: list[dict],
    build_direction: list[float],
    work: Path,
    h: float,
    glb_path: Path | None = None,
    name: str = "part",
) -> dict:
    """Meshes the part once, solves every load case, and judges each against the printed strengths.

    transform is (rotation, offset) from the part's own frame into the assembly frame; regions and
    forces are in the assembly frame. Each case: {name, region, force_n: [fx, fy, fz]}, or {name, loads: [{region, force_n}, ...]}
    for several forces at once (four motors pulling).
    Returns per-case results, the governing case, and writes the stress-coloured GLB of that case.
    """

    tools = find_tools()
    if tools is None:
        raise FemUnavailable("gmsh and CalculiX (ccx) are missing: FreeCAD's FEM tools are not on this machine.")
    gmsh, ccx = tools
    nodes, tets = mesh(geometry, work, h, gmsh)
    if transform is not None:
        matrix, offset = np.array(transform[0], dtype=float), np.array(transform[1], dtype=float)
        nodes = nodes @ matrix.T + offset
    fixed = select(nodes, fixed_region, h)
    if len(fixed) < 3:
        raise ValueError("The clamped region holds fewer than 3 mesh nodes; put it on the part.")
    tets = _largest_connected(tets, fixed)
    used = np.unique(tets)
    remap = -np.ones(len(nodes), dtype=np.int64)
    remap[used] = np.arange(len(used))
    nodes, tets = nodes[used], remap[tets]
    fixed = select(nodes, fixed_region, h)
    direction = np.array(build_direction, dtype=float)
    results = []
    worst = None
    for index, case in enumerate(cases):
        loads = []
        for load in case.get("loads") or [{"region": case["region"], "force_n": case["force_n"]}]:
            region = np.setdiff1d(select(nodes, load["region"], h), fixed)
            if len(region) == 0:
                raise ValueError(f"Load case {case.get('name')}: the loaded region is inside the clamp.")
            loads.append((region, [float(v) for v in load["force_n"]]))
        region = np.unique(np.concatenate([r for r, _f in loads]))
        total = np.sum([f for _r, f in loads], axis=0)
        disp, stress = solve(nodes, tets, props, fixed, loads, work / f"case{index}", ccx)
        vm = von_mises(stress)
        across = np.maximum(normal_stress(stress, direction), 0.0)
        away = np.ones(len(nodes), dtype=bool)
        away[fixed] = False
        away[region] = False
        vm_max = float(vm[away].max()) if away.any() else float(vm.max())
        across_max = float(across[away].max()) if away.any() else float(across.max())
        sf_plane = props["strength_mpa"] / vm_max if vm_max > 0 else 99.0
        sf_layers = props["z_strength_mpa"] / across_max if across_max > 0 else 99.0
        hot = int(np.argmax(np.where(away, vm, -1.0)))
        row = {
            "name": case.get("name") or f"case {index + 1}",
            "force_n": [round(float(v), 2) for v in total],
            "loaded_nodes": int(len(region)),
            "max_von_mises_mpa": round(vm_max, 2),
            "max_across_layers_mpa": round(across_max, 2),
            "max_deflection_mm": round(float(np.linalg.norm(disp, axis=1).max()), 3),
            "safety": round(min(sf_plane, sf_layers, 99.0), 2),
            "safety_in_plane": round(min(sf_plane, 99.0), 2),
            "safety_across_layers": round(min(sf_layers, 99.0), 2),
            "governs": "layers" if sf_layers < sf_plane else "in-plane",
            "hot_spot_mm": [round(float(v), 1) for v in nodes[hot]],
        }
        results.append(row)
        if worst is None or row["safety"] < worst[0]["safety"]:
            worst = (row, vm, region)
    assert worst is not None
    row, vm, region = worst
    if glb_path is not None:
        triangles = surface_triangles(tets)
        allowable = props["strength_mpa"]
        write_glb(glb_path, nodes, triangles, colour_map(vm / max(allowable, 1e-9)), name)
    return {
        "nodes": int(len(nodes)),
        "elements": int(len(tets)),
        "element_size_mm": h,
        "fixed_nodes": int(len(fixed)),
        "cases": results,
        "governing": row["name"],
        "safety": row["safety"],
        "max_von_mises_mpa": row["max_von_mises_mpa"],
        "max_deflection_mm": max(r["max_deflection_mm"] for r in results),
        "solver": "CalculiX " + Path(ccx).name + ", gmsh C3D10",
        "bbox_mm": [round(float(v), 2) for v in [*nodes.min(axis=0), *nodes.max(axis=0)]],
        "scale_mpa": round(props["strength_mpa"], 2),
        "build_direction": [round(float(v), 3) for v in direction / max(np.linalg.norm(direction), 1e-12)],
    }
