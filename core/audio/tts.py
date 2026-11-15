"""Text-to-speech synthesis with cadence extraction and broadcast mastering.

- synthesize_voiceover: synthesize text to speech + broadcast mastering (Edge TTS first, then Google TTS, then macOS say)
- synthesize_voiceover_with_timings: synthesizes voiceover and extracts sentence/clause frame boundaries

TTS is completely OPTIONAL. When used, speech fails loudly if every provider is
unavailable — synthetic tones are never substituted for the requested narration.
Generated audio is frozen to assets/tts_{hash}.wav as a deterministic local cache.
"""
import json
import os
import subprocess
import tempfile
import urllib.parse
import urllib.request

from core.runtime.config import ROOT
from core.runtime import manifest
from core.audio.integrity import _identity, register_audio, verify_audio

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


def _download_edge_tts(text, voice, rate="+0%", out_mp3=None, out_bounds=None):
    """Synthesize speech using Microsoft Edge Neural TTS and capture sentence boundaries. The engine carries no default voice — the caller must name one."""
    if not voice:
        raise ValueError("voice must be specified explicitly; the engine ships no default narrator")
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


def synthesize_voiceover_with_timings(text, voice, out_path=None, rate="+0%"):
    """Synthesize voiceover and return (out_path, duration_sec, boundaries).

    TTS is OPTIONAL. No voice is chosen by the engine — the caller must name
    the voice. Synthesis never silently substitutes narrators for the
    requested one; when every provider is unavailable it raises an exception.
    """
    if not voice:
        raise ValueError("voice must be specified explicitly; the engine ships no default narrator")
    if not rate:
        rate = "+0%"
    with tempfile.TemporaryDirectory(prefix="wrap-tts-") as temp_dir:
        return _synthesize_voiceover_with_timings(text, voice, out_path, rate, temp_dir)


def _synthesize_voiceover_with_timings(text, voice, out_path, rate, temp_dir):
    import hashlib
    import shutil

    if not out_path:
        out_path = os.path.join(ROOT, ".tmp", "voiceover.wav")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # Deterministic asset freeze key based on voice, rate, and normalized text
    tts_key = hashlib.sha256(f"{voice}_{rate}_{text.strip()}".encode("utf-8")).hexdigest()[:16]
    assets_dir = os.path.join(ROOT, "assets")
    cached_wav = os.path.join(assets_dir, f"tts_{tts_key}.wav")
    cached_meta = os.path.join(assets_dir, f"tts_{tts_key}.meta.json")

    # Existing cache bytes or ledger entries must be checked before regeneration.
    entries = manifest.load()["assets"]
    if (os.path.exists(cached_wav) or os.path.exists(cached_meta)
            or _identity(cached_wav)[2] in entries or _identity(cached_meta)[2] in entries):
        verify_audio(cached_wav)
        verify_audio(cached_meta)
        with open(cached_meta, "r", encoding="utf-8") as f:
            cm = json.load(f)
        dur = float(cm["duration"])
        boundaries = cm["boundaries"]
        shutil.copyfile(cached_wav, out_path)
        return out_path, dur, boundaries

    raw_audio = os.path.join(temp_dir, "raw_voice.mp3")
    tts_success = False
    boundaries = []

    # Edge neural TTS (or the voice the caller explicitly named).
    try:
        boundaries = _download_edge_tts(text, voice=voice, rate=rate, out_mp3=raw_audio)
        if os.path.exists(raw_audio) and os.path.getsize(raw_audio) > 1000:
            tts_success = True
    except Exception as ex:
        print(f"Edge TTS fallback: {ex}")

    # Google Translate TTS fallback (literal text speech, ignores voice but
    # preserves semantics) only when voice was not explicitly named.
    if not tts_success and not voice:
        try:
            _download_neural_tts(text, raw_audio)
            if os.path.exists(raw_audio) and os.path.getsize(raw_audio) > 1000:
                tts_success = True
        except Exception as ex:
            print(f"Google TTS fallback: {ex}")

    # macOS say, only for the explicitly named voice.
    if not tts_success and voice:
        tmp_aiff = os.path.join(temp_dir, "temp_speech.aiff")
        try:
            subprocess.run(["say", "-v", voice, "-r", "175", text, "-o", tmp_aiff], check=True)
            if os.path.exists(tmp_aiff) and os.path.getsize(tmp_aiff) > 4096 and get_audio_duration(tmp_aiff) > 0.5:
                raw_audio = tmp_aiff
                tts_success = True
        except Exception as ex:
            print(f"macOS say fallback: {ex}")

    # 4. Deterministic TTS is required. Never substitute synthetic tones for a
    # requested narration: that would make a broken production look successful.
    if not tts_success:
        raise RuntimeError(
            f"TTS synthesis failed for every available provider (Edge TTS, Google TTS, macOS say); "
            f"provide a final voiceover file with a .wav/.mp3/.m4a path instead of synthetic tones")

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

    # Freeze synthesized output to assets/ directory for reproducible runs
    os.makedirs(assets_dir, exist_ok=True)
    shutil.copyfile(out_path, cached_wav)
    with open(cached_meta, "w", encoding="utf-8") as f:
        json.dump({
            "duration": round(dur, 3),
            "boundaries": boundaries,
            "text": text,
            "voice": voice,
            "rate": rate,
        }, f, ensure_ascii=False, indent=2)
    register_audio(cached_wav)
    register_audio(cached_meta)

    return out_path, dur, boundaries


def synthesize_voiceover(text, voice="neural", out_path=None):
    out_path, _, _ = synthesize_voiceover_with_timings(text, voice=voice, out_path=out_path)
    return out_path
