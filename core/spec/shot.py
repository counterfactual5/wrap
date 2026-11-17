"""Shot-level validation: the spec as a whole.

`validate` is the entry point every caller uses — it checks the shot's own
fields, then each layer through `core.spec.layers`, then the relationships
between layers (parents, combat) and the gates.
"""
from .channels import validate_combat
from .constants import METRICS, HEX
from .layers import validate_layer
from .naming import valid_name


def validate(spec):
    errs = []
    e = errs.append
    for k in ("id", "canvas", "fps", "durationInFrames", "layers", "gates"):
        if k not in spec:
            e(f"missing '{k}'")
    if errs:
        return errs
    # The shot id names directories under build/ and public/ (prepared clips
    # are staged there), so it must not be able to walk out of them.
    if not valid_name(spec["id"]):
        e(f"id must be a letters/digits/._- string (got {spec['id']!r}); it "
          f"names directories under build/ and public/")
    W, H = spec["canvas"].get("w"), spec["canvas"].get("h")
    if not (isinstance(W, int) and isinstance(H, int) and W > 0 and H > 0):
        e("canvas.w/h must be positive ints")
    if not (isinstance(spec["fps"], int) and spec["fps"] > 0):
        e("fps must be a positive int")
    if not (isinstance(spec["durationInFrames"], int) and spec["durationInFrames"] > 1):
        e("durationInFrames must be an int > 1")
    ids, zs = set(), set()
    layer_by_id = {x.get("id"): x for x in spec["layers"] if isinstance(x, dict) and x.get("id")}
    ai_asset_set = {x.get("asset") for x in spec["layers"] if isinstance(x, dict) and x.get("type") == "ai" and x.get("asset")}

    for L in spec["layers"]:
        validate_layer(L, spec, ids, zs, layer_by_id, ai_asset_set, errs)
    # Validate parent references across layers (no missing parent, no self/cycle).
    parent_map = {L.get("id"): L.get("parent") for L in spec["layers"] if L.get("parent") is not None}
    for lid, par in parent_map.items():
        if not isinstance(par, str) or par not in ids:
            e(f"{lid}: parent {par!r} must reference an existing layer id in this shot")
        elif par == lid:
            e(f"{lid}: parent cannot reference itself")
        else:
            seen = {lid}
            cur = par
            while cur in parent_map:
                if cur in seen:
                    e(f"{lid}: cyclic parent chain involving {cur!r}")
                    break
                seen.add(cur)
                cur = parent_map[cur]
    if "frame_freeze" in spec and not isinstance(spec["frame_freeze"], bool):
        e("frame_freeze must be a boolean")
    for key in ("punch", "punches", "vibe", "vibe_grade", "ambient", "captions", "events", "palette", "plate"):
        if key in spec:
            e(f"migration required: removed root field {key!r}; media/component fields belong on layers and nonvisual timing belongs in tracks")
    # At most one video layer's own track may own the soundtrack. If two are
    # unmuted the encoder would silently keep the first and drop the other.
    unmuted_video = [L.get("id") for L in spec["layers"] if L.get("type") == "video" and L.get("muted") is False]
    if len(unmuted_video) > 1:
        e(f"only one video layer may have muted:false; got {unmuted_video}")
    if unmuted_video and isinstance(spec.get("audio"), dict) and spec["audio"].get("bgm"):
        e(f"audio conflict: {unmuted_video} ask for a clip's native track while audio.bgm asks for background music — pick one")
    validate_tracks(spec.get("tracks", {}), errs)
    if "audio" in spec and spec["audio"] is not None:
        if not isinstance(spec["audio"], dict):
            e("audio must be a dictionary")
        else:
            for key in spec["audio"]:
                if key not in {"voiceover", "voice", "rate", "bgm", "bgmOffset", "bgmUnderVoice"}:
                    e(f"audio.{key} is not a recognized audio field")
            if "ambient" in spec["audio"]:
                e("migration required: audio.ambient removed; provide an explicit audio file or omit audio for silence")
            if "bgmOffset" in spec["audio"]:
                bo = spec["audio"]["bgmOffset"]
                if isinstance(bo, bool) or not isinstance(bo, (int, float)) or bo < 0:
                    e(f"audio.bgmOffset must be a non-negative number in seconds (got {bo!r})")
            if "bgmUnderVoice" in spec["audio"] and spec["audio"]["bgmUnderVoice"] is not None:
                buv = spec["audio"]["bgmUnderVoice"]
                if isinstance(buv, bool) or not isinstance(buv, (int, float)) or not (0.0 <= buv <= 1.0):
                    e(f"audio.bgmUnderVoice must be a number in [0, 1] (got {buv!r})")
            if "voiceover" in spec["audio"] and spec["audio"]["voiceover"] is not None:
                if not isinstance(spec["audio"]["voiceover"], str):
                    e("audio.voiceover must be a string")
            if "bgm" in spec["audio"] and spec["audio"]["bgm"] is not None:
                if not isinstance(spec["audio"]["bgm"], str):
                    e("audio.bgm must be a string (audio file path)")
    if "combat" in spec and spec["combat"] is not None:
        validate_combat(spec["combat"], ids, errs)
    gids = set()
    for g in spec["gates"]:
        if g.get("id") in gids:
            e(f"duplicate gate id {g.get('id')}")
        gids.add(g.get("id"))
        if g.get("metric") not in METRICS:
            e(f"gate {g.get('id')}: unknown metric {g.get('metric')}")
        if g.get("metric") in ("accent_color_ratio", "red_pixel_ratio") and not HEX.fullmatch(str(g.get("color", ""))):
            e(f"gate {g.get('id')}: color must be explicit #rrggbb")
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


def gate_of(spec, metric):
    return next((g for g in spec["gates"] if g["metric"] == metric), None)


def validate_tracks(tracks, errs):
    if not isinstance(tracks, dict):
        errs.append("tracks must be an object")
        return

    def _valid_frame(item):
        frame = item.get("frame")
        if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0:
            return None
        return frame

    for kind, items in tracks.items():
        if not isinstance(kind, str) or not kind:
            errs.append("tracks: keys must be non-empty strings")
            continue
        if not isinstance(items, list):
            errs.append(f"tracks.{kind} must be a list")
            continue
        prev = -1
        for item in items:
            if not isinstance(item, dict):
                errs.append(f"tracks.{kind} item must be an object")
                continue
            frame = _valid_frame(item)
            if kind == "captions":
                ordering = "strictly increasing"
            else:
                ordering = "non-decreasing"
            if frame is None:
                errs.append(f"tracks.{kind}.frame must be a non-negative integer")
            elif kind == "captions" and frame <= prev and prev >= 0:
                errs.append(f"tracks.{kind}.frame must be {ordering} non-negative integers")
            elif frame < prev:
                errs.append(f"tracks.{kind}.frame must be {ordering} non-negative integers")
            else:
                prev = frame
            end = item.get("end_frame")
            if end is not None and (not isinstance(end, int) or isinstance(end, bool) or not isinstance(frame, int) or end <= frame):
                errs.append(f"tracks.{kind}.end_frame must be greater than frame")
            if kind == "captions":
                if not isinstance(item.get("text"), str) or not item["text"].strip():
                    errs.append("tracks.captions.text must be non-empty")
                if set(item) - {"frame", "end_frame", "text"}:
                    errs.append("migration required: tracks.captions is nonvisual; move styling to component props")
            if kind != "captions":
                # Arbitrary named timing tracks are allowed for project-defined
                # beats. They do not carry visual semantics; components read them.
                pass
