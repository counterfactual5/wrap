"""Video layer audio: the native track must actually reach the finished mp4.

Audio ownership is exclusive (SKILL.md "Audio ownership"):
  - a video layer with muted:false keeps its native track — that track is the
    shot's soundtrack, and it is mastered to the same loudness target as the
    TTS chain;
  - a muted layer (the default) drops it, and the TTS chain owns the audio;
  - declaring both is a spec error, not a style choice.

These tests cover the rule and the wiring. The clip used is the deterministic
local fixture (no generation credits); the audio it carries is a synthetic
tone, which is enough to prove the track is present, mastered and measured.
"""
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "stages"))

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "s3_compose_audio", os.path.join(ROOT, "stages", "03_compose.py")
)
s3 = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(s3)

_spec2 = _ilu.spec_from_file_location(
    "s1_gen_audio", os.path.join(ROOT, "stages", "01_generate.py")
)
s1 = _ilu.module_from_spec(_spec2)
_spec2.loader.exec_module(s1)


def _spec(video_layer=None, audio=None):
    layer = {"id": "clip", "type": "video", "asset": "aud-clip",
             "rect": [0, 0, 1080, 1920], "z": 0}
    if video_layer:
        layer.update(video_layer)
    spec = {
        "id": "audio-test",
        "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
        "fps": 30,
        "durationInFrames": 60,
        "vibe": False,
        "style": "spec/style-quantum.json",
        "layers": [layer],
        "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                   "lo": 0.0001, "hi": 0.3}],
    }
    if audio is not None:
        spec["audio"] = audio
    return spec


class TestAudioOwnershipRule(unittest.TestCase):
    """The mutual-exclusion rule must be decided before any encoding."""

    def test_00_mutually_exclusive_tracks_are_an_error(self):
        """A clip that owns the audio plus a TTS request is a spec error."""
        spec = _spec(video_layer={"muted": False},
                     audio={"voiceover": "hello", "voice": "zh-CN-YunxiNeural"})
        with mock.patch.object(s3, "video_audio_source",
                               return_value="/tmp/clip.mp4"):
            with self.assertRaises(RuntimeError) as ctx:
                s3.encode_mp4(spec, "/tmp/frames", "/tmp/out.mp4")
        self.assertIn("audio conflict", str(ctx.exception))

    def test_01_muted_clip_does_not_conflict(self):
        """A muted clip plus TTS is the normal combination — no error."""
        spec = _spec(video_layer={"muted": True},
                     audio={"voiceover": "hello", "voice": "zh-CN-YunxiNeural"})
        with mock.patch.object(s3, "video_audio_source", return_value=None), \
             mock.patch("core.audio.prepare_shot_audio") as prep:
            prep.return_value = None
            with mock.patch.object(s3.subprocess, "run") as run:
                run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr="")
                s3.encode_mp4(spec, "/tmp/frames", "/tmp/out.mp4")
        # The TTS chain was used.
        prep.assert_called_once()

    def test_02_no_track_declared_is_a_silent_shot(self):
        spec = _spec(video_layer={"muted": True})
        with mock.patch.object(s3, "video_audio_source", return_value=None), \
             mock.patch.object(s3.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="")
            s3.encode_mp4(spec, "/tmp/frames", "/tmp/out.mp4")
        cmd = run.call_args[0][0]
        self.assertNotIn("-c:a", cmd, "a silent shot must not declare an audio codec")


class TestVideoAudioSource(unittest.TestCase):
    def test_00_muted_layer_yields_no_source(self):
        spec = _spec(video_layer={"muted": True})
        with mock.patch.object(s3.manifest, "verified", return_value=None):
            self.assertIsNone(s3.video_audio_source(spec))

    def test_01_unmuted_layer_yields_the_prepared_clip(self):
        spec = _spec(video_layer={"muted": False})
        with mock.patch.object(s3.manifest, "verified") as ver:
            ver.return_value = {"path": "build/prepared/audio-test/aud-clip.mp4"}
            src = s3.video_audio_source(spec)
        self.assertTrue(src.endswith("aud-clip.mp4"), src)

    def test_02_unmuted_layer_without_prepared_row_yields_none(self):
        spec = _spec(video_layer={"muted": False})
        with mock.patch.object(s3.manifest, "verified", return_value=None):
            self.assertIsNone(s3.video_audio_source(spec))


class TestFixtureCarriesAudio(unittest.TestCase):
    """The local fixture must contain a real audio track, or the tests above
    would pass on a clip that never had one."""

    def test_00_fixture_has_an_audio_stream(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "clip.mp4")
            s1._write_video_fixture(out, seconds=1, with_audio=True)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                 "-of", "csv=p=0", out],
                capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertIn("audio", probe.stdout,
                          f"fixture has no audio track: {probe.stdout!r}")


class TestVideoAudioEndToEnd(unittest.TestCase):
    """A clip that owns the audio must produce a shot with a measured track."""

    def test_00_native_audio_reaches_the_finished_mp4(self):
        from tests.helpers import preserve_manifest
        spec = {
            "id": "audio-e2e",
            "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 60,
            "vibe": False,
            "style": "spec/style-quantum.json",
            "layers": [
                {"id": "clip", "type": "video", "asset": "audio-e2e-clip",
                 "rect": [0, 0, 1080, 1920], "z": 0, "plate": False,
                 "muted": False},
            ],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.3}],
        }
        # The temp spec lives under .tmp/ (gitignored): a spec file in spec/ would
        # be an untracked file, and a tree snapshot taken while it exists
        # would read the file's removal as "the tree changed".
        spec_path = os.path.join(ROOT, ".tmp", "audio-e2e.poster.json")
        with open(spec_path, "w") as f:
            json.dump(spec, f, indent=2)

        with preserve_manifest():
            try:
                # A fixture clip WITH audio: the track must survive S2, be
                # mastered in S3 and be measured by S4.
                gen = subprocess.run(
                    [sys.executable, "stages/01_generate.py", "--spec", spec_path,
                     "--fixture"],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(gen.returncode, 0, gen.stdout + gen.stderr)

                # Give the fixture a real track (the default fixture is silent).
                clip_path = os.path.join(ROOT, "assets", "audio-e2e-clip.mp4")
                s1._write_video_fixture(clip_path, seconds=2, with_audio=True)
                from core import manifest
                manifest.register("assets", "audio-e2e-clip",
                                  "assets/audio-e2e-clip.mp4", source="fixture")

                for stage in ("02_prepare.py", "03_compose.py"):
                    res = subprocess.run(
                        [sys.executable, os.path.join("stages", stage),
                         "--spec", spec_path],
                        cwd=ROOT, capture_output=True, text=True)
                    self.assertEqual(res.returncode, 0,
                                     f"{stage} failed:\n{res.stdout}\n{res.stderr}")

                mp4 = os.path.join(ROOT, "build", "audio-e2e.mp4")
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                     "-of", "csv=p=0", mp4],
                    capture_output=True, text=True)
                self.assertIn("audio", probe.stdout,
                              f"finished mp4 has no audio track: {probe.stdout!r}")

                res = subprocess.run(
                    [sys.executable, "stages/04_gate.py", "--spec", spec_path],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(res.returncode, 0,
                                 f"S4 rejected the shot:\n{res.stdout}\n{res.stderr}")

                with open(os.path.join(ROOT, "build", "gates", "audio-e2e.json")) as f:
                    gates = json.load(f)
                ids = {g["id"] for g in gates}
                # The audio gates must have run against the finished track.
                self.assertIn("audio_silence", ids)
                self.assertIn("audio_loudness", ids)
                for g in gates:
                    self.assertTrue(g["pass"], f"gate {g['id']} failed: {g}")
            finally:
                for path in (spec_path,
                             os.path.join(ROOT, "assets", "audio-e2e-clip.mp4")):
                    if os.path.exists(path):
                        os.remove(path)


if __name__ == "__main__":
    unittest.main()
