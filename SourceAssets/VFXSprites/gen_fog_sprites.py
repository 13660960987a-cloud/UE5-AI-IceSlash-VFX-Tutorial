"""Fog / mist sprites for the ice slash, to be drawn on camera-facing sheets (AmberGorge, task D2).

The mist is a quad (面片) that always faces the camera, textured with one of these soft cloud
puffs. All of them are built the same way: a spectral 1/f^beta noise field times a radial /
shaped falloff, so each sprite has layered cloud structure rather than a flat blob, and every
edge is faded to transparent so a quad never shows a hard border.

  T_VFX_FogPuff_A.png    512 x 512  one round puff
  T_VFX_FogPuff_B.png    512 x 512  two-three puffs joined into a bank
  T_VFX_FogPuff_C.png    512 x 512  flattened (wide) puff
  T_VFX_FogPuff_D.png    512 x 512  puff with a bitten-out notch
  T_VFX_SmokeWisp_A.png  1024 x 256 a long wispy streak of smoke, both ends fading out

Contract (checked at the end of the run, the script fails otherwise):
  * RGBA PNG, 8 bit
  * alpha = 0 within the outer 16 px on every side
  * alpha falls off smoothly from the middle: a from the centre outward reaching 0 at the edge
  * RGB in 0.9 .. 1.0 (white to pale grey), independent of alpha

Usage (Blender's bundled python has numpy):
  /Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13 gen_fog_sprites.py [out_dir]

Writes two previews, both showing the five sprites at their own relative size:
  fog_sprites_preview.png          on a dark background (where the mist will read)
  fog_sprites_preview_onwhite.png  on a light background (shows the real opacity/cloud structure)

The cloud is 1/f^beta noise (beta 2.0, in the middle of the spec's 1.8-2.2) shaped by the
sprite's silhouette, and the alpha profile is density**OMEGA_EXP: steep at the foot, soft at the
head, so opacity falls off smoothly from the middle and the last opaque pixel is well inside
the 16 px no-alpha border.
"""
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
from black_to_alpha import write_png  # noqa: E402  (same-directory helper, as asked)

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
MARGIN = 16            # alpha must be 0 within this border
BETA = 2.0             # 1/f^beta cloud spectrum (spec: 1.8 - 2.2)
OMEGA_EXP = 2.6        # alpha = density ** OMEGA_EXP: steep foot, soft head (see omega())


# ---------------------------------------------------------------- noise
def spectral_noise(n, beta=BETA, seed=0, anisotropy=(1.0, 1.0)):
    """Periodic 1/f^beta noise, n x n in [0, 1], zero mean before normalising.

    Frequency-grid anisotropy > 1 stretches the cells along that axis, so features get longer in
    the matching image direction (anisotropy=(0.45, 1) -> wide, (1, 3.2) -> streaky)."""
    r = np.random.default_rng(seed)
    fy = np.fft.fftfreq(n)[:, None] * anisotropy[0]
    fx = np.fft.fftfreq(n)[None, :] * anisotropy[1]
    f = np.sqrt(fx * fx + fy * fy)
    f[0, 0] = 1.0
    amp = f ** (-beta / 2.0)                       # power ~ 1/f^beta
    phase = r.uniform(0, 2 * np.pi, (n, n))
    field = np.fft.ifft2(np.fft.fft2(r.normal(size=(n, n))) * amp * np.exp(1j * phase)).real
    field -= field.mean()
    sd = field.std()
    return 0.5 + 0.18 * field / sd if sd > 0 else np.full((n, n), 0.5)


def fbm(n, beta, octaves=2, seed=0, anisotropy=(1.0, 1.0)):
    """Layered cloud: a few spectral scales; the fine scales add detail at light weight."""
    acc = np.zeros((n, n))
    weight = 1.0
    total = 0.0
    for k in range(octaves):
        acc += weight * spectral_noise(n, beta, seed + 101 * k,
                                       anisotropy=(anisotropy[0] * (2 ** k), anisotropy[1] * (2 ** k)))
        total += weight
        weight *= 0.40
    return smooth_blur(acc / total, 1.6)          # roll off pixel-scale speckle (1/f^2 leaves some)


def smoke_field(w, h, beta, octaves, seed):
    """Layered spectral noise at the sprite's own aspect. Frequencies are per pixel, so "long along
    the wisp" is a low x-frequency weight and fine detail a higher one that still tiles smoothly."""
    r = np.random.default_rng(seed)
    fx = np.fft.fftfreq(w)[None, :]
    fy = np.fft.fftfreq(h)[:, None]
    acc = np.zeros((h, w))
    weight, total = 1.0, 0.0
    for k in range(octaves):
        # features ~ L px long and L/3.5 px thick; L halves each octave
        L = 256.0 / (1.7 ** k)
        spread = np.exp(-0.5 * ((np.sqrt((fx * L) ** 2 + (fy * L / 3.5) ** 2) - 1.0) / 0.55) ** 2)
        spread[0, 0] = 0.0
        field = np.fft.ifft2(np.fft.fft2(r.normal(size=(h, w))) * spread).real
        field -= field.mean()
        sd = field.std()
        acc += weight * (0.5 + 0.18 * field / sd if sd > 0 else 0.5)
        total += weight
        weight *= 0.45
    return acc / total


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def grid(nx, ny):
    """Pixel-centre coordinates in [-1, 1] on both axes (so a 512 square maps 1:1 by aspect)."""
    x = (np.arange(nx) + 0.5) / nx * 2 - 1
    y = (np.arange(ny) + 0.5) / ny * 2 - 1
    return np.meshgrid(x, y)


def border_fade(nx, ny, margin=MARGIN):
    """1 everywhere except a smooth ramp to exactly 0 at the outer `margin` pixels."""
    xs = np.minimum(np.arange(nx) + 0.5, nx - np.arange(nx) - 0.5)   # px distance to the nearest edge
    ys = np.minimum(np.arange(ny) + 0.5, ny - np.arange(ny) - 0.5)
    fx = smoothstep(margin, margin * 2.0, xs)
    fy = smoothstep(margin, margin * 2.0, ys)
    return fy[:, None] * fx[None, :]


def falloff(X, Y, cx=0.0, cy=0.0, rx=0.86, ry=0.86, wobble=None, power=2.0):
    """Soft rounded falloff: 1 at the centre, 0 outside radius 1, monotone in between."""
    ang = np.arctan2((Y - cy) / ry, (X - cx) / rx)
    r = np.sqrt(((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2)
    if wobble is not None:
        r = r * (1.0 + 0.22 * wobble(ang))
    # smooth 1 -> 0 at r = 1 (C1 at the rim), with `power` softening the shoulder
    edge = smoothstep(1.0, 0.15, r) ** 1.0
    return edge ** (power * 0.5), r


def wobble_fn(seed, harmonics=(2, 3, 5, 7)):
    r = np.random.default_rng(seed)
    ph = r.uniform(0, 2 * np.pi, len(harmonics))
    am = r.uniform(0.4, 1.0, len(harmonics))
    am /= am.sum()
    return lambda a: sum(m * np.sin(h * a + p) for h, m, p in zip(harmonics, am, ph))


def billow(shape, cloud, strength=0.85):
    """Cloud density carried through a shape: the shape is the silhouette and the softened noise
    etches cloud structure into it (never below half of the shape, so no holes appear)."""
    shape = np.clip(shape, 0, 1)
    c = np.clip((cloud - 0.5) / 0.30, -1.0, 1.0)              # -1 .. 1 around the mean
    mod = 1.0 + strength * c * np.sqrt(shape)                  # scaled by the shape
    return np.clip(shape * np.clip(mod, 0.5, 1.5), 0.0, 1.0)


def lp(a, gain=0.35):
    """Cloud structure as brightness: keep the field's own mean, add `gain` x its normalised
    deviation (one sd of it), so the noise reads as light shading and dark stays dark."""
    a = np.asarray(a, float)
    sd = a.std()
    if sd < 1e-9:
        return np.clip(a, 0.0, 1.0)
    return np.clip(a + gain * (a - a.mean()) / sd, 0.0, 1.0)


def omega(body, core, detail, coarse):
    """Turn a body density into a lit cloud whose opacity falls off smoothly from the middle.

    Anything built from the noise directly has a hard foot (the noise crosses zero steeply), so
    the field is first raised to OMEGA_EXP: steep at the foot, soft at the head; the cloud's
    local contrast is then folded in as a modulation of that opacity."""
    edge = np.clip(body, 0, 1) ** OMEGA_EXP
    edge = edge * (0.86 + 0.28 * (coarse - 0.5))
    mid = np.clip(core * detail, 0, 1) ** (OMEGA_EXP + 0.4)
    den = np.clip(0.8 * edge + 0.3 * mid, 0, 1)
    # peak 0.95 so no billow clips to a flat white plateau; the cloud's local contrast stays a
    # *relative* modulation (-35 % .. +25 %), so it reads as shading without punching holes
    return np.clip(0.95 * den * (1.0 + 0.3 * (detail - detail.mean()) / max(detail.std(), 1e-9)), 0, 0.97)


def cloud_pair(n, seed, anisotropy=(1.0, 1.0)):
    """(fine, coarse) cloud fields: the coarse one is the 1/f noise again but low-passed."""
    fine = fbm(n, BETA, seed=seed, anisotropy=anisotropy)
    coarse = smooth_blur(fbm(n, BETA, seed=seed + 7, anisotropy=anisotropy), max(6.0, n / 28.0))
    coarse = (coarse - coarse.mean()) / max(coarse.std(), 1e-9) * 0.18 + 0.5
    return fine, coarse


def smooth_blur(a, sigma):
    """Gaussian blur of a 2D array via FFT (periodic is fine: the sprite is 0 at the border)."""
    n0, n1 = a.shape
    fy = np.fft.fftfreq(n0)[:, None]
    fx = np.fft.fftfreq(n1)[None, :]
    k = np.exp(-2 * (np.pi ** 2) * (sigma ** 2) * (fx * fx + fy * fy))
    return np.clip(np.fft.ifft2(np.fft.fft2(a) * k).real, 0.0, None)   # tiny negative round-off


def shade(alpha, tint=0.93, X=None, Y=None, light=0.02):
    """Pale clouds: RGB in 0.9..1.0 with a faint round shading (the side nearer the upper left is
    white, the lower rim a touch greyer) so a lit-looking puff sits in the quad. A as computed."""
    a = np.clip(alpha, 0.0, 1.0)
    g = smoothstep(0.0, 0.5, a)                    # fringe slightly greyer than the core
    rgb = tint + (1.0 - tint) * g
    if X is not None:
        lit = np.clip(0.5 - 0.5 * (0.6 * X + 0.8 * Y), 0.0, 1.0)   # 0 upper-left .. 1 lower-right
        rgb = rgb + light * (1.0 - 2.0 * lit)
    rgb = np.clip(rgb, 0.9, 1.0)
    return np.dstack([rgb, rgb, rgb, a])


# ---------------------------------------------------------------- the sprites
def fog_puff_a(n=512):
    """One round puff: soft round falloff, billowing cloud structure inside, A 0 at the edge."""
    X, Y = grid(n, n)
    shape, _ = falloff(X, Y, 0.0, 0.0, 0.80, 0.80, wobble=wobble_fn(3), power=2.4)
    cloud, coarse = cloud_pair(n, 11)
    density = billow(shape, cloud, strength=1.0)
    core = falloff(X, Y, -0.04, -0.05, 0.52, 0.50, wobble=wobble_fn(31), power=2.0)[0]
    alpha = omega(shape, core, density, coarse) * border_fade(n, n)
    return shade(alpha, tint=0.93, X=X, Y=Y)



def fog_puff_b(n=512):
    """Two-three puffs joined into a drifting bank."""
    X, Y = grid(n, n)
    lobes = [(-0.34, 0.06, 0.46, 0.42), (0.08, -0.08, 0.52, 0.46), (0.42, 0.12, 0.34, 0.32)]
    acc = np.zeros((n, n))
    cores = []
    for i, (cx, cy, rx, ry) in enumerate(lobes):
        f, _ = falloff(X, Y, cx, cy, rx, ry, wobble=wobble_fn(7 + i), power=2.2)
        acc = np.maximum(acc, f)
        c, _ = falloff(X, Y, cx * 0.85, cy - 0.03, rx * 0.6, ry * 0.58, wobble=wobble_fn(40 + i), power=2.0)
        cores.append(c)
    acc = smooth_blur(acc, 6.0)                    # blend the lobe seams into one soft bank
    acc /= acc.max()
    core = smooth_blur(np.maximum.reduce(cores), 4.0)
    cloud, coarse = cloud_pair(n, 23)
    density = billow(acc ** 0.8, cloud, strength=1.0)
    alpha = omega(acc, core, density, coarse) * border_fade(n, n)
    return shade(alpha, tint=0.95, X=X, Y=Y)


def fog_puff_c(n=512):
    """A flat, wide puff (horizon-filling mist): shape and noise both stretched horizontally."""
    X, Y = grid(n, n)
    shape, _ = falloff(X, Y, 0.0, 0.02, 0.86, 0.46, wobble=wobble_fn(9), power=2.2)
    cloud, coarse = cloud_pair(n, 37, anisotropy=(0.45, 1.0))    # long features along X
    density = billow(shape, cloud, strength=0.9)
    alpha = np.clip(0.95 * density, 0, 1) * border_fade(n, n)
    return shade(alpha, tint=0.94, X=X, Y=Y)


def fog_puff_d(n=512):
    """A puff with a bitten-out notch (an irregular bank edge, e.g. where it meets the blade)."""
    X, Y = grid(n, n)
    shape, _ = falloff(X, Y, -0.05, 0.04, 0.78, 0.75, wobble=wobble_fn(17), power=2.3)
    cloud, coarse = cloud_pair(n, 51)
    density = billow(shape, cloud, strength=0.9)
    # the bite: a soft disc cut from the upper right, its rim ragged from the cloud noise
    bite_r = np.sqrt((X - 0.50) ** 2 + (Y - 0.52) ** 2)
    bite = smoothstep(0.30, 0.52, bite_r - 0.10 * (cloud - 0.5) * 2.0)
    core = falloff(X, Y, -0.10, -0.02, 0.50, 0.48, wobble=wobble_fn(27), power=2.0)[0]
    alpha = np.clip(0.85 * shape * (0.82 + 0.36 * (coarse - 0.5)) + 0.35 * core * density, 0, 1)
    cube = smoothstep(0.0, 1.0, np.clip(alpha, 0, 1))
    alpha = lp(0.55 * alpha ** 1.5 + 0.45 * cube, gain=0.5) * (0.06 + 0.94 * bite) * border_fade(n, n)
    return shade(alpha, tint=0.94, X=X, Y=Y)


def smoke_wisp(w=1024, h=256):
    """A long horizontal wisp of smoke: a soft curling body, streaky detail, both ends fading.

    Built in a 4x-tall working canvas and squashed to 1024 x 256 at the end: a texture-space
    cross-section is what makes the wisp round on the quad; drawn directly at the sprite's aspect
    the same profile reads as a flat ribbon."""
    hs = h * 4
    x = (np.arange(w) + 0.5) / w * 2 - 1
    y = (np.arange(hs) + 0.5) / hs * 2 - 1
    X, Y = np.meshgrid(x, y)
    t = (X + 1) * 0.5                                   # 0 .. 1 along the wisp
    centre = 0.10 * np.sin(2 * np.pi * 1.1 * t + 0.6) + 0.05 * np.sin(2 * np.pi * 2.7 * t + 1.9)
    taper = np.sin(np.pi * np.clip(t, 0, 1)) ** 1.3     # thick body, tapering to nothing at the ends
    width = 0.22 * taper + 0.035
    d = np.abs(Y - centre) / width
    body = smoothstep(1.25, 0.0, d) ** 1.2               # soft band: 1 on the centre line, 0 past 1.25 w
    # streaky detail: noise with long features along X, sampled only inside the body
    n = max(w, h)
    cloud = smooth_blur(smoke_field(w, hs, BETA, 2, 77), 1.5)   # long thin bands along the wisp
    coarse = smooth_blur(cloud, 12.0)
    coarse = (coarse - coarse.mean()) / max(coarse.std(), 1e-9) * 0.18 + 0.5
    density = billow(body, cloud, strength=0.8)
    end = smoothstep(0.0, 0.16, t) * smoothstep(1.0, 0.84, t)
    # thin spiral strands: the same band, a narrower core on a different curl, at partial weight
    strand_c = 0.10 * np.sin(2 * np.pi * 1.1 * t + 0.6 + 1.2) + 0.09 * np.sin(2 * np.pi * 3.3 * t + 0.3)
    sd = np.abs(Y - strand_c) / (0.13 * taper + 0.01)
    strand = smoothstep(1.2, 0.0, sd) ** 2 * smooth_blur(smoke_field(w, hs, BETA, 2, 78), 1.2)
    alpha = (0.42 * body + 0.62 * density * body + 0.35 * strand) * end
    w_body = np.exp(-(np.abs(Y - centre) / (width * 1.1)) ** 2)        # soft gaussian across the wisp
    a0 = np.clip(alpha, 0, 1)
    alpha = (0.6 * a0 ** 1.4 + 0.4 * smoothstep(0.0, 1.0, a0)) * np.clip(w_body, 0, 1) ** 0.8
    alpha = alpha ** 1.6
    # squash the tall working canvas to 1024 x 256: box-average each column of 4 pixels
    alpha = alpha.reshape(h, 4, w).mean(axis=1)
    yy = (np.arange(h) + 0.5) / h * 2 - 1
    Xf, Yf = np.meshgrid(x, yy)
    alpha = alpha * border_fade(w, h)
    return shade(alpha, tint=0.95, X=Xf, Y=Yf)


# ---------------------------------------------------------------- checks & preview
def check(name, rgba, margin=MARGIN):
    h, w = rgba.shape[:2]
    a = rgba[..., 3]
    rgb = rgba[..., :3]
    problems = []
    if (a[:margin, :] > 0).any() or (a[-margin:, :] > 0).any() or \
       (a[:, :margin] > 0).any() or (a[:, -margin:] > 0).any():
        problems.append("alpha not 0 in the outer %d px" % margin)
    if not (0.9 - 1e-6 <= rgb.min() and rgb.max() <= 1.0 + 1e-6):
        problems.append("RGB out of 0.9..1.0 (%g..%g)" % (rgb.min(), rgb.max()))
    # centre -> edge falloff: mean alpha of rings around the centre must decrease
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    rings = [a[(r >= lo) & (r < lo + 0.2)].mean() for lo in np.arange(0, 1.0, 0.2)]
    if not all(x1 >= x2 - 0.02 for x1, x2 in zip(rings, rings[1:])):
        problems.append("alpha not monotone from centre out: %s" % np.round(rings, 3).tolist())
    cov = (a > 0.05).mean()
    print("%-22s %4dx%-4d coverage=%.3f  rings=%s %s" % (
        name, w, h, cov, np.round(rings, 2).tolist(), "OK" if not problems else "FAIL " + "; ".join(problems)))
    return not problems


def preview(items, path):
    """All sprites on a dark background at their own relative size, labelled by file name."""
    pad, gap, bg = 24, 24, 0.03
    scale = 0.5                                        # show at half resolution
    tiles = [(nm, np.array(im)) for nm, im in items]
    tiles = [(nm, im[::2, ::2], im.shape[0] / 2, im.shape[1] / 2) for nm, im in tiles]
    width = pad + sum(t[3] for t in tiles) + gap * (len(tiles) - 1) + pad
    height = pad + max(t[2] for t in tiles) + pad
    canvas = np.full((int(height), int(width), 3), bg)
    x0 = pad
    for nm, im, th, tw in tiles:
        a = im[..., 3][..., None]
        tile = im[..., :3] * a + canvas[pad:pad + int(th), x0:x0 + int(tw)] * (1 - a)
        canvas[pad:pad + int(th), x0:x0 + int(tw)] = tile
        x0 += int(tw) + gap
    write_png(str(path), np.dstack([canvas, np.ones(canvas.shape[:2])]))
    # same tiles over white (shows the cloud's real opacity the way it reads in game)
    white = np.ones_like(canvas) * 0.92
    x0 = pad
    for nm, im, th, tw in tiles:
        a = im[..., 3][..., None]
        white[pad:pad + int(th), x0:x0 + int(tw)] = im[..., :3] * a + white[pad:pad + int(th), x0:x0 + int(tw)] * (1 - a)
        x0 += int(tw) + gap
    write_png(str(path.with_name(path.stem + "_onwhite.png")), np.dstack([white, np.ones(white.shape[:2])]))
    print("PREVIEW", path, canvas.shape[1], "x", canvas.shape[0])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sprites = [
        ("T_VFX_FogPuff_A", fog_puff_a()),
        ("T_VFX_FogPuff_B", fog_puff_b()),
        ("T_VFX_FogPuff_C", fog_puff_c()),
        ("T_VFX_FogPuff_D", fog_puff_d()),
        ("T_VFX_SmokeWisp_A", smoke_wisp()),
    ]
    ok = True
    for name, rgba in sprites:
        path = OUT / (name + ".png")
        write_png(str(path), rgba)
        ok &= check(path.name, rgba)
        print("WROTE", path)
    preview(sprites, OUT / "fog_sprites_preview.png")
    if not ok:
        raise SystemExit("sprite checks failed")


if __name__ == "__main__":
    main()