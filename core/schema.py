"""Spec validation (stdlib only). `python core/schema.py [spec]` exits 1 on any error."""
import json
import os
import re
import sys

# core/ lives one level below the repo root: ROOT is the project root, so
# spec/, assets/, build/ and manifest.json resolve the same way from anywhere.
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
# This module is both a library (imported as core.schema) and a script
# (`python core/schema.py spec.json`), so the package import needs the root
# on sys.path in the script case.
if __package__ in (None, ""):
    sys.path.insert(0, ROOT)
from core import models

BLENDS = {"multiply", "screen", "normal"}
LAYER_TYPES = {"code", "ai", "video", "text", "hud", "card"}
# Aspect ratios the video backend accepts.
VIDEO_RATIOS = {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
DRAWS = {
    "grid", "bar", "dots", "geodesic", "ripples",
    "trampoline", "gravity-well", "light-deflection", "spacetime-waves",
    "blackhole-hero", "time-dilation", "light-cone-tilt", "spaghettification",
    "tunnel-hero", "wavefunction-hero", "field", "path", "captions"
}
METRICS = {"changed_pixel_ratio", "red_pixel_ratio", "edge_key_purity", "subject_motion_ratio", "accent_color_ratio"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# Generic choreography channels: every layer may declare keyframes per channel.
# Expression lives in the spec, not in component code — the renderer only
# interpolates. A keyframe is [frame, value] or [frame, value, ease]; ease
# applies to the segment ENDING at that keyframe.
ANIM_CHANNELS = {"x", "y", "scale", "opacity", "rotate"}
ANIM_EASES = {"linear", "in", "out", "inout"}


def validate_anim(anim, lid, errs):
    e = errs.append
    if not isinstance(anim, dict) or not anim:
        e(f"{lid}: anim must be a non-empty object of channel -> keyframes")
        return
    for ch, kfs in anim.items():
        if ch not in ANIM_CHANNELS:
            e(f"{lid}: anim channel '{ch}' must be one of {sorted(ANIM_CHANNELS)}")
            continue
        if not (isinstance(kfs, list) and len(kfs) >= 2):
            e(f"{lid}: anim.{ch} needs >= 2 keyframes")
            continue
        prev_f = None
        for kf in kfs:
            if not (isinstance(kf, list) and len(kf) in (2, 3)):
                e(f"{lid}: anim.{ch} keyframe must be [frame, value(, ease)]")
                break
            f, v = kf[0], kf[1]
            if not isinstance(f, int) or f < 0:
                e(f"{lid}: anim.{ch} frame must be a non-negative int")
                break
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                e(f"{lid}: anim.{ch} value must be a number")
                break
            if ch == "opacity" and not (0 <= v <= 1):
                e(f"{lid}: anim.opacity values must be within [0, 1]")
                break
            if len(kf) == 3 and kf[2] not in ANIM_EASES:
                e(f"{lid}: anim.{ch} ease must be one of {sorted(ANIM_EASES)}")
                break
            if prev_f is not None and f <= prev_f:
                e(f"{lid}: anim.{ch} frames must be strictly increasing")
                break
            prev_f = f


def hex_rgb(s):
    return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))


def validate(spec):
    errs = []
    e = errs.append
    for k in ("id", "canvas", "fps", "durationInFrames", "layers", "gates"):
        if k not in spec:
            e(f"missing '{k}'")
    if errs:
        return errs
    W, H = spec["canvas"].get("w"), spec["canvas"].get("h")
    if not (isinstance(W, int) and isinstance(H, int) and W > 0 and H > 0):
        e("canvas.w/h must be positive ints")
    if not (isinstance(spec["fps"], int) and spec["fps"] > 0):
        e("fps must be a positive int")
    if not (isinstance(spec["durationInFrames"], int) and spec["durationInFrames"] > 1):
        e("durationInFrames must be an int > 1")
    ids, zs = set(), set()
    for L in spec["layers"]:
        lid = L.get("id", "?")
        if lid in ids:
            e(f"duplicate layer id {lid}")
        ids.add(lid)
        if L.get("z") in zs:
            e(f"{lid}: duplicate z {L.get('z')}")
        zs.add(L.get("z"))
        if L.get("type") not in LAYER_TYPES:
            e(f"{lid}: type must be one of {sorted(LAYER_TYPES)}")
        r = L.get("rect")
        if not (isinstance(r, list) and len(r) == 4 and all(isinstance(v, int) for v in r)):
            e(f"{lid}: rect must be [x,y,w,h] ints")
        elif r[2] <= 0 or r[3] <= 0:
            e(f"{lid}: rect w/h must be positive")
        if L.get("type") in ("ai", "video"):
            # plate is the card-chrome switch (false = full bleed). The
            # renderer compares it strictly against false, so a non-boolean
            # value would render the OPPOSITE of what the author wrote —
            # "plate": "no" would draw the chrome the author asked to drop.
            plate = L.get("plate")
            if plate is not None and not isinstance(plate, bool):
                e(f"{lid}: plate must be a boolean (true or false), got {plate!r}")
        if L.get("type") == "ai":
            if not L.get("asset"):
                e(f"{lid}: ai layer needs 'asset'")
            if L.get("blend") not in BLENDS:
                e(f"{lid}: blend is required, one of {sorted(BLENDS)}")
            if not HEX.match(L.get("keyColor", "")):
                e(f"{lid}: keyColor must be #rrggbb")
            p = L.get("prompt")
            if p is not None and not isinstance(p, str):
                e(f"{lid}: ai prompt must be a string")
            src = L.get("input_asset")
            if src is not None:
                # Image-to-image: the source must be a frozen local asset, so
                # S1 can upload it and hand the backend a reachable URL.
                # The value names a manifest asset (not a file path), so it
                # carries no extension.
                if not isinstance(src, str) or not src.strip():
                    e(f"{lid}: ai input_asset must be a non-empty string")
                elif "/" in src or src.endswith(".png"):
                    e(f"{lid}: ai input_asset must name a manifest asset "
                      f"(got {src!r})")
        if L.get("type") == "video":
            # A video layer references a frozen video asset (mp4). It has no
            # key color: edge keying is a still-image concept, so the purity
            # gate does not apply to it.
            if not L.get("asset"):
                e(f"{lid}: video layer needs 'asset'")
            if L.get("fit") and L["fit"] not in ("cover", "contain"):
                e(f"{lid}: video fit must be 'cover' or 'contain'")
            trim = L.get("trim")
            if trim is not None:
                if not (isinstance(trim, list) and len(trim) == 2
                        and all(isinstance(v, (int, float)) for v in trim)
                        and trim[0] >= 0 and trim[1] > trim[0]):
                    e(f"{lid}: video trim must be [startSec, endSec] with endSec > startSec >= 0")
            if L.get("loop") is not None and not isinstance(L.get("loop"), bool):
                e(f"{lid}: video loop must be a boolean")
            if L.get("muted") is not None and not isinstance(L.get("muted"), bool):
                e(f"{lid}: video muted must be a boolean")
            if "sourceFps" in L:
                # S2 re-encodes every clip to the SHOT's frame rate, so the
                # renderer always sees the source at the canvas fps. A
                # sourceFps here would only mis-convert trim's seconds.
                e(f"{lid}: sourceFps is not accepted — clips are re-encoded to "
                  f"the shot's frame rate, so trim is always read at that rate")
            # Generation parameters are validated against the backend catalog
            # (core/models.py) so a typo or an out-of-range duration is caught
            # here — before a paid call, not after it.
            model = L.get("model")
            if model is not None:
                if model not in models.VIDEO_MODELS:
                    e(f"{lid}: video model {model!r} is unknown; "
                      f"choose one of {sorted(models.VIDEO_MODELS)}")
                else:
                    res = L.get("resolution")
                    if res is not None and res not in models.video_resolutions(model):
                        e(f"{lid}: {model} resolution must be one of "
                          f"{list(models.video_resolutions(model))}, got {res!r}")
            dur = L.get("duration")
            if dur is not None:
                if not isinstance(dur, int) or dur <= 0:
                    e(f"{lid}: video duration must be a positive int (seconds)")
                elif model in models.VIDEO_MODELS:
                    lo, hi = models.video_duration_range(model)
                    if not (lo <= dur <= hi):
                        e(f"{lid}: {model} duration must be {lo}-{hi}s, got {dur}")
            ratio = L.get("ratio")
            if ratio is not None and ratio not in VIDEO_RATIOS:
                e(f"{lid}: video ratio must be one of {list(VIDEO_RATIOS)}, got {ratio!r}")
        if L.get("type") == "code":
            if L.get("draw") not in DRAWS:
                e(f"{lid}: draw must be one of {sorted(DRAWS)}")
            if L.get("draw") == "bar" and not HEX.match(L.get("color", "")):
                e(f"{lid}: bar needs color #rrggbb")
            if "params" in L and not isinstance(L["params"], dict):
                e(f"{lid}: params must be an object (primitive parameters)")
        if "anim" in L:
            validate_anim(L["anim"], lid, errs)
        if L.get("type") == "text":
            if not L.get("text"):
                e(f"{lid}: text layer needs 'text'")
        if L.get("type") == "hud":
            if not L.get("hudType"):
                e(f"{lid}: hud layer needs 'hudType'")
        if L.get("type") == "card":
            if not L.get("cardType"):
                e(f"{lid}: card layer needs 'cardType'")
        m = L.get("motion")
        if m is not None:
            if m.get("type") != "geometric":
                e(f"{lid}: motion.type must be 'geometric' (numbers, not prose)")
            z = m.get("zoom")
            if z is not None and not (len(z) == 2 and all(isinstance(v, (int, float)) for v in z) and z[0] >= 1 and z[1] >= 1):
                e(f"{lid}: zoom must be [from,to] numbers >= 1")
            p = m.get("pan")
            if p is not None and not (len(p) == 2 and all(isinstance(v, (int, float)) for v in p)):
                e(f"{lid}: pan must be [xFrom,xTo] numbers")
            if z is not None and L.get("type") != "ai":
                e(f"{lid}: zoom only supported on ai layers")
            if p is not None and L.get("draw") != "bar":
                e(f"{lid}: pan only supported on 'bar' layers")
    punches = spec.get("punches")
    if punches is not None:
        if not (isinstance(punches, list) and all(isinstance(v, int) and 0 <= v for v in punches)):
            e("punches must be a list of non-negative frame ints")
    if "vibe_grade" in spec and not isinstance(spec["vibe_grade"], bool):
        e("vibe_grade must be a boolean")
    if "audio" in spec and spec["audio"] is not None:
        if not isinstance(spec["audio"], dict):
            e("audio must be a dictionary")
    gids = set()
    for g in spec["gates"]:
        if g.get("id") in gids:
            e(f"duplicate gate id {g.get('id')}")
        gids.add(g.get("id"))
        if g.get("metric") not in METRICS:
            e(f"gate {g.get('id')}: unknown metric {g.get('metric')}")
        lo, hi = g.get("lo"), g.get("hi")
        if lo is None and hi is None:
            e(f"gate {g.get('id')}: needs lo and/or hi")
        if lo is not None and hi is not None and lo > hi:
            e(f"gate {g.get('id')}: lo > hi")
        # region: optional [y0, y1] canvas band excluded from motion metrics,
        # so a panning foreground cannot mask a static subject.
        r = g.get("region")
        if r is not None and not (isinstance(r, list) and len(r) == 2
                                  and all(isinstance(v, int) for v in r) and 0 <= r[0] < r[1] <= spec["canvas"]["h"]):
            e(f"gate {g.get('id')}: region must be [y0,y1] ints within canvas height")
    return errs


def load_spec(path=None):
    path = path or os.path.join(ROOT, "spec", "shot-01.poster.json")
    with open(path) as f:
        spec = json.load(f)
    errs = validate(spec)
    if errs:
        raise ValueError("invalid spec:\n  " + "\n  ".join(errs))
    return spec


VALID_BEATS = {"hook", "development", "climax", "resolution", "transition", "intro", "outro"}


def validate_timeline(timeline):
    errs = []
    e = errs.append
    if not isinstance(timeline, dict):
        return ["timeline must be a dictionary"]
    if not timeline.get("id"):
        e("timeline missing 'id'")
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


def gate_of(spec, metric):
    return next((g for g in spec["gates"] if g["metric"] == metric), None)


if __name__ == "__main__":
    try:
        s = load_spec(sys.argv[1] if len(sys.argv) > 1 else None)
    except ValueError as ex:
        print(ex)
        sys.exit(1)
    print(f"spec ok: {s['id']} {s['canvas']['w']}x{s['canvas']['h']} {s['durationInFrames']}f, "
          f"{len(s['layers'])} layers, {len(s['gates'])} gates")
