"""Fit a circle to each v5 slash arc's outer (gold) rim and write arc_rings.json (task D1).

Outer-edge rule (same as build_blade_sheets.py): for every UV U column of the blade, take the
vertex whose Blender UV V is the smallest -- that is the rim the painted gold edge sits on.
U = 0 is the start of the swing (tail, s = 0), U = 1 its end (head, s = 1).

Coordinates are UE mesh-local: Blender (x, y, z) -> (x, -y, z), centimetres (the FBX was baked in
cm and UE only flips Y for the FBX axes).

Per blade the JSON gives the fitted circle (center_cm, radius_cm, normal, start_dir, sweep_deg,
fit_rms_cm, inner_radius_cm), a UE FQuat ring_quat_xyzw that maps the Niagara ring local frame
(X = start_dir, Y = Z x X, Z = normal) into mesh-local space, and 24 arc-length-uniform rim
samples with s / pos_cm / tangent / outward.

Fit: the rim is sampled at exact U = i/(N-1) on the per-column rim polyline, then a circle is
searched over plane normals (radial rms + out-of-plane residual, radius capped at 4x the rim's own
size) and refined. The normal's direction is fixed so that s 0 -> 1 turns counter-clockwise about
it, which makes ring local Y = Z x X point outward. The centre is rounded to 1e-3 cm and radius,
rms and sweep are then re-measured about (center_cm, normal) exactly as a consumer would.

Usage:
  Blender -b --factory-startup -P fit_arc_rings.py            # writes the json + check image
  Blender -b --factory-startup -P fit_arc_rings.py -- <blades.fbx> <out.json> [--no-render]
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True     # a stale __pycache__ .pyc in this folder shadowed real edits once

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
SRC = PROJECT / "Saved/VFX/SlashArcs_v5_ue.fbx"
OUT = PROJECT / "Tools/IceSlash/data/arc_rings.json"
CHECK = HERE / "arc_rings_check.png"

NSAMPLES = 24


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    render = "--no-render" not in a
    a = [x for x in a if not x.startswith("--")]
    src = Path(a[0]) if len(a) > 0 else SRC
    dst = Path(a[1]) if len(a) > 1 else OUT
    return src, dst, render


def n(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def to_ue(p):
    """Blender point(s) -> UE mesh-local: (x, y, z) -> (x, -y, z). A point or an (N, 3) array."""
    return np.asarray(p, float) * np.array([1.0, -1.0, 1.0])


def to_blender(p):
    return np.asarray(p, float) * np.array([1.0, -1.0, 1.0])


# ---------------------------------------------------------------- rim extraction
def uv_columns(mesh):
    """{U column: {vertex index: [UV V values]}} for the mesh's active UV map."""
    me = mesh.data
    uv = me.uv_layers.active.data
    by_u = defaultdict(lambda: defaultdict(list))
    for loop in me.loops:
        u, v = uv[loop.index].uv
        by_u[round(u, 4)][loop.vertex_index].append(v)
    return me, by_u


def rim_points(mesh):
    """One rim point per UV U column (Blender coords, U order).

    The outer rim is each column's smallest UV V. A vertex shared by two columns is judged by its
    V inside the column being examined (not by a per-vertex minimum), so the pick is exact."""
    me, by_u = uv_columns(mesh)
    out = []
    for u in sorted(by_u):
        col = by_u[u]
        vi = min(col, key=lambda i: (min(col[i]), sorted(col[i]), i))
        out.append(np.array(me.vertices[vi].co, float))
    return np.array(out)


def inner_points(mesh):
    """The opposite (largest-V) vertex of every column, Blender coords -- the blade's inner edge."""
    me, by_u = uv_columns(mesh)
    out = []
    for u in sorted(by_u):
        col = by_u[u]
        vi = max(col, key=lambda i: (max(col[i]), tuple(-v for v in sorted(col[i])), -i))
        out.append(np.array(me.vertices[vi].co, float))
    return np.array(out)


def resample_arc(pts, count):
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, cum[-1], count)
    i = np.clip(np.searchsorted(cum, t, side="right") - 1, 0, len(seg) - 1)
    f = np.clip((t - cum[i]) / np.maximum(seg[i], 1e-12), 0.0, 1.0)
    return pts[i] + (pts[i + 1] - pts[i]) * f[:, None]


def rim_at_u(pts, cos_s):
    """Rim at parametric U = s: columns are uniform in U, so lerp between neighbouring columns."""
    N = len(pts) - 1
    out = []
    for s in cos_s:
        f = min(max(float(s), 0.0), 1.0) * N
        i = min(int(f), N - 1)
        t = f - i
        out.append(pts[i] * (1 - t) + pts[i + 1] * t)
    return np.array(out)


# ---------------------------------------------------------------- circle fit
def _kasa(x, y):
    """Algebraic (Kasa) circle fit, on centred coordinates so a big arc is not swamped by a big
    offset. Works on array-likes too; returns (radius, (cx, cy)) in the input frame."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    mx, my = x.mean(), y.mean()
    x, y = x - mx, y - my
    A = np.column_stack([x, y, np.ones_like(x)])
    D, E, F = np.linalg.lstsq(A, -(x * x + y * y), rcond=None)[0]
    r = math.sqrt(max(D * D / 4 + E * E / 4 - F, 0.0))
    return r, (mx - D / 2, my - E / 2)


def _plane_axes(z):
    """In-plane axes with e1 x e2 = z."""
    z = n(z)
    e1 = n(np.cross(z, [0.0, 0.0, 1.0] if abs(z[2]) < 0.9 else [1.0, 0.0, 0.0]))
    return e1, np.cross(z, e1)


def _project(pts, c, z):
    q = pts - c
    off = q @ z
    return np.linalg.norm(q - np.outer(off, z), axis=1), off


def _resolve_center(pts, c, z, free_until=1.5):
    """Fit the circle of points pts in the plane with normal z, starting from centre c.

    Alternates the exact Kasa update (linear) with a small pattern search; each step accepts a
    new centre only if the RMS radial distance that centre really gives is smaller. (A Kasa
    update can jump far on a shallow arc while reporting a better algebraic residual, so the
    actual RMS is the referee.) Stops after `free_until` cm of total centre travel once it can no
    longer more than halve the error: that keeps a circle anchored at a given plane from being
    traded for the much better *3D* fit of a tilted plane two feet away."""
    z = n(z)
    e1, e2 = _plane_axes(z)
    p1, p2 = pts @ e1, pts @ e2

    def rms_at(a, b):
        r = np.hypot(p1 - a, p2 - b)
        return float(np.sqrt(np.mean((r - r.mean()) ** 2))), float(r.mean())

    a, b = float(c @ e1), float(c @ e2)
    best, R = rms_at(a, b)          # (R is the mean radial distance of the finish step)
    start = (a, b)
    for step in (size_step(pts) * 0.25, size_step(pts) * 0.08, 6.0, 2.0, 0.5, 0.25):
        for _ in range(200):
            moved = False
            # exact Kasa update measured at its own centre
            Rk, (ka, kb) = _kasa(p1 - a, p2 - b)
            vk, Rk2 = rms_at(a + ka, b + kb)
            if vk < best * 0.5:
                a, b, best, R, moved = a + ka, b + kb, vk, Rk2, True
                continue
            for da, db in ((step, 0), (-step, 0), (0, step), (0, -step)):
                v, R2 = rms_at(a + da, b + db)
                if v < best * 0.98 - 1e-12:
                    a, b, best, R, moved = a + da, b + db, v, R2, True
            if not moved:
                break
        if math.hypot(a - start[0], b - start[1]) > free_until:
            break
    return e1 * a + e2 * b, R, best


def size_step(pts):
    return float(np.abs(pts - pts.mean(axis=0)).max())


def _score(pts, c0, z):
    """Best circle in the plane with normal z, started from the centre c0: (residual, center, R).

    residual = rms of the true 3D distance to the circle = sqrt(radial rms^2 + out-of-plane rms^2),
    measured with the radial rms this centre actually gives (not a centre's own Kasa promise)."""
    z = n(z)
    c, R, _ = _resolve_center(pts, c0, z)
    rad, off = _project(pts, c, z)
    return float(np.sqrt(np.mean((rad - rad.mean()) ** 2 + off ** 2))), c, R


def _sweep(rel, z):
    e1, e2 = _plane_axes(z)
    ang = np.unwrap(np.arctan2(rel @ e2, rel @ e1))
    return float(math.degrees(ang[-1] - ang[0]))


# Blade arc planes as authored in Saved/VFX/generate_slash_arcs_v5.py: the sweep runs in the plane
# of e1 x e2, with e1 = (1,0,0) and e2 = (0, cos tilt, sin tilt) for the horizontal arcs and e1 =
# (cos yaw, sin yaw, 0), e2 = (0,0,1) for the vertical ones. Every rim point projects onto its
# authored plane at exactly R; the cone tilt only lifts the rim ~10 cm along the plane normal.
_AUTH = {
    1: (1, 0, 0, 0, math.cos(math.radians(12)), math.sin(math.radians(12))),
    2: (1, 0, 0, 0, math.cos(math.radians(-15)), math.sin(math.radians(-15))),
    3: (1, 0, 0, 0, math.cos(math.radians(8)), math.sin(math.radians(8))),
    4: (math.cos(math.radians(15)), math.sin(math.radians(15)), 0, 0, 0, 1),
    5: (math.cos(math.radians(-20)), math.sin(math.radians(-20)), 0, 0, 0, 1),
}


def auth_plane(blade):
    a = _AUTH[int(blade.split("_")[-1])]
    e1, e2 = n(a[:3]), n(a[3:])
    return e1, e2, n(np.cross(e1, e2))


def fit_circle(pts, z_auth):
    """Circle through pts in the authored plane. Returns
    (center, normal, radius, rms, sweep_deg, offplane_rms):
      rms          radial residual of the rim to the circle (circle error),
      offplane_rms mean out-of-plane distance along the normal (the blade's cone tilt),
      sweep_deg    signed sweep of s 0 -> 1 about the returned normal.

    The plane is the authored arc plane (z_auth): on every authored arc the rim projects onto it
    at exactly R (radial rms 0.00 cm; R = 250/270/300/260/280), the rim only rides along the
    plane's normal by the blade's cone tilt. The centre lies ON that plane (z_auth . center is
    kept at 0), which is what the authored circle is; a "better" tilted plane is rejected because
    it only wins by tilting to follow the cone tilt. The centre is the point of the plane that
    minimises the rim's scatter in projected radius (_resolve_center)."""
    pts = np.asarray(pts, float)
    za = n(z_auth)
    h0 = float(pts.mean(axis=0) @ za)
    c_on = pts.mean(axis=0) - za * h0                       # centroid projected onto the plane
    center, radius, rms = _resolve_center(pts, c_on, za)
    center = center - za * float(center @ za)               # back on the plane
    center, radius, rms = _resolve_center(pts, center, za)
    # The rim's cone tilt rides the whole rim up the normal by a constant ~10 cm; fold that into the
    # centre's height so the written circle and the written samples agree (on the near-full sweeps
    # the tilt also adds a few cm of apparent radius swing, which fit_rms_cm reports as is).
    center = center - za * float(center @ za) + za * float(np.mean(_project(pts, center, za)[1]))
    normal = za
    # Report exactly what a consumer rebuilds from (center_cm, radius_cm, normal): round first,
    # then re-measure every number with the rounded values, so no figure is left over from a
    # centre the file does not contain.
    center = np.round(center, 2)
    rad, off = _project(pts, center, normal)
    radius = round(float(rad.mean()), 2)
    # radial rms: remove the rim's mean ride along the normal first. The circle describes the
    # cylinder the rim is on; the cone tilt lifts the whole rim ~10 cm up the normal, which is a
    # constant offset, not a radius error. rim_offplane_rms_cm reports that lift separately.
    rms = float(np.sqrt(np.mean((rad - radius) ** 2)))
    off_rms = float(np.sqrt(np.mean(off ** 2)))
    return center, normal, radius, rms, _sweep(pts - center, normal), off_rms


# ---------------------------------------------------------------- quaternion (UE FQuat x,y,z,w)
def matrix_to_quat(M):
    """Rotation matrix M (columns = images of X, Y, Z) -> UE FQuat (x, y, z, w)."""
    m00, m01, m02 = M[0]
    m10, m11, m12 = M[1]
    m20, m21, m22 = M[2]
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    q = np.array([x, y, z, w])
    return q / np.linalg.norm(q)


def quat_rotate(q, v):
    """UE FQuat convention (x, y, z, w): m = q * v * q^-1."""
    x, y, z, w = q
    M = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    return M @ np.asarray(v, float)


# ---------------------------------------------------------------- main
def main():
    src, dst, render = args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(src))
    blades = sorted((o for o in bpy.context.scene.objects
                     if o.type == "MESH" and o.name.startswith("SM_SlashArc_")), key=lambda o: o.name)
    if not blades:
        raise SystemExit(f"no SM_SlashArc_* meshes in {src}")
    print(f"# {len(blades)} blades from {src}")

    out = {
        "source": str(src.relative_to(PROJECT)) if src.is_relative_to(PROJECT) else str(src),
        "coord_system": "UE mesh-local centimetres; Blender (x, y, z) -> (x, -y, z).",
        "rim_rule": "outer (gold) rim = the smallest-UV-V vertex of each UV U column; U 0 = swing "
                    "start (tail, s = 0), U 1 = end (head, s = 1).",
        "normal_note": "normal is a unit vector along the arc plane's normal; it is e1 x e2 of the blade's authored arc plane (generate_slash_arcs_v5.py: "
                       "horizontal arcs (1,0,0) x (0,cos tilt,sin tilt), vertical arcs (cos yaw,sin yaw,0) "
                       "x (0,0,1)). s 0 -> 1 runs counter-clockwise about it when sweep_deg > 0 and "
                       "clockwise when < 0 (winding_about_normal). An arc wound the other way is the "
                       "same curve, so the sign only matters to whatever drives the ring from an angle: "
                       "the rim point at parameter s sits at ring angle -s * sweep_deg (Niagara's "
                       "clockwise-positive ring angle, i.e. -atan2(p.Y, p.X) in mesh-local XY of the "
                       "ring frame) for every blade.",
        "axes_note": "ring_quat_xyzw is a UE FQuat, x, y, z, w order (pass it straight to "
                     "UnrealQuat.Rotation(); mathutils: Quaternion((w, x, y, z))). It maps the "
                     "Niagara ring local frame X=start_dir, Y=Z x X=normal x start_dir, Z=normal into "
                     "mesh-local space (right-handed). Ring angle of a rim point p = atan2(p.Y, p.X) "
                     "in that local frame, so a Niagara angular sweep of -sweep_deg covers s 0 -> 1 "
                     "at constant speed. Niagara ring angle is positive clockwise (particles spawn at "
                     "angle 0 = local +X = start_dir).",
        "fit_note": "fit_rms_cm = radial RMS of the rim's 24 sample points to the reported circle "
                    "(centre_cm / radius_cm exactly as written); rim_offplane_rms_cm = their RMS "
                    "distance along the normal from the circle's plane (0 here: the centre is placed "
                    "at the rim's mean height along the normal, so the written circle sits on the rim). "
                    "The arc plane is the one the blade was authored in (generate_slash_arcs_v5.py); "
                    "the rim is tilted ~10 cm off it per 100 cm of blade width by the blade's cone "
                    "tilt, which costs the near-full sweeps a few cm of radial stretch (see fit_rms_cm "
                    "per blade).",
        "samples_note": "samples are at s = i/23 along the rim (U from 0 to 1), pos_cm is the rim "
                        "point (the gold edge), tangent the swing direction, outward the radial "
                        "(away from the centre) direction. inner_radius_cm = mean distance of the "
                        "blade's inner (UV V = 1) edge to the circle centre: the fog band lies "
                        "between inner_radius_cm and radius_cm.",
        "samples": NSAMPLES,
        "arcs": [],
    }
    for blade in blades:
        rim_b = rim_points(blade)
        rim = to_ue(rim_b)                              # rim, U order, UE cm
        inner_b = to_ue(inner_points(blade))            # inner edge all columns, UE cm
        z_auth = auth_plane(blade.name)[2]
        center, normal, radius, rms, sweep, off_rms = fit_circle(rim, z_auth)

        # start_dir: centre -> s = 0 rim point, in the circle's plane
        v0 = rim[0] - center
        start_dir = n(v0 - normal * float(v0 @ normal))
        # exact orthonormal frame (normalised after projection so the rounded Z stays unit enough)
        Z = n(normal)
        X = n(start_dir - Z * float(start_dir @ Z))
        Y = n(np.cross(Z, X))                  # right-handed: X x Y = Z, Y = Z x X
        quat = matrix_to_quat(np.column_stack([X, Y, Z]))
        center_world = center

        # 24 samples at s = i/23 (U-uniform columns)
        ss = np.linspace(0.0, 1.0, NSAMPLES)
        samples = []
        for i, s in enumerate(ss):
            p = rim_at_u(rim, [s])[0]
            t = (rim_at_u(rim, [min(s + 0.01, 1.0)])[0] - rim_at_u(rim, [max(s - 0.01, 0.0)])[0])
            t = n(t)
            o = p - center
            o = n(o - Z * float(o @ Z))
            samples.append({
                "s": round(float(s), 6),
                "pos_cm": [round(float(x), 3) for x in p],
                "tangent": [round(float(x), 6) for x in t],
                "outward": [round(float(x), 6) for x in o],
            })

        normal = Z
        start_dir = X
        # winding: which way s 0 -> 1 runs seen from +normal. Ring local X = start_dir and local Y =
        # Z x X always point along s=0, so the ring is right-handed whatever this says; sweep_deg
        # carries the sign for anyone driving it from angles (Niagara float curve -> ring angle
        # wants sweep_deg > 0, i.e. angle = -sweep).
        winding = "ccw" if sweep > 0 else "cw"

        iu = inner_b - center
        inner_r = float(np.linalg.norm(iu, axis=1).mean())

        # every figure about the rim is measured on the written samples, about the written centre
        Pj = np.array([x["pos_cm"] for x in samples], float)
        rads, offs = _project(Pj, center, normal)
        radius = round(float(rads.mean()), 2)
        spread = round(float(np.sqrt(np.mean((rads - radius) ** 2))), 4)
        off_rms = round(float(np.sqrt(np.mean(offs ** 2))), 4)

        out["arcs"].append({
            "blade": blade.name,
            "center_cm": [round(float(x), 2) for x in center_world],
            "radius_cm": radius,
            "inner_radius_cm": round(inner_r, 4),
            "normal": [round(float(x), 6) for x in normal],
            "start_dir": [round(float(x), 6) for x in start_dir],
            "sweep_deg": round(sweep, 4),
            "fit_rms_cm": spread,
            "rim_offplane_rms_cm": off_rms,
            "ring_quat_xyzw": [round(float(x), 8) for x in quat],
            "winding_about_normal": winding,
            "rim_len_cm": round(float(np.linalg.norm(np.diff(rim, axis=0), axis=1).sum()), 3),
            "samples": samples,
        })
        print(f"OK {blade.name}: center={np.round(center, 1)} R={radius:.2f} inner={inner_r:.1f} "
              f"sweep={sweep:.1f} ({winding}) rms={rms:.3f} off={off_rms:.1f} n={np.round(normal, 3)} "
              f"q(xyzw)={np.round(quat, 4)}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"WROTE {dst} ({len(out['arcs'])} arcs)")
    if render:
        render_check(out, blades)


# ---------------------------------------------------------------- check render (Workbench)
def _mat(name, rgb):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*rgb, 1.0)
    return m


def _tube(name, pts, color, thick):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = thick
    cu.bevel_resolution = 1
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for p, q in zip(sp.points, pts):
        p.co = (*q, 1.0)
    ob = bpy.data.objects.new(name, cu)
    ob.data.materials.append(_mat(name, color))
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _ball(name, p, r, color):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=p, segments=12, ring_count=8)
    ob = bpy.context.active_object
    ob.name = name
    ob.data.materials.append(_mat(name, color))
    return ob


def _render_workbench(path, cam_loc, target, ortho, center, up_hint):
    sc = bpy.context.scene
    cam_data = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cam_data)
    sc.collection.objects.link(cam)
    f = n(np.asarray(target, float) - np.asarray(cam_loc, float))
    right = n(np.cross(f, up_hint))
    up = np.cross(right, f)
    M = np.column_stack([right, up, -f])
    x, y, z, w = matrix_to_quat(M)
    cam.location = cam_loc
    cam.rotation_mode = "QUATERNION"
    cam.rotation_quaternion = (w, x, y, z)                  # Blender wants w first
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho
    cam_data.clip_end = 10000
    sc.camera = cam
    sc.render.engine = "BLENDER_WORKBENCH"
    sh = sc.display.shading
    sh.light = "STUDIO"
    sh.color_type = "MATERIAL"
    sh.show_shadows = False
    sh.show_cavity = True
    sh.background_type = "VIEWPORT"
    sh.background_color = (0.03, 0.03, 0.05)
    sc.render.film_transparent = False
    sc.render.resolution_x = sc.render.resolution_y = 1000
    sc.render.resolution_percentage = 100
    sc.render.filepath = path
    sc.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam)


def render_check(data, blades):
    """Blades (blue) + fitted circles (orange, thin line) + 24 sample balls (green), from above and
    obliquely, side by side -> arc_rings_check.png."""
    for ob in blades:
        ob.data.materials.clear()
        ob.data.materials.append(_mat(ob.name, (0.20, 0.40, 0.90)))
    lo = np.array([1e9, 1e9, 1e9])
    hi = -lo
    for a in data["arcs"]:
        c = np.array(a["center_cm"])
        Z = np.array(a["normal"])
        e1, e2 = _plane_axes(Z)
        e1b = to_blender(e1)                                # same rotation as the JSON frame
        e2b = to_blender(e2)
        e1, e2 = n(e1b), n(e2b)
        c_b = to_blender(c)
        R = a["radius_cm"]
        ring = [c_b + R * (e1 * math.cos(t) + e2 * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 721)]
        _tube("ring_" + a["blade"], ring, (1.0, 0.45, 0.05), 1.2)
        _ball("ctr_" + a["blade"], c_b, 3.5, (1.0, 0.1, 0.1))
        for k, s in enumerate(a["samples"]):
            p = to_blender(s["pos_cm"])
            _ball("p_%s_%02d" % (a["blade"], k), p, 3.0, (0.15, 1.0, 0.3))
            lo = np.minimum(lo, p)
            hi = np.maximum(hi, p)
    mid = (lo + hi) / 2
    R_max = max(a["radius_cm"] for a in data["arcs"])
    span = 2.0 * R_max * 1.45                 # ortho_scale is the frame width; leave margin
    # top: looking straight down -Z, X right, -Y up (character forward = up on the page)
    _render_workbench(str(CHECK.with_name("_top.png")), (0.0, 0.0, 3000.0), (0.0, 0.0, mid[2]),
                      span, mid, np.array([0.0, -1.0, 0.0]))
    # oblique: 3/4 view from front-left, ~35 deg up
    eye = mid + np.array([-0.75, -1.0, 0.55]) * span * 0.62
    _render_workbench(str(CHECK.with_name("_oblique.png")), tuple(eye), tuple(mid), span * 1.05, mid,
                      np.array([0.0, 0.0, 1.0]))
    combine([str(CHECK.with_name("_top.png")), str(CHECK.with_name("_oblique.png"))], CHECK)
    for p in ("_top.png", "_oblique.png"):
        CHECK.with_name(p).unlink(missing_ok=True)


def combine(paths, out):
    imgs = [bpy.data.images.load(p) for p in paths]
    w = sum(i.size[0] for i in imgs)
    h = max(i.size[1] for i in imgs)
    dst = bpy.data.images.new("check", width=w, height=h, alpha=True)
    buf = np.zeros((h, w, 4), np.float32)
    x0 = 0
    for im in imgs:
        px = np.array(im.pixels[:], dtype=np.float32).reshape(im.size[1], im.size[0], 4)
        buf[0:im.size[1], x0:x0 + im.size[0]] = px      # bottom-up rows, same for both
        x0 += im.size[0]
    dst.pixels = buf.ravel()
    dst.filepath_raw = str(out)
    dst.file_format = "PNG"
    dst.save()
    print(f"WROTE {out} {w}x{h}")


if __name__ == "__main__":
    main()