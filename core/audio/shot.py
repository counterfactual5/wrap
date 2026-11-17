"""Per-shot audio preparation and soundtrack intent.

- prepare_shot_audio: Synthesizes, masters, and mixes audio tailored to exact shot duration, recording truncation metadata
- shot_is_intentionally_silent: True when the spec asks for NO soundtrack at all
"""
import json
import os
import subprocess

from core.runtime.config import ROOT
from core.audio.captions import clauses_from_boundaries
from core.audio.mastering import run_two_pass_loudnorm
from core.audio.tts import get_audio_duration, synthesize_voiceover_with_timings

# A voiceover longer than the shot keeps its tail clipped without exceeding
# this tolerance (25% second). Used by prepare_shot_audio's truncation flag
# and by the S4 truncation gate — keep them in one place.
VOICEOVER_TAIL_TOLERANCE = 0.25
from core.audio.integrity import verify_audio

def shot_is_intentionally_silent(spec):
    """True when the spec asks for NO soundtrack at all.

    A silent shot still gets a compliant 44100 Hz stereo silent track, so
    concatenation never has to drop an audio stream. But that track must not
    be measured against the speech/loudness gates — those exist to catch a
    soundtrack that SHOULD have sound and doesn't.

    Intent is read from the SPEC, never from the rendered file: a shot that
    declares voiceover/bgm and comes out silent is broken, and the gates have
    to say so instead of excusing it as "intentional".
    """
    if not isinstance(spec, dict):
        return False
    audio_spec = spec.get("audio")
    if isinstance(audio_spec, dict) and (audio_spec.get("voiceover") or audio_spec.get("bgm")):
        return False
    for L in spec.get("layers") or []:
        if isinstance(L, dict) and L.get("type") == "video" and not L.get("muted", True):
            return False
    return True


# BGM bed fade envelope (shot audio): a short fade in/out so the bed never
# pops at the cut boundaries. Documented shape: min(max_cap, 10% of the
# shot), max_cap 0.04 s.
BG_FADE_MAX_SEC = 0.04
BG_FADE_FRAC_OF_DURATION = 0.1


def prepare_shot_audio(audio_spec, duration_in_frames, fps, out_path, punches=None):
    """Generates mastered narration and BGM tailored to the exact shot duration.

    Voiceover / TTS is completely OPTIONAL:
    - If audio.voiceover is omitted or empty, the shot runs in pure BGM / music-driven
      mode (e.g. Douyin / TikTok style visual cards + soundtrack), or silent if no BGM.
    - If audio.bgm is provided without voiceover, BGM is mastered at full fidelity to
      -16 LUFS without artificial attenuation, supporting bgmOffset for multi-shot cuts.
    Output is pinned to 44100 Hz stereo to ensure seamless concatenation across all shots.
    """
    target_duration = duration_in_frames / fps
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    voiceover_text = (audio_spec.get("voiceover") or "").strip() if isinstance(audio_spec, dict) else ""
    voice = audio_spec.get("voice") if isinstance(audio_spec, dict) else None
    bgm_type = audio_spec.get("bgm") if isinstance(audio_spec, dict) else None
    bgm_offset = float(audio_spec.get("bgmOffset", 0.0)) if isinstance(audio_spec, dict) and audio_spec.get("bgmOffset") is not None else 0.0
    rate = (audio_spec.get("rate") or "+0%") if isinstance(audio_spec, dict) else "+0%"


    # Unique per-shot prefix so concurrent S3 runs never share scratch files.
    tmp_voice = out_path + ".voice.wav"
    tmp_bgm = out_path + ".bgm.wav"

    has_voice = False
    raw_voice_dur = 0.0
    boundaries = []
    if voiceover_text:
        voice_path = next((p for p in (voiceover_text, os.path.join(ROOT, voiceover_text),
                                        os.path.join(ROOT, "assets", voiceover_text))
                           if os.path.isfile(p)), None)
        if voice_path:
            import shutil
            shutil.copyfile(verify_audio(voice_path), tmp_voice)
            raw_voice_dur = get_audio_duration(tmp_voice)
        else:
            if voiceover_text.lower().endswith((".wav", ".mp3", ".aac", ".m4a", ".ogg", ".flac")):
                raise FileNotFoundError(f"Voiceover file not found: {voiceover_text}")
            if not voice:
                raise ValueError("text audio.voiceover requires an explicit audio.voice; the engine ships no default narrator")
            _, raw_voice_dur, boundaries = synthesize_voiceover_with_timings(
                voiceover_text, voice=voice, out_path=tmp_voice, rate=rate
            )
        has_voice = True

    # Record speech timing & truncation metadata per shot so S4 can gate against cut-off narration
    clauses = (
        clauses_from_boundaries(voiceover_text, boundaries, raw_voice_dur, fps=fps)
        if has_voice and not voice_path
        else []
    )
    meta = {
        "has_voice": has_voice,
        "raw_voice_duration": round(raw_voice_dur, 3),
        "target_duration": round(target_duration, 3),
        "truncated": bool(has_voice and raw_voice_dur > target_duration + VOICEOVER_TAIL_TOLERANCE),
        "clauses": clauses,
        "bgm": bgm_type,
        "bgm_offset": bgm_offset,
    }
    try:
        with open(out_path + ".meta.json", "w") as mf:
            json.dump(meta, mf, ensure_ascii=False, indent=2)
    except OSError:
        pass

    # Resolve BGM source (if any)
    has_bgm = bool(bgm_type and str(bgm_type).strip() and str(bgm_type).strip().lower() != "none")
    # The engine ships no default duck ratio for music under speech; the
    # author declares it. Voice-only or music-only shots run full volume.
    bgm_vol = 1.0
    if has_voice and has_bgm:
        bgm_under = audio_spec.get("bgmUnderVoice") if isinstance(audio_spec, dict) else None
        if bgm_under is None:
            raise ValueError(
                "audio.voiceover and audio.bgm are both set: the engine ships no default duck "
                "ratio — declare spec.audio 'bgmUnderVoice' (0..1, e.g. 0.25 for background "
                "music at 25% under the speech)")
        bgm_vol = float(bgm_under)

    if has_bgm:
        # Check file paths: absolute, relative to ROOT, or in assets/
        candidates = [
            bgm_type,
            os.path.join(ROOT, bgm_type),
            os.path.join(ROOT, "assets", bgm_type),
        ]
        found_bgm = next((p for p in candidates if os.path.exists(p)), None)
        if found_bgm:
            found_bgm = verify_audio(found_bgm)
            fade_dur = min(BG_FADE_MAX_SEC, target_duration * BG_FADE_FRAC_OF_DURATION)
            fade_filter = f"afade=t=in:ss=0:d={fade_dur:.3f},afade=t=out:st={max(0.0, target_duration - fade_dur):.3f}:d={fade_dur:.3f}"
            seek_args = ["-ss", f"{bgm_offset:.3f}"] if bgm_offset > 0 else []
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-stream_loop", "-1"] + seek_args + [
                "-i", found_bgm, "-t", str(target_duration),
                "-af", fade_filter,
                "-ar", "44100", "-ac", "2", tmp_bgm
            ], check=True)
        else:
            raise FileNotFoundError(f"BGM file not found: {bgm_type}; built-in music presets were removed")

    if has_voice and has_bgm:
        base_fc = (
            f"[0:a]apad=whole_dur={target_duration}[v];"
            f"[1:a]volume={bgm_vol}[b];"
            f"[v][b]amix=inputs=2:duration=first:dropout_transition=0:normalize=0"
        )
        run_two_pass_loudnorm(
            ["-i", tmp_voice, "-i", tmp_bgm],
            "-filter_complex",
            base_fc,
            target_duration,
            out_path,
        )
    elif has_voice:
        run_two_pass_loudnorm(
            ["-i", tmp_voice],
            "-af",
            # Pad the voice track out to the full shot with silence — same
            # contract as the voice+BGM branch. Without this, the mastered
            # voice is only as long as the spoken line, `-shortest` in the
            # compose stage then cuts the video to speech length, and S5's
            # frame-count check fails against durationInFrames (546 != 564).
            f"apad=whole_dur={target_duration}",
            target_duration,
            out_path,
        )
    elif has_bgm:
        run_two_pass_loudnorm(
            ["-i", tmp_bgm],
            "-af",
            "",
            target_duration,
            out_path,
        )
    else:
        # Pure silent audio track of exact duration (e.g. for silent video layer or muted cards)
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", str(target_duration),
            "-c:a", "aac", "-b:a", "192k",
            out_path
        ], check=True)

    return out_path
