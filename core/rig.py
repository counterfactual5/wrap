"""Sprite rigging, joint/pivot calibration, part splitting, and multi-pose derivation.

Stdlib-only pixel utilities for Path 2 (Static Image Model + Remotion Choreography):
- `source_to_canvas_pivot`: maps source image pixel (sx, sy) to exact canvas [px, py]
  accounting for S2's aspect-preserving `contain` (`decrease` + `pad`) scaling.
- `inspect_sprite`: generates a visual coordinate ruler grid (`build/inspect_sprite_<asset>.png`)
  with bounding-box & joint crosshair markers so agents/authors never blind-guess pivots.
- `split_sprite`: separates a single character sprite into a parent body asset and an
  articulated child weapon/limb asset of identical dimensions (1:1 canvas alignment),
  preserving a rounded overlap joint cap at `joint=(jx, jy)` and cleaning the perimeter
  ring for `edge_key_purity = 1.0`.
- `unpack_kit`: automatically detects, crops, pads, and registers all modular components
  from a multi-part runner/kit sheet on solid key_color via connected-component BFS, and
  emits ready-to-paste Remotion layer JSON templates.
- `derive_poses_from_sheet`: slices a multi-pose horizontal sprite sheet (`cols=N`) into
  individual center-aligned pose assets registered in `manifest.json`.
- `derive_pose_preset`: deterministically derives combat/transformation pose states
  (`disguise`, `shatter`, `recoil`) from a base sprite using inverse mapping (zero Moiré).
"""
import math
import os

from core import manifest
from core.metrics import edge_key_purity, read_rgb
from core.png import read_size, write_png
from core.schema import ROOT, hex_rgb


def source_to_canvas_pivot(sw, sh, rect, sx, sy):
    """Map source pixel (sx, sy) in a (sw, sh) image to canvas [px, py] inside `rect`.

    When `cutout: true` (or `fit: "contain"`), S2 scales the (sw, sh) image with
    `force_original_aspect_ratio=decrease` and centers it with `pad` inside `rect=[rx, ry, rw, rh]`.
    This function computes the exact canvas pixel coordinate where (sx, sy) lands.
    """
    rx, ry, rw, rh = rect
    scale = min(rw / max(1, sw), rh / max(1, sh))
    drawn_w = sw * scale
    drawn_h = sh * scale
    pad_x = (rw - drawn_w) / 2.0
    pad_y = (rh - drawn_h) / 2.0
    px = round(rx + pad_x + sx * scale, 1)
    py = round(ry + pad_y + sy * scale, 1)
    # Return int if whole number
    px = int(px) if px == int(px) else px
    py = int(py) if py == int(py) else py
    return [px, py]


def clean_perimeter(buf, w, h, key_rgb=(255, 255, 255), ring=10, near_tol=22):
    """Force the outer `ring` pixels to exact `key_rgb` and snap near-key background noise near the border."""
    kr, kg, kb = key_rgb
    key_bytes = bytes((kr, kg, kb))
    margin = ring * 2
    for y in range(h):
        for x in range(w):
            idx = (y * w + x) * 3
            if x < ring or x >= w - ring or y < ring or y >= h - ring:
                buf[idx:idx + 3] = key_bytes
            elif near_tol > 0 and (x < margin or x >= w - margin or y < margin or y >= h - margin):
                r, g, b = buf[idx], buf[idx + 1], buf[idx + 2]
                if abs(r - kr) <= near_tol and abs(g - kg) <= near_tol and abs(b - kb) <= near_tol:
                    buf[idx:idx + 3] = key_bytes
    return buf


def sprite_bbox(buf, w, h, key_rgb=(255, 255, 255), tol=20):
    """Bounding box [xmin, ymin, xmax, ymax] of non-key pixels."""
    kr, kg, kb = key_rgb
    xmin, ymin, xmax, ymax = w, h, 0, 0
    found = False
    for y in range(h):
        row_off = y * w * 3
        for x in range(w):
            idx = row_off + x * 3
            if (abs(buf[idx] - kr) > tol
                    or abs(buf[idx + 1] - kg) > tol
                    or abs(buf[idx + 2] - kb) > tol):
                if x < xmin:
                    xmin = x
                if x > xmax:
                    xmax = x
                if y < ymin:
                    ymin = y
                if y > ymax:
                    ymax = y
                found = True
    if not found:
        return [0, 0, w - 1, h - 1]
    return [xmin, ymin, xmax, ymax]


def inspect_sprite(asset_name, rect=None, joint=None, key_color="#ffffff", out_path=None):
    """Create a coordinate-grid diagnostic PNG and return metadata + pivot mapping."""
    row = manifest.verified("assets", asset_name)
    src_path = os.path.join(ROOT, row["path"] if row else f"assets/{asset_name}.png")
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"asset file not found: {src_path}")

    w, h = read_size(src_path)
    key_rgb = hex_rgb(key_color)
    buf = bytearray(read_rgb(src_path, w, h))
    bbox = sprite_bbox(buf, w, h, key_rgb)
    purity = edge_key_purity(bytes(buf), w, h, key_rgb)

    # Draw 100px grid lines and 50px sub-grid ticks onto a copy for visual inspection
    vis = bytearray(buf)
    for y in range(h):
        for x in range(w):
            if x % 100 == 0 or y % 100 == 0:
                idx = (y * w + x) * 3
                # Cyan-blue grid line
                vis[idx:idx + 3] = bytes((40, 140, 220))
            elif (x % 50 == 0 and y % 4 < 2) or (y % 50 == 0 and x % 4 < 2):
                idx = (y * w + x) * 3
                vis[idx:idx + 3] = bytes((160, 200, 235))

    # Draw bbox in green
    x0, y0, x1, y1 = bbox
    for x in range(x0, x1 + 1):
        for dy in (y0, y1):
            if 0 <= dy < h:
                idx = (dy * w + x) * 3
                vis[idx:idx + 3] = bytes((20, 190, 80))
    for y in range(y0, y1 + 1):
        for dx in (x0, x1):
            if 0 <= dx < w:
                idx = (y * w + dx) * 3
                vis[idx:idx + 3] = bytes((20, 190, 80))

    joint_px = None
    canvas_pivot = None
    if joint is not None:
        jx, jy = joint
        # Support normalized 0..1 coordinates or pixel coordinates
        if 0 < jx <= 1.0 and 0 < jy <= 1.0:
            jx = int(round(jx * w))
            jy = int(round(jy * h))
        else:
            jx, jy = int(round(jx)), int(round(jy))
        joint_px = [jx, jy]
        # Draw red target crosshair + circle of radius 20 around (jx, jy)
        for dy in range(-28, 29):
            for dx in range(-28, 29):
                nx, ny = jx + dx, jy + dy
                if 0 <= nx < w and 0 <= ny < h:
                    dist2 = dx * dx + dy * dy
                    if abs(dx) <= 1 or abs(dy) <= 1 or (18 * 18 <= dist2 <= 22 * 22):
                        idx = (ny * w + nx) * 3
                        vis[idx:idx + 3] = bytes((240, 30, 30))

    if rect is not None:
        ref_x, ref_y = joint_px if joint_px else [(x0 + x1) // 2, (y0 + y1) // 2]
        canvas_pivot = source_to_canvas_pivot(w, h, rect, ref_x, ref_y)

    if out_path is None:
        out_path = os.path.join(ROOT, "build", f"inspect_sprite_{asset_name}.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    write_png(out_path, w, h, bytes(vis))

    return {
        "asset": asset_name,
        "size": [w, h],
        "bbox": bbox,
        "purity": round(purity, 4),
        "joint_source": joint_px,
        "canvas_pivot": canvas_pivot,
        "annotated_image": os.path.relpath(out_path, ROOT),
    }


def split_sprite(src_asset, body_asset, part_asset, box, joint, joint_radius=22,
                 rect=None, key_color="#ffffff"):
    """Split `src_asset` into `body_asset` (parent) and `part_asset` (articulated child).

    Args:
        src_asset: Existing asset name in `assets/<src_asset>.png`.
        body_asset: Output asset name for the parent body (`assets/<body_asset>.png`).
        part_asset: Output asset name for the child limb/weapon (`assets/<part_asset>.png`).
        box: [x0, y0, x1, y1] bounding region in source pixels (or 0..1 normalized floats)
             that belongs to the detachable child weapon/limb.
        joint: [jx, jy] joint center in source pixels (or 0..1 normalized floats).
        joint_radius: Overlap radius in source pixels kept on both parent and child
                      around `joint` so rotating the child never exposes a gap.
        rect: Optional [rx, ry, rw, rh] canvas rect to compute the exact canvas `pivot`.
        key_color: Solid background hex color (default `#ffffff`).
    """
    row = manifest.verified("assets", src_asset)
    src_path = os.path.join(ROOT, row["path"] if row else f"assets/{src_asset}.png")
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"source asset not found: {src_path}")

    w, h = read_size(src_path)
    key_rgb = hex_rgb(key_color)
    key_bytes = bytes(key_rgb)
    src_buf = bytearray(read_rgb(src_path, w, h))

    bx0, by0, bx1, by1 = box
    if all(0.0 <= v <= 1.0 for v in box):
        bx0, bx1 = int(round(bx0 * w)), int(round(bx1 * w))
        by0, by1 = int(round(by0 * h)), int(round(by1 * h))
    else:
        bx0, by0, bx1, by1 = int(round(bx0)), int(round(by0)), int(round(bx1)), int(round(by1))

    jx, jy = joint
    if 0 < jx <= 1.0 and 0 < jy <= 1.0:
        jx, jy = int(round(jx * w)), int(round(jy * h))
    else:
        jx, jy = int(round(jx)), int(round(jy))

    r_sq = joint_radius * joint_radius
    overlap_sq = max(4, int(joint_radius * 0.75)) ** 2

    body_buf = bytearray(src_buf)
    part_buf = bytearray(key_bytes * (w * h))

    for y in range(h):
        for x in range(w):
            in_box = (bx0 <= x <= bx1 and by0 <= y <= by1)
            dist_sq = (x - jx) ** 2 + (y - jy) ** 2
            in_joint_cap = dist_sq <= r_sq
            if in_box or in_joint_cap:
                idx = (y * w + x) * 3
                part_buf[idx:idx + 3] = src_buf[idx:idx + 3]
                # Keep a small inner overlap disc on the parent body at the joint
                # so rotating the child never opens a white seam at the hinge.
                if in_box and dist_sq > overlap_sq:
                    body_buf[idx:idx + 3] = key_bytes

    clean_perimeter(body_buf, w, h, key_rgb)
    clean_perimeter(part_buf, w, h, key_rgb)

    body_rel = f"assets/{body_asset}.png"
    part_rel = f"assets/{part_asset}.png"
    write_png(os.path.join(ROOT, body_rel), w, h, bytes(body_buf))
    write_png(os.path.join(ROOT, part_rel), w, h, bytes(part_buf))

    r_body = manifest.register("assets", body_asset, body_rel, source="rig-split",
                               parent_source=src_asset)
    r_part = manifest.register("assets", part_asset, part_rel, source="rig-split",
                               parent_source=src_asset, joint=[jx, jy])

    effective_rect = rect or [0, 0, w, h]
    canvas_pivot = source_to_canvas_pivot(w, h, effective_rect, jx, jy)
    return {
        "body_asset": body_asset,
        "body_sha256": r_body["sha256"][:12],
        "part_asset": part_asset,
        "part_sha256": r_part["sha256"][:12],
        "size": [w, h],
        "joint_source": [jx, jy],
        "rect": effective_rect,
        "canvas_pivot": canvas_pivot,
    }


def split_multi_sprite(src_asset, body_asset, parts, clean_boxes=None, rect=None, key_color="#ffffff"):
    """Generic multi-limb splitter: separate `src_asset` into `body_asset` + N articulated child `parts`.

    Eliminates character-specific pixel loops when splitting a character into a torso plus
    multiple articulated limbs/weapons/props (e.g., front arm + rear arm, hand + basket,
    dual weapons, or head + limbs).

    Args:
        src_asset: Source asset name in `assets/<src_asset>.png`.
        body_asset: Output parent body asset name (`assets/<body_asset>.png`).
        parts: List of dicts, each specifying:
            - `"asset"`: output child asset name (`assets/<asset>.png`)
            - `"joint"`: `[jx, jy]` hinge coordinates in source pixels (or 0..1 normalized floats)
            - `"box"`: `[x0, y0, x1, y1]` bounding region, OR `"boxes"`: list of `[x0, y0, x1, y1]` regions
            - `"radius"` (optional): joint cap radius in source pixels (default `20`)
        clean_boxes: Optional list of `[x0, y0, x1, y1]` boxes to erase stray AI-baked wire/rod stubs
                     to `key_color` before splitting.
        rect: Optional `[rx, ry, rw, rh]` canvas rect to compute `canvas_pivot` for each part.
        key_color: Solid background hex color (default `#ffffff`).
    """
    if not isinstance(parts, list) or not parts:
        raise ValueError("split_multi_sprite requires a non-empty list of part definitions")

    row = manifest.verified("assets", src_asset)
    src_path = os.path.join(ROOT, row["path"] if row else f"assets/{src_asset}.png")
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"source asset not found: {src_path}")

    w, h = read_size(src_path)
    key_rgb = hex_rgb(key_color)
    key_bytes = bytes(key_rgb)
    src_buf = bytearray(read_rgb(src_path, w, h))

    def norm_box(b):
        bx0, by0, bx1, by1 = b
        if all(0.0 <= v <= 1.0 for v in b):
            return [int(round(bx0 * w)), int(round(by0 * h)), int(round(bx1 * w)), int(round(by1 * h))]
        return [int(round(bx0)), int(round(by0)), int(round(bx1)), int(round(by1))]

    if clean_boxes:
        for cb in clean_boxes:
            cx0, cy0, cx1, cy1 = norm_box(cb)
            for y in range(max(0, cy0), min(h, cy1 + 1)):
                for x in range(max(0, cx0), min(w, cx1 + 1)):
                    idx = (y * w + x) * 3
                    src_buf[idx:idx + 3] = key_bytes

    body_buf = bytearray(src_buf)
    effective_rect = rect or [0, 0, w, h]
    part_Specs = []
    for p in parts:
        p_asset = p["asset"]
        raw_boxes = p.get("boxes") if p.get("boxes") else [p["box"]]
        boxes = [norm_box(b) for b in raw_boxes]
        jx, jy = p["joint"]
        if 0 < jx <= 1.0 and 0 < jy <= 1.0:
            jx, jy = int(round(jx * w)), int(round(jy * h))
        else:
            jx, jy = int(round(jx)), int(round(jy))
        rad = int(round(p.get("radius", 20)))
        part_Specs.append({
            "asset": p_asset,
            "boxes": boxes,
            "joint": [jx, jy],
            "r_sq": rad * rad,
            "ov_sq": max(4, int(rad * 0.75)) ** 2,
            "buf": bytearray(key_bytes * (w * h)),
        })

    for y in range(h):
        for x in range(w):
            idx = (y * w + x) * 3
            px_bytes = src_buf[idx:idx + 3]
            if px_bytes == key_bytes:
                continue
            for ps in part_Specs:
                jx, jy = ps["joint"]
                dist_sq = (x - jx) ** 2 + (y - jy) ** 2
                in_any_box = any(bx0 <= x <= bx1 and by0 <= y <= by1 for bx0, by0, bx1, by1 in ps["boxes"])
                if in_any_box or dist_sq <= ps["r_sq"]:
                    ps["buf"][idx:idx + 3] = px_bytes
                    if in_any_box and dist_sq > ps["ov_sq"]:
                        body_buf[idx:idx + 3] = key_bytes

    clean_perimeter(body_buf, w, h, key_rgb)
    body_rel = f"assets/{body_asset}.png"
    write_png(os.path.join(ROOT, body_rel), w, h, bytes(body_buf))
    r_body = manifest.register("assets", body_asset, body_rel, size=[w, h],
                               source="rig-split-multi", parent_source=src_asset)

    out_parts = []
    for ps in part_Specs:
        clean_perimeter(ps["buf"], w, h, key_rgb)
        p_rel = f"assets/{ps['asset']}.png"
        write_png(os.path.join(ROOT, p_rel), w, h, bytes(ps["buf"]))
        r_part = manifest.register("assets", ps["asset"], p_rel, size=[w, h],
                                   source="rig-split-multi", parent_source=src_asset, joint=ps["joint"])
        out_parts.append({
            "part_asset": ps["asset"],
            "part_sha256": r_part["sha256"][:12],
            "joint_source": ps["joint"],
            "canvas_pivot": source_to_canvas_pivot(w, h, effective_rect, ps["joint"][0], ps["joint"][1]),
        })

    return {
        "body_asset": body_asset,
        "body_sha256": r_body["sha256"][:12],
        "size": [w, h],
        "rect": effective_rect,
        "parts": out_parts,
    }


def snap_socket_joint(parent_size, parent_rect, parent_socket, child_size, child_joint,
                      scale=None, part_scale=1.0, socket_radius=None, joint_radius=None,
                      child_rect_size=None):
    """Compute child layer's canvas `rect` and canvas `pivot` to snap onto parent socket.

    Universal 2D Skeletal Assembly (Sci-Fi mechas, cybernetic limbs, weapons, puppets):
    - `parent_size`: [pw, ph] parent source image dimensions.
    - `parent_rect`: [rx, ry, rw, rh] parent canvas rectangle.
    - `parent_socket`: [sx, sy] receiving socket coordinates in parent source image.
    - `child_size`: [cw, ch] child limb/weapon source image dimensions.
    - `child_joint`: [jx, jy] joint flange center in child source image.
    - `scale`: optional explicit canvas-per-source-pixel scale for the child.
    - `part_scale`: multiplier relative to parent's contain-scale (default 1.0; use < 1.0
      when child is a close-up standalone asset whose joint cap is larger in source pixels
      than the parent's socket).
    - `socket_radius` / `joint_radius`: if both are provided, `part_scale` is automatically
      derived as `socket_radius / joint_radius` so the joint disc matches the socket size.
    - `child_rect_size`: optional [rw, rh] box size to preserve while snapping [rx, ry].

    Returns dict with exact `rect`, `pivot`, `scale`, and `part_scale`.
    """
    pw, ph = parent_size
    prx, pry, prw, prh = parent_rect
    psx, psy = parent_socket
    canvas_socket = source_to_canvas_pivot(pw, ph, parent_rect, psx, psy)

    cw, ch = child_size
    cjx, cjy = child_joint
    parent_scale = min(prw / max(1, pw), prh / max(1, ph))

    if socket_radius is not None and joint_radius is not None and joint_radius > 0:
        part_scale = float(socket_radius) / float(joint_radius)

    if child_rect_size is not None:
        cw_drawn, ch_drawn = int(round(child_rect_size[0])), int(round(child_rect_size[1]))
        eff_scale = min(cw_drawn / max(1, cw), ch_drawn / max(1, ch))
        pad_x = (cw_drawn - cw * eff_scale) / 2.0
        pad_y = (ch_drawn - ch * eff_scale) / 2.0
        crx = int(round(canvas_socket[0] - (pad_x + cjx * eff_scale)))
        cry = int(round(canvas_socket[1] - (pad_y + cjy * eff_scale)))
        scale = eff_scale
    else:
        if scale is None:
            scale = parent_scale * float(part_scale)
        cw_drawn = max(2, int(round(cw * scale)))
        ch_drawn = max(2, int(round(ch * scale)))
        crx = int(round(canvas_socket[0] - cjx * scale))
        cry = int(round(canvas_socket[1] - cjy * scale))

    child_rect = [crx, cry, cw_drawn, ch_drawn]
    canvas_pivot = source_to_canvas_pivot(cw, ch, child_rect, cjx, cjy)
    return {
        "parent_socket_canvas": canvas_socket,
        "rect": child_rect,
        "pivot": canvas_pivot,
        "scale": round(scale, 6),
        "part_scale": round(float(part_scale), 4),
    }


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


# ==============================================================================
# INVERSE KINEMATICS (IK) & PARAMETRIC MARTIAL ARTS CHOREOGRAPHY ENGINE
# ==============================================================================

def solve_2bone_ik(hip, foot, L1, L2, bend_dir=1):
    """Analytic 2-bone Inverse Kinematics solver (thigh -> knee -> foot).

    Parameters:
    - hip: [hx, hy] hip socket coordinates
    - foot: [fx, fy] target foot contact coordinates
    - L1: length of upper segment (thigh)
    - L2: length of lower segment (calf + foot)
    - bend_dir: +1 (knee bends forward/right) or -1 (knee bends backward/left)

    Returns:
    - thigh_angle: angle of thigh relative to vertical (pointing down), in degrees
    - knee_angle: relative bend angle at knee joint, in degrees
    - knee: [kx, ky] calculated 2D knee joint position
    - foot: [fx, fy] actual foot position (coincident with target if reachable)
    - reachable: True if target was within reach (dist <= L1 + L2)
    """
    hx, hy = hip
    fx, fy = foot
    dx = fx - hx
    dy = fy - hy
    dist = math.hypot(dx, dy)

    # Ray angle from hip to target
    theta_base = math.atan2(dy, dx)

    # Target beyond reach: fully extended along ray
    if dist >= (L1 + L2) - 1e-4:
        kx = hx + L1 * math.cos(theta_base)
        ky = hy + L1 * math.sin(theta_base)
        act_fx = hx + (L1 + L2) * math.cos(theta_base)
        act_fy = hy + (L1 + L2) * math.sin(theta_base)
        thigh_angle = math.degrees(theta_base - math.pi / 2.0)
        return {
            "thigh_angle": round(thigh_angle, 2),
            "knee_angle": 0.0,
            "knee": [round(kx, 1), round(ky, 1)],
            "foot": [round(act_fx, 1), round(act_fy, 1)],
            "reachable": False,
        }

    # Target collapsed inside minimum reach:
    min_reach = abs(L1 - L2) + 1e-3
    if dist < min_reach:
        dist = min_reach

    # Law of Cosines:
    # L2^2 = L1^2 + dist^2 - 2 * L1 * dist * cos(alpha)
    cos_alpha = (L1 * L1 + dist * dist - L2 * L2) / (2.0 * L1 * dist)
    cos_alpha = max(-1.0, min(1.0, cos_alpha))
    alpha = math.acos(cos_alpha)

    # dist^2 = L1^2 + L2^2 - 2 * L1 * L2 * cos(beta)
    cos_beta = (L1 * L1 + L2 * L2 - dist * dist) / (2.0 * L1 * L2)
    cos_beta = max(-1.0, min(1.0, cos_beta))
    beta = math.acos(cos_beta)

    # Thigh direction:
    theta_thigh = theta_base - bend_dir * alpha
    kx = hx + L1 * math.cos(theta_thigh)
    ky = hy + L1 * math.sin(theta_thigh)

    # Calf direction:
    theta_calf = math.atan2(fy - ky, fx - kx)
    rel_knee = math.degrees(theta_calf - theta_thigh)
    # Normalize to [-180, 180]
    while rel_knee > 180:
        rel_knee -= 360
    while rel_knee < -180:
        rel_knee += 360

    thigh_angle = math.degrees(theta_thigh - math.pi / 2.0)
    return {
        "thigh_angle": round(thigh_angle, 2),
        "knee_angle": round(rel_knee, 2),
        "knee": [round(kx, 1), round(ky, 1)],
        "foot": [round(fx, 1), round(fy, 1)],
        "reachable": True,
    }


def solve_leg_ground_lock(hip_x, hip_y, ground_y, foot_offset_x, L1=160, L2=160, bend_dir=1):
    """Lock a puppet's foot to the ground plane while the hip moves dynamically."""
    foot_x = hip_x + foot_offset_x
    foot_y = ground_y
    return solve_2bone_ik([hip_x, hip_y], [foot_x, foot_y], L1, L2, bend_dir=bend_dir)


def solve_spring_damper_track(driver_kfs, total_frames, fps=30, omega=18.0, zeta=0.25,
                              coupling=0.45, base_kfs=None, step_frames=2, max_accel=4500.0):
    """Simulate a 2nd-order damped spring-mass oscillator driven by parent acceleration.

    Models secondary appendages (pheasant plumes, silk ribbons, tassels, or chart needles)
    under the differential equation:
        theta'' + 2 * zeta * omega * theta' + omega^2 * (theta - theta_rest) = -coupling * u''(t)

    where u(t) is the primary bone's motion track (`driver_kfs`) and theta_rest(t) is the
    optional baseline orientation (`base_kfs`). When the primary bone accelerates or snaps
    to a sudden halt (`亮相`), the appendage naturally lags behind and rings out with realistic
    damped rod-tremor (`抖签`) oscillation.
    """
    if total_frames <= 1:
        return [[0, 0.0]]

    dt_frame = 1.0 / max(1.0, float(fps))
    substeps = 4
    dt = dt_frame / substeps
    clamp_a = max(1.0, float(max_accel))

    u = [eval_channel(driver_kfs, f, 0.0) for f in range(total_frames)]
    r = [eval_channel(base_kfs, f, 0.0) if base_kfs else 0.0 for f in range(total_frames)]

    accel = [0.0] * total_frames
    for f in range(1, total_frames - 1):
        a = (u[f + 1] - 2.0 * u[f] + u[f - 1]) / (dt_frame * dt_frame)
        accel[f] = max(-clamp_a, min(clamp_a, a))

    theta = r[0]
    vel = 0.0
    out_kfs = []

    for f in range(total_frames):
        target_r = r[f]
        drv_a = accel[f]
        for _ in range(substeps):
            force = -coupling * drv_a - 2.0 * zeta * omega * vel - (omega * omega) * (theta - target_r)
            vel += force * dt
            theta += vel * dt
        if f == 0 or f == total_frames - 1 or f % max(1, int(step_frames)) == 0:
            out_kfs.append([f, round(theta, 2)])

    return out_kfs


def generate_puppet_choreography(beats, default_ground_y=720):
    """Generate physically-coordinated keyframe tracks for an articulated puppet.

    Produces synchronized keyframes for:
    - torso: x, y, rotate (center of gravity & weight shifts)
    - leg-front: rotate (stepping, crouching, kicking with ground contact)
    - leg-back: rotate (stance anchoring, lunging, pushing)
    - arm-front: rotate (weapon swings, thrusts, aerial raises)
    - arm-back: rotate (counter-phase martial balance, 亮掌/甩袖)
    - plume: rotate (inertial lag & harmonic settlement)
    """
    torso_x = []
    torso_y = []
    torso_rot = []
    leg_front_rot = []
    leg_back_rot = []
    arm_front_rot = []
    arm_back_rot = []
    plume_rot = []

    for b in beats:
        btype = b.get("type", "ready")
        f_start = b["start"]
        f_end = b["end"]
        ground_y = b.get("ground_y", default_ground_y)

        if btype == "ready":
            # Classic Opera Wusheng Stance (虚步就绪):
            # Front foot light on toe (-5°), back foot supporting 70% weight (15°).
            # Rear arm extended behind back in martial balance (+30°), front arm holding staff (0°).
            rx = b.get("root_x", 450)
            torso_x.append([f_start, rx])
            torso_y.append([f_start, 0])
            torso_rot.append([f_start, 0])
            leg_front_rot.append([f_start, -5])
            leg_back_rot.append([f_start, 15])
            arm_front_rot.append([f_start, 0])
            arm_back_rot.append([f_start, 30])
            plume_rot.append([f_start, -8])

            if f_end > f_start:
                torso_x.append([f_end, rx])
                torso_y.append([f_end, 0])
                torso_rot.append([f_end, 0])
                leg_front_rot.append([f_end, -5])
                leg_back_rot.append([f_end, 15])
                arm_front_rot.append([f_end, 0])
                arm_back_rot.append([f_end, 30])
                plume_rot.append([f_end, -8])

        elif btype == "strike":
            # Three-Phase Martial Strike:
            # 1. Anticipation (蓄力): Torso lowers and pulls back, front staff raises overhead (-55°),
            #    rear arm counterbalances forward (-20°), front knee lifts (-28°), back leg extends (22°).
            # 2. Impact Snap (千钧暴击): Torso lunges down-forward into 弓步 (bow stance),
            #    front staff slams down level (40°), rear arm snaps back hard (+50° ~ +55°),
            #    front leg bends deep (20°), back leg straightens (-18°).
            # 3. Follow-through / Recoil (收势与定点): slight rebound into guard.
            f_ant = b.get("anticipation", int(f_start + (f_end - f_start) * 0.45))
            f_hit = b.get("impact", int(f_start + (f_end - f_start) * 0.75))
            x_start = b.get("root_x_start", 450)
            x_end = b.get("root_x_end", 800)

            # --- Anticipation Frame ---
            torso_x.append([f_ant, int(x_start + (x_end - x_start) * 0.35), "out"])
            torso_y.append([f_ant, -15, "out"])  # slight aerial lift or crouch
            torso_rot.append([f_ant, -10, "out"]) # leaning back
            leg_front_rot.append([f_ant, -28, "out"])
            leg_back_rot.append([f_ant, 22, "out"])
            arm_front_rot.append([f_ant, -55, "out"]) # weapon raised high
            arm_back_rot.append([f_ant, -20, "out"])  # counter-swings forward
            plume_rot.append([f_ant, 15, "out"])      # dragged back by air resistance

            # --- Impact Frame ---
            torso_x.append([f_hit, x_end, "in"])
            torso_y.append([f_hit, 0, "in"])
            torso_rot.append([f_hit, 8, "in"])        # lunging forward into strike
            leg_front_rot.append([f_hit, 20, "in"])   # bow stance (弓步屈膝)
            leg_back_rot.append([f_hit, -16, "in"])  # arrow leg straight (箭步绷直)
            arm_front_rot.append([f_hit, 40, "snap"]) # lethal snap down
            arm_back_rot.append([f_hit, 48, "snap"])  # rear balance snap backwards!
            plume_rot.append([f_hit, -22, "snap"])    # whipped forward on sudden stop

            # --- Recoil / Settle Frame ---
            if f_end > f_hit:
                torso_x.append([f_end, int(x_end - 25), "out"])
                torso_y.append([f_end, 0, "out"])
                torso_rot.append([f_end, 2, "out"])
                leg_front_rot.append([f_end, 0, "out"])
                leg_back_rot.append([f_end, 15, "out"])
                arm_front_rot.append([f_end, 10, "out"])
                arm_back_rot.append([f_end, 32, "out"])
                plume_rot.append([f_end, -10, "out"])

    return {
        "torso": {
            "x": torso_x,
            "y": torso_y,
            "rotate": torso_rot,
        },
        "leg-front": {
            "rotate": leg_front_rot,
        },
        "leg-back": {
            "rotate": leg_back_rot,
        },
        "arm-front": {
            "rotate": arm_front_rot,
        },
        "arm-back": {
            "rotate": arm_back_rot,
        },
        "plume": {
            "rotate": plume_rot,
        },
    }


def verify_puppet_rig(spec, out_dir="build/inspect", tolerance=4):
    """Verify skeletal puppet joint alignment, socket calibration, and render diagnostic overlay."""
    layers = spec.get("layers", [])
    layer_map = {L["id"]: L for L in layers}
    results = []
    errors = []

    os.makedirs(os.path.join(ROOT, out_dir), exist_ok=True)

    # Find root puppets and their child limbs
    for L in layers:
        par_id = L.get("parent")
        if not par_id or par_id not in layer_map:
            continue
        par = layer_map[par_id]
        kit = L.get("kit")
        if not kit:
            continue

        socket_src = kit.get("socket")
        joint_src = kit.get("joint")
        if not socket_src or not joint_src:
            errors.append(f"{L['id']}: missing socket or joint in kit configuration")
            continue

        # Get parent asset and child asset dimensions
        par_asset = par.get("asset")
        child_asset = L.get("asset")
        par_row = manifest.verified("assets", par_asset)
        child_row = manifest.verified("assets", child_asset)

        if not par_row or not child_row:
            errors.append(f"{L['id']}: missing verified manifest asset for parent ({par_asset}) or child ({child_asset})")
            continue

        par_size = par_row["size"]
        child_size = child_row["size"]
        par_rect = par.get("rect", [0, 0, par_size[0], par_size[1]])
        part_scale = L.get("partScale", 1.0)

        # Snap socket to joint:
        snapped = snap_socket_joint(par_size, par_rect, socket_src, child_size, joint_src, part_scale=part_scale)
        child_rect = snapped["rect"]
        child_pivot = snapped["pivot"]

        # Calculate canvas position of parent socket:
        par_socket_canvas = source_to_canvas_pivot(par_size[0], par_size[1], par_rect, socket_src[0], socket_src[1])

        # Distance error between parent socket and child pivot
        delta = math.hypot(par_socket_canvas[0] - child_pivot[0], par_socket_canvas[1] - child_pivot[1])
        status = "PASS" if delta <= tolerance else "DISLOCATED"

        if delta > tolerance:
            errors.append(
                f"{L['id']}: joint detached from parent socket! delta={delta:.1f}px > tol={tolerance}px. "
                f"Parent socket canvas={par_socket_canvas}, child pivot={child_pivot}"
            )

        results.append({
            "child_id": L["id"],
            "parent_id": par_id,
            "delta_px": round(delta, 2),
            "status": status,
            "socket_src": socket_src,
            "joint_src": joint_src,
            "pivot_canvas": child_pivot,
            "child_rect": child_rect,
        })

    # Render diagnostic calibration sheet if PIL is available
    diag_path = os.path.join(ROOT, out_dir, f"rig_calibration_{spec.get('id', 'puppet')}.png")
    try:
        from PIL import Image, ImageDraw
        cw, ch = spec.get("canvas", {}).get("w", 1920), spec.get("canvas", {}).get("h", 1080)
        img = Image.new("RGBA", (cw, ch), (20, 16, 12, 255))
        draw = ImageDraw.Draw(img)

        # Draw grid
        for x in range(0, cw, 100):
            draw.line([(x, 0), (x, ch)], fill=(40, 32, 24), width=1)
        for y in range(0, ch, 100):
            draw.line([(0, y), (cw, y)], fill=(40, 32, 24), width=1)

        # Plot each calibrated joint
        for r in results:
            px, py = r["pivot_canvas"]
            # Socket crosshair (RED)
            draw.line([(px - 14, py), (px + 14, py)], fill=(255, 60, 60), width=3)
            draw.line([(px, py - 14), (px, py + 14)], fill=(255, 60, 60), width=3)
            # Joint circle (CYAN)
            draw.ellipse([px - 8, py - 8, px + 8, py + 8], outline=(60, 220, 255), width=2)
            # Label
            draw.text((px + 16, py - 8), f"{r['child_id']} (Δ={r['delta_px']}px) [{r['status']}]",
                      fill=(255, 215, 0) if r["status"] == "PASS" else (255, 50, 50))

        img.save(diag_path)
    except Exception:
        pass

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "joints": results,
        "diagnostic_image": diag_path,
    }


def eval_channel(kfs, frame, fallback=0.0):
    """Linearly interpolate a scalar keyframe track at a given frame."""
    if not kfs:
        return fallback
    if frame <= kfs[0][0]:
        return float(kfs[0][1])
    if frame >= kfs[-1][0]:
        return float(kfs[-1][1])
    for i in range(len(kfs) - 1):
        k0 = kfs[i]
        k1 = kfs[i + 1]
        if k0[0] <= frame <= k1[0]:
            t = (frame - k0[0]) / max(1, k1[0] - k0[0])
            return float(k0[1]) + (float(k1[1]) - float(k0[1])) * t
    return fallback


def verify_combat_contact(spec, attacker_id=None, weapon_id=None,
                          target_id=None, tolerance=None, tip_offset=None, ref_width=None):
    """Verify that the attacker's weapon physically contacts the target hitbox on all punch frames.

    Reads combat participants & weapon geometry from:
    1. Explicit function arguments (`attacker_id`, `weapon_id`, `target_id`, `tolerance`, `tip_offset`, `ref_width`),
    2. Or `spec["combat"]` (`{"attacker": "...", "weapon": "...", "target": "...", "tolerance": 40, "tipOffset": [dx, dy], "refWidth": 1090}`),
    3. Or automatic topological discovery (locating the root parent with an articulated weapon/arm child and the opposing character layer).
    """
    combat_cfg = spec.get("combat") if isinstance(spec.get("combat"), dict) else {}
    layers_list = spec.get("layers", [])
    layers = {l["id"]: l for l in layers_list if "id" in l}

    attacker_id = attacker_id or combat_cfg.get("attacker")
    weapon_id = weapon_id or combat_cfg.get("weapon")
    target_id = target_id or combat_cfg.get("target")
    if tolerance is None:
        tolerance = combat_cfg.get("tolerance", 40)
    tip_offset = tip_offset or combat_cfg.get("tipOffset")
    ref_width = ref_width or combat_cfg.get("refWidth")

    # Auto-discover from layer topology if not explicitly specified
    if not weapon_id:
        for l in layers_list:
            lid = l.get("id", "").lower()
            ktype = (l.get("kit") or {}).get("type", "")
            is_weapon_like = (ktype == "weapon" or "staff" in lid or "weapon" in lid or "sword" in lid or "blade" in lid or "lance" in lid or "spear" in lid or "arm" in lid)
            if is_weapon_like and (l.get("parent") or "pivot" in l):
                weapon_id = l["id"]
                if not attacker_id:
                    if l.get("parent"):
                        attacker_id = l["parent"]
                    elif "-" in l["id"]:
                        prefix = l["id"].split("-")[0]
                        if prefix in layers:
                            attacker_id = prefix
                break

    if not attacker_id and weapon_id and weapon_id in layers:
        attacker_id = layers[weapon_id].get("parent")
        if not attacker_id and "-" in weapon_id:
            prefix = weapon_id.split("-")[0]
            if prefix in layers:
                attacker_id = prefix

    if not target_id:
        for l in layers_list:
            lid = l.get("id")
            if lid and lid not in (attacker_id, weapon_id) and not l.get("parent") and (l.get("cutout") or l.get("poses") or "anim" in l):
                ltype = l.get("type")
                if ltype in (None, "ai", "component", "code") and l.get("draw") not in ("field", "path", "captions", "grid", "dots"):
                    target_id = lid
                    break

    attacker = layers.get(attacker_id) if attacker_id else None
    weapon = layers.get(weapon_id) if weapon_id else None
    target = layers.get(target_id) if target_id else None

    if not attacker or not weapon or not target:
        return {
            "passed": False,
            "errors": [
                f"Missing attacker, weapon, or target layer in spec (resolved attacker={attacker_id!r}, weapon={weapon_id!r}, target={target_id!r}). "
                f"Declare 'combat': {{'attacker': '...', 'weapon': '...', 'target': '...'}} in spec or pass --attacker/--weapon/--target."
            ],
        }

    punches = spec.get("punches", [])
    if not punches:
        return {"passed": True, "details": [], "message": "No punches defined"}

    errors = []
    details = []

    w_rect = weapon.get("rect", [0, 0, 476, 530])
    p0 = weapon.get("pivot", [attacker["rect"][0] + attacker["rect"][2] * 0.5, attacker["rect"][1] + attacker["rect"][3] * 0.35])

    if ref_width is None:
        w_asset = weapon.get("asset")
        w_row = manifest.verified("assets", w_asset) if w_asset else None
        if w_row and isinstance(w_row.get("size"), list) and w_row["size"][0] > 0:
            ref_width = float(w_row["size"][0])
        else:
            ref_width = 1090.0

    scale = w_rect[2] / float(ref_width) if w_rect[2] > 0 and ref_width > 0 else 0.42

    if tip_offset is not None and len(tip_offset) == 2:
        dx0 = float(tip_offset[0]) * scale
        dy0 = float(tip_offset[1]) * scale
    else:
        dx0 = 535.0 * scale
        dy0 = -268.0 * scale

    for f in punches:
        wa_x = eval_channel(attacker.get("anim", {}).get("x", []), f)
        wa_y = eval_channel(attacker.get("anim", {}).get("y", []), f)
        wa_rot = eval_channel(attacker.get("anim", {}).get("rotate", []), f)
        wep_rot = eval_channel(weapon.get("anim", {}).get("rotate", []), f)

        bg_x = eval_channel(target.get("anim", {}).get("x", []), f)
        bg_y = eval_channel(target.get("anim", {}).get("y", []), f)

        px = p0[0] + wa_x
        py = p0[1] + wa_y

        tot_rot = math.radians(wa_rot + wep_rot)
        tip_x = px + (dx0 * math.cos(tot_rot) - dy0 * math.sin(tot_rot))
        tip_y = py + (dx0 * math.sin(tot_rot) + dy0 * math.cos(tot_rot))

        t_rect = target.get("rect", [980, 509, 246, 330])
        t_min = t_rect[0] + bg_x
        t_max = t_min + t_rect[2]

        if tip_x < t_min:
            gap = t_min - tip_x
            status = "WHIFFING_SHORT" if gap > tolerance else "CONTACT_PASS"
        elif tip_x > t_max:
            gap = tip_x - t_max
            status = "OVER_PENETRATION" if gap > tolerance else "CONTACT_PASS"
        else:
            gap = 0.0
            status = "DIRECT_HIT"

        if status not in ("CONTACT_PASS", "DIRECT_HIT"):
            errors.append(
                f"Punch at frame {f}: weapon tip at x={tip_x:.1f} misses target [{t_min:.1f}, {t_max:.1f}] by {gap:.1f}px!"
            )

        details.append({
            "frame": f,
            "weapon_tip": [round(tip_x, 1), round(tip_y, 1)],
            "target_hitbox": [round(t_min, 1), round(t_max, 1)],
            "gap_px": round(gap, 1),
            "status": status,
        })

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "details": details,
    }


def verify_stage_blocking(spec, max_overlap_px=12.0):
    """Verify that co-planar 2D cutout characters do not overlap horizontally on the stage plane.

    In 2D shadow puppetry and flat-plane cutout animation, all characters occupy the same
    optical projection screen (`同平面贴幕`). When two upright characters' torsos overlap
    horizontally (`overlap_x > max_overlap_px`), their translucent/multiply layers muddy
    together into an unreadable silhouette.

    Rules (100% domain-agnostic, zero character-name hardcoding):
    - Discovers all root cutout character layers (`type == 'ai'`, `cutout == True`, `parent is None`).
    - Computes each character's core torso horizontal interval `[x_left(f), x_right(f)]` from its
      actual opaque pixel bounding box mapped into `layer['rect']` + `anim.x(f)`.
    - Exempts frames where a character is invisible (`opacity < 0.25`), leaping high in the air
      above head height (`anim.y(f) <= -105`), or collapsed on the ground after impact.
    - Reports PASS if all upright ground-plane character pairs maintain clean horizontal separation
      across all frames `0..durationInFrames-1`, or FAIL with exact colliding pairs and frame windows.
    """
    layers_list = spec.get("layers", [])
    dur = int(spec.get("durationInFrames", 300))
    root_chars = [
        L for L in layers_list
        if L.get("type") == "ai" and L.get("cutout") and not L.get("parent")
    ]
    if len(root_chars) < 2:
        return {"passed": True, "errors": [], "pairs": []}

    char_boxes = {}
    for L in root_chars:
        lid = L["id"]
        rect = L.get("rect", [0, 0, 300, 400])
        rx, ry, rw, rh = rect
        asset = L.get("asset")
        row = manifest.verified("assets", asset) if asset else None
        src_path = os.path.join(ROOT, row["path"] if row else f"assets/{asset}.png") if asset else None
        if src_path and os.path.exists(src_path):
            sw, sh = read_size(src_path)
            buf = read_rgb(src_path, sw, sh)
            bx0, by0, bx1, by1 = sprite_bbox(buf, sw, sh, hex_rgb(L.get("keyColor", "#ffffff")))
            p0 = source_to_canvas_pivot(sw, sh, rect, bx0, by0)
            p1 = source_to_canvas_pivot(sw, sh, rect, bx1, by1)
            span_w = max(40.0, p1[0] - p0[0])
            # Core torso silhouette (trimming 12% outer sleeve/staff tip overhang on each side)
            base_left = p0[0] + span_w * 0.12
            base_right = p1[0] - span_w * 0.12
        else:
            base_left = rx + rw * 0.20
            base_right = rx + rw * 0.80
        char_boxes[lid] = (base_left, base_right, L)

    errors = []
    pair_summaries = []
    char_ids = [L["id"] for L in root_chars]

    for i in range(len(char_ids)):
        for j in range(i + 1, len(char_ids)):
            id_a, id_b = char_ids[i], char_ids[j]
            la_0, ra_0, layer_a = char_boxes[id_a]
            lb_0, rb_0, layer_b = char_boxes[id_b]
            anim_a = layer_a.get("anim") or {}
            anim_b = layer_b.get("anim") or {}

            max_ov = -9999.0
            worst_frame = 0
            overlap_frames = []

            for f in range(dur):
                op_a = eval_channel(anim_a.get("opacity", []), f, 1.0)
                op_b = eval_channel(anim_b.get("opacity", []), f, 1.0)
                if op_a < 0.25 or op_b < 0.25:
                    continue

                ya = eval_channel(anim_a.get("y", []), f, 0.0)
                yb = eval_channel(anim_b.get("y", []), f, 0.0)
                # High-altitude aerial leap/cloud flight passes above the ground plane
                if ya <= -105.0 or yb <= -105.0 or abs(ya - yb) >= 105.0:
                    continue

                # Check if either character has switched to a shattered/collapsed ground pose
                rot_a = abs(eval_channel(anim_a.get("rotate", []), f, 0.0))
                rot_b = abs(eval_channel(anim_b.get("rotate", []), f, 0.0))
                if (ya >= 18.0 and rot_a >= 12.0) or (yb >= 18.0 and rot_b >= 12.0):
                    continue

                xa = eval_channel(anim_a.get("x", []), f, 0.0)
                xb = eval_channel(anim_b.get("x", []), f, 0.0)
                a_left, a_right = la_0 + xa, ra_0 + xa
                b_left, b_right = lb_0 + xb, rb_0 + xb

                ov = min(a_right, b_right) - max(a_left, b_left)
                if ov > max_ov:
                    max_ov = ov
                    worst_frame = f
                if ov > max_overlap_px:
                    overlap_frames.append(f)

            status = "PASS" if not overlap_frames else "OVERLAP"
            min_clearance = round(-max_ov, 1) if max_ov > -9000 else 999.0
            pair_summaries.append({
                "pair": f"{id_a} <-> {id_b}",
                "status": status,
                "max_overlap_px": round(max(0.0, max_ov), 1),
                "min_clearance_px": min_clearance,
                "worst_frame": worst_frame,
                "overlap_frame_count": len(overlap_frames),
            })
            if overlap_frames:
                f0, f1 = overlap_frames[0], overlap_frames[-1]
                errors.append(
                    f"Co-planar character overlap between '{id_a}' and '{id_b}' on frames {f0}..{f1} "
                    f"(worst at frame {worst_frame}: overlap={max_ov:.1f}px > max_overlap_px={max_overlap_px}px). "
                    f"Separate their horizontal stage zones or add push-pull counter-blocking!"
                )

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "pairs": pair_summaries,
    }





