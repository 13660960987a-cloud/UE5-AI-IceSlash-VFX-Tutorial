"""Split the v2 Tripo ice cluster into six cartoon-prism parts.

v2 is a different asset from v1: it is already 31 separate connected islands
(snow disc + individual hexagonal prisms + blocky ice stones), so grouping is
done per island instead of by k-means over one welded shell.

Classification is shape-based, because the model ships a single material with
no vertex colours:

    height / footprint >= 1.0  -> a crystal prism
    height / footprint <  1.0  -> a blocky ice stone (Boulders)
    the >1000-vertex island    -> the snow disc (Base)

Crystals are then ranked by tip height: the tallest 1-2 become Core, the rest
are grouped by azimuth into Left / Right / Back (Left = -X, i.e. the viewer's
left when looking at the cluster from -Y).

Hard edges matter here: these are low-poly prisms, so shading them smooth
would melt the facets. Every part is shaded smooth and then given an
Edge Split modifier at 30 degrees, which keeps each facet flat while still
smoothing any coplanar run.

Run:  blender -b --python SourceAssets/IceCrystal/split_ice_cluster_v2.py
"""

import bpy
import bmesh
import json
import math
import os

import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
IN_FBX = os.path.join(HERE, "Tripo_IceCluster_v2_raw.fbx")
OUT_FBX = os.path.join(HERE, "SM_IceCluster_v2.fbx")
OUT_PNG = os.path.join(HERE, "IceCluster_v2_split_preview.png")
OUT_JSON = os.path.join(HERE, "SM_IceCluster_v2_parts.json")

DISC_MIN_VERTS = 1000        # the snow disc is the only island this large
CRYSTAL_RATIO = 1.0          # height / footprint
CORE_COUNT = 2               # tallest prisms that become Core
SHARP_ANGLE = math.radians(30.0)
BACK_Y = 0.10                # +Y is the back of the cluster

PART_COLOURS = {
    "SM_IceCluster_Core": (0.25, 0.60, 1.00),
    "SM_IceCluster_Left": (0.20, 0.95, 0.85),
    "SM_IceCluster_Right": (0.80, 0.40, 1.00),
    "SM_IceCluster_Back": (0.25, 0.90, 0.45),
    "SM_IceCluster_Boulders": (1.00, 0.95, 0.55),
    "SM_IceCluster_Base": (0.75, 0.82, 0.92),
}


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras,
                       bpy.data.lights, bpy.data.images):
        for block in list(datablocks):
            try:
                datablocks.remove(block, do_unlink=True)
            except (RuntimeError, ReferenceError):
                pass


def import_source():
    bpy.ops.import_scene.fbx(filepath=IN_FBX)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("nothing imported")
    obj = meshes[0]
    obj.data.transform(obj.matrix_world)
    obj.matrix_world.identity()
    return obj


def island_list(mesh):
    """Connected components as lists of vertex indices."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    seen = set()
    islands = []
    for vert in bm.verts:
        if vert.index in seen:
            continue
        stack = [vert]
        seen.add(vert.index)
        component = []
        while stack:
            current = stack.pop()
            component.append(current.index)
            for edge in current.link_edges:
                other = edge.other_vert(current)
                if other.index not in seen:
                    seen.add(other.index)
                    stack.append(other)
        islands.append(component)
    bm.free()
    return islands


def faces_of_islands(mesh, islands):
    """Map island index -> set of face indices."""
    vertex_to_faces = {}
    for poly in mesh.polygons:
        for index in poly.vertices:
            vertex_to_faces.setdefault(index, []).append(poly.index)

    result = []
    for component in islands:
        faces = set()
        for vertex_index in component:
            faces.update(vertex_to_faces.get(vertex_index, []))
        result.append(sorted(faces))
    return result


def classify(mesh):
    islands = island_list(mesh)
    island_faces = faces_of_islands(mesh, islands)
    coords = np.array([[v.co.x, v.co.y, v.co.z] for v in mesh.vertices])

    entries = []
    for component, faces in zip(islands, island_faces):
        points = coords[component]
        centre = points.mean(0)
        height = float(points[:, 2].max() - points[:, 2].min())
        footprint = float(max(points[:, 0].max() - points[:, 0].min(),
                              points[:, 1].max() - points[:, 1].min()))
        entries.append(dict(
            verts=component, faces=faces, centre=centre, height=height,
            footprint=footprint, ratio=height / max(footprint, 1e-6),
            zmax=float(points[:, 2].max()),
            radius=float(math.hypot(centre[0], centre[1])),
            count=len(component),
        ))

    parts = {name: [] for name in PART_COLOURS}

    disc = [e for e in entries if e["count"] >= DISC_MIN_VERTS]
    rest = [e for e in entries if e["count"] < DISC_MIN_VERTS]
    for entry in disc:
        parts["SM_IceCluster_Base"].extend(entry["faces"])

    crystals = [e for e in rest if e["ratio"] >= CRYSTAL_RATIO]
    boulders = [e for e in rest if e["ratio"] < CRYSTAL_RATIO]

    for entry in boulders:
        parts["SM_IceCluster_Boulders"].extend(entry["faces"])

    crystals.sort(key=lambda e: -e["zmax"])
    for index, entry in enumerate(crystals):
        if index < CORE_COUNT:
            parts["SM_IceCluster_Core"].extend(entry["faces"])
            continue
        cx, cy = entry["centre"][0], entry["centre"][1]
        if cy > BACK_Y:
            parts["SM_IceCluster_Back"].extend(entry["faces"])
        elif cx < 0.0:
            parts["SM_IceCluster_Left"].extend(entry["faces"])
        else:
            parts["SM_IceCluster_Right"].extend(entry["faces"])

    stats = dict(
        islands=len(entries),
        disc_islands=[e["count"] for e in disc],
        crystal_islands=[round(e["ratio"], 2) for e in crystals],
        boulder_islands=[round(e["ratio"], 2) for e in boulders],
    )
    return parts, stats


def build_object(source_mesh, face_ids, name):
    bm_source = bmesh.new()
    bm_source.from_mesh(source_mesh)
    bm_source.faces.ensure_lookup_table()

    selected = [bm_source.faces[i] for i in face_ids if i < len(bm_source.faces)]
    sub = bmesh.new()
    mapping = {}
    for face in selected:
        verts = []
        for vert in face.verts:
            if vert.index not in mapping:
                mapping[vert.index] = sub.verts.new(vert.co.copy())
            verts.append(mapping[vert.index])
        try:
            sub.faces.new(verts)
        except ValueError:
            continue
    bm_source.free()

    if not sub.faces:
        sub.free()
        return None

    bmesh.ops.recalc_face_normals(sub, faces=list(sub.faces))
    mesh = bpy.data.meshes.new(name + "_mesh")
    sub.to_mesh(mesh)
    sub.free()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    # Origin at the part's bottom centre so it can grow up from the ground.
    coords = np.array([[v.co.x, v.co.y, v.co.z] for v in mesh.vertices])
    low = coords.min(0)
    high = coords.max(0)
    origin = Vector(((low[0] + high[0]) * 0.5, (low[1] + high[1]) * 0.5, low[2]))
    for vert in mesh.vertices:
        vert.co -= origin
    obj.location = origin

    rebuild_uv(mesh)
    hard_edges(obj)
    return obj


def rebuild_uv(mesh):
    """Cylindrical UV: U around the part, V bottom(0) -> top(1) for growth masks."""
    coords = np.array([[v.co.x, v.co.y, v.co.z] for v in mesh.vertices])
    low = coords.min(0)
    high = coords.max(0)
    centre_x = (low[0] + high[0]) * 0.5
    centre_y = (low[1] + high[1]) * 0.5
    height = max(high[2] - low[2], 1e-6)

    uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vert = mesh.vertices[mesh.loops[loop_index].vertex_index]
            u = math.atan2(vert.co.y - centre_y, vert.co.x - centre_x) / (2.0 * math.pi) + 0.5
            v = (vert.co.z - low[2]) / height
            uv_layer.data[loop_index].uv = (u, max(0.0, min(1.0, v)))
    mesh.update()


def hard_edges(obj):
    """Smooth shading + a 30 deg Edge Split so prism facets stay flat."""
    for poly in obj.data.polygons:
        poly.use_smooth = True

    modifier = obj.modifiers.new("EdgeSplit", "EDGE_SPLIT")
    modifier.split_angle = SHARP_ANGLE
    modifier.use_edge_angle = True
    modifier.use_edge_sharp = False

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)


def make_preview_material(name, rgb):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    emission.inputs["Strength"].default_value = 1.15
    material.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def setup_world():
    world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.02, 0.025, 0.035, 1.0)
        background.inputs["Strength"].default_value = 1.0


def bounds_of(objects):
    low = np.array([1e9, 1e9, 1e9])
    high = np.array([-1e9, -1e9, -1e9])
    for obj in objects:
        for corner in obj.bound_box:
            world = np.array(obj.matrix_world @ Vector(corner))
            low = np.minimum(low, world)
            high = np.maximum(high, world)
    return low, high


def add_ortho_camera(name, location, rotation, ortho_scale):
    data = bpy.data.cameras.new(name)
    data.type = "ORTHO"
    data.ortho_scale = ortho_scale
    camera = bpy.data.objects.new(name, data)
    camera.location = tuple(location)
    camera.rotation_euler = rotation
    bpy.context.collection.objects.link(camera)
    return camera


def render_view(camera, path, resolution=900):
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def combine_side_by_side(left_path, right_path, out_path):
    left = bpy.data.images.load(left_path)
    right = bpy.data.images.load(right_path)
    width, height = left.size
    left_px = list(left.pixels)
    right_px = list(right.pixels)
    sheet_width = width * 2
    buffer = [0.0] * (sheet_width * height * 4)
    for row in range(height):
        src = row * width * 4
        dst = row * sheet_width * 4
        buffer[dst:dst + width * 4] = left_px[src:src + width * 4]
        buffer[dst + width * 4:dst + width * 8] = right_px[src:src + width * 4]
    sheet = bpy.data.images.new("IceV2Split", sheet_width, height, alpha=True)
    sheet.pixels = buffer
    sheet.filepath_raw = out_path
    sheet.file_format = "PNG"
    sheet.save()


def main():
    clear_scene()
    source = import_source()
    print("SOURCE faces=%d verts=%d" % (len(source.data.polygons), len(source.data.vertices)))

    parts, stats = classify(source.data)
    print("ISLANDS total=%d disc=%s" % (stats["islands"], stats["disc_islands"]))
    print("CRYSTAL ratios=%s" % stats["crystal_islands"])
    print("BOULDER ratios=%s" % stats["boulder_islands"])

    order = ["SM_IceCluster_Core", "SM_IceCluster_Left", "SM_IceCluster_Right",
             "SM_IceCluster_Back", "SM_IceCluster_Boulders", "SM_IceCluster_Base"]

    built = []
    report = []
    for name in order:
        face_ids = parts[name]
        if not face_ids:
            print("SKIP %s (empty)" % name)
            continue
        obj = build_object(source.data, face_ids, name)
        if obj is None:
            continue
        built.append(obj)
        coords = np.array([[v.co.x + obj.location.x, v.co.y + obj.location.y,
                            v.co.z + obj.location.z] for v in obj.data.vertices])
        size = coords.max(0) - coords.min(0)
        report.append(dict(name=name, faces=len(obj.data.polygons),
                           verts=len(obj.data.vertices),
                           size_m=[round(float(v), 3) for v in size],
                           z_range=[round(float(coords[:, 2].min()), 3),
                                    round(float(coords[:, 2].max()), 3)]))

    bpy.data.objects.remove(source, do_unlink=True)

    # export
    bpy.ops.object.select_all(action="DESELECT")
    for obj in built:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = built[0]
    bpy.ops.export_scene.fbx(
        filepath=OUT_FBX,
        use_selection=True,
        object_types={"MESH"},
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_ALL",
        axis_forward="-Y",
        axis_up="Z",
        bake_space_transform=False,
        mesh_smooth_type="OFF",
    )
    print("EXPORTED", OUT_FBX)

    # preview
    setup_world()
    for obj in built:
        obj.data.materials.clear()
        obj.data.materials.append(
            make_preview_material("M_" + obj.name, PART_COLOURS.get(obj.name, (1, 1, 1))))

    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 32
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"

    low, high = bounds_of(built)
    centre = (low + high) * 0.5
    span = high - low
    distance = max(span) * 3.0

    front = add_ortho_camera("Cam_Front", centre + np.array([0.0, -distance, 0.0]),
                             (math.radians(90.0), 0.0, 0.0), max(span[0], span[2]) * 1.15)
    top = add_ortho_camera("Cam_Top", centre + np.array([0.0, 0.0, distance]),
                           (0.0, 0.0, 0.0), max(span[0], span[1]) * 1.15)

    front_png = os.path.join(HERE, "_v2_front.png")
    top_png = os.path.join(HERE, "_v2_top.png")
    render_view(front, front_png)
    render_view(top, top_png)
    combine_side_by_side(front_png, top_png, OUT_PNG)
    print("PREVIEW", OUT_PNG)
    for temp in (front_png, top_png):
        if os.path.exists(temp):
            os.remove(temp)

    print("--- PARTS ---")
    for item in report:
        print("%s | faces=%d verts=%d | size=%.3f x %.3f x %.3f | z=[%.3f, %.3f]"
              % (item["name"], item["faces"], item["verts"], item["size_m"][0],
                 item["size_m"][1], item["size_m"][2], item["z_range"][0], item["z_range"][1]))
    with open(OUT_JSON, "w") as handle:
        json.dump(report, handle, indent=2)
    print("PARTS JSON written")


main()