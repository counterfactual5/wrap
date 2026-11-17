"""Cross-shot timeline continuity verification (backdrop handoff & character state seams)."""
import math
import os

from core.runtime.config import ROOT

from .stagecraft import DEFAULT_MIN_VISIBLE_OPACITY, verify_shot_stagecraft


def verify_timeline_continuity(timeline_data, root_dir=None, require_seamless_handoff=True,
                               max_char_jump_px=18.0, min_visible_opacity=DEFAULT_MIN_VISIBLE_OPACITY):
    """Verify cross-shot continuity across an entire timeline of shots.

    For every adjacent shot pair (k, k+1) in the timeline:
    1. Backdrop handoff: shot k's tail backdrop must equal shot k+1's
       opening backdrop. With require_seamless_handoff=False a mismatch is
       reported as status 'BACKDROP_WARN' instead of a hard failure.
    2. Character state continuity: a character at least min_visible_opacity
       visible at the end of shot k and at frame 0 of shot k+1 must not
       jump more than max_char_jump_px.

    Every shot also runs verify_shot_stagecraft (spec validation and a
    backdrop/character-state report).

    Knobs (all three are parameters; the CLI exposes them, and the timeline
    may carry a 'continuity' block):
      require_seamless_handoff (default True)
      max_char_jump_px         (default 18.0 canvas px)
      min_visible_opacity      (default 0.20, the opacity at/above which a
                                character counts as visible in a cut)
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
        rep = verify_shot_stagecraft(s_data, min_visible_opacity=min_visible_opacity)
        shot_reports.append(rep)
        errors.extend(rep["errors"])

    handoffs = []
    unverified = []
    for i in range(len(shot_reports) - 1):
        curr_rep = shot_reports[i]
        next_rep = shot_reports[i + 1]
        end_bg = curr_rep["end_backdrop"]
        next_start_bg = next_rep["start_backdrop"]
        bg_equal = (end_bg == next_start_bg)
        # A shot that declares no backdrop identity cannot be compared. That is
        # NOT the same as "the backdrop matched" — reporting it as PASS would
        # make an unchecked cut look verified.
        bg_comparable = (end_bg is not None and next_start_bg is not None)

        # Character discontinuity across the cut (only characters visible in both shots)
        char_jumps = []
        end_st = curr_rep.get("end_states", {})
        start_st = next_rep.get("start_states", {})
        for cid, st1 in start_st.items():
            if st1["opacity"] < min_visible_opacity:
                continue
            if cid in end_st and end_st[cid]["opacity"] >= min_visible_opacity:
                st0 = end_st[cid]
                jump = math.hypot(st1["x"] - st0["x"], st1["y"] - st0["y"])
                if jump > max_char_jump_px:
                    char_jumps.append(
                        f"{cid} teleports by {jump:.1f}px across cut ({curr_rep['shot_id']} end=({st0['x']}, {st0['y']}) -> "
                        f"{next_rep['shot_id']} start=({st1['x']}, {st1['y']}))"
                    )

        if not bg_comparable:
            bg_status = "NO_BACKDROP_DECLARED"
        elif bg_equal:
            bg_status = None
        elif require_seamless_handoff:
            bg_status = "HARD_CUT_JUMP"
        else:
            bg_status = "BACKDROP_WARN"

        if char_jumps:
            status = "CHAR_JUMP"
        elif bg_status is not None:
            status = bg_status
        else:
            status = "PASS"

        handoffs.append({
            "from_shot": curr_rep["shot_id"],
            "to_shot": next_rep["shot_id"],
            "end_backdrop": end_bg,
            "next_start_backdrop": next_start_bg,
            "char_jumps": char_jumps,
            "status": status,
            "backdrop_equal": bg_equal,
            "backdrop_comparable": bg_comparable,
            "require_seamless_handoff": require_seamless_handoff,
        })
        if bg_status == "HARD_CUT_JUMP":
            errors.append(
                f"Hard-cut backdrop jump between '{curr_rep['shot_id']}' (ends on {end_bg!r}) "
                f"and '{next_rep['shot_id']}' (starts on {next_start_bg!r})."
            )
        elif bg_status == "NO_BACKDROP_DECLARED":
            # Not a failure — an honest "not checked": the cut's backdrop
            # continuity was NOT verified because no identity was declared.
            unverified.append(
                f"{curr_rep['shot_id']} -> {next_rep['shot_id']}: no backdrop identity "
                f"declared (layer field 'backdrop'), so the cut's backdrop continuity "
                f"was NOT verified")
        for cj in char_jumps:
            errors.append(f"Cross-shot character discontinuity ({curr_rep['shot_id']} -> {next_rep['shot_id']}): {cj}")

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "unverified": unverified,
        "shots": shot_reports,
        "handoffs": handoffs,
    }
