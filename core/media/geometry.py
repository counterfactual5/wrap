"""Sprite/canvas geometry shared by the spec resolver and the rig tooling.

Pure math, no imports beyond the stdlib — both `core.spec` and `core.rig`
depend on this module, so it must never depend back on either.
"""


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
