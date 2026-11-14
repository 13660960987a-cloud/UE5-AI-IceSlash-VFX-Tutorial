"""Convert black-background AI sprites into RGBA VFX textures.

Alpha is taken from brightness (max channel) so a pure-black background
becomes fully transparent; colour is un-premultiplied by that alpha so the
sprite keeps its full hue when blended. Optional square/rect centre-crop
and resize to the spec size.

Usage (Blender's bundled Python has numpy; macOS `sips` does the resize):
  python3.13 -I black_to_alpha.py <src.png> <dst.png> <W> <H> [crop=square|rect|none]
"""
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np


def read_png(path):
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, idat, w = 8, b"", 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and ctype in (2, 6), f"unsupported PNG type {ctype}/{depth}"
            ch = 3 if ctype == 2 else 4
        elif tag == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    stride = w * ch
    out = np.zeros((h, stride), np.int32)
    prev = np.zeros(stride, np.int32)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = np.frombuffer(raw, np.uint8, stride, y * (stride + 1) + 1).astype(np.int32)
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 255
        else:
            cur = np.zeros(stride, np.int32)
            for x in range(stride):
                a = cur[x - ch] if x >= ch else 0
                b = prev[x]
                c = prev[x - ch] if x >= ch else 0
                if f == 1:
                    p = a
                elif f == 3:
                    p = (a + b) // 2
                else:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    p = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[x] = (line[x] + p) & 255
        out[y] = cur
        prev = cur
    return out.reshape(h, w, ch)[..., :3].astype(np.float64) / 255.0


def write_png(path, rgba):
    img = (np.clip(rgba, 0, 1) * 255 + 0.5).astype(np.uint8)
    h, w, _ = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(tag, body):
        c = struct.pack(">I", len(body)) + tag + body
        return c + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n"
                           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    src, dst, tw, th = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    crop = sys.argv[5] if len(sys.argv) > 5 else "rect"
    with tempfile.TemporaryDirectory() as tmp:
        # Normalise to an unfiltered-friendly PNG via sips, cropping to the target aspect.
        info = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", src],
                              capture_output=True, text=True).stdout.split()
        sw, sh = int(info[info.index("pixelWidth:") + 1]), int(info[info.index("pixelHeight:") + 1])
        if crop != "none":
            aspect = tw / th
            cw, ch = (min(sw, int(sh * aspect)), min(sh, int(sw / aspect)))
            mid = Path(tmp) / "c.png"
            subprocess.run(["sips", "-c", str(ch), str(cw), src, "--out", str(mid)], check=True, capture_output=True)
            src = str(mid)
        sized = Path(tmp) / "s.png"
        subprocess.run(["sips", "-z", str(th), str(tw), "-s", "format", "png", src, "--out", str(sized)],
                       check=True, capture_output=True)
        rgb = read_png(sized)
    # Brightness -> alpha with a small black floor so JPEG-ish noise vanishes.
    a = np.clip((rgb.max(axis=2) - 0.04) / 0.96, 0, 1)
    color = np.where(a[..., None] > 1e-3, np.clip(rgb / np.maximum(a[..., None], 1e-3), 0, 1), 0)
    write_png(dst, np.dstack([color, a]))
    print(f"wrote {dst} {tw}x{th} alpha-coverage={a.mean():.3f}")


if __name__ == "__main__":
    main()
