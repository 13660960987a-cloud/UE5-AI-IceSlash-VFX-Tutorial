"""Procedural Ice Burst v3: white snow mound + radial blue ice shards (UE-ready, baked cm).

Reference: SourceAssets/Reference/frames/ref_03.50 / 03.75 / 04.00 / 04.50 (Ice Slash VFX).
The burst is centred on the character: a flat white snow dome (r ~170 cm, h ~55 cm, the
character stands at its centre), blue spear-like ice shards bursting outwards all around,
flatter and longer toward the rim and steeper near the middle, three hero shards (the longest
leaning up and to the right-back), white faceted ice chunks at the character's feet and three
small debris meshes for Niagara.

Parts (the six names the IceSlash pipeline already consumes, each one merged object):
    SM_IceCluster_Core      hero shards (3, the longest 520 cm)
    SM_IceCluster_Left      shards whose outbreak direction is character-left  (Blender -Y)
    SM_IceCluster_Right     shards on character-right                          (Blender +X)
    SM_IceCluster_Back      shards behind the character                        (Blender +Y)
    SM_IceCluster_Boulders  white faceted ice chunks at the feet (5)
    SM_IceCluster_Base      snow mound
    SM_IceDebris_01..03     Niagara debris shards (10-25 cm)

Conventions (same as Tools/IceSlash/data/rescale_fbx_cm.py):
    * Blender Z-up, character faces +Y, character's left is -Y (the v2 split script's
      convention); one shard's "azimuth" is measured from +Y toward +X.
    * Geometry is in centimetres, baked into the vertex data; every object sits at the origin
      with identity transform and is exported with FBX_SCALE_NONE. UE's FBX import maps that to
      (x, -y, z) cm: Blender +Y -> UE forward, Blender +X -> UE right, so the +Y/+X hero shard
      is the UE right-back one.
    * Hard edges: flat shading, one normal per face (custom split normals), FBX mesh_smooth OFF.
    * UV0: each crystal island is unwrapped on its own. V = 0 at the root cross-section and 1 at
      the tip, taken along the nearest point of the shard axis (monotonic along the shard);
      U = 0..1 around the shard, one column per facet. UE's FBX importer flips V for
      axis_forward -Y, so in UE a shard reads root V = 1 -> tip V = 0; the parts JSON records
      this as uv_root_v / uv_tip_v. Boulders, debris and mound: U around, V by height.
    * The parts JSON keeps the v2 file shape (name, faces, verts, size_m, z_range) so the
      existing importer consumes it unchanged; size_m is the true metre size.

Run:
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
        -P SourceAssets/IceCrystal/generate_ice_burst_v3.py

Writes (next to this script): SM_IceCluster_v3_cm.fbx, SM_IceDebris_v3_cm.fbx,
SM_IceCluster_v3_parts.json, IceBurst_v3_preview.png (render | ref_04.00 side by side).
"""

import json
import math
import os
import random

import bpy
import bmesh
import numpy as np
from mathutils import Euler, Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT_CLUSTER_FBX = os.path.join(HERE, "SM_IceCluster_v3_cm.fbx")
OUT_DEBRIS_FBX = os.path.join(HERE, "SM_IceDebris_v3_cm.fbx")
OUT_PARTS_JSON = os.path.join(HERE, "SM_IceCluster_v3_parts.json")
OUT_PREVIEW_PNG = os.path.join(HERE, "IceBurst_v3_preview.png")
OUT_PREVIEW_SIDE = os.path.join(HERE, "IceBurst_v3_render.png")
REF_FRAME = os.path.join(ROOT, "SourceAssets", "Reference", "frames", "ref_04.00.jpg")
DATA_JSON = os.path.join(ROOT, "Tools", "IceSlash", "data", "ice_slash_data.json")

SEED = 260418
CLUSTER_PARTS = ["SM_IceCluster_Core", "SM_IceCluster_Left", "SM_IceCluster_Right",
                 "SM_IceCluster_Back", "SM_IceCluster_Boulders", "SM_IceCluster_Base"]
ROLE = {"SM_IceCluster_Core": "prism", "SM_IceCluster_Left": "prism",
        "SM_IceCluster_Right": "prism", "SM_IceCluster_Back": "prism",
        "SM_IceCluster_Boulders": "boulder", "SM_IceCluster_Base": "snowbase"}
DEBRIS_PARTS = ["SM_IceDebris_01", "SM_IceDebris_02", "SM_IceDebris_03"]

# ---- layout (cm) --------------------------------------------------------------------------
MOUND_R = 170.0
MOUND_R_SCALE = 0.85          # silhouette ~1.3x wider than tall vs the mound, like the ref

MOUND_H = 55.0
NO_CRYSTAL_R = 45.0
RING_R = (60.0, 150.0)
MID_COUNT = 27                 # ring shards; + 3 heroes = 30 crystals
HERO_COUNT = 1                 # one hero: the long right-back crystal (task B allows 3-4)
# HERO_HEADING is measured from +Y toward +X, but the tips lean further out than the roots, so
# the direction used for the tilt points further out: 45 deg (UE right-back) ~ 55 / 125 here.
HERO_MAX = 520.0
HERO_ANGLE = (50.0, 62.0)
HERO_INNER = (0.62, 0.80)      # index 0 takes the top of the band
HERO_HEADING = 52.0            # tilt direction of the long hero (tips: UE right-back-up)
SHARD_LEN = (160.0, 390.0)
SHARD_ASPECT = (5.0, 8.5)
SHARD_TILT = (15.0, 40.0)
INNER_TILT = (68.0, 80.0)      # innermost ring: upright blades, as tall as the heroes
INNER_TILT_R = RING_R[0] + 0.25 * (RING_R[1] - RING_R[0])   # ... inside this ring radius
INNER_COUNT = 3                # inner blades, packed close together (they burst as a bundle)
FOOTPRINT_MAX = 360.0          # tips: within ~2x the mound radius of the centre
BOULDER_SIZE = (24.0, 44.0)
BOULDER_ARC = (95.0, 265.0)    # azimuth of the feet chunks (front of the character = 0)
BOULDER_COUNT = 6
DEBRIS_SIZE = (10.0, 25.0)
ELEV_DEG = 25.0                # preview camera: ~25 deg oblique top-down
DIST_CM = 960.0                # preview camera: target distance (~9.6 m; the bursts fills the frame)
TILT_REF = 42.0                # the tilt axis of the ball-and-socket base (base-normal blend)
CAMERA_TARGET = Vector((10.0, -10.0, 215.0))


def r2(value, digits=2):
    return round(float(value), digits)


# ==========================================================================================
# primitives
# ==========================================================================================
def direction(az_deg, tilt_deg, plane_deg=0.0):
    """Unit direction from an azimuth (from +Y toward +X) and a tilt away from the tilt plane
    (the ground when plane_deg = 0). An azimuth of 90 deg points along +X, 180 deg along -Y
    (the character's left), 270 deg along -X."""
    az, el = math.radians(az_deg), math.radians(tilt_deg)
    return Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el),
                   math.sin(el))).normalized()


def tangent_basis(axis, roll_deg, flatten=1.0):
    """Orthonormal (u, v) across `axis`: u = wide direction (horizontal unless the axis is
    vertical), v = thin direction scaled by `flatten`. `roll` turns u about the axis."""
    h = Vector((axis.y, -axis.x, 0.0))
    if h.length < 1e-4:
        h = Vector((1.0, 0.0, 0.0))
    h.normalize()
    v0 = axis.cross(h).normalized()
    roll = math.radians(roll_deg)
    u = (h * math.cos(roll) + v0 * math.sin(roll)).normalized()
    return u, axis.cross(u).normalized() * flatten


def hex_point(c, u, v, ru, rv, phase, k):
    ang = math.radians(k * 60.0) + phase
    return c + u * (ru * math.cos(ang)) + v * (rv * math.sin(ang))


def hex_support(ru, rv, phase, k):
    """Distance from the ring centre to hexagon vertex k along the (u, v) ellipse."""
    ang = math.radians(k * 60.0) + phase
    return 1.0 / (math.cos(ang) / max(ru, 1e-6) + math.sin(ang) / max(rv, 1e-6))


# ==========================================================================================
# shards
# ==========================================================================================
def make_shard(rng, root, azimuth, tilt, length, width, roll=0.0, flat=0.8, tilt_from_ground=True):
    """One ice spear.

    Stations along the axis: neck (0.34 w) -> shoulder (1.0 w) -> 2-3 knuckles tapering to the
    neck again, then a short hooked apex capped by 1-2 oblique fracture facets (single columns
    broken early), so both ends read as broken ice instead of two hexagon pyramids.
    `tilt` is the elevation above the ground for the ring shards and the tilt away from the
    socket plane for the near-vertical inner heroes.
    Returns verts, faces, tip vertex index and the axis path used for the U/V mapping.
    """
    axis = direction(azimuth, tilt if tilt_from_ground else TILT_REF + tilt)
    if not tilt_from_ground:
        # the hero keeps its measured elevation; the reference plane only decides verticality
        axis = (direction(azimuth, tilt) + Vector((0.0, 0.0, 0.12))).normalized()
    u, v = tangent_basis(axis, roll, flat)
    root = Vector(root)
    phase = rng.uniform(0.0, math.pi / 3.0)
    shoulder = rng.uniform(0.11, 0.20)
    knuckles = rng.choice((2, 3))
    top = rng.uniform(0.56, 0.70)
    tip_dir = (axis + Vector((0.0, 0.0, rng.uniform(0.10, 0.30)))).normalized()   # slightly hooked
    stations = [(0.0, 0.34), (shoulder, 1.0)]
    for i in range(1, knuckles + 1):
        f = i / knuckles
        stations.append((shoulder + (top - shoulder) * f, 0.34 + 0.66 * (1.0 - f) ** 1.2))
    # a slight bend over the length so shards are not ruler-straight
    wobble = Vector((rng.uniform(-0.035, 0.035) * length, rng.uniform(-0.035, 0.035) * length,
                     rng.uniform(0.0, 0.03) * length))

    def station_centre(t):
        return root + axis * (t * length) + wobble * (t * t)

    verts, cols, rings = [], [[] for _ in range(6)], []
    for t, s in stations:
        c = station_centre(t)
        # widths vary between stations so blades bulge and pinch like split ice
        s = s * rng.uniform(0.86, 1.08) if 0.0 < t < top else s
        rows = []
        for k in range(6):
            rows.append(len(verts))
            verts.append(hex_point(c, u, v, width * s, width * s * flat, phase, k))
        rings.append((c, width * s, rows))
        for k in range(6):
            cols[k].append(rows[k])

    # Apex: a short hooked point plus up to two oblique fracture caps on single columns.
    neck_c, neck_w, neck_rows = rings[-1]
    axial = (length - (neck_c - root).length) * rng.uniform(0.45, 0.75)
    apex = neck_c + tip_dir * axial
    chips = rng.sample(range(6), 2) if rng.random() < 0.75 else []
    for k in chips:
        kr = hex_support(neck_w, neck_w * flat, phase, k)
        pt = hex_point(neck_c, u, v, neck_w, neck_w * flat, phase, k)
        rise = max(rng.uniform(0.35, 0.85) * kr, neck_w * 1.2)    # a visible oblique fracture
        cols[k].append(len(verts))
        verts.append(pt + tip_dir * rise + (neck_c - pt) * 0.05)
    apex_index = len(verts)
    verts.append(apex)

    faces = []
    for k in range(6):
        k2 = (k + 1) % 6
        a, b = cols[k], cols[k2]
        for i in range(min(len(a), len(b)) - 1):
            faces.append((a[i], b[i], b[i + 1], a[i + 1]))
        faces.append((a[-1], b[-1], apex_index))                 # cap facet / fan to the apex
    path = [root, station_centre(top * 0.5), neck_c, apex]
    return verts, faces, apex_index, path


# ==========================================================================================
# irregular faceted chunks and the mound
# ==========================================================================================
def make_chunk(rng, centre, radius, flatten_z=1.0, subdiv=1, jitter=0.28, stretch=None):
    """Low-poly irregular faceted polyhedron: icosphere (level 1 -> 20 faces, 2 -> 80) with
    every vertex pushed/pulled at random, optionally stretched per axis and dropped onto
    `centre` (its lowest point sits at centre.z)."""
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1.0)
    for vert in bm.verts:
        vert.co = vert.co.normalized() * (1.0 + rng.uniform(-jitter, jitter))
    sx, sy, sz = stretch or (1.0, 1.0, flatten_z)
    bm.verts.index_update()
    pts = [Vector((v.co.x * radius * sx, v.co.y * radius * sy, v.co.z * radius * sz)) for v in bm.verts]
    faces = [tuple(v.index for v in f.verts) for f in bm.faces]
    bm.free()
    ground = min(Vector(centre).z, 0.0)
    low = min(p.z for p in pts)
    lift = Vector(centre) - Vector((0.0, 0.0, low))              # bottom at centre.z
    verts = [p + lift for p in pts]
    return verts, faces


def mound_height(x, y):
    """Snow dome height at (x, y); the top is flattened around the character."""
    d = min(1.0, math.hypot(x, y) / (MOUND_R * MOUND_R_SCALE))
    return MOUND_H * (1.0 - d * d) ** 0.62


def make_mound(rng, segments=40):
    """Snow dome: a fan of polygonal rings. Flat-ish top around the character, the slope steepens
    toward a bulging white skirt whose rim wobbles (a few lobes), the rim pushed out to the
    right, and a slightly shorter back lip so the cut side is tucked behind the burst."""
    lobes = [(rng.uniform(0.0, 6.283), f, rng.uniform(0.03, 0.07)) for f in (2, 3, 5)]
    rings_t = [0.0, 0.16, 0.32, 0.48, 0.62, 0.74, 0.84, 0.92, 0.97, 1.0]
    lean = (-0.10, rng.uniform(-0.08, 0.08))       # rim pushed to -X (image right from this camera)
    verts = [Vector((0.0, 0.0, MOUND_H))]
    rows = []
    for ri, r in enumerate(rings_t):
        if r == 0.0:
            continue
        row = []
        for s in range(segments):
            ang = 2.0 * math.pi * s / segments
            wob = sum(a * math.sin(f * ang + ph) for ph, f, a in lobes) * (r ** 2)
            rr = MOUND_R * MOUND_R_SCALE * r * (1.0 + wob)
            z = MOUND_H * (1.0 - r * r) ** 0.62 * (1.0 + 0.05 * math.sin(3.0 * ang + ri))
            if r >= 0.97:                                     # last ring: cut just above the floor
                z *= (1.0 - (r - 0.97) / 0.03) * 0.3
            z -= max(0.0, -math.sin(ang)) * 7.0 * (r ** 4)    # shorter lip behind (+Y is front)
            ox = lean[0] * rr * 0.35 * (r ** 1.5)
            oy = lean[1] * rr * 0.35 * (r ** 1.5)
            row.append(len(verts))
            verts.append(Vector((rr * math.sin(ang) + ox, rr * math.cos(ang) + oy, max(0.0, z))))
        rows.append(row)
    faces = [(0, rows[0][s], rows[0][(s + 1) % segments]) for s in range(segments)]
    for a, b in zip(rows, rows[1:]):
        for s in range(segments):
            s2 = (s + 1) % segments
            faces.append((a[s], b[s], b[s2], a[s2]))
    return verts, faces


# ==========================================================================================
# UVs
# ==========================================================================================
def shard_uvs(verts, faces, path):
    """Cylindrical, per island: V along the shard axis (root cross-section 0 -> tip 1; the
    nearest axis point is used, so a broken post and the tip both read 1), U around it starting
    at the radial direction (±X/±Y) - the seam lands on a facet edge, one facet column per side."""
    root = Vector(path[0])
    tip = Vector(path[-1])
    axis = (tip - root).normalized()
    total = max((tip - root).length, 1e-6)
    e1 = Vector((axis.y, -axis.x, 0.0))
    if e1.length < 1e-4:
        e1 = Vector((1.0, 0.0, 0.0))
    e1.normalize()
    e2 = axis.cross(e1)
    uvs = []
    for face in faces:
        start = len(uvs)
        pair = []
        for idx in face:
            p = verts[idx] - root
            v = max(0.0, min(1.0, p.dot(axis) / total))
            d = p - axis * (p.dot(axis))
            angle = math.atan2(d.dot(e2), d.dot(e1))
            pair.append([angle / (2.0 * math.pi), v])
        # unwrap across the seam: keep a face's u span < 0.5 by shifting negative angles
        for col in (0, 1):
            vals = [pair[i][col] for i in range(len(face))]
            if max(vals) - min(vals) > 0.5:
                for item in pair:
                    if item[col] < 0.0:
                        item[col] += 1.0
        for item in pair:
            uvs.append((item[0], item[1]))
    return uvs


def cylinder_uvs(verts, faces, centre_xy=(0.0, 0.0), z0=0.0, z1=1.0):
    """U around Z, V by height - for boulders, debris and the mound."""
    cx, cy = centre_xy
    span = max(z1 - z0, 1e-6)
    uvs = []
    for face in faces:
        start = len(uvs)
        pair = []
        for idx in face:
            p = verts[idx]
            angle = math.atan2(p.y - cy, p.x - cx)
            pair.append([angle / (2.0 * math.pi) + 0.5, (p.z - z0) / span])
        if max(u for u, _ in pair) - min(u for u, _ in pair) > 0.5:
            for item in pair:
                if item[0] < 0.5:
                    item[0] += 1.0
        for item in pair:
            uvs.append((item[0], max(0.0, min(1.0, item[1]))))
    return uvs


# ==========================================================================================
# scene / object helpers
# ==========================================================================================
def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_outward(verts, faces):
    """Flip any face whose island has negative enclosed volume (in place). Returns True if any
    face was flipped. Works per island via a shared-vertex flood fill."""
    parent = list(range(len(verts)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for f in faces:
        r0 = find(f[0])
        for v in f[1:]:
            parent[find(v)] = r0
    volume = {}
    for f in faces:
        a, b, c = (Vector(verts[f[0]]), Vector(verts[f[1]]), Vector(verts[f[2]]))
        vol = a.dot(b.cross(c)) / 6.0
        r = find(f[0])
        volume[r] = volume.get(r, 0.0) + vol
    result = []
    for f in faces:
        bad = volume[find(f[0])] < 0.0
        if bad:
            f.reverse()
        result.append(bad)
    return result


def make_object(name, verts, faces, uvs, material=None):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    # outward winding: flip every island whose signed volume is negative (bmesh's recalc picks
    # a "most outward" face, which leaves the rest inward on concave islands)
    faces = [list(p.vertices) for p in mesh.polygons]
    flip = [False] * len(faces)
    for idx, flipped in enumerate(make_outward(verts, faces)):
        flip[idx] = flipped
        if flipped:
            faces[idx].reverse()
            start = sum(len(faces[j]) for j in range(idx))
            n = len(faces[idx])
            uvs[start:start + n] = uvs[start:start + n][::-1]
    for poly, f in zip(mesh.polygons, faces):
        poly.vertices = f
    mesh.update()

    layer = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        for li in poly.loop_indices:
            layer.data[li].uv = uvs[li]
    mesh.polygons.foreach_set("use_smooth", [False] * len(mesh.polygons))
    if material is not None:
        mesh.materials.append(material)
    # flatten all normals (hard edges), written out as custom split normals
    mesh.normals_split_custom_set([(0.0, 0.0, 0.0)] * len(mesh.loops))
    mesh.update()
    return obj


def merge_meshes(name, objects, material):
    """Concatenate the islands' meshes into one mesh (vertices, faces, UV loops) - no operator,
    so it also works headless - and return a new object at the world origin."""
    verts, faces, uvs = [], [], []
    for obj in objects:
        mesh = obj.data
        base = len(verts)
        verts.extend([tuple(v.co) for v in mesh.vertices])
        faces.extend(tuple(base + i for i in poly.vertices) for poly in mesh.polygons)
        layer = mesh.uv_layers[0]
        for li in range(len(mesh.loops)):
            uvs.append(tuple(layer.data[li].uv))
    for obj in objects:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.meshes.remove(data)
    return make_object(name, verts, faces, uvs, material)


def bounds_of(obj):
    co = np.array([v.co[:] for v in obj.data.vertices])
    return co.min(0), co.max(0)


# ==========================================================================================
# layout
# ==========================================================================================
def group_for(azimuth):
    """Left / Right / Back by where the shard bursts towards (UE: forward +Y, right +X there;
    in Blender the same numbers mean forward -Y / right -X, the set is just relabelled)."""
    a = math.radians(azimuth)
    if math.cos(a) > 0.5:
        return "SM_IceCluster_Back"            # behind the character
    return "SM_IceCluster_Right" if math.sin(a) > 0.0 else "SM_IceCluster_Left"


def scatter_angles(rng, count, lo, hi):
    """Full-circle azimuths that are deliberately uneven: alternating jittered steps plus a
    few tight packs (shards bursting together)."""
    step = 360.0 / count
    angles = []
    phase = rng.uniform(0.0, 360.0)
    for i in range(count):
        angles.append((phase + i * step * rng.uniform(0.55, 1.45)) % 360.0)
    # a few pairs drifting closer together
    for _ in range(3):
        i = rng.randrange(count)
        angles[(i + 1) % count] = (angles[i] + rng.uniform(5.0, 12.0)) % 360.0
    return angles


def plan_shards(rng):
    """Root ring + orientation of every crystal.

    Outer ring = longer and flatter, inner ring = shorter and steeper, so the burst reads as a
    bowl that opens outwards. Every tip stays within FOOTPRINT_MAX of the centre, and shards
    that need more than 380 cm to get there are trimmed (the ring shards stay 140-380 cm)."""
    shards = []
    angles = scatter_angles(rng, MID_COUNT, RING_R[0], RING_R[1])
    for az in angles:
        u = rng.random()
        rad = RING_R[0] + (RING_R[1] - RING_R[0]) * u              # even 0..1, then weighted
        f = 0.25 + 0.75 * ((rad - RING_R[0]) / (RING_R[1] - RING_R[0])) ** 0.6   # rings lean outer
        band = rng.random() ** 0.7                                 # skewed towards longer shards
        length = SHARD_LEN[0] + (SHARD_LEN[1] - SHARD_LEN[0]) * band
        length = 150.0 + (length - 150.0) * (0.80 + 0.20 * f)      # inner shards a little shorter
        tilt = SHARD_TILT[1] - (SHARD_TILT[1] - SHARD_TILT[0]) * (f ** 1.0)        # outer flatter
        if rad < INNER_TILT_R:
            tilt = rng.uniform(*INNER_TILT)
        tilt = max(SHARD_TILT[0], tilt)          # inner blades keep their steep tilt
        limit = FOOTPRINT_MAX if not (25.0 <= az % 360.0 <= 65.0) else FOOTPRINT_MAX - 35.0
        while rad + length * math.cos(math.radians(tilt)) > limit and length > SHARD_LEN[0]:
            length *= 0.96
        width = length / rng.uniform(*SHARD_ASPECT) * rng.uniform(0.90, 1.05)  # aspect 5-9
        width *= 0.66                                              # slimmer blades = more tips visible
        shards.append(dict(az=az, r=rad, tilt=tilt, length=length, width=width, hero=False))

    # Inner upright blades: a tight bundle just outside the no-crystal radius.
    bundle = rng.uniform(0.0, 360.0) - 22.0
    for i in range(INNER_COUNT):
        az = (bundle + rng.uniform(8.0, 20.0) * i) % 360.0
        rad = rng.uniform(RING_R[0], INNER_TILT_R)
        tilt = rng.uniform(*INNER_TILT)
        length = rng.uniform(200.0, 290.0)
        width = length / rng.uniform(5.5, 7.5) * 0.95
        shards.append(dict(az=az, r=rad, tilt=tilt, length=length, width=width, hero=False))

    # Heroes: 3 tall shards 380-520 cm at 50-70 deg; the longest one leans to the right-back.
    hero_lengths = [HERO_MAX, rng.uniform(400.0, 470.0), rng.uniform(380.0, 430.0)][:HERO_COUNT]
    hero_angles = [HERO_HEADING, 180.0 + rng.uniform(-15.0, 10.0), rng.uniform(30.0, 60.0)]
    for idx, (length, az) in enumerate(zip(hero_lengths, hero_angles)):
        rad = rng.uniform(70.0, 105.0)
        tilt = rng.uniform(*HERO_ANGLE)
        width = length / rng.uniform(6.5, 8.5)
        shards.append(dict(az=az % 360.0, r=rad, tilt=tilt, length=length, width=width, hero=True))
    return shards


def build_cluster(seed):
    rng = random.Random(seed)
    materials = make_materials()
    groups = {name: [] for name in CLUSTER_PARTS}
    stats = []

    mound_verts, mound_faces = make_mound(rng)
    mound = make_object("tmp_base", mound_verts, mound_faces,
                        cylinder_uvs(mound_verts, mound_faces, (0.0, 0.0), 0.0, MOUND_H),
                        materials["snow"])

    for i, plan in enumerate(plan_shards(rng)):
        az, rad, tilt = plan["az"], plan["r"], plan["tilt"]
        root = Vector((math.sin(math.radians(az)) * rad,
                       math.cos(math.radians(az)) * rad, 0.0))
        root.z = mound_height(root.x, root.y) - 0.35 * MOUND_H * 0.12   # root slightly buried
        verts, faces, tip, path = make_shard(rng, root, az, tilt, plan["length"], plan["width"],
                                             roll=rng.uniform(-22.0, 22.0),
                                             flat=rng.uniform(0.70, 0.88),
                                             tilt_from_ground=not plan["hero"])
        uvs = shard_uvs(verts, faces, path)
        obj = make_object("shard_%02d" % i, verts, faces, uvs, materials["ice"])
        group = "SM_IceCluster_Core" if plan["hero"] else group_for(az)
        groups[group].append(obj)
        tip_world = verts[tip]
        stats.append(dict(index=i, hero=plan["hero"], group=group, az=r2(az, 1),
                          root=[r2(v, 1) for v in root], tilt=r2(tilt, 1),
                          length=r2(plan["length"], 1), aspect=r2(plan["length"] / plan["width"], 2),
                          tip=[r2(v, 1) for v in tip_world],
                          horizontal=r2(math.hypot(tip_world.x, tip_world.y), 1),
                          tip_z=r2(tip_world.z, 1)))

    # White ice chunks at the character's feet, front arc (azimuth 95..265 measured from +Y).
    for i in range(BOULDER_COUNT):
        az = math.radians(BOULDER_ARC[0] + (BOULDER_ARC[1] - BOULDER_ARC[0]) * (i + rng.uniform(0.1, 0.9)) / BOULDER_COUNT)
        size = rng.uniform(*BOULDER_SIZE)
        rad = rng.uniform(24.0, 42.0)
        cx, cy = math.sin(az) * rad, math.cos(az) * rad
        centre = Vector((cx, cy, mound_height(cx, cy) - size * 0.25))
        verts, faces = make_chunk(rng, centre, size * 0.5, subdiv=1,
                                  stretch=(rng.uniform(0.75, 1.15), rng.uniform(0.75, 1.15),
                                           rng.uniform(0.65, 0.95)))
        uvs = cylinder_uvs(verts, faces, (cx, cy), centre.z, centre.z + size * 0.8)
        groups["SM_IceCluster_Boulders"].append(make_object("boulder_%d" % i, verts, faces, uvs,
                                                            materials["snow_ice"]))
    groups["SM_IceCluster_Base"].append(mound)

    merged = {}
    print("DEBUG groups", {k: len(v) for k, v in groups.items()})
    for name in CLUSTER_PARTS:
        mat = {"SM_IceCluster_Boulders": materials["snow_ice"], "SM_IceCluster_Base": materials["snow"],
               }.get(name, materials["ice"])
        merged[name] = merge_meshes(name, groups[name], mat) if groups[name] else None
    return merged, stats


def build_debris(seed):
    rng = random.Random(seed + 1)
    materials = make_materials()
    out = []
    for i, name in enumerate(DEBRIS_PARTS):
        size = rng.uniform(*DEBRIS_SIZE)
        subdiv = 1 if i != 1 else 1
        verts, faces = make_chunk(rng, Vector((0.0, 0.0, size * 0.5)), size * 0.5, subdiv=subdiv,
                                  jitter=0.34,
                                  stretch=(rng.uniform(0.6, 0.95), rng.uniform(0.6, 0.95),
                                           rng.uniform(0.6, 1.0)))
        # centre the mesh on the object origin (debris spins around its own middle in Niagara)
        co = np.array([v[:] for v in verts])
        mid = Vector(((co.min(0) + co.max(0)) / 2.0).tolist())
        verts = [v - mid for v in verts]
        zmin = min(v.z for v in verts)
        zmax = max(v.z for v in verts)
        uvs = cylinder_uvs(verts, faces, (0.0, 0.0), zmin, zmax)
        out.append(make_object(name, verts, faces, uvs, materials["ice"]))
    return out


# ==========================================================================================
# export
# ==========================================================================================
def export_fbx(objects, path):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=True,
        object_types={"MESH"},
        global_scale=1.0,
        apply_unit_scale=False,
        apply_scale_options="FBX_SCALE_NONE",
        axis_forward="-Y",
        axis_up="Z",
        bake_space_transform=False,
        mesh_smooth_type="OFF",
        use_mesh_modifiers=False,
        use_tspace=False,
        add_leaf_bones=False,
    )


def write_parts_json(merged):
    parts = []
    for name in CLUSTER_PARTS:
        obj = merged[name]
        low, high = bounds_of(obj)
        mesh = obj.data
        parts.append({
            "name": name,
            "faces": len(mesh.polygons),
            "verts": len(mesh.vertices),
            "size_m": [r2((high[i] - low[i]) / 100.0, 3) for i in range(3)],
            "z_range": [r2(low[2] / 100.0, 3), r2(high[2] / 100.0, 3)],
        })
    with open(OUT_PARTS_JSON, "w") as f:
        json.dump(parts, f, indent=2)
        f.write("\n")
    return parts


# ==========================================================================================
# preview render + side-by-side sheet
# ==========================================================================================
def srgb(hex_string):
    h = hex_string.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def linear(rgb):
    def f(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return tuple(f(c) for c in rgb)


LIGHT = srgb("#9fdcff")
LIGHT_DIR = Vector((-0.72, 0.62, 0.32)).normalized()
MIDTONE = srgb("#2f8fe6")
SHADE = srgb("#0b3aa0")


def add_color_ramp_linked(nt, input_socket, stops):
    """ValToRGB with CONSTANT (banded) stops [(position, srgb rgb), ...]."""
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    els = ramp.color_ramp.elements
    while len(els) < len(stops):
        els.new(0.5)
    for el, (pos, rgb) in zip(els, stops):
        el.position = pos
        el.color = (*rgb, 1.0)
    nt.links.new(input_socket, ramp.inputs["Fac"])
    return ramp


def flat_material(name, stops, light_dir, facing_shift=0.0):
    """Unlit banded material: N.L against a fixed light direction picks the flat colour (so a
    facet shows exactly its hex colour after the Standard view transform). `facing_shift`
    adds a camera-facing term so shards with different azimuths still catch the light."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    nt = mat.node_tree
    mat.use_nodes = True
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    lw = nt.nodes.new("ShaderNodeVectorMath")
    lw.operation = "DOT_PRODUCT"
    lw.inputs[1].default_value = Vector(light_dir).normalized()
    nt.links.new(geo.outputs["Normal"], lw.inputs[0])
    fac = lw.outputs["Value"]
    if facing_shift:
        cc = nt.nodes.new("ShaderNodeVectorMath")
        cc.operation = "DOT_PRODUCT"
        cc.inputs[1].default_value = Vector((0.0, -1.0, 0.6)).normalized()
        nt.links.new(geo.outputs["Normal"], cc.inputs[0])
        bw = nt.nodes.new("ShaderNodeMath")
        bw.operation = "MULTIPLY_ADD"
        bw.inputs[1].default_value = 1.0
        bw.inputs[2].default_value = bg_strength = facing_shift
        nt.links.new(cc.outputs["Value"], bw.inputs[0])
        add = nt.nodes.new("ShaderNodeMath")
        add.operation = "ADD"
        nt.links.new(lw.outputs["Value"], add.inputs[0])
        nt.links.new(bw.outputs["Value"], add.inputs[1])
        fac = add.outputs["Value"]
    ramp = add_color_ramp_linked(nt, fac, stops)
    nt.links.new(ramp.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def make_materials():
    """Ice: #0b3aa0 shadow / #2f8fe6 mid / #9fdcff lit; snow and ice chunks: near white."""
    ice = flat_material("IceFlat", [(0.0, SHADE), (0.36, MIDTONE), (0.72, LIGHT)],
                        LIGHT_DIR, facing_shift=0.0)
    snow = flat_material("SnowFlat", [(0.0, (0.86, 0.90, 1.0)), (0.30, (0.97, 0.98, 1.0)),
                                      (0.62, (1.0, 1.0, 1.0))], (-0.55, 0.72, 0.60))
    snow_ice = flat_material("SnowIceFlat", [(0.0, (0.80, 0.88, 1.0)), (0.32, (0.93, 0.96, 1.0)),
                                             (0.60, (1.0, 1.0, 1.0))], (-0.55, 0.72, 0.60))
    return {"ice": ice, "snow": snow, "snow_ice": snow_ice}


def setup_world():
    world = bpy.data.worlds.new("IceWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.010, 0.020, 0.045, 1.0)
    bg.inputs["Strength"].default_value = 1.0


def add_character_placeholder():
    """180 cm grey humanoid: tapered body, head, arms, legs standing on the mound centre."""
    mat = flat_material("PlaceholderGrey", [(0.0, (0.05, 0.055, 0.07)), (0.45, (0.24, 0.26, 0.29))],
                        (-0.5, 0.7, 0.5))
    parts = []
    def tube(name, p0, p1, r0, r1):
        p0, p1 = Vector(p0), Vector(p1)
        length = (p1 - p0).length
        bpy.ops.mesh.primitive_cone_add(vertices=10, radius1=r0, radius2=r1, depth=length,
                                        location=(p0 + p1) / 2)
        obj = bpy.context.active_object
        obj.name = name
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = (p1 - p0).to_track_quat("Z", "Y")
        obj.data.materials.append(mat)
        parts.append(obj)
        return obj

    z = MOUND_H
    tube("ph_torso", (0, 0, z + 95), (0, 0, z + 150), 20, 16)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=13.5,
                                         location=(0, 0, z + 165))
    head = bpy.context.active_object
    head.data.materials.append(mat)
    parts.append(head)
    for sx in (-1, 1):
        tube("ph_arm", (sx * 21, 0, z + 145), (sx * 40, 6, z + 95), 7.5, 6.0)
        tube("ph_leg", (sx * 9, 0, z + 90), (sx * 11, 2, z + 2), 9.0, 7.0)
    for obj in parts:
        obj.select_set(False)
    return parts


def look_at(camera, target):
    direction = Vector(target) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def render_preview(merged, path, target=CAMERA_TARGET):
    scene = bpy.context.scene
    setup_world()
    add_character_placeholder()

    cam_data = bpy.data.cameras.new("PreviewCam")
    cam_data.lens = 28.0
    cam_data.sensor_width = 36.0
    camera = bpy.data.objects.new("PreviewCam", cam_data)
    scene.collection.objects.link(camera)
    elev = math.radians(ELEV_DEG)
    dist = DIST_CM
    camera.location = target + Vector((-0.22, -math.cos(elev), math.sin(elev))) * dist
    look_at(camera, target)
    scene.camera = camera

    scene.render.engine = "BLENDER_WORKBENCH" if False else "BLENDER_EEVEE"
    try:
        scene.eevee.taa_render_samples = 16
    except AttributeError:
        pass
    scene.render.resolution_x = 1100
    scene.render.resolution_y = 714
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


def side_by_side(render_path, ref_path, out_path):
    """Compose render | reference into one PNG (numpy only)."""
    import bpy
    img_l = bpy.data.images.load(render_path)
    img_r = bpy.data.images.load(ref_path)
    size = (1100, 714)
    if tuple(img_r.size) != size:
        img_r.scale(*size)
    if tuple(img_l.size) != size:
        img_l.scale(*size)
    w, h = size
    left = np.array(img_l.pixels[:], dtype=np.float32).reshape(h, w, img_l.channels)
    right = np.array(img_r.pixels[:], dtype=np.float32).reshape(h, w, img_r.channels)
    left = left[..., :3]
    right = right[..., :3]
    gap = np.zeros((h, 6, 3), dtype=np.float32)
    out = np.concatenate([left, gap, right], axis=1)
    sheet = bpy.data.images.new("IceBurst_v3_preview", out.shape[1], h, alpha=False)
    rgba = np.concatenate([out, np.ones((h, out.shape[1], 1), dtype=np.float32)], axis=2)
    sheet.pixels = rgba.ravel().tolist()
    sheet.filepath_raw = out_path
    sheet.file_format = "PNG"
    sheet.save()
    return out.shape


# ==========================================================================================
# data JSON
# ==========================================================================================
def update_data_json(parts):
    """Only cluster_parts / cluster_scale / cluster_center_cm: load, replace those three keys,
    dump the whole document back (arcs untouched)."""
    with open(DATA_JSON) as f:
        data = json.load(f)
    roles = ROLE
    data["cluster_parts"] = [{
        "name": p["name"],
        "pivot_cm": [0.0, 0.0, 0.0],
        "rotation_deg": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
        "size_cm": [r2(v * 100.0, 2) for v in p["size_m"]],
        "faces": p["faces"],
        "material_role": roles[p["name"]],
    } for p in parts]
    data["cluster_scale"] = 1.0
    data["cluster_center_cm"] = [0.0, 0.0, 0.0]
    with open(DATA_JSON, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ==========================================================================================
# main
# ==========================================================================================
def debug_groups():
    import traceback
    for fn in ("mound", "shard"):
        try:
            if fn == "mound":
                make_mound(random.Random(1))
            else:
                rng = random.Random(1)
                v, f, t, path = make_shard(rng, (80, 0, 20), 30, 40, 300, 45)
                shard_uvs(v, f, path)
            print("DEBUG", fn, "ok")
        except Exception:
            print("DEBUG", fn, "FAILED")
            traceback.print_exc()


def main():
    clear_scene()
    debug_groups()
    merged, stats = build_cluster(SEED)
    debris = build_debris(SEED)

    export_fbx([merged[n] for n in CLUSTER_PARTS if merged[n]], OUT_CLUSTER_FBX)
    export_fbx(debris, OUT_DEBRIS_FBX)
    parts = write_parts_json(merged)

    for name in CLUSTER_PARTS:
        obj = merged[name]
        low, high = bounds_of(obj)
        print("PART %-24s faces %4d verts %5d size_cm %s z_cm %s" % (
            name, len(obj.data.polygons), len(obj.data.vertices),
            [round((high[i] - low[i]), 1) for i in range(3)], [round(low[2], 1), round(high[2], 1)]))
    for obj in debris:
        low, high = bounds_of(obj)
        print("DEBRIS %-18s faces %3d size_cm %s" % (obj.name, len(obj.data.polygons),
                                                     [round(high[i] - low[i], 1) for i in range(3)]))
    for s in stats:
        print("SHARD", json.dumps(s))

    render_preview(merged, OUT_PREVIEW_SIDE)
    print("SHEET", side_by_side(OUT_PREVIEW_SIDE, REF_FRAME, OUT_PREVIEW_PNG))
    update_data_json(parts)
    print("WROTE", OUT_CLUSTER_FBX, OUT_DEBRIS_FBX, OUT_PARTS_JSON, OUT_PREVIEW_PNG)


if __name__ == "__main__":
    main()
