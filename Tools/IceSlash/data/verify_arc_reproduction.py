"""Prove that the SlashArcs_v4 FBX geometry is the guide's UE numbers copied 1:1.

Re-runs the pure-numpy fitting functions of Saved/VFX/generate_slash_arcs_v4.py
(only its constants and function definitions are executed, never main()) on
the guide JSON and compares the resulting centre-lines (metres, in the guide's
own x/y/z) with the centre-line vertices (UV.y = 0.5) that Blender re-imported
from SlashArcs_v4.fbx (fbx_extract_raw.json). A match at the micrometre level
shows Blender world == guide/100 with no axis change, so the only axis change
is the one UE applies at FBX import (Y negated).

Run with Blender's Python (numpy is needed):
  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
      -P Tools/IceSlash/data/verify_arc_reproduction.py -- <project root>
"""

import ast
import json
import math
import os
import sys

import numpy as np

KEEP_FUNCS = {"load_clip", "joint_position", "window_points", "body_centre", "fit_plane",
              "plane_basis", "fit_circle", "build_segment"}
KEEP_NAMES = {"JSON_PATH", "HERE", "MIN_ARC_LENGTH", "RADIUS_RANGE", "WIDTH_RANGE",
              "TAPER_EXPONENT", "SEGMENTS"}


def project_root():
    argv = sys.argv
    if "--" in argv and len(argv) > argv.index("--") + 1:
        return os.path.abspath(argv[argv.index("--") + 1])
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


def load_generator(path):
    with open(path, "r") as handle:
        tree = ast.parse(handle.read())
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in KEEP_FUNCS:
            body.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in KEEP_NAMES for t in node.targets):
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    namespace = {"np": np, "math": math, "os": os, "json": json, "__file__": path}
    exec(compile(module, path, "exec"), namespace)
    return namespace


def main():
    root = project_root()
    gen = load_generator(os.path.join(root, "Saved", "VFX", "generate_slash_arcs_v4.py"))
    frames, fps = gen["load_clip"]()
    with open(os.path.join(root, "Tools", "IceSlash", "data", "fbx_extract_raw.json"), "r") as handle:
        extract = json.load(handle)
    objects = extract["files"]["SlashArcs_v4.fbx"]["imported"]["objects"]

    worst = 0.0
    for row in gen["SEGMENTS"]:
        name, bone, f0, f1, arc_deg, width, hint, colour, radius_target, forward = row
        centerline, centre, diag = gen["build_segment"](frames, bone, f0, f1, arc_deg, width, hint,
                                                        radius_target, forward)
        rows = sorted([r for r in objects[name]["uv_vertices"] if abs(r[1] - 0.5) < 1e-3],
                      key=lambda r: r[0])
        fbx = np.array([r[5:8] for r in rows])
        same = float(np.max(np.linalg.norm(fbx - centerline, axis=1)))
        mirrored = fbx * np.array([1.0, -1.0, 1.0])
        mirror_err = float(np.max(np.linalg.norm(mirrored - centerline, axis=1)))
        worst = max(worst, same)
        print("REPRO %s max|fbx-guide|=%.6f m  max|mirrorY(fbx)-guide|=%.3f m  centre=%s normal=%s"
              % (name, same, mirror_err, np.round(centre * 100.0, 2), np.round(diag["normal"], 4)))
    print("REPRO_WORST_M %.8f" % worst)
    if worst > 1e-4:
        raise RuntimeError("FBX arcs do not reproduce the guide numbers")


main()
