"""Build painted-crescent blade sheets that follow each v5 slash arc (NobleShore).

The painted crescent texture (T_SlashBlade_Painted.png) was measured by key_painted_blade.py:
its gold rim is a polyline (tail -> head) with inward normals, plus the inward depth and outward
glow extent in pixels. Every v5 blade gives a 3D rim path (its outer edge, U=0 start .. U=1 end)
and an inward direction (towards its inner edge). A strip mesh is laid along that path:

  column s (0 = start of the swing = painted tail, 1 = end = painted head)
  row d    (pixels, from -glow outside the rim to +depth inside)
  3D  = rim3D(s) + inward3D(s) * d * k      with k = 3D rim length / painted rim length (cm/px)
  UV0 = rimPx(s) + inwardPx(s) * d          -> samples the painting without distortion
  UV1 = (s, row fraction)                   -> drives the sweep reveal in the material

So the painting's proportions are kept; only the curvature follows the arc.

Usage: Blender -b --factory-startup -P build_blade_sheets.py -- <blades_cm.fbx> <painted.json> <out.fbx>
"""
import json
import sys
from collections import defaultdict

import bmesh
import bpy

ROWS = 24
# The rim polyline stops at the crescent's two tips, but the painted head (wave crest) and the
# glow reach past them: extend the sheet along the rim tangent beyond both ends so nothing is
# cut off flat. The extra columns keep the sweep value of their end (0 at the tail, 1 at the head).
EXT_HEAD_PX, EXT_TAIL_PX, EXT_STEPS = 90.0, 56.0, 4

args = sys.argv[sys.argv.index("--") + 1:]
src, info_path, dst = args
info = json.load(open(info_path))
W, H = float(info["width"]), float(info["height"])
rim_px = info["rim_points_px"]
nrm_px = info["rim_normals"]
depth_px = float(info["depth_px"])
glow_px = float(info["glow_px"]) + 64.0     # room for the baked emissive halo outside the rim


def polyline_length(pts):
    return sum(((pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5
               for i in range(len(pts) - 1))


def sample(seq, s):
    """Linear sample of a list of tuples/vectors at fraction s by index (seq is arc-length uniform)."""
    f = s * (len(seq) - 1)
    i = min(int(f), len(seq) - 2)
    t = f - i
    a, b = seq[i], seq[i + 1]
    return [a[k] * (1 - t) + b[k] * t for k in range(len(a))]


rim_len_px = polyline_length(rim_px)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)
blades = sorted((o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith("SM_SlashArc_")),
                key=lambda o: o.name)

made = []
for blade in blades:
    me = blade.data
    uv = me.uv_layers.active.data
    by_u = defaultdict(list)
    for loop in me.loops:
        u, v = uv[loop.index].uv
        by_u[round(u, 4)].append((v, me.vertices[loop.vertex_index].co.copy()))
    cols = []
    for u in sorted(by_u):
        pts = sorted(by_u[u], key=lambda p: p[0])
        cols.append((pts[0][1], pts[-1][1]))          # (outer edge, inner edge): Blender V=0 is outer
    # Resample the 3D rim by arc length so it lines up with the arc-length-uniform painted rim.
    outer = [c[0] for c in cols]
    inward = [(c[1] - c[0]).normalized() for c in cols]
    seg = [(outer[i + 1] - outer[i]).length for i in range(len(outer) - 1)]
    cum = [0.0]
    for l in seg:
        cum.append(cum[-1] + l)
    rim_len_3d = cum[-1]
    k = rim_len_3d / rim_len_px                         # cm per painted pixel

    def rim3d(s):
        target = s * rim_len_3d
        for i in range(len(seg)):
            if cum[i + 1] >= target or i == len(seg) - 1:
                t = 0.0 if seg[i] == 0 else (target - cum[i]) / seg[i]
                t = min(max(t, 0.0), 1.0)
                p = outer[i].lerp(outer[i + 1], t)
                n = inward[i].lerp(inward[i + 1], t).normalized()
                return p, n
        return outer[-1], inward[-1]

    columns = len(rim_px)

    def unit2(a, b):
        dx, dy = a[0] - b[0], a[1] - b[1]
        ln = (dx * dx + dy * dy) ** 0.5
        return dx / ln, dy / ln

    specs = []                                             # (p3, n3, px, npx, sweep)
    p_tail, n_tail = rim3d(0.0)
    t3_tail = (p_tail - rim3d(0.02)[0]).normalized()
    t2_tail = unit2(rim_px[0], rim_px[3])
    for j in range(EXT_STEPS, 0, -1):
        d = EXT_TAIL_PX * j / EXT_STEPS
        specs.append((p_tail + t3_tail * (d * k), n_tail,
                      (rim_px[0][0] + t2_tail[0] * d, rim_px[0][1] + t2_tail[1] * d), nrm_px[0], 0.0))
    for ci in range(columns):
        sw = ci / (columns - 1)
        p3, n3 = rim3d(sw)
        specs.append((p3, n3, rim_px[ci], nrm_px[ci], sw))
    p_head, n_head = rim3d(1.0)
    t3_head = (p_head - rim3d(0.98)[0]).normalized()
    t2_head = unit2(rim_px[-1], rim_px[-4])
    for j in range(1, EXT_STEPS + 1):
        d = EXT_HEAD_PX * j / EXT_STEPS
        specs.append((p_head + t3_head * (d * k), n_head,
                      (rim_px[-1][0] + t2_head[0] * d, rim_px[-1][1] + t2_head[1] * d), nrm_px[-1], 1.0))

    bm = bmesh.new()
    uv0 = bm.loops.layers.uv.new("UVMap")
    uv1 = bm.loops.layers.uv.new("UVSweep")
    grid = []
    for p3, n3, px, npx, s in specs:
        row = []
        for ri in range(ROWS + 1):
            f = ri / ROWS
            d = -glow_px + f * (glow_px + depth_px)
            vert = bm.verts.new(p3 + n3 * (d * k))
            tx = (px[0] + npx[0] * d) / W
            ty = (px[1] + npx[1] * d) / H
            row.append((vert, (tx, 1.0 - ty), (s, 1.0 - f)))   # FBX->UE flips V; store 1-V
        grid.append(row)
    for a, b in zip(grid[:-1], grid[1:]):
        for ri in range(ROWS):
            quad = (a[ri], b[ri], b[ri + 1], a[ri + 1])
            face = bm.faces.new([q[0] for q in quad])
            for loop, q in zip(face.loops, quad):
                loop[uv0].uv = q[1]
                loop[uv1].uv = q[2]
    sheet = bpy.data.meshes.new(blade.name)
    bm.to_mesh(sheet)
    bm.free()
    blade.data = sheet                                     # keep object name/transform, swap geometry
    made.append(blade)
    print("SHEET", blade.name, "rim3d_cm", round(rim_len_3d, 1), "k_cm_per_px", round(k, 4),
          "depth_cm", round(depth_px * k, 1), "dims", [round(x, 1) for x in blade.dimensions])

bpy.ops.object.select_all(action="DESELECT")
for o in made:
    o.select_set(True)
bpy.context.view_layer.objects.active = made[0]
bpy.ops.export_scene.fbx(filepath=dst, use_selection=True, object_types={"MESH"}, global_scale=1.0,
                         apply_unit_scale=False, apply_scale_options="FBX_SCALE_NONE",
                         axis_forward="-Y", axis_up="Z", bake_space_transform=False, mesh_smooth_type="OFF")
print("EXPORTED", dst)
