"""Re-export an FBX with geometry baked to centimetres (x100), keeping each object's pivot.

The original exports used apply_scale_options='FBX_SCALE_ALL', which stores the metre->cm factor in
the node transforms; Interchange's static-mesh path drops it, so meshes arrived 100x too small.
Here every object's location is multiplied by 100 and its mesh data scaled by 100 about its own
origin, then exported with FBX_SCALE_NONE so the vertices themselves are in centimetres.

Usage: Blender -b --factory-startup -P rescale_fbx_cm.py -- <in.fbx> <out.fbx>
"""
import sys

import bpy
import mathutils

args = sys.argv[sys.argv.index("--") + 1:]
src, dst = args[0], args[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]

# Undo the importer's 0.01 object scale (if any) so each object is unit-scaled, then bake x100.
for o in meshes:
    o.data.transform(mathutils.Matrix.Diagonal((o.scale.x * 100.0, o.scale.y * 100.0, o.scale.z * 100.0, 1.0)))
    o.location = o.location * 100.0
    o.scale = (1.0, 1.0, 1.0)

bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]

bpy.ops.export_scene.fbx(
    filepath=dst,
    use_selection=True,
    object_types={"MESH"},
    global_scale=1.0,
    apply_unit_scale=False,
    apply_scale_options="FBX_SCALE_NONE",
    axis_forward="-Y",
    axis_up="Z",
    bake_space_transform=False,
    mesh_smooth_type="OFF",
)
for o in meshes:
    dims = [round(d, 1) for d in o.dimensions]
    print("RESCALED", o.name, "loc", [round(v, 1) for v in o.location], "dims_cm", dims)
