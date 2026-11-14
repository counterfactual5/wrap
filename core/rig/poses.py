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


def derive_pose_preset(src_asset, out_asset, preset="shatter", key_color="#ffffff"):
    """Deterministically derive a combat/transformation pose (`disguise`, `shatter`, `recoil`)
    from `src_asset` using inverse mapping (zero Moiré) and register it in `manifest.json`."""
    if preset not in ("disguise", "shatter", "recoil"):
        raise ValueError(f"unknown preset {preset!r}; choose from ('disguise', 'shatter', 'recoil')")
    row = manifest.verified("assets", src_asset)
    src_path = os.path.join(ROOT, row["path"] if row else f"assets/{src_asset}.png")
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"source asset not found: {src_path}")

    w, h = read_size(src_path)
    key_rgb = hex_rgb(key_color)
    kr, kg, kb = key_rgb
    key_bytes = bytes(key_rgb)
    src_buf = bytearray(read_rgb(src_path, w, h))
    clean_perimeter(src_buf, w, h, key_rgb)

    out_buf = bytearray(key_bytes * (w * h))

    if preset == "disguise":
        for i in range(0, len(src_buf), 3):
            r, g, b = src_buf[i], src_buf[i + 1], src_buf[i + 2]
            if (r, g, b) == (kr, kg, kb):
                continue
            nr = min(255, int(r * 1.04 + 18))
            ng = max(0, int(g * 0.80 - 14))
            nb = max(0, int(b * 0.62 - 28))
            out_buf[i:i + 3] = bytes((nr, ng, nb))
    elif preset == "recoil":
        # Inverse-mapped backward torso tilt (+14 deg around lower center)
        cx, cy = w * 0.52, h * 0.68
        ang = 0.24
        ca, sa = math.cos(ang), math.sin(ang)
        for ny in range(12, h - 12):
            for nx in range(12, w - 12):
                rx, ry = nx - 28 - cx, ny - 10 - cy
                sx = int(round(cx + rx * ca + ry * sa))
                sy = int(round(cy - rx * sa + ry * ca))
                if 0 <= sx < w and 0 <= sy < h:
                    s_idx = (sy * w + sx) * 3
                    rgb = src_buf[s_idx:s_idx + 3]
                    if rgb != key_bytes:
                        out_buf[(ny * w + nx) * 3:(ny * w + nx) * 3 + 3] = rgb
    elif preset == "shatter":
        # Inverse-mapped 4-segment puppet fracture (head, torso, back limb, lower skirt)
        y_neck = int(h * 0.295)
        y_waist = int(h * 0.488)
        y_hem = int(h * 0.616)
        x_back = int(w * 0.647)

        def put_seg(cond, cx, cy, ang, dx, dy):
            ca, sa = math.cos(ang), math.sin(ang)
            for ny in range(12, h - 12):
                for nx in range(12, w - 12):
                    rx, ry = nx - dx - cx, ny - dy - cy
                    sx = int(round(cx + rx * ca + ry * sa))
                    sy = int(round(cy - rx * sa + ry * ca))
                    if 0 <= sx < w and 0 <= sy < h and cond(sx, sy):
                        s_idx = (sy * w + sx) * 3
                        r, g, b = src_buf[s_idx], src_buf[s_idx + 1], src_buf[s_idx + 2]
                        if (r, g, b) == (kr, kg, kb):
                            continue
                        luma = int(0.299 * r + 0.587 * g + 0.114 * b)
                        br = min(255, int(luma * 1.05 + 10))
                        bg_c = min(255, int(luma * 1.02 + 6))
                        bb = max(0, int(luma * 0.88 - 10))
                        d_idx = (ny * w + nx) * 3
                        out_buf[d_idx:d_idx + 3] = bytes((br, bg_c, bb))

        put_seg(lambda sx, sy: sy >= y_waist and not (sy < y_hem and sx >= x_back),
                w * 0.53, h * 0.65, -0.16, 22, 34)
        put_seg(lambda sx, sy: y_neck <= sy < y_waist and sx < x_back,
                w * 0.55, h * 0.39, 0.28, 42, 10)
        put_seg(lambda sx, sy: y_neck <= sy < y_hem and sx >= x_back,
                w * 0.76, h * 0.45, 0.42, 62, 46)
        put_seg(lambda sx, sy: sy < y_neck,
                w * 0.55, h * 0.22, 0.45, 68, -28)

    clean_perimeter(out_buf, w, h, key_rgb)
    rel = f"assets/{out_asset}.png"
    write_png(os.path.join(ROOT, rel), w, h, bytes(out_buf))
    reg = manifest.register("assets", out_asset, rel, source=f"rig-preset-{preset}",
                            base_asset=src_asset)
    return {
        "asset": out_asset,
        "path": rel,
        "preset": preset,
        "sha256": reg["sha256"][:12],
    }
