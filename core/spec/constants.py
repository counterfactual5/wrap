"""The vocabulary of the spec contract: the value sets a spec may use.

These sets ARE the contract. The contract tests (tests/contract/) read them
live from this defining module and compare them against the renderer and
the docs. Narrowing one of them is a
silent narrowing of the contract, so see the note on DRAWS before touching one.
"""
import re

BLENDS = {"multiply", "screen", "normal"}
LAYER_TYPES = {"code", "ai", "video", "text", "hud", "card", "component"}
# Aspect ratios the video backend accepts.
VIDEO_RATIOS = {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
# The values the renderer dispatches on (remotion/layers/). "scanline" was
# listed in the docs and the TS type but had no branch in the renderer, so a
# spec using it drew nothing — it is not in the enum.
HUD_TYPES = {"badge", "telemetry", "equalizer", "progress"}
CARD_TYPES = {"capsule", "formula", "quote"}
# The draws an author may write in a spec.
#
# The renderer may not lead the contract: a draw the renderer draws but the
# contract does not accept means the contract was narrowed — and narrowing
# it is invisible: every check that iterates FROM this list shrinks with it
# (measured: removing one entry left the whole suite green), so the
# capability disappears without a word. `tests/contract/test_contract_weakening.py`
# guards that direction. Fix a narrowing by adding the draw (the renderer
# already draws it) or by removing the branch from the renderer; never by
# shrinking this list without saying so.
DRAWS = {
    "grid", "bar", "dots", "geodesic", "ripples",
    "trampoline", "gravity-well", "light-deflection", "spacetime-waves",
    "blackhole-hero", "time-dilation", "light-cone-tilt", "spaghettification",
    "tunnel-hero", "wavefunction-hero", "field", "path", "captions"
}
METRICS = {"changed_pixel_ratio", "red_pixel_ratio", "edge_key_purity", "subject_motion_ratio", "accent_color_ratio"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# The code layers S2 prepares as an image (grid, dots). The renderer draws
# them through PreparedLayer — the same component that interpolates
# motion.zoom for ai layers — so a zoom on them is a camera push-in.
ZOOMABLE_CODE_DRAWS = {"grid", "dots"}

# Generic choreography channels: every layer may declare keyframes per channel.
# Expression lives in the spec, not in component code — the renderer only
# interpolates. A keyframe is [frame, value] or [frame, value, ease]; ease
# applies to the segment ENDING at that keyframe.
ANIM_CHANNELS = {"x", "y", "scale", "opacity", "rotate", "depth", "flipX"}
ANIM_EASES = {"linear", "in", "out", "inout", "snap", "overshoot", "step"}
GAIT_MODES = {"puppet", "walk", "float", "shudder"}
SPRING_CHANNELS = {"x", "y", "scale", "rotate"}
LAYER_ROLES = {"humanoid", "quadruped", "mech", "prop", "backdrop"}

# Names that end up in file paths (shot id, layer id, asset name) must not be
# able to walk out of the directory they belong to.
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
