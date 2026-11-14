"""Cross-shot timeline continuity verification (backdrop handoff & character state seams)."""
import math
import os

from core.runtime.config import ROOT

from .stagecraft import verify_shot_stagecraft


def verify_timeline_continuity(timeline_data, root_dir=None, require_seamless_handoff=True, max_char_jump_px=18.0):
    """Verify multi-scene narrative continuity across an entire timeline of shots.

    Enforces traditional shadow-puppetry / 2D scrolling stagecraft invariants:
    1. Zero Frozen Characters: Every character on stage in every shot has articulated motion.
    2. Zero Wireframe Path Overlays on Shadow-Puppet Stages: Magical circles, halos, and
       binding rings must be carved translucent oxhide cutout props (`role: 'prop'`), never
       crude geometric `code: path` lines.
    3. Push-Pull Scrolling Transitions ('推拉换景') & Cross-Shot Backdrop Handoff ('跨幕同景交接'):
       When Shot k scrolls to `end_backdrop` at its tail, Shot k+1 must open on that exact
       `start_backdrop == end_backdrop` so concatenating Shot k -> Shot k+1 produces zero
       background jump at the cut boundary.
    4. Cross-Shot Character State Continuity ('跨幕角色坐标与显隐无缝咬合'):
       - Any character visible at the end of Shot k and at frame 0 of Shot k+1 must preserve
         their canvas position (`hypot(dx, dy) <= max_char_jump_px`) with zero teleport jump.
       - Any newly entering character in Shot k+1 (not visible at the end of Shot k) must start
         off-stage (`|x| >= 340` or `|y| >= 220`) or faded out (`opacity <= 0.15`) at frame 0,
         never popping into the middle of the screen at the cut boundary.
    """
    import json as _json
    base_dir = root_dir or ROOT
    shots_cfg = timeline_data.get("shots", [])
    shot_reports = []
    errors = []

    for entry in shots_cfg:
        spec_rel = entry["spec"] if isinstance(entry, dict) else entry
        spec_path = os.path.join(base_dir, spec_rel if spec_rel.endswith(".json") else f"spec/{spec_rel}.poster.json")
        if not os.path.exists(spec_path):
            errors.append(f"Shot spec not found: {spec_path}")
            continue
        with open(spec_path) as f:
            s_data = _json.load(f)
        rep = verify_shot_stagecraft(s_data)
        shot_reports.append(rep)
        if rep["frozen_characters"]:
            errors.append(f"{rep['shot_id']}: frozen character(s) without motion: {rep['frozen_characters']}")
        if rep["wireframe_paths"]:
            errors.append(
                f"{rep['shot_id']}: crude wireframe 'code: path' layer(s) {rep['wireframe_paths']} on shadow-puppet stage — "
                f"replace with carved oxhide filigree cutout prop assets (role='prop', cutout=True)!"
            )
        if rep.get("stale_props"):
            errors.append(
                f"{rep['shot_id']}: stale stationary ground prop(s) {rep['stale_props']} remain visible during/after stage scroll transition — "
                f"fade out (opacity -> 0) before the scenery scrolls!"
            )
        if rep.get("weak_shudder_acting"):
            errors.append(
                f"{rep['shot_id']}: character(s) {rep['weak_shudder_acting']} with gait.mode='shudder' lack deep kneeling/forward-pitching agony posture or bare-arm pose!"
            )
        if rep.get("caption_action_desync"):
            errors.append(
                f"{rep['shot_id']}: caption-to-acting desynchronization detected: {rep['caption_action_desync']}"
            )
        if len(rep.get("root_characters", [])) >= 3 and not rep.get("turnaround_characters"):
            errors.append(
                f"{rep['shot_id']}: all {len(rep['root_characters'])} characters remain locked facing a single direction — "
                f"use flipX or anim.flipX so characters turn to face each other during dialogue, slander, or kowtowing!"
            )
        if not rep["narrative_props"]:
            errors.append(f"{rep['shot_id']}: missing narrative stagecraft props/effects ('砌末')")

    handoffs = []
    for i in range(len(shot_reports) - 1):
        curr_rep = shot_reports[i]
        next_rep = shot_reports[i + 1]
        end_bg = curr_rep["end_backdrop"]
        next_start_bg = next_rep["start_backdrop"]
        seamless_bg = (end_bg == next_start_bg) or curr_rep["has_in_shot_scroll"] or next_rep["has_in_shot_scroll"]
        exact_bg = (end_bg == next_start_bg)
        bg_ok = exact_bg if require_seamless_handoff else seamless_bg

        # Check cross-shot character coordinate & entrance continuity
        char_jumps = []
        end_st = curr_rep.get("end_states", {})
        start_st = next_rep.get("start_states", {})
        is_continuous_stage = bool(end_st) or (end_bg is not None and end_bg == next_start_bg) or curr_rep["has_in_shot_scroll"] or next_rep["has_in_shot_scroll"]
        for cid, st1 in start_st.items():
            op1 = st1["opacity"]
            if op1 < 0.20:
                continue
            if cid in end_st and end_st[cid]["opacity"] >= 0.20:
                st0 = end_st[cid]
                jump = math.hypot(st1["x"] - st0["x"], st1["y"] - st0["y"])
                if jump > max_char_jump_px:
                    char_jumps.append(
                        f"{cid} teleports by {jump:.1f}px across cut ({curr_rep['shot_id']} end=({st0['x']}, {st0['y']}) -> "
                        f"{next_rep['shot_id']} start=({st1['x']}, {st1['y']}))"
                    )
            elif is_continuous_stage:
                cw, ch = st1.get("canvas", [1920, 1080])
                rx, ry, rw, rh = st1.get("rect", [0, 0, 300, 400])
                cx = st1["x"] + rw * 0.5
                cy = st1["y"] + rh * 0.5
                dx = st1.get("dx", 0.0)
                dy = st1.get("dy", 0.0)
                in_mid_stage_x = (cw * 0.18 < cx < cw * 0.82) and (st1["x"] >= 0) and (st1["x"] + rw <= cw)
                in_mid_stage_y = (ch * 0.15 < cy < ch * 0.88) and (st1["y"] >= 0) and (st1["y"] + rh <= ch)
                if in_mid_stage_x and in_mid_stage_y and abs(dx) < 340.0 and abs(dy) < 220.0:
                    char_jumps.append(
                        f"{cid} pops in mid-stage at frame 0 of {next_rep['shot_id']} (x={st1['x']}, y={st1['y']}, opacity={op1}); "
                        f"start off-stage (outside central stage [18%..82% W] or |anim.x|>=360) or fade in (opacity=0 at frame 0)"
                    )

        status = "PASS" if (bg_ok and not char_jumps) else ("CHAR_JUMP" if char_jumps else "HARD_CUT_JUMP")
        handoffs.append({
            "from_shot": curr_rep["shot_id"],
            "to_shot": next_rep["shot_id"],
            "end_backdrop": end_bg,
            "next_start_backdrop": next_start_bg,
            "in_shot_scroll": curr_rep["has_in_shot_scroll"] or next_rep["has_in_shot_scroll"],
            "char_jumps": char_jumps,
            "status": status,
        })
        if not bg_ok:
            errors.append(
                f"Hard-cut backdrop jump between '{curr_rep['shot_id']}' (ends on {end_bg!r}) "
                f"and '{next_rep['shot_id']}' (starts on {next_start_bg!r})."
            )
        for cj in char_jumps:
            errors.append(f"Cross-shot character discontinuity ({curr_rep['shot_id']} -> {next_rep['shot_id']}): {cj}")

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "shots": shot_reports,
        "handoffs": handoffs,
    }
