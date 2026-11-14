"""Build Tools/IceSlash/data/ice_slash_data.json from the Blender extract.

Inputs (read-only):
  Tools/IceSlash/data/fbx_extract_raw.json          (from extract_fbx_blender.py)
  Saved/VFX/generate_slash_arcs_v4.py               (SEGMENTS, parsed with ast, never executed)
  Saved/VFX/SlashGuide_1HM_AerialSwing01_2HitCombo.json
  SourceAssets/IceCrystal/SM_IceCluster_v2_parts.json

Run with a plain interpreter (no Blender needed):
  python3 -I Tools/IceSlash/data/build_ice_slash_data.py [--report]
"""

import ast
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
EXTRACT = os.path.join(HERE, "fbx_extract_raw.json")
OUT = os.path.join(HERE, "ice_slash_data.json")
GEN = os.path.join(PROJECT, "Saved", "VFX", "generate_slash_arcs_v4.py")
GUIDE = os.path.join(PROJECT, "Saved", "VFX", "SlashGuide_1HM_AerialSwing01_2HitCombo.json")
PARTS = os.path.join(PROJECT, "SourceAssets", "IceCrystal", "SM_IceCluster_v2_parts.json")

ANIM_ASSET = "/Game/RamsterZ_FreeAnims_Volume1/AnimationSequence/1HM/1HM_AerialSwing01_2HitCombo"
PLAN_FIRST_SLASH_S = 1.4
RADIUS_RANGE = (1.2, 2.2)      # generate_slash_arcs_v4.py RADIUS_RANGE
WIDTH_RANGE = (0.25, 0.45)     # generate_slash_arcs_v4.py WIDTH_RANGE
SPAN_RANGE = (120.0, 300.0)    # generate_slash_arcs_v4.py build_segment clamp
CLUSTER_SCALE = 4.0
ROLE = {
    "SM_IceCluster_Core": "prism",
    "SM_IceCluster_Left": "prism",
    "SM_IceCluster_Right": "prism",
    "SM_IceCluster_Back": "prism",
    "SM_IceCluster_Boulders": "boulder",
    "SM_IceCluster_Base": "snowbase",
}


def r(value, digits=2):
    return round(float(value), digits)


def vec(values, digits=2):
    return [r(v, digits) for v in values]


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    return [a[0] / n, a[1] / n, a[2] / n]


def blender_to_ue_cm(p):
    """Blender metres -> UE cm as UE's FBX import produces it (Y flipped)."""
    return [p[0] * 100.0, -p[1] * 100.0, p[2] * 100.0]


def load_segments():
    with open(GEN, "r") as handle:
        tree = ast.parse(handle.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SEGMENTS" for t in node.targets):
            rows = ast.literal_eval(node.value)
            out = {}
            for row in rows:
                name, bone, f0, f1, arc_deg, width, hint, colour, radius_target, forward = row
                out[name] = dict(bone=bone, f0=f0, f1=f1, arc_deg=arc_deg, width=width,
                                 hint=hint, radius_target=radius_target, forward_offset=forward)
            return out
    raise RuntimeError("SEGMENTS not found in " + GEN)


def circle_fit_3d(points):
    """Centre, normal and radius of points that lie on one circle (exact data)."""
    count = len(points)
    a = points[0]
    b = points[count // 3]
    c = points[(2 * count) // 3]
    ab = sub(b, a)
    ac = sub(c, a)
    normal = unit(cross(ab, ac))
    # circumcentre of triangle abc
    ab_x_ac = cross(ab, ac)
    term1 = [x * dot(ac, ac) for x in cross(ab_x_ac, ab)]
    term2 = [x * dot(ab, ab) for x in cross(ac, ab_x_ac)]
    denom = 2.0 * dot(ab_x_ac, ab_x_ac)
    centre = [a[i] + (term1[i] + term2[i]) / denom for i in range(3)]
    radii = [norm(sub(p, centre)) for p in points]
    return centre, normal, sum(radii) / len(radii), max(radii) - min(radii)


def sweep_deg(points, centre, normal):
    e1 = unit(sub(points[0], centre))
    e2 = cross(normal, e1)
    total = 0.0
    prev = 0.0
    for p in points[1:]:
        d = sub(p, centre)
        ang = math.atan2(dot(d, e2), dot(d, e1))
        step = ang - prev
        while step > math.pi:
            step -= 2.0 * math.pi
        while step < -math.pi:
            step += 2.0 * math.pi
        total += step
        prev = ang
    return abs(math.degrees(total))


def hand_samples(frames, bone, f0, f1, samples=40):
    last = len(frames) - 1
    f0 = max(0, min(last, f0))
    f1 = max(f0 + 1, min(last, f1))
    out = []
    for step in range(samples):
        u = step / (samples - 1)
        frame = f0 + (f1 - f0) * u
        low = int(math.floor(frame))
        high = min(f1, low + 1)
        mix = frame - low
        a = frames[low][bone]["translation"]
        b = frames[high][bone]["translation"]
        out.append([a[k] * (1.0 - mix) + b[k] * mix for k in "xyz"])
    return out


def nearest(points, p):
    return min(norm(sub(q, p)) for q in points)


def main(report):
    with open(EXTRACT, "r") as handle:
        extract = json.load(handle)
    with open(GUIDE, "r") as handle:
        guide = json.load(handle)
    with open(PARTS, "r") as handle:
        parts_json = {p["name"]: p for p in json.load(handle)}
    segments = load_segments()

    fps = float(guide["fps"])
    frames = guide["frames"]
    duration = float(guide["duration"])

    arcs_file = extract["files"]["SlashArcs_v4.fbx"]
    cluster_file = extract["files"]["SM_IceCluster_v2.fbx"]
    for f in (arcs_file, cluster_file):
        gs = f["raw"]["global_settings"]
        expected = {"UpAxis": 2, "UpAxisSign": 1, "FrontAxis": 1, "FrontAxisSign": 1,
                    "CoordAxis": 0, "CoordAxisSign": -1, "UnitScaleFactor": 100.0}
        for key, value in expected.items():
            if gs.get(key) != value:
                raise RuntimeError("unexpected FBX GlobalSettings %s=%r in %s" % (key, gs.get(key), f["path"]))
        for name, model in f["raw"]["models"].items():
            imp = f["imported"]["objects"][name]["location"]
            lt = model["lcl_translation"]
            # Blender wrote Rz(180) @ matrix_world: Lcl T = (-x, -y, z), Lcl R = (0, 0, 180).
            if (abs(lt[0] + imp[0]) > 1e-4 or abs(lt[1] + imp[1]) > 1e-4 or abs(lt[2] - imp[2]) > 1e-4
                    or abs(abs(model["lcl_rotation"][2]) - 180.0) > 1e-3):
                raise RuntimeError("Lcl transform of %s is not Rz180 @ location" % name)

    order = sorted(segments)
    offset = PLAN_FIRST_SLASH_S - segments[order[0]]["f0"] / fps

    arcs = []
    diagnostics = []
    for name in order:
        seg = segments[name]
        obj = arcs_file["imported"]["objects"][name]
        loc_b = obj["location"]
        low = obj["local_min"]
        high = obj["local_max"]
        rows = obj["uv_vertices"]          # u, v, local xyz, world xyz (Blender metres)
        centre_rows = sorted([row for row in rows if abs(row[1] - 0.5) < 1e-3], key=lambda row: row[0])
        edge0 = sorted([row for row in rows if abs(row[1]) < 1e-3], key=lambda row: row[0])
        edge1 = sorted([row for row in rows if abs(row[1] - 1.0) < 1e-3], key=lambda row: row[0])
        centre_world_b = [row[5:8] for row in centre_rows]
        width_m = max(norm(sub(a[5:8], b[5:8])) for a, b in zip(edge0, edge1))
        circ_c, circ_n, circ_r, circ_err = circle_fit_3d(centre_world_b)
        sweep = sweep_deg(centre_world_b, circ_c, circ_n)

        radius_gen = max(RADIUS_RANGE[0], min(RADIUS_RANGE[1], seg["radius_target"]))
        width_gen = max(WIDTH_RANGE[0], min(WIDTH_RANGE[1], seg["width"]))
        span_gen = max(SPAN_RANGE[0], min(SPAN_RANGE[1], seg["arc_deg"]))

        pivot_ue = blender_to_ue_cm(loc_b)
        bounds = [(high[i] - low[i]) * 100.0 for i in range(3)]

        arcs.append({
            "name": name,
            "pivot_cm": vec(pivot_ue),
            "rotation_deg": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            "scale": [1, 1, 1],
            "frame_range": [seg["f0"], seg["f1"]],
            "time_range_s": [r(seg["f0"] / fps, 4), r(seg["f1"] / fps, 4)],
            "radius_cm": r(radius_gen * 100.0, 1),
            "sweep_deg": r(span_gen, 1),
            "max_width_cm": r(width_gen * 100.0, 1),
            "bounds_cm": vec(bounds),
        })

        # Alignment evidence: hand path (guide, UE cm) vs arc centre-line.
        hand = hand_samples(frames, seg["bone"], seg["f0"], seg["f1"])
        corrected = [[p[0] * 100.0, p[1] * 100.0, p[2] * 100.0] for p in centre_world_b]   # after parent scale (1,-1,1)
        mirrored = [blender_to_ue_cm(p) for p in centre_world_b]                            # raw import, no correction
        d_corr = [nearest(corrected, h) for h in hand]
        d_mirr = [nearest(mirrored, h) for h in hand]
        centre_corr = [circ_c[0] * 100.0, circ_c[1] * 100.0, circ_c[2] * 100.0]
        diagnostics.append({
            "name": name,
            "bone": seg["bone"],
            "measured_radius_cm": r(circ_r * 100.0, 2),
            "circle_residual_cm": r(circ_err * 100.0, 4),
            "measured_sweep_deg": r(sweep, 2),
            "measured_max_width_cm": r(width_m * 100.0, 2),
            "head_corrected_cm": vec([p * 100.0 for p in centre_world_b[0]], 1),
            "tail_corrected_cm": vec([p * 100.0 for p in centre_world_b[-1]], 1),
            "circle_centre_corrected_cm": vec(centre_corr, 1),
            "plane_normal_corrected": vec(circ_n, 3),
            "hand_to_arc_corrected_cm_mean_max": [r(sum(d_corr) / len(d_corr), 1), r(max(d_corr), 1)],
            "hand_to_arc_mirrored_cm_mean_max": [r(sum(d_mirr) / len(d_mirr), 1), r(max(d_mirr), 1)],
            "hand_mean_cm": vec([sum(h[i] for h in hand) / len(hand) for i in range(3)], 1),
            "seq_time_s": r(seg["f0"] / fps + offset, 4),
        })

    # ---- cluster -----------------------------------------------------------
    cluster_parts = []
    low_all = [1e9, 1e9, 1e9]
    high_all = [-1e9, -1e9, -1e9]
    for name in ["SM_IceCluster_Core", "SM_IceCluster_Left", "SM_IceCluster_Right",
                 "SM_IceCluster_Back", "SM_IceCluster_Boulders", "SM_IceCluster_Base"]:
        obj = cluster_file["imported"]["objects"][name]
        loc_b = obj["location"]
        low = obj["local_min"]
        high = obj["local_max"]
        pivot_ue = blender_to_ue_cm(loc_b)
        # local bounds in UE: y range flips
        ue_low = [low[0] * 100.0, -high[1] * 100.0, low[2] * 100.0]
        ue_high = [high[0] * 100.0, -low[1] * 100.0, high[2] * 100.0]
        for i in range(3):
            low_all[i] = min(low_all[i], pivot_ue[i] + ue_low[i])
            high_all[i] = max(high_all[i], pivot_ue[i] + ue_high[i])
        size = [(high[i] - low[i]) * 100.0 for i in range(3)]
        ref = parts_json.get(name)
        if ref and ref["faces"] != obj["polygons"]:
            raise RuntimeError("face count mismatch for %s: %d vs %d" % (name, ref["faces"], obj["polygons"]))
        cluster_parts.append({
            "name": name,
            "pivot_cm": vec(pivot_ue),
            "rotation_deg": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
            "size_cm": vec(size),
            "faces": obj["polygons"],
            "material_role": ROLE[name],
        })
    # Ground anchor: XY centre of the union, Z = bottom of the snow disc (the
    # disc lies on the ground; prism roots that reach below it stay buried).
    base_bottom = blender_to_ue_cm(cluster_file["imported"]["objects"]["SM_IceCluster_Base"]["location"])[2]
    cluster_center = [(low_all[0] + high_all[0]) * 0.5, (low_all[1] + high_all[1]) * 0.5, base_bottom]

    # ---- timeline ----------------------------------------------------------
    def hand_pos(i):
        t = frames[i]["hand_r"]["translation"]
        return [t["x"], t["y"], t["z"]]

    def speed_into(i):
        return norm(sub(hand_pos(i), hand_pos(i - 1))) * fps

    # Impact = the low frame where the downward swing stops hardest
    # (largest drop between incoming and outgoing hand speed).
    candidates = [i for i in range(30, len(frames) - 1) if hand_pos(i)[2] < 30.0]
    impact_frame = max(candidates, key=lambda i: speed_into(i) - speed_into(i + 1))
    impact_anim_s = impact_frame / fps
    timeline = [{"event": "FX_HandEnergy_Start", "time_s": 0.0, "source": "plan"}]
    for name in order:
        idx = name[-2:]
        timeline.append({"event": "FX_Slash_" + idx,
                         "time_s": r(segments[name]["f0"] / fps + offset, 4), "source": "anim"})
    timeline += [
        {"event": "FX_Slash_Impact", "time_s": r(impact_anim_s + offset, 4), "source": "anim"},
        {"event": "FX_IceBurst", "time_s": 3.2, "source": "plan"},
        {"event": "FX_CrystalReveal", "time_s": 4.3, "source": "plan"},
        {"event": "FX_CrystalHold", "time_s": 5.0, "source": "plan"},
        {"event": "FX_End", "time_s": 5.8, "source": "plan"},
    ]

    hand_impact = frames[impact_frame]["hand_r"]["translation"]
    pelvis_impact = frames[impact_frame]["pelvis"]["translation"]

    diag_by = {d["name"]: d for d in diagnostics}
    mean_corr = sum(d["hand_to_arc_corrected_cm_mean_max"][0] for d in diagnostics) / len(diagnostics)
    mean_mirr = sum(d["hand_to_arc_mirrored_cm_mean_max"][0] for d in diagnostics) / len(diagnostics)

    notes = [
        "pivot_cm is the arc/part origin exactly as UE's FBX import produces it (Blender metres x100 with Y negated), "
        "i.e. BEFORE the mirror correction. Arcs: origin = slash head (UV.x=0). Cluster parts: origin = part bottom centre.",
        "Blender FBX export (axis_forward=-Y, axis_up=Z, bake_space_transform=False, FBX_SCALE_ALL) wrote GlobalSettings "
        "Up=+Z, Front=+Y, Coord=-X, UnitScaleFactor=100 and every Model as Lcl Translation (-x,-y,z), Lcl Rotation (0,0,180): "
        "verified in fbx_extract_raw.json. UE (Interchange FFbxConvert::ConvertScene, target Z-up / front -Y / RH) re-rotates "
        "by 180 deg about Z, which cancels Blender's 180, then FFbxConvert::ConvertPos negates Y (RH->LH) and units become cm. "
        "Net: UE = (100x, -100y, 100z) with zero rotation for every object.",
        "SlashGuide is UE component space (left-handed, character faces +Y, right hand on -X, root motion +247 cm along +Y). "
        "generate_slash_arcs_v4.py copied those numbers into right-handed Blender unchanged, so the imported arcs are the "
        "Y-mirror of the hand path. Fix: put all arcs under one parent whose RELATIVE scale is (1,-1,1), attached to the "
        "skeletal mesh component (not the capsule/actor root) at identity location/rotation; each arc keeps its imported "
        "relative transform (pivot_cm, zero rotation) or (0,0,0) if the meshes were baked. Per-arc equivalent without a "
        "parent: world = MeshComponentTransform * Scale(1,-1,1) * Translate(pivot_cm), i.e. actor location "
        "(px, -py, pz) in component space with actor scale (1,-1,1).",
        "Evidence: verify_arc_reproduction.py re-runs the v4 fitting code on the guide and matches the FBX centre-lines "
        "to < 0.001 mm in the guide's own x,y,z, while the Y-mirrored (as-imported) arcs miss by 3.4-7.4 m. Mean distance "
        "from the sampled hand path to the arc centre-line is %.1f cm with the correction versus %.1f cm without it. The "
        "corrected residual is by design: v4 forces radius to 130/170/220 cm, pulls the centre 68%% toward the pelvis and "
        "shifts arcs 0/30/60 cm along -Y." % (mean_corr, mean_mirr),
        "Facing: in guide space the character faces +Y (root motion +Y, right hand on -X). The v4 author treated -Y as "
        "'front' (forward_offset along -Y, plane normals forced to -Y, preview camera at -Y), so after correction the "
        "0/30/60 cm offsets push arcs 02/03 slightly BEHIND the travel direction and the arcs' authored front faces look "
        "toward mesh -Y. The material is TwoSided, so this only matters for camera framing.",
        "Arc 04 dips to z=-72 cm and arc 05 to z=-33 cm below the floor (component space, floor at z=0) and arc 02's "
        "tail reaches z=+9 cm; the floor clips those parts (DepthFade softens the cut).",
        "Negative parent scale reverses triangle winding; UE flips culling for negative-determinant transforms, and "
        "M_SlashArc_v2 is TwoSided anyway, so nothing else changes. The arc's V=0 (gold rim) edge is mirrored with the mesh.",
        "FBX import mode matters: Interchange default bake_meshes=True writes node transforms into the vertices, so every "
        "StaticMesh pivot becomes the FBX scene origin (anim component-space origin). In that case place each arc at (0,0,0) "
        "under the (1,-1,1) parent. With bake_meshes=False the pivot stays at pivot_cm (slash head / part bottom centre). "
        "Verify after import: StaticMesh bounding-box size must equal bounds_cm (arcs) / size_cm*1 (parts); a 100x smaller "
        "size means FBX unit scale ended up on the node and must be compensated (import_uniform_scale 100 or bake).",
        "The cluster parts need bake_meshes=False (or equivalent) because M_IceCrystal_v2 measures growth height from "
        "ObjectPositionWS; with baked meshes the object origin would be the cluster origin, %.1f cm (x4 = %.1f cm) above "
        "the snow-disc bottom." % (-cluster_center[2], -cluster_center[2] * CLUSTER_SCALE),
        "cluster_center_cm is the ground anchor in imported UE cm at scale 1: XY = centre of the union of all six parts, "
        "Z = bottom of SM_IceCluster_Base (the snow disc). Prism roots reach %.2f cm lower (union bottom z=%.2f), i.e. "
        "%.1f cm below the floor at scale 4, which hides them. To stand the cluster on FX_CrystalCenter: cluster parent at "
        "the socket with uniform scale 4 and each part at relative location (pivot_cm - cluster_center_cm) (relative "
        "values are multiplied by the parent's scale 4). Mirroring is irrelevant for the cluster (no animation link); the "
        "split script's 'Back' group (+Y in Blender) ends up on -Y in UE. Union size at scale 1 = %s cm, at scale 4 = %s cm."
        % (base_bottom - low_all[2], low_all[2], (base_bottom - low_all[2]) * CLUSTER_SCALE,
           vec([high_all[i] - low_all[i] for i in range(3)], 1),
           vec([(high_all[i] - low_all[i]) * CLUSTER_SCALE for i in range(3)], 1)),
        "rotation_deg is zero for every object: Blender objects carried only location (no rotation/scale) and the two "
        "180-degree Z rotations cancel in UE's axis conversion.",
        "Arc radius_cm / sweep_deg / max_width_cm are the generator values (generate_slash_arcs_v4.py SEGMENTS after its "
        "clamps); measured from the FBX mesh: radius within 0.01 cm, sweep within 0.1 deg, width up to 0.01 cm smaller "
        "(96 samples miss u=0.5 exactly). bounds_cm is the local AABB size (abs, unaffected by the mirror).",
        "time_range_s on arcs are ANIMATION times (frame/30); add anim_start_offset_s for sequence time. All timeline "
        "time_s values are sequence times.",
        "anim_start_offset_s = 1.4 - 10/30 = %.4f s: the attack starts at that sequence time and holds frame 0 before it "
        "(hand-energy prep 0.0-1.4 s). The animation then ends at %.4f s sequence time (duration %.4f s); hold its last "
        "frame afterwards." % (offset, offset + duration, duration),
        "FX_Slash_01..05 are anim-matched: notify at each arc's window start f0 (arc reveal +0.05 s, full +0.20 s, gone "
        "+0.35 s). With f0 as the trigger, FX_Slash_01 reaches full brightness at anim frame 16 (0.533 s), the peak hand "
        "speed of that swing. Plan times were 1.4 / 1.8 / 2.2 for slashes 1-3; anim-matched slash 2 is %.4f and slash 3 is "
        "%.4f. Slashes 04 and 05 are the extra layers of the big third sweep (05 is the left hand)."
        % (diag_by["SM_SlashArc_02"]["seq_time_s"], diag_by["SM_SlashArc_03"]["seq_time_s"]),
        "FX_Slash_Impact is anim-matched to frame %d (anim %.4f s), where the downward swing lands: hand_r z=%.1f cm and "
        "its speed drops from %.0f to %.0f cm/s; plan said 2.6 s. Hand_r at impact (guide = corrected component space) = "
        "(%.1f, %.1f, %.1f) cm; pelvis = (%.1f, %.1f, %.1f) cm, so the impact lies ~%.0f cm in front of the pelvis, not "
        "the plan's 165 cm socket offset (that offset assumed the root stays put; here the root travels with the lunge)."
        % (impact_frame, impact_anim_s, hand_impact["z"], speed_into(impact_frame), speed_into(impact_frame + 1),
           hand_impact["x"], hand_impact["y"], hand_impact["z"], pelvis_impact["x"], pelvis_impact["y"],
           pelvis_impact["z"], hand_impact["y"] - pelvis_impact["y"]),
        "Showcase check (if the correction is right): seen from the side, all five arcs sit along the lunge, between the "
        "start position and ~3.75 m ahead along mesh +Y (corrected world AABBs span y = +4..+375 cm), wrapping the "
        "character's path (arc 03 circle centre ~(-15, 201, 137) cm vs pelvis mean ~(-25, 223, 113) during its swing); "
        "arc 03's tail ends near the ground just short of where hand_r lands at frame %d; at FX_Slash_01 + 0.20 s the "
        "right hand (41.9, 189.7, 158.5) is inside arc 01's circle (68 cm from its centre, radius 130) on the "
        "character's left side (mesh +X). If the arcs instead extend 0-3.75 m BEHIND the start position (mesh -Y) "
        "while the character lunges forward, the (1,-1,1) parent is missing or applied at the wrong level." % impact_frame,
        "FX_IceBurst 3.2, FX_CrystalReveal 4.3, FX_CrystalHold 5.0 and FX_End 5.8 keep the user's plan times (burst "
        "3.2-4.3, grow 4.3-5.0, hold 5.0-5.8, settle/fade 5.8-7.0; the sequence ends at 7.0). FX_End marks the start of "
        "the fade. Every event after %.4f s happens after the animation has ended, so those must be Sequencer events "
        "(or an AnimNotify placed on a held/extended section), not AnimNotifies inside the 2.03 s sequence asset."
        % (offset + duration),
        "If AnimNotifies are added to the AnimSequence asset itself, use animation time = time_s - anim_start_offset_s "
        "(FX_Slash_01 0.3333, _02 0.4667, _03 1.0333, _04 1.2000, _05 1.2333, FX_Slash_Impact %.4f)." % impact_anim_s,
        "The guide includes root motion (pelvis travels from y=0 to y=247 cm). The arcs line up only if the animation "
        "plays without root-motion extraction/root lock (component-space root moves). If the AnimSequence has "
        "enable_root_motion=True and the player locks the root, the hand path shifts back by the root translation "
        "(up to ~247 cm along mesh +Y) and the arcs will appear ahead of the character.",
        "The guide was sampled on the RamsterZ (UE4 mannequin) skeleton. On Guard (via RTG_TraversalUE4ToManny/RTG_Guard) "
        "proportions differ, so expect a few cm to ~20 cm deviation between Guard's hand and the arcs.",
        "anim.frames = 61 = duration*fps frame intervals; the guide holds 61 samples (t = 0.0..2.0 s) and the UE "
        "sequence has 62 keys (0..61).",
    ]

    data = {
        "units": "UE cm, X forward, Y right, Z up",
        "mirror_correction": {
            "needed": True,
            "parent_scale": [1, -1, 1],
            "explanation": (
                "The guide is UE (left-handed) component-space cm. generate_slash_arcs_v4.py copied x,y,z unchanged into "
                "right-handed Blender metres, Blender exported with axis_forward=-Y/axis_up=Z (Rz180 on every node, "
                "Front=+Y in GlobalSettings), and UE's FBX import undoes the Rz180 and then negates Y for the RH->LH "
                "conversion. Net effect: imported arc vertex = (x, -y, z) of the guide-space position, a mirror across "
                "the XZ plane. Parent all arcs under a component attached to the skeletal mesh component with relative "
                "scale (1,-1,1) (identity location/rotation); children keep their imported transforms. That maps every "
                "vertex back to guide space, where it follows the hand path."),
            "confidence": "high",
        },
        "arcs": arcs,
        "cluster_parts": cluster_parts,
        "cluster_scale": CLUSTER_SCALE,
        "cluster_center_cm": vec(cluster_center),
        "anim": {"asset": ANIM_ASSET, "fps": int(fps), "duration_s": r(duration, 4),
                 "frames": int(round(duration * fps))},
        "anim_start_offset_s": r(offset, 4),
        "timeline": timeline,
        "arc_reveal": {"start_offset_s": 0.05, "full_s": 0.20, "gone_s": 0.35},
        "notes": notes,
    }

    with open(OUT, "w") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print("WROTE", OUT)

    if report:
        print(json.dumps(diagnostics, indent=1))
        print("cluster union low/high", vec(low_all), vec(high_all))
        print("impact frame", impact_frame, hand_impact, pelvis_impact)


if __name__ == "__main__":
    main("--report" in sys.argv)
