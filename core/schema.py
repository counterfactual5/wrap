"""Spec validation (stdlib only). `python core/schema.py [spec]` exits 1 on any error."""
import json
import os
import re
import sys

# core/ lives one level below the repo root: ENGINE_ROOT is the engine itself.
# ROOT is the project root (spec/, assets/, build/, manifest.json) — the engine
# by default (development/tests), or POSTER_ROOT when set (external projects).
ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ROOT = os.environ.get("POSTER_ROOT") or ENGINE_ROOT
# This module is both a library (imported as core.schema) and a script
# (`python core/schema.py spec.json`), so the package import needs the root
# on sys.path in the script case.
if __package__ in (None, ""):
    sys.path.insert(0, ENGINE_ROOT)
from core import models

BLENDS = {"multiply", "screen", "normal"}
LAYER_TYPES = {"code", "ai", "video", "text", "hud", "card", "component"}
# Aspect ratios the video backend accepts.
VIDEO_RATIOS = {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
# The values the renderer dispatches on (remotion/layers.tsx). "scanline" was
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
# capability disappears without a word. `tests/test_contract_weakening.py`
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


def zoom_supported(layer):
    """Whether the renderer actually interpolates motion.zoom for this layer.

    The renderer does it in PreparedLayer (ai layers, and the code layers
    drawn as grid / dots, which S2 prepares as an image) and in
    VideoLayerComp. CodeLayerComp reads only motion.pan, and the text / hud /
    card layers scale through the anim "scale" channel — promising a
    motion.zoom there would promise something the renderer never draws.
    """
    ltype = layer.get("type")
    if ltype in ("ai", "video"):
        return True
    return ltype == "code" and layer.get("draw") in ZOOMABLE_CODE_DRAWS

# Generic choreography channels: every layer may declare keyframes per channel.
# Expression lives in the spec, not in component code — the renderer only
# interpolates. A keyframe is [frame, value] or [frame, value, ease]; ease
# applies to the segment ENDING at that keyframe.
ANIM_CHANNELS = {"x", "y", "scale", "opacity", "rotate", "depth"}
ANIM_EASES = {"linear", "in", "out", "inout", "snap", "overshoot", "step"}
GAIT_MODES = {"puppet", "walk", "float", "shudder"}
SPRING_CHANNELS = {"x", "y", "scale", "rotate"}
LAYER_ROLES = {"humanoid", "quadruped", "mech", "prop"}


def validate_spring(spring, lid, errs):
    e = errs.append
    if not isinstance(spring, dict) or not spring:
        e(f"{lid}: spring must be a non-empty object (omega, zeta, coupling, channel, driverChannel, maxAccel)")
        return
    for k, (lo, hi) in (
        ("omega", (1.0, 120.0)),
        ("zeta", (0.01, 2.0)),
        ("coupling", (-5.0, 5.0)),
        ("maxAccel", (1.0, 100000.0)),
    ):
        if k in spring:
            v = spring[k]
            if not (isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi):
                e(f"{lid}: spring.{k} must be a number in [{lo}, {hi}] (got {v!r})")
    for ch_key in ("channel", "driverChannel"):
        if ch_key in spring and spring[ch_key] is not None:
            if spring[ch_key] not in SPRING_CHANNELS:
                e(f"{lid}: spring.{ch_key} must be one of {sorted(SPRING_CHANNELS)} (got {spring[ch_key]!r})")


def validate_combat(combat, layer_ids, errs):
    e = errs.append
    if not isinstance(combat, dict) or not combat:
        e("combat must be a non-empty object with attacker, weapon, target")
        return
    for req_k in ("attacker", "weapon", "target"):
        val = combat.get(req_k)
        if not isinstance(val, str) or val not in layer_ids:
            e(f"combat.{req_k} {val!r} must reference an existing layer id in this shot")
    if "tolerance" in combat:
        tol = combat["tolerance"]
        if not (isinstance(tol, (int, float)) and not isinstance(tol, bool) and tol >= 0):
            e(f"combat.tolerance must be a non-negative number (got {tol!r})")
    if "tipOffset" in combat:
        to = combat["tipOffset"]
        if not (isinstance(to, list) and len(to) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in to)):
            e("combat.tipOffset must be [dx, dy] numbers in source pixels")
    if "refWidth" in combat:
        rw = combat["refWidth"]
        if not (isinstance(rw, (int, float)) and not isinstance(rw, bool) and rw > 0):
            e("combat.refWidth must be a positive number")


def validate_gait(gait, lid, errs):
    e = errs.append
    if not isinstance(gait, dict) or not gait:
        e(f"{lid}: gait must be a non-empty object with mode in {sorted(GAIT_MODES)}")
        return
    mode = gait.get("mode")
    if mode not in GAIT_MODES:
        e(f"{lid}: gait.mode must be one of {sorted(GAIT_MODES)} (got {mode!r})")
    for k in ("freq", "bob", "sway"):
        if k in gait:
            v = gait[k]
            if not (isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0):
                e(f"{lid}: gait.{k} must be a non-negative number (got {v!r})")
            elif k == "freq" and v <= 0:
                e(f"{lid}: gait.freq must be > 0 (got {v!r})")
    rng = gait.get("range")
    if rng is not None:
        if not (isinstance(rng, list) and len(rng) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) for v in rng)
                and 0 <= rng[0] < rng[1]):
            e(f"{lid}: gait.range must be [startFrame, endFrame] ints with 0 <= startFrame < endFrame")


def _norm_tokens(s):
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", str(s).lower()))


def validate_captions_against_voiceover(items, voiceover_text, lid, errs):
    """Ensure captions items share a single source of truth with audio.voiceover."""
    if not isinstance(items, list) or not items:
        return
    vo_str = (voiceover_text or "").strip()
    if not vo_str or os.path.exists(vo_str) or vo_str.endswith((".wav", ".mp3", ".aac", ".m4a")):
        return
    vo_norm = _norm_tokens(vo_str)
    if len(vo_norm) < 4:
        return
    vo_bigrams = {vo_norm[i:i + 2] for i in range(len(vo_norm) - 1)}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        it_text = item.get("text", "")
        it_norm = _norm_tokens(it_text)
        if len(it_norm) < 3:
            continue
        if it_norm in vo_norm:
            continue
        it_bigrams = [it_norm[i:i + 2] for i in range(len(it_norm) - 1)]
        overlap = sum(1 for bg in it_bigrams if bg in vo_bigrams) / max(1, len(it_bigrams))
        if overlap < 0.60:
            errs.append(
                f"{lid}: captions item[{idx}] {it_text!r} does not match audio.voiceover "
                f"(bigram overlap {overlap:.0%} < 60%) — subtitles and voiceover must share a "
                f"single source of truth (run 'python3 pipeline.py sync-audio --spec <spec>' "
                f"to auto-populate captions from audio.voiceover)"
            )
            break


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
            if ch == "depth" and not (0 <= v <= 1):
                e(f"{lid}: anim.depth values must be within [0, 1] (0=pressed against silk screen, 1=pulled back with penumbra blur)")
                break
            if len(kf) == 3 and kf[2] not in ANIM_EASES:
                e(f"{lid}: anim.{ch} ease must be one of {sorted(ANIM_EASES)}")
                break
            if prev_f is not None and f <= prev_f:
                e(f"{lid}: anim.{ch} frames must be strictly increasing")
                break
            prev_f = f


# Names that end up in file paths (shot id, layer id, asset name) must not be
# able to walk out of the directory they belong to.
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def valid_name(value):
    return isinstance(value, str) and bool(NAME_RE.fullmatch(value))


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
    for L in spec["layers"]:
        lid = L.get("id", "?")
        if lid in ids:
            e(f"duplicate layer id {lid}")
        ids.add(lid)
        # Layer ids and asset names reach file paths (build/prepared/{shot}/
        # {layer}.png, assets/{asset}.png). The same rule as the shot id.
        if not valid_name(lid):
            e(f"{lid}: layer id must be a letters/digits/._- string — it names "
              f"a file under build/prepared/")
        asset = L.get("asset")
        if asset is not None and not valid_name(asset):
            e(f"{lid}: asset must be a letters/digits/._- string (got {asset!r}) "
              f"— it names a file under assets/")
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
        cr = L.get("clipRect")
        if cr is not None:
            if not (isinstance(cr, list) and len(cr) == 4 and all(isinstance(v, int) for v in cr)):
                e(f"{lid}: clipRect must be [x,y,w,h] ints")
            elif cr[2] <= 0 or cr[3] <= 0:
                e(f"{lid}: clipRect w/h must be positive")
        piv = L.get("pivot")
        if piv is not None:
            if not (isinstance(piv, list) and len(piv) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in piv)):
                e(f"{lid}: pivot must be [x,y] numbers")
        jt = L.get("joint")
        if jt is not None:
            if L.get("type") != "ai":
                e(f"{lid}: joint is only supported on 'ai' layers")
            elif not (isinstance(jt, list) and len(jt) == 2
                      and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in jt)):
                e(f"{lid}: joint must be [sx,sy] source-image pixel numbers")
            elif not (L.get("cutout") or L.get("fit") == "contain"):
                e(f"{lid}: joint needs cutout:true or fit:'contain' (the pivot "
                  f"conversion assumes aspect-preserving contain scaling)")
        sock = L.get("socket")
        if sock is not None:
            if L.get("type") != "ai":
                e(f"{lid}: socket is only supported on 'ai' layers")
            elif not (isinstance(sock, list) and len(sock) == 2
                      and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in sock)):
                e(f"{lid}: socket must be [sx,sy] source-image pixel numbers")
            elif not L.get("parent"):
                e(f"{lid}: socket requires 'parent' pointing to the receiving body layer")
        ps = L.get("partScale")
        if ps is not None:
            if L.get("type") != "ai":
                e(f"{lid}: partScale is only supported on 'ai' layers")
            elif isinstance(ps, bool) or not isinstance(ps, (int, float)) or ps <= 0:
                e(f"{lid}: partScale must be a positive number")
        kit = L.get("kit")
        if kit is not None:
            if L.get("type") != "ai":
                e(f"{lid}: kit is only supported on 'ai' layers")
            elif not isinstance(kit, dict):
                e(f"{lid}: kit must be an object")
            else:
                ktype = kit.get("type")
                if ktype is not None and ktype not in ("torso", "limb", "weapon", "turret", "head", "wing"):
                    e(f"{lid}: kit.type must be one of ('torso', 'limb', 'weapon', 'turret', 'head', 'wing')")
                pa = kit.get("parent_asset")
                if pa is not None and not valid_name(pa):
                    e(f"{lid}: kit.parent_asset must be a valid asset name")
                for k_pos in ("socket", "joint"):
                    if kit.get(k_pos) is not None:
                        val = kit[k_pos]
                        if not (isinstance(val, list) and len(val) == 2
                                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in val)):
                            e(f"{lid}: kit.{k_pos} must be [x,y] numbers")
                for k_rad in ("socket_radius", "joint_radius"):
                    if kit.get(k_rad) is not None:
                        rval = kit[k_rad]
                        if isinstance(rval, bool) or not isinstance(rval, (int, float)) or rval <= 0:
                            e(f"{lid}: kit.{k_rad} must be a positive number")
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
            cutout = L.get("cutout")
            if cutout is not None and not isinstance(cutout, bool):
                e(f"{lid}: cutout must be a boolean (true or false), got {cutout!r}")
            csim = L.get("cutoutSimilarity")
            if csim is not None and not (
                    isinstance(csim, (int, float)) and not isinstance(csim, bool) and 0 < csim <= 1):
                e(f"{lid}: cutoutSimilarity must be a number in (0, 1], got {csim!r}")
            cblend = L.get("cutoutBlend")
            if cblend is not None and not (
                    isinstance(cblend, (int, float)) and not isinstance(cblend, bool) and 0 <= cblend <= 1):
                e(f"{lid}: cutoutBlend must be a number in [0, 1], got {cblend!r}")
            poses = L.get("poses")
            if poses is not None:
                if not isinstance(poses, list) or len(poses) == 0:
                    e(f"{lid}: poses must be a non-empty list of {{frame, asset}} objects")
                else:
                    prev_pf = None
                    for pidx, pose in enumerate(poses):
                        if not isinstance(pose, dict):
                            e(f"{lid}: poses[{pidx}] must be an object")
                            break
                        pf = pose.get("frame")
                        pa = pose.get("asset")
                        if not isinstance(pf, int) or isinstance(pf, bool) or pf < 0:
                            e(f"{lid}: poses[{pidx}].frame must be a non-negative int")
                            break
                        if prev_pf is not None and pf <= prev_pf:
                            e(f"{lid}: poses frames must be strictly increasing")
                            break
                        prev_pf = pf
                        if not valid_name(pa):
                            e(f"{lid}: poses[{pidx}].asset must be a valid asset name (got {pa!r})")
                            break
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
            rate = L.get("playbackRate")
            if rate is not None and not (isinstance(rate, (int, float))
                                         and not isinstance(rate, bool) and rate > 0):
                # The renderer feeds this into the clip's timeline
                # (unloopedTimeInSeconds * playbackRate * fps), so a wrong
                # type makes the whole shot's timing wrong.
                e(f"{lid}: video playbackRate must be a positive number (got {rate!r})")
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
            if L.get("draw") == "captions" and isinstance(L.get("params"), dict):
                vo = (spec.get("audio") or {}).get("voiceover") if isinstance(spec.get("audio"), dict) else None
                if isinstance(vo, str) and vo.strip():
                    validate_captions_against_voiceover(L["params"].get("items"), vo, lid, errs)
        if "anim" in L:
            validate_anim(L["anim"], lid, errs)
        if "gait" in L and L["gait"] is not None:
            validate_gait(L["gait"], lid, errs)
        if "spring" in L and L["spring"] is not None:
            validate_spring(L["spring"], lid, errs)
        if "role" in L and L["role"] is not None:
            if L["role"] not in LAYER_ROLES:
                e(f"{lid}: role must be one of {sorted(LAYER_ROLES)} (got {L['role']!r})")
        if "shadowColor" in L and L["shadowColor"] is not None:
            if not HEX.match(str(L["shadowColor"])):
                e(f"{lid}: shadowColor must be #rrggbb (got {L['shadowColor']!r})")
        if "translucent" in L and L["translucent"] is not None:
            if not isinstance(L["translucent"], bool):
                e(f"{lid}: translucent must be a boolean (got {L['translucent']!r})")
        if "controlRod" in L and L["controlRod"] is not None:
            if not isinstance(L["controlRod"], bool):
                e(f"{lid}: controlRod must be a boolean (got {L['controlRod']!r})")
        if "rodAnchor" in L and L["rodAnchor"] is not None:
            ra = L["rodAnchor"]
            if not (isinstance(ra, list) and len(ra) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in ra)):
                e(f"{lid}: rodAnchor must be [rx, ry] normalized floats in [0, 1]")
        if "rodAnchors" in L and L["rodAnchors"] is not None:
            ras = L["rodAnchors"]
            if not (isinstance(ras, list) and len(ras) >= 1 and all(
                    isinstance(pt, list) and len(pt) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in pt)
                    for pt in ras)):
                e(f"{lid}: rodAnchors must be a non-empty list of [rx, ry] normalized floats in [0, 1]")
        if L.get("type") == "text":
            if not L.get("text"):
                e(f"{lid}: text layer needs 'text'")
            size = L.get("fontSize")
            if size is not None and not (isinstance(size, (int, float))
                                         and not isinstance(size, bool) and size > 0):
                e(f"{lid}: text fontSize must be a positive number (got {size!r})")
            weight = L.get("fontWeight")
            if weight is not None and not (isinstance(weight, (str, int, float))
                                           and not isinstance(weight, bool)):
                e(f"{lid}: text fontWeight must be a string or number (got {weight!r})")
            if "subtext" in L and not isinstance(L["subtext"], str):
                e(f"{lid}: text subtext must be a string")
        if L.get("type") == "hud":
            if not L.get("hudType"):
                e(f"{lid}: hud layer needs 'hudType'")
            elif L["hudType"] not in HUD_TYPES:
                # The renderer dispatches on this value; an unknown one draws
                # nothing while the spec still claims the layer exists.
                e(f"{lid}: hudType must be one of {sorted(HUD_TYPES)} "
                  f"(got {L['hudType']!r})")
        if L.get("type") == "card":
            if not L.get("cardType"):
                e(f"{lid}: card layer needs 'cardType'")
            elif L["cardType"] not in CARD_TYPES:
                e(f"{lid}: cardType must be one of {sorted(CARD_TYPES)} "
                  f"(got {L['cardType']!r})")
            details = L.get("details")
            if details is not None and not (
                    isinstance(details, list)
                    and all(isinstance(d, dict) for d in details)):
                e(f"{lid}: card details must be a list of objects")
        if L.get("type") == "component":
            comp_name = L.get("component")
            if not comp_name:
                e(f"{lid}: component layer needs 'component' (registered in remotion/custom/index.tsx)")
            elif not valid_name(comp_name):
                e(f"{lid}: component must be a valid identifier string (got {comp_name!r})")
            if "props" in L and not isinstance(L["props"], dict):
                e(f"{lid}: component props must be an object")
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
            if z is not None and not zoom_supported(L):
                # The validator must not refuse what the renderer can do — and
                # must not promise what it cannot. The message names the layer
                # kind so the author knows which channel to use instead.
                if L.get("type") == "code":
                    e(f"{lid}: zoom is not supported on code layers drawn as "
                      f"{L.get('draw')!r} — only {sorted(ZOOMABLE_CODE_DRAWS)} "
                      f"go through the prepared-image path; use the anim "
                      f"'scale' channel for the other draws")
                else:
                    e(f"{lid}: zoom is not supported on {L.get('type')} layers "
                      f"— scale them with the anim 'scale' channel instead")
            if p is not None and L.get("draw") != "bar":
                e(f"{lid}: pan only supported on 'bar' layers")
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
    punches = spec.get("punches")
    if punches is not None:
        if not (isinstance(punches, list) and all(isinstance(v, int) and 0 <= v for v in punches)):
            e("punches must be a list of non-negative frame ints")
    if "vibe_grade" in spec and not isinstance(spec["vibe_grade"], bool):
        e("vibe_grade must be a boolean")
    if "vibe" in spec and not isinstance(spec["vibe"], bool):
        # The renderer opts out with a strict `vibe !== false`, so a
        # non-boolean value would run the opposite of what the author wrote.
        e("vibe must be a boolean")
    if "ambient" in spec and not isinstance(spec["ambient"], bool):
        e("ambient must be a boolean")
    if "audio" in spec and spec["audio"] is not None:
        if not isinstance(spec["audio"], dict):
            e("audio must be a dictionary")
        elif "ambient" in spec["audio"] and not isinstance(spec["audio"]["ambient"], bool):
            e("audio.ambient must be a boolean")
    if "combat" in spec and spec["combat"] is not None:
        validate_combat(spec["combat"], ids, errs)
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
    validate_puppet_topology(spec, errs)
    return errs


def validate_puppet_topology(spec, errs):
    """Anatomy Topology Contract: Ensure articulated humanoid puppets do not suffer from
    missing limbs (the single-leg or single-arm amputee defects).

    If an articulated puppet root layer has child limbs (parent points to it):
    - If lower limbs ('leg') are articulated, at least 2 legs (e.g. leg-front and leg-back)
      must be declared to form a complete standing/stepping pair.
    - If upper limbs ('arm' / 'weapon') are articulated on a humanoid character
      (declared via `role: "humanoid"` or having a bipedal leg pair), at least 2 arms
      must be declared to form a complete pair.
    """
    layers = spec.get("layers", [])
    layer_map = {L.get("id"): L for L in layers if L.get("id")}
    parents_with_limbs = set()
    for L in layers:
        par_id = L.get("parent")
        if par_id and (L.get("kit") or L.get("joint") or "leg" in L.get("id", "").lower() or "arm" in L.get("id", "").lower()):
            parents_with_limbs.add(par_id)

    for pid in parents_with_limbs:
        par_layer = layer_map.get(pid, {})
        is_humanoid = par_layer.get("role") == "humanoid"
        child_legs = [
            L for L in layers
            if L.get("parent") == pid and ("leg" in L.get("id", "").lower() or "leg" in str(L.get("asset", "")).lower())
        ]
        if len(child_legs) == 1:
            errs.append(
                f"{pid}: humanoid puppet has only 1 leg ({child_legs[0]['id']}) declared — "
                f"missing rear leg causes one-legged amputee visual defect. "
                f"Declare both front and back legs (e.g. '{pid}-leg-front' and '{pid}-leg-back')."
            )

        child_arms = [
            L for L in layers
            if L.get("parent") == pid and ("arm" in L.get("id", "").lower() or "arm" in str(L.get("asset", "")).lower())
        ]
        if len(child_arms) == 1 and (len(child_legs) >= 2 or is_humanoid):
            errs.append(
                f"{pid}: humanoid puppet has only 1 arm ({child_arms[0]['id']}) declared — "
                f"missing rear counterbalance arm causes one-armed amputee visual defect. "
                f"Declare both front and back arms (e.g. '{pid}-arm-front' and '{pid}-arm-back')."
            )


PIVOT_JOINT_TOL = 8  # canvas px a hand-written pivot may stray from its joint


def resolve_joints(spec):
    """Derive a layer's canvas `pivot` from where its joint sits in the source image.

    A hinge pivot is a point on the *source picture* (a wrist, an elbow, a turret
    ring), but the renderer needs canvas pixels after S2's aspect-preserving
    `contain` scale + pad. Guessing that conversion by eye is what detached a hand
    from its sleeve, so two sources are honoured and cross-checked:

    * the layer's own `joint: [sx, sy]` (source pixels) -> pivot is computed;
    * the `joint` recorded in the manifest by `split-sprite` -> a hand-written
      `pivot` that disagrees by more than PIVOT_JOINT_TOL px is rejected.

    Layers whose asset is not registered yet are left alone (S2 reports that).
    """
    from core import manifest
    from core.png import read_size
    from core.rig import source_to_canvas_pivot

    for L in spec.get("layers", []):
        if L.get("type") != "ai":
            continue
        kit = L.get("kit")
        if isinstance(kit, dict):
            if kit.get("joint") is not None and L.get("joint") is None:
                L["joint"] = kit["joint"]
            if kit.get("socket") is not None and L.get("socket") is None:
                L["socket"] = kit["socket"]
            if (kit.get("socket_radius") is not None and kit.get("joint_radius") is not None
                    and L.get("partScale") is None):
                L["partScale"] = round(float(kit["socket_radius"]) / float(kit["joint_radius"]), 4)
            if kit.get("type") in ("limb", "weapon", "turret", "wing") and L.get("snap") is None:
                L["snap"] = "socket"
        if not L.get("rect"):
            continue
        own = L.get("joint")
        row = manifest.verified("assets", L.get("asset"))
        if not row:
            continue
        joint = own if own is not None else row.get("joint")
        if joint is None:
            continue
        try:
            sw, sh = read_size(os.path.join(ROOT, row["path"]))
        except (OSError, ValueError):
            continue
        want = source_to_canvas_pivot(sw, sh, L["rect"], joint[0], joint[1])
        sock = L.get("socket")
        par_id = L.get("parent")
        if par_id:
            par = next((p for p in spec.get("layers", []) if p.get("id") == par_id), None)
            if par and par.get("rect") and par.get("asset"):
                par_row = manifest.verified("assets", par.get("asset"))
                if sock is None and L.get("snap") == "socket" and par_row:
                    sock = par_row.get("socket")
                if sock is not None and par_row:
                    from core.rig import snap_socket_joint
                    try:
                        psw, psh = read_size(os.path.join(ROOT, par_row["path"]))
                        use_part_scale = (
                            L.get("snap") == "socket"
                            or L.get("partScale") is not None
                            or L["rect"] == par["rect"]
                        )
                        snap = snap_socket_joint(
                            [psw, psh], par["rect"], sock, [sw, sh], joint,
                            part_scale=L.get("partScale", 1.0),
                            child_rect_size=None if use_part_scale else L["rect"][2:],
                        )
                        L["rect"] = snap["rect"]
                        want = snap["pivot"]
                    except (OSError, ValueError):
                        pass
        have = L.get("pivot")
        if have is not None and max(abs(have[0] - want[0]), abs(have[1] - want[1])) > PIVOT_JOINT_TOL:
            raise ValueError(
                f"invalid spec:\n  {L['id']}: pivot {have} is {max(abs(have[0]-want[0]), abs(have[1]-want[1])):.0f}px "
                f"away from its joint {list(joint)} (canvas {want}) — rotating about it "
                f"detaches the part from the body. Delete 'pivot' and declare "
                f"'joint': {list(joint)} instead.")
        L["pivot"] = want
    return spec


def load_spec(path=None):
    path = path or os.path.join(ROOT, "tests", "fixtures", "shot-01.poster.json")
    with open(path) as f:
        spec = json.load(f)
    errs = validate(spec)
    if errs:
        raise ValueError("invalid spec:\n  " + "\n  ".join(errs))
    return resolve_joints(spec)


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


def carry_state_from(prev_spec, new_shot_id):
    """Carry the end-of-shot state of `prev_spec` into a new shot skeleton for `new_shot_id`.

    Solves cross-shot state continuity (#4): each persistent layer keeps its
    final keyframe values (x, y, scale, opacity, rotate) at frame 0 of the next
    shot, and a multi-pose `ai` layer starts from its last active pose asset.
    """
    import copy
    out = copy.deepcopy(prev_spec)
    out["id"] = new_shot_id
    out.pop("punches", None)
    new_layers = []
    for L in out.get("layers", []):
        # Drop per-shot ephemeral subtitle captions items so the new shot starts clean
        if L.get("type") == "code" and L.get("draw") == "captions":
            L = copy.deepcopy(L)
            if isinstance(L.get("params"), dict):
                L["params"]["items"] = []
        # If an ai layer had poses, carry its final pose asset as the default asset at frame 0
        if L.get("type") == "ai" and isinstance(L.get("poses"), list) and L["poses"]:
            last_pose = L["poses"][-1]
            if isinstance(last_pose, dict) and last_pose.get("asset"):
                L["asset"] = last_pose["asset"]
                L["poses"] = [{"frame": 0, "asset": last_pose["asset"]}]
        # If the layer had anim channels, seed frame 0 with the final keyframe value
        if isinstance(L.get("anim"), dict):
            carried_anim = {}
            for ch, kfs in L["anim"].items():
                if isinstance(kfs, list) and kfs:
                    last_val = kfs[-1][1]
                    carried_anim[ch] = [[0, last_val], [out.get("durationInFrames", 150) - 1, last_val]]
            if carried_anim:
                L["anim"] = carried_anim
        if isinstance(L.get("gait"), dict):
            if L["gait"].get("mode") == "shudder":
                L.pop("gait", None)
            else:
                L["gait"].pop("range", None)
        new_layers.append(L)
    out["layers"] = new_layers
    return out


if __name__ == "__main__":
    try:
        s = load_spec(sys.argv[1] if len(sys.argv) > 1 else None)
    except ValueError as ex:
        print(ex)
        sys.exit(1)
    print(f"spec ok: {s['id']} {s['canvas']['w']}x{s['canvas']['h']} {s['durationInFrames']}f, "
          f"{len(s['layers'])} layers, {len(s['gates'])} gates")
