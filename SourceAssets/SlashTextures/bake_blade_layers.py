"""Bake the mask and emissive layers for the painted slash crescent (NobleShore).

The reference blade is not one solid painted block: only the gold rim, a cyan fill band under
the rim (wide at the head, thin toward the tail) and the line art (swirl curls, hair strands)
are solid; the rest of the body is see-through with a faint blue haze, and every bright edge
carries a soft glow (warm halo outside the rim, cyan halo around the lines).

Inputs:  T_SlashBlade_Painted.png (+ .json from key_painted_blade.py: rim polyline tail->head,
         inward normals, depth_px).
Outputs (same size, same UV0 space as the painting, so one TexCoord samples all three):
  T_SlashBlade_BodyMask.png  linear  R = visibility (multiplies the painting's alpha)
                                     G = line art (extra emission on the lines)
                                     B = fill band (debug / optional use)
  T_SlashBlade_Emissive.png  sRGB    RGB = glow colour, A = glow strength; extends beyond the
                                     painted alpha (the sheet mesh has room for it outside the rim)
  T_SlashBlade_LayersPreview.png     composite over a dark background for review

Usage: python3.13 -I bake_blade_layers.py <painted.png> <painted.json> <out_dir>
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "VFXSprites"))
from black_to_alpha import write_png  # noqa: E402


def read_rgba(path):
    """8-bit RGBA PNG -> float HxWx4 (handles all scanline filters)."""
    import struct
    import zlib
    data = Path(path).read_bytes()
    pos, idat = 8, b""
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and ctype == 6, "need 8-bit RGBA"
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    raw = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(h, w * 4 + 1)
    out = np.zeros((h, w * 4), np.int32)
    prev = np.zeros(w * 4, np.int32)
    for y in range(h):
        f, line = raw[y, 0], raw[y, 1:].astype(np.int32)
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 255
        else:
            cur = np.zeros(w * 4, np.int32)
            for x in range(w * 4):
                a = cur[x - 4] if x >= 4 else 0
                b, c = prev[x], (prev[x - 4] if x >= 4 else 0)
                if f == 1:
                    pr = a
                elif f == 3:
                    pr = (a + b) // 2
                else:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[x] = (line[x] + pr) & 255
        out[y], prev = cur, cur
    return out.reshape(h, w, 4) / 255.0

# --- art direction (painting pixels; s = 0 tail .. 1 head along the rim, d = px inward) ---
RIM_DEPTH = 34.0                     # rim + white core stay solid down to this depth
BAND_TAIL, BAND_HEAD = 22.0, 250.0   # cyan fill band depth at the tail / the head
BAND_S0, BAND_S1 = 0.25, 0.82        # where the band widens from tail to head depth
BAND_SOFT = 0.45                     # soft edge of the band, as a fraction of its depth
HAZE = 0.06                          # faint blue haze left in the hollow body
LINE_LO, LINE_HI = 0.022, 0.075      # high-pass thresholds for line art
GLOW_SIGMAS = (3.0, 9.0, 22.0, 40.0)       # emissive halo: tight core + mid + wide
GLOW_WEIGHTS = (0.55, 0.38, 0.20, 0.14)
GLOW_GAIN = 1.6
GLOW_SAT = 1.0                       # push halo colour saturation (orange around rim, cyan around lines)
BORDER_FADE = 24.0                   # fade glow to 0 at the image border (texture is clamped)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def gblur(img, sigma):
    """Gaussian blur via FFT with zero padding (no scipy in Blender's Python)."""
    pad = int(math.ceil(3 * sigma)) + 2
    two_d = img.ndim == 2
    a = img[..., None] if two_d else img
    h, w, c = a.shape
    p = np.zeros((h + 2 * pad, w + 2 * pad, c), np.float64)
    p[pad:pad + h, pad:pad + w] = a
    fy = np.fft.fftfreq(p.shape[0])[:, None]
    fx = np.fft.rfftfreq(p.shape[1])[None, :]
    tf = np.exp(-2.0 * (math.pi * sigma) ** 2 * (fx * fx + fy * fy))
    out = np.empty_like(p)
    for i in range(c):
        out[..., i] = np.fft.irfft2(np.fft.rfft2(p[..., i]) * tf, s=p.shape[:2])
    out = out[pad:pad + h, pad:pad + w]
    return out[..., 0] if two_d else out


def value_noise(u, v, seed, octaves=3):
    """Fractal value noise at float coords (u, v); smooth, deterministic."""
    rng = np.random.default_rng(seed)
    total, amp, norm = np.zeros_like(u), 1.0, 0.0
    for o in range(octaves):
        f = 2 ** o
        grid = rng.random((256, 256))
        x, y = u * f, v * f
        x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
        tx, ty = x - x0, y - y0
        tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        g = lambda i, j: grid[(y0 + j) % 256, (x0 + i) % 256]  # noqa: E731
        n = (g(0, 0) * (1 - tx) + g(1, 0) * tx) * (1 - ty) + (g(0, 1) * (1 - tx) + g(1, 1) * tx) * ty
        total += n * amp
        norm += amp
        amp *= 0.5
    return total / norm


def rim_coords(info, mask):
    """(s, d) for every pixel in `mask`: nearest point on the densified rim polyline."""
    rim = np.array(info["rim_points_px"], np.float64)
    nrm = np.array(info["rim_normals"], np.float64)
    n = 1280
    t = np.linspace(0, len(rim) - 1, n)
    i0 = np.minimum(t.astype(int), len(rim) - 2)
    f = (t - i0)[:, None]
    R = rim[i0] * (1 - f) + rim[i0 + 1] * f
    N = nrm[i0] * (1 - f) + nrm[i0 + 1] * f
    N /= np.linalg.norm(N, axis=1, keepdims=True)
    ys, xs = np.nonzero(mask)
    P = np.column_stack([xs, ys]).astype(np.float32)
    Rf = R.astype(np.float32)
    idx = np.empty(len(P), int)
    for a in range(0, len(P), 4096):
        q = P[a:a + 4096]
        d2 = ((q[:, None, :] - Rf[None, :, :]) ** 2).sum(-1)
        idx[a:a + 4096] = d2.argmin(1)
    s = idx / (n - 1)
    d = ((P - R[idx]) * N[idx]).sum(1)
    S = np.zeros(mask.shape)
    D = np.full(mask.shape, -1e3)
    S[ys, xs], D[ys, xs] = s, d
    return S, D


def main():
    src, info_path, out_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    info = json.load(open(info_path))
    img = read_rgba(src)
    rgb, a = img[..., :3], img[..., 3]
    h, w = a.shape
    lum = rgb @ np.array([0.30, 0.59, 0.11])

    S, D = rim_coords(info, a > 0.004)

    # rim: solid down to RIM_DEPTH (gold + white core), plus everything outside the rim (glow)
    rim_zone = 1.0 - smoothstep(RIM_DEPTH * 0.7, RIM_DEPTH * 1.3, D)
    # pixels far 'outside' the rim are body past the rim's ends (flame fringe), not rim glow
    near_rim = smoothstep(-95.0, -60.0, D)
    rim_zone *= near_rim

    # fill band: depth grows from tail to head; its inner edge is broken into streaks that run
    # along the sweep (noise stretched along s, fast across d) like the reference's smoky edge
    band = BAND_TAIL + (BAND_HEAD - BAND_TAIL) * smoothstep(BAND_S0, BAND_S1, S)
    streak = value_noise(S * 9.0, np.maximum(D, 0) / 11.0, seed=7)
    edge = band * (1.0 + 0.55 * (streak - 0.5))
    fill = 1.0 - smoothstep(edge * (1 - BAND_SOFT), edge * (1 + BAND_SOFT * 0.5), D)
    # dark navy inside the band reads as smoke, bright cyan as solid paint
    fill *= (0.30 + 0.70 * smoothstep(0.12, 0.45, lum)) * near_rim
    # the ragged flame fringe on the inner edge dissolves into haze instead of a dark outline
    fill *= smoothstep(0.45, 0.95, gblur(a, 6.0))

    # line art: bright thin features = high-pass of luminance (painted alpha premultiplied)
    # normalised convolution: the blur only averages painted pixels, so the alpha boundary of
    # the body is not mistaken for a line; lines must also sit inside the body, not on its edge
    hp = lum - gblur(lum * a, 4.0) / np.maximum(gblur(a, 4.0), 1e-3)
    inside = smoothstep(0.80, 0.97, gblur(a, 3.0))
    lines = smoothstep(LINE_LO, LINE_HI, hp) * smoothstep(0.10, 0.25, lum) * inside
    lines = np.maximum(lines, np.clip(gblur(lines, 1.0) * 1.6, 0, 1))      # close 1px gaps
    # dim royal-blue hair strands stay thin and half-transparent; cyan/white line art is solid
    lines *= 0.30 + 0.70 * smoothstep(0.26, 0.55, lum)

    haze = HAZE * (0.5 + value_noise(S * 6.0, np.maximum(D, 0) / 26.0, seed=11))
    vis = np.clip(np.maximum.reduce([rim_zone, fill, lines, haze]), 0, 1)
    vis[a <= 0.004] = 1.0            # outside the painting the alpha is already 0
    write_png(str(out_dir / "T_SlashBlade_BodyMask.png"),
              np.dstack([vis, lines, np.clip(fill, 0, 1), np.ones_like(vis)]))

    # emissive halo from what stays visible, weighted toward bright pixels
    vis_a = a * vis
    wgt = vis_a * smoothstep(0.22, 0.75, lum)
    prem = np.zeros_like(rgb)
    amt = np.zeros_like(a)
    for sg, wt in zip(GLOW_SIGMAS, GLOW_WEIGHTS):
        prem += wt * gblur(rgb * wgt[..., None], sg)
        amt += wt * gblur(wgt, sg)
    col = prem / np.maximum(amt, 1e-4)[..., None]
    gl = col @ np.array([0.30, 0.59, 0.11])
    col = np.clip(gl[..., None] + (col - gl[..., None]) * GLOW_SAT, 0, 1)
    col /= np.maximum(col.max(-1, keepdims=True), 1e-4)           # normalised hue, brightness in A
    # warm halo leans gold (reference: white-gold rim, orange only at the very outside)
    warm = smoothstep(0.05, 0.35, col[..., 0] - col[..., 2])[..., None]
    col = col * (1 - 0.45 * warm) + np.array([1.0, 0.78, 0.42]) * 0.45 * warm
    yy, xx = np.mgrid[0:h, 0:w]
    border = np.minimum.reduce([xx, yy, w - 1 - xx, h - 1 - yy]).astype(np.float64)
    glow_a = np.clip(amt * GLOW_GAIN, 0, 1) * smoothstep(0, BORDER_FADE, border)
    col[glow_a < 0.002] = 0.0
    write_png(str(out_dir / "T_SlashBlade_Emissive.png"), np.dstack([col, glow_a]))

    # preview: dark bg, glow composited like the material (over), painting over that
    bg = np.ones_like(rgb) * np.array([0.035, 0.045, 0.08])
    comp = bg * (1 - glow_a[..., None] * 0.85) + col * glow_a[..., None] * 0.85
    comp = comp * (1 - vis_a[..., None]) + rgb * vis_a[..., None]
    comp = np.clip(comp + col * glow_a[..., None] * 0.25 * vis_a[..., None], 0, 1)
    write_png(str(out_dir / "T_SlashBlade_LayersPreview.png"), np.dstack([comp, np.ones_like(a)]))
    print(json.dumps({"vis_mean": round(float(vis_a.mean()), 4), "paint_alpha_mean": round(float(a.mean()), 4),
                      "glow_px_outside": int((glow_a > 0.03).sum() - (a > 0.03).sum()),
                      "d_range": [round(float(D[a > 0.004].min()), 1), round(float(D[a > 0.004].max()), 1)]}))


if __name__ == "__main__":
    main()
