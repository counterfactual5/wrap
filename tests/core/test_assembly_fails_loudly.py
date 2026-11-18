"""The assembly side must report what it could not measure.

Three silent failures lived in `core/assembly/timeline.py`:

  * `concat_stream_problem` ran ffprobe without looking at its exit code
    and swallowed a JSON parse error, so a failed probe turned into "this
    shot has no audio track". When every probe failed, the function
    returned None — "these clips can be concatenated" — while the concat
    demuxer would drop every audio track with a zero exit code and no
    warning;
  * `gate_full_video` measured the durations, and when the probe failed
    every duration came back 0. Against an expectation of 0 s that reads
    as a perfect match, so a film nobody measured passed the gate. The
    same zero made "has_audio" False, which skipped the audio gates as if
    the film had been measured to be silent;
  * `extract_frame_asset` took the asset name straight from the command
    line and used it as a path, so "../.." could write outside the assets
    directory.

Each one has a test here, and each test would fail if the fix were undone.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.assembly import timeline as assembly  # noqa: E402


def _probe(returncode, stdout, stderr=""):
    return subprocess.CompletedProcess(args=["ffprobe"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


AUDIO_STREAMS = '{"streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}'
VIDEO_ONLY_STREAMS = '{"streams": [{"codec_type": "video"}]}'


class TestAFailedProbeIsNotAnAbsentAudioTrack(unittest.TestCase):
    """`concat_stream_problem` decides whether the concat demuxer would
    silently drop the soundtrack. It may only say "yes" when it measured."""

    def test_00_a_failing_probe_is_reported(self):
        with mock.patch("subprocess.run",
                        return_value=_probe(1, "", "No such file or directory")):
            problem = assembly.concat_stream_problem(
                [("shot-a", "a.mp4"), ("shot-b", "b.mp4")])
        self.assertIsNotNone(problem,
                             "a failed ffprobe must not read as 'no audio track'")
        self.assertIn("shot-a", problem)
        self.assertIn("shot-b", problem)

    def test_01_every_probe_failing_is_still_a_problem(self):
        """The bug: all probes failed, so both groups were empty, so the
        function said 'these clips agree'."""
        with mock.patch("subprocess.run", return_value=_probe(1, "", "boom")):
            problem = assembly.concat_stream_problem(
                [("shot-a", "a.mp4"), ("shot-b", "b.mp4")])
        self.assertIsNotNone(problem)

    def test_02_unparsable_probe_output_is_a_problem_too(self):
        with mock.patch("subprocess.run", return_value=_probe(0, "not json at all")):
            problem = assembly.concat_stream_problem(
                [("shot-a", "a.mp4"), ("shot-b", "b.mp4")])
        self.assertIsNotNone(problem)
        self.assertIn("shot-a", problem)

    def test_03_one_failed_probe_among_good_ones_is_a_problem(self):
        """A good probe says nothing about the one that failed."""
        answers = [_probe(0, AUDIO_STREAMS), _probe(1, "", "boom")]
        with mock.patch("subprocess.run", side_effect=answers):
            problem = assembly.concat_stream_problem(
                [("shot-a", "a.mp4"), ("shot-b", "b.mp4")])
        self.assertIsNotNone(problem)
        self.assertIn("shot-b", problem)

    def test_04_measured_clips_still_agree(self):
        """The counter-proof: a real measurement still reports 'no problem'
        when the clips agree, and still reports the mismatch when they do
        not."""
        with mock.patch("subprocess.run", return_value=_probe(0, AUDIO_STREAMS)):
            self.assertIsNone(assembly.concat_stream_problem(
                [("s1", "a.mp4"), ("s2", "b.mp4")]))
        with mock.patch("subprocess.run", return_value=_probe(0, VIDEO_ONLY_STREAMS)):
            self.assertIsNone(assembly.concat_stream_problem(
                [("s1", "a.mp4"), ("s2", "b.mp4")]))
        answers = [_probe(0, VIDEO_ONLY_STREAMS), _probe(0, AUDIO_STREAMS)]
        with mock.patch("subprocess.run", side_effect=answers):
            problem = assembly.concat_stream_problem(
                [("shot-silent", "a.mp4"), ("shot-audible", "b.mp4")])
        self.assertIsNotNone(problem)
        self.assertIn("shot-silent", problem)
        self.assertIn("shot-audible", problem)


class TestTheFullVideoGateRefusesUnmeasuredValues(unittest.TestCase):
    """A gate that cannot measure must not pass. `measure_av_durations`
    reports the probe's success as `measurement_ok`; when that key is
    absent, all-zero durations are the only evidence that nothing was
    measured."""

    def _gate(self, av, segments, allow_black=True):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "build"), exist_ok=True)
        silence = {"measurement_ok": True, "max_volume": -20.0, "mean_volume": -30.0,
                   "speech_max_volume": -20.0, "speech_mean_volume": -30.0,
                   "is_silent": False, "has_content": True}
        with mock.patch.object(assembly, "ROOT", tmp), \
                mock.patch("core.audio.measure_av_durations", return_value=av), \
                mock.patch("core.audio.measure_audio_silence", return_value=silence), \
                mock.patch("core.audio.measure_audio_loudness", return_value=-16.0):
            code = assembly.gate_full_video(os.path.join(tmp, "film.mp4"),
                                            "probe-tl", segments,
                                            allow_black=allow_black)
        path = os.path.join(tmp, "build", "gates_full_probe-tl.json")
        with open(path, encoding="utf-8") as f:
            results = json.load(f)
        return code, {r["id"]: r for r in results}

    UNMEASURED = {"video_duration": 0.0, "audio_duration": 0.0,
                  "delta": 0.0, "has_audio": False}

    def test_00_an_unmeasured_probe_does_not_pass_the_duration_gate(self):
        """The zero-vs-zero trap: nothing was measured, so nothing passed."""
        code, gates = self._gate(self.UNMEASURED, [("shot-1", 0.0, 3.0)])
        self.assertEqual(code, 1, "an unmeasured film must not pass the gate")
        self.assertFalse(gates["duration"]["pass"])
        self.assertFalse(gates["av_probe"]["pass"])

    def test_01_an_unmeasured_probe_does_not_pass_with_no_segments(self):
        """Expected 0 s against a measured 0 s is a perfect match — of
        nothing at all."""
        code, gates = self._gate(self.UNMEASURED, [])
        self.assertEqual(code, 1)
        self.assertFalse(gates["duration"]["pass"])
        self.assertFalse(gates["segments"]["pass"])

    def test_02_an_explicit_measurement_failure_wins_over_the_values(self):
        """`measurement_ok: False` is the probe saying it failed; the
        numbers it returns are placeholders and must not be believed."""
        av = {"video_duration": 3.0, "audio_duration": 3.0, "delta": 0.0,
              "has_audio": True, "measurement_ok": False}
        code, gates = self._gate(av, [("shot-1", 0.0, 3.0)])
        self.assertEqual(code, 1)
        self.assertFalse(gates["duration"]["pass"])
        self.assertFalse(gates["audio_presence"]["pass"])

    def test_03_an_unmeasured_probe_does_not_skip_the_audio_gates(self):
        """has_audio False because the probe failed is not the same as
        has_audio False because the film is silent: the first must be a
        failure, the second may be skipped."""
        code, gates = self._gate(self.UNMEASURED, [("shot-1", 0.0, 3.0)])
        self.assertEqual(code, 1)
        self.assertIn("audio_presence", gates)
        self.assertFalse(gates["audio_presence"]["pass"])

    def test_04_a_measured_film_still_passes(self):
        """The counter-proof: a film that was measured, and matches the
        timeline, still passes — and its silent audio track is skipped,
        not failed."""
        av = {"video_duration": 3.0, "audio_duration": 0.0, "delta": 3.0,
              "has_audio": False, "measurement_ok": True}
        code, gates = self._gate(av, [("shot-1", 0.0, 3.0)])
        self.assertEqual(code, 0, f"a measured film must still pass: {gates}")
        self.assertTrue(gates["duration"]["pass"])
        self.assertNotIn("audio_presence", gates)

    def test_05_a_measured_film_with_audio_still_runs_the_audio_gates(self):
        av = {"video_duration": 3.0, "audio_duration": 3.0, "delta": 0.0,
              "has_audio": True, "measurement_ok": True}
        code, gates = self._gate(av, [("shot-1", 0.0, 3.0)])
        self.assertEqual(code, 0, f"a measured film must still pass: {gates}")
        self.assertIn("av_sync", gates)
        self.assertTrue(gates["av_sync"]["pass"])


class TestTheFrameAssetNameIsChecked(unittest.TestCase):
    """The asset name becomes a path (assets/<name>.png) and a manifest
    key, so it must be a plain identifier."""

    def test_00_a_traversing_name_is_refused(self):
        for name in ("../../evil", "a/b", "..", "/abs/path", ".hidden"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    assembly.extract_frame_asset("clip.mp4", name)

    def test_01_a_normal_name_still_works(self):
        """The counter-proof: the check does not break the ordinary path."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)

        def fake_run(cmd, **kwargs):
            out = cmd[-1]
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "wb") as f:
                f.write(b"\x89PNG")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.object(assembly, "ROOT", tmp), \
                mock.patch("core.runtime.manifest.register",
                           return_value={"sha256": "abc"}), \
                mock.patch.object(assembly.subprocess, "run", side_effect=fake_run):
            row = assembly.extract_frame_asset(os.path.join(tmp, "clip.mp4"),
                                               "ok-name")
        self.assertEqual(row["sha256"], "abc")
        self.assertTrue(os.path.exists(os.path.join(tmp, "assets", "ok-name.png")))


if __name__ == "__main__":
    unittest.main()
