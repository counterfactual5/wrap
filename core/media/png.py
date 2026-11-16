"""Minimal PNG helpers (stdlib only): write RGB8/RGBA8, read IHDR size."""
import os
import struct
import zlib


def _chunks(get_row, w, h, path, color_type):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + get_row(y) for y in range(h))
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 6)))
        f.write(chunk(b"IEND", b""))


def write_png(path, w, h, rgb):
    assert len(rgb) == w * h * 3
    _chunks(lambda y: rgb[y * w * 3:(y + 1) * w * 3], w, h, path, 2)


def write_png_rgba(path, w, h, rgba):
    """RGBA8 PNG (color type 6) — per-pixel alpha for layered compositing.

    The renderer's anim wrapper gives every animated layer its own stacking
    context, which traps mixBlendMode; per-pixel alpha is the portable way
    to composite a derived cutout (see SKILL.md pitfall 16).
    """
    assert len(rgba) == w * h * 4
    _chunks(lambda y: rgba[y * w * 4:(y + 1) * w * 4], w, h, path, 6)


def read_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    return struct.unpack(">II", head[16:24])
