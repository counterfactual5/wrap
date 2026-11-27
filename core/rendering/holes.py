"""The hole guard: a rendered frame must carry the picture its spec declares.

Remotion paints a video layer from a `<video>` element, and that element can
fail to deliver the frame it was asked for. The element then stays empty, the
layer leaves a transparent gap, and the encoder composites the gap over the
canvas background - a black hole in the delivered film, with the soundtrack
still playing under it.

Measured on a real H3 clip (180 frames, one video layer covering the canvas):
the first render left gaps at frames 89 and 90, and the SAME spec re-rendered
produced none. The defect is a race in the renderer, not a property of the
spec, so re-running the pipeline is not a fix - only a guard is.

The guard reads the rendered frame sequence and compares each frame's mean
alpha against what the spec says must be visible there:

    measured_i  = mean alpha over the canvas (1.0 = fully opaque)
    required_i  = max over video layers of (opacity at frame i x rect area)

Alpha compositing guarantees the result is at least as opaque as its most
opaque contributor, so `required` is a true lower bound: when the video layer
painted, the frame reaches it; when the element came up empty, the frame
falls far below it and the frame is a hole.

Layers that do not fill their rect are excluded, because a lower bound they
cannot meet would report a hole that is not one:
  - fit="contain" letterboxes the clip inside its rect (the padded band is
    transparent), so the rect is not the area the layer covers;
  - a layer whose opacity the spec fades below OPAQUE_FLOOR contributes
    proportionally less alpha than its full rect.

The guard reports the holes; it does not decide what to do about them. S3
re-renders while holes remain (the race is not reproducible), and fails
loudly when they persist.
"""
import os
import subprocess

from core.rendering.frames import sequence_color_types
from core.rig.kinematics import eval_channel
from core.runtime.timeouts import LOCAL_TOOL_TIMEOUT

# A frame whose mean |dY| against the master exceeds this is not the master's
# picture. Measured on a correct render of the same shot: every frame stayed
# at or below 1.5 (the encoder's own quantization at crf 18), while the
# format-switch defect showed 35-61 on the frames it corrupted.
MASTER_DELTA_LIMIT = 6.0

# The colour type of a PNG that carries an alpha channel (6 = RGBA) and the
# one that does not (2 = RGB).
COLOR_TYPE_RGBA = 6

# A frame may fall this far below its requirement before it is called a hole.
# It absorbs the renderer's own quantization and the components that draw on
# top of the video layer (a caption's glyphs, a panel's background).
HOLE_TOLERANCE = 0.05

# A video layer below this opacity is not required to cover its rect: the spec
# is fading it out, and a fading layer's alpha falls with its opacity.
OPAQUE_FLOOR = 0.05

# How many times S3 renders a shot before it gives up on the hole guard. The
# race is not reproducible - a re-render of the same spec usually comes back
# clean - so a small number of attempts is enough, and a shot that still has
# holes after them is a defect the guard must report, not hide.
RENDER_ATTEMPTS = 3


def _layer_opacity(layer, frame, layer_map):
    """The layer's effective opacity at a frame: its own times its ancestors'.

    Mirrors the transform chain in remotion/Shot.tsx (LayerNode multiplies the
    opacity of the layer and every ancestor), so the guard expects what the
    renderer actually drew.
    """
    opacity = 1.0
    chain = []
    visited = set()
    cur = layer
    while cur is not None and cur.get("id") not in visited:
        visited.add(cur.get("id"))
        chain.append(cur)
        parent_id = cur.get("parent")
        cur = layer_map.get(parent_id) if parent_id else None
    for item in reversed(chain):
        anim = item.get("anim") or {}
        opacity *= eval_channel(anim.get("opacity"), frame, 1.0)
    return opacity


def required_opacity(spec):
    """Per frame, the least opacity the spec promises: a list over the frames.

    The value is the strongest lower bound the spec's video layers give -
    the largest (opacity x rect area) among the layers that are visible at
    that frame. 0.0 means the spec promises nothing opaque there.
    """
    canvas = spec.get("canvas") or {}
    cw = canvas.get("w") or 1920
    ch = canvas.get("h") or 1080
    canvas_area = float(cw * ch) or 1.0
    frames = int(spec.get("durationInFrames") or 0)
    layers = spec.get("layers") or []
    layer_map = {L.get("id"): L for L in layers}

    req = [0.0] * frames
    for layer in layers:
        if layer.get("type") != "video":
            continue
        # A contained clip is letterboxed inside its rect; the rect is then
        # not the area the layer covers, so it cannot promise that area.
        if (layer.get("fit") or "cover") == "contain":
            continue
        rect = layer.get("rect")
        if not rect or len(rect) < 4:
            continue
        area = float(rect[2] * rect[3]) / canvas_area
        for frame in range(frames):
            opacity = _layer_opacity(layer, frame, layer_map)
            if opacity <= OPAQUE_FLOOR:
                continue
            value = opacity * area
            if value > req[frame]:
                req[frame] = value
    return req


def measured_opacity(frames_dir, fps=30):
    """Per frame, the mean alpha over the canvas: a list over the frames.

    One pass over the PNG sequence. The frames are forced to RGBA first, so
    a frame the renderer wrote as RGB (no alpha) reads as fully opaque
    instead of failing the extraction.
    """
    cmd = [
        "ffmpeg", "-v", "error", "-nostats",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "%05d.png"),
        "-vf", "format=rgba,alphaextract,signalstats,metadata=print:file=-",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=LOCAL_TOOL_TIMEOUT)
    if proc.returncode != 0:
        raise RuntimeError(
            f"frame alpha measurement failed ({' '.join(cmd)}): {proc.stderr.strip()}")
    values = []
    for line in proc.stdout.splitlines():
        if line.startswith("lavfi.signalstats.YAVG="):
            values.append(float(line.split("=", 1)[1]) / 255.0)
    return values


def alpha_basis(frames_dir):
    """Whether these frames can show a transparent hole at all.

    "measured"  - the frames carry an alpha channel, so the mean alpha of a
                  frame is a real measurement and a frame that fell below the
                  spec's promise really did fall below it.

    "no_alpha"  - the frames carry NO alpha channel (PNG colour type 2).
                  Then no frame CAN hold a transparent hole, and that is a
                  STRUCTURAL argument, not a measurement: "mean alpha =
                  1.0000" is what the reading gives by construction, and
                  quoting it as evidence would be a check that cannot fail.

    The two are reported apart on purpose. A hole the renderer painted as
    opaque BLACK is invisible to this guard in either case - the whole-film
    black gate is what covers that.
    """
    types = sequence_color_types(frames_dir)
    has_alpha = COLOR_TYPE_RGBA in types
    return {
        "basis": "measured" if has_alpha else "no_alpha",
        "color_types": sorted(types),
        "can_show_transparent_hole": has_alpha,
        "note": ("the frames carry an alpha channel, so the mean alpha is a measurement"
                 if has_alpha else
                 "the frames carry no alpha channel (PNG colour type 2), so no frame can hold "
                 "a transparent hole - a structural argument; a hole painted as opaque black "
                 "would not be visible here (the whole-film black gate covers that)"),
    }


def find_holes(spec, frames_dir, fps=30, tolerance=HOLE_TOLERANCE):
    """The frames the renderer left empty: a list of {"frame", "measured"}.

    "frame" is the composition frame index (0-based), the same index the
    layer keyframes use. An empty list means the sequence carries everything
    the spec promised.
    """
    required = required_opacity(spec)
    measured = measured_opacity(frames_dir, fps)
    if len(measured) != len(required):
        raise RuntimeError(
            f"the rendered sequence has {len(measured)} frames but the spec "
            f"declares {len(required)} - the hole guard cannot compare them")
    holes = []
    for frame, (req, got) in enumerate(zip(required, measured)):
        if req <= 0.0:
            continue
        if got < req - tolerance:
            holes.append({"frame": frame, "measured": round(got, 4),
                          "required": round(req, 4)})
    return holes


def format_holes(holes, shot_id):
    """The holes as one readable line for a log or an error message."""
    if not holes:
        return f"{shot_id}: no holes"
    listed = ", ".join(str(h["frame"]) for h in holes)
    return (f"{shot_id}: {len(holes)} frame(s) the renderer left empty "
            f"(composition frames {listed})")


def describe_holes(spec, frames_dir, shot_id, fps=30):
    """The guard's verdict and the basis it stands on, as one line.

    The basis matters as much as the verdict: a reader who only sees "no
    holes" cannot tell a measurement from an argument that cannot fail.
    """
    basis = alpha_basis(frames_dir)
    holes = find_holes(spec, frames_dir, fps)
    verdict = format_holes(holes, shot_id)
    if basis["basis"] == "measured":
        cov = measured_opacity(frames_dir, fps)
        low = f"; min mean alpha {min(cov):.4f}" if cov else ""
        return f"{verdict} (measured: {basis['note']}{low})"
    return f"{verdict} (not a measurement: {basis['note']})"
