"""Modular kit extraction, component segmentation, and socket assembly."""
import math
import os

from core.runtime import manifest
from core.quality.pixels import read_rgb
from core.media.png import read_size, write_png
from core.runtime.config import ROOT
from core.spec.naming import hex_rgb

from core.media.geometry import snap_socket_joint, source_to_canvas_pivot
from .sprites import clean_perimeter


def extract_kit(src_asset, out_asset, box=None, joint=None, socket=None,
                pad_x=0, pad_y=0, trim_outside_elbow=None, key_color="#ffffff"):
    """Extract or pad a modular component from `src_asset` and register its `joint`/`socket`.

    - Crops `box=[x0, y0, x1, y1]` (or keeps full image when `box=None`),
    - Optionally trims duplicate sleeve/limb regions outside `trim_outside_elbow=[ex, ey, sx, sy, radius]`
      so a torso's upper arm terminates cleanly in a rounded elbow socket at `(ex, ey)`,
    - Adds `(pad_x, pad_y)` solid `key_color` margin so 360-degree rotation never clips,
    - Cleans the 10px perimeter ring (`edge_key_purity = 1.0`),
    - Translates `joint` and `socket` coordinates into the extracted PNG's coordinate space
      and records them in `manifest.json`.
    """
    row = manifest.verified("assets", src_asset)
    src_path = os.path.join(ROOT, row["path"] if row else f"assets/{src_asset}.png")
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"source asset not found: {src_path}")

    w, h = read_size(src_path)
    key_rgb = hex_rgb(key_color)
    key_bytes = bytes(key_rgb)
    src_buf = bytearray(read_rgb(src_path, w, h))

    if trim_outside_elbow is not None:
        ex, ey, sx, sy, rad = trim_outside_elbow
        ux, uy = sx - ex, sy - ey
        ulen = max(1.0, math.hypot(ux, uy))
        ux, uy = ux / ulen, uy / ulen
        for y in range(h):
            for x in range(int(round(sx)) - 40):
                dx, dy = x - ex, y - ey
                dist = math.hypot(dx, dy)
                proj = dx * ux + dy * uy
                perp = abs(dx * (-uy) + dy * ux)
                in_upper = (0 <= proj <= ulen + 20 and perp <= rad + 4)
                in_disc = (dist <= rad)
                if not (in_upper or in_disc):
                    idx = (y * w + x) * 3
                    src_buf[idx:idx + 3] = key_bytes

    x0, y0, x1, y1 = box if box is not None else [0, 0, w, h]
    x0, y0 = max(0, int(round(x0))), max(0, int(round(y0)))
    x1, y1 = min(w, int(round(x1))), min(h, int(round(y1)))
    cw, ch = max(2, x1 - x0), max(2, y1 - y0)

    px, py = max(0, int(round(pad_x))), max(0, int(round(pad_y)))
    out_w = (cw + px * 2) // 2 * 2
    out_h = (ch + py * 2) // 2 * 2
    out_buf = bytearray(key_bytes * (out_w * out_h))

    for y in range(ch):
        sy_i = y0 + y
        if sy_i >= h:
            break
        for x in range(cw):
            sx_i = x0 + x
            if sx_i >= w:
                break
            dx_i, dy_i = px + x, py + y
            if dx_i < out_w and dy_i < out_h:
                s_idx = (sy_i * w + sx_i) * 3
                d_idx = (dy_i * out_w + dx_i) * 3
                out_buf[d_idx:d_idx + 3] = src_buf[s_idx:s_idx + 3]

    clean_perimeter(out_buf, out_w, out_h, key_rgb)
    rel = f"assets/{out_asset}.png"
    write_png(os.path.join(ROOT, rel), out_w, out_h, bytes(out_buf))

    meta = {"source": "rig-kit", "kit_source": src_asset}
    out_joint = None
    out_socket = None
    if joint is not None:
        out_joint = [int(round(joint[0] - x0 + px)), int(round(joint[1] - y0 + py))]
        meta["joint"] = out_joint
    if socket is not None:
        out_socket = [int(round(socket[0] - x0 + px)), int(round(socket[1] - y0 + py))]
        meta["socket"] = out_socket

    reg = manifest.register("assets", out_asset, rel, **meta)
    return {
        "asset": out_asset,
        "path": rel,
        "size": [out_w, out_h],
        "joint": out_joint,
        "socket": out_socket,
        "sha256": reg["sha256"][:12],
    }


def unpack_kit(sheet_asset, out_prefix, key_color="#ffffff", min_area=300, pad=16, tol=20,
               sort_by="area", labels=None):
    """Automatically detect, slice, pad, and register all modular components from a kit sheet.

    Given a single sprite/runner sheet containing disconnected components on a solid key_color:
    1. Reads `sheet_asset` from assets/ (or verified manifest).
    2. Runs connected-component analysis (BFS) to segment disconnected non-background islands.
    3. Filters out islands smaller than `min_area` pixels.
    4. Sorts islands:
       - if sort_by == 'area': descending by area (largest = main body/torso/chassis, parts 2..N = limbs/weapons).
       - if sort_by == 'position': top-to-bottom, left-to-right.
    5. For each island:
       - Computes its bounding box [min_x, min_y, max_x, max_y] and centroid [cx, cy].
       - Crops the island with `pad` padding around the bbox, rounding to even dimensions.
       - Isolates only pixels from this island (keying background & other islands to pure `key_color`).
       - Cleans outer 10px perimeter ring (`edge_key_purity = 1.0`).
       - Writes PNG to `assets/{out_prefix}-{label}.png` (where label is from `labels` or `part-1`, `part-2`...).
       - Registers part in `manifest.json` with source `unpack-kit`, `bbox`, `center`, `size`.
    6. Generates and returns a ready-to-paste Remotion layer JSON specification snippet so the
       author/agent only has to configure parent-child sockets without touching manual coordinates.
    """
    row = manifest.verified("assets", sheet_asset)
    src_path = os.path.join(ROOT, row["path"] if row else f"assets/{sheet_asset}.png")
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"kit sheet asset not found: {src_path}")

    w, h = read_size(src_path)
    key_rgb = hex_rgb(key_color)
    kr, kg, kb = key_rgb
    key_bytes = bytes(key_rgb)
    src_buf = bytearray(read_rgb(src_path, w, h))

    mask = bytearray(w * h)
    for i in range(w * h):
        idx = i * 3
        if abs(src_buf[idx] - kr) > tol or abs(src_buf[idx + 1] - kg) > tol or abs(src_buf[idx + 2] - kb) > tol:
            mask[i] = 1

    visited = bytearray(w * h)
    islands = []
    for y in range(h):
        row_off = y * w
        for x in range(w):
            idx = row_off + x
            if mask[idx] and not visited[idx]:
                q = [idx]
                visited[idx] = 1
                min_x, max_x = x, x
                min_y, max_y = y, y
                sum_x, sum_y = 0, 0
                head = 0
                while head < len(q):
                    curr = q[head]
                    head += 1
                    cy = curr // w
                    cx = curr % w
                    sum_x += cx
                    sum_y += cy
                    if cx < min_x: min_x = cx
                    if cx > max_x: max_x = cx
                    if cy < min_y: min_y = cy
                    if cy > max_y: max_y = cy

                    if cx > 0:
                        n = curr - 1
                        if mask[n] and not visited[n]: visited[n] = 1; q.append(n)
                    if cx < w - 1:
                        n = curr + 1
                        if mask[n] and not visited[n]: visited[n] = 1; q.append(n)
                    if cy > 0:
                        n = curr - w
                        if mask[n] and not visited[n]: visited[n] = 1; q.append(n)
                    if cy < h - 1:
                        n = curr + w
                        if mask[n] and not visited[n]: visited[n] = 1; q.append(n)

                if len(q) >= min_area:
                    islands.append({
                        "pixels": set(q),
                        "area": len(q),
                        "bbox": [min_x, min_y, max_x, max_y],
                        "center": [sum_x / len(q), sum_y / len(q)],
                    })

    if not islands:
        raise ValueError(f"no valid components found in {sheet_asset} (min_area={min_area})")

    if sort_by == "area":
        islands.sort(key=lambda isl: isl["area"], reverse=True)
    elif sort_by == "position":
        islands.sort(key=lambda isl: (isl["bbox"][1] // 50, isl["bbox"][0]))
    else:
        raise ValueError(f"unknown sort_by: {sort_by!r}")

    extracted = []
    layer_templates = []
    for idx_isl, isl in enumerate(islands):
        min_x, min_y, max_x, max_y = isl["bbox"]
        cx_c, cy_c = isl["center"]

        if labels and idx_isl < len(labels):
            part_suffix = labels[idx_isl]
        else:
            part_suffix = f"part-{idx_isl + 1}"
        part_asset = f"{out_prefix}-{part_suffix}"

        x0 = max(0, min_x - pad)
        y0 = max(0, min_y - pad)
        x1 = min(w, max_x + 1 + pad)
        y1 = min(h, max_y + 1 + pad)
        cw = max(2, (x1 - x0) // 2 * 2)
        ch = max(2, (y1 - y0) // 2 * 2)

        out_buf = bytearray(key_bytes * (cw * ch))
        isl_pixels = isl["pixels"]

        ext_visited = bytearray(cw * ch)
        ext_q = []
        for bx in range(cw):
            for by in (0, ch - 1):
                s_idx = (y0 + by) * w + (x0 + bx)
                if s_idx not in isl_pixels:
                    b_idx = by * cw + bx
                    ext_visited[b_idx] = 1
                    ext_q.append(b_idx)
        for by in range(ch):
            for bx in (0, cw - 1):
                s_idx = (y0 + by) * w + (x0 + bx)
                if s_idx not in isl_pixels:
                    b_idx = by * cw + bx
                    if not ext_visited[b_idx]:
                        ext_visited[b_idx] = 1
                        ext_q.append(b_idx)

        head = 0
        while head < len(ext_q):
            curr = ext_q[head]
            head += 1
            ly, lx = curr // cw, curr % cw
            if lx > 0:
                n = curr - 1
                s_idx = (y0 + ly) * w + (x0 + lx - 1)
                if not ext_visited[n] and s_idx not in isl_pixels:
                    ext_visited[n] = 1
                    ext_q.append(n)
            if lx < cw - 1:
                n = curr + 1
                s_idx = (y0 + ly) * w + (x0 + lx + 1)
                if not ext_visited[n] and s_idx not in isl_pixels:
                    ext_visited[n] = 1
                    ext_q.append(n)
            if ly > 0:
                n = curr - cw
                s_idx = (y0 + ly - 1) * w + (x0 + lx)
                if not ext_visited[n] and s_idx not in isl_pixels:
                    ext_visited[n] = 1
                    ext_q.append(n)
            if ly < ch - 1:
                n = curr + cw
                s_idx = (y0 + ly + 1) * w + (x0 + lx)
                if not ext_visited[n] and s_idx not in isl_pixels:
                    ext_visited[n] = 1
                    ext_q.append(n)

        for ly in range(ch):
            sy_i = y0 + ly
            if sy_i >= h:
                break
            for lx in range(cw):
                sx_i = x0 + lx
                if sx_i >= w:
                    break
                loc_idx = ly * cw + lx
                if not ext_visited[loc_idx]:
                    s_idx = (sy_i * w + sx_i) * 3
                    d_idx = loc_idx * 3
                    out_buf[d_idx:d_idx + 3] = src_buf[s_idx:s_idx + 3]

        clean_perimeter(out_buf, cw, ch, key_rgb, ring=10)
        rel = f"assets/{part_asset}.png"
        write_png(os.path.join(ROOT, rel), cw, ch, bytes(out_buf))

        part_center = [int(round(cx_c - x0)), int(round(cy_c - y0))]
        reg = manifest.register(
            "assets", part_asset, rel,
            source="unpack-kit",
            kit_source=sheet_asset,
            part_index=idx_isl + 1,
            bbox=isl["bbox"],
            size=[cw, ch],
            center=part_center,
            area=isl["area"],
        )
        extracted.append({
            "asset": part_asset,
            "path": rel,
            "size": [cw, ch],
            "center": part_center,
            "bbox": isl["bbox"],
            "area": isl["area"],
            "sha256": reg["sha256"][:12],
        })

        if idx_isl == 0:
            layer_templates.append({
                "id": part_suffix,
                "type": "ai",
                "asset": part_asset,
                "rect": [260, 290, cw, ch],
                "z": 10,
                "_comment": "Root component (torso/chassis). Adjust rect as needed.",
            })
        else:
            layer_templates.append({
                "id": part_suffix,
                "type": "ai",
                "asset": part_asset,
                "parent": layer_templates[0]["id"],
                "kit": {
                    "type": "limb",
                    "joint": part_center,
                    "socket": [100, 100],
                },
                "z": 10 + idx_isl,
                "rot": [0, [
                    {"frame": 0, "val": 0},
                    {"frame": 60, "val": 15},
                ]],
                "_comment": "Articulated child. Calibrate kit.joint and parent socket.",
            })

    return {
        "sheet_asset": sheet_asset,
        "parts_count": len(extracted),
        "parts": extracted,
        "spec_layers_snippet": layer_templates,
    }
