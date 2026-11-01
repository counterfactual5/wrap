"""Spec validation (stdlib only). `python schema.py [spec]` exits 1 on any error."""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BLENDS = {"multiply", "screen", "normal"}
LAYER_TYPES = {"code", "ai", "text", "hud", "card"}
DRAWS = {
    "grid", "bar", "dots", "geodesic", "ripples",
    "trampoline", "gravity-well", "light-deflection", "spacetime-waves",
    "blackhole-hero", "time-dilation", "light-cone-tilt", "spaghettification",
    "tunnel-hero", "wavefunction-hero"
}
METRICS = {"changed_pixel_ratio", "red_pixel_ratio", "edge_key_purity", "subject_motion_ratio", "accent_color_ratio"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


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
        if L.get("type") == "ai":
            if not L.get("asset"):
                e(f"{lid}: ai layer needs 'asset'")
            if L.get("blend") not in BLENDS:
                e(f"{lid}: blend is required, one of {sorted(BLENDS)}")
            if not HEX.match(L.get("keyColor", "")):
                e(f"{lid}: keyColor must be #rrggbb")
        if L.get("type") == "code":
            if L.get("draw") not in DRAWS:
                e(f"{lid}: draw must be one of {sorted(DRAWS)}")
            if L.get("draw") == "bar" and not HEX.match(L.get("color", "")):
                e(f"{lid}: bar needs color #rrggbb")
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
