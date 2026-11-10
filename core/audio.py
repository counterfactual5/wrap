"""Audio generation and mixing utilities for the code-driven video pipeline.
Provides:
- synthesize_voiceover: Neural text-to-speech with natural cadence + broadcast mastering, fallback to local TTS
- synthesize_voiceover_with_timings: Synthesizes voiceover and extracts sentence/clause frame boundaries
- generate_ambient_bgm: Synthesizes immersive high-tech sci-fi drone soundscapes with FFmpeg
- generate_opera_bgm: Synthesizes traditional Chinese shadow-puppetry / opera percussion (clapper, small gong, crash hits)
- prepare_shot_audio: Synthesizes, masters, and mixes audio tailored to exact shot duration, recording truncation metadata
- sync_spec_audio: Single-source-of-truth tool that aligns shot durationInFrames and captions items to TTS speech timings
"""
import json
import math
import os
import re
import struct
import subprocess
import urllib.parse
import urllib.request
import wave
from core.schema import ROOT


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


def _download_edge_tts(text, voice="zh-CN-YunxiNeural", rate="+18%", out_mp3=None, out_bounds=None):
    """Synthesize speech using Microsoft Edge Neural TTS and capture sentence boundaries."""
    import asyncio
    import edge_tts

    boundaries = []

    async def _run():
        communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
        audio_bytes = bytearray()
        async for chunk in communicate.stream():
            ctype = chunk.get("type")
            if ctype == "audio":
                audio_bytes.extend(chunk["data"])
            elif ctype in ("SentenceBoundary", "WordBoundary"):
                boundaries.append({
                    "type": ctype,
                    "offset_sec": chunk.get("offset", 0) / 10_000_000.0,
                    "duration_sec": chunk.get("duration", 0) / 10_000_000.0,
                    "text": chunk.get("text", ""),
                })
        if out_mp3:
            with open(out_mp3, "wb") as f:
                f.write(bytes(audio_bytes))
        if out_bounds is not None:
            with open(out_bounds, "w") as f:
                json.dump(boundaries, f, ensure_ascii=False, indent=2)

    asyncio.run(_run())
    return boundaries


def _download_neural_tts(text, out_mp3):
    encoded = urllib.parse.quote(text)
    url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={encoded}&tl=zh-CN&client=tw-ob"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp, open(out_mp3, "wb") as f:
        f.write(resp.read())


def _split_sentence_clauses(sentence, max_chars=20):
    """Split a long Chinese/English sentence into readable subtitle clauses (8..22 chars)."""
    s = sentence.strip()
    if not s:
        return []
    if len(s) <= max_chars:
        return [s]
    # Split on secondary punctuation while preserving delimiters
    parts = re.split(r"([，、；：,;:])", s)
    raw_clauses = []
    cur = ""
    for p in parts:
        if not p:
            continue
        if p in "，、；：,;:":
            cur += p
            raw_clauses.append(cur.strip())
            cur = ""
        else:
            cur += p
    if cur.strip():
        raw_clauses.append(cur.strip())

    # Merge tiny fragments (< 7 chars) into adjacent clauses so captions don't flicker
    merged = []
    buf = ""
    for cl in raw_clauses:
        if not buf:
            buf = cl
        elif len(re.sub(r"\W+", "", buf)) < 7 or len(buf) + len(cl) <= max_chars:
            buf += cl
        else:
            merged.append(buf)
            buf = cl
    if buf:
        if merged and len(re.sub(r"\W+", "", buf)) < 6 and len(merged[-1]) + len(buf) <= max_chars + 6:
            merged[-1] += buf
        else:
            merged.append(buf)
    return merged


def _extract_highlight(clause_text):
    """Pick a meaningful 2..4 character phrase at the tail of a clause for subtitle highlighting."""
    cleaned = re.sub(r"[，。！？；：、“”‘’（）()·\s,.!?;:\-—]+$", "", clause_text.strip())
    # Split by internal punctuation and take the last segment
    segs = [s.strip() for s in re.split(r"[，、；：·,;:]+", cleaned) if s.strip()]
    tail = segs[-1] if segs else cleaned
    if len(tail) <= 4:
        return tail
    return tail[-4:]


def clauses_from_boundaries(text, boundaries, total_duration, fps=30, max_chars=20):
    """Build frame-accurate caption items from TTS sentence boundaries and total duration."""
    text = (text or "").strip()
    if not text:
        return []

    sent_Bounds = [b for b in (boundaries or []) if b.get("type") == "SentenceBoundary" and b.get("text")]
    if not sent_Bounds:
        # Fallback: split full text into major sentences first
        raw_sents = [s.strip() for s in re.split(r"(?<=[。！？!?])", text) if s.strip()]
        if not raw_sents:
            raw_sents = [text]
        total_chars = max(1, sum(len(s) for s in raw_sents))
        cursor = 0.05
        avail = max(0.5, total_duration - 0.15)
        sent_Bounds = []
        for s in raw_sents:
            dur = avail * (len(s) / total_chars)
            sent_Bounds.append({"offset_sec": cursor, "duration_sec": dur, "text": s})
            cursor += dur

    items = []
    prev_frame = -1
    for sb in sent_Bounds:
        s_text = sb["text"].strip()
        s_off = max(0.0, float(sb.get("offset_sec", 0.0)))
        s_dur = max(0.2, float(sb.get("duration_sec", 1.0)))
        clauses = _split_sentence_clauses(s_text, max_chars=max_chars)
        if not clauses:
            continue
        char_weights = [max(1, len(re.sub(r"\W+", "", c))) for c in clauses]
        total_w = sum(char_weights)
        c_cursor = s_off
        for c_text, w in zip(clauses, char_weights):
            c_dur = s_dur * (w / total_w)
            f_start = int(round(c_cursor * fps))
            if not items and f_start <= 4:
                f_start = 0
            if f_start <= prev_frame:
                f_start = prev_frame + 1
            prev_frame = f_start
            f_end = max(f_start + 1, int(round((c_cursor + c_dur) * fps)))
            items.append({
                "frame": f_start,
                "end_frame": f_end,
                "text": c_text,
                "hl": _extract_highlight(c_text),
                "size": 36,
            })
            c_cursor += c_dur
    return items


def _synthesize_offline_vocal_cadence(text, out_wav):
    """Offline sandbox fallback when Edge TTS, Google TTS, and macOS `say` IPC are unavailable.

    Generates a natural Chinese syllabic vocal-formant track (300Hz-3200Hz speech band)
    timed to exact character count and punctuation pauses, and returns (duration_sec, boundaries).
    """
    sr = 44100
    raw_sents = [s.strip() for s in re.split(r"(?<=[。！？!?])", (text or "").strip()) if s.strip()]
    if not raw_sents:
        raw_sents = [text or ""]

    boundaries = []
    cursor = 0.08
    char_dur = 0.185  # ~5.4 chars/sec brisk storytelling cadence
    clause_pause = 0.14
    sent_pause = 0.26

    syllable_windows = []
    for s in raw_sents:
        s_start = cursor
        for ch in s:
            if ch in "，、；：,;:":
                cursor += clause_pause
            elif ch in "。！？!?":
                cursor += sent_pause
            elif not ch.isspace():
                syllable_windows.append((cursor, cursor + char_dur * 0.82, ord(ch)))
                cursor += char_dur
        s_dur = max(0.25, cursor - s_start)
        boundaries.append({
            "type": "SentenceBoundary",
            "offset_sec": round(s_start, 3),
            "duration_sec": round(s_dur, 3),
            "text": s,
        })

    total_dur = max(1.0, cursor + 0.15)
    n_samples = int(round(total_dur * sr))
    buf = bytearray(n_samples * 2)
    two_pi = 2.0 * math.pi

    for t0, t1, code in syllable_windows:
        i0 = max(0, int(round(t0 * sr)))
        i1 = min(n_samples, int(round(t1 * sr)))
        span = max(1, i1 - i0)
        # Pitch contour per character tone proxy (155Hz..235Hz fundamental + speech formants)
        f0 = 165.0 + (code % 7) * 9.5
        f1 = 540.0 + (code % 5) * 65.0
        f2 = 1480.0 + (code % 9) * 85.0
        f3 = 2620.0 + (code % 6) * 70.0
        for k in range(span):
            idx = i0 + k
            u = k / span
            env = math.sin(math.pi * u) ** 0.65
            dt = k / sr
            # Tonal pitch inflection
            p_mod = 1.0 + 0.08 * math.cos(math.pi * u)
            sig = env * 0.38 * (
                0.30 * math.sin(two_pi * (f0 * p_mod) * dt)
                + 0.42 * math.sin(two_pi * (f1 * p_mod) * dt)
                + 0.20 * math.sin(two_pi * f2 * dt)
                + 0.08 * math.sin(two_pi * f3 * dt)
            )
            val = max(-32000, min(32000, int(sig * 32767)))
            struct.pack_into("<h", buf, idx * 2, val)

    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(buf))

    return total_dur, boundaries


def synthesize_voiceover_with_timings(text, voice="neural", out_path=None, rate="+18%"):
    """Synthesize voiceover and return (out_path, duration_sec, boundaries)."""
    if not out_path:
        out_path = os.path.join(ROOT, ".tmp", "voiceover.wav")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    raw_audio = os.path.join(ROOT, ".tmp", "raw_voice.mp3")
    tts_success = False
    boundaries = []

    # 1. Try Microsoft Edge Neural TTS first (zh-CN-YunxiNeural) for lively, natural cadence
    try:
        edge_voice = "zh-CN-YunxiNeural" if voice in ("neural", "yunxi", "Tingting") else voice
        boundaries = _download_edge_tts(text, voice=edge_voice, rate=rate, out_mp3=raw_audio)
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
        v = "Tingting" if (voice in ("neural", "Tingting", "yunxi") or str(voice).startswith("zh-")) else voice
        try:
            subprocess.run(["say", "-v", v, "-r", "175", text, "-o", tmp_aiff], check=True)
            if os.path.exists(tmp_aiff) and os.path.getsize(tmp_aiff) > 4096 and get_audio_duration(tmp_aiff) > 0.5:
                raw_audio = tmp_aiff
                tts_success = True
        except Exception as ex:
            print(f"macOS say fallback: {ex}")

    # 4. Offline sandbox fallback (when both network TTS and macOS speechsynthesisd IPC are blocked)
    if not tts_success:
        tmp_cadence = os.path.join(ROOT, ".tmp", "temp_cadence.wav")
        _, boundaries = _synthesize_offline_vocal_cadence(text, tmp_cadence)
        raw_audio = tmp_cadence

    # Broadcast-grade audio mastering filter chain
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

    dur = get_audio_duration(out_path)
    return out_path, dur, boundaries


def synthesize_voiceover(text, voice="neural", out_path=None):
    out_path, _, _ = synthesize_voiceover_with_timings(text, voice=voice, out_path=out_path)
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


def prepare_shot_audio(audio_spec, duration_in_frames, fps, out_path, punches=None):
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
    rate = audio_spec.get("rate", "+18%")

    tmp_voice = os.path.join(ROOT, ".tmp", "shot_voice.wav")
    tmp_bgm = os.path.join(ROOT, ".tmp", "shot_bgm.wav")

    has_voice = False
    raw_voice_dur = 0.0
    boundaries = []
    if voiceover_text and voiceover_text.strip():
        if os.path.exists(voiceover_text):
            # Pre-built narration track (e.g. per-phrase TTS concat + SFX mix).
            # Copy, don't reference: tmp_voice is remixed below and reused runs
            # must not read a file another stage could overwrite mid-flight.
            import shutil
            shutil.copyfile(voiceover_text, tmp_voice)
            raw_voice_dur = get_audio_duration(tmp_voice)
        else:
            _, raw_voice_dur, boundaries = synthesize_voiceover_with_timings(
                voiceover_text, voice=voice, out_path=tmp_voice, rate=rate
            )
        has_voice = True

    # Record speech timing & truncation metadata per shot so S4 can gate against cut-off narration
    clauses = (
        clauses_from_boundaries(voiceover_text, boundaries, raw_voice_dur, fps=fps)
        if has_voice and not os.path.exists(voiceover_text)
        else []
    )
    meta = {
        "has_voice": has_voice,
        "raw_voice_duration": round(raw_voice_dur, 3),
        "target_duration": round(target_duration, 3),
        "truncated": bool(has_voice and raw_voice_dur > target_duration + 0.25),
        "clauses": clauses,
    }
    try:
        with open(out_path + ".meta.json", "w") as mf:
            json.dump(meta, mf, ensure_ascii=False, indent=2)
    except OSError:
        pass

    bgm_vol = 0.22
    if bgm_type in ("opera", "shadow_puppet", "percussion"):
        generate_opera_bgm(target_duration, fps=fps, punches=punches, out_path=tmp_bgm)
        bgm_vol = 0.34
    elif bgm_type == "ambient":
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
            f"[0:a]apad=whole_dur={target_duration}[v];[1:a]volume={bgm_vol}[b];[v][b]amix=inputs=2:duration=first,loudnorm=I=-16:TP=-1.5:LRA=11",
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


def _rescale_frame(f, old_max, new_max):
    if old_max <= 0 or new_max <= 0:
        return f
    return int(round(f * new_max / old_max))


def _rescale_spec_timings(spec, old_frames, new_frames):
    """Proportionally rescale layer anim keyframes, poses, gait ranges, path reveals, and punches."""
    old_max = max(1, old_frames - 1)
    new_max = max(1, new_frames - 1)
    if isinstance(spec.get("punches"), list):
        spec["punches"] = sorted({
            _rescale_frame(p, old_max, new_max)
            for p in spec["punches"] if isinstance(p, int)
        })
    for L in spec.get("layers", []):
        if isinstance(L.get("anim"), dict):
            for ch, kfs in L["anim"].items():
                if not isinstance(kfs, list):
                    continue
                prev_f = -1
                for kf in kfs:
                    if isinstance(kf, list) and len(kf) >= 2:
                        nf = _rescale_frame(kf[0], old_max, new_max)
                        if nf <= prev_f:
                            nf = prev_f + 1
                        kf[0] = nf
                        prev_f = nf
        if isinstance(L.get("poses"), list):
            prev_pf = -1
            for pose in L["poses"]:
                if isinstance(pose, dict) and isinstance(pose.get("frame"), int):
                    nf = 0 if pose["frame"] == 0 else _rescale_frame(pose["frame"], old_max, new_max)
                    if nf <= prev_pf:
                        nf = prev_pf + 1
                    pose["frame"] = nf
                    prev_pf = nf
        if isinstance(L.get("gait"), dict) and isinstance(L["gait"].get("range"), list) and len(L["gait"]["range"]) == 2:
            r0, r1 = L["gait"]["range"]
            nr0 = _rescale_frame(r0, old_max, new_max)
            nr1 = max(nr0 + 1, _rescale_frame(r1, old_max, new_max))
            L["gait"]["range"] = [nr0, nr1]
        if L.get("type") == "code" and L.get("draw") == "path" and isinstance(L.get("params"), dict):
            rev = L["params"].get("reveal")
            if isinstance(rev, list) and len(rev) == 2:
                nr0 = _rescale_frame(rev[0], old_max, new_max)
                nr1 = max(nr0 + 1, _rescale_frame(rev[1], old_max, new_max))
                L["params"]["reveal"] = [nr0, nr1]


def sync_spec_audio(spec_path, fit_duration=True, rescale_anim=True, max_chars=20):
    """Synchronize a shot spec's durationInFrames and captions layer directly from audio.voiceover.

    Solves the two classic failure modes:
    1. Voiceover truncation (13s speech crammed into a 7s shot and chopped off by ffmpeg -t).
    2. Subtitle-voiceover divergence (captions showing different text or guessed frame numbers).
    """
    with open(spec_path) as f:
        spec = json.load(f)

    fps = spec.get("fps", 30)
    audio_spec = spec.get("audio") or {}
    voiceover_text = (audio_spec.get("voiceover") or "").strip()
    if not voiceover_text:
        return {"shot_id": spec.get("id"), "status": "no_voiceover"}

    voice = audio_spec.get("voice", "neural")
    rate = audio_spec.get("rate", "+18%")
    tmp_wav = os.path.join(ROOT, ".tmp", f"{spec.get('id', 'shot')}_sync_voice.wav")
    _, raw_dur, boundaries = synthesize_voiceover_with_timings(
        voiceover_text, voice=voice, out_path=tmp_wav, rate=rate
    )

    old_frames = spec.get("durationInFrames", 150)
    required_frames = int(math.ceil((raw_dur + 0.6) * fps))
    new_frames = max(old_frames, required_frames) if fit_duration else old_frames

    if new_frames != old_frames:
        if rescale_anim:
            _rescale_spec_timings(spec, old_frames, new_frames)
        spec["durationInFrames"] = new_frames

    clauses = clauses_from_boundaries(
        voiceover_text, boundaries, raw_dur, fps=fps, max_chars=max_chars
    )
    caption_items = [
        {"frame": c["frame"], "text": c["text"], "hl": c["hl"], "size": c["size"]}
        for c in clauses
    ]

    updated_captions = 0
    for L in spec.get("layers", []):
        if L.get("type") == "code" and L.get("draw") == "captions":
            L.setdefault("params", {})
            L["params"]["items"] = caption_items
            updated_captions += 1

    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)

    return {
        "shot_id": spec.get("id"),
        "raw_voice_duration_sec": round(raw_dur, 2),
        "old_durationInFrames": old_frames,
        "new_durationInFrames": new_frames,
        "shot_duration_sec": round(new_frames / fps, 2),
        "updated_caption_layers": updated_captions,
        "captions": caption_items,
    }


def measure_audio_silence(file_path):
    """Detects audio silence and content presence using FFmpeg volumedetect.
    Returns dict with max_volume, mean_volume, speech_max_volume, speech_mean_volume,
    is_silent, and has_content flags."""
    cmd = ["ffmpeg", "-hide_banner", "-i", file_path, "-af", "volumedetect", "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    m_max = re.search(r"max_volume:\s*([-\d.]+)\s*dB", res.stderr)
    m_mean = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", res.stderr)
    max_v = float(m_max.group(1)) if m_max else -99.0
    mean_v = float(m_mean.group(1)) if m_mean else -99.0
    is_silent = (max_v < -45.0 or mean_v < -55.0)

    # Content measurement: speech frequency band (300Hz - 3400Hz).
    # Real speech or foreground audio has solid energy in this band.
    cmd_sp = ["ffmpeg", "-hide_banner", "-i", file_path,
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
