"""Timeline validation: the multi-shot sequence file."""
import os
import tempfile

from .naming import valid_name

VALID_BEATS = {"hook", "development", "climax", "resolution", "transition", "intro", "outro"}

# The keys a timeline may declare. Every one of them is read by the
# pipeline (core/assembly/timeline.py, pipeline.py) — an unknown key is a
# typo the author believes is doing something, so it is refused rather than
# ignored. Same rule the `continuity` block already follows.
TIMELINE_KEYS = {"id", "shots", "bgm", "bgmUnderVoice", "allow_black",
                  "allow_bgm_override_silent", "continuity"}
# The keys a shot entry may declare.
SHOT_KEYS = {"spec", "beat", "reason"}


def _allowed_roots():
    """Where a shot's spec may live: the project, or a scratch directory.

    The project root is where a relative shot path resolves. The OS scratch
    directory is where a timeline that was assembled OUTSIDE the project
    keeps its shot specs — the CLI accepts such a timeline
    (`verify-continuity --timeline <file>`), so its shots must be readable
    too.
    """
    from core.runtime.config import ROOT
    roots = [os.path.realpath(ROOT)]
    scratch = tempfile.gettempdir()
    if scratch:
        roots.append(os.path.realpath(scratch))
    return roots


def _shot_path_problem(rel):
    """Why a shot's spec path cannot be used, or None when it is fine.

    The path is joined onto the project root by the pipeline
    (`os.path.join(ROOT, rel)`), so it must stay inside the project: no
    `..` segments, and an absolute path only when it points inside the
    project (or a scratch directory).
    """
    if not isinstance(rel, str) or not rel.strip():
        return "must be a non-empty string"
    parts = rel.replace("\\", "/").split("/")
    if ".." in parts:
        return "must not walk out of the project ('..' is refused)"
    if os.path.isabs(rel):
        target = os.path.realpath(rel)
        for root in _allowed_roots():
            try:
                if os.path.commonpath([root, target]) == root:
                    return None
            except ValueError:  # different drives (Windows)
                continue
        return ("must point inside the project (or a scratch directory) — "
                "an absolute path outside it is refused")
    return None


def validate_timeline(timeline):
    errs = []
    e = errs.append
    if not isinstance(timeline, dict):
        return ["timeline must be a dictionary"]
    for key in sorted(set(timeline) - TIMELINE_KEYS):
        e(f"timeline: unknown key {key!r}")
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
            else:
                problem = _shot_path_problem(s)
                if problem:
                    e(f"shot {idx}: spec path {problem} (got {s!r})")
        elif isinstance(s, dict):
            for key in sorted(set(s) - SHOT_KEYS):
                e(f"shot {idx}: unknown key {key!r}")
            if not s.get("spec"):
                e(f"shot {idx}: dict needs 'spec' path")
            else:
                problem = _shot_path_problem(s.get("spec"))
                if problem:
                    e(f"shot {idx}: 'spec' {problem} (got {s.get('spec')!r})")
            beat = s.get("beat")
            if beat is not None and beat not in VALID_BEATS:
                e(f"shot {idx}: invalid beat '{beat}', must be one of {sorted(VALID_BEATS)}")
            reason = s.get("reason")
            if reason is not None and not str(reason).strip():
                e(f"shot {idx}: 'reason' cannot be empty")
        else:
            e(f"shot {idx}: must be a spec path string or dict with spec/beat/reason")
    return errs
