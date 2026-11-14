"""Remotion timeline math, shared by the audio mastering chain.

The contract is read from the installed renderer (remotion 4.0.529,
node_modules): remotion/Shot.tsx maps trim -> trimBefore/trimAfter =
Math.round(trim * fps); html5-video.js wraps a looping clip in <Loop
duration = window / playbackRate>; video/get-current-time.js seeks the media
to trimBefore + local * playbackRate. Every consumer must land on the same
media frames the renderer picks, or picture and sound drift apart (the S4
AV-sync gate allows <= 100 ms).
"""
import math


def _js_round(x):
    """JavaScript Math.round parity (half away from zero). Remotion converts
    trim seconds to media frames with Math.round(trim * fps); Python's round()
    is half-to-even, so a trim landing exactly on .5 frames would send the
    mastered audio and the fallback picture to different frames than the
    renderer picks."""
    return math.floor(x + 0.5)


def video_timeline(layer, fps):
    """A video layer's Remotion timeline (remotion 4.0.529, html5-video.js +
    video/get-current-time.js), shared by the native-audio mastering chain:

      trimBefore/trimAfter = Math.round(trim * fps)   (remotion/Shot.tsx)
      media time at composition frame i = (trimBefore + local_i * rate) / fps
        local_i = i, wrapped by <Loop> into the window
        [trimBefore, trimAfter] (or the whole clip) when loop is on.

    Returns (t0_sec, t1_sec_or_None, rate) with t0/t1 already frame-rounded,
    so every consumer lands on the same media frames as the renderer."""
    trim = layer.get("trim")
    t0 = _js_round(trim[0] * fps) / fps if trim else 0.0
    t1 = _js_round(trim[1] * fps) / fps if trim else None
    rate = layer.get("playbackRate")
    return t0, t1, float(rate) if rate else 1.0


def atempo_chain(rate):
    """ffmpeg atempo factors covering any positive rate (one atempo instance
    accepts [0.5, 100]). Remotion time-warps a clip's native audio by the
    same playbackRate as its picture; the mastering chain must warp with it
    or the track drifts out of sync by (1 - 1/rate) * t over the shot."""
    r = float(rate)
    factors = []
    while r < 0.5 - 1e-9:
        factors.append(0.5)
        r /= 0.5
    while r > 100.0 + 1e-9:
        factors.append(100.0)
        r /= 100.0
    factors.append(r)
    parts = []
    for f in factors:
        parts.append("atempo=" + f"{f:.6f}".rstrip("0").rstrip("."))
    return parts
