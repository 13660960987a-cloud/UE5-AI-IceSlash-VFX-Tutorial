"""Turn the processed Tripo ice burst the right way up (NobleShore).

process_tripo_burst_v3.py delivered the six parts upside down (snow base on top, crystals
pointing down). This rotates everything 180 degrees about X (a rotation, so winding and
normals stay valid), puts the lowest point on z = 0, flat-shades the crystals and exports
with the project's cm conventions.

Usage: Blender -b --factory-startup -P fix_tripo_burst_up.py -- <in_cm.fbx> <out_cm.fbx> <parts.json>
"""
import json
import math
import sys

import bpy
from mathutils import Matrix, Vector

src, dst, parts_path = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)
objs = sorted((o for o in bpy.context.scene.objects if o.type == "MESH"), key=lambda o: o.name)

rot = Matrix.Rotation(math.pi, 4, "X")
zmin = 1e9
for o in objs:
    o.data.transform(rot @ o.matrix_world)      # bake world transform + flip into the vertices
    o.matrix_world = Matrix.Identity(4)
    zmin = min(zmin, min(v.co.z for v in o.data.vertices))
parts = []
for o in objs:
    o.data.transform(Matrix.Translation(Vector((0, 0, -zmin))))
    for p in o.data.polygons:
        p.use_smooth = o.name.endswith("_Base")  # snow base stays smooth, crystals are faceted
    o.data.update()
    xs = [v.co for v in o.data.vertices]
    lo = [min(c[i] for c in xs) for i in range(3)]
    hi = [max(c[i] for c in xs) for i in range(3)]
    parts.append({"name": o.name, "faces": len(o.data.polygons), "verts": len(o.data.vertices),
                  "size_cm": [round(hi[i] - lo[i], 1) for i in range(3)],
                  "z_range_cm": [round(lo[2], 1), round(hi[2], 1)]})
    print("PART", o.name, parts[-1]["size_cm"], parts[-1]["z_range_cm"])
json.dump(parts, open(parts_path, "w"), indent=1)

bpy.ops.object.select_all(action="DESELECT")
for o in objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.export_scene.fbx(filepath=dst, use_selection=True, object_types={"MESH"}, global_scale=1.0,
                         apply_unit_scale=False, apply_scale_options="FBX_SCALE_NONE",
                         axis_forward="-Y", axis_up="Z", bake_space_transform=False, mesh_smooth_type="FACE")
print("EXPORTED", dst)
