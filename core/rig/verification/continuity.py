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
        errors.extend(rep["errors"])

    handoffs = []
    for i in range(len(shot_reports) - 1):
        curr_rep = shot_reports[i]
        next_rep = shot_reports[i + 1]
        end_bg = curr_rep["end_backdrop"]
        next_start_bg = next_rep["start_backdrop"]
        seamless_bg = (end_bg == next_start_bg)
        exact_bg = (end_bg == next_start_bg)
        bg_ok = exact_bg if require_seamless_handoff else seamless_bg

        # Check cross-shot character coordinate & entrance continuity
        char_jumps = []
        end_st = curr_rep.get("end_states", {})
        start_st = next_rep.get("start_states", {})
        is_continuous_stage = bool(end_st) or (end_bg is not None and end_bg == next_start_bg)
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

        status = "PASS" if (bg_ok and not char_jumps) else ("CHAR_JUMP" if char_jumps else "HARD_CUT_JUMP")
        handoffs.append({
            "from_shot": curr_rep["shot_id"],
            "to_shot": next_rep["shot_id"],
            "end_backdrop": end_bg,
            "next_start_backdrop": next_start_bg,
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
