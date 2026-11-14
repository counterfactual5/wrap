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
        e("timeline 'bgm' must be a string (preset name or audio file path)")
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
