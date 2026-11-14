"""Process the Tripo IceBurst v3 model into the ice-slash cluster parts.

Pipeline:
  1. import Tripo_IceBurst_v3_raw.fbx (1 m, one material + 2K textures)
  2. per-face basecolor sampling: on floating-point UVs the chart contents bleed into the
     gutters, so each face first re-unwraps its own UV island (smart project) and then takes
     the greedy mean of 5 samples (centroid + 4 steps halfway to the vertices) -- every
     source face whose layout samples fall inside it contributes ITS OWN samples
  3. thresholds from the island brightness / saturation list (it jumps 0.35 -> 0.36):
     near-white & low = Base (the mound) or Boulders (near-white blocks that sit on the
     dome); blue = crystals, the 3 tallest up-front spikes = Core, crystals within 50 deg of
     +Y (snug behind the mound) = Back, the rest Left (-X) / Right (+X)
  4. rotate Tripo's Z-down frame to Z-up, scale so the mound is 700 cm across, put the
     pivot on the mound's top-surface centre at ground level, then slide the burst so its
     XY centre is the origin and lift it so the mound bottom is z = 0 (the stand point the
     character stands on is the origin).  Crystals get flat facets (Edge Split 30 deg), the
     mound stays smooth (weighted normals).
  5. UVs per part: U = azimuth around the part (seam chosen at the lowest vertex), V = 0 at
     the part's lowest point .. 1 at its highest -- written V-flipped because FBX (this
     export path) flips V, so UE reads V = 0 at the bottom (verified by re-import).
  6. export SM_IceCluster_v3_tripo_cm.fbx, cm baked (FBX_SCALE_NONE, apply_unit_scale=False,
     axis -Y / up Z), six objects with pivots at (0,0,0); parts json; ice_slash_data.json;
     split-check render; ref comparison sheet.

Run:  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
          -P SourceAssets/IceCrystal/process_tripo_burst_v3.py
"""

import json
import math
import os
import sys

import bpy
import bmesh
import numpy as np

# NOTE: mathutils is deliberately NOT imported -- loading it (Vector/Matrix) poisons Cycles here
# (all Cycles renders turn black), so camera maths goes through bpy.mathutils's own to_euler().

# Tripo's local frame is Z-down / Y-front: 180 deg about X gives Z up with the camera side on -Y.
# Plain row-vector maths: world = local @ ROT.
ROT = np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]])
# rotated frame -> Tripo local frame (local Z is down, Y points to their "front")
ROT_INV = np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]])


def set_vertices(mesh, coords):
    """Write vertex positions. (foreach_set("co", flat n*3) mis-registers in this Blender
    build -- only the first coordinate lands per vertex -- so set each Vector.)"""
    coords = np.asarray(coords, dtype=np.float64).reshape(-1, 3)
    for vert, c in zip(mesh.vertices, coords):
        vert.co = (float(c[0]), float(c[1]), float(c[2]))
    mesh.update()


def xform(pts, mat):
    """Row-vector transform pts (n,3) @ mat. np.matmul (`@`) is flaky in this numpy build,
    so this goes through einsum."""
    return np.einsum("ij,jk->ik", np.asarray(pts, dtype=np.float64), np.asarray(mat, dtype=np.float64))


def xform_vec(vec, mat):
    return np.einsum("j,jk->k", np.asarray(vec, dtype=np.float64), np.asarray(mat, dtype=np.float64))

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.abspath(os.path.join(HERE, "..", ".."))
IN_FBX = os.path.join(HERE, "Tripo_IceBurst_v3_raw.fbx")
OUT_FBX = os.path.join(HERE, "SM_IceCluster_v3_tripo_cm.fbx")
OUT_JSON = os.path.join(HERE, "SM_IceCluster_v3_tripo_parts.json")
SPLIT_PNG = os.path.join(HERE, "IceBurst_v3_split_check.png")
COMPARE_PNG = os.path.join(HERE, "IceBurst_v3_tripo_compare.png")
DATA_JSON = os.path.join(PROJECT, "Tools", "IceSlash", "data", "ice_slash_data.json")
REF_FRAME_ASPECT = (1024, 512)  # the 16:9 frame with its letterbox cropped away

ORDER = ["SM_IceCluster_Core", "SM_IceCluster_Left", "SM_IceCluster_Right",
         "SM_IceCluster_Back", "SM_IceCluster_Boulders", "SM_IceCluster_Base"]
CRYSTALS = {"SM_IceCluster_Core", "SM_IceCluster_Left", "SM_IceCluster_Right",
            "SM_IceCluster_Back"}
MATERIAL_ROLE = {"SM_IceCluster_Core": "prism", "SM_IceCluster_Left": "prism",
                 "SM_IceCluster_Right": "prism", "SM_IceCluster_Back": "prism",
                 "SM_IceCluster_Boulders": "boulder", "SM_IceCluster_Base": "snowbase"}

MOUND_WIDTH_CM = 700.0     # reference: mound width ~3.5-4 x the 180 cm character
CORE_COUNT = 3             # longest crystals that become Core (the hero burst)
CORE_INNER = 0             # extra front crystals allowed in the core (tall ones only)
CORE_HEIGHT_RATIO = 0.75   # core = crystals whose height is 0.75 x their footprint
AIM_YAW_DEG = 0.0          # rotate the burst about Z after the pivot is fixed (0 = as modelled)
BACK_CONE_DEG = 50.0       # back = within 50 deg of local +Y (snug behind the mound)
BACK_COS = math.cos(math.radians(50.0))   # azimuth |angle from +Y| < 50 deg -> Back
SHARP_ANGLE = math.radians(30.0)
SAMPLES_PER_FACE = 5
ATLAS_UNITS = 512.0        # the raw Tripo UVs address the 2K atlas in 512-unit space

# thresholds (sRGB, 0..1); the reasons are printed from the histograms at run time
BASE_SAT_MAX = 0.355       # "near white": the sorted saturation list jumps 0.35 -> 0.36 here
BASE_VAL_MIN = 0.90
BOULDER_SAT_MAX = 0.35
BOULDER_VAL_MIN = 0.90

HUMAN_HEIGHT_CM = 180.0

PART_COLOURS = {
    "SM_IceCluster_Core": (1.00, 0.30, 0.25),
    "SM_IceCluster_Left": (0.10, 0.85, 0.45),
    "SM_IceCluster_Right": (0.90, 0.30, 0.95),
    "SM_IceCluster_Back": (0.15, 0.80, 0.95),
    "SM_IceCluster_Boulders": (1.00, 0.80, 0.10),
    "SM_IceCluster_Base": (0.90, 0.92, 1.00),
}
FLAT_COLOURS = {  # Workbench-flat test colours (readable, not the reference palette)
    "SM_IceCluster_Core": (1.00, 0.20, 0.20),
    "SM_IceCluster_Left": (0.10, 0.85, 0.30),
    "SM_IceCluster_Right": (0.90, 0.55, 0.05),     # magenta reads as brown in Workbench
    "SM_IceCluster_Back": (0.10, 0.75, 0.95),
    "SM_IceCluster_Boulders": (1.00, 0.82, 0.10),
    "SM_IceCluster_Base": (0.95, 0.95, 0.97),
}

TRI_TONES = [(0x0b / 255.0, 0x3a / 255.0, 0xa0 / 255.0),   # dark  #0b3aa0
             (0x2f / 255.0, 0x8f / 255.0, 0xe6 / 255.0),   # mid   #2f8fe6
             (0x9f / 255.0, 0xdc / 255.0, 0xff / 255.0)]   # light #9fdcff
NEAR_WHITE = (0.93, 0.95, 0.98)
HUMAN_RGB = (0.20, 0.22, 0.27)         # grey figure, display values (reads against the white mound)
BACKDROP_LINEAR = (0.03, 0.034, 0.05)  # Workbench world colour used in the pass B render
CYAN_KEY = (0.0, 0.45, 1.0, 1.0)     # marker diffuse for the near-white parts in the compare pass


# ----------------------------------------------------------------------------- utils
def log(*args):
    print("[tripo_v3]", *args)
    sys.stdout.flush()


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 0.01   # 1 BU = 1 cm
    scene.unit_settings.length_unit = "CENTIMETERS"


def srgb_from_linear(rgb):
    rgb = np.clip(rgb, 0.0, 1.0)
    return np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)


def hex_rgb(h):
    return ((h >> 16 & 255) / 255.0, (h >> 8 & 255) / 255.0, (h & 255) / 255.0)


# ----------------------------------------------------------------------------- import
def import_source():
    bpy.ops.import_scene.fbx(filepath=IN_FBX)
    for obj in bpy.data.objects:
        link_to_view_layer(obj)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if len(meshes) != 1:
        raise RuntimeError("expected one mesh, got %d" % len(meshes))
    obj = meshes[0]
    obj.data.transform(obj.matrix_world)
    obj.matrix_world.identity()
    return obj


def mesh_arrays(mesh):
    co = np.array([v.co[:] for v in mesh.vertices], dtype=np.float64)
    loop_vert = []
    for poly in mesh.polygons:
        loop_vert.extend(poly.vertices)
    loop_vert = np.array(loop_vert, dtype=np.int64)
    uv = np.zeros(len(mesh.loops) * 2)
    mesh.uv_layers[0].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2).copy()
    loop_start = np.zeros(len(mesh.polygons), dtype=np.int64)
    mesh.polygons.foreach_get("loop_start", loop_start)
    loop_total = np.zeros(len(mesh.polygons), dtype=np.int64)
    mesh.polygons.foreach_get("loop_total", loop_total)
    poly_of_loop = np.zeros(len(mesh.loops), dtype=np.int64)
    for p in mesh.polygons:
        poly_of_loop[p.loop_start:p.loop_start + p.loop_total] = p.index
    return co, loop_vert, uv, loop_start, loop_total, poly_of_loop


def islands_of(mesh):
    """Union-find over edges -> island index per vertex."""
    n = len(mesh.vertices)
    parent = np.arange(n)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for edge in mesh.edges:
        a, b = find(edge.vertices[0]), find(edge.vertices[1])
        if a != b:
            parent[a] = b
    roots = np.array([find(i) for i in range(n)])
    _, inv = np.unique(roots, return_inverse=True)
    return inv


def load_basecolor(mesh):
    for mat in mesh.materials:
        if not mat:
            continue
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image and "basecolor" in node.image.name.lower():
                img = node.image
                w, h = img.size
                raw = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
                px = raw[:, :, :3]
                log("pixel stats: max %.3f min %.3f mean %.3f ; alpha mean %.3f"
                    % (px.max(), px.min(), px.mean(), raw[:, :, 3].mean()))
                log("basecolor", img.name, w, "x", h, img.filepath)
                return px
    raise RuntimeError("no basecolor texture")


def unwrap_islands_by_uv(obj):
    """The Tripo UVs are one chaotic atlas; re-unwrap every connected island on its own
    (smart project, angle based -- keeps the chart shapes) into UNIQUE space."""
    mesh = obj.data
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    n = len(mesh.vertices)
    parent = np.arange(n)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for edge in mesh.edges:
        a, b = find(edge.vertices[0]), find(edge.vertices[1])
        if a != b:
            parent[a] = b
    vis = np.array([find(i) for i in range(n)])
    _, vis = np.unique(vis, return_inverse=True)
    first_vert = np.array([p.vertices[0] for p in mesh.polygons], dtype=np.int64)
    face_island = vis[first_vert]
    prev_2d = bpy.context.scene.tool_settings.use_uv_select_sync
    bpy.context.scene.tool_settings.use_uv_select_sync = True
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        for k in range(int(vis.max()) + 1):
            bpy.ops.object.mode_set(mode="OBJECT")
            mesh.polygons.foreach_set("select", face_island == k)
            mesh.update()
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=0.002,
                                     area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
        bpy.ops.object.mode_set(mode="OBJECT")
    finally:
        bpy.context.scene.tool_settings.use_uv_select_sync = prev_2d
    return vis


def sample_faces(px, co, loop_vert, uv, loop_start, loop_total, poly_of_loop):
    """5 samples per face (centroid + 4 steps halfway to the vertices).

    1 unit of the Tripo UV layout is 1 texel of the 512 base atlas; the exports store it
    against a 2048 texture (4x), so UV * (size / ATLAS_UNITS) is the texel.

    face_rgb      greedy mean: every source face whose layout samples fall inside this
                  face gets the average of ITS OWN samples (no bleeding at chart edges)
    face_srgb     eager mean: this face's samples only (comparison / debug)
    """
    h, w = px.shape[:2]
    faces = len(loop_start)
    face_rgb = np.zeros((faces, 3))
    face_srgb = np.zeros((faces, 3))
    weights = np.linspace(0.0, 1.0, SAMPLES_PER_FACE)
    chunk = 4096
    for start in range(0, faces, chunk):
        stop = min(start + chunk, faces)
        n = stop - start
        ls = loop_start[start:stop]
        lt = loop_total[start:stop]
        max_lt = int(lt.max())
        cols = np.arange(max_lt)[None, :]
        valid = cols < lt[:, None]
        li = ls[:, None] + np.minimum(cols, lt[:, None] - 1)
        poly_uv = uv[li]                                   # n x max_lt x 2
        centre = (poly_uv * valid[..., None]).sum(1) / lt[:, None]
        samples = poly_uv[:, :, None, :] * (1.0 - weights[None, None, :, None]) \
            + centre[:, None, None, :] * weights[None, None, :, None]   # n x max_lt x S x 2
        src_face = poly_of_loop[li]
        samples = samples[valid]                            # (sum lt) x S x 2
        src_face = src_face[valid]                          # (sum lt,) one owner per loop
        x = np.clip(np.round(samples[..., 0] * w), 0, w - 1).astype(np.int64)
        y = np.clip(np.round(samples[..., 1] * h), 0, h - 1).astype(np.int64)
        col = np.take(px.reshape(-1, 3), y * w + x, axis=0).reshape(y.shape + (3,))   # (sum lt) x S x 3
        src_idx = np.repeat(np.asarray(poly_of_loop[li], dtype=np.intp).ravel(), SAMPLES_PER_FACE)
        den = np.zeros(faces)
        np.add.at(den, src_idx, 1.0)
        for c in range(3):
            num = np.zeros(faces)
            np.add.at(num, src_idx, np.ascontiguousarray(col[:, :, c]).reshape(-1))
            sel = den > 0
            face_rgb[sel, c] = num[sel] / den[sel]
        owner = np.repeat(np.arange(n), lt)
        eager = np.zeros((n, 3))
        mean_samples = col.mean(axis=1)
        for c in range(3):
            eager[:, c] = np.bincount(owner, weights=np.ascontiguousarray(mean_samples[:, c]), minlength=n)[:n] / lt
        face_srgb[start:stop] = srgb_from_linear(eager)
    return face_rgb, face_srgb


def weighted_bincount(idx, weights, length):
    """np.bincount(idx, weights) + zero padding to `length`. This numpy build rejects
    weighted bincount / add.at whenever length > idx.max() + 1, so grow afterwards."""
    idx = np.asarray(idx, dtype=np.intp).ravel()
    weights = np.asarray(weights, dtype=np.float64).ravel()
    if idx.size == 0:
        return np.zeros(length, dtype=np.float64)
    out = np.bincount(idx, weights=weights)
    if out.size < length:
        out = np.concatenate([out, np.zeros(length - out.size)])
    return out


def colour_stats(rgb_linear):
    s = srgb_from_linear(rgb_linear)
    mx = s.max(-1)
    mn = s.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return s, mx, sat


# ----------------------------------------------------------------------------- classify
def histogram_report(island_sat, island_val, island_band, near_white, zmin, zmax):
    """Around the near-white threshold: what sits just above/below it, and where."""
    order = np.argsort(island_sat)
    log("HIST islands sorted by saturation (V, S, z-range):")
    for i in order:
        mark = "<- near-white" if near_white[i] else ""
        log("      isl %2d  V=%.2f  S=%.2f  %s" % (i, island_val[i], island_sat[i], mark))
    sat_edges = [0.0, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50]
    hist = np.histogram(island_sat, bins=sat_edges)[0]
    log("HIST island saturation bins [0.10,0.15,0.20,0.25,0.30,0.35,0.40,0.50] = %s"
        % hist.tolist())
    # where is the bottom / front-middle zone of the mound (pivot-independent, model units)
    base_top = zmax - 0.35 * (zmax - zmin)
    log("     (mound bottom zone: islands with zmin < %.1f model units)" % (zmin + 0.6 * (zmax - zmin)))
    log("THRESHOLD near-white = saturation < %.2f AND brightness > %.2f  (%d of %d islands; the gap "
        "in the sorted list above is where it was cut)"
        % (BASE_SAT_MAX, BASE_VAL_MIN, int(near_white.sum()), len(island_sat)))


def classify(co, vis, face_rgb, loop_vert, mesh_loop_start):
    face_srgb, face_val, face_sat = colour_stats(face_rgb)
    island_count = int(vis.max()) + 1
    island_of_face = vis[loop_vert[mesh_loop_start]]
    isat = np.array([face_sat[island_of_face == i].mean() for i in range(island_count)])
    ival = np.array([face_val[island_of_face == i].mean() for i in range(island_count)])
    icol = np.array([face_srgb[island_of_face == i].mean(0) for i in range(island_count)])

    zmin, zmax = co[:, 2].min(), co[:, 2].max()   # note: Tripo's local -Z is up!
    height = zmax - zmin
    stats = []
    for i in range(island_count):
        pts = co[vis == i]
        centre = pts.mean(0)
        size = pts.max(0) - pts.min(0)
        stats.append(dict(index=i, centre=centre, size=size, zmin=pts[:, 2].min(),
                          ztop=pts[:, 2].max(), verts=len(pts)))
    big = max(range(island_count), key=lambda i: stats[i]["verts"])
    mound = stats[big]
    y_front_at = co[vis == big][:, 1].min()
    mcx = 0.5 * (co[vis == big][:, 0].min() + co[vis == big][:, 0].max())
    mcy = 0.5 * (co[vis == big][:, 1].min() + co[vis == big][:, 1].max())
    mtop = mound["ztop"]
    log("mound island %d: verts %d, top z %.1f, centre xy (%+.1f, %+.1f), front y %.1f"
        % (big, mound["verts"], mtop, mcx, mcy, y_front_at))
    near_white = (isat < BASE_SAT_MAX) & (ival > BASE_VAL_MIN)
    lowest = sorted(range(island_count), key=lambda i: stats[i]["zmin"])
    band = np.array(["blue"] * island_count)
    band[lowest[:5]] = "low"
    band[np.argsort(ival)[:5]] = "bright"
    band[near_white] = "near-white"
    histogram_report(isat, ival, band, near_white, zmin, zmax)

    parts = {name: [] for name in ORDER}
    for s in stats:
        i = s["index"]
        if i == big:
            parts["SM_IceCluster_Base"].append(i)
        elif near_white[i]:
            if s["centre"][2] < mtop - 0.35 * (mtop - zmin):
                parts["SM_IceCluster_Base"].append(i)
            else:
                parts["SM_IceCluster_Boulders"].append(i)
    crystals = [s for s in stats if not near_white[s["index"]] and s["index"] != big]
    crystals.sort(key=lambda s: -s["ztop"])
    log("%d near-white islands, %d blue islands" % (int(near_white.sum()), len(crystals)))
    for s in crystals[:CORE_COUNT]:
        parts["SM_IceCluster_Core"].append(s["index"])
    lr_line = crystals[CORE_COUNT:]
    front = []
    for s in lr_line:
        # angle in the upright frame: local -Y (camera side, catches the hero spike
        # that leans to local +X and forward) is azimuth 0, +Y (behind the mound) is 180
        rel = xform_vec(s["centre"] - np.array([mcx, mcy, s["centre"][2]]), ROT_INV)
        azimuth = math.degrees(math.atan2(rel[0], -rel[1]))
        if abs(azimuth) > 180.0 - BACK_CONE_DEG:
            parts["SM_IceCluster_Back"].append(s["index"])
        else:
            front.append(s)
    # the burst's core: the longest crystals straight ahead; the big ones fanned out
    # to either side are the Left / Right wings
    front.sort(key=lambda s: -s["ztop"])
    core = [s for s in front if s["size"][2] >= CORE_HEIGHT_RATIO * s["size"][:2].max()][:CORE_COUNT]
    # only the genuinely tall spikes are Core; if the model has fewer, so be it
    for s in core:
        parts["SM_IceCluster_Core"].append(s["index"])
    for s in front:
        if s["index"] in parts["SM_IceCluster_Core"]:
            continue
        rel = xform_vec(s["centre"] - np.array([mcx, mcy, s["centre"][2]]), ROT_INV)
        name = "SM_IceCluster_Left" if rel[0] < 0 else "SM_IceCluster_Right"
        parts[name].append(s["index"])
    # non-mound near-white islands that are not big enough for Base part (none expected)
    for s in stats:
        i = s["index"]
        used = any(i in v for v in parts.values())
        log("ISLAND %2d verts=%4d colour=(%.2f %.2f %.2f) V=%.2f S=%.2f ctr=(%+.2f %+.2f) z=[%+.2f %+.2f] -> %s"
            % (i, s["verts"], *icol[i], ival[i], isat[i],
               s["centre"][0], s["centre"][1], s["zmin"], s["ztop"],
               [k for k, v in parts.items() if i in v] or "UNUSED"))
        if not used:
            raise RuntimeError("island %d not classified" % i)
    return parts


# ----------------------------------------------------------------------------- build
def build_part(src, name, island_ids, vert_island, loop_vert, loop_start, loop_total,
               offset, scale):
    """Copy the faces of the given islands into a new object (cm, pivot at origin)."""
    face_mask = np.isin(vert_island[loop_vert[loop_start]], island_ids)
    face_ids = np.nonzero(face_mask)[0]
    bm = bmesh.new()
    bm.from_mesh(src)
    bm.faces.ensure_lookup_table()
    keep = [bm.faces[i] for i in face_ids]
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f not in set(keep)], context="FACES")
    bm.verts.ensure_lookup_table()
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    mesh = bpy.data.meshes.new(name + "_mesh")
    bm.to_mesh(mesh)
    bm.free()
    # to source units -> cm, origin at the part's own pivot (decided below)
    off = np.asarray(offset, dtype=np.float64)
    co_old = np.array([v.co[:] for v in mesh.vertices])      # never iterate mesh.verts in place
    co_new = xform(co_old - off[None, :], ROT) * scale
    set_vertices(mesh, co_new)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    link_to_view_layer(obj)
    return obj


def rebuild_uv(obj):
    """U = azimuth around the part's axis (U=1 wraps back to the lowest seam vertex),
    V = 0 at the part's lowest vertex, 1 at its highest (orientation for FBX below)."""
    mesh = obj.data
    co = np.array([v.co[:] for v in mesh.vertices])
    low = co.min(0)[2]
    high = co.max(0)[2]
    height = max(high - low, 1e-6)
    centre = co.mean(0)
    ang = np.arctan2(co[:, 1] - centre[1], co[:, 0] - centre[0])   # -pi..pi
    u = (ang + math.pi) / (2.0 * math.pi)                           # 0..1
    v = np.clip((co[:, 2] - low) / height, 0.0, 1.0)
    # seam choice: the lowest vertex keeps U = 1 (was ~0) so V lines that run
    # bottom->top never jump across the U seam (UE World Aligned / growth masks).
    seam = int(np.lexsort((u, v))[0])
    u = u.copy()
    if u[seam] < 0.5:
        u = np.where(u < 0.5, u + 1.0, u)
    else:
        u = np.where(u >= 0.5, u - 1.0, u)
    # The seam vertex keeps U = 1 end-to-end; faces next to it are re-indexed so they
    # also read 1, not 0 (no horizontal jump across the seam).
    first_vert = np.array([p.vertices[0] for p in mesh.polygons], dtype=np.int64)
    hi_faces = (u[first_vert] >= 0.5)
    loop_vert = np.zeros(len(mesh.loops), dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", loop_vert)
    poly_loops = np.repeat(np.arange(len(mesh.polygons)), np.array([p.loop_total for p in mesh.polygons]))
    loop_hi = hi_faces[poly_loops]
    u_loop = u[loop_vert].copy()
    u_loop[loop_hi] = 1.0 + (u_loop[loop_hi] - 1.0) % 1.0
    # FBX (FBX_SCALE_NONE, no BakeSpaceTransform) applies a V-flip on export, so the
    # value that must reach UE as V is (1 - V_blender). (Verified by re-import round trip.)
    fbx_v = 1.0 - v
    uv_layer = mesh.uv_layers[0] if mesh.uv_layers else mesh.uv_layers.new(name="UVMap")
    uv = np.stack([u_loop, fbx_v[loop_vert]], axis=1)
    uv_layer.name = "UV0"
    uv_layer.data.foreach_set("uv", uv.ravel())
    mesh.update()


def placeholder_material(role):
    """Placeholder the UE side replaces with the cluster master material."""
    colour = {"prism": (0.10, 0.45, 0.95), "boulder": (0.80, 0.87, 0.95),
              "snowbase": (0.92, 0.95, 1.00)}[role]
    # one material per role (placeholder only -- UE replaces it with the cluster master material)
    mat = bpy.data.materials.get("MI_IceCluster_%s_Placeholder" % role.capitalize())
    if mat is not None:
        return mat
    mat = bpy.data.materials.new("MI_IceCluster_%s_Placeholder" % role.capitalize())
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*colour, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.25 if role == "prism" else 0.8
    mat.diffuse_color = (*colour, 1.0)
    return mat


def verify_uv(obj):
    """Self check: in the exported file UE must see V 0 at the bottom and 1 at the top.
    Blender stores the V-flipped values, so blender V should be 1 at the lowest vertex."""
    mesh = obj.data
    co = np.array([v.co[:] for v in mesh.vertices])
    loop_vert = np.array([l.vertex_index for l in mesh.loops])
    uv = np.array([tuple(l.uv) for l in mesh.uv_layers[0].data])
    lo, hi = int(np.argmin(co[:, 2])), int(np.argmax(co[:, 2]))
    v_lo = uv[loop_vert == lo][:, 1].mean()
    v_hi = uv[loop_vert == hi][:, 1].mean()
    ok = abs(v_lo - 1.0) < 1e-3 and abs(v_hi) < 1e-3
    log("UVCHECK %-22s V(blender) bottom=%.2f top=%.2f -> UE V bottom=%.2f top=%.2f  U=[%.2f %.2f]  %s"
        % (obj.name, v_lo, v_hi, 1.0 - v_lo, 1.0 - v_hi, uv[:, 0].min(), uv[:, 0].max(),
           "OK" if ok else "MISMATCH"))
    if not ok:
        raise RuntimeError("UV V orientation wrong on %s" % obj.name)


def set_shading(obj, hard):
    mesh = obj.data
    for poly in mesh.polygons:
        poly.use_smooth = True
    if hard:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        mod = obj.modifiers.new("EdgeSplit", "EDGE_SPLIT")
        mod.split_angle = SHARP_ANGLE
        mod.use_edge_angle = True
        mod.use_edge_sharp = False
        bpy.ops.object.modifier_apply(modifier=mod.name)
        obj.select_set(False)
    else:
        # gentle crease smoothing on the snow mound (weighted normals)
        for poly in mesh.polygons:
            poly.use_smooth = True
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        mod = obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
        mod.keep_sharp = True
        bpy.ops.object.modifier_apply(modifier=mod.name)
        obj.select_set(False)


def part_bounds(obj):
    co = np.array([v.co[:] for v in obj.data.vertices])
    return co.min(0), co.max(0)


# ----------------------------------------------------------------------------- render helpers
def add_camera(name, loc, rot, lens=35.0, sensor=36.0):
    data = bpy.data.cameras.new(name)
    data.lens = lens
    data.sensor_width = sensor
    cam = bpy.data.objects.new(name, data)
    cam.location = loc
    cam.rotation_euler = rot
    bpy.context.collection.objects.link(cam)
    link_to_view_layer(cam)
    return cam


def look_rotation(direction):
    """Euler (XYZ) that points a camera's -Z along `direction` with +Y up."""
    d = np.asarray(direction, dtype=np.float64)
    d = d / max(np.linalg.norm(d), 1e-9)
    pitch = math.acos(max(-1.0, min(1.0, -d[2])))     # 0 = straight down, pi = straight up
    yaw = math.atan2(-d[0], d[1])                     # camera forward = (sin yaw, -cos yaw)
    return (pitch, 0.0, yaw)


def project(pts, right, up, fwd):
    """world points (...,3) -> camera-plane/side X, Y and forward Z (broadcasting-safe)."""
    pts = np.asarray(pts, dtype=np.float64)
    x = pts[..., 0] * float(right[0]) + pts[..., 1] * float(right[1]) + pts[..., 2] * float(right[2])
    y = pts[..., 0] * float(up[0]) + pts[..., 1] * float(up[1]) + pts[..., 2] * float(up[2])
    z = pts[..., 0] * float(fwd[0]) + pts[..., 1] * float(fwd[1]) + pts[..., 2] * float(fwd[2])
    return x, y, z


def view_basis(rotation_euler):
    """Camera basis (right, up, forward) from its XYZ euler."""
    from mathutils import Euler  # local import only: importing mathutils at module load breaks Cycles
    rot = Euler(tuple(rotation_euler), "XYZ").to_matrix()
    return np.array(rot.col[0][:]), np.array(rot.col[1][:]), -np.array(rot.col[2][:])


def vsub(a, b):
    return np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)


def emission_material(name, rgb, strength=1.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    em = nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    em.inputs["Strength"].default_value = strength
    mat.node_tree.links.new(em.outputs[0], out.inputs[0])
    return mat


def diffuse_material(name, rgb, roughness=0.5):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = 0.0
    return mat


def human_stand_in():
    """A simple 180 cm human silhouette as one mesh at world coordinates (feet at z = 0,
    facing -Y): legs, hips, torso, neck, head and arms of a bmesh primitives."""
    import bmesh
    from mathutils import Matrix
    me = bpy.data.meshes.new("Human_180cm")
    bm = bmesh.new()
    for (x, y), z0, z1, r in (((-9, 0), 0, 82, 7.5), ((9, 0), 0, 82, 7.5),
                              ((-21, 0), 80, 150, 5.0), ((21, 0), 80, 150, 5.0)):
        bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=r, radius2=r, depth=z1 - z0,
                              matrix=Matrix.Translation((x, y, (z0 + z1) * 0.5)))
    for (x, y, z), (sx, sy, sz) in (((0, 0, 84), (16, 11, 10)), ((0, 0, 108), (18, 12, 26)),
                                    ((0, 0, 166), (9.5, 11, 12.5))):
        m = Matrix.Translation((x, y, z))
        m = m @ Matrix.Diagonal((sx, sy, sz, 1.0))
        bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=1.0, matrix=m)
    bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=5.0, radius2=5.0, depth=10,
                          matrix=Matrix.Translation((0, 0, 140)))
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("Human_180cm", me)
    bpy.context.collection.objects.link(obj)
    link_to_view_layer(obj)
    obj.data.materials.append(diffuse_material("M_Human_Silhouette", HUMAN_RGB, 0.8))
    zs = [v.co.z for v in me.vertices]
    log("figure: %d verts, %.0f..%.0f cm tall" % (len(me.vertices), min(zs), max(zs)))
    return [obj]


def link_to_view_layer(obj):
    """Blender 5.2 does NOT put a new object into the view layer's object list when it is
    added to a collection (collection.objects.link) -- link it there explicitly."""
    vl = bpy.context.view_layer
    if obj.name not in vl.objects:
        try:
            vl.objects.link(obj)
        except AttributeError:      # build without the VL API: keep it via the master collection
            if obj.name not in bpy.context.scene.collection.objects:
                bpy.context.scene.collection.objects.link(obj)


def set_world(rgb, strength=1.0):
    """Flat backdrop: every camera ray that misses the model sees exactly `rgb`."""
    world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    bg = nodes.get("Background")
    out = nodes.get("World Output")
    out = out or nodes.new("ShaderNodeOutputWorld")
    for node in list(nodes):
        if node is not out:
            nodes.remove(node)
    em = nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    em.inputs["Strength"].default_value = strength
    links.new(em.outputs[0], out.inputs[0])


def read_pixels(path):
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = "Non-Color"   # Raw render is already display values
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return px  # bottom-up rows


def make_camera(name, loc, rot, lens=50.0):
    """Camera factory used for previews. The default 1000-unit clip end is too short for
    this 7 m shot, and a nothing-visible frame is handled by the caller."""
    cam = add_camera(name, loc, rot, lens=lens)
    cam.data.clip_start = 0.1
    cam.data.clip_end = 30000.0
    return cam


def setup_workbench(scene):
    """Workbench is the only engine that renders this scene reliably headless here (the
    V1 computer -- Cycles goes black on the bottom-down mound and EEVEE needs a GPU)."""
    scene.render.engine = "BLENDER_WORKBENCH"
    shade = scene.display.shading
    shade.light = "FLAT"                  # exact material / vertex colours
    shade.color_type = "MATERIAL"         # material.diffuse_color
    shade.show_shadows = False
    shade.show_cavity = False
    shade.show_object_outline = False
    return scene


def render_flat(scene, camera, path, res, color_type="MATERIAL", transparent=False):
    """Workbench FLAT + MATERIAL with the 'Raw' view transform into an EXR: the file then
    holds exactly the material colours (0..1) plus the depth pass in alpha."""
    setup_workbench(scene)
    scene.display.shading.color_type = color_type
    scene.display.shading.show_shadows = False
    scene.display.shading.show_cavity = False
    scene.view_settings.view_transform = "Raw"          # no sRGB encode on the way out
    scene.view_layers[0].use_pass_z = True
    scene.camera = camera
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    scene.render.filepath = path
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = transparent
    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(path, check_existing=False)
    img.colorspace_settings.name = "Non-Color"   # Raw render is already display values
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return px


def write_pixels(path, px, name):
    bpy.context.scene.view_settings.view_transform = "Standard"
    h, w = px.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=True)
    img.pixels = px.ravel().tolist()
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def save_split_check(parts_objs, path):
    """Four views: split colours (persp + top) and raw tri-tone shading (front + persp)."""
    scene = bpy.context.scene
    set_world(hex_rgb(0xb5babf), 1.0)      # light grey plate to read the coloured parts
    # one material per colour so several objects can share it
    split_mats = {}
    for n in ORDER:
        key = FLAT_COLOURS[n]
        mat = bpy.data.materials.get("M_Split_%s_%s_%s" % tuple(int(c * 255) for c in key))
        if mat is None:
            mat = bpy.data.materials.new("M_Split_%s_%s_%s" % tuple(int(c * 255) for c in key))
            mat.diffuse_color = (*key, 1.0)
        split_mats[n] = mat
    for obj in parts_objs:
        obj.data.materials.clear()
        obj.data.materials.append(split_mats[obj.name])
    low = np.full(3, 1e9)
    high = np.full(3, -1e9)
    for obj in parts_objs:
        lo, hi = part_bounds(obj)
        low = np.minimum(low, lo)
        high = np.maximum(high, hi)
    centre = (low + high) * 0.5
    span = high - low
    dist = float(max(span)) * 1.6

    az = math.radians(28.0)
    el = math.radians(25.0)
    fov_v = 2.0 * math.atan(24.0 / 2.0 / 45.0)          # vertical fov of a 45 mm lens
    fit = max(float(max(span)), float(span[2]) * 1.15)  # horizontal fov is wider: fit height
    dist = (fit * 0.5) / math.tan(fov_v * 0.5) * 1.08
    pos = (centre[0] + math.sin(az) * math.cos(el) * dist,
           centre[1] + math.cos(az) * math.cos(el) * dist,
           centre[2] + math.sin(el) * dist)
    cam_persp = make_camera("Cam_SplitPersp", tuple(pos), look_rotation(vsub(centre, pos)), lens=45.0)
    cam_top = make_camera("Cam_SplitTop", (centre[0], centre[1], high[2] + 50.0),
                          look_rotation((0, 0, -1)), lens=45.0)
    cam_top.data.type = "ORTHO"
    cam_top.data.ortho_scale = float(max(span[0], span[1])) * 1.1
    cam_top.location.z = centre[2] + dist
    cam_front = make_camera("Cam_SplitFront", (centre[0], -dist * 0.55, centre[2] + 60.0),
                            look_rotation((0, 1, 0)), lens=45.0)
    cam_front.data.type = "ORTHO"
    cam_front.data.ortho_scale = float(max(span[0], span[2])) * 1.1
    res = (1024, 1024)
    for ob in bpy.context.scene.objects:
        if ob.name.startswith("Human_"):
            ob.hide_render = True
    plane = bpy.data.objects.get("BG_Ground")
    if plane:
        plane.hide_render = True
    set_world(tuple(c * c for c in hex_rgb(0xb5babf)), 1.0)   # linear grey plate (Raw output)
    tiles = [render_flat(scene, cam_persp, "/tmp/ice_split_check_persp.exr", res),
             render_flat(scene, cam_top, "/tmp/ice_split_check_top.exr", res),
             render_flat(scene, cam_front, "/tmp/ice_split_check_front.exr", res)]
    h, w = tiles[0].shape[:2]
    sheet = np.ones((h, w * 3, 4), dtype=np.float32)
    for idx, tile in enumerate(tiles):
        disp = tile.copy()
        disp[..., :3] = srgb_from_linear(disp[..., :3])      # EXR is linear; the sheet is sRGB-encoded
        sheet[:, idx * w:(idx + 1) * w] = disp
    write_pixels(path, sheet, "IceBurst_v3_split_check")
    log("SPLIT CHECK", path, "(left: 3/4 view | middle: top view | right: front ortho; "
        "Core red, Left green, Right magenta, Back cyan, Boulders yellow, Base white)")


def ensure_bg(world_rgb, ground_rgb):
    """World colour (Workbench background) + one large ground plane."""
    global BACKDROP_LINEAR
    BACKDROP_LINEAR = tuple(c * c for c in world_rgb)
    scene = bpy.context.scene
    set_world(world_rgb, 1.0)
    plane = bpy.data.objects.get("BG_Ground")
    if plane is None:
        bpy.ops.mesh.primitive_plane_add(size=9000, location=(0.0, 0.0, -2.0))
        plane = bpy.context.active_object
        plane.name = "BG_Ground"
        link_to_view_layer(plane)
        mat = bpy.data.materials.new("M_BG_Ground")
        plane.data.materials.append(mat)
    plane.data.materials[0].diffuse_color = (*ground_rgb, 1.0)
    plane.hide_render = False
    return plane


def paint_vertex_colours(obj, fn):
    """Bake node-style colours into a corner colour attribute (Workbench FLAT + MATERIAL
    ignores node trees, so the figure's ramp / sheen lives in vertices)."""
    mesh = obj.data
    attr = mesh.color_attributes.get("Col") or mesh.color_attributes.new(name="Col", type="BYTE_COLOR",
                                                                         domain="CORNER")
    co = np.array([v.co[:] for v in mesh.vertices], dtype=np.float64).reshape(-1, 3)
    loop_vert = np.array([l.vertex_index for l in mesh.loops], dtype=np.int64)
    loop_total = np.array([p.loop_total for p in mesh.polygons], dtype=np.int64)
    loop_poly = np.repeat(np.arange(len(mesh.polygons)), loop_total)
    poly_nrm = np.array([p.normal[:] for p in mesh.polygons], dtype=np.float64)
    nrm = poly_nrm[loop_poly]
    rgba = fn(co[loop_vert], nrm, co)
    attr.data.foreach_set("color", np.ascontiguousarray(rgba, dtype=np.float32).ravel())
    mesh.update()


def vertex_colour_material(name, fallback):
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    attr = nt.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "Col"
    nt.links.new(attr.outputs["Color"], bsdf.inputs["Base Color"])
    mat.diffuse_color = (*fallback, 1.0)
    return mat


def dot_mask_at(px, rgb, tol):
    return ((px[..., 0] - rgb[0]) ** 2 + (px[..., 1] - rgb[1]) ** 2 + (px[..., 2] - rgb[2]) ** 2) < tol * tol


def fov_scale(camera, res):
    w, h = res
    fit = camera.data.sensor_fit
    if fit == "VERTICAL" or (fit == "AUTO" and h > w):
        return (camera.data.lens / camera.data.sensor_width) * h
    return (camera.data.lens / camera.data.sensor_width) * w


def encode_normal_colours(obj):
    """Vertex colours = world normal * 0.5 + 0.5 (per corner).  Workbench FLAT + VERTEX can
    read them, so the three tones can be derived in a later pass without any Cycles."""
    mesh = obj.data
    attr = mesh.color_attributes.get("NrmCol") or mesh.color_attributes.new(name="NrmCol",
                                                                           type="BYTE_COLOR", domain="CORNER")
    co = np.array([v.co[:] for v in mesh.vertices], dtype=np.float64)
    loop_vert = np.array([l.vertex_index for l in mesh.loops], dtype=np.int64)
    loop_total = np.array([p.loop_total for p in mesh.polygons], dtype=np.int64)
    loop_poly = np.repeat(np.arange(len(mesh.polygons)), loop_total)
    pn = np.array([p.normal[:] for p in mesh.polygons], dtype=np.float64)
    n = pn[loop_poly]
    rgba = np.concatenate([(n * 0.5 + 0.5), np.ones((len(n), 1))], axis=1)
    attr.data.foreach_set("color", np.ascontiguousarray(rgba, dtype=np.float32).ravel())
    mesh.update()


def near_white_colour(obj):
    return (0.93, 0.95, 0.98) if obj.name == "SM_IceCluster_Base" else (0.84, 0.89, 0.96)


def render_compare_view(scene, camera, res, built, human_objs):
    """Two Workbench passes (Cycles is unusable in this headless build):
      A. burst crystals + near-white parts with their real colours
      B. every crystal's VERTEX normals encoded as colours (see encode_normal_colours)
    From B each crystal pixel's normal picks the tone (#9fdcff / #2f8fe6 / #0b3aa0) and that
    tone replaces the pixel in A; the ground gets a contact shadow from the crystal mask.
    Returns display-space (sRGB-encoded) pixels."""
    crystals = [o for o in built if o.name in CRYSTALS]
    white = [o for o in built if o.name not in CRYSTALS]
    for o in white:
        o.data.materials[0].diffuse_color = (*near_white_colour(o), 1.0)
    ground = bpy.data.objects.get("BG_Ground")
    ground_col = (0.014, 0.017, 0.030)
    if ground is not None:
        ground.data.materials[0].diffuse_color = (*ground_col, 1.0)
    flat = render_flat(scene, camera, "/tmp/ice_compare_flat.exr", res)
    disp = flat.copy()
    disp[..., :3] = srgb_from_linear(disp[..., :3])
    # pass B: normals as vertex colours
    for o in crystals:
        encode_normal_colours(o)
    hidden = [o for o in bpy.context.scene.objects if o.type == "MESH" and o not in crystals]
    for o in hidden:
        o.hide_render = True
    npx = render_flat(scene, camera, "/tmp/ice_compare_normals.exr", res, color_type="VERTEX",
                      transparent=True)
    for o in hidden:
        o.hide_render = False
    nrm = npx[..., :3] * 2.0 - 1.0
    light = np.array((0.18, 0.62, 0.76))          # key from upper front/right, like ref_04.00
    light = light / np.linalg.norm(light)
    lam = nrm[..., 0] * light[0] + nrm[..., 1] * light[1] + nrm[..., 2] * light[2]
    # pass B: crystals only, transparent elsewhere.  (EXR's alpha is always 1 in this
    # build, so read the empty space as the backdrop colour instead.)
    # (EXR alpha is always 1 in this build; the "empty" pixels are exactly the backdrop colour)
    empty = (npx[..., 0] < 0.004) & (npx[..., 1] < 0.004) & (npx[..., 2] < 0.004)
    crystal_px = ~empty
    dark, mid, bright = [np.array(t, np.float32) for t in TRI_TONES]
    tone = np.where((lam > 0.50)[..., None], bright, np.where((lam > -0.05)[..., None], mid, dark))
    disp[..., :3] = np.where(crystal_px[..., None], tone, disp[..., :3])
    # contact shadow on the ground just around / under the burst (darken only ground
    # pixels within ~22 px of a crystal pixel; the crystals themselves keep their tone)
    d = crystal_px.astype(np.float32)
    for _ in range(int(round(14 * res[0] / 1024.0))):
        d = np.maximum(np.maximum(np.roll(d, 1, 0), np.roll(d, -1, 0)),
                       np.maximum(np.roll(d, 1, 1), np.roll(d, -1, 1)))
    shadow_fac = (1.0 - 0.38 * d)[..., None]
    ground_px = ~crystal_px
    out = disp.copy()
    out[..., :3] = out[..., :3] * shadow_fac
    out = np.where(crystal_px[..., None], disp, out)
    log("compare: %d crystal px, tone light/mid/dark = %.0f%%/%.0f%%/%.0f%%" % (
        int(crystal_px.sum()), 100 * float(((lam > 0.50) & crystal_px).sum()) / max(1, crystal_px.sum()),
        100 * float(((lam > -0.05) & (lam <= 0.50) & crystal_px).sum()) / max(1, crystal_px.sum()),
        100 * float(((lam <= -0.05) & crystal_px).sum()) / max(1, crystal_px.sum())))
    return out


def render_compare(built, path):
    """Oblique ~25 deg view, three-tone crystals, near-white snow / boulders, 180 cm
    figure at the origin; stitched next to ref_04.00.jpg."""
    scene = bpy.context.scene
    set_world(hex_rgb(0x0f1622), 1.0)
    white = diffuse_material("M_NearWhite", (0.93, 0.95, 0.98), 0.9)
    boulder_mat = diffuse_material("M_Boulder", (0.84, 0.89, 0.96), 0.8)
    tri = diffuse_material("M_Crystal_Flat", (1.0, 1.0, 1.0), 0.3)   # marker: recoloured in compositing
    for obj in built:
        obj.data.materials.clear()
        if obj.name in CRYSTALS:
            obj.data.materials.append(tri)
        elif obj.name == "SM_IceCluster_Base":
            obj.data.materials.append(white)
        else:
            obj.data.materials.append(boulder_mat)

    ground = ensure_bg(hex_rgb(0x141b26), (0.24, 0.27, 0.33))

    human_objs = human_stand_in()
    for ob in human_objs:
        link_to_view_layer(ob)
        ob.data.materials.clear()
        ob.data.materials.append(diffuse_material("M_Human_Silhouette", HUMAN_RGB, 0.8))

    low = np.full(3, 1e9)
    high = np.full(3, -1e9)
    for obj in built:
        lo, hi = part_bounds(obj)
        low = np.minimum(low, lo)
        high = np.maximum(high, hi)
    # Frame it like ref_04.00.jpg (a design shot, not a scale diagram): oblique ~25 deg,
    # the burst filling the square frame, the figure reading at ~1/7 of the frame height.
    frame_span = 900.0
    target = np.array((0.0, 0.0, high[2] * 0.55))
    el = math.radians(30.0)                                          # ref_04.00 looks ~30 deg down
    az = math.radians(20.0)
    fov = 2.0 * math.atan(36.0 / 2.0 / 50.0)                         # 50 mm, 1:1 frame
    dist = (frame_span * 0.5) / math.tan(fov * 0.5)
    pos = (target[0] + math.sin(az) * math.cos(el) * dist,
           target[1] + math.cos(az) * math.cos(el) * dist,
           target[2] + math.sin(el) * dist)
    cam = make_camera("Cam_Compare", pos, look_rotation(vsub(target, pos)), lens=50.0)
    scene.camera = cam
    render_px = render_compare_view(scene, cam, (1024, 1024), built, human_objs)
    # fresh C-order float64 arrays for the image writes (a strided numpy view handed to
    # image.pixels can be misread -- allocate plainly)
    render_px = np.array(render_px, dtype=np.float64)
    render_px = render_px.copy()
    render_px[..., :3] = srgb_from_linear(render_px[..., :3])
    ref = bpy.data.images.load(os.path.join(PROJECT, "SourceAssets/Reference/frames/ref_04.00.jpg"))
    ref.colorspace_settings.name = "Non-Color"     # read the stored sRGB values untouched
    rw, rh = ref.size
    rpx = np.array(ref.pixels[:], dtype=np.float32).reshape(rh, rw, 4)
    # crop the letterbox bars (rows with no picture content above / below the frame)
    rows_on = np.nonzero(rpx[..., :3].mean(axis=(1, 2)) > 0.02)[0]
    rpx = rpx[rows_on.min():rows_on.max() + 1]
    bpy.data.images.remove(ref)
    h, w = render_px.shape[:2]
    tw = int(round(w * rpx.shape[1] / rpx.shape[0]))
    yi = np.clip((np.arange(h) * rpx.shape[0] / h).astype(int), 0, rpx.shape[0] - 1)
    xi = np.clip((np.arange(tw) * rpx.shape[1] / tw).astype(int), 0, rpx.shape[1] - 1)
    ref_r = rpx[yi][:, xi]
    sheet = np.array(np.concatenate([ref_r, render_px], axis=1), dtype=np.float64)
    write_pixels(path, sheet, "IceBurst_v3_tripo_compare")
    log("COMPARE", path)


# ----------------------------------------------------------------------------- main
def main():
    clear_scene()
    src = import_source()
    log("source", src.name, "verts", len(src.data.vertices), "faces", len(src.data.polygons))
    co, loop_vert, uv, loop_start, loop_total, poly_of_loop = mesh_arrays(src.data)
    px = load_basecolor(src.data)
    vis = islands_of(src.data)
    face_rgb, face_srgb_eager = sample_faces(px, co, loop_vert, uv, loop_start, loop_total, poly_of_loop)
    face_srgb, face_val, face_sat = colour_stats(face_rgb)
    log("eager-mean check: face brightness p10/50/90 = %.2f/%.2f/%.2f"
        % tuple(np.percentile(colour_stats(face_srgb_eager)[1], [10, 50, 90]).round(2)))
    log("sampled %d faces (%d samples each); face brightness p10/50/90 = %.2f/%.2f/%.2f, "
        "saturation p10/50/90 = %.2f/%.2f/%.2f"
        % (len(face_val), SAMPLES_PER_FACE, *np.percentile(face_val, [10, 50, 90]).round(2),
           *np.percentile(face_sat, [10, 50, 90]).round(2)))

    parts = classify(co, vis, face_rgb, loop_vert, loop_start)

    # ---- scale: mound width -> MOUND_WIDTH_CM
    base_ids = parts["SM_IceCluster_Base"]
    base_pts = co[np.isin(vis, base_ids)]
    mound_w = float(max(base_pts[:, 0].max() - base_pts[:, 0].min(),
                        base_pts[:, 1].max() - base_pts[:, 1].min()))
    scale = MOUND_WIDTH_CM / mound_w
    log("mound width in model units = %.4f -> scale %.2f (cm per unit)" % (mound_w, scale))

    # ---- pivot: centre of the mound's top surface, at ground level (mound bottom)
    rot_all = xform(co, ROT)                # model in the upright frame (Z up)
    rot_pts = rot_all[np.isin(vis, base_ids)]
    top_z = rot_pts[:, 2].max()
    top_pts = rot_pts[rot_pts[:, 2] > top_z - 0.06 * (top_z - rot_pts[:, 2].min())]
    pivot = np.array([0.5 * (top_pts[:, 0].min() + top_pts[:, 0].max()),
                      0.5 * (top_pts[:, 1].min() + top_pts[:, 1].max()),
                      rot_pts[:, 2].min()])
    mound_size_cm = (rot_pts.max(0) - rot_pts.min(0)) * scale
    log("mound width/depth/height at the end = %.1f x %.1f x %.1f cm (mound diameter target %.0f)"
        % (mound_size_cm[0], mound_size_cm[1], mound_size_cm[2], MOUND_WIDTH_CM))
    log("pivot (model units) = %s" % (pivot.round(4),))
    centre_cm = ((rot_all.min(0) + rot_all.max(0)) * 0.5 - pivot) * scale
    log("model centre relative to the stand point = (%.1f, %.1f, %.1f) cm; full bbox %.1f x %.1f x %.1f cm"
        % (centre_cm[0], centre_cm[1], centre_cm[2], *(np.ptp(rot_all, axis=0) * scale)))

    built = []
    for name in ORDER:
        if not parts[name]:
            raise RuntimeError("part %s empty" % name)
        obj = build_part(src.data, name, parts[name], vis, loop_vert, loop_start, loop_total,
                         pivot, scale)
        rebuild_uv(obj)
        verify_uv(obj)
        set_shading(obj, hard=name in CRYSTALS)
        obj.data.materials.clear()
        obj.data.materials.append(placeholder_material(MATERIAL_ROLE[name]))
        obj.location = (0.0, 0.0, 0.0)
        obj.rotation_euler = (0.0, 0.0, 0.0)
        obj.scale = (1.0, 1.0, 1.0)
        built.append(obj)
    bpy.data.objects.remove(src, do_unlink=True)

    # ---- final placement: Z up, ground at the mound bottom; then aim the model's burst
    # centre at the stand point (character stands on top of the mound, at its centre)
    shift = np.array([0.0, 0.0, -min(part_bounds(o)[0][2] for o in built)])
    ang = math.radians(AIM_YAW_DEG)
    Rz = np.array([[math.cos(ang), -math.sin(ang), 0.0], [math.sin(ang), math.cos(ang), 0.0], [0.0, 0.0, 1.0]])
    all_lo = np.min([part_bounds(o)[0] for o in built], axis=0) + shift
    all_hi = np.max([part_bounds(o)[1] for o in built], axis=0) + shift
    burst_centre = (all_lo + all_hi) * 0.5
    log("burst centre before aim = (%.1f, %.1f, %.1f) cm" % tuple(burst_centre))
    for obj in built:
        co_old = np.array([v.co[:] for v in obj.data.vertices]) + shift[None, :]
        co_new = xform(co_old - np.array([burst_centre[0], burst_centre[1], 0.0])[None, :], Rz)
        set_vertices(obj.data, co_new)
    log("stand point (origin, ground) sits on the mound top surface centre; full centre now %s"
        % ((np.min([part_bounds(o)[0] for o in built], axis=0) + np.max([part_bounds(o)[1] for o in built], axis=0)) * 0.5).round(1))

    report = []
    for obj in built:
        lo, hi = part_bounds(obj)
        size = hi - lo
        report.append(dict(name=obj.name, faces=len(obj.data.polygons), verts=len(obj.data.vertices),
                           size_m=[round(float(v) / 100.0, 3) for v in size],
                           z_range=[round(float(lo[2]) / 100.0, 3), round(float(hi[2]) / 100.0, 3)]))
        log("PART %-22s faces=%5d verts=%5d size_cm=(%.1f %.1f %.1f) z=[%.1f %.1f]"
            % (obj.name, len(obj.data.polygons), len(obj.data.vertices), *size, lo[2], hi[2]))
    total = sum(r["faces"] for r in report)
    full_lo = np.min([part_bounds(o)[0] for o in built], axis=0)
    full_hi = np.max([part_bounds(o)[1] for o in built], axis=0)
    log("TOTAL faces=%d  overall size_cm=(%.1f %.1f %.1f)  z=[%.1f %.1f]"
        % (total, *(full_hi - full_lo), full_lo[2], full_hi[2]))

    # ---- export (geometry baked in cm, pivots at 0,0,0)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in built:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = built[0]
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
        use_mesh_modifiers=True,
        add_leaf_bones=False,
        path_mode="STRIP",
    )
    log("EXPORTED", OUT_FBX)

    with open(OUT_JSON, "w") as handle:
        json.dump(report, handle, indent=2)
    log("JSON", OUT_JSON)

    update_data_json(report)

    save_split_check(built, SPLIT_PNG)
    render_compare(built, COMPARE_PNG)


def update_data_json(report):
    with open(DATA_JSON) as handle:
        data = json.load(handle)
    by_name = {r["name"]: r for r in report}
    cluster_parts = []
    for name in ORDER:
        r = by_name[name]
        cluster_parts.append(dict(
            name=name,
            pivot_cm=[0.0, 0.0, 0.0],
            rotation_deg={"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            size_cm=[round(r["size_m"][0] * 100.0, 1), round(r["size_m"][1] * 100.0, 1),
                     round(r["size_m"][2] * 100.0, 1)],
            faces=r["faces"],
            material_role=MATERIAL_ROLE[name],
        ))
    data["cluster_parts"] = cluster_parts
    data["cluster_scale"] = 1.0
    data["cluster_center_cm"] = [0.0, 0.0, 0.0]
    with open(DATA_JSON, "w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    log("UPDATED", DATA_JSON)


main()