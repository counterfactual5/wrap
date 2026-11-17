"""BGM consent is about spec intent, not the rendered track's volume.

Run the real CLI in isolated projects: no production assets, manifest, or
rendered output are changed, and no generation/network providers are used.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from core.spec.timeline import validate_timeline

ENGINE = Path(__file__).resolve().parents[2]
FLAG = "allow_bgm_override_silent"


class TestTimelineBgmSchema(unittest.TestCase):
    def test_only_json_booleans_are_accepted(self):
        for value in (None, 0, 1, 0.0, 1.0, "true", "false", "", [], {}):
            with self.subTest(value=value):
                self.assertEqual(validate_timeline({
                    "id": "film", "shots": ["shot"], FLAG: value,
                }), [f"timeline '{FLAG}' must be a boolean"])
        for extra in ({}, {FLAG: False}, {FLAG: True}):
            with self.subTest(extra=extra):
                self.assertEqual(validate_timeline({
                    "id": "film", "shots": ["shot"], **extra,
                }), [])


class TestTimelineBgmIntent(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("spec", "build", ".tmp", "assets"):
            (self.root / name).mkdir()
        self.env = dict(os.environ, POSTER_ROOT=str(self.root),
                        POSTER_MANIFEST=str(self.root / "manifest.json"))
        self.bgm = self.root / "assets" / "bed.wav"
        self.ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=2",
                    "-ar", "44100", "-ac", "2", str(self.bgm))
        self.register_bgm()

    def register_bgm(self):
        subprocess.run([sys.executable, "-m", "core.audio.integrity", "register", str(self.bgm)],
                       cwd=ENGINE, env=self.env, check=True, capture_output=True, timeout=30)

    def ffmpeg(self, *args):
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args],
                       check=True, capture_output=True, timeout=30)

    def write(self, rel, data):
        (self.root / rel).write_text(json.dumps(data))

    def shot(self, name, **extra):
        self.write(f"spec/{name}.poster.json", {
            "id": name, "fps": 30, "durationInFrames": 60,
            "layers": [], **extra,
        })
        return name

    def timeline(self, shots, **extra):
        self.write("spec/timeline.json", {
            "id": "film", "bgm": "bed.wav", "shots": shots, **extra,
        })

    def cli(self, command="concat"):
        result = subprocess.run([
            sys.executable, str(ENGINE / "pipeline.py"), command,
            "--timeline", "spec/timeline.json", "--output", "build/out.mp4",
        ], cwd=self.root, env=self.env, capture_output=True, text=True, timeout=60)
        return result, result.stdout + result.stderr

    def test_silent_shot_requires_consent_before_any_build_or_overwrite(self):
        self.shot("quiet")
        for command in ("concat", "run"):
            for extra in ({}, {FLAG: False}):
                with self.subTest(command=command, extra=extra):
                    self.timeline(["quiet"], **extra)
                    protected = {"manifest.json": b"existing manifest",
                                 "build/out.mp4": b"existing output",
                                 "build/full.mp4": b"existing alias",
                                 "build/gates_full_film.json": b"existing gates"}
                    for path, content in protected.items():
                        (self.root / path).write_bytes(content)
                    result, text = self.cli(command)
                    self.assertNotEqual(result.returncode, 0, text)
                    self.assertIn("intentionally silent shot(s): quiet", text)
                    self.assertIn(f"{FLAG}:true", text)
                    self.assertNotIn("[Build Contract]", text)
                    self.assertNotIn("=== [Stage]", text)
                    self.assertFalse((self.root / "build/quiet.mp4").exists())
                    for path, content in protected.items():
                        self.assertEqual((self.root / path).read_bytes(), content)

    def test_mixed_shots_report_only_silent_ids(self):
        self.shot("spoken", audio={"voiceover": "hello"})
        self.shot("music", audio={"bgm": "bed.wav"})
        self.shot("native", layers=[{"type": "video", "muted": False}])
        self.shot("quiet", layers=[{"type": "video", "muted": True}])
        self.timeline(["spoken", {"spec": "quiet"}, "music", "native"])
        result, text = self.cli()
        self.assertNotEqual(result.returncode, 0, text)
        self.assertIn("intentionally silent shot(s): quiet.", text)
        self.assertNotIn("intentionally silent shot(s): spoken", text)

    def test_invalid_flag_is_rejected_by_both_entry_points(self):
        self.shot("quiet")
        for command in ("concat", "run"):
            for value in (None, 1, "true", [], {}):
                with self.subTest(command=command, value=value):
                    self.timeline(["quiet"], **{FLAG: value})
                    result, text = self.cli(command)
                    self.assertNotEqual(result.returncode, 0, text)
                    self.assertIn(f"timeline '{FLAG}' must be a boolean", text)
                    self.assertNotIn("would override", text)

    def test_missing_bgm_keeps_precise_file_error_even_with_consent(self):
        self.shot("quiet")
        for extra in ({}, {FLAG: True}):
            self.timeline(["quiet"], bgm="missing.wav", **extra)
            result, text = self.cli()
            self.assertNotEqual(result.returncode, 0, text)
            self.assertIn("Timeline BGM file not found: missing.wav", text)
            self.assertNotIn("would override", text)

    def test_missing_shot_keeps_precise_error(self):
        self.timeline(["missing"])
        result, text = self.cli()
        self.assertNotEqual(result.returncode, 0, text)
        self.assertIn(f"Error: shot spec not found: {self.root}/spec/missing.poster.json", text)
        self.assertNotIn("would override", text)

    def render_clip(self, name, audible=False):
        source = "sine=frequency=440:duration=2" if audible else "anullsrc=r=44100:cl=stereo"
        self.ffmpeg("-f", "lavfi", "-i", "color=c=0x203040:s=64x64:r=30:d=2",
                    "-f", "lavfi", "-i", source, "-t", "2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    str(self.root / "build" / f"{name}.mp4"))

    def assert_assembled(self):
        result, text = self.cli()
        self.assertEqual(result.returncode, 0, text)
        self.assertTrue((self.root / "build/out.mp4").is_file())
        gates = json.loads((self.root / "build/gates_full_film.json").read_text())
        self.assertTrue(gates)
        self.assertTrue(all(g["pass"] for g in gates), gates)
        return text

    def test_explicit_consent_really_overlays_silent_audio(self):
        from core.audio.metrics import measure_audio_silence
        self.shot("quiet")
        self.render_clip("quiet")
        self.timeline(["quiet"], **{FLAG: True})
        self.assertIn("timeline bgm: overlaid", self.assert_assembled())
        self.assertFalse(measure_audio_silence(str(self.root / "build/out.mp4"))["is_silent"])

    def test_no_silent_intent_needs_no_consent_even_if_render_is_silent(self):
        # Intent must come from the spec, never inferred from measured volume.
        for extra in ({"audio": {"voiceover": "hello"}},
                      {"audio": {"bgm": "bed.wav"}},
                      {"layers": [{"type": "video", "muted": False}]}):
            with self.subTest(extra=extra):
                self.shot("audible", **extra)
                self.render_clip("audible")
                self.timeline(["audible"])
                self.assertIn("timeline bgm: overlaid", self.assert_assembled())

    def test_audible_shot_mixes_without_consent(self):
        self.shot("audible", audio={"bgm": "bed.wav"})
        self.render_clip("audible", audible=True)
        self.timeline(["audible"], bgmUnderVoice=0.24, **{FLAG: False})
        self.assertIn("timeline bgm: mixed", self.assert_assembled())

    def test_mixing_under_shot_audio_requires_a_declared_duck_ratio(self):
        """The engine ships no default bed level: an audible shot under a
        timeline BGM bed must declare timeline 'bgmUnderVoice'."""
        self.shot("audible", audio={"bgm": "bed.wav"})
        self.render_clip("audible", audible=True)
        self.timeline(["audible"])
        result, text = self.cli()
        self.assertNotEqual(result.returncode, 0, text)
        self.assertIn("bgmUnderVoice", text)

    def test_integrity_cannot_be_bypassed_by_consent_or_existing_render(self):
        self.shot("quiet")
        self.render_clip("quiet")
        for command in ("concat", "run"):
            for state in ("unregistered", "tampered"):
                for bgm in ("bed.wav", "assets/bed.wav", str(self.bgm)):
                    with self.subTest(command=command, state=state, bgm=bgm):
                        self.register_bgm()
                        if state == "unregistered":
                            self.write("manifest.json", {"assets": {}, "prepared": {}, "video": {}})
                        else:
                            with self.bgm.open("ab") as f:
                                f.write(b"tampered")
                        ledger = (self.root / "manifest.json").read_bytes()
                        self.timeline(["quiet"], bgm=bgm, **{FLAG: True})
                        output = self.root / "build/out.mp4"
                        output.write_bytes(b"existing film")
                        result, text = self.cli(command)
                        self.assertNotEqual(result.returncode, 0, text)
                        self.assertIn("Audio integrity check failed (unregistered or changed)", text)
                        self.assertIn(str(self.bgm), text)
                        self.assertNotIn("=== [Stage]", text)
                        self.assertEqual(output.read_bytes(), b"existing film")
                        self.assertEqual((self.root / "manifest.json").read_bytes(), ledger)

    def test_inactive_bgm_does_not_require_consent(self):
        self.shot("quiet")
        self.render_clip("quiet")
        for bgm in (None, "", "  ", "none", " NoNe "):
            with self.subTest(bgm=bgm):
                self.timeline(["quiet"], bgm=bgm)
                self.assertNotIn("timeline bgm:", self.assert_assembled())
        self.write("spec/timeline.json", {"id": "film", "shots": ["quiet"]})
        self.assertNotIn("timeline bgm:", self.assert_assembled())
