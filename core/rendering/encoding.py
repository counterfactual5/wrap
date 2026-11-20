"""Audio ownership resolution and the bit-exact mp4 encode from the PNG
frames S4 measures."""
import os
import subprocess

from core.runtime import manifest
from core.runtime.config import ROOT
from core.audio.sentinel import has_bgm as declares_bgm
from core.rendering.timeline import atempo_chain, video_timeline
from core.rendering.frames import normalize_frame_formats
from core.runtime.timeouts import LOCAL_TOOL_TIMEOUT
from core.spec.constants import HEX


def canvas_background(spec):
    """The opaque sheet the frames are composited over: (width, height, color).

    The color is an ffmpeg color spec derived from spec.canvas.bg — the
    project's declared canvas background, or black when it declares none.
    Shared with the S4 master/video binding check so the two always composite
    the master the same way.
    """
    canvas = spec.get("canvas") or {}
    cw, ch = canvas.get("w") or 1920, canvas.get("h") or 1080
    raw_bg = str(canvas.get("bg") or "").strip()
    if HEX.fullmatch(raw_bg):
        bg_color = f"0x{raw_bg[1:]}"
    elif raw_bg.lower() in ("black", "white"):
        bg_color = raw_bg.lower()
    else:
        bg_color = "black"
    return cw, ch, bg_color


def video_audio_source(spec):
    """The prepared clip whose native track owns the soundtrack, if any.

    Audio ownership is exclusive (SKILL.md "Audio ownership"):
      - a video layer with muted:false keeps its native track, and that track
        is the shot's soundtrack;
      - otherwise the pipeline's TTS chain owns it.
    Returns the prepared clip path, or None."""
    shot_id = spec["id"]
    candidates = [L for L in spec["layers"] if L.get("type") == "video" and not L.get("muted", True)]
    if len(candidates) > 1:
        raise RuntimeError(
            f"{spec.get('id')}: more than one unmuted video layer "
            f"({[L.get('id') for L in candidates]}) — the pipeline cannot decide "
            f"whose track owns the soundtrack; set \"muted\": true on all but one.")
    for L in candidates:
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
    # `bgm: "none"` is the engine's own "no background music" sentinel — it
    # must not be read as a request for a soundtrack.
    has_bgm = declares_bgm(audio_spec.get("bgm") if audio_spec else None)
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
                round(shot_seconds, 6),
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
        prepare_shot_audio(audio_spec, spec["durationInFrames"], FPS, audio_file)
        bgm_label = audio_spec.get("bgm")
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

    # The rendered PNGs carry an alpha channel (Remotion writes RGBA). Encoding
    # them straight to yuv420p DISCARDS that alpha, so a layer's opacity ramp
    # never reaches the picture: a backdrop faded to 45% arrives at full
    # strength, and only opacity 0 (the element dropped entirely) reads as
    # black. Composite the frames over an opaque sheet matching spec.canvas.bg
    # (or black when unset) — that preserves both transparent opacity ramps and
    # the project's declared canvas background.
    #
    # The frame sequence must reach the decoder in ONE pixel format: Remotion
    # writes RGBA only for the frames that carry transparency and RGB for the
    # rest, so a rendered sequence can mix color types; the PNG demuxer then
    # changes the decoded format mid-stream, ffmpeg reconfigures the filter
    # graph, the overlay's frame sync is reset, and the encoder emits the bare
    # background sheet (a black frame) at positions that differ from run to
    # run. S3 normalizes the sequence right after the render (see
    # core.rendering.frames) — the encoder only reads what it is given.
    cw, ch, bg_color = canvas_background(spec)
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={bg_color}:s={cw}x{ch}:r={FPS}",
        "-framerate", str(FPS), "-i", os.path.join(frames_dir, "%05d.png"),
    ]
    has_audio_file = bool(audio_file and os.path.exists(audio_file))
    if has_audio_file:
        cmd.extend(["-i", audio_file])

    # Pad audio with silence (`apad`) before `-shortest` so AAC packet rounding
    # (e.g. 5.033311s vs 151 frames = 5.033333s) or a short non-looping clip
    # track can never truncate the final rendered video frame; `[v]` remains
    # strictly bounded by `overlay=shortest=1` to exact `durationInFrames`.
    filter_complex = (
        "[0:v][1:v]overlay=shortest=1[v];[2:a]apad[a]"
        if has_audio_file
        else "[0:v][1:v]overlay=shortest=1[v]"
    )
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-frames:v", str(spec["durationInFrames"]), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-threads", "1", "-r", str(FPS),
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-movflags", "+faststart", "-fflags", "+bitexact", "-flags:v", "+bitexact",
        "-pix_fmt", "yuv420p",
    ])
    if has_audio_file:
        # `-map [v]` above means ffmpeg no longer auto-maps the soundtrack:
        # input 0 is the colour sheet, 1 the frames, 2 the padded audio.
        cmd.extend(["-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-shortest"])

    cmd.append(out_mp4)
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT, timeout=LOCAL_TOOL_TIMEOUT)
