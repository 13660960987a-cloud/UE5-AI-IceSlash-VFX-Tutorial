"""Rebuild ALL IceSlash arc sheets as 100% FLAT 2D planar sword-cut meshes (zero cone/potato-chip bend!):
  1. Saved/VFX/SlashSheets_v7_ue.fbx        (SM_SlashArc_01..05, flat planar crescent sheets)
  2. SourceAssets/SlashMist/SlashMist_v1_cm.fbx (SM_SlashMist_01..05, flat planar inner frost fans)
  3. Saved/VFX/SlashOuterGlow_v1_ue.fbx     (SM_SlashOuterGlow_01..05, flat narrow outer-rim emissive strips)
  4. Saved/VFX/tutorial_mesh_01_main_arc.png & tutorial_mesh_02_outer_strip_stack.png (3D wireframe + flat plane diagrams)

Root cause fixed:
  Previously, build_blade_sheets.py took inward = normalize(inner - outer) from the raw sword trace,
  where the hilt sat lower than the blade tip (~22 deg cone angle). Extrapolating 165 cm inward turned
  every slash sheet into a giant 3D cone/lampshade (+/- 94 cm out-of-plane warp!).
  Real stylized sword slashes lie on a STRICTLY FLAT 2D PLANE (out-of-plane = 0.000 cm), and 3D slash
  angles come solely from rotating that flat plane.
"""
import json
import math
import os
from collections import defaultdict

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Vector

PROJECT_DIR = "/Users/mengmeile/Downloads/lianxi/m"
SRC_ARC_UE_FBX = os.path.join(PROJECT_DIR, "Saved/VFX/SlashArcs_v5_ue.fbx")
PAINTED_JSON = os.path.join(PROJECT_DIR, "SourceAssets/SlashTextures/T_SlashBlade_Painted.json")

OUT_SHEETS_FBX = os.path.join(PROJECT_DIR, "Saved/VFX/SlashSheets_v7_ue.fbx")
OUT_MIST_FBX = os.path.join(PROJECT_DIR, "SourceAssets/SlashMist/SlashMist_v1_cm.fbx")
OUT_GLOW_FBX = os.path.join(PROJECT_DIR, "Saved/VFX/SlashOuterGlow_v1_ue.fbx")
OUT_CANON_JSON = os.path.join(PROJECT_DIR, "Tools/IceSlash/data/flat_slash_canon.json")

TUT_MAIN_ARC_PNG = os.path.join(PROJECT_DIR, "Saved/VFX/tutorial_mesh_01_main_arc.png")
TUT_OUTER_STRIP_PNG = os.path.join(PROJECT_DIR, "Saved/VFX/tutorial_mesh_02_outer_strip_stack.png")

ROWS_MAIN = 24
ROWS_GLOW = 12
ROWS_MIST = 10
EXT_HEAD_PX, EXT_TAIL_PX, EXT_STEPS = 90.0, 56.0, 4

# Narrow outer-rim emissive strip range around d=0 (exact golden rim spine):
# -155 px (~ -62 cm outward for rich golden Bloom aura) to +95 px (~ +38 cm inward, covering golden rim without touching cyan curls)
GLOW_D_OUTER_PX = -155.0
GLOW_D_INNER_PX = 95.0


def polyline_length(pts):
    return sum(((pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5
               for i in range(len(pts) - 1))


def unit2(a, b):
    dx, dy = a[0] - b[0], a[1] - b[1]
    ln = max((dx * dx + dy * dy) ** 0.5, 1e-6)
    return dx / ln, dy / ln


def extract_flat_rim_spec(blade_obj, force_horizontal=False):
    """Extract outer rim polyline projected onto a strictly flat 2D plane + radial inward vectors in that plane."""
    me = blade_obj.data
    uv = me.uv_layers.active.data
    by_u = defaultdict(list)
    for loop in me.loops:
        u, v = uv[loop.index].uv
        by_u[round(u, 4)].append((v, me.vertices[loop.vertex_index].co.copy()))
    cols = []
    for u in sorted(by_u):
        pts = sorted(by_u[u], key=lambda p: p[0])
        cols.append((pts[0][1], pts[-1][1]))  # (outer, inner)

    outer_raw = np.array([[c[0].x, c[0].y, c[0].z] for c in cols], dtype=np.float64)
    c0 = outer_raw.mean(axis=0)

    if force_horizontal:
        # Pure horizontal XY plane at Z = mean outer Z (~95 cm chest height; extent.z = 0.000 cm!)
        z_flat = float(round(c0[2], 2))
        c_plane = np.array([c0[0], c0[1], z_flat], dtype=np.float64)
        e1 = np.array([1.0, 0.0, 0.0], dtype=np.float64)
        e2 = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        n_plane = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    else:
        _, _, vt = np.linalg.svd(outer_raw - c0, full_matrices=False)
        c_plane = c0
        e1, e2, n_plane = vt[0], vt[1], vt[2]

    # Project outer points strictly onto the flat 2D plane and fit an exact 2D circle for silky-smooth inward normals
    rel = outer_raw - c_plane
    p2 = np.column_stack([rel @ e1, rel @ e2])
    A = np.column_stack([2.0 * p2[:, 0], 2.0 * p2[:, 1], np.ones(len(p2))])
    b = p2[:, 0] ** 2 + p2[:, 1] ** 2
    sol, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    cx2, cy2 = float(sol[0]), float(sol[1])
    R_fit = float(math.sqrt(max(sol[2] + cx2 * cx2 + cy2 * cy2, 1.0)))
    center_3d = c_plane + cx2 * e1 + cy2 * e2

    # Snap outer points cleanly onto the fitted 2D circle in the flat plane so the silhouette is a crisp circular arc
    outer_flat = []
    inward_flat = []
    for x2, y2 in p2:
        dx, dy = x2 - cx2, y2 - cy2
        ang = math.atan2(dy, dx)
        rx, ry = cx2 + R_fit * math.cos(ang), cy2 + R_fit * math.sin(ang)
        p3 = c_plane + rx * e1 + ry * e2
        # Inward vector points strictly towards center_3d INSIDE the flat plane!
        inw = center_3d - p3
        inw = inw / max(np.linalg.norm(inw), 1e-8)
        outer_flat.append(Vector((float(p3[0]), float(p3[1]), float(p3[2]))))
        inward_flat.append(Vector((float(inw[0]), float(inw[1]), float(inw[2]))))

    return outer_flat, inward_flat, Vector((float(center_3d[0]), float(center_3d[1]), float(center_3d[2]))), R_fit, n_plane


def export_fbx_objects(objs, filepath):
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 0.01
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.fbx(
        filepath=filepath,
        use_selection=True,
        object_types={"MESH"},
        global_scale=1.0,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        axis_forward="-Y",
        axis_up="Z",
        bake_space_transform=False,
        mesh_smooth_type="OFF",
    )
    print("EXPORTED", filepath)


def build_all_flat_meshes():
    info = json.load(open(PAINTED_JSON))
    W, H = float(info["width"]), float(info["height"])
    rim_px = info["rim_points_px"]
    nrm_px = info["rim_normals"]
    depth_px = float(info["depth_px"])
    glow_px = float(info["glow_px"]) + 64.0
    rim_len_px = polyline_length(rim_px)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=SRC_ARC_UE_FBX)
    src_blades = sorted(
        (o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith("SM_SlashArc_")),
        key=lambda o: o.name,
    )

    main_objs = []
    glow_objs = []
    mist_objs = []
    canon_meta = {}

    for blade in src_blades:
        orig_name = blade.name
        blade.name = "_src_" + orig_name
        blade.data.name = "_src_me_" + orig_name
        idx_str = orig_name.split("_")[-1]
        is_first = idx_str == "01"
        outer, inward, center_3d, R_fit, n_plane = extract_flat_rim_spec(blade, force_horizontal=is_first)

        seg = [(outer[i + 1] - outer[i]).length for i in range(len(outer) - 1)]
        cum = [0.0]
        for l in seg:
            cum.append(cum[-1] + l)
        rim_len_3d = cum[-1]
        k = rim_len_3d / rim_len_px  # cm per painted pixel
        # Clamp inward reach so d*k never exceeds 0.86 * R_fit (prevents inner-ring self-intersection!)
        max_inward_cm = 0.86 * R_fit

        def rim3d(s):
            target = s * rim_len_3d
            for i in range(len(seg)):
                if cum[i + 1] >= target or i == len(seg) - 1:
                    t = 0.0 if seg[i] == 0 else (target - cum[i]) / seg[i]
                    t = min(max(t, 0.0), 1.0)
                    p = outer[i].lerp(outer[i + 1], t)
                    # Project onto circle around center_3d to stay 100% circular & flat
                    radial = p - center_3d
                    n = (-radial).normalized()
                    p_circ = center_3d - n * R_fit
                    return p_circ, n
            return outer[-1], inward[-1]

        columns = len(rim_px)
        total_cols = EXT_STEPS + columns + EXT_STEPS
        specs = []  # (p3, n3, px, npx, sweep_s, u_strip)

        p_tail, n_tail = rim3d(0.0)
        t3_tail = (p_tail - rim3d(0.02)[0]).normalized()
        t2_tail = unit2(rim_px[0], rim_px[3])
        for j in range(EXT_STEPS, 0, -1):
            d_ext = EXT_TAIL_PX * j / EXT_STEPS
            u_st = (EXT_STEPS - j) / float(total_cols - 1)
            p_ext = p_tail + t3_tail * (d_ext * k)
            n_ext = (center_3d - p_ext).normalized()
            specs.append((
                p_ext, n_ext,
                (rim_px[0][0] + t2_tail[0] * d_ext, rim_px[0][1] + t2_tail[1] * d_ext),
                nrm_px[0], 0.0, u_st,
            ))

        for ci in range(columns):
            sw = ci / float(columns - 1)
            p3, n3 = rim3d(sw)
            u_st = (EXT_STEPS + ci) / float(total_cols - 1)
            specs.append((p3, n3, rim_px[ci], nrm_px[ci], sw, u_st))

        p_head, n_head = rim3d(1.0)
        t3_head = (p_head - rim3d(0.98)[0]).normalized()
        t2_head = unit2(rim_px[-1], rim_px[-4])
        for j in range(1, EXT_STEPS + 1):
            d_ext = EXT_HEAD_PX * j / EXT_STEPS
            u_st = (EXT_STEPS + columns - 1 + j) / float(total_cols - 1)
            p_ext = p_head + t3_head * (d_ext * k)
            n_ext = (center_3d - p_ext).normalized()
            specs.append((
                p_ext, n_ext,
                (rim_px[-1][0] + t2_head[0] * d_ext, rim_px[-1][1] + t2_head[1] * d_ext),
                nrm_px[-1], 1.0, u_st,
            ))

        # --- 1) Main Flat Crescent Sheet: SM_SlashArc_0N ---
        bm_main = bmesh.new()
        uv0_m = bm_main.loops.layers.uv.new("UVMap")
        uv1_m = bm_main.loops.layers.uv.new("UVSweep")
        grid_m = []
        for p3, n3, px, npx, s, _u_st in specs:
            row = []
            for ri in range(ROWS_MAIN + 1):
                f = ri / float(ROWS_MAIN)
                d_px = -glow_px + f * (glow_px + depth_px)
                d_cm = min(d_px * k, max_inward_cm)
                vert = bm_main.verts.new(p3 + n3 * d_cm)
                tx = (px[0] + npx[0] * d_px) / W
                ty = (px[1] + npx[1] * d_px) / H
                row.append((vert, (tx, 1.0 - ty), (s, 1.0 - f)))
            grid_m.append(row)
        for a, b in zip(grid_m[:-1], grid_m[1:]):
            for ri in range(ROWS_MAIN):
                quad = (a[ri], b[ri], b[ri + 1], a[ri + 1])
                face = bm_main.faces.new([q[0] for q in quad])
                for loop, q in zip(face.loops, quad):
                    loop[uv0_m].uv = q[1]
                    loop[uv1_m].uv = q[2]
        me_main = bpy.data.meshes.new(orig_name)
        bm_main.to_mesh(me_main)
        bm_main.free()
        obj_main = bpy.data.objects.new(orig_name, me_main)
        bpy.context.scene.collection.objects.link(obj_main)
        main_objs.append(obj_main)

        # --- 2) Narrow Flat Outer-Rim Emissive Strip: SM_SlashOuterGlow_0N ---
        glow_name = f"SM_SlashOuterGlow_{idx_str}"
        bm_glow = bmesh.new()
        uv0_g = bm_glow.loops.layers.uv.new("UVMap")
        uv1_g = bm_glow.loops.layers.uv.new("UVSweep")
        grid_g = []
        for p3, n3, _px, _npx, s, u_st in specs:
            row = []
            for ri in range(ROWS_GLOW + 1):
                f = ri / float(ROWS_GLOW)
                d_px = GLOW_D_OUTER_PX + f * (GLOW_D_INNER_PX - GLOW_D_OUTER_PX)
                vert = bm_glow.verts.new(p3 + n3 * (d_px * k))
                row.append((vert, (u_st, 1.0 - f), (s, 1.0 - f)))
            grid_g.append(row)
        for a, b in zip(grid_g[:-1], grid_g[1:]):
            for ri in range(ROWS_GLOW):
                quad = (a[ri], b[ri], b[ri + 1], a[ri + 1])
                face = bm_glow.faces.new([q[0] for q in quad])
                for loop, q in zip(face.loops, quad):
                    loop[uv0_g].uv = q[1]
                    loop[uv1_g].uv = q[2]
        me_glow = bpy.data.meshes.new(glow_name)
        bm_glow.to_mesh(me_glow)
        bm_glow.free()
        obj_glow = bpy.data.objects.new(glow_name, me_glow)
        bpy.context.scene.collection.objects.link(obj_glow)
        glow_objs.append(obj_glow)

        # --- 3) Flat Inner Mist Fan: SM_SlashMist_0N ---
        mist_name = f"SM_SlashMist_{idx_str}"
        bm_mist = bmesh.new()
        uv0_ms = bm_mist.loops.layers.uv.new("UVMap")
        grid_ms = []
        for ci in range(len(outer)):
            u_m = ci / float(len(outer) - 1)
            p_out = outer[ci]
            inw = inward[ci]
            start_cm = 35.0
            end_cm = min(0.84 * R_fit, 215.0)
            row = []
            for ri in range(ROWS_MIST + 1):
                t = ri / float(ROWS_MIST)
                d_cm = start_cm + t * (end_cm - start_cm)
                row.append((bm_mist.verts.new(p_out + inw * d_cm), u_m, t))
            grid_ms.append(row)
        for a, b in zip(grid_ms[:-1], grid_ms[1:]):
            for ri in range(ROWS_MIST):
                quad = (a[ri], b[ri], b[ri + 1], a[ri + 1])
                face = bm_mist.faces.new([q[0] for q in quad])
                for loop, q in zip(face.loops, quad):
                    loop[uv0_ms].uv = (q[1], 1.0 - q[2])
        me_mist = bpy.data.meshes.new(mist_name)
        bm_mist.to_mesh(me_mist)
        bm_mist.free()
        obj_mist = bpy.data.objects.new(mist_name, me_mist)
        bpy.context.scene.collection.objects.link(obj_mist)
        mist_objs.append(obj_mist)

        # Verify machine-precision flatness via SVD!
        arr = np.array([[v.co.x, v.co.y, v.co.z] for v in me_main.vertices])
        _, sv, _ = np.linalg.svd(arr - arr.mean(axis=0), full_matrices=False)
        # Note Blender->UE FBX (-Y forward, Z up): UE_X = Blender_X, UE_Y = -Blender_Y, UE_Z = Blender_Z
        p_tail_ue = (float(p_tail.x), float(-p_tail.y), float(p_tail.z))
        p_mid, _ = rim3d(0.5)
        p_mid_ue = (float(p_mid.x), float(-p_mid.y), float(p_mid.z))
        p_head_ue = (float(p_head.x), float(-p_head.y), float(p_head.z))
        c_ue = (float(center_3d.x), float(-center_3d.y), float(center_3d.z))

        canon_meta[orig_name] = {
            "R_cm": round(R_fit, 3),
            "center_ue_cm": [round(x, 3) for x in c_ue],
            "tail_ue_cm": [round(x, 3) for x in p_tail_ue],
            "belly_ue_cm": [round(x, 3) for x in p_mid_ue],
            "head_ue_cm": [round(x, 3) for x in p_head_ue],
            "svd_thickness_cm": round(float(sv[2]), 6),
        }
        print(
            f"FLAT {orig_name}: R={R_fit:.2f}cm center_ue={[round(x,2) for x in c_ue]} "
            f"svd_out_of_plane={sv[2]:.6f}cm glow_strip_w={(GLOW_D_INNER_PX - GLOW_D_OUTER_PX)*k:.1f}cm"
        )

    # Remove original imported source meshes before exporting
    for b in src_blades:
        bpy.data.objects.remove(b, do_unlink=True)

    export_fbx_objects(main_objs, OUT_SHEETS_FBX)
    export_fbx_objects(mist_objs, OUT_MIST_FBX)
    export_fbx_objects(glow_objs, OUT_GLOW_FBX)

    single_dir = os.path.join(PROJECT_DIR, "Saved/VFX/SingleMeshes")
    os.makedirs(single_dir, exist_ok=True)
    for obj in main_objs + mist_objs + glow_objs:
        export_fbx_objects([obj], os.path.join(single_dir, f"{obj.name}.fbx"))

    with open(OUT_CANON_JSON, "w") as f:
        json.dump(canon_meta, f, indent=2)
    print("WROTE", OUT_CANON_JSON)


def make_emission_mat(name, color_rgba, strength=1.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = color_rgba
    em.inputs["Strength"].default_value = strength
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return mat


def make_principled_mat(name, base_rgba, rough=0.45, metal=0.1, em_rgba=None, em_str=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = base_rgba
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if em_rgba is not None and "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = em_rgba
        bsdf.inputs["Emission Strength"].default_value = em_str
    return mat


def add_wireframe_clone(obj, wire_mat, thickness=1.0, z_lift=0.25):
    dup = obj.copy()
    dup.data = obj.data.copy()
    dup.location.z += z_lift
    bpy.context.collection.objects.link(dup)
    dup.data.materials.clear()
    dup.data.materials.append(wire_mat)
    mod = dup.modifiers.new("Wire", type="WIREFRAME")
    mod.thickness = thickness
    mod.use_replace = True
    mod.use_even_offset = True
    return dup


def render_tutorial_mesh_diagrams():
    """Render two clean 3D studio views (3/4 angle so viewers clearly see BOTH the circular crescent shape AND that Z=0 is 100% flat!)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    avail = {e.identifier for e in scene.render.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in avail else "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1200

    world = bpy.data.worlds.new("StudioWorld")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.016, 0.022, 0.038, 1.0)
    bg.inputs[1].default_value = 1.0

    bpy.ops.import_scene.fbx(filepath=OUT_SHEETS_FBX)
    for o in list(bpy.context.scene.objects):
        if o.name != "SM_SlashArc_01":
            bpy.data.objects.remove(o, do_unlink=True)
    main_arc = bpy.data.objects["SM_SlashArc_01"]

    bpy.ops.import_scene.fbx(filepath=OUT_GLOW_FBX)
    for o in list(bpy.context.scene.objects):
        if o.name.startswith("SM_SlashOuterGlow_") and o.name != "SM_SlashOuterGlow_01":
            bpy.data.objects.remove(o, do_unlink=True)
    outer_strip = bpy.data.objects["SM_SlashOuterGlow_01"]

    # FBX exported with scale_length=0.01 imports into Blender's 1.0m studio scene at 0.01 scale (meters);
    # scale vertices by 100 so studio units match centimetres (grid = 760 cm, camera ~ 500 cm)!
    for obj in (main_arc, outer_strip):
        for v in obj.data.vertices:
            v.co *= 100.0
        obj.data.update()

    # Recenter both on XY and put Z=0 right on the reference plane!
    vs = [main_arc.matrix_world @ v.co for v in main_arc.data.vertices]
    cx = 0.5 * (min(v.x for v in vs) + max(v.x for v in vs))
    cy = 0.5 * (min(v.y for v in vs) + max(v.y for v in vs))
    cz = 0.5 * (min(v.z for v in vs) + max(v.z for v in vs))
    for obj in (main_arc, outer_strip):
        obj.location -= Vector((cx, cy, cz))

    # Flat reference grid right below Z=0 (-3 cm) so the viewer visually sees it lies dead-flat on the plane!
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=14, y_subdivisions=14, size=760.0, location=(0.0, 0.0, -3.0))
    grid_obj = bpy.context.active_object
    grid_obj.data.materials.append(make_emission_mat("GridWire", (0.09, 0.16, 0.28, 1.0), 1.0))
    gmod = grid_obj.modifiers.new("GridWire", type="WIREFRAME")
    gmod.thickness = 0.9
    gmod.use_replace = True

    mat_arc_clay = make_principled_mat(
        "ArcClay", (0.14, 0.38, 0.66, 1.0), rough=0.36, metal=0.08,
        em_rgba=(0.06, 0.24, 0.45, 1.0), em_str=0.45,
    )
    mat_arc_wire = make_emission_mat("ArcWire", (0.48, 0.90, 1.0, 1.0), 2.2)
    mat_strip_clay = make_principled_mat(
        "StripGold", (1.0, 0.68, 0.14, 1.0), rough=0.24, metal=0.15,
        em_rgba=(1.0, 0.62, 0.12, 1.0), em_str=2.6,
    )
    mat_strip_wire = make_emission_mat("StripWire", (1.0, 0.96, 0.72, 1.0), 3.2)

    main_arc.data.materials.clear()
    main_arc.data.materials.append(mat_arc_clay)
    arc_wire_obj = add_wireframe_clone(main_arc, mat_arc_wire, thickness=1.15, z_lift=0.25)

    outer_strip.data.materials.clear()
    outer_strip.data.materials.append(mat_strip_clay)
    # Tiny +5 cm lift ONLY in this exploded tutorial diagram so both flat sheets' quad grids are clearly distinguishable
    outer_strip.location.z += 5.0
    strip_wire_obj = add_wireframe_clone(outer_strip, mat_strip_wire, thickness=1.25, z_lift=0.25)

    key_data = bpy.data.lights.new("KeyLight", type="SUN")
    key_data.energy = 3.5
    key_obj = bpy.data.objects.new("KeyLight", key_data)
    bpy.context.collection.objects.link(key_obj)
    key_obj.rotation_euler = Euler((math.radians(42), math.radians(-25), math.radians(30)), "XYZ")

    cam_data = bpy.data.cameras.new("DiagramCam")
    cam_data.lens = 38.0
    cam_data.clip_end = 5000.0
    cam_obj = bpy.data.objects.new("DiagramCam", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    scene.camera = cam_obj

    cam_pos = Vector((-425.0, -500.0, 435.0))
    target = Vector((18.0, -5.0, 0.0))
    cam_obj.location = cam_pos
    cam_obj.rotation_euler = (target - cam_pos).normalized().to_track_quat("-Z", "Y").to_euler()

    outer_strip.hide_render = True
    strip_wire_obj.hide_render = True
    scene.render.filepath = TUT_MAIN_ARC_PNG
    bpy.ops.render.render(write_still=True)
    print("RENDERED", TUT_MAIN_ARC_PNG)

    mat_arc_dim = make_principled_mat(
        "ArcDim", (0.08, 0.21, 0.38, 1.0), rough=0.48, metal=0.05,
        em_rgba=(0.03, 0.10, 0.22, 1.0), em_str=0.18,
    )
    mat_arc_wire_dim = make_emission_mat("ArcWireDim", (0.22, 0.48, 0.70, 1.0), 0.85)
    main_arc.data.materials[0] = mat_arc_dim
    arc_wire_obj.data.materials[0] = mat_arc_wire_dim
    outer_strip.hide_render = False
    strip_wire_obj.hide_render = False
    scene.render.filepath = TUT_OUTER_STRIP_PNG
    bpy.ops.render.render(write_still=True)
    print("RENDERED", TUT_OUTER_STRIP_PNG)


if __name__ == "__main__":
    build_all_flat_meshes()
    render_tutorial_mesh_diagrams()
