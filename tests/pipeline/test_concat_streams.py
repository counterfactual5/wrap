"""Concat must not silently drop an audio track.

The native video models (H3 / H3-Max) render their own synchronized audio
track, while the pipeline's TTS chain produces a different one. A timeline
that mixes the two gives the concat demuxer inputs with mismatched stream
configurations — and with `-c copy` it drops the audio of every shot that
had one, exiting 0 without a word.

These tests cover the guard: mismatched stream configurations are refused
with a readable error naming the shots involved.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core import audio


def _probe_streams(path):
    """(has_audio, sample_rate, channels) of an mp4, via ffprobe."""
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "stream=codec_type,sample_rate,channels", "-of", "json", path]
    res = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(res.stdout)
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return has_audio


class TestStreamConfigProbe(unittest.TestCase):
    """The probe must report the audio stream's presence correctly."""

    def test_00_detects_video_only(self):
        with tempfile_mp4(has_audio=False) as path:
            self.assertFalse(_probe_streams(path))

    def test_01_detects_audio(self):
        with tempfile_mp4(has_audio=True) as path:
            self.assertTrue(_probe_streams(path))


class tempfile_mp4:
    """Build a tiny mp4 with or without an audio track, in a temp dir."""

    def __init__(self, has_audio):
        self.has_audio = has_audio
        self.path = None

    def __enter__(self):
        import tempfile
        self._dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._dir.name, "clip.mp4")
        cmd = ["ffmpeg", "-v", "error", "-y",
               "-f", "lavfi", "-i", "color=c=0x203040:s=64x64:r=30"]
        if self.has_audio:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=0.4",
                    "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-ar", "44100", "-ac", "2"]
        cmd += ["-frames:v", "10", "-c:v", "libx264", "-pix_fmt", "yuv420p", self.path]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"could not build the test clip:\n{res.stderr}")
        return self.path

    def __exit__(self, *exc):
        self._dir.cleanup()
        return False


class TestConcatStreamGuard(unittest.TestCase):
    """`pipeline.py concat` must refuse a timeline whose shots disagree on
    whether they carry an audio track."""

    def _concat(self, clips):
        """Assemble the given mp4s with the real concat command; return
        (returncode, stdout, stderr)."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            listing = os.path.join(d, "list.txt")
            with open(listing, "w") as f:
                for p in clips:
                    f.write(f"file '{os.path.abspath(p)}'\n")
            out = os.path.join(d, "out.mp4")
            cmd = ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                   "-i", listing, "-c", "copy", "-movflags", "+faststart", out]
            res = subprocess.run(cmd, capture_output=True, text=True)
            produced = out if os.path.exists(out) else None
            return res, produced

    def test_00_mixed_audio_streams_lose_the_track(self):
        """The bug this guards: mixing a silent and an audible shot drops
        the audible shot's track, with a zero exit code."""
        with tempfile_mp4(has_audio=False) as silent, \
             tempfile_mp4(has_audio=True) as audible:
            res, produced = self._concat([silent, audible])
            self.assertEqual(res.returncode, 0,
                             "ffmpeg's behaviour may have changed; re-check the premise")
            self.assertIsNotNone(produced)
            self.assertFalse(_probe_streams(produced),
                             "premise broken: the audio track was NOT dropped — "
                             "ffmpeg may have started handling this case")

    def test_01_guard_detects_the_mismatch(self):
        """The guard the pipeline uses must flag exactly this case."""
        from pipeline import concat_stream_problem
        with tempfile_mp4(has_audio=False) as silent, \
             tempfile_mp4(has_audio=True) as audible:
            problem = concat_stream_problem([("shot-silent", silent),
                                             ("shot-audible", audible)])
            self.assertIsNotNone(problem, "the guard missed a mixed-audio timeline")
            self.assertIn("shot-silent", problem)
            self.assertIn("shot-audible", problem)

    def test_02_uniform_streams_pass(self):
        """Shots that agree (all silent, or all audible) are not flagged."""
        from pipeline import concat_stream_problem
        with tempfile_mp4(has_audio=False) as a, tempfile_mp4(has_audio=False) as b:
            self.assertIsNone(concat_stream_problem([("s1", a), ("s2", b)]))
        with tempfile_mp4(has_audio=True) as c, tempfile_mp4(has_audio=True) as d:
            self.assertIsNone(concat_stream_problem([("s1", c), ("s2", d)]))


if __name__ == "__main__":
    unittest.main()
