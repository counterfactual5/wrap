"""Audio gate honesty: a measurement that could not be taken must FAIL the gate.

Every defect in this file is the same shape: a probe that failed was reported
as "nothing to check", so the gate passed a shot it had not measured. The
tests below pin the honest behaviour:

  1. a failed ffprobe/ffmpeg measurement fails the gate (it is not "no audio")
  2. a failed loudness measurement fails the gate
  3. missing narration metadata fails the gate (the truncation check is not
     optional once a voiceover is declared)
  4. `bgm: "none"` means "no background music" everywhere
  5. the requested narrator is never swapped for another one
  6. a half-written TTS cache is regenerated, not read
  7. a failed decode is an error, not "no transients"
  8. an unmeasurable duration is an error, not 0.0
  9. the Google TTS path is gone (it ignored the requested voice)
 10. the macOS fallback honours the declared rate
 11. a .aiff/.mp4 voiceover that does not exist is a missing file
 12. a bare output filename does not crash os.makedirs
 13. a relative asset path resolves against ROOT, not the process CWD
 14. a declared-but-empty rate is an error, not a silent "+0%"
 15. the caption short-fragment threshold is one constant
 16. the per-shot scratch files do not pile up
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, REPO_ROOT)

from core import audio
from core.audio import captions as captions_mod
from core.audio import shot as audio_shot
from core.audio import tts as tts_mod
from core.runtime import manifest

GATE_PATH = os.path.join(REPO_ROOT, "stages", "04_gate.py")


def load_gate():
    """The S4 gate as a module (the stage is a script, not an importable package)."""
    module_spec = importlib.util.spec_from_file_location("audio_gate_honesty_gate", GATE_PATH)
    gate = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(gate)
    return gate


def make_silence(path, seconds=1):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=stereo", "-t", str(seconds), path],
                   check=True)
    return path


def make_tone(path, seconds=1, freq=220):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"sine=frequency={freq}:duration={seconds}",
                    "-ar", "44100", "-ac", "2", path], check=True)
    return path


def fake_tool_run(say_calls=None, say_bytes=8192):
    """A subprocess.run stand-in that writes the output file it was asked for."""
    def run(cmd, *args, **kwargs):
        if cmd[0] == "say":
            if say_calls is not None:
                say_calls.append(cmd)
            with open(cmd[-1], "wb") as f:
                f.write(b"x" * say_bytes)
        else:
            with open(cmd[-1], "wb") as f:
                f.write(b"audio")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return run


class IsolatedLedgerMixin:
    """Points the ledger and the audio roots at a temp dir (never the user's)."""

    def isolate(self, tmp):
        env = patch.dict(os.environ, {"POSTER_MANIFEST": os.path.join(tmp, "manifest.json")})
        env.start()
        self.addCleanup(env.stop)
        for module in (tts_mod, manifest):
            p = patch.object(module, "ROOT", tmp)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(manifest, "LOCK_PATH", os.path.join(tmp, "lock"))
        p.start()
        self.addCleanup(p.stop)


class GateTestCase(unittest.TestCase):
    """Drives stages/04_gate.py with the audio measurements mocked out."""

    def setUp(self):
        self.gate = load_gate()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def run_gate(self, spec, **audio_patches):
        """Run the gate over `spec`; returns (exit_code, results)."""
        ctxs = [
            patch.object(self.gate, "ROOT", self.root),
            patch.object(self.gate, "load_spec", return_value=spec),
            patch.object(self.gate, "_verify_measured_object"),
            patch.object(self.gate.manifest, "verified", return_value=None),
            patch.object(sys, "argv", ["04_gate.py"]),
        ]
        for name, value in audio_patches.items():
            ctxs.append(patch.object(audio, name, **value))
        for ctx in ctxs:
            ctx.start()
            self.addCleanup(ctx.stop)
        code = self.gate.main()
        gate_file = os.path.join(self.root, "build", "gates",
                                 f"{spec['id']}.json")
        results = []
        if os.path.exists(gate_file):
            with open(gate_file) as f:
                results = json.load(f)
        return code, results

    @staticmethod
    def base_spec(**extra):
        spec = {"id": "probe-shot", "canvas": {"w": 10, "h": 10}, "fps": 30,
                "durationInFrames": 30, "gates": [], "layers": [],
                "frame_freeze": True}
        spec.update(extra)
        return spec

    @staticmethod
    def probed(**overrides):
        """An ffprobe result for a file that carries an audio track."""
        result = {"measurement_ok": True, "has_audio": True, "delta": 0.0,
                  "video_duration": 1.0, "audio_duration": 1.0, "error": None}
        result.update(overrides)
        return {"return_value": result}

    @staticmethod
    def audible(**overrides):
        """A silence measurement for a track that carries sound."""
        result = {"max_volume": -10.0, "mean_volume": -20.0, "is_silent": False,
                  "has_content": True, "measurement_ok": True}
        result.update(overrides)
        return {"return_value": result}


class TestDefect1ProbeFailureIsNotSilentAudio(GateTestCase):
    """Defect 1: a failed ffprobe was reported as "this file has no audio"."""

    def test_measure_av_durations_reports_a_failed_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = os.path.join(tmp, "not-a-video.mp4")
            with open(broken, "wb") as f:
                f.write(b"this is not a media file")
            probe = audio.measure_av_durations(broken)
        self.assertFalse(probe.get("measurement_ok"),
                         "a failed ffprobe must not look like a successful measurement")
        self.assertFalse(probe.get("has_audio"))
        self.assertIn("ffprobe", probe.get("error", "").lower())

    def test_measure_av_durations_reports_a_missing_file(self):
        probe = audio.measure_av_durations("/nonexistent/shot.mp4")
        self.assertFalse(probe.get("measurement_ok"))

    def test_measure_av_durations_on_a_real_file_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_tone(os.path.join(tmp, "tone.wav"))
            probe = audio.measure_av_durations(path)
        self.assertTrue(probe.get("measurement_ok"))
        self.assertTrue(probe.get("has_audio"))

    def test_gate_fails_when_the_audio_probe_fails(self):
        code, results = self.run_gate(
            self.base_spec(),
            measure_av_durations={"return_value": {
                "measurement_ok": False, "has_audio": False, "delta": 0.0,
                "video_duration": 0.0, "audio_duration": 0.0,
                "error": "ffprobe exited 1 while probing build/probe-shot.mp4: Invalid data"}},
        )
        self.assertEqual(code, 1, "a failed audio probe must FAIL the gate")
        ids = {r["id"]: r for r in results}
        self.assertIn("audio_probe", ids)
        self.assertFalse(ids["audio_probe"]["pass"])


class TestDefect2LoudnessFailureFailsTheGate(GateTestCase):
    """Defect 2: `if lufs is not None` skipped the loudness gate on failure."""

    def test_detail_reports_a_failed_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = os.path.join(tmp, "broken.wav")
            with open(broken, "wb") as f:
                f.write(b"not audio at all")
            detail = audio.measure_audio_loudness_detail(broken)
        self.assertIsNone(detail["lufs"])
        self.assertFalse(detail["measurement_ok"])
        self.assertFalse(detail["silent"])
        self.assertTrue(detail["error"])

    def test_detail_treats_a_silent_track_as_silent_not_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_silence(os.path.join(tmp, "silent.wav"))
            detail = audio.measure_audio_loudness_detail(path)
        self.assertTrue(detail["measurement_ok"], "a silent track is a legitimate measurement")
        self.assertTrue(detail["silent"])

    def test_measure_audio_loudness_still_returns_a_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_tone(os.path.join(tmp, "tone.wav"))
            self.assertIsNotNone(audio.measure_audio_loudness(path))

    def test_gate_fails_when_loudness_cannot_be_measured(self):
        code, results = self.run_gate(
            self.base_spec(audio={"bgm": "music.wav"}),
            measure_av_durations=self.probed(),
            measure_audio_silence=self.audible(),
            measure_audio_loudness_detail={"return_value": {
                "lufs": None, "measurement_ok": False, "silent": False,
                "error": "ffmpeg exited 1 while measuring the loudness"}},
        )
        self.assertEqual(code, 1, "an unmeasurable loudness must FAIL the gate")
        loud = next(r for r in results if r["id"] == "audio_loudness")
        self.assertFalse(loud["pass"])
        self.assertFalse(loud.get("measurement_ok"))

    def test_gate_does_not_fail_on_a_legitimately_silent_loudness_reading(self):
        code, results = self.run_gate(
            self.base_spec(audio={"bgm": "music.wav"}),
            measure_av_durations=self.probed(),
            measure_audio_silence=self.audible(),
            measure_audio_loudness_detail={"return_value": {
                "lufs": None, "measurement_ok": True, "silent": True, "error": None}},
        )
        self.assertEqual(code, 0, "a silent track must not fail the loudness gate on its own")
        loud = next(r for r in results if r["id"] == "audio_loudness")
        self.assertTrue(loud.get("measurement_ok"))


class TestDefect3NarrationMetadataMustExist(GateTestCase):
    """Defect 3: a failed metadata write silently disabled the truncation check."""

    def test_meta_write_failure_propagates(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "shot.aac")
            # A directory where the metadata file belongs: the atomic write
            # cannot replace it, and the failure must not be swallowed.
            os.makedirs(out + ".meta.json")
            with patch.object(audio_shot, "run_two_pass_loudnorm"), \
                    patch("core.audio.shot.subprocess.run"):
                with self.assertRaises(OSError):
                    audio_shot.prepare_shot_audio({}, 30, 30, out)

    def test_meta_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "shot.aac")
            with patch.object(audio_shot, "run_two_pass_loudnorm"), \
                    patch("core.audio.shot.subprocess.run"):
                audio_shot.prepare_shot_audio({}, 30, 30, out)
            with open(out + ".meta.json") as f:
                meta = json.load(f)
            self.assertFalse(meta["has_voice"])
            self.assertFalse(os.path.exists(out + ".meta.json.tmp"),
                             "the temporary metadata file must not survive")

    def test_gate_fails_when_the_narration_metadata_is_missing(self):
        code, results = self.run_gate(
            self.base_spec(audio={"voiceover": "你好", "voice": "TestVoice"}),
            measure_av_durations=self.probed(),
            measure_audio_silence=self.audible(),
            measure_audio_loudness_detail={"return_value": {
                "lufs": -16.0, "measurement_ok": True, "silent": False, "error": None}},
        )
        self.assertEqual(code, 1, "a declared voiceover without metadata must FAIL the gate")
        trunc = next(r for r in results if r["id"] == "voiceover_truncation")
        self.assertFalse(trunc["pass"])

    def test_gate_fails_when_the_narration_metadata_is_unreadable(self):
        os.makedirs(os.path.join(self.root, ".tmp"), exist_ok=True)
        with open(os.path.join(self.root, ".tmp", "probe-shot_audio.aac.meta.json"), "w") as f:
            f.write("{not json")
        code, results = self.run_gate(
            self.base_spec(audio={"voiceover": "你好", "voice": "TestVoice"}),
            measure_av_durations=self.probed(),
            measure_audio_silence=self.audible(),
            measure_audio_loudness_detail={"return_value": {
                "lufs": -16.0, "measurement_ok": True, "silent": False, "error": None}},
        )
        self.assertEqual(code, 1, "unreadable narration metadata must FAIL the gate")
        trunc = next(r for r in results if r["id"] == "voiceover_truncation")
        self.assertFalse(trunc["pass"])


class TestDefect4TheNoBgmSentinel(unittest.TestCase):
    """Defect 4: `bgm: "none"` was read as "this shot has music"."""

    def test_shot_with_bgm_none_is_intentionally_silent(self):
        self.assertTrue(audio.shot_is_intentionally_silent({"audio": {"bgm": "none"}}))
        self.assertTrue(audio.shot_is_intentionally_silent({"audio": {"bgm": "NONE"}}))
        self.assertTrue(audio.shot_is_intentionally_silent({"audio": {"bgm": ""}}))

    def test_shot_with_a_real_bgm_is_not_silent(self):
        self.assertFalse(audio.shot_is_intentionally_silent({"audio": {"bgm": "music.wav"}}))

    def test_encoding_treats_bgm_none_as_no_bgm(self):
        from core.rendering import encoding
        calls = []

        def fake_prepare(audio_spec, frames, fps, out_path, punches=None):
            calls.append(audio_spec)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(b"audio")

        with tempfile.TemporaryDirectory() as tmp:
            spec = {"id": "none-bgm", "fps": 30, "durationInFrames": 30,
                    "layers": [], "audio": {"bgm": "none"}}
            frames_dir = os.path.join(tmp, "frames")
            os.makedirs(frames_dir)
            with patch.object(encoding, "ROOT", tmp), \
                    patch("core.audio.prepare_shot_audio", side_effect=fake_prepare), \
                    patch.object(encoding.subprocess, "run"):
                encoding.encode_mp4(spec, frames_dir, os.path.join(tmp, "out.mp4"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], {},
                         "bgm:'none' must not be treated as a request for a soundtrack")


class TestDefect5TheRequestedNarratorIsNeverSwapped(IsolatedLedgerMixin, unittest.TestCase):
    """Defect 5: `say -v <unknown>` exits 0 and speaks with the default voice."""

    def test_synthesize_voiceover_requires_a_voice(self):
        with self.assertRaises(TypeError):
            tts_mod.synthesize_voiceover("hello")

    def test_unknown_say_voice_fails_instead_of_using_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate(tmp)
            with patch.object(tts_mod, "_download_edge_tts", side_effect=RuntimeError("no network")), \
                    patch.object(tts_mod, "_say_voices", return_value={"samantha": "Samantha"}):
                with self.assertRaises(RuntimeError) as ctx:
                    tts_mod.synthesize_voiceover_with_timings(
                        "hello", voice="definitely_not_a_voice",
                        out_path=os.path.join(tmp, "out.wav"))
        self.assertIn("definitely_not_a_voice", str(ctx.exception))
        self.assertIn("default voice", str(ctx.exception))

    def test_installed_say_voice_is_used_with_its_canonical_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate(tmp)
            say_calls = []
            with patch.object(tts_mod, "_download_edge_tts", side_effect=RuntimeError("no network")), \
                    patch.object(tts_mod, "_say_voices", return_value={"samantha": "Samantha"}), \
                    patch.object(tts_mod, "get_audio_duration", return_value=1.0), \
                    patch.object(tts_mod.subprocess, "run", side_effect=fake_tool_run(say_calls)):
                tts_mod.synthesize_voiceover_with_timings(
                    "hello", voice="samantha", out_path=os.path.join(tmp, "out.wav"))
        self.assertEqual(len(say_calls), 1)
        self.assertEqual(say_calls[0][say_calls[0].index("-v") + 1], "Samantha",
                         "the canonical voice name must be passed to say")


class TestDefect6HalfWrittenTtsCache(IsolatedLedgerMixin, unittest.TestCase):
    """Defect 6: a cache with only one of its two files crashed on the other."""

    def test_half_written_cache_is_regenerated(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate(tmp)
            key = hashlib.sha256(b"voice_+0%_hello").hexdigest()[:16]
            assets = os.path.join(tmp, "assets")
            os.makedirs(assets)
            wav = os.path.join(assets, f"tts_{key}.wav")
            meta = os.path.join(assets, f"tts_{key}.meta.json")
            with open(wav, "wb") as f:
                f.write(b"half written audio")

            def fake_edge(text, voice, rate="+0%", out_mp3=None, out_bounds=None):
                with open(out_mp3, "wb") as f:
                    f.write(b"m" * 4096)
                return []

            with patch.object(tts_mod, "_download_edge_tts", side_effect=fake_edge), \
                    patch.object(tts_mod, "get_audio_duration", return_value=1.0), \
                    patch.object(tts_mod.subprocess, "run", side_effect=fake_tool_run()):
                out = os.path.join(tmp, "out.wav")
                tts_mod.synthesize_voiceover_with_timings("hello", voice="voice", out_path=out)
            self.assertTrue(os.path.exists(out))
            self.assertTrue(os.path.exists(meta),
                            "the regenerated cache must have its metadata back")


class TestDefect7DecodeFailureIsAnError(unittest.TestCase):
    """Defect 7: a failed decode looked like "this track has no transients"."""

    def test_undecodable_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = os.path.join(tmp, "broken.wav")
            with open(broken, "wb") as f:
                f.write(b"definitely not audio")
            with self.assertRaises(RuntimeError) as ctx:
                audio.detect_audio_punches(broken)
        self.assertIn("ffmpeg", str(ctx.exception).lower())

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            audio.detect_audio_punches("/nonexistent/track.wav")


class TestDefect8UnmeasurableDurationIsAnError(unittest.TestCase):
    """Defect 8: every probe failure returned 0.0 seconds."""

    def test_missing_file_raises(self):
        with self.assertRaises(RuntimeError):
            tts_mod.get_audio_duration("/nonexistent/voice.wav")

    def test_corrupt_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = os.path.join(tmp, "broken.wav")
            with open(broken, "wb") as f:
                f.write(b"not audio")
            with self.assertRaises(RuntimeError):
                tts_mod.get_audio_duration(broken)

    def test_real_file_still_measures(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_tone(os.path.join(tmp, "tone.wav"), seconds=2)
            self.assertAlmostEqual(tts_mod.get_audio_duration(path), 2.0, delta=0.2)


class TestDefect9TheGoogleTtsPathIsGone(IsolatedLedgerMixin, unittest.TestCase):
    """Defect 9: the Google TTS branch was dead code that ignored the voice."""

    def test_google_tts_is_not_part_of_the_synthesis_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate(tmp)

            def fake_edge(text, voice, rate="+0%", out_mp3=None, out_bounds=None):
                with open(out_mp3, "wb") as f:
                    f.write(b"m" * 4096)
                return []

            with patch.object(tts_mod, "_download_edge_tts", side_effect=fake_edge), \
                    patch.object(tts_mod, "_download_neural_tts",
                                 side_effect=AssertionError("Google TTS must not be used")), \
                    patch.object(tts_mod, "get_audio_duration", return_value=1.0), \
                    patch.object(tts_mod.subprocess, "run", side_effect=fake_tool_run()):
                tts_mod.synthesize_voiceover_with_timings(
                    "hello", voice="voice", out_path=os.path.join(tmp, "out.wav"))

    def test_the_module_docstring_does_not_claim_a_google_fallback(self):
        doc = tts_mod.__doc__ or ""
        self.assertNotIn("Google TTS", doc)
        self.assertIn("macOS say", doc)


class TestDefect10TheSayFallbackHonoursTheRate(IsolatedLedgerMixin, unittest.TestCase):
    """Defect 10: the macOS fallback hard-coded 175 wpm whatever was declared."""

    def test_say_rate_is_derived_from_the_declared_rate(self):
        self.assertEqual(tts_mod._say_wpm("+0%"), 175)
        self.assertEqual(tts_mod._say_wpm("+10%"), 193)
        self.assertEqual(tts_mod._say_wpm("-20%"), 140)

    def test_the_fallback_records_the_substitution_in_the_cache_metadata(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            self.isolate(tmp)
            say_calls = []
            rate = "+10%"
            key = hashlib.sha256(f"Samantha_{rate}_hello".encode("utf-8")).hexdigest()[:16]
            with patch.object(tts_mod, "_download_edge_tts", side_effect=RuntimeError("no network")), \
                    patch.object(tts_mod, "_say_voices", return_value={"samantha": "Samantha"}), \
                    patch.object(tts_mod, "get_audio_duration", return_value=1.0), \
                    patch.object(tts_mod.subprocess, "run", side_effect=fake_tool_run(say_calls)):
                tts_mod.synthesize_voiceover_with_timings(
                    "hello", voice="Samantha", rate=rate,
                    out_path=os.path.join(tmp, "out.wav"))
            self.assertEqual(say_calls[0][say_calls[0].index("-r") + 1], "193",
                             "say must speak at the declared rate")
            meta_file = os.path.join(tmp, "assets", f"tts_{key}.meta.json")
            with open(meta_file) as f:
                meta = json.load(f)
            self.assertEqual(meta["provider"], "macos_say")
            self.assertEqual(meta["voice"], "Samantha")
            self.assertTrue(any("Samantha" in note for note in meta["provider_notes"]),
                            "the provider substitution must be recorded")


class TestDefect11MediaExtensionsAreFileReferences(unittest.TestCase):
    """Defect 11: a missing .aiff voiceover was read aloud as narration."""

    def test_missing_aiff_voiceover_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                audio_shot.prepare_shot_audio(
                    {"voiceover": "missing-voice.aiff", "voice": "TestVoice"},
                    30, 30, os.path.join(tmp, "out.aac"))

    def test_missing_mp4_voiceover_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                audio_shot.prepare_shot_audio(
                    {"voiceover": "missing-voice.mp4", "voice": "TestVoice"},
                    30, 30, os.path.join(tmp, "out.aac"))

    def test_narration_text_still_needs_a_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                audio_shot.prepare_shot_audio(
                    {"voiceover": "你好世界"},
                    30, 30, os.path.join(tmp, "out.aac"))


class TestDefect12BareOutputFilename(unittest.TestCase):
    """Defect 12: os.makedirs("") crashed for a bare output filename."""

    def test_prepare_shot_audio_accepts_a_bare_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with patch.object(audio_shot, "run_two_pass_loudnorm"), \
                        patch("core.audio.shot.subprocess.run", side_effect=fake_tool_run()):
                    audio_shot.prepare_shot_audio({}, 30, 30, "shot.aac")
                self.assertTrue(os.path.exists(os.path.join(tmp, "shot.aac")))
            finally:
                os.chdir(cwd)

    def test_tts_accepts_a_bare_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                def fake_edge(text, voice, rate="+0%", out_mp3=None, out_bounds=None):
                    with open(out_mp3, "wb") as f:
                        f.write(b"m" * 4096)
                    return []

                env = patch.dict(os.environ, {"POSTER_MANIFEST": os.path.join(tmp, "manifest.json")})
                env.start()
                self.addCleanup(env.stop)
                with patch.object(tts_mod, "ROOT", tmp), \
                        patch.object(tts_mod, "_download_edge_tts", side_effect=fake_edge), \
                        patch.object(tts_mod, "get_audio_duration", return_value=1.0), \
                        patch.object(tts_mod.subprocess, "run", side_effect=fake_tool_run()):
                    tts_mod.synthesize_voiceover_with_timings("hello", voice="voice",
                                                             out_path="voice.wav")
                self.assertTrue(os.path.exists(os.path.join(tmp, "voice.wav")))
            finally:
                os.chdir(cwd)


class TestDefect13RelativePathsResolveAgainstRoot(unittest.TestCase):
    """Defect 13: a relative asset path was resolved against the process CWD."""

    def test_relative_voiceover_resolves_against_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "root")
            elsewhere = os.path.join(tmp, "elsewhere")
            os.makedirs(os.path.join(root, "assets"))
            os.makedirs(elsewhere)
            make_tone(os.path.join(root, "assets", "narration.wav"), seconds=1)
            verified = []

            def fake_verify(path):
                verified.append(path)
                return path

            cwd = os.getcwd()
            os.chdir(elsewhere)
            try:
                with patch.object(audio_shot, "ROOT", root), \
                        patch.object(audio_shot, "verify_audio", side_effect=fake_verify), \
                        patch.object(audio_shot, "run_two_pass_loudnorm"), \
                        patch.object(audio_shot, "get_audio_duration", return_value=1.0):
                    audio_shot.prepare_shot_audio(
                        {"voiceover": "narration.wav", "voice": "TestVoice"},
                        30, 30, os.path.join(root, "out.aac"))
            finally:
                os.chdir(cwd)
        self.assertTrue(verified, "the voiceover file was not found")
        self.assertEqual(verified[0], os.path.join(root, "assets", "narration.wav"))


class TestDefect14DeclaredEmptyRateIsAnError(unittest.TestCase):
    """Defect 14: an explicitly empty rate was silently replaced by "+0%"."""

    def test_resolve_speech_rate_rejects_an_empty_value(self):
        for value in ("", "   ", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    tts_mod.resolve_speech_rate(value)

    def test_shot_audio_rejects_a_declared_empty_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                audio_shot.prepare_shot_audio(
                    {"voiceover": "你好", "voice": "TestVoice", "rate": ""},
                    30, 30, os.path.join(tmp, "out.aac"))

    def test_undeclared_rate_uses_the_neutral_default(self):
        recorded = {}

        def fake_synth(text, voice, out_path, rate):
            recorded["rate"] = rate
            return out_path, 1.0, []

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(audio_shot, "synthesize_voiceover_with_timings",
                              side_effect=fake_synth), \
                    patch.object(audio_shot, "run_two_pass_loudnorm"):
                audio_shot.prepare_shot_audio(
                    {"voiceover": "你好", "voice": "TestVoice"},
                    30, 30, os.path.join(tmp, "out.aac"))
        self.assertEqual(recorded["rate"], "+0%")

    def test_sync_rejects_a_declared_empty_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w") as f:
                json.dump({"id": "shot", "fps": 30, "durationInFrames": 60, "layers": [],
                           "audio": {"voiceover": "你好", "voice": "TestVoice", "rate": ""}}, f)
            from core.audio import sync as sync_mod
            with patch.object(sync_mod, "synthesize_voiceover_with_timings") as synth:
                with self.assertRaises(ValueError):
                    sync_mod.sync_spec_audio(spec_path)
            synth.assert_not_called()


class TestDefect15OneShortFragmentThreshold(unittest.TestCase):
    """Defect 15: the merge loop used 7 while the tail merge used 6."""

    def test_the_middle_merge_uses_the_shared_constant(self):
        limit = captions_mod.CAPTION_SHORT_FRAGMENT
        # A first clause of exactly `limit` word characters: with the old
        # literal 7 it was merged into its neighbour, with the constant it is
        # not — and the tail merge already used the constant.
        first = "一二三四五六七八"[:limit]
        second = "七八九十甲乙丙丁"
        clauses = captions_mod._split_sentence_clauses(f"{first}，{second}", max_chars=8)
        self.assertEqual(clauses, [f"{first}，", second])

    def test_a_shorter_fragment_is_still_merged(self):
        limit = captions_mod.CAPTION_SHORT_FRAGMENT
        first = "一二三四五六七八"[:limit - 1]
        second = "七八九十甲乙丙丁"
        clauses = captions_mod._split_sentence_clauses(f"{first}，{second}", max_chars=8)
        self.assertEqual(clauses, [f"{first}，{second}"])


class TestDefect16ScratchFilesAreCleanedUp(unittest.TestCase):
    """Defect 16: *.voice.wav / *.bgm.wav piled up in .tmp/ forever."""

    def test_scratch_files_do_not_survive_the_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "shot.aac")

            def fake_synth(text, voice, out_path, rate):
                with open(out_path, "wb") as f:
                    f.write(b"voice")
                return out_path, 1.0, []

            def fake_loudnorm(inputs, opt, value, target_dur, out_path):
                with open(out_path, "wb") as f:
                    f.write(b"audio")

            with patch.object(audio_shot, "synthesize_voiceover_with_timings",
                              side_effect=fake_synth), \
                    patch.object(audio_shot, "run_two_pass_loudnorm", side_effect=fake_loudnorm), \
                    patch.object(audio_shot, "verify_audio", side_effect=lambda p: p), \
                    patch.object(audio_shot, "get_audio_duration", return_value=1.0):
                audio_shot.prepare_shot_audio(
                    {"voiceover": "你好", "voice": "TestVoice"},
                    30, 30, out)
            self.assertFalse(os.path.exists(out + ".voice.wav"),
                             "the voice scratch file must not survive")
            self.assertFalse(os.path.exists(out + ".bgm.wav"),
                             "the bgm scratch file must not survive")
            self.assertTrue(os.path.exists(out + ".meta.json"),
                            "the narration metadata must survive")


if __name__ == "__main__":
    unittest.main()
