"""Procedural slash-arc textures matched to the SlashArcs_v4 UV layout.

UV convention (from generate_slash_arcs_v4.py):
  U (x) runs along the slash, 0 = start -> 1 = tail
  V (y) runs across the ribbon, 0 / 1 = edges, 0.5 = core

Outputs 1024x256 RGBA PNGs (wide, since slashes are long and thin):
  T_SlashArc_Mask  R = cross-section core falloff, G = along-slash head/tail fade,
                   B = jagged dissolve edge noise, A = combined alpha
  T_SlashArc_Glow  white-hot inner edge with a warm-yellow rim on one side
  T_SlashArc_Noise tileable flowing energy streaks (tiles in U)

Run with Blender's bundled Python (has numpy):
  .../Blender.app/Contents/Resources/5.2/python/bin/python3.13 -I gen_slash_textures.py <outdir>
"""
import sys
import zlib
import struct
from pathlib import Path

import numpy as np

W, H = 1024, 256
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
rng = np.random.default_rng(7)

u = np.linspace(0.0, 1.0, W)[None, :].repeat(H, 0)
v = np.linspace(0.0, 1.0, H)[:, None].repeat(W, 1)


def save_png(path, rgba):
    """Write an 8-bit RGBA PNG with only the standard library + numpy."""
    img = (np.clip(rgba, 0.0, 1.0) * 255 + 0.5).astype(np.uint8)
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)
    print("wrote", path)


def value_noise(freq_u, freq_v, octaves=4, tile_u=True):
    """Fractal value noise; tiles in U so it can scroll along the slash."""
    acc = np.zeros((H, W))
    amp, total = 1.0, 0.0
    for o in range(octaves):
        fu, fv = freq_u * 2 ** o, freq_v * 2 ** o
        grid = rng.random((fv + 2, fu + 1))
        if tile_u:
            grid[:, -1] = grid[:, 0]
        x = u * fu
        y = v * fv
        x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
        tx, ty = x - x0, y - y0
        tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        x1 = np.minimum(x0 + 1, fu)
        y1 = np.minimum(y0 + 1, fv + 1)
        n = (grid[y0, x0] * (1 - tx) * (1 - ty) + grid[y0, x1] * tx * (1 - ty)
             + grid[y1, x0] * (1 - tx) * ty + grid[y1, x1] * tx * ty)
        acc += n * amp
        total += amp
        amp *= 0.5
    return acc / total


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# Cross-section: 0 at the ribbon edges, 1 at the core.
across = 1.0 - np.abs(v - 0.5) * 2.0

# --- Mask -------------------------------------------------------------------
core = across ** 1.6
# Sharp head, long fading tail (the slash leads at U=0 and trails off to U=1).
along = smoothstep(0.0, 0.06, u) * (1.0 - smoothstep(0.35, 1.0, u)) ** 0.8
edge_noise = value_noise(24, 4, octaves=4)
# Jagged erosion that bites in more toward the tail, for the dissolve look.
dissolve = smoothstep(0.25 + 0.55 * u, 0.35 + 0.55 * u, edge_noise * 0.6 + across * 0.7)
alpha = core * along * dissolve
save_png(OUT / "T_SlashArc_Mask.png", np.dstack([core, along, edge_noise, alpha]))

# --- Glow -------------------------------------------------------------------
# Thin white-hot line just inside the leading (V=0) edge, warm rim on that edge.
inner_line = np.exp(-((v - 0.18) / 0.045) ** 2)
warm_rim = np.exp(-((v - 0.06) / 0.035) ** 2) * (1.0 - smoothstep(0.5, 1.0, u))
white = inner_line * along
glow_rgb = (white[..., None] * np.array([1.0, 1.0, 1.0])
            + warm_rim[..., None] * np.array([1.0, 0.78, 0.35]))
glow_a = np.clip(white + warm_rim, 0.0, 1.0)
save_png(OUT / "T_SlashArc_Glow.png", np.dstack([glow_rgb, glow_a]))

# --- Noise ------------------------------------------------------------------
# Long streaks along U (energy flow), tileable in U for panning in the material.
streaks = value_noise(6, 24, octaves=5)
swirl = value_noise(12, 6, octaves=3)
flow = smoothstep(0.35, 0.8, streaks * 0.75 + swirl * 0.35)
save_png(OUT / "T_SlashArc_Noise.png", np.dstack([flow, flow, flow, np.ones_like(flow)]))

# --- Preview: composite as the material would (core blue + white + warm) -----
base = np.array([0.15, 0.55, 1.0])
col = (alpha[..., None] * base * (0.6 + 0.8 * flow[..., None])
       + glow_rgb * glow_a[..., None] * along[..., None])
bg = np.array([0.02, 0.025, 0.04])
prev = bg + col
save_png(OUT / "preview_composite.png", np.dstack([prev, np.ones((H, W))]))
