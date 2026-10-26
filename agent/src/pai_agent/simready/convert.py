"""Turns a SimReady package into what AnyBuild runs: an MJCF body for MuJoCo and a GLB for the 3D view.

Reading (pxr): the stage opens with SimReady's MuJoCo physics variant selected, and every mesh
is baked into the asset frame: Z up, metres, the origin where SimReady put it (under the object
for most props), whatever the file's own units and up axis. The collision meshes are the ones
with UsdPhysics' CollisionAPI, grouped by the physics material USD binds to them (UsdShade,
physics purpose); a group's dynamic friction becomes MuJoCo's sliding friction, the lower of the
two coefficients, so a grasp that holds in MuJoCo is not held by friction the object lacks.
Mass, centre of mass and inertia follow UsdPhysics' precedence: the rigid body's MassAPI, else
the sum of its colliders' MassAPI values moved to one centre of mass. SimReady computed those
from density, volume and a fill ratio, so the mass is always marked as an estimate. Grasp
points (`Grasp_Point_*`) become sites.

Collision: MuJoCo collides a mesh as its convex hull. That is right for a banana and wrong for
a pan: the hull is a lid over the cavity, and a banana dropped into the pan lies on that lid
30 mm up. `auto` measures the cavity first: the object's top surface on a grid, flooded from
above and drained over the edges (priority flood); water that stays is a cavity. A cavity at
least CAVITY_MM deep holding at least CAVITY_SHARE of the object's box makes it a container,
and each collision group is split into convex parts by CoACD (in its own process, with a time
limit and a fixed seed); otherwise each collision mesh becomes its convex hull. `hull` and
`decompose` force either. A decomposition that fails or runs out of time falls back to the
hulls with a warning.

CoACD and Blender run one at a time in a backend (Blender on two threads), so a second object
waits instead of competing for the machine. Outputs are cached under
<cache>/<revision>/converted/<id>/<key>/, the key hashing the package content and this module's
code; PAI_CACHE=0 converts again.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from pai_agent.simready import AUTHOR, LICENSE_NAME, LICENSE_URL, asset_url, source_tag
from pai_agent.simready.fetch import Package, SimReadyError, cache_root, fetch, revision_dir

COLLISION_MODES = ("auto", "hull", "decompose")
# A container holds water this deep, over at least this share of its bounding box.
CAVITY_MM = 5.0
CAVITY_SHARE = 0.10
# CoACD: concavity threshold (lower is finer and slower), most parts per collision group, fixed seed.
COACD_THRESHOLD = 0.05
COACD_MAX_PARTS = 48
COACD_SEED = 0
# MuJoCo's own torsional and rolling friction, the values SimReady's Newton variant also carries.
TORSIONAL, ROLLING = 0.005, 0.0001
DEFAULT_FRICTION = 1.0
_GRID = 96
_CODE = (Path(__file__), Path(__file__).with_name("decompose.py"))
_BLENDER_SCRIPT = Path(__file__).with_name("blender_glb.py")
# Y up to Z up, for a stage authored Y up: (x, y, z) becomes (x, -z, y).
_Y_TO_Z = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
# One CoACD or Blender run at a time in this backend, and Blender on two threads: the machine stays usable.
_HEAVY = threading.Lock()
BLENDER_THREADS = 2
# The largest texture side a GLB keeps: enough for the 3D view, small enough for a browser to load.
GLB_TEXTURE_PX = 1024


class ConvertError(SimReadyError):
    """The USD could not be turned into an MJCF body or a GLB."""


def decompose_timeout() -> float:
    try:
        return max(5.0, float(os.environ.get("PAI_SIMREADY_DECOMPOSE_S", "") or 180.0))
    except ValueError:
        return 180.0


# ---------------------------------------------------------------- reading the USD


@dataclass
class Mesh:
    """Triangles in the asset frame (metres, Z up)."""

    vertices: np.ndarray
    faces: np.ndarray
    source: str = ""


@dataclass
class Group:
    """The collision meshes bound to one physics material."""

    material: str
    friction: float
    static_friction: float | None
    restitution: float | None
    density: float | None
    meshes: list[Mesh] = field(default_factory=list)


@dataclass
class Visual:
    """The faces drawn with one render material, and its colour: the diffuse texture where those faces sample it, area-weighted, sRGB."""

    material: str
    rgba: tuple
    mesh: Mesh


@dataclass
class Asset:
    asset_id: str
    author: str
    wikidata_class: str | None
    qcode: str | None
    documentation: str
    bbox_min: np.ndarray
    bbox_max: np.ndarray
    mass_kg: float
    com: np.ndarray
    inertia: np.ndarray
    mass_source: str
    groups: list[Group]
    visuals: list[Visual]
    grasps: list[dict]
    maxhullvert: int | None
    bodies: int
    warnings: list[str]

    @property
    def size_mm(self) -> list[float]:
        return [round(float(v) * 1000.0, 1) for v in self.bbox_max - self.bbox_min]


def read_asset(package: Package) -> Asset:
    """Everything a conversion needs from the composed USD stage, in the asset frame."""

    from pxr import Usd, UsdGeom, UsdPhysics

    stage = Usd.Stage.Open(str(package.root_usd), Usd.Stage.LoadAll)
    if stage is None:
        raise ConvertError(f"{package.asset_id}: the root USD does not open.")
    root = stage.GetDefaultPrim() or next(iter(stage.GetPseudoRoot().GetChildren()), None)
    if root is None:
        raise ConvertError(f"{package.asset_id}: the USD has no prims.")
    variants = root.GetVariantSets()
    names = variants.GetNames()
    if "MuJoCo" in names:
        # SimReady ships one physics variant per simulator; MuJoCo's carries the mjc: collision settings.
        for name in names:
            if set(variants.GetVariantSet(name).GetVariantNames()) >= {"Enabled", "Disabled"}:
                variants.GetVariantSet(name).SetVariantSelection("Enabled" if name == "MuJoCo" else "Disabled")

    meters = float(UsdGeom.GetStageMetersPerUnit(stage) or 1.0)
    kilograms = float(UsdPhysics.GetStageKilogramsPerUnit(stage) or 1.0)
    up = _Y_TO_Z if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y else np.eye(3)
    cache = UsdGeom.XformCache()

    def frame(prim) -> tuple[np.ndarray, np.ndarray]:
        """(linear, translation) taking a prim's local points (row vectors) to the asset frame in metres."""

        matrix = np.array(cache.GetLocalToWorldTransform(prim), dtype=float)
        return matrix[:3, :3] @ up.T * meters, matrix[3, :3] @ up.T * meters

    warnings: list[str] = []
    groups: dict[str, Group] = {}
    visuals: dict[str, list[Mesh]] = {}
    # Per render material: the area-weighted sum of its colour over its faces, and that area.
    paint: dict[str, list] = {}
    textures: dict[str, np.ndarray | None] = {}
    colliders = []
    grasps: dict[str, dict] = {}
    maxhullvert = None
    bodies = 0
    low, high = np.full(3, np.inf), np.full(3, -np.inf)

    for prim in Usd.PrimRange(root, Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)):
        if prim.HasAPI(UsdPhysics.RigidBodyAPI):
            bodies += 1
        if prim.GetName().startswith("Grasp_Point"):
            linear, offset = frame(prim)
            key = prim.GetName()[len("Grasp_Point"):].strip("_") or str(len(grasps) + 1)
            grasps[key] = {"id": key, "pos": offset.tolist()}
            continue
        if not prim.IsA(UsdGeom.Mesh):
            continue
        imageable = UsdGeom.Imageable(prim)
        purpose = imageable.ComputePurpose()
        visible = imageable.ComputeVisibility() != UsdGeom.Tokens.invisible
        mesh = UsdGeom.Mesh(prim)
        points = mesh.GetPointsAttr().Get()
        counts = mesh.GetFaceVertexCountsAttr().Get()
        indices = mesh.GetFaceVertexIndicesAttr().Get()
        if not points or not counts or indices is None:
            continue
        linear, offset = frame(prim)
        vertices = np.asarray(points, dtype=float) @ linear + offset
        triangles, face_of = _triangulate(np.asarray(counts, dtype=np.int64), np.asarray(indices, dtype=np.int64), mesh.GetOrientationAttr().Get() == UsdGeom.Tokens.leftHanded)
        if np.linalg.det(linear) < 0:
            triangles = triangles[:, ::-1]
        if not len(triangles):
            continue
        path = str(prim.GetPath())
        drawn = visible and purpose in (UsdGeom.Tokens.default_, UsdGeom.Tokens.render)
        if drawn:
            low, high = np.minimum(low, vertices.min(axis=0)), np.maximum(high, vertices.max(axis=0))
            uvs = _polygon_uvs(prim, np.asarray(counts, dtype=np.int64), np.asarray(indices, dtype=np.int64))
            for material, chosen in _faces_by_material(prim, mesh, face_of, purpose=""):
                faces = triangles[chosen]
                visuals.setdefault(material, []).append(Mesh(vertices, faces, path))
                corners = vertices[faces]
                area = 0.5 * np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1)
                colour = _face_colours(stage, material, None if uvs is None else uvs[face_of[chosen]], textures)
                total = paint.setdefault(material, [np.zeros(3), 0.0])
                total[0] += (colour * area[:, None]).sum(axis=0)
                total[1] += float(area.sum())
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            enabled = UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get()
            if enabled is False:
                continue
            hull_limit = prim.GetAttribute("mjc:maxhullvert").Get() if prim.HasAttribute("mjc:maxhullvert") else None
            if hull_limit is not None and int(hull_limit) > 3:
                maxhullvert = max(maxhullvert or 0, int(hull_limit))
            densest = (0, None)
            for material, chosen in _faces_by_material(prim, mesh, face_of, purpose="physics"):
                group = groups.get(material)
                if group is None:
                    group = groups[material] = _group(stage, material, warnings)
                group.meshes.append(Mesh(vertices, triangles[chosen], path))
                densest = max(densest, (int(chosen.sum()), group.density), key=lambda pair: pair[0])
            colliders.append((prim, Mesh(vertices, triangles, path), densest[1]))

    if not np.all(np.isfinite(low)):
        raise ConvertError(f"{package.asset_id}: no visible mesh to convert.")
    if not groups:
        # No CollisionAPI anywhere: the drawn meshes collide, with MuJoCo's default friction.
        warnings.append("No collision meshes in the USD; the visible meshes collide, with MuJoCo's default friction 1.")
        group = groups[""] = Group("", DEFAULT_FRICTION, None, None, None)
        for meshes in visuals.values():
            group.meshes.extend(meshes)
    if bodies > 1:
        warnings.append(f"{bodies} rigid bodies merged into one; their joints are not converted.")

    if not colliders:
        # The drawn meshes stand in as colliders, for the mass as well.
        colliders = [(None, mesh, None) for meshes in visuals.values() for mesh in meshes]
    mass, com, inertia, source = _mass_properties(root, colliders, up, meters, kilograms)
    inertia, balanced = valid_inertia(inertia)
    if balanced:
        warnings.append("The inertia was adjusted to be physically valid (each principal moment at most the sum of the other two).")

    md = dict(stage.GetRootLayer().customLayerData.get("SimReady_Metadata") or {})
    cls, qcode = _semantics(root)
    documentation = root.GetAttribute("omni:simready:documentation").Get() if root.HasAttribute("omni:simready:documentation") else ""
    return Asset(
        asset_id=package.asset_id,
        author=str(md.get("author") or AUTHOR),
        wikidata_class=cls,
        qcode=qcode or (str(md.get("qcode")) if md.get("qcode") else None),
        documentation=str(documentation or ""),
        bbox_min=low,
        bbox_max=high,
        mass_kg=float(mass),
        com=np.asarray(com, dtype=float),
        inertia=np.asarray(inertia, dtype=float),
        mass_source=source,
        groups=list(groups.values()),
        visuals=[Visual(material, _rgba(paint.get(material)), _merge(meshes)) for material, meshes in visuals.items()],
        grasps=[grasps[key] for key in sorted(grasps)],
        maxhullvert=maxhullvert,
        bodies=max(bodies, 1),
        warnings=warnings,
    )


def _triangulate(counts: np.ndarray, indices: np.ndarray, left_handed: bool) -> tuple[np.ndarray, np.ndarray]:
    """Fan triangles of every polygon, and the polygon each triangle came from."""

    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    valid = counts >= 3
    triangles, origin = [], []
    for size in np.unique(counts[valid]):
        faces = np.nonzero(counts == size)[0]
        base = starts[faces]
        for k in range(1, int(size) - 1):
            triangles.append(np.stack([indices[base], indices[base + k], indices[base + k + 1]], axis=1))
            origin.append(faces)
    if not triangles:
        return np.zeros((0, 3), dtype=np.int64), np.zeros(0, dtype=np.int64)
    tris, face_of = np.concatenate(triangles), np.concatenate(origin)
    order = np.argsort(face_of, kind="stable")
    tris, face_of = tris[order], face_of[order]
    if left_handed:
        tris = tris[:, ::-1]
    return tris, face_of


def _faces_by_material(prim, mesh, face_of: np.ndarray, purpose: str):
    """(material path, triangle mask) per material: GeomSubsets bound to their own material, the rest to the mesh's."""

    from pxr import UsdGeom, UsdShade

    which = purpose or UsdShade.Tokens.allPurpose
    remaining = np.ones(len(face_of), dtype=bool)
    out: dict[str, np.ndarray] = {}
    for subset in UsdGeom.Subset.GetAllGeomSubsets(mesh):
        if subset.GetFamilyNameAttr().Get() != "materialBind" or subset.GetElementTypeAttr().Get() != UsdGeom.Tokens.face:
            continue
        direct = UsdShade.MaterialBindingAPI(subset.GetPrim()).GetDirectBinding(materialPurpose=which).GetMaterial()
        if not direct:
            continue
        chosen = np.isin(face_of, np.asarray(subset.GetIndicesAttr().Get() or [], dtype=np.int64)) & remaining
        if chosen.any():
            key = str(direct.GetPath())
            out[key] = out[key] | chosen if key in out else chosen
            remaining &= ~chosen
    if remaining.any():
        material, _ = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial(materialPurpose=which)
        key = str(material.GetPath()) if material else ""
        out[key] = out[key] | remaining if key in out else remaining
    return list(out.items())


def _polygon_uvs(prim, counts: np.ndarray, indices: np.ndarray) -> np.ndarray | None:
    """The texture coordinate at the centre of every polygon, or None without texture coordinates."""

    from pxr import Sdf, UsdGeom

    primvars = UsdGeom.PrimvarsAPI(prim)
    primvar = primvars.GetPrimvar("st")
    if not primvar or not primvar.HasValue():
        primvar = next((pv for pv in primvars.GetPrimvarsWithValues() if pv.GetTypeName().role == Sdf.ValueRoleNames.TextureCoordinate), None)
    if primvar is None:
        return None
    values = primvar.ComputeFlattened()
    if values is None or not len(values):
        return None
    values = np.asarray(values, dtype=float)[:, :2]
    interpolation = primvar.GetInterpolation()
    if interpolation == UsdGeom.Tokens.uniform and len(values) == len(counts):
        return values
    if interpolation == UsdGeom.Tokens.constant:
        return np.repeat(values[:1], len(counts), axis=0)
    if interpolation == UsdGeom.Tokens.faceVarying and len(values) == len(indices):
        corner = values
    elif interpolation in (UsdGeom.Tokens.vertex, UsdGeom.Tokens.varying) and indices.max(initial=-1) < len(values):
        corner = values[indices]
    else:
        return None
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    return np.add.reduceat(corner, starts, axis=0) / np.maximum(counts, 1)[:, None]


def _face_colours(stage, material_path: str, uvs: np.ndarray | None, textures: dict) -> np.ndarray:
    """Each face's base colour: its diffuse texture at the face's texture coordinate, else the diffuse constant, else grey."""

    texture, constant = _diffuse(stage, material_path)
    count = 1 if uvs is None else len(uvs)
    if texture and uvs is not None:
        if texture not in textures:
            textures[texture] = _load_texture(texture)
        image = textures[texture]
        if image is not None:
            height, width = image.shape[:2]
            column = np.clip((np.mod(uvs[:, 0], 1.0) * width).astype(np.int64), 0, width - 1)
            row = np.clip(((1.0 - np.mod(uvs[:, 1], 1.0)) * height).astype(np.int64), 0, height - 1)
            return image[row, column]
    colour = np.asarray(constant if constant is not None else (0.6, 0.6, 0.6), dtype=float)
    return np.repeat(colour[None, :], count if uvs is not None else 1, axis=0)


def _diffuse(stage, material_path: str) -> tuple[str | None, tuple | None]:
    """(texture file, constant colour) of a material's diffuse input; either may be None."""

    from pxr import Sdf, UsdShade

    prim = stage.GetPrimAtPath(material_path) if material_path else None
    if prim is None or not prim.IsValid():
        return None, None
    shader, _, _ = UsdShade.Material(prim).ComputeSurfaceSource()
    if not shader:
        return None, None
    diffuse = shader.GetInput("diffuseColor") or shader.GetInput("base_color")
    if not diffuse:
        return None, None
    sources = diffuse.GetConnectedSources()[0] if diffuse.HasConnectedSource() else []
    for info in sources:
        file_input = UsdShade.Shader(info.source.GetPrim()).GetInput("file")
        asset = file_input.Get() if file_input else None
        resolved = asset.resolvedPath if isinstance(asset, Sdf.AssetPath) else ""
        if resolved and Path(resolved).is_file():
            return resolved, None
    value = diffuse.Get()
    return None, (tuple(float(v) for v in value)[:3] if value is not None else None)


def _load_texture(path: str) -> np.ndarray | None:
    try:
        from PIL import Image

        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((256, 256))
            return np.asarray(image, dtype=float) / 255.0
    except OSError:
        return None


def _rgba(total) -> tuple:
    if not total or total[1] <= 0:
        return (0.6, 0.6, 0.6, 1.0)
    return tuple(round(float(v), 3) for v in total[0] / total[1]) + (1.0,)


def _group(stage, material_path: str, warnings: list[str]) -> Group:
    from pxr import UsdPhysics

    prim = stage.GetPrimAtPath(material_path) if material_path else None
    if prim is None or not prim.IsValid() or not prim.HasAPI(UsdPhysics.MaterialAPI):
        warnings.append("A collision mesh has no physics material; MuJoCo's default friction 1 applies to it.")
        return Group(material_path, DEFAULT_FRICTION, None, None, None)
    api = UsdPhysics.MaterialAPI(prim)

    def value(attr):
        got = attr.Get() if attr and attr.HasAuthoredValue() else None
        return float(got) if got is not None else None

    dynamic, static = value(api.GetDynamicFrictionAttr()), value(api.GetStaticFrictionAttr())
    friction = dynamic if dynamic is not None else static
    return Group(
        material_path,
        float(friction) if friction is not None else DEFAULT_FRICTION,
        static,
        value(api.GetRestitutionAttr()),
        value(api.GetDensityAttr()),
    )


def _semantics(root) -> tuple[str | None, str | None]:
    def first(*names):
        for name in names:
            attr = root.GetAttribute(name)
            if attr and attr.HasValue():
                value = attr.Get()
                if value is not None and len(value):
                    return str(value if isinstance(value, str) else value[0]).strip() or None
        return None

    return (
        first("semantics:labels:wikidata_class", "semantic:wikidata_class:params:semanticData"),
        first("semantics:labels:wikidata_qcode", "semantic:wikidata_qcode:params:semanticData"),
    )


def _mass_properties(root, colliders, up: np.ndarray, meters: float, kilograms: float):
    """(mass kg, centre of mass, 3 x 3 inertia about it, source) in the asset frame, after UsdPhysics' precedence.

    Per rigid body: its own MassAPI wins; else its colliders' MassAPI values add up; values the
    file leaves unset (UsdPhysics' sentinels) come from the colliders' convex hulls at their
    material's density, scaled to the mass the file does give. Several rigid bodies, and colliders
    outside any body, add up into one: each tensor turned into the asset frame and moved to the
    common centre of mass.
    """

    from pxr import Usd, UsdGeom, UsdPhysics

    cache = UsdGeom.XformCache()

    def explicit(prim):
        """(mass, centre, tensor) from a MassAPI in the asset frame; centre or tensor None where unset."""

        if prim is None or not prim.HasAPI(UsdPhysics.MassAPI):
            return None
        api = UsdPhysics.MassAPI(prim)
        mass = api.GetMassAttr().Get()
        if not mass or mass <= 0:
            return None
        matrix = np.array(cache.GetLocalToWorldTransform(prim), dtype=float)
        linear, offset = matrix[:3, :3] @ up.T * meters, matrix[3, :3] @ up.T * meters
        com = api.GetCenterOfMassAttr().Get()
        centre = None
        if com is not None and all(math.isfinite(v) for v in com):
            centre = np.asarray(com, dtype=float) @ linear + offset
        diagonal = api.GetDiagonalInertiaAttr().Get()
        tensor = None
        if diagonal is not None and any(diagonal):
            axes = api.GetPrincipalAxesAttr().Get()
            principal = _quat_matrix(axes.GetReal(), *axes.GetImaginary()) if axes is not None and axes.GetLength() > 1e-6 else np.eye(3)
            # Column-vector rotation from the prim's local axes to the asset frame (a uniform scale is taken out).
            rotation = _orthonormal(linear).T @ principal
            tensor = rotation @ np.diag(np.asarray(diagonal, dtype=float)) @ rotation.T * kilograms * meters * meters
        return float(mass) * kilograms, centre, tensor

    def complete(values) -> bool:
        return values is not None and values[1] is not None and values[2] is not None

    bodies = {str(p.GetPath()): p for p in Usd.PrimRange(root, Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)) if p.HasAPI(UsdPhysics.RigidBodyAPI)}

    def owner(prim) -> str:
        while prim is not None and prim.IsValid():
            if str(prim.GetPath()) in bodies:
                return str(prim.GetPath())
            prim = prim.GetParent()
        return ""

    members: dict[str, list] = {}
    for collider in colliders:
        members.setdefault(owner(collider[0]), []).append(collider)
    parts, sources = [], set()
    for key in [*bodies, *([""] if "" in members else [])]:
        own = explicit(bodies[key]) if key else None
        if complete(own):
            parts.append(own)
            sources.add("body")
            continue
        mine = members.get(key, [])
        values = [explicit(prim) for prim, _, _ in mine]
        if mine and all(complete(v) for v in values):
            parts.extend(values)
            sources.add("colliders")
            continue
        hull = _mass_from_hulls([(mesh, density) for _, mesh, density in mine])
        if hull is None:
            continue
        given = own[0] if own is not None else (sum(v[0] for v in values if v is not None) or None)
        if given:
            # The file states the mass but not how it is spread: the hulls' shape at that mass.
            hull = (given, hull[1], hull[2] * (given / hull[0]))
            sources.add("hull-shape")
        else:
            sources.add("hull")
        parts.append(hull)
    if not parts:
        raise ConvertError("The USD has no mass and its collision meshes have no volume.")
    mass = sum(m for m, _, _ in parts)
    centre = sum(m * c for m, c, _ in parts) / mass
    tensor = np.zeros((3, 3))
    for m, c, t in parts:
        d = c - centre
        tensor += t + m * (float(d @ d) * np.eye(3) - np.outer(d, d))
    if sources == {"body"}:
        source = "SimReady estimate (the rigid body's mass properties)" if len(parts) == 1 else f"SimReady estimate (the mass properties of its {len(parts)} rigid bodies, added up)"
    elif sources <= {"body", "colliders"}:
        source = "SimReady estimate (material density, volume and fill ratio)"
    elif "hull" in sources and not sources & {"body", "colliders", "hull-shape"}:
        source = "computed by AnyBuild from the collision hulls at the material density (no mass in the USD)"
    else:
        source = "SimReady mass; where the USD gives no centre of mass or inertia, AnyBuild computed them from the collision hulls"
    return mass, centre, tensor, source


def _quat_matrix(w: float, x: float, y: float, z: float) -> np.ndarray:
    """Column-vector rotation matrix of a quaternion."""

    norm = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def _orthonormal(matrix: np.ndarray) -> np.ndarray:
    u, _, vt = np.linalg.svd(matrix)
    return u @ vt


def valid_inertia(tensor: np.ndarray) -> tuple[np.ndarray, bool]:
    """(tensor, changed): symmetric, positive, and each principal moment at most the sum of the other two, as MuJoCo requires."""

    tensor = (np.asarray(tensor, dtype=float) + np.asarray(tensor, dtype=float).T) / 2.0
    moments, axes = np.linalg.eigh(tensor)
    fixed = np.maximum(moments, max(float(moments.max()), 1e-12) * 1e-6)
    for i in range(3):
        others = fixed.sum() - fixed[i]
        fixed[i] = min(fixed[i], others)
    changed = bool(np.any(np.abs(fixed - moments) > 1e-3 * max(float(moments.max()), 1e-12)))
    return axes @ np.diag(fixed) @ axes.T, changed


def _mass_from_hulls(meshes: list[tuple["Mesh", float | None]]):
    """(mass, centre, tensor) of the meshes' convex hulls at their density (water's without one), or None without volume."""

    import trimesh

    mass, parts = 0.0, []
    for mesh, density in meshes:
        hull = trimesh.Trimesh(mesh.vertices[np.unique(mesh.faces)], process=False).convex_hull
        if hull.volume <= 0:
            continue
        m = hull.volume * (density or 1000.0)
        mass += m
        parts.append((m, np.asarray(hull.center_mass), np.asarray(hull.moment_inertia) * (density or 1000.0)))
    if mass <= 0:
        return None
    centre = sum(m * c for m, c, _ in parts) / mass
    tensor = np.zeros((3, 3))
    for m, c, t in parts:
        d = c - centre
        tensor += t + m * (float(d @ d) * np.eye(3) - np.outer(d, d))
    return mass, centre, tensor


def _merge(meshes: list[Mesh]) -> Mesh:
    vertices, faces, offset = [], [], 0
    for mesh in meshes:
        used = np.unique(mesh.faces)
        remap = np.full(len(mesh.vertices), -1, dtype=np.int64)
        remap[used] = np.arange(len(used)) + offset
        vertices.append(mesh.vertices[used])
        faces.append(remap[mesh.faces])
        offset += len(used)
    return Mesh(np.concatenate(vertices), np.concatenate(faces), ",".join(sorted({m.source for m in meshes})))


# ---------------------------------------------------------------- containers


def cavity(mesh: Mesh) -> tuple[float, float]:
    """(deepest water in mm, share of the bounding box it fills) the top surface holds, flooded from above.

    The top surface is the highest point of the mesh in each cell of a plan-view grid (every
    triangle sampled at least twice per cell width, so no cell inside the outline stays empty);
    the border around the outline is the floor, where water drains away.
    """

    vertices, faces = mesh.vertices, mesh.faces
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    span = float(max(high[0] - low[0], high[1] - low[1]))
    height = float(high[2] - low[2])
    if span <= 0 or height <= 0 or not len(faces):
        return 0.0, 0.0
    cell = span / _GRID
    nx, ny = int(math.ceil((high[0] - low[0]) / cell)) + 1, int(math.ceil((high[1] - low[1]) / cell)) + 1
    points = _lattice(vertices[faces], cell / 2.0)
    grid = np.full((nx + 2, ny + 2), low[2])
    ix = np.clip(((points[:, 0] - low[0]) / cell).astype(np.int64) + 1, 1, nx)
    iy = np.clip(((points[:, 1] - low[1]) / cell).astype(np.int64) + 1, 1, ny)
    np.maximum.at(grid, (ix, iy), points[:, 2])

    level = np.full(grid.shape, np.inf)
    heap = []
    for i in range(grid.shape[0]):
        for j in (0, grid.shape[1] - 1):
            heap.append((grid[i, j], i, j))
    for j in range(1, grid.shape[1] - 1):
        for i in (0, grid.shape[0] - 1):
            heap.append((grid[i, j], i, j))
    for h, i, j in heap:
        level[i, j] = h
    heapq.heapify(heap)
    while heap:
        h, i, j = heapq.heappop(heap)
        if h > level[i, j]:
            continue
        for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= a < grid.shape[0] and 0 <= b < grid.shape[1]:
                water = max(h, grid[a, b])
                if water < level[a, b]:
                    level[a, b] = water
                    heapq.heappush(heap, (water, a, b))
    water = level - grid
    volume = float(water.sum()) * cell * cell
    box = (high[0] - low[0]) * (high[1] - low[1]) * height
    return round(float(water.max()) * 1000.0, 1), round(volume / box, 3) if box > 0 else 0.0


def _lattice(triangles: np.ndarray, spacing: float) -> np.ndarray:
    """Points on every triangle on a barycentric lattice no coarser than `spacing` in plan view, plus its corners."""

    edges = np.stack([triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 1], triangles[:, 0] - triangles[:, 2]], axis=1)
    longest = np.sqrt((edges[:, :, :2] ** 2).sum(axis=2)).max(axis=1)
    steps = np.clip(np.ceil(longest / spacing), 1, 256).astype(np.int64)
    out = [triangles.reshape(-1, 3)]
    for n in np.unique(steps):
        if n <= 1:
            continue
        chosen = triangles[steps == n]
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
        keep = (i + j) <= n
        u, v = (i[keep] / n)[None, :, None], (j[keep] / n)[None, :, None]
        a, b, c = chosen[:, 0][:, None, :], chosen[:, 1][:, None, :], chosen[:, 2][:, None, :]
        out.append((a + u * (b - a) + v * (c - a)).reshape(-1, 3))
    return np.concatenate(out)


# ---------------------------------------------------------------- conversion cache


def _code_key() -> str:
    digest = hashlib.sha256()
    for path in _CODE:
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def converted_dir(package: Package) -> Path:
    key = hashlib.sha256((package.digest() + _code_key()).encode()).hexdigest()[:20]
    return revision_dir(package.revision) / "converted" / package.asset_id / key


def _cache_enabled() -> bool:
    from pai_agent import cache

    return cache.enabled()


def write_stl(path: Path, vertices: np.ndarray, faces: np.ndarray, header: str = "") -> None:
    """Binary STL; the 80-byte header carries the attribution."""

    triangles = vertices[faces].astype(np.float32)
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, lengths, out=np.zeros_like(normals), where=lengths > 0).astype(np.float32)
    record = np.zeros(len(faces), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    record["n"], record["v"] = normals, triangles
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    with partial.open("wb") as handle:
        handle.write(header.encode("ascii", "replace")[:80].ljust(80, b" "))
        handle.write(struct.pack("<I", len(faces)))
        handle.write(record.tobytes())
    os.replace(partial, path)


def read_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = path.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    record = np.frombuffer(data, dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")], count=count, offset=84)
    vertices = record["v"].reshape(-1, 3).astype(float)
    return vertices, np.arange(len(vertices)).reshape(-1, 3)


def prepare(package: Package) -> tuple[Path, dict]:
    """The converted folder with the visual meshes, the convex hulls and asset.json; read from the USD once."""

    folder = converted_dir(package)
    meta_path = folder / "asset.json"
    if _cache_enabled() and meta_path.is_file():
        try:
            return folder, json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    asset = read_asset(package)
    folder.mkdir(parents=True, exist_ok=True)
    header = f"SimReady {package.asset_id} by {asset.author}, {LICENSE_NAME}"
    visuals = []
    for index, visual in enumerate(asset.visuals):
        name = f"visual-{index}.stl"
        write_stl(folder / name, visual.mesh.vertices, visual.mesh.faces, header)
        visuals.append({"file": name, "material": visual.material, "rgba": list(visual.rgba), "triangles": int(len(visual.mesh.faces))})
    groups = []
    everything = _merge([mesh for group in asset.groups for mesh in group.meshes])
    for g, group in enumerate(asset.groups):
        hulls = []
        for k, mesh in enumerate(group.meshes):
            vertices, faces = _hull(mesh)
            name = f"hull-{g}-{k}.stl"
            write_stl(folder / name, vertices, faces, header)
            hulls.append(name)
        merged = _merge(group.meshes)
        np.savez(folder / f"collision-{g}.npz", vertices=merged.vertices, faces=merged.faces)
        groups.append(
            {
                "material": group.material,
                "friction": round(group.friction, 4),
                "static_friction": group.static_friction,
                "restitution": group.restitution,
                "hulls": hulls,
                "mesh": f"collision-{g}.npz",
                "triangles": int(len(merged.faces)),
            }
        )
    depth_mm, share = cavity(everything)
    meta = {
        "asset_id": package.asset_id,
        "revision": package.revision,
        "author": asset.author,
        "wikidata": {"class": asset.wikidata_class, "qcode": asset.qcode},
        "documentation": asset.documentation,
        "size_mm": asset.size_mm,
        "bbox_m": [asset.bbox_min.tolist(), asset.bbox_max.tolist()],
        "mass_kg": asset.mass_kg,
        "com_m": asset.com.tolist(),
        "inertia_kg_m2": asset.inertia.tolist(),
        "mass_source": asset.mass_source,
        "visuals": visuals,
        "groups": groups,
        "grasps": asset.grasps,
        "maxhullvert": asset.maxhullvert,
        "bodies": asset.bodies,
        "cavity_mm": depth_mm,
        "cavity_share": share,
        "warnings": asset.warnings,
    }
    meta_path.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return folder, meta


def _hull(mesh: Mesh) -> tuple[np.ndarray, np.ndarray]:
    """The convex hull of one collision mesh; a flat mesh gets a hull 1 mm thick so MuJoCo can collide it."""

    import trimesh

    used = mesh.vertices[np.unique(mesh.faces)]
    try:
        hull = trimesh.Trimesh(used, process=False).convex_hull
        if hull.volume > 1e-12:
            return np.asarray(hull.vertices), np.asarray(hull.faces)
    except Exception:
        pass
    low, high = used.min(axis=0), used.max(axis=0)
    thin = np.maximum(high - low, 0.001)
    box = trimesh.creation.box(extents=thin)
    box.apply_translation((low + high) / 2.0)
    return np.asarray(box.vertices), np.asarray(box.faces)


def decomposition(package: Package, folder: Path, meta: dict) -> dict:
    """CoACD parts per collision group, cached in the converted folder: {"status", "groups": [[files]], "seconds", "error"}."""

    path = folder / "coacd.json"
    if _cache_enabled() and path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    with _HEAVY:
        if _cache_enabled() and path.is_file():
            # Another call decomposed the same object while this one waited.
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return _decompose(package, folder, meta, path)


def _decompose(package: Package, folder: Path, meta: dict, path: Path) -> dict:
    started = time.perf_counter()
    header = f"SimReady {package.asset_id} by {meta['author']}, {LICENSE_NAME}"
    result = {"status": "ok", "groups": [], "seconds": 0.0, "error": "", "threshold": COACD_THRESHOLD}
    budget = decompose_timeout()
    scratch = Path(tempfile.mkdtemp(prefix="coacd-", dir=_scratch()))
    try:
        for g, group in enumerate(meta["groups"]):
            remaining = budget - (time.perf_counter() - started)
            if remaining <= 1:
                raise subprocess.TimeoutExpired("coacd", budget)
            out = scratch / f"parts-{g}.npz"
            completed = subprocess.run(
                [sys.executable, "-m", "pai_agent.simready.decompose", str(folder / group["mesh"]), str(out), str(COACD_THRESHOLD), str(COACD_MAX_PARTS), str(COACD_SEED)],
                capture_output=True,
                text=True,
                timeout=remaining,
                check=False,
            )
            if completed.returncode != 0 or not out.is_file():
                tail = (completed.stderr or completed.stdout or "no output").strip().splitlines()[-1:] or ["no output"]
                raise ConvertError(f"CoACD stopped with code {completed.returncode}: {tail[0][:200]}")
            files = []
            with np.load(out) as parts:
                for k in range(int(parts["count"])):
                    name = f"coacd-{g}-{k}.stl"
                    write_stl(folder / name, parts[f"v{k}"], parts[f"f{k}"], header)
                    files.append(name)
            result["groups"].append(files)
    except subprocess.TimeoutExpired:
        result.update(status="timeout", groups=[], error=f"CoACD took longer than {budget:g} s")
    except (ConvertError, OSError, ValueError, KeyError) as exc:
        result.update(status="failed", groups=[], error=str(exc))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    result["seconds"] = round(time.perf_counter() - started, 1)
    if result["status"] == "ok":
        path.write_text(json.dumps(result), encoding="utf-8")
    return result


def _scratch() -> Path:
    folder = cache_root() / "tmp"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ---------------------------------------------------------------- MJCF


@dataclass
class MjcfObject:
    """One object as MJCF: a <body> (in the scene at pos and quat) and the <mesh> assets it needs.

    Mesh `file` attributes are the keys of `files`, bare names, so the XML works next to copies of
    those files or with MuJoCo's in-memory assets (`assets()`).
    """

    asset_id: str
    name: str
    body: str
    assets_xml: str
    files: dict[str, Path]
    meta: dict

    def assets(self) -> dict[str, bytes]:
        return {name: path.read_bytes() for name, path in self.files.items()}

    def standalone(self) -> str:
        """A whole MJCF document with just this body: loadable on its own, or <include>d into a scene."""

        return (
            f'<mujoco model={quoteattr(self.name)}>\n'
            f"  <!-- {_comment(self.meta['attribution'])} -->\n"
            f"  <asset>\n{self.assets_xml}  </asset>\n"
            f"  <worldbody>\n{_indent(self.body, 4)}  </worldbody>\n"
            "</mujoco>\n"
        )


def collision_mode(requested: str, meta: dict) -> str:
    """auto: a container (a cavity at least CAVITY_MM deep over CAVITY_SHARE of the box) is decomposed, the rest hulled."""

    if requested not in COLLISION_MODES:
        raise SimReadyError(f"collision must be one of {', '.join(COLLISION_MODES)}, not {requested!r}")
    if requested != "auto":
        return requested
    return "decompose" if meta["cavity_mm"] >= CAVITY_MM and meta["cavity_share"] >= CAVITY_SHARE else "hull"


def to_mjcf(
    asset_id: str,
    *,
    collision: str = "auto",
    name: str | None = None,
    file_prefix: str | None = None,
    pos=(0.0, 0.0, 0.0),
    quat=(1.0, 0.0, 0.0, 0.0),
    free: bool = True,
    source=None,
) -> MjcfObject:
    """The object as an MJCF <body> with its meshes: visual meshes per material, convex collision geoms
    (one hull per collision mesh, or CoACD parts for a container), mass, inertia and friction from the USD.

    The body frame is the asset frame (Z up, metres); `pos` and `quat` place it, `free` gives it a free joint.
    """

    package = fetch(asset_id, source=source)
    folder, meta = prepare(package)
    mode = collision_mode(collision, meta)
    collision_info = {"requested": collision, "method": "hull", "parts": 0, "cavity_mm": meta["cavity_mm"], "cavity_share": meta["cavity_share"]}
    warnings = list(meta["warnings"])
    parts_by_group = [group["hulls"] for group in meta["groups"]]
    if mode == "decompose":
        result = decomposition(package, folder, meta)
        collision_info["seconds"] = result["seconds"]
        if result["status"] == "ok":
            parts_by_group = result["groups"]
            collision_info["method"] = "coacd"
            collision_info["threshold"] = result.get("threshold", COACD_THRESHOLD)
        else:
            warnings.append(f"{result['error']}; using one convex hull per collision mesh, so its cavity collides as a lid.")
    collision_info["parts"] = sum(len(files) for files in parts_by_group)

    name = name or asset_id
    prefix = file_prefix if file_prefix is not None else name + "-"
    files: dict[str, Path] = {}
    assets, geoms = [], []
    hull_limit = f' maxhullvert="{meta["maxhullvert"]}"' if meta.get("maxhullvert") else ""
    for index, visual in enumerate(meta["visuals"]):
        mesh = f"{name}-visual-{index}"
        files[prefix + visual["file"]] = folder / visual["file"]
        # Visual meshes never collide; shell inertia accepts open surfaces (the body's inertial is explicit anyway).
        assets.append(f'<mesh name={quoteattr(mesh)} file={quoteattr(prefix + visual["file"])} inertia="shell"/>')
        geoms.append(f'<geom name={quoteattr(mesh)} type="mesh" mesh={quoteattr(mesh)} contype="0" conaffinity="0" group="2" density="0" rgba="{_floats(visual["rgba"])}"/>')
    for g, files_of_group in enumerate(parts_by_group):
        group = meta["groups"][g]
        friction = f'{_float(group["friction"])} {TORSIONAL:g} {ROLLING:g}'
        for k, file_name in enumerate(files_of_group):
            mesh = f"{name}-collision-{g}-{k}"
            files[prefix + file_name] = folder / file_name
            assets.append(f'<mesh name={quoteattr(mesh)} file={quoteattr(prefix + file_name)}{hull_limit}/>')
            geoms.append(f'<geom name={quoteattr(mesh)} type="mesh" mesh={quoteattr(mesh)} group="3" friction="{friction}" density="0" rgba="0.36 0.62 0.78 0.35"/>')
    sites = [
        f'<site name={quoteattr(f"{name}-grasp-{grasp["id"]}")} pos="{_floats(grasp["pos"])}" size="0.004" group="4" rgba="1 0.54 0.24 1"/>'
        for grasp in meta["grasps"]
    ]
    inertia = np.asarray(meta["inertia_kg_m2"], dtype=float)
    full = [inertia[0, 0], inertia[1, 1], inertia[2, 2], inertia[0, 1], inertia[0, 2], inertia[1, 2]]
    lines = [f'<body name={quoteattr(name)} pos="{_floats(pos)}" quat="{_floats(quat)}">']
    if free:
        lines.append(f"  <freejoint name={quoteattr(name)}/>")
    lines.append(f'  <inertial pos="{_floats(meta["com_m"])}" mass="{_float(meta["mass_kg"])}" fullinertia="{_floats(full)}"/>')
    lines += ["  " + line for line in geoms + sites]
    lines.append("</body>")
    body = "\n".join(lines) + "\n"
    assets_xml = "".join("    " + line + "\n" for line in assets)

    changes = changes_for(collision_info)
    friction_main = _main_friction(meta)
    info = {
        **{key: meta[key] for key in ("asset_id", "author", "wikidata", "documentation", "size_mm", "mass_source", "grasps", "bodies")},
        "mass_g": round(meta["mass_kg"] * 1000.0, 1),
        "com_mm": [round(v * 1000.0, 2) for v in meta["com_m"]],
        "friction": friction_main,
        "frictions": [{"material": group["material"].rsplit("/", 1)[-1], "friction": group["friction"]} for group in meta["groups"]],
        "collision": collision_info,
        "warnings": warnings,
        "changes": changes,
        "attribution": attribution(asset_id, meta["author"], package.revision, changes),
        "source": source_tag(package.revision),
        "bbox_m": meta["bbox_m"],
    }
    obj = MjcfObject(asset_id, name, body, assets_xml, files, info)
    _check_compiles(obj)
    return obj


def _main_friction(meta: dict) -> float:
    """The friction of the collision group with the most triangles: the one number a card shows."""

    main = max(meta["groups"], key=lambda group: group["triangles"])
    return float(main["friction"])


def changes_for(collision_info: dict) -> list[str]:
    changes = ["Converted from USD to STL meshes and an MJCF body for MuJoCo (Z up, metres)"]
    if collision_info["method"] == "coacd":
        changes.append(f"Collision split into {collision_info['parts']} convex parts with CoACD instead of one convex hull")
    else:
        changes.append("Collision meshes replaced by their convex hulls")
    return changes


def attribution(asset_id: str, author: str, revision: str, changes: list[str]) -> str:
    """CC BY 4.0 attribution: title, author, source, license and the changes made."""

    listed = "; ".join(change[:1].lower() + change[1:] for change in changes)
    return (
        f'"{asset_id}" by {author}, from the SimReady assets ({asset_url(asset_id, revision)}), '
        f"licensed under {LICENSE_NAME} ({LICENSE_URL}). Changed by AnyBuild: {listed}."
    )


def _check_compiles(obj: MjcfObject) -> None:
    """The body is only handed out once MuJoCo compiles it."""

    import mujoco

    try:
        mujoco.MjModel.from_xml_string(obj.standalone(), obj.assets())
    except Exception as exc:
        raise ConvertError(f"{obj.asset_id}: MuJoCo does not compile the converted body: {exc}") from exc


def scene_xml(objects: list[MjcfObject], floor: bool = True, timestep: float = 0.002) -> tuple[str, dict[str, bytes]]:
    """Objects on a floor in one MJCF document, with the in-memory mesh assets MjModel.from_xml_string takes."""

    assets: dict[str, bytes] = {}
    for obj in objects:
        assets.update(obj.assets())
    ground = '    <geom name="floor" type="plane" size="2 2 0.05" rgba="0.92 0.92 0.9 1"/>\n' if floor else ""
    xml = (
        '<mujoco model="simready scene">\n'
        f'  <option timestep="{timestep:g}"/>\n'
        "  <asset>\n" + "".join(obj.assets_xml for obj in objects) + "  </asset>\n"
        "  <worldbody>\n" + ground + "".join(_indent(obj.body, 4) for obj in objects) + "  </worldbody>\n"
        "</mujoco>\n"
    )
    return xml, assets


def _float(value: float) -> str:
    return f"{float(value):.6g}"


def _floats(values) -> str:
    return " ".join(_float(v) for v in values)


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "".join(pad + line + "\n" for line in text.splitlines())


def _comment(text: str) -> str:
    return escape(text.replace("--", "- -"))


# ---------------------------------------------------------------- GLB


def to_glb(asset_id: str, *, source=None) -> tuple[Path, dict]:
    """(path, info) of the object as GLB for the 3D view: Y up, metres, the asset origin, textures embedded.

    Blender (the one blender_render uses) converts the USD with its materials, textures scaled down to
    at most GLB_TEXTURE_PX; without Blender, or when it fails, the visual meshes are written in their
    base colours without textures.
    """

    from pai_agent.tools.blender import find_blender

    package = fetch(asset_id, source=source)
    folder, meta = prepare(package)
    binary = find_blender()
    from pai_agent import cache

    key = hashlib.sha256((_BLENDER_SCRIPT.read_bytes() + f"{cache.tool_version(binary)}:{GLB_TEXTURE_PX}".encode())).hexdigest()[:12]
    target = folder / f"object-{key}.glb"
    info_path = target.with_suffix(".json")
    if _cache_enabled() and target.is_file() and info_path.is_file():
        try:
            return target, json.loads(info_path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    copyright_text = attribution(asset_id, meta["author"], package.revision, ["Converted from USD to glTF binary (GLB)"])
    info = {"method": "blender", "textured": True, "error": ""}
    started = time.perf_counter()
    if binary:
        try:
            with _HEAVY:
                completed = subprocess.run(
                    [binary, "-b", "--factory-startup", "-t", str(BLENDER_THREADS), "-P", str(_BLENDER_SCRIPT), "--", str(package.root_usd), str(target), copyright_text, str(GLB_TEXTURE_PX)],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                )
            if completed.returncode != 0 or not target.is_file() or target.stat().st_size < 64:
                tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-1:] or ["no GLB written"]
                raise ConvertError("Blender: " + tail[0][:200])
            resized = re.search(r"ANYBUILD_RESIZED (\d+)", completed.stdout or "")
            info["textures_resized"] = int(resized.group(1)) if resized else 0
        except (subprocess.SubprocessError, OSError, ConvertError) as exc:
            info = {"method": "trimesh", "textured": False, "error": str(exc)}
    else:
        info = {"method": "trimesh", "textured": False, "error": "Blender is not installed"}
    if info["method"] == "trimesh":
        _plain_glb(folder, meta, target, copyright_text)
    info["seconds"] = round(time.perf_counter() - started, 1)
    if not info["textured"]:
        info["change"] = "Converted to an untextured glTF binary (GLB) in the materials' base colours"
    elif info.get("textures_resized"):
        info["change"] = f"Converted from USD to glTF binary (GLB) with Blender, textures scaled down to at most {GLB_TEXTURE_PX} px"
    else:
        info["change"] = "Converted from USD to glTF binary (GLB) with Blender"
    info_path.write_text(json.dumps(info), encoding="utf-8")
    return target, info


def _plain_glb(folder: Path, meta: dict, target: Path, copyright_text: str) -> None:
    import trimesh

    scene = trimesh.Scene()
    # Asset frame Z up to glTF's Y up: (x, y, z) becomes (x, z, -y).
    turn = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
    for index, visual in enumerate(meta["visuals"]):
        vertices, faces = read_stl(folder / visual["file"])
        mesh = trimesh.Trimesh(vertices @ turn.T, faces, process=True)
        rgba = [int(round(255 * v)) for v in visual["rgba"]]
        mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(baseColorFactor=rgba, metallicFactor=0.0, roughnessFactor=0.7))
        scene.add_geometry(mesh, node_name=f"visual-{index}")

    def stamp(tree: dict) -> None:
        tree.setdefault("asset", {})["copyright"] = copyright_text

    data = trimesh.exchange.gltf.export_glb(scene, tree_postprocessor=stamp)
    partial = target.with_name(target.name + ".partial")
    partial.write_bytes(data)
    os.replace(partial, target)
