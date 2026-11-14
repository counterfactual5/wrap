"""The vocabulary of the spec contract: the value sets a spec may use.

These sets ARE the contract. The contract tests (tests/contract/) read them
live from this defining module and compare them against the renderer and
the docs. Narrowing one of them is a
silent narrowing of the contract, so see the note on DRAWS before touching one.
"""
import re

BLENDS = {"multiply", "screen", "normal"}
LAYER_TYPES = {"ai", "video", "component"}
# Aspect ratios the video backend accepts.
VIDEO_RATIOS = {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
# The procedural draw vocabulary is REMOVED (zero-template migration). The set
# is kept, empty and loud, as the migration boundary: nothing may be added back
# without a renderer branch and a contract test. A spec that names a draw is
# refused with a migration error by core/spec/layers.py — never silently
# ignored, and never re-creating a built-in visual.
DRAWS = set()
METRICS = {"changed_pixel_ratio", "red_pixel_ratio", "edge_key_purity", "subject_motion_ratio", "accent_color_ratio"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# Generic choreography channels: every layer may declare keyframes per channel.
# Expression lives in the spec, not in component code — the renderer only
# interpolates. A keyframe is [frame, value] or [frame, value, ease]; ease
# applies to the segment ENDING at that keyframe.
ANIM_CHANNELS = {"x", "y", "scale", "opacity", "rotate", "flipX"}
ANIM_EASES = {"linear", "in", "out", "inout", "snap", "overshoot", "step"}
SPRING_CHANNELS = {"x", "y", "scale", "rotate"}
LAYER_ROLES = {"humanoid", "quadruped", "mech", "prop", "backdrop"}

# Names that end up in file paths (shot id, layer id, asset name) must not be
# able to walk out of the directory they belong to.
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
