"""Audio generation and mixing utilities for the code-driven video pipeline.
Provides:
- synthesize_voiceover: Neural text-to-speech with natural cadence + broadcast mastering, fallback to local TTS
- generate_ambient_bgm: Synthesizes immersive high-tech sci-fi drone soundscapes with FFmpeg
- prepare_shot_audio: Synthesizes, masters, and mixes audio tailored to exact shot duration
"""
import os
import subprocess
import urllib.parse
import urllib.request
from schema import ROOT


def get_audio_duration(file_path):
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(res.stdout.strip())
    except Exception:
        return 0.0


def _download_edge_tts(text, voice="zh-CN-YunxiNeural", rate="+18%", out_mp3=None):
    """Synthesize speech using Microsoft Edge Neural TTS."""
    import asyncio
    import edge_tts

    async def _run():
        communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
        await communicate.save(out_mp3)

    asyncio.run(_run())


def _download_neural_tts(text, out_mp3):
    encoded = urllib.parse.quote(text)
    url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={encoded}&tl=zh-CN&client=tw-ob"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp, open(out_mp3, "wb") as f:
        f.write(resp.read())


def synthesize_voiceover(text, voice="neural", out_path=None):
    if not out_path:
        out_path = os.path.join(ROOT, ".tmp", "voiceover.wav")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    raw_audio = os.path.join(ROOT, ".tmp", "raw_voice.mp3")
    tts_success = False

    # 1. Try Microsoft Edge Neural TTS first (zh-CN-YunxiNeural) for lively, natural Douyin/TikTok cadence
    try:
        edge_voice = "zh-CN-YunxiNeural" if voice in ("neural", "yunxi", "Tingting") else voice
        _download_edge_tts(text, voice=edge_voice, rate="+18%", out_mp3=raw_audio)
        if os.path.exists(raw_audio) and os.path.getsize(raw_audio) > 1000:
            tts_success = True
    except Exception as ex:
        print(f"Edge TTS fallback: {ex}")

    # 2. Try Google Translate TTS fallback
    if not tts_success:
        try:
            _download_neural_tts(text, raw_audio)
            if os.path.exists(raw_audio) and os.path.getsize(raw_audio) > 1000:
                tts_success = True
        except Exception as ex:
            print(f"Google TTS fallback: {ex}")

    # 3. Fallback to local macOS speech synthesis with measured brisk rate
    if not tts_success:
        tmp_aiff = os.path.join(ROOT, ".tmp", "temp_speech.aiff")
        v = "Tingting" if voice in ("neural", "Tingting") else voice
        subprocess.run(["say", "-v", v, "-r", "175", text, "-o", tmp_aiff], check=True)
        raw_audio = tmp_aiff

    # 3. Broadcast-grade audio mastering filter chain:
    # - High-pass 75Hz: cuts sub-bass mud
    # - Low-mid warmth EQ (250Hz, +2.5dB)
    # - Presence EQ (3200Hz, +2.0dB) for crystal clear vocals
    # - Dynamic compressor: levels peaks and creates warm podcast tone
    master_filter = (
        "highpass=f=75,"
        "equalizer=f=250:t=q:w=1:g=2.5,"
        "equalizer=f=3200:t=q:w=1:g=2.0,"
        "compand=0.01|0.05:6:-60/-60|-22/-12|0/-2:6:0:-90:0.05,"
        "volume=1.35"
    )

    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-i", raw_audio,
        "-af", master_filter,
        "-ar", "44100", "-ac", "2", out_path
    ], check=True)

    if os.path.exists(raw_audio):
        os.remove(raw_audio)
    return out_path


def generate_ambient_bgm(duration_sec, out_path=None):
    if not out_path:
        out_path = os.path.join(ROOT, ".tmp", "ambient_bgm.wav")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # Immersive cinematic sci-fi soundscape (Sub-bass + warm chord + gentle shimmer pulse)
    lavfi_filter = (
        f"sine=frequency=55:duration={duration_sec},lowpass=f=160,volume=0.3[sub];"
        f"sine=frequency=110:duration={duration_sec},lowpass=f=260,volume=0.18[bass];"
        f"sine=frequency=220:duration={duration_sec},lowpass=f=380,volume=0.08[mid];"
        f"sine=frequency=440:duration={duration_sec},lowpass=f=600,tremolo=f=0.5:d=0.7,volume=0.04[shimmer];"
        "[sub][bass][mid][shimmer]amix=inputs=4"
    )
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
        "-i", lavfi_filter, "-ar", "44100", "-ac", "2", out_path
    ], check=True)
    return out_path


def prepare_shot_audio(audio_spec, duration_in_frames, fps, out_path):
    """Generates mastered narration and BGM tailored to the exact shot duration.
    Output is pinned to 44100 Hz stereo: loudnorm resamples internally to 192 kHz
    and leaks that rate out unless -ar pins it, and shots with mismatched sample
    rates corrupt each other in the concat demuxer (it decodes every input with
    the first file's stream config)."""
    target_duration = duration_in_frames / fps
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    voiceover_text = audio_spec.get("voiceover")
    voice = audio_spec.get("voice", "neural")
    bgm_type = audio_spec.get("bgm", "ambient")

    tmp_voice = os.path.join(ROOT, ".tmp", "shot_voice.wav")
    tmp_bgm = os.path.join(ROOT, ".tmp", "shot_bgm.wav")

    has_voice = False
    if voiceover_text and voiceover_text.strip():
        synthesize_voiceover(voiceover_text, voice=voice, out_path=tmp_voice)
        has_voice = True

    if bgm_type == "ambient":
        generate_ambient_bgm(target_duration, out_path=tmp_bgm)
    elif os.path.exists(os.path.join(ROOT, bgm_type)):
        src_bgm = os.path.join(ROOT, bgm_type)
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-stream_loop", "-1", "-i", src_bgm,
            "-t", str(target_duration), "-ar", "44100", "-ac", "2", tmp_bgm
        ], check=True)
    else:
        generate_ambient_bgm(target_duration, out_path=tmp_bgm)

    if has_voice:
        cmd = [
            "ffmpeg", "-v", "error", "-y",
            "-i", tmp_voice,
            "-i", tmp_bgm,
            "-filter_complex",
            f"[0:a]apad=whole_dur={target_duration}[v];[1:a]volume=0.22[b];[v][b]amix=inputs=2:duration=first,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "44100",
            "-t", str(target_duration),
            "-c:a", "aac", "-b:a", "192k",
            out_path
        ]
        subprocess.run(cmd, check=True)
    else:
        cmd = [
            "ffmpeg", "-v", "error", "-y",
            "-i", tmp_bgm,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "44100",
            "-t", str(target_duration),
            "-c:a", "aac", "-b:a", "192k",
            out_path
        ]
        subprocess.run(cmd, check=True)

    return out_path


def measure_audio_silence(file_path):
    """Detects audio silence using FFmpeg volumedetect.
    Returns dict with max_volume, mean_volume, and is_silent flag."""
    cmd = ["ffmpeg", "-hide_banner", "-i", file_path, "-af", "volumedetect", "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    import re
    m_max = re.search(r"max_volume:\s*([-\d.]+)\s*dB", res.stderr)
    m_mean = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", res.stderr)
    max_v = float(m_max.group(1)) if m_max else -99.0
    mean_v = float(m_mean.group(1)) if m_mean else -99.0
    is_silent = (max_v < -45.0 or mean_v < -55.0)
    return {"max_volume": max_v, "mean_volume": mean_v, "is_silent": is_silent}


def measure_audio_loudness(file_path, start=None, duration=None):
    """Measures Integrated Loudness (LUFS) using FFmpeg EBU R128 filter.
    Optional start/duration window a seek to a segment (per-shot loudness in a
    concatenated full video)."""
    import re
    cmd = ["ffmpeg", "-hide_banner"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-i", file_path, "-af", "ebur128", "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    matches = re.findall(r"I:\s*([-\d.]+)\s*LUFS", res.stderr)
    if matches:
        return float(matches[-1])
    return None


def measure_av_durations(file_path):
    """Measures video and audio stream durations and their absolute delta in seconds."""
    import json
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
        "-of", "json", file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(res.stdout)
        durs = {s["codec_type"]: float(s["duration"]) for s in data.get("streams", []) if "duration" in s}
        vid_d = durs.get("video", 0.0)
        aud_d = durs.get("audio", 0.0)
        return {
            "video_duration": vid_d,
            "audio_duration": aud_d,
            "delta": abs(vid_d - aud_d),
            "has_audio": "audio" in durs
        }
    except Exception:
        return {"video_duration": 0.0, "audio_duration": 0.0, "delta": 0.0, "has_audio": False}
