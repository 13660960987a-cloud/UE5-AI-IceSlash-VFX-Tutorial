"""Build narrow outer-rim emissive strip meshes (SM_SlashOuterGlow_01..05) aligned 1:1 with
SM_SlashArc_01..05's golden rim path, plus render clean 3D mesh + wireframe tutorial diagrams!

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P build_outer_glow_strip.py
"""
import json
import math
import os
from collections import defaultdict

import bmesh
import bpy
from mathutils import Euler, Vector

PROJECT_DIR = "/Users/mengmeile/Downloads/lianxi/m"
SRC_BLADES_FBX = os.path.join(PROJECT_DIR, "Saved/VFX/SlashArcs_v5_cm.fbx")
SHEETS_FBX = os.path.join(PROJECT_DIR, "Saved/VFX/SlashSheets_v7_ue.fbx")
PAINTED_JSON = os.path.join(PROJECT_DIR, "SourceAssets/SlashTextures/T_SlashBlade_Painted.json")
OUT_FBX = os.path.join(PROJECT_DIR, "Saved/VFX/SlashOuterGlow_v1_ue.fbx")

TUT_MAIN_ARC_PNG = os.path.join(PROJECT_DIR, "Saved/VFX/tutorial_mesh_01_main_arc.png")
TUT_OUTER_STRIP_PNG = os.path.join(PROJECT_DIR, "Saved/VFX/tutorial_mesh_02_outer_strip_stack.png")

ROWS = 12
EXT_HEAD_PX, EXT_TAIL_PX, EXT_STEPS = 90.0, 56.0, 4
# Narrow radial band hugging ONLY the golden outer rim (d=0 is exact golden rim spine):
# -105 px (~ -42 cm outward for Bloom halo) to +105 px (~ +42 cm inward, stopping before cyan curls!)
D_OUTER_PX = -105.0
D_INNER_PX = 105.0


def polyline_length(pts):
    return sum(((pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5
               for i in range(len(pts) - 1))


def unit2(a, b):
    dx, dy = a[0] - b[0], a[1] - b[1]
    ln = max((dx * dx + dy * dy) ** 0.5, 1e-6)
    return dx / ln, dy / ln


def build_outer_glow_fbx():
    info = json.load(open(PAINTED_JSON))
    rim_px = info["rim_points_px"]
    nrm_px = info["rim_normals"]
    rim_len_px = polyline_length(rim_px)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=SRC_BLADES_FBX)
    blades = sorted(
        (o for o in bpy.context.scene.objects if o.type == "MESH" and o.name.startswith("SM_SlashArc_")),
        key=lambda o: o.name,
    )

    made = []
    for blade in blades:
        idx_suffix = blade.name.split("_")[-1]
        out_name = f"SM_SlashOuterGlow_{idx_suffix}"

        me = blade.data
        uv = me.uv_layers.active.data
        by_u = defaultdict(list)
        for loop in me.loops:
            u, v = uv[loop.index].uv
            by_u[round(u, 4)].append((v, me.vertices[loop.vertex_index].co.copy()))
        cols = []
        for u in sorted(by_u):
            pts = sorted(by_u[u], key=lambda p: p[0])
            cols.append((pts[0][1], pts[-1][1]))  # (outer edge, inner edge)

        outer = [c[0] for c in cols]
        inward = [(c[1] - c[0]).normalized() for c in cols]
        seg = [(outer[i + 1] - outer[i]).length for i in range(len(outer) - 1)]
        cum = [0.0]
        for l in seg:
            cum.append(cum[-1] + l)
        rim_len_3d = cum[-1]
        k = rim_len_3d / rim_len_px  # cm per painted pixel

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
        total_cols = EXT_STEPS + columns + EXT_STEPS
        specs = []  # (p3, n3, u_tex, sweep_s)

        p_tail, n_tail = rim3d(0.0)
        t3_tail = (p_tail - rim3d(0.02)[0]).normalized()
        for j in range(EXT_STEPS, 0, -1):
            d_ext = EXT_TAIL_PX * j / EXT_STEPS
            col_idx = EXT_STEPS - j
            u_tex = col_idx / float(total_cols - 1)
            specs.append((p_tail + t3_tail * (d_ext * k), n_tail, u_tex, 0.0))

        for ci in range(columns):
            sw = ci / float(columns - 1)
            p3, n3 = rim3d(sw)
            col_idx = EXT_STEPS + ci
            u_tex = col_idx / float(total_cols - 1)
            specs.append((p3, n3, u_tex, sw))

        p_head, n_head = rim3d(1.0)
        t3_head = (p_head - rim3d(0.98)[0]).normalized()
        for j in range(1, EXT_STEPS + 1):
            d_ext = EXT_HEAD_PX * j / EXT_STEPS
            col_idx = EXT_STEPS + columns - 1 + j
            u_tex = col_idx / float(total_cols - 1)
            specs.append((p_head + t3_head * (d_ext * k), n_head, u_tex, 1.0))

        bm = bmesh.new()
        uv0 = bm.loops.layers.uv.new("UVMap")
        uv1 = bm.loops.layers.uv.new("UVSweep")
        grid = []
        for p3, n3, u_tex, s in specs:
            row = []
            for ri in range(ROWS + 1):
                f = ri / float(ROWS)  # 0 = outer edge, 0.5 = golden rim center, 1.0 = inner edge of strip
                d = D_OUTER_PX + f * (D_INNER_PX - D_OUTER_PX)
                vert = bm.verts.new(p3 + n3 * (d * k))
                # FBX -> UE flips V, so store 1.0 - f so UE V=0 is outer, V=0.5 is golden rim, V=1.0 is inner
                row.append((vert, (u_tex, 1.0 - f), (s, 1.0 - f)))
            grid.append(row)

        for a, b in zip(grid[:-1], grid[1:]):
            for ri in range(ROWS):
                quad = (a[ri], b[ri], b[ri + 1], a[ri + 1])
                face = bm.faces.new([q[0] for q in quad])
                for loop, q in zip(face.loops, quad):
                    loop[uv0].uv = q[1]
                    loop[uv1].uv = q[2]

        strip_mesh = bpy.data.meshes.new(out_name)
        bm.to_mesh(strip_mesh)
        bm.free()
        blade.name = out_name
        blade.data = strip_mesh
        made.append(blade)
        print(
            "OUTER_STRIP",
            out_name,
            "rim3d_cm",
            round(rim_len_3d, 1),
            "strip_width_cm",
            round((D_INNER_PX - D_OUTER_PX) * k, 1),
            "dims",
            [round(x, 1) for x in blade.dimensions],
        )

    bpy.ops.object.select_all(action="DESELECT")
    for o in made:
        o.select_set(True)
    bpy.context.view_layer.objects.active = made[0]
    bpy.ops.export_scene.fbx(
        filepath=OUT_FBX,
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
    print("EXPORTED", OUT_FBX)


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
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = base_rgba
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if em_rgba is not None and "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = em_rgba
        bsdf.inputs["Emission Strength"].default_value = em_str
    return mat


def add_wireframe_clone(obj, wire_mat, thickness=1.1, z_lift=0.35):
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
    """Render two ultra-clean studio 3D diagrams showing:
      1) SM_SlashArc_01 wide circular crescent mesh + quad wireframe
      2) SM_SlashArc_01 + narrow SM_SlashOuterGlow_01 golden outer-rim strip stacked on top
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    # Pick available engine (BLENDER_EEVEE_NEXT in Blender 4.2+, BLENDER_EEVEE in 3.x/4.0)
    avail = {e.identifier for e in scene.render.bl_rna.properties["engine"].enum_items}
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in avail else "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1200
    scene.render.film_transparent = False

    # Dark studio world
    world = bpy.data.worlds.new("StudioWorld")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.018, 0.024, 0.042, 1.0)
    bg.inputs[1].default_value = 1.0

    # Import SM_SlashArc_01 and SM_SlashOuterGlow_01
    bpy.ops.import_scene.fbx(filepath=SHEETS_FBX)
    for o in list(bpy.context.scene.objects):
        if o.name != "SM_SlashArc_01":
            bpy.data.objects.remove(o, do_unlink=True)
    main_arc = bpy.data.objects["SM_SlashArc_01"]

    bpy.ops.import_scene.fbx(filepath=OUT_FBX)
    for o in list(bpy.context.scene.objects):
        if o.name.startswith("SM_SlashOuterGlow_") and o.name != "SM_SlashOuterGlow_01":
            bpy.data.objects.remove(o, do_unlink=True)
    outer_strip = bpy.data.objects["SM_SlashOuterGlow_01"]

    # Flatten both into canonical XY plane (same transform as NS_IceSlash_Slash so it reads naturally!)
    for obj in (main_arc, outer_strip):
        obj.scale = (1.08022, 1.08022, 1.08022)
        obj.rotation_euler = Euler((math.radians(0.0), math.radians(-12.0), math.radians(0.0)), "XYZ")
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        obj.select_set(False)

    # Recenter bounding box around origin on XY and Z=0
    verts_world = [main_arc.matrix_world @ v.co for v in main_arc.data.vertices]
    cx = 0.5 * (min(v.x for v in verts_world) + max(v.x for v in verts_world))
    cy = 0.5 * (min(v.y for v in verts_world) + max(v.y for v in verts_world))
    cz = 0.5 * (min(v.z for v in verts_world) + max(v.z for v in verts_world))
    for obj in (main_arc, outer_strip):
        obj.location -= Vector((cx, cy, cz))

    # Subtle reference floor grid
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=14, y_subdivisions=14, size=820.0, location=(0.0, 0.0, -45.0))
    grid_obj = bpy.context.active_object
    grid_wire_mat = make_emission_mat("GridWire", (0.09, 0.14, 0.24, 1.0), 1.0)
    grid_obj.data.materials.append(grid_wire_mat)
    gmod = grid_obj.modifiers.new("GridWire", type="WIREFRAME")
    gmod.thickness = 0.8
    gmod.use_replace = True

    # Materials
    mat_arc_clay = make_principled_mat(
        "ArcClay", (0.14, 0.36, 0.62, 1.0), rough=0.38, metal=0.08,
        em_rgba=(0.06, 0.22, 0.42, 1.0), em_str=0.35,
    )
    mat_arc_wire = make_emission_mat("ArcWire", (0.42, 0.86, 1.0, 1.0), 1.8)
    mat_strip_clay = make_principled_mat(
        "StripGold", (1.0, 0.68, 0.14, 1.0), rough=0.25, metal=0.15,
        em_rgba=(1.0, 0.62, 0.12, 1.0), em_str=2.2,
    )
    mat_strip_wire = make_emission_mat("StripWire", (1.0, 0.95, 0.68, 1.0), 3.0)

    main_arc.data.materials.clear()
    main_arc.data.materials.append(mat_arc_clay)
    arc_wire_obj = add_wireframe_clone(main_arc, mat_arc_wire, thickness=0.95, z_lift=0.25)

    outer_strip.data.materials.clear()
    outer_strip.data.materials.append(mat_strip_clay)
    # Lift outer_strip slightly (+6 cm) in diagram #2 so both layers & their quad grids are crystal clear!
    outer_strip.location.z += 6.0
    strip_wire_obj = add_wireframe_clone(outer_strip, mat_strip_wire, thickness=1.05, z_lift=0.30)

    # Studio lights
    key_data = bpy.data.lights.new("KeyLight", type="SUN")
    key_data.energy = 3.5
    key_obj = bpy.data.objects.new("KeyLight", key_data)
    bpy.context.collection.objects.link(key_obj)
    key_obj.rotation_euler = Euler((math.radians(42), math.radians(-25), math.radians(30)), "XYZ")

    rim_data = bpy.data.lights.new("RimLight", type="SUN")
    rim_data.energy = 1.8
    rim_data.color = (0.65, 0.85, 1.0)
    rim_obj = bpy.data.objects.new("RimLight", rim_data)
    bpy.context.collection.objects.link(rim_obj)
    rim_obj.rotation_euler = Euler((math.radians(58), math.radians(135), math.radians(-20)), "XYZ")

    # Camera framing the full crescent cleanly from an intuitive 3/4 top-front angle
    cam_data = bpy.data.cameras.new("DiagramCam")
    cam_data.lens = 38.0
    cam_data.clip_end = 5000.0
    cam_obj = bpy.data.objects.new("DiagramCam", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    scene.camera = cam_obj

    cam_pos = Vector((0.0, -560.0, 520.0))
    target = Vector((0.0, 15.0, -10.0))
    direction = (target - cam_pos).normalized()
    cam_obj.location = cam_pos
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    # Render #1: Main circular arc mesh ONLY
    outer_strip.hide_render = True
    strip_wire_obj.hide_render = True
    scene.render.filepath = TUT_MAIN_ARC_PNG
    bpy.ops.render.render(write_still=True)
    print("RENDERED", TUT_MAIN_ARC_PNG)

    # Render #2: Main arc mesh (slightly dimmed) + Narrow Outer-Rim Glow Strip stacked along outer edge!
    mat_arc_dim = make_principled_mat(
        "ArcDim", (0.09, 0.22, 0.40, 1.0), rough=0.48, metal=0.05,
        em_rgba=(0.03, 0.10, 0.22, 1.0), em_str=0.18,
    )
    mat_arc_wire_dim = make_emission_mat("ArcWireDim", (0.22, 0.50, 0.72, 1.0), 0.9)
    main_arc.data.materials[0] = mat_arc_dim
    arc_wire_obj.data.materials[0] = mat_arc_wire_dim

    outer_strip.hide_render = False
    strip_wire_obj.hide_render = False
    scene.render.filepath = TUT_OUTER_STRIP_PNG
    bpy.ops.render.render(write_still=True)
    print("RENDERED", TUT_OUTER_STRIP_PNG)


if __name__ == "__main__":
    build_outer_glow_fbx()
    render_tutorial_mesh_diagrams()
