"""Runs inside Blender: imports a SimReady USD and writes a textured GLB for AnyBuild's 3D view.

    blender -b --factory-startup -t 2 -P blender_glb.py -- <root.usd> <out.glb> <copyright> <max texture px>

Blender's USD importer reads the UsdPreviewSurface materials with their base colour, normal and
ORM textures; the glTF exporter packs them into the GLB (metallic-roughness from the ORM map),
Y up in metres with the asset's own origin. Only the visible render meshes come along: no
guides (the grasp curves), no proxies, no cameras or lights, and every mesh is a plain object
(no instancing), so the GLB has one node per mesh and nothing twice. Textures larger than the
given size are scaled down to it, so a browser can load the model (SimReady ships some objects
with hundreds of megabytes of 4K and 8K textures); the line `ANYBUILD_RESIZED <n>` says how many.
The CC BY 4.0 attribution goes into the glTF `asset.copyright` field.
"""

import sys

import bpy

source, target, copyright_text, max_px = sys.argv[sys.argv.index("--") + 1:][:4]
max_px = int(max_px)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.usd_import(
    filepath=source,
    import_cameras=False,
    import_lights=False,
    import_curves=False,
    import_points=False,
    import_volumes=False,
    import_skeletons=False,
    import_blendshapes=False,
    import_shapes=False,
    import_visible_only=True,
    import_guide=False,
    import_proxy=False,
    import_render=True,
    support_scene_instancing=False,
    import_materials=True,
    import_usd_preview=True,
    create_world_material=False,
    import_textures_mode="IMPORT_PACK",
)

meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
if not meshes:
    raise SystemExit("The USD has no visible mesh.")
# Flatten the USD scopes (Geometry, PhysicsMaterials, ...) away: each mesh keeps its place in the world.
for obj in meshes:
    world = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = world
for obj in [obj for obj in bpy.data.objects if obj.type != "MESH"]:
    bpy.data.objects.remove(obj, do_unlink=True)
for obj in meshes:
    # Blender suffixed the mesh with .001 where its USD Xform had the same name.
    obj.name = obj.name.rsplit(".", 1)[0] if obj.name.rsplit(".", 1)[-1].isdigit() else obj.name

resized = 0
for image in bpy.data.images:
    width, height = image.size
    if max(width, height) > max_px:
        scale = max_px / max(width, height)
        image.scale(max(1, round(width * scale)), max(1, round(height * scale)))
        # Packed again, so the exporter writes the smaller pixels and not the original file.
        image.pack()
        resized += 1
print(f"ANYBUILD_RESIZED {resized}")

bpy.ops.export_scene.gltf(
    filepath=target,
    export_format="GLB",
    export_yup=True,
    export_apply=True,
    export_materials="EXPORT",
    export_image_format="AUTO",
    export_texcoords=True,
    export_normals=True,
    export_extras=False,
    export_copyright=copyright_text,
)
