"""Timeline validation: the multi-shot sequence file."""
from .naming import valid_name

VALID_BEATS = {"hook", "development", "climax", "resolution", "transition", "intro", "outro"}


def validate_timeline(timeline):
    errs = []
    e = errs.append
    if not isinstance(timeline, dict):
        return ["timeline must be a dictionary"]
    if not timeline.get("id"):
        e("timeline missing 'id'")
    elif not valid_name(timeline["id"]):
        # The timeline id names build/gates_full_{id}.json.
        e(f"timeline id must be a letters/digits/._- string (got {timeline['id']!r})")
    if "bgm" in timeline and timeline["bgm"] is not None and not isinstance(timeline["bgm"], str):
        e("timeline 'bgm' must be a string (audio file path)")
    if "bgmUnderVoice" in timeline and timeline["bgmUnderVoice"] is not None:
        buv = timeline["bgmUnderVoice"]
        if isinstance(buv, bool) or not isinstance(buv, (int, float)) or not (0.0 <= buv <= 1.0):
            e("timeline 'bgmUnderVoice' must be a number in [0, 1]")
    if "allow_black" in timeline and not isinstance(timeline["allow_black"], bool):
        e("timeline 'allow_black' must be a boolean")
    if "allow_bgm_override_silent" in timeline and not isinstance(timeline["allow_bgm_override_silent"], bool):
        e("timeline 'allow_bgm_override_silent' must be a boolean")
    continuity = timeline.get("continuity")
    if continuity is not None:
        if not isinstance(continuity, dict):
            e("timeline 'continuity' must be an object")
        else:
            for key in sorted(set(continuity) - {"max_char_jump_px", "require_seamless_handoff", "min_visible_opacity"}):
                e(f"timeline continuity: unknown key {key!r}")
            jump = continuity.get("max_char_jump_px")
            if jump is not None:
                if isinstance(jump, bool) or not isinstance(jump, (int, float)) or jump < 0:
                    e("timeline continuity 'max_char_jump_px' must be a non-negative number")
            req = continuity.get("require_seamless_handoff")
            if req is not None and not isinstance(req, bool):
                e("timeline continuity 'require_seamless_handoff' must be a boolean")
            op = continuity.get("min_visible_opacity")
            if op is not None:
                if isinstance(op, bool) or not isinstance(op, (int, float)) or not (0.0 <= op < 1.0):
                    e("timeline continuity 'min_visible_opacity' must be a number in [0, 1)")
    shots = timeline.get("shots")
    if not isinstance(shots, list) or len(shots) == 0:
        e("timeline 'shots' must be a non-empty list")
        return errs
    for idx, s in enumerate(shots):
        if isinstance(s, str):
            if not s.strip():
                e(f"shot {idx}: spec path cannot be empty")
        elif isinstance(s, dict):
            if not s.get("spec"):
                e(f"shot {idx}: dict needs 'spec' path")
            beat = s.get("beat")
            if beat is not None and beat not in VALID_BEATS:
                e(f"shot {idx}: invalid beat '{beat}', must be one of {sorted(VALID_BEATS)}")
            reason = s.get("reason")
            if reason is not None and not str(reason).strip():
                e(f"shot {idx}: 'reason' cannot be empty")
        else:
            e(f"shot {idx}: must be a spec path string or dict with spec/beat/reason")
    return errs
