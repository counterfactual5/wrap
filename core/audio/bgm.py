"""Background music generators.

- generate_ambient_bgm: Synthesizes immersive high-tech sci-fi drone soundscapes with FFmpeg
- generate_opera_bgm: Synthesizes traditional Chinese shadow-puppetry / opera percussion (clapper, small gong, crash hits)
"""
import math
import os
import struct
import subprocess
import wave

from core.runtime.config import ROOT

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


def generate_opera_bgm(duration_sec, fps=30, punches=None, out_path=None):
    """Synthesize traditional Chinese shadow-puppetry / Qinqiang opera percussion & string bed.

    Includes:
    - Crisp wooden clapper (梆子/板鼓) stepping cadence (3.6 Hz) for puppet gait rhythm
    - Small opera gong (小锣) metallic pitch-glide accents on beat 4
    - Subtle low pentatonic string resonance (D3-A3) below the speech band
    - Heavy crash gong + woodblock strike hits synchronized to `punches` frames
    """
    if not out_path:
        out_path = os.path.join(ROOT, ".tmp", "opera_bgm.wav")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    sr = 44100
    n_samples = max(1, int(round(duration_sec * sr)))
    buf_l = [0.0] * n_samples
    buf_r = [0.0] * n_samples

    # 1. Subtle pentatonic warm string undertone (D3=146.83Hz, A3=220.0Hz)
    two_pi = 2.0 * math.pi
    for i in range(n_samples):
        t = i / sr
        env = 0.75 + 0.25 * math.sin(two_pi * 0.4 * t)
        drone = (0.07 * math.sin(two_pi * 146.83 * t) + 0.045 * math.sin(two_pi * 220.0 * t)) * env
        buf_l[i] = drone
        buf_r[i] = drone

    def _add_wood_clapper(t_start, amp=0.42, pitch=920.0):
        idx0 = int(round(t_start * sr))
        dur_s = int(0.055 * sr)
        for k in range(dur_s):
            idx = idx0 + k
            if 0 <= idx < n_samples:
                dt = k / sr
                env = math.exp(-dt * 68.0)
                # Resonant hardwood modes (bangzi clapper)
                s = amp * env * (
                    0.65 * math.sin(two_pi * pitch * dt)
                    + 0.35 * math.sin(two_pi * (pitch * 2.08) * dt)
                    + 0.20 * math.sin(two_pi * (pitch * 3.41) * dt)
                )
                buf_l[idx] += s * 1.05
                buf_r[idx] += s * 0.92

    def _add_small_gong(t_start, amp=0.30):
        idx0 = int(round(t_start * sr))
        dur_s = int(0.28 * sr)
        for k in range(dur_s):
            idx = idx0 + k
            if 0 <= idx < n_samples:
                dt = k / sr
                env = math.exp(-dt * 11.5)
                # Characteristic xiaoluo upward pitch bend (380Hz -> 495Hz) + inharmonic partials
                f_inst = 380.0 + 115.0 * (1.0 - math.exp(-dt * 18.0))
                s = amp * env * (
                    0.55 * math.sin(two_pi * f_inst * dt)
                    + 0.30 * math.sin(two_pi * (f_inst * 1.58) * dt)
                    + 0.15 * math.sin(two_pi * (f_inst * 2.73) * dt)
                )
                buf_l[idx] += s * 0.90
                buf_r[idx] += s * 1.08

    def _add_crash_gong(t_start, amp=0.72):
        idx0 = int(round(t_start * sr))
        dur_s = int(0.65 * sr)
        for k in range(dur_s):
            idx = idx0 + k
            if 0 <= idx < n_samples:
                dt = k / sr
                env = math.exp(-dt * 5.2)
                # Daluo downward pitch glide (240Hz -> 175Hz) + rich metallic overtones
                f_inst = 175.0 + 65.0 * math.exp(-dt * 9.0)
                shimmer = math.sin(two_pi * 612.0 * dt + 2.5 * math.sin(two_pi * 193.0 * dt))
                s = amp * env * (
                    0.50 * math.sin(two_pi * f_inst * dt)
                    + 0.28 * math.sin(two_pi * (f_inst * 1.62) * dt)
                    + 0.22 * shimmer
                )
                buf_l[idx] += s
                buf_r[idx] += s

    # 2. Brisk theatrical cadence (3.6 beats/sec = 0.277s per beat)
    beat_sec = 0.28
    t_cur = 0.08
    beat_idx = 0
    while t_cur < duration_sec - 0.1:
        if beat_idx % 4 == 0:
            _add_wood_clapper(t_cur, amp=0.45, pitch=960.0)
            _add_small_gong(t_cur + 0.01, amp=0.25)
        elif beat_idx % 2 == 1:
            _add_wood_clapper(t_cur, amp=0.32, pitch=880.0)
            # Double-tap embellishment on beat 3
            if beat_idx % 4 == 3 and t_cur + 0.13 < duration_sec - 0.1:
                _add_wood_clapper(t_cur + 0.13, amp=0.26, pitch=1020.0)
        else:
            _add_wood_clapper(t_cur, amp=0.35, pitch=910.0)
        t_cur += beat_sec
        beat_idx += 1

    # 3. Stamp dramatic opera crash gong + clapper hits on `punches` frames
    for pf in (punches or []):
        t_hit = float(pf) / max(1, fps)
        if 0.0 <= t_hit < duration_sec:
            _add_wood_clapper(t_hit, amp=0.65, pitch=1040.0)
            _add_crash_gong(t_hit, amp=0.72)

    # Write stereo 16-bit PCM WAV
    raw_bytes = bytearray(n_samples * 4)
    for i in range(n_samples):
        sl = max(-0.98, min(0.98, buf_l[i]))
        sr_v = max(-0.98, min(0.98, buf_r[i]))
        struct.pack_into("<hh", raw_bytes, i * 4, int(sl * 32767), int(sr_v * 32767))

    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(raw_bytes))

    return out_path
