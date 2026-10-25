"""One render of many part models on a grid, each scaled to its cell and labelled with its real size.

blender -b -P contact_sheet.py -- sheet.json out.png [eevee|workbench]
sheet.json: {"columns": 10, "cell_px": 320, "items": [{"label": "...", "glb": "/abs/path.glb"}, ...]}
Part models are millimetres with Z up; the glTF importer turns them Y up, so each is turned back.
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

CELL = 1.0
ROW = 1.3  # row pitch in cells: room for the label under each part
TILT = math.radians(48)


def _bounds(objects):
    low = Vector((math.inf,) * 3)
    high = Vector((-math.inf,) * 3)
    for obj in objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            low = Vector(map(min, low, world))
            high = Vector(map(max, high, world))
    return low, high


def _label(text, location, size):
    curve = bpy.data.curves.new("label", type="FONT")
    curve.body = text
    curve.size = size
    curve.align_x = "CENTER"
    obj = bpy.data.objects.new("label", curve)
    obj.location = location
    bpy.context.collection.objects.link(obj)
    mat = bpy.data.materials.get("label_ink")
    if mat is None:
        mat = bpy.data.materials.new("label_ink")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (0.03, 0.03, 0.035, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.9
    curve.materials.append(mat)
    return obj


def main():
    sheet_file, output = sys.argv[sys.argv.index("--") + 1 :][:2]
    engine = (sys.argv[sys.argv.index("--") + 1 :] + [None, None, "eevee"])[2]
    sheet = json.loads(Path(sheet_file).read_text())
    columns = int(sheet.get("columns", 10))
    items = sheet["items"]
    rows = math.ceil(len(items) / columns)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    for index, item in enumerate(items):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=item["glb"])
        objects = [obj for obj in bpy.data.objects if obj not in before]
        root = bpy.data.objects.new("part", None)
        bpy.context.collection.objects.link(root)
        for obj in objects:
            if obj.parent is None:
                obj.parent = root
        # Back to Z up, then a quarter turn so each part shows two faces to the camera.
        root.rotation_euler = (math.radians(-90), 0, 0)
        bpy.context.view_layer.update()
        turn = bpy.data.objects.new("turn", None)
        bpy.context.collection.objects.link(turn)
        root.parent = turn
        turn.rotation_euler = (0, 0, math.radians(-35))
        root = turn
        bpy.context.view_layer.update()
        low, high = _bounds(objects)
        size = max(high - low) or 1.0
        scale = 0.72 * CELL / size
        column, row = index % columns, index // columns
        centre = (low + high) / 2
        root.scale = (scale,) * 3
        bpy.context.view_layer.update()
        low, high = _bounds(objects)
        centre = (low + high) / 2
        target = Vector((column * CELL, -row * CELL * ROW, 0.0))
        root.location += Vector((target.x - centre.x, target.y - centre.y, -low.z))
        _label(item["label"], (target.x, target.y - CELL * 0.5, 0.002), CELL * 0.07)

    floor = bpy.data.meshes.new("floor")
    span_x, span_y = columns * CELL, rows * CELL * ROW
    floor.from_pydata(
        [(-CELL, CELL, -0.001), (span_x, CELL, -0.001), (span_x, -span_y, -0.001), (-CELL, -span_y, -0.001)], [], [(0, 1, 2, 3)]
    )
    floor_obj = bpy.data.objects.new("floor", floor)
    bpy.context.collection.objects.link(floor_obj)
    floor_mat = bpy.data.materials.new("floor")
    floor_mat.use_nodes = True
    floor_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.78, 0.79, 0.8, 1.0)
    floor.materials.append(floor_mat)

    # Orthographic camera tilted about X: the grid's depth shrinks by cos(tilt) on screen.
    camera_data = bpy.data.cameras.new("camera")
    camera_data.type = "ORTHO"
    width = span_x
    height = span_y * math.cos(TILT) + CELL * 0.8
    camera_data.ortho_scale = max(width, height) * 1.01
    camera = bpy.data.objects.new("camera", camera_data)
    bpy.context.collection.objects.link(camera)
    middle = Vector(((columns - 1) * CELL / 2, -span_y / 2 + CELL * 0.45, 0.25 * CELL))
    camera.location = middle + Vector((0, -math.sin(TILT) * 60, math.cos(TILT) * 60))
    camera.rotation_euler = (TILT, 0, 0)
    scene.camera = camera
    cell_px = int(sheet.get("cell_px", 300))
    scene.render.resolution_x = int(columns * cell_px)
    scene.render.resolution_y = int(columns * cell_px * height / width)
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", type="SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(35), math.radians(-25), math.radians(20))
    bpy.context.collection.objects.link(sun)
    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.9, 0.9, 0.9, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.9
    scene.world = world

    scene.render.resolution_percentage = 100
    if engine == "workbench":
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_shadows = True
    else:
        scene.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items} else "BLENDER_EEVEE_NEXT"
        try:
            scene.eevee.taa_render_samples = 16
        except AttributeError:
            pass
    scene.view_settings.view_transform = "Standard"
    scene.render.filepath = output
    bpy.ops.render.render(write_still=True)


main()
