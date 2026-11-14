"""Single-source-of-truth alignment of a shot spec to TTS speech timings.

- sync_spec_audio: Aligns shot durationInFrames and tracks.captions to TTS
  speech clause timings. When no voiceover is declared, a spec's tracks are
  left untouched (a judge/author owns them); there is no pacing default.
"""
import json
import math
import os
import re
import tempfile

from core.audio.captions import clauses_from_boundaries
from core.audio.tts import synthesize_voiceover_with_timings

def _norm_cjk(s):
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", str(s or "").lower()))


def _build_clause_anchors(old_items, new_clauses, old_max, new_max):
    """Build piecewise-linear frame anchors [(old_f, new_f), ...] by matching authored caption
    items against TTS-timed clauses so visual beats stay 100% locked to spoken subtitle clauses."""
    anchors = [(0, 0)]
    if isinstance(old_items, list) and len(old_items) >= 2 and isinstance(new_clauses, list) and len(new_clauses) >= 2:
        c_idx = 0
        for it in old_items:
            if not isinstance(it, dict):
                continue
            of = it.get("frame")
            otext = _norm_cjk(it.get("text", ""))
            if not isinstance(of, int) or of <= 0 or of >= old_max or len(otext) < 2:
                continue
            prefix = otext[:min(4, len(otext))]
            matched_nf = None
            for j in range(c_idx, len(new_clauses)):
                ctext = _norm_cjk(new_clauses[j].get("text", ""))
                if prefix in ctext or ctext[:min(3, len(ctext))] in otext[:6]:
                    matched_nf = int(new_clauses[j]["frame"])
                    c_idx = j + 1
                    break
            if matched_nf is not None and of > anchors[-1][0] and matched_nf > anchors[-1][1] and matched_nf < new_max:
                anchors.append((of, matched_nf))
    anchors.append((old_max, new_max))
    return anchors


def _rescale_frame(f, old_max, new_max, anchors=None):
    if old_max <= 0 or new_max <= 0:
        return f
    if f <= 0:
        return 0
    if f >= old_max:
        return new_max
    if anchors and len(anchors) >= 2:
        for i in range(len(anchors) - 1):
            o0, n0 = anchors[i]
            o1, n1 = anchors[i + 1]
            if o0 <= f <= o1:
                if o1 <= o0:
                    return n0
                t = (f - o0) / float(o1 - o0)
                return int(round(n0 + t * (n1 - n0)))
    return int(round(f * new_max / old_max))


def _rescale_spec_timings(spec, old_frames, new_frames, anchors=None):
    """Piecewise clause-anchored (or proportional) rescaling of layer anim keyframes,
    poses, and tracks.events frames."""
    old_max = max(1, old_frames - 1)
    new_max = max(1, new_frames - 1)
    for event in (spec.get("tracks") or {}).get("events", []):
        for key in ("frame", "end_frame"):
            if key in event:
                event[key] = _rescale_frame(event[key], old_max, new_max, anchors=anchors)
    for L in spec.get("layers", []):
        if isinstance(L.get("anim"), dict):
            for ch, kfs in L["anim"].items():
                if not isinstance(kfs, list):
                    continue
                prev_f = -1
                for kf in kfs:
                    if isinstance(kf, list) and len(kf) >= 2:
                        nf = _rescale_frame(kf[0], old_max, new_max, anchors=anchors)
                        if nf <= prev_f:
                            nf = prev_f + 1
                        kf[0] = nf
                        prev_f = nf
        if isinstance(L.get("poses"), list):
            prev_pf = -1
            for pose in L["poses"]:
                if isinstance(pose, dict) and isinstance(pose.get("frame"), int):
                    nf = 0 if pose["frame"] == 0 else _rescale_frame(pose["frame"], old_max, new_max, anchors=anchors)
                    if nf <= prev_pf:
                        nf = prev_pf + 1
                    pose["frame"] = nf
                    prev_pf = nf


def sync_spec_audio(spec_path, fit_duration=True, rescale_anim=True, max_chars=20):
    """Synchronize a shot spec's durationInFrames and tracks.captions from audio.voiceover.

    TTS is strictly optional:
    - If audio.voiceover is present, aligns durationInFrames and tracks.captions
      to speech clauses and warps layer keyframes / poses / events to them.
    - If audio.voiceover is omitted, the spec is left untouched (tracks are
      authored data; the engine does not pace or design them).
    """
    with open(spec_path) as f:
        spec = json.load(f)

    fps = spec.get("fps", 30)
    audio_spec = spec.get("audio") or {}
    voiceover_text = (audio_spec.get("voiceover") or "").strip()
    tracks = spec.setdefault("tracks", {})
    old_items = tracks.get("captions", [])
    if not voiceover_text:
        return {"shot_id": spec.get("id"), "status": "no_voiceover", "captions": old_items}

    voice = audio_spec.get("voice")
    rate = audio_spec.get("rate") or "+0%"
    if voiceover_text and not voice:
        raise ValueError("audio.voiceover requires an explicit audio.voice; the engine ships no default narrator")
    with tempfile.TemporaryDirectory(prefix="wrap-sync-audio-") as temp_dir:
        tmp_wav = os.path.join(temp_dir, "voice.wav")
        _, raw_dur, boundaries = synthesize_voiceover_with_timings(
            voiceover_text, voice=voice, out_path=tmp_wav, rate=rate
        )

    old_frames = spec.get("durationInFrames", 150)
    required_frames = int(math.ceil((raw_dur + 0.6) * fps))
    new_frames = max(old_frames, required_frames) if fit_duration else old_frames

    clauses = clauses_from_boundaries(
        voiceover_text, boundaries, raw_dur, fps=fps, max_chars=max_chars
    )

    anchors = _build_clause_anchors(old_items, clauses, max(1, old_frames - 1), max(1, new_frames - 1))
    if rescale_anim and (new_frames != old_frames or len(anchors) > 2):
        _rescale_spec_timings(spec, old_frames, new_frames, anchors=anchors)
    spec["durationInFrames"] = new_frames
    caption_items = clauses
    tracks["captions"] = caption_items
    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)

    return {
        "shot_id": spec.get("id"),
        "raw_voice_duration_sec": round(raw_dur, 2),
        "old_durationInFrames": old_frames,
        "new_durationInFrames": new_frames,
        "shot_duration_sec": round(new_frames / fps, 2),
        "updated_caption_tracks": 1,
        "captions": caption_items,
    }
