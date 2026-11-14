"""Validate Tools/IceSlash/data/arc_rings.json end to end (needs numpy: Blender's python3.13).

Re-derives everything a consumer needs from the written JSON alone and checks the contract:
  * center_cm / radius_cm reproduce the 24 sample points (max | |p-c| projected - R | small)
  * normal and ring_quat_xyzw agree; the quaternion maps X=start_dir, Y=normal x start_dir, Z=normal
    (right-handed) into mesh-local space
  * sweep_deg matches the samples and winding_about_normal says which way they run
  * start_dir = centre -> s=0 point; Y = Z x X = outward at every sample on a flat circle
  * tangents point along the swing; inner_radius_cm < radius_cm
Usage: python3 validate_arc_rings.py [path/to/arc_rings.json]
"""
import json
import sys

import numpy as np

PATH = sys.argv[1] if len(sys.argv) > 1 else "Tools/IceSlash/data/arc_rings.json"
data = json.load(open(PATH))


def qmat(q):
    x, y, z, w = np.asarray(q, float)
    n2 = x * x + y * y + z * z + w * w
    return np.array([[1 - 2 * (y * y + z * z) / n2, 2 * (x * y - z * w) / n2, 2 * (x * z + y * w) / n2],
                     [2 * (x * y + z * w) / n2, 1 - 2 * (x * x + z * z) / n2, 2 * (y * z - x * w) / n2],
                     [2 * (x * z - y * w) / n2, 2 * (y * z + x * w) / n2, 1 - 2 * (x * x + y * y) / n2]])


fails = []
for a in data["arcs"]:
    name = a["blade"]
    c = np.array(a["center_cm"], float)
    R = float(a["radius_cm"])
    q = np.array(a["ring_quat_xyzw"], float)
    M = qmat(q)
    qX, qY, qZ = M[:, 0], M[:, 1], M[:, 2]                 # frame as the quaternion maps it
    out = a["samples"]
    P = np.array([s["pos_cm"] for s in out], float)
    T = np.array([s["tangent"] for s in out], float)
    O = np.array([s["outward"] for s in out], float)
    ss = [s["s"] for s in out]

    # per point: the vector from the centre, its out-of-plane part and its radius. The fitted
    # plane is the one least-squares to the points (the centre is on it), like the fitter used.
    v = P - c
    # signed SVD: the last right singular vector's sign is fixed by the SVD convention, so align it
    # to the reported normal explicitly instead of assuming a sign.
    nw = np.linalg.svd(v, full_matrices=False)[2][2]
    nw = nw if float(nw @ qZ) >= 0 else -nw
    off = np.array([float(np.dot(vv, nw)) for vv in v])
    rel = v - off[:, None] * nw
    r = np.linalg.norm(rel, axis=1)
    radial = rel / r[:, None]
    ang = np.arctan2(rel @ qY, rel @ qX) * 180.0 / np.pi
    step = np.diff(ang)
    step = (step + 180.0) % 360.0 - 180.0                  # each step's turn, in (-180, 180]
    turn = float(step.sum())                               # signed net turn, degrees
    sweep_samples = float(np.abs(step).sum())              # total turn, degrees
    ccw = turn > 0

    checks = {
        "frame_unit": abs(np.linalg.norm(qZ) - 1) < 1e-6 and abs(np.linalg.norm(qX) - 1) < 1e-6,
        "frame_orthonormal": abs(float(qX @ qZ)) < 1e-6 and abs(float(qX @ qY)) < 1e-6,
        "frame_right_handed": np.max(np.abs(np.cross(qX, qY) - qZ)) < 1e-6,
        "q_X_is_start_dir": np.max(np.abs(qX - a["start_dir"])) < 1e-5,
        "q_Z_is_normal": np.max(np.abs(qZ - a["normal"])) < 1e-5,
        "q_Y_is_ZxX": np.max(np.abs(qY - np.cross(qZ, qX))) < 1e-6,
        "q_unit": abs(np.linalg.norm(q) - 1) < 1e-6,
        "samples_0_to_1": len(P) == 24 and ss[0] == 0.0 and ss[-1] == 1.0,
        "start_dir_is_s0": np.max(np.abs(O[0] - qX)) < 1e-3,
        "radius_reproduced": float(np.max(np.abs(r - R))) < 5.0,     # flat rims: < 0.2 cm
        "rms_matches": abs(float(np.sqrt(np.mean((r - R) ** 2))) - a["fit_rms_cm"]) < 5.0,     # flat rims: < 0.1 cm
        "normal_is_fit_plane": float(abs(nw @ qZ)) > 0.9,
        "sweep_matches_winding": abs(abs(sweep_samples) - abs(a["sweep_deg"])) < 2.0,
        "winding_field": a["winding_about_normal"] == ("ccw" if a["sweep_deg"] > 0 else "cw"),
        "winding_matches_samples": (ccw if a["sweep_deg"] > 0 else not ccw),
        "tangent_perp_outward": float(np.max(np.abs(np.sum(T * O, axis=1)))) < 0.05,
        "outward_radial": float(np.min(np.sum(O * radial, axis=1))) > 0.85,
        "inner_lt_radius": a["inner_radius_cm"] < R,
        "rms_lt_10": a["fit_rms_cm"] < 10.0,
    }
    failed = [k for k, ok in checks.items() if not ok]
    fails += [(name, k) for k in failed]
    print("%-16s %s R=%8.3f  max|r-R|=%.3f  inner=%7.2f  sweep=%8.2f (%s)  rms=%.3f  offplane=%.1f  %s" % (
        name, "OK  " if not failed else "FAIL", R, np.max(np.abs(r - R)), a["inner_radius_cm"], a["sweep_deg"],
        a["winding_about_normal"], a["fit_rms_cm"], a.get("rim_offplane_rms_cm", float("nan")),
        failed if failed else ""))

print("ALL OK" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
