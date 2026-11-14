"""Audio ownership resolution and the bit-exact mp4 encode from the PNG
frames S4 measures."""
import os
import subprocess

from core.runtime import manifest
from core.runtime.config import ROOT
from core.rendering.timeline import atempo_chain, video_timeline


def video_audio_source(spec):
    """The prepared clip whose native track owns the soundtrack, if any.

    Audio ownership is exclusive (SKILL.md "Audio ownership"):
      - a video layer with muted:false keeps its native track, and that track
        is the shot's soundtrack;
      - otherwise the pipeline's TTS chain owns it.
    Returns the prepared clip path, or None."""
    shot_id = spec.get("id", "shot-01")
    for L in spec["layers"]:
        if L.get("type") != "video" or L.get("muted", True):
            continue
        row = manifest.verified("prepared", f"{shot_id}/{L['asset']}")
        if row is None:
            continue
        return os.path.join(ROOT, row["path"])
    return None


def encode_mp4(spec, frames_dir, out_mp4):
    FPS = spec["fps"]
    audio_spec = spec.get("audio")
    audio_file = None

    # Which track owns the soundtrack: the clip's native audio, the TTS chain,
    # or neither. Declaring both is a spec error, not a style choice — the
    # two would overlap and the S4 audio gates would flag the result.
    clip_audio = video_audio_source(spec)
    has_voice = bool(audio_spec and audio_spec.get("voiceover"))
    has_bgm = bool(audio_spec and audio_spec.get("bgm"))
    wants_tts = has_voice or has_bgm
    if clip_audio and wants_tts:
        raise RuntimeError(
            f"{spec.get('id')}: audio conflict — a video layer with muted:false "
            f"keeps its native track, and audio.voiceover/bgm asks for the TTS "
            f"chain as well. Pick one: set \"muted\": true on the video layer "
            f"(TTS owns the audio) or drop audio.voiceover/bgm (the clip owns it).")

    if clip_audio:
        # The clip's native track has not been through the mastering chain, so
        # its loudness is whatever the model produced (-22.9 LUFS measured on a
        # real H3 clip — below the gate's -19 floor). Run the same loudnorm
        # target the TTS chain uses so every shot lands in the same window.
        audio_file = os.path.join(ROOT, ".tmp", f"{spec['id']}_clip_audio.m4a")
        v_layer = next((L for L in spec.get("layers", [])
                        if L.get("type") == "video" and not L.get("muted", True)), None)
        t0, t1, rate = video_timeline(v_layer, FPS) if v_layer else (0.0, None, 1.0)
        trim = (t0, t1) if t1 is not None else None
        shot_seconds = spec["durationInFrames"] / max(1, FPS)

        af_parts = ["aformat=sample_rates=44100:channel_layouts=stereo"]
        # The renderer time-warps the clip's native audio by the same
        # playbackRate as its picture (remotion media seek: trimBefore +
        # local * rate). Master the track through the same warp or the shot
        # drifts out of AV sync by (1 - 1/rate) * t — the S4 sync gate
        # (<= 100 ms) fails long before the clip ends.
        warp = atempo_chain(rate) if abs(rate - 1.0) > 1e-9 else []
        input_args = []
        if trim:
            seg_dur = max(0.001, t1 - t0)
            af_parts.append(f"atrim=start={t0}:end={t1}")
            af_parts.append("asetpts=PTS-STARTPTS")
            # Loop the window BEFORE warping it. Warping the looped window
            # yields exactly Remotion's loop period (window / rate) — and
            # aloop must see the unwarped samples: aloop-after-atempo was
            # measured to repeat only a partial buffer, flattening the track
            # to its first few samples.
            if v_layer.get("loop", True) and seg_dur / rate < shot_seconds:
                af_parts.append(
                    f"aloop=loop=-1:size={max(1, int(round(seg_dur * 44100)))}")
            af_parts.extend(warp)
        else:
            af_parts.extend(warp)
            if v_layer and v_layer.get("loop", True):
                input_args = ["-stream_loop", "-1"]

        base_af = ",".join(af_parts)
        from core.audio import run_two_pass_loudnorm
        try:
            run_two_pass_loudnorm(
                input_args + ["-i", clip_audio],
                "-af",
                base_af,
                round(shot_seconds, 4),
                audio_file,
            )
        except subprocess.CalledProcessError as ex:
            raise RuntimeError(f"mastering the clip's native audio failed: {ex}") from ex
        notes = []
        if trim:
            notes.append(f"trimmed to [{t0}s, {t1}s]")
        if abs(rate - 1.0) > 1e-9:
            notes.append(f"playbackRate {rate:g}")
        note = f" ({', '.join(notes)})" if notes else ""
        print(f"audio source: native track of {os.path.basename(clip_audio)}{note} "
              f"(mastered to -16 LUFS)")
    elif wants_tts:
        from core.audio import prepare_shot_audio
        audio_file = os.path.join(ROOT, ".tmp", f"{spec['id']}_audio.aac")
        if spec.get("punches"):
            prepare_shot_audio(audio_spec, spec["durationInFrames"], FPS, audio_file, punches=spec["punches"])
        else:
            prepare_shot_audio(audio_spec, spec["durationInFrames"], FPS, audio_file)
        bgm_label = audio_spec.get("bgm", "ambient")
        # Name the track that was ACTUALLY built. The old label said
        # "TTS chain (edge-tts + ...)" for every branch, which sent the
        # author looking for a narration that was never synthesized.
        if has_voice and has_bgm:
            print(f"audio source: voiceover + {bgm_label} bgm (mastered to -16 LUFS)")
        elif has_voice:
            print("audio source: voiceover only (mastered to -16 LUFS)")
        else:
            print(f"audio source: bgm only ({bgm_label}, mastered to -16 LUFS)")
    else:
        # A silent shot still gets a compliant 44100 Hz stereo silent track.
        # Without one the mp4 carries no audio stream at all, and concat
        # refuses to assemble it beside shots that DO have sound — the exact
        # thing this track is meant to prevent.
        from core.audio import prepare_shot_audio
        audio_file = os.path.join(ROOT, ".tmp", f"{spec['id']}_audio.aac")
        prepare_shot_audio({}, spec["durationInFrames"], FPS, audio_file)
        print("audio source: silent track (44100 Hz stereo aac)")

    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-framerate", str(FPS), "-i", os.path.join(frames_dir, "%05d.png"),
    ]
    if audio_file and os.path.exists(audio_file):
        cmd.extend(["-i", audio_file])

    # vibe_grade: cinema texture on encode (deterministic filters — same spec
    # still yields the same mp4). Gates measure the ungraded S3 frames; this is
    # presentation layered on top.
    if spec.get("vibe_grade"):
        cmd.extend(["-vf", "split[a][b];[b]gblur=sigma=14[bl];[a][bl]blend=all_mode=screen:all_opacity=0.22,noise=alls=12:allf=t,vignette=PI/3.8,eq=contrast=1.1:saturation=1.16"])

    cmd.extend([
        "-frames:v", str(spec["durationInFrames"]), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-threads", "1", "-r", str(FPS),
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-movflags", "+faststart", "-fflags", "+bitexact", "-flags:v", "+bitexact",
        "-pix_fmt", "yuv420p",
    ])
    if audio_file and os.path.exists(audio_file):
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])

    cmd.append(out_mp4)
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)
