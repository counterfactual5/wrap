"""Sprite-sheet slicing and deterministic pose derivation."""
import math
import os

from core.runtime import manifest
from core.quality.pixels import read_rgb
from core.media.png import read_size, write_png
from core.runtime.config import ROOT
from core.spec.naming import hex_rgb

from .sprites import clean_perimeter


def derive_poses_from_sheet(sheet_asset, out_prefix, cols=3, key_color="#ffffff"):
    """Slice a horizontal `cols`-panel sprite sheet into individual registered pose assets."""
    if cols < 2:
        raise ValueError("cols must be >= 2")
    row = manifest.verified("assets", sheet_asset)
    src_path = os.path.join(ROOT, row["path"] if row else f"assets/{sheet_asset}.png")
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"sheet asset not found: {src_path}")

    w, h = read_size(src_path)
    key_rgb = hex_rgb(key_color)
    key_bytes = bytes(key_rgb)
    src_buf = bytearray(read_rgb(src_path, w, h))

    cell_w = (w // cols) // 2 * 2
    cell_h = h // 2 * 2
    outputs = []
    for c in range(cols):
        x_start = c * (w // cols)
        panel = bytearray(key_bytes * (cell_w * cell_h))
        for y in range(cell_h):
            for x in range(cell_w):
                sx = min(w - 1, x_start + x)
                s_idx = (y * w + sx) * 3
                d_idx = (y * cell_w + x) * 3
                panel[d_idx:d_idx + 3] = src_buf[s_idx:s_idx + 3]
        clean_perimeter(panel, cell_w, cell_h, key_rgb)
        pose_name = f"{out_prefix}-pose-{c + 1}"
        rel = f"assets/{pose_name}.png"
        write_png(os.path.join(ROOT, rel), cell_w, cell_h, bytes(panel))
        reg = manifest.register("assets", pose_name, rel, source="rig-sheet",
                                sheet_source=sheet_asset, panel=c + 1)
        outputs.append({"asset": pose_name, "path": rel, "sha256": reg["sha256"][:12]})
    return outputs
