"""Hit-feedback sprites for the ice slash (NobleShore).

The reference's mid-scale layer (between the big crescent blades and the small snowflakes /
stars) is the hit feedback at each slash: a long thin light streak skimming the ground with a
white-hot core and cyan glow, and a white-gold starburst flash where the blade meets the target.

  T_VFX_HitStreak_A.png  256 x 1024, vertical (long axis = V) so a velocity-aligned sprite
                         stretches along the slash direction; white core, cyan halo, tapered
                         ends, the front (top) end brighter, plus a few thinner side lines.
  T_VFX_HitFlash_A.png   512 x 512, starburst: white core, pale-gold spikes of random length,
                         a few long thin rays.
  T_VFX_HitSplash_A.png  T_VFX_GroundBrushTrail_A turned upright (spray end up), for the dark-blue
                         splash under the streak.

RGB = colour, A = intensity (the IceSlash sprite materials multiply texture, tint and particle
colour). Usage: python3.13 -I gen_hit_sprites.py <out_dir>
"""
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from black_to_alpha import write_png  # noqa: E402

rng = np.random.default_rng(5)
out = Path(sys.argv[1])


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- streak
W, H = 256, 1024
x = (np.arange(W) + 0.5) / W * 2 - 1          # -1 .. 1 across
y = (np.arange(H) + 0.5) / H                  # 0 top (front) .. 1 bottom (tail)
X, Y = np.meshgrid(x, y)
# envelope along the streak: sharp front, long fading tail
env = smoothstep(0.0, 0.10, Y) * (1 - smoothstep(0.35, 1.0, Y)) ** 0.8
width = 0.05 + 0.10 * np.sin(np.clip(Y, 0, 1) * math.pi) ** 0.7
core = np.exp(-(X / (width * 0.18)) ** 2) * env
glow = np.exp(-(X / (width * 0.9)) ** 2) * env
halo = np.exp(-(X / (width * 2.6)) ** 2) * env * 0.45
lines = np.zeros_like(X)
for _ in range(7):                            # thinner speed lines beside the main beam
    off = rng.uniform(0.18, 0.55) * rng.choice([-1, 1])
    y0 = rng.uniform(0.05, 0.45)
    y1 = y0 + rng.uniform(0.25, 0.55)
    seg = smoothstep(y0, y0 + 0.06, Y) * (1 - smoothstep(y1 - 0.15, y1, Y))
    lines += np.exp(-((X - off) / 0.012) ** 2) * seg * rng.uniform(0.35, 0.8)
inten = np.clip(core * 1.0 + glow * 0.55 + halo + lines * 0.7, 0, 1)
white = np.array([1.0, 1.0, 1.0])
cyan = np.array([0.35, 0.85, 1.0])
mix = np.clip(core * 1.6 + lines * 0.3, 0, 1)[..., None]
rgb = white * mix + cyan * (1 - mix)
write_png(str(out / "T_VFX_HitStreak_A.png"), np.dstack([rgb, inten]))

# ---------------------------------------------------------------- flash
N = 512
c = (np.arange(N) + 0.5) / N * 2 - 1
FX, FY = np.meshgrid(c, c)
r = np.hypot(FX, FY)
a = np.arctan2(FY, FX)
spikes = np.zeros_like(r)
n = 18
for k in range(n):
    ang = 2 * math.pi * k / n + rng.uniform(-0.12, 0.12)
    length = rng.uniform(0.45, 0.95) if k % 2 == 0 else rng.uniform(0.25, 0.55)
    half = rng.uniform(0.16, 0.26)                      # angular half width at the base
    d = np.angle(np.exp(1j * (a - ang)))
    taper = np.clip(1 - r / length, 0, 1)                # spike narrows to a point
    edge = np.maximum(half * taper ** 1.1, 1e-4)        # angular half width at this radius
    spikes = np.maximum(spikes, smoothstep(edge, edge * 0.7, np.abs(d)) * taper ** 0.45)
rays = np.zeros_like(r)
for k in range(6):                                       # long thin rays
    ang = rng.uniform(0, 2 * math.pi)
    d = np.angle(np.exp(1j * (a - ang)))
    rays = np.maximum(rays, np.exp(-(d * r / 0.012) ** 2) * np.clip(1 - r / 0.98, 0, 1))
core_f = np.exp(-(r / 0.24) ** 2)
glow_f = np.exp(-(r / 0.42) ** 2) * 0.5
spk = np.clip(spikes, 0, 1)
inten = np.clip(core_f + glow_f + spk * 0.95 + rays * 0.8, 0, 1) * smoothstep(1.0, 0.92, r)
gold = np.array([1.0, 0.88, 0.52])
mixf = np.clip(core_f * 1.4 + (1 - r) ** 3, 0, 1)[..., None]
rgb = white * mixf + gold * (1 - mixf)
write_png(str(out / "T_VFX_HitFlash_A.png"), np.dstack([rgb, inten]))
# ---------------------------------------------------------------- splash
# The dark-blue ink splash under the streak reuses the ground-brush painting, turned so its
# spray end (right) points up like the streak's front.
src = out / "T_VFX_GroundBrushTrail_A.png"
if src.exists():
    import struct
    import zlib
    data = src.read_bytes()
    pos, idat = 8, b""
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        tag, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + ln]
        if tag == b"IHDR":
            bw, bh, depth, ctype = struct.unpack(">IIBB", body[:10])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + ln
    assert depth == 8 and ctype == 6
    raw = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(bh, bw * 4 + 1)
    img = np.zeros((bh, bw * 4), np.int32)
    prev = np.zeros(bw * 4, np.int32)
    for yy in range(bh):
        f, line = raw[yy, 0], raw[yy, 1:].astype(np.int32)
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 255
        else:
            cur = np.zeros(bw * 4, np.int32)
            for xx in range(bw * 4):
                aa = cur[xx - 4] if xx >= 4 else 0
                bb, cc = prev[xx], (prev[xx - 4] if xx >= 4 else 0)
                if f == 1:
                    pr = aa
                elif f == 3:
                    pr = (aa + bb) // 2
                else:
                    pa, pb, pc = abs(bb - cc), abs(aa - cc), abs(aa + bb - 2 * cc)
                    pr = aa if pa <= pb and pa <= pc else (bb if pb <= pc else cc)
                cur[xx] = (line[xx] + pr) & 255
        img[yy], prev = cur, cur
    img = img.reshape(bh, bw, 4) / 255.0
    write_png(str(out / "T_VFX_HitSplash_A.png"), np.rot90(img, 1))
print("ok")
