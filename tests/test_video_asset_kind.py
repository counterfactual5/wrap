"""A video layer must point at real footage, and the gates must name the cause.

Two hand mistakes this catches:

  1. A `type: "video"` layer pointing at a picture. ffmpeg would convert it
     into a 1-frame mp4 — a still shot that only surfaces at the motion and
     freeze gates, with the wrong reason.

  2. A clip shorter than the shot with `loop: false`. The footage runs out
     and the tail freezes — which is a different problem from footage that
     was never moving, and the hint must say so.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s2 = _load("s2_media", os.path.join(ROOT, "stages", "02_prepare.py"))
s4 = _load("s4_media", os.path.join(ROOT, "stages", "04_gate.py"))


def _make_clip(path, seconds=2, fps=30, w=64, h=64, still=False):
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "lavfi", "-i", f"color=c=0x203040:s={w}x{h}:r={fps}"]
    if still:
        cmd += ["-frames:v", "1"]
    else:
        cmd += ["-frames:v", str(seconds * fps)]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", path]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


class TestMediaProbe(unittest.TestCase):
    def test_00_a_clip_reports_its_frames_and_duration(self):
        with tempfile.TemporaryDirectory() as d:
            path = _make_clip(os.path.join(d, "clip.mp4"), seconds=2)
            w, h, frames, dur = s2._video_source_info(path)
            self.assertEqual((w, h), (64, 64))
            self.assertEqual(frames, 60)
            self.assertAlmostEqual(dur, 2.0, delta=0.2)

    def test_01_a_still_image_reports_no_frames(self):
        """A picture probed as media has no frames — that is the signal."""
        with tempfile.TemporaryDirectory() as d:
            path = _make_clip(os.path.join(d, "still.png"), seconds=1, still=True)
            w, h, frames, dur = s2._video_source_info(path)
            self.assertEqual((w, h), (64, 64))
            # No frame count at all, or exactly one — either way it is not a
            # clip that can carry motion.
            self.assertTrue(frames is None or frames < 2,
                            f"a still must not report usable frames (got {frames})")
            self.assertEqual(dur, 0.0)


class TestFreezeHint(unittest.TestCase):
    """The hint must tell the two freeze causes apart."""

    def _spec(self, loop):
        return {
            "id": "hint-shot",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 300,
            "layers": [{"id": "clip", "type": "video", "asset": "short-clip",
                        "rect": [0, 0, 1080, 1920], "z": 0, "loop": loop}],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.3}],
        }

    def test_00_a_ran_out_clip_says_so(self):
        row = {"path": "build/prepared/hint-shot/short-clip.mp4",
               "shorter_than_shot": True}
        import unittest.mock as mock
        with mock.patch.object(s4.manifest, "verified", return_value=row):
            hint = s4._video_hint(self._spec(loop=False))
        self.assertIn("RAN OUT", hint)
        self.assertIn("loop", hint)

    def test_01_a_looping_clip_gets_the_generic_hint(self):
        row = {"path": "build/prepared/hint-shot/short-clip.mp4",
               "shorter_than_shot": True}
        import unittest.mock as mock
        with mock.patch.object(s4.manifest, "verified", return_value=row):
            hint = s4._video_hint(self._spec(loop=True))
        self.assertNotIn("RAN OUT", hint)
        self.assertIn("static", hint)

    def test_02_a_shot_without_video_layers_has_no_hint(self):
        spec = {
            "id": "hint-shot",
            "canvas": {"w": 1080, "h": 1920},
            "fps": 30,
            "durationInFrames": 300,
            "layers": [{"id": "bg", "type": "code", "draw": "grid",
                        "rect": [0, 0, 1080, 1920], "z": 0}],
            "gates": [],
        }
        self.assertEqual(s4._video_hint(spec), "")


class TestS5Criteria(unittest.TestCase):
    def test_00_the_duration_criterion_exists(self):
        s5 = _load("s5_media", os.path.join(ROOT, "stages", "05_inspect.py"))
        joined = " ".join(s5.AUDIT_CRITERIA)
        self.assertIn("source_duration", joined)
        self.assertIn("source_resolution", joined,
                      "the earlier criterion must not be lost")
        self.assertGreaterEqual(len(s5.AUDIT_CRITERIA), 6)


if __name__ == "__main__":
    unittest.main()
