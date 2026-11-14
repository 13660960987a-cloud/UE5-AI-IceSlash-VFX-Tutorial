"""Generate authentic stylized target-hit VFX textures matching the reference hit effect:
  1. T_VFX_HitCutBeam_A.png (512 x 2048 RGBA, vertical V-axis for Niagara VelocityAligned + FaceCamera):
     - Ultra-crisp, anti-aliased, razor-thin piercing slash-cut beam (imported uncompressed, never_stream=True, sRGB=False for LinearColor additive sampler):
       * Front/right side (y = 0.02 -> 0.37): needle-sharp radiant golden-yellow -> warm white-gold
       * Impact core (y = 0.35 -> 0.45): tight incandescent pure-white flare right on the target
       * Tail/left side (y = 0.43 -> 0.98): sleek electric ice-cyan -> deep sapphire-cyan needle tail with a razor-thin white central laser spine
     - Strict >= 16 px Alpha = 0 margin on all 4 borders.
  2. T_VFX_HitCutBeam_Preview.png (2048 x 340 horizontal dark-grid preview card for tutorial docs/video).
  3. T_VFX_IceShard_A.png (512 x 512 RGBA): crisp cel-shaded faceted cyan-blue polygonal ice crystal shard
     with bright ice-white facet edge highlight (strict >= 16 px Alpha = 0 margin).
"""
import os
import numpy as np
from PIL import Image

OUT_DIR = "/Users/mengmeile/Downloads/lianxi/m/SourceAssets/VFXSprites"
os.makedirs(OUT_DIR, exist_ok=True)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def build_cut_beam():
    W, H = 512, 2048
    # x in [-1, 1] across beam width; y in [0, 1] along beam length (0 = right/front gold tip, 1 = left/tail cyan tip)
    x = ((np.arange(W, dtype=np.float64) + 0.5) / W) * 2.0 - 1.0
    y = (np.arange(H, dtype=np.float64) + 0.5) / H
    X, Y = np.meshgrid(x, y)

    # Strict >16 px zero-alpha border envelope
    mu = 24.0 / W * 2.0
    mv = 24.0 / H
    border_x = smoothstep(1.0 - mu, 1.0 - mu - 0.10, np.abs(X))
    border_y = smoothstep(mv, mv + 0.03, Y) * (1.0 - smoothstep(1.0 - mv - 0.03, 1.0 - mv, Y))

    # Longitudinal needle-sharp spindle peaking at y_core = 0.38 (38% gold right tip, 62% long cyan left slash line)
    y_core = 0.38
    env_gold = smoothstep(0.02, y_core, Y) ** 1.25
    env_cyan = (1.0 - smoothstep(y_core, 0.98, Y)) ** 1.15
    env_len = np.where(Y <= y_core, env_gold, env_cyan) * border_y

    # Razor-thin laser spindle width: ultra-tight needle ends, subtle hot swell at y_core
    spindle_w = 0.018 + 0.115 * (env_len ** 0.80) + 0.055 * np.exp(-((Y - y_core) / 0.095) ** 2)

    # Three concentric smooth Gaussian layers (zero abrupt step edges!)
    laser_core = np.exp(-((X / np.maximum(spindle_w * 0.28, 0.007)) ** 2)) * (env_len ** 0.72)
    color_sheath = np.exp(-((X / np.maximum(spindle_w * 0.82, 0.015)) ** 2)) * env_len
    outer_bloom = np.exp(-((X / np.maximum(spindle_w * 2.10, 0.038)) ** 2)) * (env_len ** 1.15) * 0.34

    # Compact white impact flare at y_core
    impact_flare = np.exp(-((Y - y_core) / 0.075) ** 2) * np.exp(-((X / 0.22) ** 2)) * 0.52

    # Delicate ultra-smooth parallel cyan slit line along the cyan side only (smooth C2 Gaussian taper)
    slit_env = smoothstep(0.40, 0.54, Y) * (1.0 - smoothstep(0.74, 0.92, Y))
    slit_line = np.exp(-(((X - 0.22) / 0.018) ** 2)) * slit_env * 0.42

    # Linear-space vivid colors (since M_VFX_Sprite_Additive uses SAMPLERTYPE_LinearColor with sRGB=False)
    w_gold = 1.0 - smoothstep(0.25, 0.39, Y)
    w_cyan = smoothstep(0.37, 0.52, Y)
    w_white_zone = np.clip(np.exp(-((Y - y_core) / 0.075) ** 2), 0.0, 1.0)

    gold_lin = np.array([1.00, 0.62, 0.04])       # rich golden-amber in linear space -> warm bright gold on screen
    cyan_mid_lin = np.array([0.03, 0.72, 1.00])   # electric ice-cyan in linear space
    cyan_deep_lin = np.array([0.01, 0.18, 0.82])  # deep sapphire rim in linear space
    white_lin = np.array([1.00, 1.00, 1.00])

    edge_t = np.clip(1.0 - (color_sheath / np.maximum(color_sheath + outer_bloom, 1e-4)), 0.0, 1.0)
    cyan_col = cyan_mid_lin[None, None, :] * (1.0 - 0.68 * edge_t[..., None]) + cyan_deep_lin[None, None, :] * (0.68 * edge_t[..., None])

    norm_w = np.maximum(w_gold + w_cyan, 1e-4)[..., None]
    base_lin = (gold_lin[None, None, :] * w_gold[..., None] + cyan_col * w_cyan[..., None]) / norm_w

    white_pull = np.clip(laser_core * 0.94 + impact_flare * 0.95 + w_white_zone * 0.58 + slit_line * 0.35, 0.0, 1.0)[..., None]
    rgb_lin = np.clip(base_lin * (1.0 - white_pull) + white_lin[None, None, :] * white_pull, 0.0, 1.0)

    alpha = np.clip((laser_core + color_sheath * 0.82 + outer_bloom + impact_flare + slit_line) * border_x * border_y, 0.0, 1.0)
    alpha[:16, :] = 0.0
    alpha[-16:, :] = 0.0
    alpha[:, :16] = 0.0
    alpha[:, -16:] = 0.0

    rgba_lin = np.dstack([rgb_lin, alpha])
    u8_lin = (rgba_lin * 255.0 + 0.5).astype(np.uint8)
    out_png = os.path.join(OUT_DIR, "T_VFX_HitCutBeam_A.png")
    Image.fromarray(u8_lin, mode="RGBA").save(out_png)

    # Display-gamma sRGB preview card (left = cyan tail, center = white impact, right = gold tip)
    rgb_srgb = np.clip(rgb_lin ** (1.0 / 2.2), 0.0, 1.0)
    u8_srgb = (np.dstack([rgb_srgb, alpha]) * 255.0 + 0.5).astype(np.uint8)
    horiz = Image.fromarray(u8_srgb, mode="RGBA").transpose(Image.Transpose.ROTATE_270).resize((2048, 256), Image.Resampling.LANCZOS)
    prev = Image.new("RGBA", (2048, 340), (12, 16, 26, 255))
    ppx = prev.load()
    for py in range(340):
        for px in range(2048):
            if ((px // 32) + (py // 32)) % 2 == 0:
                ppx[px, py] = (18, 24, 38, 255)
    prev.alpha_composite(horiz, (0, 42))
    prev_png = os.path.join(OUT_DIR, "T_VFX_HitCutBeam_Preview.png")
    prev.save(prev_png)
    print("SAVED", out_png, "max_border_alpha=", int(max(u8_lin[:16,:,3].max(), u8_lin[-16:,:,3].max(), u8_lin[:,:16,3].max(), u8_lin[:,-16:,3].max())))
    print("SAVED", prev_png)


def build_ice_shard():
    N = 512
    c = ((np.arange(N, dtype=np.float64) + 0.5) / N) * 2.0 - 1.0
    X, Y = np.meshgrid(c, c)

    # Sharp 5-sided cel-shaded polygonal anime ice fragment
    planes = [
        (0.88, 0.47, 0.40),
        (-0.84, 0.54, 0.38),
        (-0.62, -0.78, 0.50),
        (0.45, -0.89, 0.54),
        (0.96, -0.26, 0.34),
    ]
    signed_d = np.full_like(X, -10.0)
    for nx, ny, dist in planes:
        signed_d = np.maximum(signed_d, (X * nx + Y * ny) - dist)

    inside = smoothstep(0.016, -0.016, signed_d)
    soft_glow = np.exp(-np.maximum(signed_d, 0.0) / 0.05) * 0.25

    facet_split = smoothstep(-0.018, 0.018, X * 0.78 - Y * 0.32 + 0.04)
    rim_hi = smoothstep(-0.085, -0.005, signed_d) * inside
    top_spec = smoothstep(0.35, -0.45, Y) * inside

    light_cyan = np.array([0.62, 0.96, 1.00])
    mid_cyan = np.array([0.20, 0.80, 0.98])
    deep_cyan = np.array([0.10, 0.54, 0.90])
    white_rgb = np.array([0.97, 0.99, 1.00])

    body_rgb = light_cyan[None, None, :] * facet_split[..., None] + deep_cyan[None, None, :] * (1.0 - facet_split[..., None])
    body_rgb = body_rgb * (0.76 + 0.24 * top_spec[..., None]) + mid_cyan[None, None, :] * 0.10
    rim_w = np.clip(rim_hi * 0.80 + smoothstep(0.07, -0.015, np.abs(X * 0.78 - Y * 0.32 + 0.04)) * inside * 0.55, 0.0, 1.0)[..., None]
    rgb = np.clip(body_rgb * (1.0 - rim_w) + white_rgb[None, None, :] * rim_w, 0.0, 1.0)

    border = smoothstep(1.0 - 20.0 / N * 2.0, 1.0 - 44.0 / N * 2.0, np.maximum(np.abs(X), np.abs(Y)))
    alpha = np.clip((inside * 0.94 + soft_glow) * border, 0.0, 1.0)
    alpha[:16, :] = 0.0
    alpha[-16:, :] = 0.0
    alpha[:, :16] = 0.0
    alpha[:, -16:] = 0.0

    u8 = (np.dstack([rgb, alpha]) * 255.0 + 0.5).astype(np.uint8)
    out_png = os.path.join(OUT_DIR, "T_VFX_IceShard_A.png")
    Image.fromarray(u8, mode="RGBA").save(out_png)
    print("SAVED", out_png, "max_border_alpha=", int(max(u8[:16,:,3].max(), u8[-16:,:,3].max(), u8[:,:16,3].max(), u8[:,-16:,3].max())))


if __name__ == "__main__":
    build_cut_beam()
    build_ice_shard()
