"""Tileable cloud noise for the slash frost mist (NobleShore).

Spectral synthesis: random phases with a 1/f^beta amplitude give an fBm-like cloud that is
periodic in both axes by construction, so the material can pan and tile it freely.

Usage: python3.13 -I gen_mist_cloud.py <out.png>   (Blender's bundled Python has numpy)
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "VFXSprites"))
from black_to_alpha import write_png  # noqa: E402

N, BETA, SEED = 512, 1.9, 23

rng = np.random.default_rng(SEED)
fy = np.fft.fftfreq(N)[:, None]
fx = np.fft.fftfreq(N)[None, :]
f = np.sqrt(fx * fx + fy * fy)
f[0, 0] = 1.0
amp = 1.0 / f ** BETA
amp[0, 0] = 0.0
amp[f < 2.0 / N] = 0.0                       # drop the two lowest harmonics: no single big blob
spec = amp * np.exp(2j * np.pi * rng.random((N, N)))
img = np.real(np.fft.ifft2(spec))
img = (img - img.mean()) / img.std()
img = np.clip(0.5 + img * 0.22, 0.0, 1.0)    # mid-grey centred, soft contrast
img = img * img * (3 - 2 * img)
write_png(sys.argv[1], np.dstack([img, img, img, np.ones_like(img)]))
print("cloud", round(float(img.mean()), 3), round(float(img.min()), 3), round(float(img.max()), 3))
