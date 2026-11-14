"""Key a painted slash crescent off its magenta background and measure its circle.

1. Alpha from colour distance to the magenta key, then un-mix the magenta spill from
   semi-transparent pixels (C = a*F + (1-a)*M  ->  F = (C - (1-a)*M) / a).
2. Fit a circle to the bright gold rim (least squares) and measure the crescent's angular span
   and radial extent around that centre. Written next to the PNG as <name>.json so the
   Blender sheet builder can map the crescent onto each slash plane without distortion.

Usage (Blender's bundled Python has numpy):
  python3.13 -I key_painted_blade.py <src.png> <dst.png>
"""
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "VFXSprites"))
from black_to_alpha import read_png, write_png  # noqa: E402

KEY = np.array([1.0, 0.0, 1.0])
PAD = 96   # transparent margin added around the painting so the baked glow layer
           # (bake_blade_layers.py) has room outside the rim; all measurements include it


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def rim_curve(a, cx, cy, start, span, head_at_start, columns=160):
    """Outer edge of the opaque crescent, ordered tail -> head and resampled by arc length.

    For every 0.5 degree ray from the pole (cx, cy) the farthest pixel with alpha > 0.6 is the
    outer edge (the gold rim). The polyline is smoothed, resampled to `columns` points, and an
    inward normal (toward the pole side) is computed per point. depth_px is how far inward the
    painted body reaches (max over columns), glow_px how far the soft glow reaches outward.
    """
    h, w = a.shape
    edge = []
    for k in range(int(span * 2) + 1):
        ang = math.radians(start + k * 0.5)
        dx, dy = math.cos(ang), math.sin(ang)
        best = None
        for rr in range(int(1.6 * max(h, w))):
            x, y = int(cx + dx * rr), int(cy + dy * rr)
            if not (0 <= x < w and 0 <= y < h):
                break
            if a[y, x] > 0.6:
                best = (cx + dx * rr, cy + dy * rr)
        if best:
            edge.append(best)
    pts = np.array(edge)
    kernel = np.ones(9) / 9.0
    pts = np.column_stack([np.convolve(np.pad(pts[:, i], 4, mode='edge'), kernel, mode='valid') for i in (0, 1)])
    if head_at_start:
        pts = pts[::-1]                      # make index 0 the tail
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    target = np.linspace(0.0, cum[-1], columns)
    res = np.column_stack([np.interp(target, cum, pts[:, i]) for i in (0, 1)])
    tang = np.gradient(res, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
    to_pole = np.array([cx, cy]) - res
    flip = np.sign(np.sum(nrm * to_pole, axis=1))
    nrm *= flip[:, None]
    depths, glow = [], 0.0
    for p, n in zip(res, nrm):
        # Walk inward only until the body ends (12 consecutive transparent pixels); do not
        # continue across the empty concave side into the opposite part of the crescent.
        last_in, gap = 0.0, 0
        for d in range(0, 900):
            x, y = int(p[0] + n[0] * d), int(p[1] + n[1] * d)
            if not (0 <= x < w and 0 <= y < h):
                break
            if a[y, x] > 0.05:
                last_in, gap = float(d), 0
            else:
                gap += 1
                if gap > 12:
                    break
        depths.append(last_in)
        for d in range(0, 200):
            x, y = int(p[0] - n[0] * d), int(p[1] - n[1] * d)
            if not (0 <= x < w and 0 <= y < h):
                break
            if a[y, x] > 0.03:
                glow = max(glow, float(d))
    depth = float(np.percentile(depths, 99))
    return ([[round(float(x), 2), round(float(y), 2)] for x, y in res],
            [[round(float(x), 4), round(float(y), 4)] for x, y in nrm],
            round(depth + 6.0, 1), round(glow + 4.0, 1))


def main():
    src, dst = sys.argv[1], sys.argv[2]
    tmp = '/tmp/_key_src.png'
    subprocess.run(['sips', '-s', 'format', 'png', src, '--out', tmp], check=True, capture_output=True)
    rgb = read_png(tmp)
    h, w, _ = rgb.shape
    # Sample the real key colour from the corners (AI backgrounds are rarely exact #FF00FF).
    corners = np.concatenate([rgb[:8, :8].reshape(-1, 3), rgb[:8, -8:].reshape(-1, 3),
                              rgb[-8:, :8].reshape(-1, 3), rgb[-8:, -8:].reshape(-1, 3)])
    key = np.median(corners, axis=0)
    padded = np.empty((h + 2 * PAD, w + 2 * PAD, 3))
    padded[:] = key
    padded[PAD:PAD + h, PAD:PAD + w] = rgb
    rgb = padded
    h, w, _ = rgb.shape
    dist = np.linalg.norm(rgb - key, axis=2)
    a = smoothstep(0.10, 0.50, dist)
    safe = np.maximum(a, 1e-3)[..., None]
    fg = np.clip((rgb - (1.0 - a[..., None]) * key) / safe, 0.0, 1.0)
    fg[a < 0.02] = 0.0
    # Despill: warm glow pixels that kept a pink cast get their blue clamped below green.
    warm = (fg[..., 0] > fg[..., 1]) & (fg[..., 0] > 0.5) & (fg[..., 2] > fg[..., 1])
    fg[..., 2] = np.where(warm, np.minimum(fg[..., 2], fg[..., 1] * 0.55), fg[..., 2])
    write_png(dst, np.dstack([fg, a]))

    # Rim = bright, warm, opaque pixels.
    r, g, b = fg[..., 0], fg[..., 1], fg[..., 2]
    rim = (a > 0.6) & (r > 0.85) & (g > 0.55) & (r > b + 0.15)
    ys, xs = np.nonzero(rim)
    # Kasa algebraic circle fit: x^2 + y^2 + D x + E y + F = 0
    A = np.column_stack([xs, ys, np.ones_like(xs)]).astype(float)
    bb = -(xs.astype(float) ** 2 + ys.astype(float) ** 2)
    D, E, F = np.linalg.lstsq(A, bb, rcond=None)[0]
    cx, cy = -D / 2.0, -E / 2.0
    radius = math.sqrt(cx * cx + cy * cy - F)

    # Angular span and radial extent of everything visible around that centre.
    vy, vx = np.nonzero(a > 0.08)
    ang = np.degrees(np.arctan2(vy - cy, vx - cx))          # image coords: y down
    rad = np.hypot(vx - cx, vy - cy) / radius
    # Unwrap around the gap: find the largest empty angular sector and start after it.
    hist = np.zeros(360, bool)
    hist[(np.round(ang).astype(int) + 360) % 360] = True
    best_len, best_end, run = 0, 0, 0
    for i in range(720):
        if not hist[i % 360]:
            run += 1
            if run > best_len:
                best_len, best_end = run, i
        else:
            run = 0
    start = (best_end + 1) % 360
    rel = (ang - start) % 360
    span = float(rel.max())
    # Which end is the wide head? Compare visible pixel counts in the first/last 20 % of the span.
    first = np.count_nonzero(rel < 0.2 * span)
    last = np.count_nonzero(rel > 0.8 * span)
    head_at_start = first > last
    rim_pts, normals, depth_px, glow_px = rim_curve(a, cx, cy, start, span, head_at_start)
    info = {
        'rim_points_px': rim_pts, 'rim_normals': normals, 'depth_px': depth_px, 'glow_px': glow_px,
        'rim_note': 'rim_points run from TAIL (index 0) to HEAD (last); normals point inward (toward the body)',
        'width': w, 'height': h, 'centre_px': [round(cx, 2), round(cy, 2)], 'rim_radius_px': round(radius, 2),
        'span_start_deg': float(start), 'span_deg': round(span, 2),
        'head_end': 'start' if head_at_start else 'end',
        'radius_min': round(float(np.percentile(rad, 1)), 3), 'radius_max': round(float(np.percentile(rad, 99.7)), 3),
        'angles': 'image space, degrees, 0 = +x (right), positive = clockwise on screen (y down)',
        'alpha_coverage': round(float(a.mean()), 3), 'key_rgb': [round(float(k), 3) for k in key],
    }
    Path(dst).with_suffix('.json').write_text(json.dumps(info, indent=1))
    print(json.dumps(info))


if __name__ == '__main__':
    main()
