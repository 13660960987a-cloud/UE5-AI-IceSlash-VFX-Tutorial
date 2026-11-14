"""Split the Tripo ice cluster into six gameplay-ready parts.

The Tripo mesh is a single welded shell: the ground ice disc and every crystal
spike are one connected surface, so connected-component splitting is useless
(only a stray 5-vertex fragment is separate). The split is therefore done
geometrically:

    1. bisect the whole mesh at the disc's top plane and fill the cut, so the
       disc becomes a clean closed slab instead of sharing a welded boundary
    2. everything below that plane -> SM_IceCluster_Base
    3. everything above -> k-means (k=10) on face centroids
       * the cluster holding the global highest vertex -> _Core
       * the rest grouped by azimuth -> _Left / _Right / _Back
       * clusters that are too small -> _Debris (and dropped below a floor)
    4. per crystal part: sharpen the spikes by pulling the upper vertices
       toward the local tip axis (topology untouched, no extra faces)
    5. rebuild UVs cylindrically: U around the part, V 0 at the bottom -> 1 at
       the top, so a CrystalGrowth mask can drive upward growth
    6. move every origin to its own bottom centre, keep Z up and no rotation
    7. export SourceAssets/IceCrystal/SM_IceCluster.fbx (6 objects) and render
       a colour-coded preview

Run:  blender -b --python SourceAssets/IceCrystal/split_ice_cluster.py
"""

import bpy
import bmesh
import json
import math
import os

import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
IN_FBX = os.path.join(HERE, "Tripo_IceCluster_raw.fbx")
OUT_FBX = os.path.join(HERE, "SM_IceCluster.fbx")
OUT_PNG = os.path.join(HERE, "IceCluster_split_preview.png")

# Disc top plane, measured from the source: the flat ground slab spans
# z = -0.409 .. -0.315, the spikes grow above it.
DISC_TOP_Z = -0.315

K_MEANS = 10
MIN_CLUSTER_FRACTION = 0.015     # clusters below this share of crystal faces -> debris
MIN_DEBRIS_FACES = 40            # debris smaller than this is deleted outright
SPIKE_SHARPEN_START = 0.55       # start tapering at 55% of the part's height
SPIKE_SHARPEN_STRENGTH = 0.55

PART_COLOURS = {
    "SM_IceCluster_Core": (0.20, 0.55, 1.00),
    "SM_IceCluster_Left": (0.15, 0.90, 0.85),
    "SM_IceCluster_Right": (0.75, 0.35, 1.00),
    "SM_IceCluster_Back": (0.20, 0.85, 0.45),
    "SM_IceCluster_Base": (0.55, 0.65, 0.80),
    "SM_IceCluster_Debris": (1.00, 0.60, 0.20),
}


# --------------------------------------------------------------------------
# scene helpers
# --------------------------------------------------------------------------
def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras,
                       bpy.data.lights, bpy.data.curves, bpy.data.images):
        for block in list(datablocks):
            try:
                datablocks.remove(block, do_unlink=True)
            except (RuntimeError, ReferenceError):
                pass


def import_source():
    bpy.ops.import_scene.fbx(filepath=IN_FBX)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("no mesh imported")
    obj = meshes[0]
    # Keep only the largest mesh if the importer split things up.
    matrix = obj.matrix_world.copy()
    obj.data.transform(matrix)
    obj.matrix_world.identity()
    return obj


def bisect_at_disc_top(obj, z_cut):
    """Cut the welded shell at the disc's top plane and fill both sides."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.bisect_plane(
        bm,
        geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
        plane_co=(0.0, 0.0, z_cut),
        plane_no=(0.0, 0.0, 1.0),
        clear_inner=False,
        clear_outer=False,
    )
    bmesh.ops.holes_fill(bm, edges=list(bm.edges), sides=0)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


# --------------------------------------------------------------------------
# clustering
# --------------------------------------------------------------------------
def kmeans(points, k, iterations=40, seed=7):
    """Plain Lloyd's algorithm -- deterministic for a fixed seed."""
    rng = np.random.default_rng(seed)
    if len(points) < k:
        k = max(1, len(points))
    centres = points[rng.choice(len(points), k, replace=False)].copy()
    labels = np.zeros(len(points), dtype=int)
    for _ in range(iterations):
        distances = ((points[:, None, :] - centres[None, :, :]) ** 2).sum(-1)
        labels = distances.argmin(1)
        for index in range(k):
            mask = labels == index
            if mask.any():
                centres[index] = points[mask].mean(0)
    return labels, centres


def classify_faces(obj):
    """Return {part_name: [face_index, ...]} for the six output parts."""
    mesh = obj.data
    mesh.calc_loop_triangles()

    crystal = []      # (face_index, centroid)
    base = []
    for poly in mesh.polygons:
        centre = poly.center
        if centre.z < DISC_TOP_Z:
            base.append(poly.index)
        else:
            crystal.append((poly.index, np.array([centre.x, centre.y, centre.z])))

    points = np.array([c for _, c in crystal])
    labels, centres = kmeans(points, K_MEANS)

    # Cluster statistics -------------------------------------------------
    stats = []
    for index in range(centres.shape[0]):
        mask = labels == index
        if not mask.any():
            continue
        cluster_points = points[mask]
        stats.append(dict(
            id=index,
            count=int(mask.sum()),
            centroid=centres[index],
            zmax=float(cluster_points[:, 2].max()),
            radius=float(np.hypot(centres[index][0], centres[index][1])),
        ))

    total = sum(s["count"] for s in stats)
    stats.sort(key=lambda s: -s["zmax"])

    parts = {"SM_IceCluster_Base": list(base),
             "SM_IceCluster_Core": [],
             "SM_IceCluster_Left": [],
             "SM_IceCluster_Right": [],
             "SM_IceCluster_Back": [],
             "SM_IceCluster_Debris": []}

    # Core = the central crystal column: every cluster whose centre sits close
    # to the vertical axis joins it, not just the single highest cluster.
    CORE_RADIUS = 0.16
    core_taken = False
    for cluster in stats:
        face_ids = [crystal[i][0] for i in np.where(labels == cluster["id"])[0]]

        if not core_taken and cluster["zmax"] >= stats[0]["zmax"] - 1e-6:
            parts["SM_IceCluster_Core"].extend(face_ids)
            core_taken = True
            continue

        if cluster["radius"] <= CORE_RADIUS:
            parts["SM_IceCluster_Core"].extend(face_ids)
            continue

        if cluster["count"] < total * MIN_CLUSTER_FRACTION:
            parts["SM_IceCluster_Debris"].extend(face_ids)
            continue

        cx, cy = cluster["centroid"][0], cluster["centroid"][1]
        # The character faces -Y, so +Y is the back of the cluster.
        if cy > 0.10:
            parts["SM_IceCluster_Back"].extend(face_ids)
        elif cx < 0.0:
            parts["SM_IceCluster_Left"].extend(face_ids)
        else:
            parts["SM_IceCluster_Right"].extend(face_ids)

    # Drop debris that is too small to be worth a draw call.
    if len(parts["SM_IceCluster_Debris"]) < MIN_DEBRIS_FACES:
        parts["SM_IceCluster_Debris"] = []

    return parts


# --------------------------------------------------------------------------
# mesh building
# --------------------------------------------------------------------------
def build_object(source_mesh, face_ids, name, sharpen):
    """Create a new object from selected faces, sharpen spikes, re-UV it."""
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
    sub.to_mesh(bpy.data.meshes.new(name + "_mesh"))
    sub.free()

    mesh = bpy.data.meshes[name + "_mesh"]
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    if sharpen:
        sharpen_spikes(mesh)

    # Origin at the part's own bottom centre.
    coords = np.array([[v.co.x, v.co.y, v.co.z] for v in mesh.vertices])
    low = coords.min(0)
    high = coords.max(0)
    origin = Vector(((low[0] + high[0]) * 0.5, (low[1] + high[1]) * 0.5, low[2]))
    for vert in mesh.vertices:
        vert.co -= origin
    obj.location = origin
    mesh.update()

    rebuild_uv(mesh)
    return obj


def sharpen_spikes(mesh, start=SPIKE_SHARPEN_START, strength=SPIKE_SHARPEN_STRENGTH):
    """Pull the upper half of each spike toward its tip axis -- no new faces."""
    zs = [v.co.z for v in mesh.vertices]
    if not zs:
        return
    z_min, z_max = min(zs), max(zs)
    height = z_max - z_min
    if height < 1e-6:
        return

    # Tip = centroid of the top 5% of vertices.
    threshold = z_max - height * 0.05
    tip_xy = [v.co for v in mesh.vertices if v.co.z >= threshold]
    tip_x = sum(v.x for v in tip_xy) / len(tip_xy)
    tip_y = sum(v.y for v in tip_xy) / len(tip_xy)

    for vert in mesh.vertices:
        t = (vert.co.z - z_min) / height
        if t <= start:
            continue
        u = (t - start) / max(1.0 - start, 1e-6)
        factor = 1.0 - strength * (u ** 1.2)
        vert.co.x = tip_x + (vert.co.x - tip_x) * factor
        vert.co.y = tip_y + (vert.co.y - tip_y) * factor
    mesh.update()


def rebuild_uv(mesh):
    """Cylindrical UV: U around the part, V bottom(0) -> top(1)."""
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


# --------------------------------------------------------------------------
# preview
# --------------------------------------------------------------------------
def make_preview_material(name, rgb):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    emission.inputs["Strength"].default_value = 1.25
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
    sheet = bpy.data.images.new("IceSplit", sheet_width, height, alpha=True)
    sheet.pixels = buffer
    sheet.filepath_raw = out_path
    sheet.file_format = "PNG"
    sheet.save()


# --------------------------------------------------------------------------
def main():
    clear_scene()
    source = import_source()
    print("SOURCE faces=%d verts=%d" % (len(source.data.polygons), len(source.data.vertices)))

    bisect_at_disc_top(source, DISC_TOP_Z)
    print("AFTER BISECT faces=%d verts=%d" % (len(source.data.polygons), len(source.data.vertices)))

    parts = classify_faces(source)

    order = ["SM_IceCluster_Core", "SM_IceCluster_Left", "SM_IceCluster_Right",
             "SM_IceCluster_Back", "SM_IceCluster_Base", "SM_IceCluster_Debris"]

    built = []
    report = []
    for name in order:
        face_ids = parts[name]
        if not face_ids:
            print("SKIP %s (empty)" % name)
            continue
        obj = build_object(source.data, face_ids, name, sharpen=(name != "SM_IceCluster_Base"))
        if obj is None:
            continue
        built.append(obj)

        coords = np.array([[v.co.x + obj.location.x,
                            v.co.y + obj.location.y,
                            v.co.z + obj.location.z] for v in obj.data.vertices])
        size = coords.max(0) - coords.min(0)
        report.append(dict(name=name, faces=len(obj.data.polygons), verts=len(obj.data.vertices),
                           size=size, zmin=float(coords[:, 2].min()),
                           zmax=float(coords[:, 2].max())))

    # source object no longer needed
    bpy.data.objects.remove(source, do_unlink=True)

    # export -----------------------------------------------------------
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

    # preview ----------------------------------------------------------
    setup_world()
    for obj in built:
        obj.data.materials.clear()
        obj.data.materials.append(make_preview_material("M_" + obj.name, PART_COLOURS.get(obj.name, (1, 1, 1))))

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

    front_png = os.path.join(HERE, "_split_front.png")
    top_png = os.path.join(HERE, "_split_top.png")
    render_view(front, front_png)
    render_view(top, top_png)
    combine_side_by_side(front_png, top_png, OUT_PNG)
    print("PREVIEW", OUT_PNG)

    for temp in (front_png, top_png):
        if os.path.exists(temp):
            os.remove(temp)

    # report -----------------------------------------------------------
    print("--- PARTS ---")
    payload = []
    for item in report:
        size = item["size"]
        print("%s | faces=%d verts=%d | size=%.3f x %.3f x %.3f (m) | z=[%.3f, %.3f]"
              % (item["name"], item["faces"], item["verts"],
                 size[0], size[1], size[2], item["zmin"], item["zmax"]))
        payload.append(dict(name=item["name"], faces=item["faces"], verts=item["verts"],
                            size_m=[round(float(v), 3) for v in size],
                            z_range=[round(item["zmin"], 3), round(item["zmax"], 3)]))
    with open(os.path.join(HERE, "SM_IceCluster_parts.json"), "w") as handle:
        json.dump(payload, handle, indent=2)
    print("PARTS JSON written")


main()