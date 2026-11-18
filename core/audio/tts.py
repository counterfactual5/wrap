"""Text-to-speech synthesis with cadence extraction and broadcast mastering.

- synthesize_voiceover: synthesize text to speech + broadcast mastering (Edge TTS first, then macOS say)
- synthesize_voiceover_with_timings: synthesizes voiceover and extracts sentence/clause frame boundaries

TTS is completely OPTIONAL. When used, speech fails loudly if every provider is
unavailable — synthetic tones are never substituted for the requested narration,
and the requested narrator is never swapped for another one.
Generated audio is frozen to assets/tts_{hash}.wav as a deterministic local cache.
"""
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request

from core.runtime.config import ROOT
from core.runtime import manifest
from core.runtime.timeouts import (
    LOCAL_TOOL_TIMEOUT,
    NETWORK_FETCH_TIMEOUT,
    PROBE_TIMEOUT,
    SAY_BASE_TIMEOUT,
    VOICE_LIST_TIMEOUT,
    say_timeout,
)
from core.audio.integrity import _identity, register_audio, verify_audio

# The neutral speech rate: "no change from the provider's own default".
DEFAULT_SPEECH_RATE = "+0%"

# macOS `say` speaks at a fixed number of words per minute; the declared rate
# is a percentage change on the provider's default speed, so the `say`
# fallback derives its own wpm from the same percentage.
SAY_BASE_WPM = 175

# `say -v '?'` prints one voice per line:
#   <name><padding><locale><padding># <sample sentence>
# The name may contain spaces ("Bad News") and the locale is not always
# two-letter-plus-two-letter ("ar_001"), so the line is parsed on the locale
# token and the trailing "#".
SAY_VOICE_LINE = re.compile(r"^(?P<name>.+?)\s+(?P<locale>[a-z]{2}_\S+)\s+#")

# Voice names `say` actually has, filled on first use.
_SAY_VOICES = None


def get_audio_duration(file_path):
    """The duration of an audio file in seconds.

    Raises RuntimeError when the duration cannot be measured. A missing or
    broken file is not a zero-length file: reporting 0.0 here would let a
    voiceover that was never measured pass the truncation gate.
    """
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True,
                         timeout=PROBE_TIMEOUT)
    if res.returncode != 0:
        raise RuntimeError(
            f"ffprobe exited {res.returncode} while measuring the duration of "
            f"{file_path}: {' '.join((res.stderr or '').split())[-400:]}")
    try:
        return float(res.stdout.strip())
    except (TypeError, ValueError) as ex:
        raise RuntimeError(
            f"ffprobe returned no usable duration for {file_path}: "
            f"{res.stdout!r}") from ex


def resolve_speech_rate(declared):
    """The declared speech rate, validated.

    An undeclared rate is handled by the caller (it gets the neutral
    DEFAULT_SPEECH_RATE). A rate that IS declared but empty is an error:
    the author wrote something and meant it, and quietly replacing it with
    "+0%" would hide the mistake.
    """
    text = "" if declared is None else str(declared).strip()
    if not text:
        raise ValueError(
            "audio.rate is declared but empty — declare a rate such as '+10%' "
            "or remove the field entirely")
    return text


def _say_voices():
    """The voice names macOS `say` has, as {casefolded name: canonical name}.

    An empty dict means the list could not be read (no `say` on this machine,
    or the command failed) — the caller must treat that as "the provider is
    unavailable", never as "the voice is fine".
    """
    global _SAY_VOICES
    if _SAY_VOICES is not None:
        return _SAY_VOICES
    voices = {}
    try:
        res = subprocess.run(["say", "-v", "?"], capture_output=True, text=True,
                         timeout=VOICE_LIST_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as ex:
        print(f"macOS say voice list unavailable: {ex}")
        _SAY_VOICES = voices
        return voices
    if res.returncode != 0:
        print(f"macOS say voice list unavailable: exit {res.returncode}")
        _SAY_VOICES = voices
        return voices
    for line in (res.stdout or "").splitlines():
        m = SAY_VOICE_LINE.match(line.strip())
        if m:
            voices[m.group("name").casefold()] = m.group("name")
    _SAY_VOICES = voices
    return voices


def _resolve_say_voice(voice):
    """The canonical macOS voice name for `voice`, or None when there is none.

    macOS `say` accepts an unknown voice name without complaining: it exits 0
    and speaks with the SYSTEM DEFAULT voice. That silent swap of the
    narrator is exactly what must not happen, so the name is checked against
    the list `say -v '?'` prints.
    """
    voices = _say_voices()
    if not voices:
        return None
    return voices.get(str(voice).strip().casefold())


def _say_wpm(rate):
    """Words per minute for macOS `say`, derived from the declared rate."""
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", str(rate or ""))
    if not m:
        return SAY_BASE_WPM
    pct = float(m.group(1))
    return max(60, int(round(SAY_BASE_WPM * (1.0 + pct / 100.0))))


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
    """Google Translate TTS — NOT part of the synthesis chain.

    It speaks literal text and ignores the requested voice, so wiring it in
    would silently replace the requested narrator. It is kept exported for API
    compatibility only; the engine never calls it.
    """
    encoded = urllib.parse.quote(text)
    url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={encoded}&tl=zh-CN&client=tw-ob"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, timeout=NETWORK_FETCH_TIMEOUT) as resp, open(out_mp3, "wb") as f:
        f.write(resp.read())


def synthesize_voiceover_with_timings(text, voice, out_path=None, rate=DEFAULT_SPEECH_RATE):
    """Synthesize voiceover and return (out_path, duration_sec, boundaries).

    TTS is OPTIONAL. No voice is chosen by the engine — the caller must name
    the voice. Synthesis never silently substitutes narrators for the
    requested one; when every provider is unavailable it raises an exception.
    """
    if not voice:
        raise ValueError("voice must be specified explicitly; the engine ships no default narrator")
    rate = resolve_speech_rate(rate)
    with tempfile.TemporaryDirectory(prefix="wrap-tts-") as temp_dir:
        return _synthesize_voiceover_with_timings(text, voice, out_path, rate, temp_dir)


def _synthesize_voiceover_with_timings(text, voice, out_path, rate, temp_dir):
    import hashlib
    import shutil

    if not out_path:
        out_path = os.path.join(ROOT, ".tmp", "voiceover.wav")
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # Deterministic asset freeze key based on voice, rate, and normalized text
    tts_key = hashlib.sha256(f"{voice}_{rate}_{text.strip()}".encode("utf-8")).hexdigest()[:16]
    assets_dir = os.path.join(ROOT, "assets")
    cached_wav = os.path.join(assets_dir, f"tts_{tts_key}.wav")
    cached_meta = os.path.join(assets_dir, f"tts_{tts_key}.meta.json")

    # Existing cache bytes or ledger entries must be checked before regeneration.
    entries = manifest.load()["assets"]
    wav_key = _identity(cached_wav)[2]
    meta_key = _identity(cached_meta)[2]
    wav_exists = os.path.exists(cached_wav)
    meta_exists = os.path.exists(cached_meta)
    if wav_exists and meta_exists:
        verify_audio(cached_wav)
        verify_audio(cached_meta)
        with open(cached_meta, "r", encoding="utf-8") as f:
            cm = json.load(f)
        dur = float(cm["duration"])
        boundaries = cm["boundaries"]
        shutil.copyfile(cached_wav, out_path)
        return out_path, dur, boundaries
    if wav_exists or meta_exists:
        # HALF-WRITTEN cache entry: the process died between the two writes.
        # This is not a cache hit — reading it would fail on the missing half,
        # and the error would point at the metadata instead of the cause.
        print(f"TTS cache entry incomplete ({os.path.basename(cached_wav)} / "
              f"{os.path.basename(cached_meta)}); regenerating")
    elif wav_key in entries or meta_key in entries:
        # The ledger references cache files that are gone from disk: that is
        # an integrity failure, not a cold cache. verify_audio raises.
        verify_audio(cached_wav)
        verify_audio(cached_meta)

    raw_audio = os.path.join(temp_dir, "raw_voice.mp3")
    tts_success = False
    boundaries = []
    provider = None
    provider_notes = []

    # Edge neural TTS (or the voice the caller explicitly named).
    try:
        boundaries = _download_edge_tts(text, voice=voice, rate=rate, out_mp3=raw_audio)
        if os.path.exists(raw_audio) and os.path.getsize(raw_audio) > 1000:
            tts_success = True
            provider = "edge_tts"
    except Exception as ex:
        provider_notes.append(f"edge-tts: {ex}")
        print(f"Edge TTS unavailable: {ex}")

    # macOS say, only for the explicitly named voice. The voice name is
    # verified first: `say` accepts an unknown name and speaks with the
    # SYSTEM DEFAULT voice instead, which would ship the wrong narrator.
    if not tts_success:
        voices = _say_voices()
        if not voices:
            raise RuntimeError(
                f"TTS synthesis failed for voice {voice!r}: "
                + "; ".join(provider_notes + ["macOS say is not available on this machine"])
                + " — install edge-tts, or provide a final voiceover file "
                  "(.wav/.mp3/.m4a) instead")
        say_voice = _resolve_say_voice(voice)
        if say_voice is None:
            raise RuntimeError(
                f"TTS synthesis failed for voice {voice!r}: it is not an installed "
                f"macOS `say` voice, and `say` would silently speak it with the "
                f"system default voice instead"
                + (f" (edge-tts failed: {'; '.join(provider_notes)})" if provider_notes else "")
                + " — name an installed voice (`say -v '?'` lists them), install "
                  "edge-tts, or provide a final voiceover file (.wav/.mp3/.m4a)")
        wpm = _say_wpm(rate)
        tmp_aiff = os.path.join(temp_dir, "temp_speech.aiff")
        try:
            # `say` can block on a stuck audio device — budget follows the
            # narration's length, because that is what decides its runtime.
            subprocess.run(["say", "-v", say_voice, "-r", str(wpm), text, "-o", tmp_aiff],
                           check=True, timeout=say_timeout(text))
            if os.path.exists(tmp_aiff) and os.path.getsize(tmp_aiff) > 4096 and get_audio_duration(tmp_aiff) > 0.5:
                raw_audio = tmp_aiff
                tts_success = True
                provider = "macos_say"
                provider_notes.append(
                    f"macOS say spoke the request with {say_voice!r} at {wpm} wpm "
                    f"(rate {rate})")
        except Exception as ex:
            provider_notes.append(f"macOS say: {ex}")
            print(f"macOS say fallback: {ex}")

    # 4. Deterministic TTS is required. Never substitute synthetic tones for a
    # requested narration: that would make a broken production look successful.
    if not tts_success:
        raise RuntimeError(
            f"TTS synthesis failed for every available provider (Edge TTS, macOS say): "
            f"{'; '.join(provider_notes)}; "
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
    ], check=True, timeout=LOCAL_TOOL_TIMEOUT)

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
            "provider": provider,
            "provider_notes": provider_notes,
        }, f, ensure_ascii=False, indent=2)
    register_audio(cached_wav)
    register_audio(cached_meta)

    return out_path, dur, boundaries


def synthesize_voiceover(text, voice, out_path=None):
    """Synthesize a voiceover and return the path to the mastered audio.

    `voice` is REQUIRED: the engine ships no default narrator, and a default
    would silently hand the author a voice they never asked for.
    """
    out_path, _, _ = synthesize_voiceover_with_timings(text, voice=voice, out_path=out_path)
    return out_path
