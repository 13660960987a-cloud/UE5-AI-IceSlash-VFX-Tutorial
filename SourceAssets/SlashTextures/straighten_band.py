"""Straighten the AI crescent slash image into a UV-aligned strip.

The AI source (AI_SlashArc_Stylized_src.png) is a curved crescent on black.
The slash meshes are UV'd with U along the slash (0 = head) and V across the
ribbon, so the band has to be unbent: for every column we find the band's top
and bottom extent and resample that span onto the full output height. Top of
the output (V=0) is the golden rim, bottom (V=1) is the dark brush edge.

Output: T_SlashArc_Base.png, 2048x512 RGBA, alpha keyed from black.

Run with Blender's bundled Python (numpy):
  python3.13 -I straighten_band.py <src.png> <dst.png>
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "VFXSprites"))
from black_to_alpha import read_png, write_png  # noqa: E402

OUT_W, OUT_H = 2048, 512
PRESENCE_MIN = 0.12   # brightness above which a pixel belongs to the band
PAD = 6               # extra source rows kept above/below the band


def smooth(values, radius):
    kernel = np.ones(2 * radius + 1) / (2 * radius + 1)
    padded = np.pad(values, radius, mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def band_edges(presence):
    """Per-column top/bottom rows of the band, cleaned and smoothed."""
    h, w = presence.shape
    rows = np.arange(h)[:, None]
    inside = presence > PRESENCE_MIN
    has = inside.sum(axis=0) > 3
    top = np.where(has, np.where(inside, rows, h).min(axis=0), np.nan)
    bottom = np.where(has, np.where(inside, rows, -1).max(axis=0), np.nan)
    cols = np.flatnonzero(has)
    # Fill gaps by interpolation, then median-ish smoothing to ignore stray sparkles.
    top = np.interp(np.arange(w), cols, top[cols])
    bottom = np.interp(np.arange(w), cols, bottom[cols])
    return smooth(top, 9), smooth(bottom, 9), cols.min(), cols.max()


def main():
    src, dst = sys.argv[1], sys.argv[2]
    rgb = read_png(src)
    presence = rgb.max(axis=2)
    top, bottom, x0, x1 = band_edges(presence)
    print(f"band columns {x0}..{x1}, height range {np.min(bottom - top):.0f}..{np.max(bottom - top):.0f}px")

    h = rgb.shape[0]
    out = np.zeros((OUT_H, OUT_W, 3))
    xs = np.linspace(x0, x1, OUT_W)
    v = np.linspace(0.0, 1.0, OUT_H)
    for i, x in enumerate(xs):
        xi = int(round(x))
        t, b = top[xi] - PAD, bottom[xi] + PAD
        src_rows = np.clip(t + v * (b - t), 0, h - 1)
        lo = np.floor(src_rows).astype(int)
        hi = np.minimum(lo + 1, h - 1)
        f = (src_rows - lo)[:, None]
        out[:, i] = rgb[lo, xi] * (1 - f) + rgb[hi, xi] * f

    a = np.clip((out.max(axis=2) - 0.04) / 0.96, 0, 1)
    color = np.where(a[..., None] > 1e-3, np.clip(out / np.maximum(a[..., None], 1e-3), 0, 1), 0)
    write_png(dst, np.dstack([color, a]))
    print(f"wrote {dst} {OUT_W}x{OUT_H} alpha-coverage={a.mean():.3f}")


if __name__ == "__main__":
    main()
