"""Generate T_SlashOuterGlow.png (2048x256 RGBA) for the narrow outer-rim emissive strip mesh
SM_SlashOuterGlow_01..05.

Exact radial fusion math against T_SlashBlade_Painted.png:
  - Mesh spans d_px in [-78.0, +52.0] (v_raw=0 -> -78px outer air, v_raw=1 -> +52px inside Blade's white-gold core).
  - On T_SlashBlade_Painted.png, Blade's outer edge drops sharply across d_px = +8 -> -8 px, while d_px = +16..+36 px
    is warm gold and d_px = +40..+64 px is warm white.
  - To fuse with ZERO hard edge and ZERO secondary ribbon:
      * Peak sits right across Blade's outer seam (d_px = +6 px) with NO flat clamping plateau.
      * Inward (d_px = +6 -> +46 px): smooth raised-cosine^2 handoff into Blade's warm gold/white core.
      * Outward (d_px = +6 -> -60 px): concave power-exponential mist falloff ((1 - t)^2.75) reaching 0.000
        well inside the 18 px Alpha=0 border margin so no mesh boundary is ever visible.
      * RGB uses low-saturation warm champagne-gold (Hue ~42 deg, matching Blade's golden rim without redness).
"""
import math
import os
from PIL import Image

OUT_DIR = "/Users/mengmeile/Downloads/lianxi/m/SourceAssets/SlashTextures"
OUT_PNG = os.path.join(OUT_DIR, "T_SlashOuterGlow.png")
OUT_PREVIEW = os.path.join(OUT_DIR, "T_SlashOuterGlow_Preview.png")

W, H = 2048, 256
MARGIN_U = 24
MARGIN_V = 18

D_OUTER = -78.0
D_INNER = 52.0


def smoothstep(e0, e1, x):
    if e1 == e0:
        return 0.0
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


def fbm1d(x, freqs):
    acc = 0.0
    wsum = 0.0
    for freq, amp, phase in freqs:
        acc += amp * (0.5 + 0.5 * math.sin(x * freq * 2.0 * math.pi + phase))
        wsum += amp
    return acc / max(wsum, 1e-6)


def main():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = img.load()

    u_prof = [0.0] * W
    u_fil = [0.0] * W
    freqs = [(3.0, 0.50, 0.4), (7.0, 0.32, 1.9), (13.0, 0.18, 3.7)]

    for x in range(W):
        if x < MARGIN_U or x >= W - MARGIN_U:
            u_prof[x] = 0.0
            continue
        u = (x - MARGIN_U) / float(W - 1 - 2 * MARGIN_U)
        # Long, silky-smooth raised-cosine^1.6 taper at tail and head so tips melt seamlessly into Blade
        tail_in = smoothstep(0.03, 0.36, u) ** 1.35
        head_out = (1.0 - smoothstep(0.64, 0.93, u)) ** 1.45
        belly = 0.85 + 0.18 * smoothstep(0.22, 0.58, u)
        u_prof[x] = tail_in * head_out * belly
        u_fil[x] = fbm1d(u, freqs)

    for y in range(H):
        if y < MARGIN_V or y >= H - MARGIN_V:
            continue
        v_raw = y / float(H - 1)
        d_px = D_OUTER + v_raw * (D_INNER - D_OUTER)

        # Seam peak at d_peak = -3.0 px (right where Blade's own alpha drops through 50%, so Blade + OuterGlow
        # forms a strictly monotonic, completely crest-free radial falloff from inner spine into outer mist!)
        d_peak = -3.0
        if d_px >= d_peak:
            # Gentle inward taper (+41.5 px -> 0, so it softly warms d=0..+30px without piling up on opaque Blade)
            t_in = max(0.0, min(1.0, (d_px - d_peak) / (41.5 - d_peak)))
            s_in = 0.5 * (1.0 + math.cos(math.pi * t_in))
            radial_a = s_in ** 1.85
            inward_mix = smoothstep(d_peak, 30.0, d_px)
        else:
            # Outward concave mist falloff (-3 px -> -65 px)
            t_out = max(0.0, min(1.0, (d_peak - d_px) / (d_peak - (-65.0))))
            s_cos = 0.5 * (1.0 + math.cos(math.pi * t_out))
            s_exp = math.exp(-((t_out / 0.38) ** 1.50)) * (1.0 - smoothstep(0.62, 1.0, t_out))
            radial_a = 0.36 * (s_cos ** 2.3) + 0.64 * s_exp
            inward_mix = 0.0

        if radial_a <= 1e-4:
            continue

        for x in range(MARGIN_U, W - MARGIN_U):
            up = u_prof[x]
            if up <= 1e-4:
                continue
            # Very subtle organic breath (+/- 7%) so it feels hand-painted, never noisy or stripy
            breath = 0.93 + 0.14 * u_fil[x]

            # Peak alpha kept at ~0.58 (NEVER clamped to 1.0 -> zero flat plateau!)
            alpha = 0.58 * radial_a * up * breath
            alpha = max(0.0, min(0.92, alpha))
            if alpha < (1.0 / 255.0):
                continue

            # Low-saturation warm champagne-gold matching Blade's 42-deg golden hue family (zero redness!):
            #   outer misty veil -> soft muted champagne (1.00, 0.89, 0.69)
            #   seam / inner     -> warm pale ivory-gold (1.00, 0.95, 0.83)
            w_core = min(1.0, radial_a * 0.75 + inward_mix * 0.35)
            r = 1.00
            g = 0.89 + (0.95 - 0.89) * w_core
            b = 0.69 + (0.83 - 0.69) * w_core

            ri = int(round(max(0.0, min(1.0, r)) * 255.0))
            gi = int(round(max(0.0, min(1.0, g)) * 255.0))
            bi = int(round(max(0.0, min(1.0, b)) * 255.0))
            ai = int(round(alpha * 255.0))
            if ai > 0:
                px[x, y] = (ri, gi, bi, ai)

    img.save(OUT_PNG)

    # Verify strict 16px zero-alpha border
    edge_max_a = 0
    for x in range(W):
        for y in list(range(16)) + list(range(H - 16, H)):
            edge_max_a = max(edge_max_a, px[x, y][3])
    for y in range(H):
        for x in list(range(16)) + list(range(W - 16, W)):
            edge_max_a = max(edge_max_a, px[x, y][3])

    prev = Image.new("RGBA", (W, 360), (14, 18, 28, 255))
    ppx = prev.load()
    for y in range(360):
        for x in range(W):
            if ((x // 32) + (y // 32)) % 2 == 0:
                ppx[x, y] = (20, 25, 38, 255)
    prev.alpha_composite(img, (0, 52))
    prev.save(OUT_PREVIEW)
    print(f"SAVED {OUT_PNG} ({W}x{H}) edge_16px_max_alpha={edge_max_a}")
    print(f"SAVED {OUT_PREVIEW}")


if __name__ == "__main__":
    main()
