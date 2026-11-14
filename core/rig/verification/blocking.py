"""Co-planar stage blocking (horizontal non-overlap) verification."""
import os

from core.runtime import manifest
from core.runtime.config import ROOT
from core.quality.pixels import read_rgb
from core.media.png import read_size
from core.spec.naming import hex_rgb

from ..kinematics import eval_channel
from ..sprites import source_to_canvas_pivot, sprite_bbox


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
        if L.get("type") == "ai" and L.get("cutout") and not L.get("parent") and L.get("role") != "prop"
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
