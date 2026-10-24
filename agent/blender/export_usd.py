"""Export the same assembly as the studio render, without cameras or a floor."""

import json
import math
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).parent))
import studio


def main():
    stl, output, spec_file = sys.argv[sys.argv.index("--") + 1 :]
    spec = json.loads(Path(spec_file).read_text())
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.scale_length = 1.0
    if spec.get("glb"):
        # Use the actual FreeCAD assembly, including its camera, canopy and hardware.
        studio._hero(spec["glb"])
        imported = list(bpy.context.scene.objects)
        for item in spec["parts"]:
            category, index = item["category"], item["index"]
            matches = sorted((o for o in imported if o.name == category or o.name.startswith(category + "_")), key=lambda o: o.name)
            group = bpy.data.objects.new(item["name"], None)
            bpy.context.collection.objects.link(group)
            group["mass_kg"] = item["mass_kg"]
            if index < len(matches):
                obj = matches[index]
                matrix = obj.matrix_world.copy()
                obj.parent = group
                obj.matrix_world = matrix
        # Keep the upload self-contained: use preview colours without external textures.
        for material in bpy.data.materials:
            if material.use_nodes:
                for node in list(material.node_tree.nodes):
                    if node.type == "TEX_IMAGE":
                        material.node_tree.nodes.remove(node)
        bpy.ops.wm.usd_export(filepath=output, root_prim_path="/Geometry", export_custom_properties=True)
        return
    mats = studio._materials()
    top = spec["thickness_mm"] * studio.MM
    arm = spec["arm_mm"] * studio.MM

    def part(name, mass, build):
        before = set(bpy.data.objects)
        build()
        objects = set(bpy.data.objects) - before
        group = bpy.data.objects.new(name, None)
        bpy.context.collection.objects.link(group)
        group["mass_kg"] = mass
        for obj in objects:
            obj.parent = group
        return group, objects

    def frame():
        obj = studio._frame(stl, mats["frame"])
        obj.rotation_euler[2] = math.radians(45)

    for item in spec["parts"]:
        category = item["category"]
        index = item["index"]
        if category == "frame":
            build = frame
        elif category in ("motor", "propeller"):
            # Split the studio helper's motor and propeller into separate mass groups.
            if category == "propeller":
                continue
            angle = math.radians(45 + index * 90)
            position = (arm * math.cos(angle), arm * math.sin(angle), top)
            build = lambda p=position, i=index: studio._motor(
                mats, p, spin=i % 2 == 0, prop_radius=spec["prop_mm"] * studio.MM / 2
            )
        elif category == "battery":
            build = lambda: studio._battery(mats, top, [v * studio.MM for v in spec["battery_mm"]])
        elif category == "flight_controller":
            build = lambda: studio._flight_controller(mats, top)
        else:
            # Optional accessories contribute mass; the legacy frame-only model has no mesh for them.
            build = lambda: None
        _, objects = part(item["name"], item["mass_kg"], build)
        if category == "motor":
            prop = next(p for p in spec["parts"] if p["category"] == "propeller" and p["index"] == index)
            group = bpy.data.objects.new(prop["name"], None)
            bpy.context.collection.objects.link(group)
            group["mass_kg"] = prop["mass_kg"]
            for obj in objects:
                if obj.type == "MESH" and mats["prop"] in list(obj.data.materials):
                    obj.parent = group
    bpy.ops.wm.usd_export(filepath=output, root_prim_path="/Geometry", export_custom_properties=True)


if __name__ == "__main__":
    main()
