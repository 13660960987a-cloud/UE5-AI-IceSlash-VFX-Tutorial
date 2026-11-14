"""Build one frost-mist fan per slash blade (NobleShore).

For every SM_SlashArc_0N in the blade FBX the blade's outer edge (UV V=0) and inner edge (V=1)
are read per column along the slash (UV U). The mist strip starts slightly outside the inner
half of the blade and extends inward toward the arc centre by MIST_DEPTH x blade width, so it
fills the area the blade swept, like the grey frost haze in the reference video.

UV of the mist: U = same as the blade (0 = start of the swing, 1 = tip), V = 0 at the blade
side, 1 at the deep inner edge. Geometry is written in centimetres (the input is the cm-baked
blade FBX) and exported the same way.

Usage: Blender -b --factory-startup -P build_mist_meshes.py -- <blades_cm.fbx> <out.fbx>
"""
import sys
from collections import defaultdict

import bmesh
import bpy
from mathutils import Vector

MIST_DEPTH = 1.8      # how far inward the mist reaches, in blade widths
START_V = 0.45        # where the mist starts inside the blade (0 outer edge .. 1 inner edge)
ROWS = 8              # rows across the mist strip

args = sys.argv[sys.argv.index("--") + 1:]
src, dst = args[0], args[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)
blades = sorted((o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith("SM_SlashArc_")),
                key=lambda o: o.name)


def columns(obj):
    """Return [(u, outer_point, inner_point)] sorted by u, in object space."""
    me = obj.data
    uv = me.uv_layers.active.data
    by_u = defaultdict(list)
    for loop in me.loops:
        u, v = uv[loop.index].uv
        by_u[round(u, 4)].append((v, me.vertices[loop.vertex_index].co.copy()))
    cols = []
    for u, pts in by_u.items():
        pts.sort(key=lambda p: p[0])
        cols.append((u, pts[0][1], pts[-1][1], pts[0][0], pts[-1][0]))
    cols.sort(key=lambda c: c[0])
    return cols


made = []
for blade in blades:
    cols = columns(blade)
    # The material's V may be flipped relative to geometry; detect which end is outer (farther
    # from the column centroid of the whole blade = farther from the arc centre).
    centre = sum((c[1] + c[2] for c in cols), Vector()) / (2 * len(cols))
    flip = sum((c[2] - centre).length - (c[1] - centre).length for c in cols) > 0
    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")
    grid = []
    for u, p_lo, p_hi, v_lo, v_hi in cols:
        outer, inner = (p_hi, p_lo) if flip else (p_lo, p_hi)
        width = (inner - outer).length
        inward = (inner - outer).normalized()
        start = outer.lerp(inner, START_V)
        end = inner + inward * width * MIST_DEPTH
        row = []
        for r in range(ROWS + 1):
            t = r / ROWS
            row.append((bm.verts.new(start.lerp(end, t)), u, t))
        grid.append(row)
    for a, b in zip(grid[:-1], grid[1:]):
        for r in range(ROWS):
            quad = (a[r], b[r], b[r + 1], a[r + 1])
            face = bm.faces.new([q[0] for q in quad])
            for loop, q in zip(face.loops, quad):
                loop[uv_layer].uv = (q[1], 1.0 - q[2])   # FBX->UE flips V: store 1-V so UE sees V
    name = blade.name.replace("SM_SlashArc_", "SM_SlashMist_")
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    made.append(obj)
    print("MIST", name, "columns", len(cols), "flip", flip, "dims", [round(d, 1) for d in obj.dimensions])

bpy.ops.object.select_all(action="DESELECT")
for o in made:
    o.select_set(True)
bpy.context.view_layer.objects.active = made[0]
bpy.ops.export_scene.fbx(filepath=dst, use_selection=True, object_types={"MESH"}, global_scale=1.0,
                         apply_unit_scale=False, apply_scale_options="FBX_SCALE_NONE",
                         axis_forward="-Y", axis_up="Z", bake_space_transform=False, mesh_smooth_type="OFF")
print("EXPORTED", dst)
