"""Generate T_SlashOuterGlow.png (2048x256 RGBA) for the narrow outer-rim emissive strip mesh
SM_SlashOuterGlow_01..05.

UV0 layout on SM_SlashOuterGlow_01:
  - U in [0, 1]: runs from extended tail tip (0.0) -> crescent belly (0.55) -> extended head tip (1.0)
  - V in [0, 1]: runs across the narrow outer-rim strip (d_outer = -105 px -> V=0, golden rim spine d=0 -> V=0.5, d_inner = +105 px -> V=1.0)
  - Strictly enforces >= 16 px Alpha = 0 margin on ALL 4 borders so clamping never produces rectangular quad edges.
"""
import math
import os
from PIL import Image

OUT_DIR = "/Users/mengmeile/Downloads/lianxi/m/SourceAssets/SlashTextures"
OUT_PNG = os.path.join(OUT_DIR, "T_SlashOuterGlow.png")
OUT_PREVIEW = os.path.join(OUT_DIR, "T_SlashOuterGlow_Preview.png")

W, H = 2048, 256
MARGIN_U = 20
MARGIN_V = 18


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

    # Precompute U profile: smooth taper at tail (U=0) and head (U=1), stronger towards the leading front half (U ~ 0.45..0.88)
    u_prof = [0.0] * W
    u_fil_a = [0.0] * W
    u_fil_b = [0.0] * W
    freqs_a = [(3.0, 0.45, 0.4), (7.0, 0.32, 1.9), (15.0, 0.23, 3.7)]
    freqs_b = [(5.0, 0.48, 2.1), (11.0, 0.30, 0.8), (23.0, 0.22, 4.5)]

    for x in range(W):
        if x < MARGIN_U or x >= W - MARGIN_U:
            u_prof[x] = 0.0
            continue
        u = (x - MARGIN_U) / float(W - 1 - 2 * MARGIN_U)
        # Taper softly from tail (0.0 -> 0.26) and taper cleanly before the sharp blade tip (0.76 -> 0.95) so it hugs the sharp point!
        tail_in = smoothstep(0.02, 0.26, u)
        head_out = 1.0 - smoothstep(0.75, 0.95, u)
        # Slight energy swell in the main outer belly + leading arc (u in 0.30..0.78)
        belly_boost = 0.78 + 0.28 * smoothstep(0.18, 0.58, u) * (1.0 - 0.30 * smoothstep(0.74, 0.95, u))
        u_prof[x] = tail_in * head_out * belly_boost
        u_fil_a[x] = fbm1d(u, freqs_a)
        u_fil_b[x] = fbm1d(u, freqs_b)

    for y in range(H):
        if y < MARGIN_V or y >= H - MARGIN_V:
            continue
        # Normalized v in [0, 1] inside safe margin; center V=0.50 aligns with golden rim spine d=0
        v_raw = y / float(H - 1)
        border_v = smoothstep(MARGIN_V / float(H - 1), (MARGIN_V + 18) / float(H - 1), v_raw) * (
            1.0 - smoothstep(1.0 - (MARGIN_V + 18) / float(H - 1), 1.0 - MARGIN_V / float(H - 1), v_raw)
        )
        # Asymmetric cross-section: generous warm golden halo outward (v < 0.60), tighter falloff inward (v > 0.60) so cyan curls stay crisp
        dv = v_raw - 0.58
        sigma_core = 0.055
        sigma_mid = 0.135 if dv < 0.0 else 0.095
        sigma_halo = 0.235 if dv < 0.0 else 0.155

        core_v = math.exp(-(dv * dv) / (2.0 * sigma_core * sigma_core))
        mid_v = math.exp(-(dv * dv) / (2.0 * sigma_mid * sigma_mid))
        halo_v = math.exp(-(dv * dv) / (2.0 * sigma_halo * sigma_halo))
        # Crisp outer secondary golden filament slightly outside the main spine (v ~ 0.38)
        dv_sub = v_raw - 0.38
        sub_v = math.exp(-(dv_sub * dv_sub) / (2.0 * 0.038 * 0.038))

        for x in range(MARGIN_U, W - MARGIN_U):
            up = u_prof[x]
            if up <= 1e-4:
                continue
            fa = 0.86 + 0.28 * u_fil_a[x]
            fb = 0.74 + 0.50 * u_fil_b[x]

            core = min(1.0, core_v * fa)
            mid = min(1.0, mid_v * (0.92 + 0.16 * u_fil_a[x]))
            sub_rib = min(1.0, sub_v * fb * 0.78)

            # Non-premultiplied saturated RGB (so RGB * Alpha * EmissiveBoost in UE5 Additive hits true HDR Bloom!):
            #   outer halo -> fiery golden-amber (1.00, 0.46, 0.06)
            #   mid / rib  -> luminous pure gold (1.00, 0.78, 0.22)
            #   core       -> incandescent cream-white (1.00, 0.97, 0.86)
            w_mid = max(mid, sub_rib * 0.85)
            r = 1.00
            g = 0.46 + (0.78 - 0.46) * w_mid + (0.97 - 0.78) * core
            b = 0.06 + (0.22 - 0.06) * w_mid + (0.86 - 0.22) * core

            alpha = (0.52 * halo_v + 0.62 * mid + 0.45 * sub_rib + 0.85 * core) * up * border_v
            alpha = max(0.0, min(1.0, alpha))
            if alpha <= 1e-4:
                continue

            ri = int(round(max(0.0, min(1.0, r)) * 255.0))
            gi = int(round(max(0.0, min(1.0, g)) * 255.0))
            bi = int(round(max(0.0, min(1.0, b)) * 255.0))
            ai = int(round(alpha * 255.0))
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

    # Also build a clean dark-grid preview card (2048x360) so tutorial viewers can inspect the strip texture clearly
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
