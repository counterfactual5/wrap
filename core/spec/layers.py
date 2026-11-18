"""Layer-level validation: every field a layer may declare.

The order of the checks is the order the errors come out in. The messages are
the contract with the author, so the sequence is part of the behaviour, not an
implementation detail — the per-type blocks below are called from
`validate_layer` in exactly the order the fields appear in a layer.
"""
from core.generation import models

from .channels import (
    validate_anim,
    validate_spring,
)
from . import constants
from .constants import (
    BLENDS,
    HEX,
    LAYER_ROLES,
    VIDEO_RATIOS,
)
from .naming import valid_name


def zoom_supported(layer):
    """Whether the renderer interpolates motion.zoom for this layer.

    Only ai and video layers do — a camera move on an image or clip.
    Component layers scale through the anim "scale" channel instead.
    """
    return layer.get("type") in ("ai", "video")


def _check_manifest_asset_name(lid, value, field_label, kind_label, errs):
    """A manifest asset name is a BARE name: no path, no `.png` suffix.

    The ledger keys assets by that bare name (`assets/<name>.png` on disk),
    so a name carrying a path or an extension can never be found in it and
    would only fail much later, in S1/S2, as "no verified asset in manifest".
    """
    e = errs.append
    if not isinstance(value, str) or not value.strip():
        e(f"{lid}: {field_label} must be a non-empty string")
        return False
    if "/" in value or value.endswith(".png") or not valid_name(value):
        kind = f"{kind_label} " if kind_label else ""
        e(f"{lid}: {kind}{field_label} must name a manifest asset (got {value!r})")
        return False
    return True


def _check_img_ref(lid, ref_val, field_label, kind_label, layer_by_id, errs):
    e = errs.append
    if not _check_manifest_asset_name(lid, ref_val, field_label, kind_label, errs):
        return
    if ref_val in layer_by_id:
        # The name may be an ai layer's id — S1 uploads that layer's own
        # image as the source. Any other layer kind has no image to hand
        # over, so a component/video layer is refused here rather than
        # silently producing a broken request.
        target_l = layer_by_id[ref_val]
        if target_l.get("type") != "ai":
            e(f"{lid}: {field_label} must reference an ai layer or a frozen image asset")


def _validate_ai_layer(L, lid, layer_by_id, errs):
    e = errs.append
    if not L.get("asset"):
        e(f"{lid}: ai layer needs 'asset'")
    if L.get("blend") not in BLENDS:
        e(f"{lid}: blend is required, one of {sorted(BLENDS)}")
    if not HEX.fullmatch(str(L.get("keyColor", ""))):
        e(f"{lid}: keyColor must be #rrggbb")
    p = L.get("prompt")
    if p is not None and not isinstance(p, str):
        e(f"{lid}: ai prompt must be a string")
    cutout = L.get("cutout")
    if cutout is not None and not isinstance(cutout, bool):
        e(f"{lid}: cutout must be a boolean (true or false), got {cutout!r}")
    if cutout is True:
        csim_must_be_declared = L.get("cutoutSimilarity")
        if csim_must_be_declared is None:
            e(f"{lid}: cutout:true requires an explicit 'cutoutSimilarity' — the engine "
              f"ships no default key-matching ratio (measure it against your key color)")
        cblend_must_be_declared = L.get("cutoutBlend")
        if cblend_must_be_declared is None:
            e(f"{lid}: cutout:true requires an explicit 'cutoutBlend' — the engine "
              f"ships no default blend width (start from a rendered proof, not a guess)")
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
                if not _check_manifest_asset_name(lid, pa, f"poses[{pidx}].asset", "", errs):
                    break
    src = L.get("input_asset")
    if src is not None:
        # Image-to-image: the source must be a frozen local asset, another
        # ai layer, or a static code layer (grid/dots), so S1 can upload it
        # and hand the backend a reachable URL.
        _check_img_ref(lid, src, "input_asset", "ai", layer_by_id, errs)
    for rk, max_cnt in (("reference_images", 16), ("reference_assets", 16)):
        if rk in L and L[rk] is not None:
            rlist = L[rk]
            if not isinstance(rlist, list) or not (1 <= len(rlist) <= max_cnt):
                e(f"{lid}: ai {rk} must be a list of 1..{max_cnt} asset/layer names")
            else:
                for item in rlist:
                    _check_img_ref(lid, item, rk, "ai", layer_by_id, errs)


def _validate_video_layer(L, lid, layer_by_id, errs, generation_model=None):
    e = errs.append
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
    # (core/generation/models.py) so a typo or an out-of-range duration is caught
    # here — before a paid call, not after it.
    # Model availability belongs to generation, not frozen-asset validation.
    eff_model = generation_model
    dur = L.get("duration")
    if dur is not None:
        if not isinstance(dur, int) or isinstance(dur, bool) or dur <= 0:
            e(f"{lid}: video duration must be a positive int (seconds)")
        elif eff_model:
            lo, hi = models.video_duration_range(eff_model)
            if not (lo <= dur <= hi):
                e(f"{lid}: {eff_model} duration must be {lo}-{hi}s, got {dur}")
            allowed = models.video_allowed_durations(eff_model)
            if allowed is not None and dur not in allowed:
                e(f"{lid}: {eff_model} duration must be one of "
                  f"{list(allowed)}s, got {dur}s")
            res = L.get("resolution")
            if res is not None:
                max_res_dur = models.video_resolution_max_duration(eff_model, res)
                if max_res_dur is not None and dur > max_res_dur:
                    e(f"{lid}: {eff_model} resolution {res!r} only supports duration <= {max_res_dur}s, got {dur}s")
    ratio = L.get("ratio")
    if ratio is not None and ratio not in VIDEO_RATIOS:
        e(f"{lid}: video ratio must be one of {list(VIDEO_RATIOS)}, got {ratio!r}")

    # Keyframe & reference media validation against core/generation/models.py capability table
    ff_key = next((k for k in ("first_frame", "input_asset", "input_image") if k in L and L[k] is not None), None)
    ff_val = L.get(ff_key) if ff_key else None
    if ff_key is not None:
        _check_img_ref(lid, ff_val, ff_key, "video", layer_by_id, errs)
        if eff_model and not models.video_supports_input_image(eff_model):
            e(f"{lid}: {eff_model} does not support {ff_key}")
        if ratio is not None and ratio != "adaptive":
            e(f"{lid}: video ratio must be 'adaptive' when {ff_key} is set (got {ratio!r})")

    lf_key = next((k for k in ("last_frame", "last_frame_image", "last_frame_asset") if k in L and L[k] is not None), None)
    lf_val = L.get(lf_key) if lf_key else None
    if lf_key is not None:
        _check_img_ref(lid, lf_val, lf_key, "video", layer_by_id, errs)
        if ff_key is None:
            e(f"{lid}: {lf_key} requires first_frame / input_image")
        if eff_model and not models.video_supports_last_frame(eff_model):
            e(f"{lid}: {eff_model} does not support {lf_key}")

    ref_type = L.get("reference_type")
    if ref_type is not None:
        if not isinstance(ref_type, str):
            e(f"{lid}: video reference_type must be a string")
        elif eff_model:
            allowed_rt = models.video_reference_types(eff_model)
            if ref_type not in allowed_rt:
                reason = models.video_unsupported_reference_type_reason(eff_model, ref_type)
                detail = f" — {reason}" if reason else ""
                e(f"{lid}: {eff_model} reference_type must be one of {list(allowed_rt)}, got {ref_type!r}{detail}")
            max_rt_dur = models.video_reference_type_max_duration(eff_model, ref_type)
            if max_rt_dur is not None and dur is not None and isinstance(dur, int) and dur > max_rt_dur:
                e(f"{lid}: {eff_model} reference_type {ref_type!r} only supports duration <= {max_rt_dur}s, got {dur}s")

    for rk, max_cnt in (("reference_images", 9), ("reference_assets", 9)):
        if rk in L and L[rk] is not None:
            if eff_model and not models.video_supports_reference_media(eff_model):
                supported_ref_models = [m for m in models.VIDEO_MODELS if models.video_supports_reference_media(m)]
                e(f"{lid}: {eff_model} does not support {rk} (supported by: {supported_ref_models})")
            rlist = L[rk]
            if not isinstance(rlist, list) or not (1 <= len(rlist) <= max_cnt):
                e(f"{lid}: {rk} must be a list of 1..{max_cnt} asset/layer names")
            else:
                for item in rlist:
                    _check_img_ref(lid, item, rk, "video", layer_by_id, errs)

    # reference_videos / reference_audios are accepted by the backend,
    # but S1 cannot resolve a video or audio SOURCE: they are not
    # image assets, and nothing in the spec can point at one. Leaving
    # them accepted would be a silent no-op — the clip would come
    # back text-to-video with the reference dropped — so they are
    # refused here until the transport can carry them.
    for rk in ("reference_videos", "reference_audios"):
        if rk in L and L[rk] is not None:
            e(f"{lid}: video {rk} is not supported yet — S1 cannot "
              f"resolve a video/audio source, so it would be silently "
              f"dropped from the request. Use reference_images instead.")


def validate_layer(L, spec, ids, zs, layer_by_id, errs):
    """Validate one layer of a shot, appending any problem to `errs`."""
    e = errs.append
    if not isinstance(L, dict):
        e("layer must be an object")
        return
    lid = L.get("id", "?")
    removed = {"draw", "params", "text", "subtext", "fontSize", "fontWeight", "color", "hudType", "cardType", "details", "title", "quote", "plate", "gait", "depth", "translucent", "shadowColor", "controlRod", "rodAnchor", "rodAnchors", "punch", "vibe", "vibe_grade"}
    for key in sorted(removed.intersection(L)):
        e(f"{lid}: migration required: removed field {key!r}; author visuals in component props, captions/events in tracks")
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
    z = L.get("z")
    if isinstance(z, bool) or not isinstance(z, int):
        # The renderer stacks the layers by z (remotion/Shot.tsx sorts on
        # it). A missing or non-integer z sorts as NaN and leaves the
        # stacking order to chance, so it is refused here instead.
        e(f"{lid}: z must be an int (the renderer stacks layers by z) — got {z!r}")
    else:
        if z in zs:
            e(f"{lid}: duplicate z {z}")
        zs.add(z)
    ltype = L.get("type")
    if not isinstance(ltype, str):
        e(f"{lid}: type must be a string (got {ltype!r})")
    elif ltype not in constants.LAYER_TYPES:
        e(f"{lid}: migration required: type must be one of {sorted(constants.LAYER_TYPES)}; author legacy visuals as project components")
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
    lc = L.get("blockCore")
    if lc is not None:
        if not (isinstance(lc, list) and len(lc) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and 0.0 <= v <= 1.0 for v in lc)):
            e(f"{lid}: blockCore must be [leftFrac, rightFrac] in [0,1] "
              f"(the torso band of the rect used by verify-blocking)")
    bd = L.get("backdrop")
    if bd is not None:
        if not isinstance(bd, str) or not bd.strip():
            e(f"{lid}: backdrop must be a non-empty string — the project's own "
              f"identity for this background (the same identity across two shots "
              f"means 'the same place'; verify-continuity compares these)")
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
    if L.get("type") == "ai":
        _validate_ai_layer(L, lid, layer_by_id, errs)
    if L.get("type") == "video":
        _validate_video_layer(L, lid, layer_by_id, errs)
    if "anim" in L:
        validate_anim(L["anim"], lid, errs)
    if "spring" in L and L["spring"] is not None:
        validate_spring(L["spring"], lid, errs)
    if "role" in L and L["role"] is not None:
        if L["role"] not in LAYER_ROLES:
            e(f"{lid}: role must be one of {sorted(LAYER_ROLES)} (got {L['role']!r})")
    if "flipX" in L and L["flipX"] is not None:
        if not isinstance(L["flipX"], bool):
            e(f"{lid}: flipX must be a boolean (got {L['flipX']!r})")
    if L.get("type") == "component":
        comp_name = L.get("component")
        if not comp_name:
            e(f"{lid}: component layer needs 'component' (registered in the project's remotion-custom.tsx CUSTOM_COMPONENTS, aliased as 'project-custom')")
        elif not valid_name(comp_name):
            e(f"{lid}: component must be a valid identifier string (got {comp_name!r})")
        if "props" in L and not isinstance(L["props"], dict):
            e(f"{lid}: component props must be an object")
    m = L.get("motion")
    if m is not None:
        if not isinstance(m, dict):
            e(f"{lid}: motion must be an object (got {m!r})")
        elif m.get("type") != "geometric":
            e(f"{lid}: motion.type must be 'geometric' (numbers, not prose)")
        else:
            z = m.get("zoom")
            if z is not None and not (isinstance(z, list) and len(z) == 2
                                      and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                              for v in z) and z[0] >= 1 and z[1] >= 1):
                e(f"{lid}: zoom must be [from,to] numbers >= 1")
            p = m.get("pan")
            if p is not None and not (isinstance(p, list) and len(p) == 2
                                      and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                              for v in p)):
                e(f"{lid}: pan must be [xFrom,xTo] numbers")
            if z is not None and not zoom_supported(L):
                # The validator must not refuse what the renderer can do — and
                # must not promise what it cannot. The message names the layer
                # kind so the author knows which channel to use instead.
                e(f"{lid}: zoom is unsupported; use anim.scale")
            if p is not None:
                e(f"{lid}: migration required: motion.pan removed; use anim.x")


def validate_video_generation(layer, model):
    errors = []
    if model not in models.VIDEO_MODELS:
        return [f"No configured video capabilities for {model!r}"]
    resolution = layer.get("resolution")
    if resolution is not None and resolution not in models.video_resolutions(model):
        errors.append(f"{model}: unsupported resolution {resolution!r}")
    _validate_video_layer(layer, layer.get("id", "?"), {}, errors, generation_model=model)
    return errors
