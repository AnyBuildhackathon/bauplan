"""Headless studio render of the whole drone.

Blender runs this with `blender -b -P studio.py -- frame.stl out.png [assembly.json]`.
The frame is the real STL from CAD. Motors, propellers, the flight controller and the
battery are placed from assembly.json (arm length, plate thickness, battery size in mm),
so a new battery in v2 shows up in the picture. Scene units are metres.
"""

import json
import math
import sys

import bpy
from mathutils import Vector

DEFAULT = {"arm_mm": 36.0, "thickness_mm": 2.0, "battery_mm": [68.0, 15.5, 6.7], "prop_mm": 40.0}
MM = 0.001


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :]
    stl_path, png_path = argv[0], argv[1]
    spec = dict(DEFAULT)
    if len(argv) > 2:
        with open(argv[2], encoding="utf-8") as handle:
            spec.update(json.load(handle))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.scale_length = 1.0

    mats = _materials()
    if spec.get("mode") == "part":
        radius, height = _part(spec["parts"], mats["frame"])
        _studio(mats)
        _lights()
        _camera(radius, height / 2)
        _render_settings(scene, png_path)
        bpy.ops.render.render(write_still=True)
        return
    frame = _frame(stl_path, mats["frame"])
    top = spec["thickness_mm"] * MM
    arm = spec["arm_mm"] * MM
    for index in range(4):
        angle = math.radians(45 + index * 90)
        x, y = arm * math.cos(angle), arm * math.sin(angle)
        _motor(mats, (x, y, top), spin=index % 2 == 0, prop_radius=spec["prop_mm"] * MM / 2)
    _flight_controller(mats, top)
    _battery(mats, top, [v * MM for v in spec["battery_mm"]])
    frame.rotation_euler[2] = math.radians(45)

    _studio(mats)
    _lights()
    _camera(arm + spec["prop_mm"] * MM / 2)
    _render_settings(scene, png_path)
    bpy.ops.render.render(write_still=True)


# --- materials ---------------------------------------------------------------------


def _principled(name, color, roughness=0.5, metallic=0.0, coat=0.0, alpha=1.0, transmission=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    for key in ("Coat Weight", "Clearcoat"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = coat
            break
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = transmission
    if alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = alpha
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "BLENDED"
    return mat


def _srgb(hex_color: str):
    value = hex_color.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(value[i : i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def _materials() -> dict:
    return {
        "frame": _principled("PLA", _srgb("#FF8A3D"), roughness=0.42, coat=0.15),
        "bell": _principled("Glocke", _srgb("#2A2C31"), roughness=0.28, metallic=0.9),
        "base": _principled("Aluminium", _srgb("#B8BDC6"), roughness=0.3, metallic=1.0),
        "copper": _principled("Kupfer", _srgb("#B8733A"), roughness=0.35, metallic=1.0),
        "prop": _principled("Propeller", _srgb("#F1F3F7"), roughness=0.3, alpha=0.88),
        "pcb": _principled("Platine", _srgb("#1B2230"), roughness=0.45, coat=0.4),
        "chip": _principled("Chip", _srgb("#0E0F12"), roughness=0.35),
        "gold": _principled("Gold", _srgb("#D9B25C"), roughness=0.25, metallic=1.0),
        "battery": _principled("Akku", _srgb("#2B2E35"), roughness=0.32, coat=0.5),
        "label": _principled("Etikett", _srgb("#F2B33D"), roughness=0.4),
        "strap": _principled("Gurt", _srgb("#141518"), roughness=0.8),
        "floor": _principled("Boden", _srgb("#ECEBF1"), roughness=0.62),
    }


# --- parts -------------------------------------------------------------------------


def _frame(path: str, material):
    try:
        bpy.ops.wm.stl_import(filepath=path)
    except (AttributeError, RuntimeError):
        bpy.ops.import_mesh.stl(filepath=path)
    obj = bpy.context.selected_objects[0]
    bpy.context.view_layer.objects.active = obj
    obj.scale = (MM, MM, MM)
    bpy.ops.object.transform_apply(scale=True)
    low = min((obj.matrix_world @ Vector(c)).z for c in obj.bound_box)
    obj.location.z -= low
    bpy.ops.object.shade_auto_smooth() if hasattr(bpy.ops.object, "shade_auto_smooth") else None
    _bevel(obj, 0.0003)
    obj.data.materials.append(material)
    return obj


def _part(parts, fallback):
    """Any generated part: each STL with its own color, centred on the floor. Returns the camera radius."""

    objects = []
    for index, part in enumerate(parts):
        color = part.get("color")
        # #rrggbbaa marks a see-through body, such as the phone a stand holds.
        alpha = int(color.lstrip("#")[6:8], 16) / 255.0 if color and len(color.lstrip("#")) == 8 else 1.0
        material = _principled("Teil" + str(index), _srgb(color), roughness=0.42, coat=0.15, alpha=max(alpha, 0.3)) if color else fallback
        objects.append(_frame(part["stl"], material))
    # _frame drops each object onto the floor on its own; put them back together first.
    for obj in objects:
        obj.location.z = 0
    corners = [obj.matrix_world @ Vector(c) for obj in objects for c in obj.bound_box]
    low = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    high = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    center = (low + high) / 2
    for obj in objects:
        obj.location.x -= center.x
        obj.location.y -= center.y
        obj.location.z -= low.z
    # The frame is landscape: a tall product needs more room than a flat one of the same size.
    return max(max(high.x - low.x, high.y - low.y) * 0.7, (high.z - low.z) * 0.9), high.z - low.z


def _bevel(obj, width: float) -> None:
    mod = obj.modifiers.new("Kante", "BEVEL")
    mod.width = width
    mod.segments = 2
    mod.limit_method = "ANGLE"


def _cyl(name, radius, depth, location, material, vertices=48):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    bpy.ops.object.shade_smooth()
    _bevel(obj, min(radius, depth) * 0.12)
    return obj


def _box(name, size, location, material, bevel=0.0006):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(scale=True)
    obj.data.materials.append(material)
    _bevel(obj, bevel)
    return obj


def _motor(mats, at, spin: bool, prop_radius: float) -> None:
    x, y, z = at
    _cyl("Motorfuß", 0.0068, 0.0022, (x, y, z + 0.0011), mats["base"])
    _cyl("Wicklung", 0.0055, 0.004, (x, y, z + 0.004), mats["copper"])
    _cyl("Glocke", 0.0071, 0.0082, (x, y, z + 0.0084), mats["bell"])
    _cyl("Welle", 0.0008, 0.004, (x, y, z + 0.0142), mats["base"], vertices=16)
    hub_z = z + 0.0145
    _cyl("Nabe", 0.0032, 0.004, (x, y, hub_z), mats["prop"])
    for blade in range(3):
        angle = math.radians(blade * 120 + (0 if spin else 60))
        bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=1, depth=0.0007)
        obj = bpy.context.object
        obj.name = "Blatt"
        obj.scale = (prop_radius * 0.5, prop_radius * 0.13, 1)
        bpy.ops.object.transform_apply(scale=True)
        obj.rotation_euler = (math.radians(14 if spin else -14), 0, angle)
        obj.location = (x + math.cos(angle) * prop_radius * 0.52, y + math.sin(angle) * prop_radius * 0.52, hub_z)
        obj.data.materials.append(mats["prop"])
        bpy.ops.object.shade_smooth()


def _flight_controller(mats, top: float) -> None:
    z = top + 0.0035
    _box("Flugregler", (0.029, 0.029, 0.0016), (0, 0, z), mats["pcb"], bevel=0.0004)
    _box("Prozessor", (0.007, 0.007, 0.0012), (0.004, -0.004, z + 0.0014), mats["chip"], bevel=0.0002)
    for sx in (-1, 1):
        for sy in (-1, 1):
            _cyl("Pad", 0.0012, 0.0004, (sx * 0.0115, sy * 0.0115, z + 0.001), mats["gold"], vertices=16)


def _battery(mats, top: float, size) -> None:
    length, width, height = size
    z = top + 0.0035 + 0.0008 + 0.0025 + height / 2
    _box("Akku", (width, length, height), (0, 0, z), mats["battery"], bevel=min(width, height) * 0.18)
    _box("Etikett", (width * 1.002, length * 0.42, height * 1.002), (0, -length * 0.12, z), mats["label"], bevel=min(width, height) * 0.18)
    _box("Gurt", (width + 0.0014, 0.008, height + 0.0014), (0, length * 0.22, z), mats["strap"], bevel=0.0004)


# --- studio ------------------------------------------------------------------------


def _studio(mats) -> None:
    """A seamless cyclorama: a floor that curves up into a back wall, so there is no horizon."""

    import bmesh

    mesh = bpy.data.meshes.new("Hohlkehle")
    bm = bmesh.new()
    width, front, wall, height, radius, steps = 3.0, 1.5, 0.45, 1.2, 0.3, 18
    # Profile in (y, z): floor towards the wall, a quarter circle, then the wall up.
    profile = [(-front, 0.0)]
    for i in range(steps + 1):
        a = math.pi / 2 * i / steps
        profile.append((wall - radius + radius * math.sin(a), radius - radius * math.cos(a)))
    profile.append((wall, height))
    rows = [[bm.verts.new((x, py, pz)) for py, pz in profile] for x in (-width / 2, width / 2)]
    for i in range(len(profile) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("Hohlkehle", mesh)
    bpy.context.collection.objects.link(obj)
    # Turn the wall to face the camera, which looks from the front right.
    obj.rotation_euler[2] = math.atan2(0.68, -0.62) - math.pi / 2
    obj.data.materials.append(mats["floor"])
    for poly in obj.data.polygons:
        poly.use_smooth = True
    world = bpy.data.worlds.new("Studio")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (*_srgb("#E9E8F0"), 1.0)
    background.inputs["Strength"].default_value = 0.18


def _area(name, location, energy, size, color=(1.0, 1.0, 1.0), target=(0, 0, 0.012)):
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    direction = Vector(target) - Vector(location)
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _lights() -> None:
    _area("Key", (0.35, -0.3, 0.5), 8.0, 0.35, color=(1.0, 0.97, 0.93))
    _area("Fill", (-0.45, -0.25, 0.22), 1.6, 0.5, color=(0.92, 0.95, 1.0))
    _area("Rim", (-0.2, 0.4, 0.28), 4.5, 0.25)
    _area("Top", (0.0, 0.0, 0.6), 1.5, 0.7)


def _camera(radius: float, target_z: float = 0.011) -> None:
    data = bpy.data.cameras.new("Kamera")
    data.lens = 85
    data.dof.use_dof = True
    data.dof.aperture_fstop = 22
    obj = bpy.data.objects.new("Kamera", data)
    bpy.context.collection.objects.link(obj)
    distance = radius * 6.9
    obj.location = (distance * 0.55, -distance * 0.6, distance * 0.58)
    target = Vector((0, 0, target_z))
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()
    data.dof.focus_distance = (target - obj.location).length
    bpy.context.scene.camera = obj


def _render_settings(scene, png_path: str) -> None:
    for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    eevee = getattr(scene, "eevee", None)
    if eevee is not None:
        for key, value in (("taa_render_samples", 64), ("use_shadows", True), ("use_raytracing", True), ("use_gtao", True)):
            if hasattr(eevee, key):
                setattr(eevee, key, value)
    view = scene.view_settings
    try:
        view.view_transform = "AgX"
        view.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.film_transparent = False
    scene.render.filepath = png_path
    scene.render.image_settings.file_format = "PNG"


if __name__ == "__main__":
    main()
