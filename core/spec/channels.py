"""The per-layer channels: anim keyframes, gait, spring, combat, captions.

Each of these is declared inside a layer (or, for combat, at the shot level)
and validated on its own, apart from the layer's own fields.
"""
import os
import re

from .constants import ANIM_CHANNELS, ANIM_EASES, GAIT_MODES, SPRING_CHANNELS


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
