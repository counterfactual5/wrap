"""Co-planar stage blocking (horizontal non-overlap) verification."""
import os

from core.runtime import manifest
from core.runtime.config import ROOT
from core.quality.pixels import read_rgb
from core.media.png import read_size
from core.spec.naming import hex_rgb

from ..kinematics import eval_channel
from .stagecraft import DEFAULT_MIN_VISIBLE_OPACITY
from ..sprites import source_to_canvas_pivot, sprite_bbox


def verify_stage_blocking(spec, max_overlap_px=12.0,
                          min_visible_opacity=DEFAULT_MIN_VISIBLE_OPACITY,
                          torso_trim=0.12, min_span_px=40.0):
    """Verify that co-planar 2D cutout/character layers do not overlap horizontally on the stage plane.

    When two upright characters' torsos overlap horizontally (`overlap_x >
    max_overlap_px`), their translucent/multiply layers muddy together into
    an unreadable silhouette.

    Rules (domain-agnostic — measurements are derived, never guessed):
    - Discovers all root character layers: `type == 'ai'` with `cutout == True`,
      or `type == 'component'` with `role` in `{humanoid, quadruped, mech}`,
      with no `parent` and not `prop`.
    - Torso interval: for assets, derived from the opaque-pixel bounding box
      mapped into `layer['rect']` + `anim.x(f)`, with `torso_trim` (default 0.12)
      trimming outer sleeve/staff overhang on each side of the span
      (span floored at `min_span_px`, default 40.0 canvas px). For asset-less
      layers — project components have no pixels to derive from — the band is
      declared by the spec via `blockCore` [leftFrac, rightFrac] (in [0,1] of
      the rect width) — when missing, verification fails naming the layer
      instead of assuming 20–80%.
    - Exempts frames where a character is invisible (opacity < min_visible_opacity,
      default 0.20) or its layer carries `role: "prop"`. No guessed choreography
      exemptions (a leap is not assumed above the ground plane).
    - Reports PASS if all upright character pairs maintain clean horizontal separation
      across all frames `0..durationInFrames-1`, or FAIL with exact colliding pairs and frame windows.
    """
    layers_list = spec.get("layers", [])
    dur = int(spec["durationInFrames"])  # required by the schema
    # ai + cutout: asset-backed characters measured via opaque-pixel bbox.
    # component: project components with a declared character role measured
    # via the mandatory `blockCore` band (no pixels to derive from).
    ai_chars = [
        L for L in layers_list
        if L.get("type") == "ai" and L.get("cutout") and not L.get("parent") and L.get("role") != "prop"
    ]
    component_chars = [
        L for L in layers_list
        if L.get("type") == "component" and L.get("role") in ("humanoid", "quadruped", "mech")
        and not L.get("parent")
    ]
    root_chars = ai_chars + component_chars
    if len(root_chars) < 2:
        return {"passed": True, "errors": [], "pairs": []}

    char_boxes = {}
    missing_block_core = []
    for L in root_chars:
        lid = L["id"]
        rect = L["rect"]  # required by the schema
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
            span_w = max(min_span_px, p1[0] - p0[0])
            # Core torso silhouette (trimming outer sleeve/staff tip overhang on each side)
            base_left = p0[0] + span_w * torso_trim
            base_right = p1[0] - span_w * torso_trim
        else:
            block_core = L.get("blockCore")
            if not (isinstance(block_core, list) and len(block_core) == 2):
                missing_block_core.append(lid)
                continue
            base_left = rx + rw * block_core[0]
            base_right = rx + rw * block_core[1]
        char_boxes[lid] = (base_left, base_right, L)
    if missing_block_core:
        return {
            "passed": False,
            "errors": [
                f"verify-blocking cannot measure the torso band of asset-less character "
                f"layer(s) {missing_block_core}: declare a 'blockCore' [leftFrac, rightFrac] "
                f"(in [0,1]) on the layer, or give it an asset (the box is then derived "
                f"from its opaque pixels). The engine does not guess torso bands."
            ],
            "pairs": [],
        }

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
                if op_a < min_visible_opacity or op_b < min_visible_opacity:
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
