"""Sprite pixel utilities, inspection, splitting, and canvas coordinates."""
import os

from core.runtime import manifest
from core.quality.pixels import edge_key_purity, read_rgb
from core.media.png import read_size, write_png
from core.runtime.config import ROOT
from core.media.geometry import source_to_canvas_pivot
from core.spec.naming import hex_rgb


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
    """Bounding box [xmin, ymin, xmax, ymax] of non-key pixels.

    `tol` is the per-channel distance from the key color within which a pixel
    still counts as background; it is a documented measurement choice, not a
    guessed default (raise it for near-white keys, lower it for chroma keys).
    """
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
    # The 0.75 factor is the documented seam-coverage rule: the part's clean
    # margin must extend 0.75*radius past the socket so the seam never shows.

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
