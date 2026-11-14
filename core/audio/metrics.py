"""FFmpeg/ffprobe measurement helpers for the audio gates.

- measure_audio_silence: Silence and speech-band content flags via volumedetect
- measure_audio_loudness: Integrated loudness (LUFS) via EBU R128
- measure_av_durations: Video/audio stream durations and their delta
- detect_audio_punches: Percussion/plowsive transient peaks mapped to frames
"""
import json
import math
import os
import re
import struct
import subprocess

def measure_audio_silence(file_path, start=None, duration=None):
    """Detects audio silence and content presence using FFmpeg volumedetect.
    Returns dict with max_volume, mean_volume, speech_max_volume, speech_mean_volume,
    is_silent, and has_content flags.

    start/duration seek to a window of the file (the per-shot segment of a
    concatenated full video), the same way measure_audio_loudness does."""
    seek = []
    if start is not None:
        seek += ["-ss", f"{start:.3f}"]
    if duration is not None:
        seek += ["-t", f"{duration:.3f}"]
    cmd = ["ffmpeg", "-hide_banner"] + seek + ["-i", file_path, "-af", "volumedetect", "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    m_max = re.search(r"max_volume:\s*([-\d.]+)\s*dB", res.stderr)
    m_mean = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", res.stderr)
    max_v = float(m_max.group(1)) if m_max else -99.0
    mean_v = float(m_mean.group(1)) if m_mean else -99.0
    is_silent = (max_v < -45.0 or mean_v < -55.0)

    # Content measurement: speech frequency band (300Hz - 3400Hz).
    # Real speech or foreground audio has solid energy in this band.
    cmd_sp = ["ffmpeg", "-hide_banner"] + seek + ["-i", file_path,
              "-af", "highpass=f=300,lowpass=f=3400,volumedetect", "-f", "null", "-"]
    res_sp = subprocess.run(cmd_sp, capture_output=True, text=True)
    m_sp_max = re.search(r"max_volume:\s*([-\d.]+)\s*dB", res_sp.stderr)
    m_sp_mean = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", res_sp.stderr)
    sp_max = float(m_sp_max.group(1)) if m_sp_max else -99.0
    sp_mean = float(m_sp_mean.group(1)) if m_sp_mean else -99.0
    has_content = (sp_max >= -25.0 and sp_mean >= -45.0)

    return {
        "max_volume": max_v,
        "mean_volume": mean_v,
        "speech_max_volume": sp_max,
        "speech_mean_volume": sp_mean,
        "is_silent": is_silent,
        "has_content": has_content,
    }


def measure_audio_loudness(file_path, start=None, duration=None):
    """Measures Integrated Loudness (LUFS) using FFmpeg EBU R128 filter.
    Optional start/duration window a seek to a segment (per-shot loudness in a
    concatenated full video)."""
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


def detect_audio_punches(file_path, fps=30, max_punches=6, min_gap_sec=0.45,
                         threshold_sigma=1.6, highpass_hz=180):
    """Detect percussion hits / vocal plosive / sub-bass transient peaks (Audio-to-Punches) in an audio/video file.

    Computes spectral/energy flux per video frame (with configurable `highpass_hz`: set `180`
    for opera percussion/speech plosives, or `0` / `40` for EDM/cinematic sub-bass kicks),
    identifies local transient peaks exceeding `mean + threshold_sigma * std`, and enforces
    a minimum inter-onset gap (`min_gap_sec`) via non-maximum suppression.
    Returns a dict with `punches` (sorted frame indices) and `peaks` (detailed frame/time/flux).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"audio file not found: {file_path}")

    sr = 16000
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-i", file_path]
    if highpass_hz and float(highpass_hz) > 0:
        cmd += ["-af", f"highpass=f={float(highpass_hz):.0f}"]
    cmd += ["-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    res = subprocess.run(cmd, capture_output=True)
    pcm = res.stdout
    n_samples = len(pcm) // 2
    if n_samples < sr // 10:
        return {"punches": [], "peaks": []}

    samples_per_frame = max(1, int(round(sr / max(1, fps))))
    n_frames = n_samples // samples_per_frame
    if n_frames < 3:
        return {"punches": [], "peaks": []}

    energies = []
    for f in range(n_frames):
        off = f * samples_per_frame * 2
        chunk = pcm[off:off + samples_per_frame * 2]
        cnt = len(chunk) // 2
        if cnt == 0:
            energies.append(0.0)
            continue
        vals = struct.unpack(f"<{cnt}h", chunk)
        rms = math.sqrt(sum(v * v for v in vals) / cnt) / 32768.0
        energies.append(rms)

    flux = [0.0]
    for f in range(1, n_frames):
        flux.append(max(0.0, energies[f] - energies[f - 1]))

    mean_f = sum(flux) / len(flux)
    var_f = sum((x - mean_f) ** 2 for x in flux) / len(flux)
    std_f = math.sqrt(var_f)
    thresh = mean_f + threshold_sigma * std_f

    candidates = []
    for f in range(3, n_frames - 3):
        if flux[f] >= thresh and flux[f] >= flux[f - 1] and flux[f] >= flux[f + 1]:
            candidates.append((flux[f], f))

    candidates.sort(reverse=True)
    min_gap_frames = max(2, int(round(min_gap_sec * fps)))
    selected = []
    for score, f in candidates:
        if all(abs(f - sel_f) >= min_gap_frames for _, sel_f in selected):
            selected.append((score, f))
            if len(selected) >= max_punches:
                break

    selected.sort(key=lambda item: item[1])
    return {
        "punches": [f for _, f in selected],
        "peaks": [
            {"frame": f, "time_sec": round(f / max(1, fps), 3), "flux": round(score, 4)}
            for score, f in selected
        ],
    }
