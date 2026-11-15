import hashlib
import importlib.util
import sys
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from core.audio import integrity, metrics, shot, tts
from core.runtime import manifest


class AudioIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.env = patch.dict(os.environ, {"POSTER_MANIFEST": os.path.join(self.root, "manifest.json")})
        self.env.start()
        self.addCleanup(self.env.stop)
        for module in (integrity, manifest, tts, shot):
            p = patch.object(module, "ROOT", self.root)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(manifest, "LOCK_PATH", os.path.join(self.root, "lock"))
        p.start()
        self.addCleanup(p.stop)

    def test_external_file_requires_explicit_registration_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as external:
            path = os.path.join(external, "music.wav")
            with open(path, "wb") as f:
                f.write(b"trusted")
            with self.assertRaisesRegex(RuntimeError, "register"):
                integrity.verify_audio(path)
            integrity.register_audio(path)
            self.assertEqual(integrity.verify_audio(path), os.path.realpath(path))
            with open(path, "wb") as f:
                f.write(b"changed")
            with self.assertRaisesRegex(RuntimeError, "changed"):
                integrity.verify_audio(path)
            integrity.register_audio(path)
            integrity.verify_audio(path)

    def test_tts_cache_and_metadata_are_verified(self):
        key = hashlib.sha256(b"voice_+0%_hello").hexdigest()[:16]
        assets = os.path.join(self.root, "assets")
        os.makedirs(assets)
        wav = os.path.join(assets, f"tts_{key}.wav")
        meta = os.path.join(assets, f"tts_{key}.meta.json")
        with open(wav, "wb") as f:
            f.write(b"audio")
        with open(meta, "w") as f:
            json.dump({"duration": 1, "boundaries": []}, f)
        out = os.path.join(self.root, "out.wav")
        with self.assertRaisesRegex(RuntimeError, "register"):
            tts.synthesize_voiceover_with_timings("hello", "voice", out)
        integrity.register_audio(wav)
        integrity.register_audio(meta)
        tts.synthesize_voiceover_with_timings("hello", "voice", out)
        with open(meta, "w") as f:
            f.write('{}')
        with self.assertRaisesRegex(RuntimeError, "changed"):
            tts.synthesize_voiceover_with_timings("hello", "voice", out)
        os.remove(wav)
        os.remove(meta)
        with self.assertRaises(FileNotFoundError):
            tts.synthesize_voiceover_with_timings("hello", "voice", out)

    def test_explicit_voice_and_bgm_require_registration(self):
        path = os.path.join(self.root, "music.wav")
        with open(path, "wb") as f:
            f.write(b"untrusted")
        out = os.path.join(self.root, "out.wav")
        with self.assertRaisesRegex(RuntimeError, "register"):
            shot.prepare_shot_audio({"bgm": path}, 30, 30, out)
        with self.assertRaisesRegex(RuntimeError, "register"):
            shot.prepare_shot_audio({"voiceover": path, "voice": "v"}, 30, 30, out)

    def test_gate_checks_silent_track_and_fails_closed(self):
        stage_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                                  "stages", "04_gate.py")
        module_spec = importlib.util.spec_from_file_location("audio_gate_test", stage_path)
        gate = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(gate)
        spec = {"id": "silence", "canvas": {"w": 10, "h": 10}, "fps": 30,
                "durationInFrames": 30, "gates": [], "layers": [], "frame_freeze": True}
        from core import audio
        for peak, measured, expected in ((-90, True, 0), (-20, True, 1), (-99, False, 1)):
            with self.subTest(peak=peak, measured=measured), \
                 patch.object(gate, "ROOT", self.root), \
                 patch.object(gate, "load_spec", return_value=spec), \
                 patch.object(gate, "_verify_measured_object"), \
                 patch.object(gate.manifest, "verified", return_value=None), \
                 patch.object(audio, "measure_av_durations", return_value={"has_audio": True, "delta": 0}), \
                 patch.object(audio, "measure_audio_silence", return_value={"max_volume": peak, "measurement_ok": measured}), \
                 patch.object(sys, "argv", ["gate"]):
                self.assertEqual(gate.main(), expected)
                with open(os.path.join(self.root, "build", "gates", "silence.json")) as f:
                    rows = json.load(f)
                self.assertEqual(next(r for r in rows if r["id"] == "audio_silence")["pass"], expected == 0)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_real_silence_and_short_peak(self):
        silent = os.path.join(self.root, "silent.wav")
        peak = os.path.join(self.root, "peak.wav")
        for path, source in ((silent, "anullsrc=r=44100:cl=stereo"),
                             (peak, "aevalsrc=if(lt(t\\,0.01)\\,0.5\\,0):s=44100")):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source,
                            "-t", "1", path], check=True)
        a, b = metrics.measure_audio_silence(silent), metrics.measure_audio_silence(peak)
        self.assertTrue(a["measurement_ok"])
        self.assertLess(a["max_volume"], -45)
        self.assertTrue(b["measurement_ok"])
        self.assertGreaterEqual(b["max_volume"], -45)


if __name__ == "__main__":
    unittest.main()
