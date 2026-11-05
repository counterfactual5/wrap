"""The gate must point at the video layer, and must not accept sourceFps.

Two things this covers:

  1. When a shot's video layer is a static clip, the motion and freeze gates
     go red. The raw metrics ("changed_pixel_ratio 0.000000", "1 frozen
     segment") do not say where to look; the failure must name the layer and
     its clip, so the author knows the SOURCE footage is the problem rather
     than the composition.

  2. `sourceFps` must be rejected: S2 re-encodes every clip to the shot's
     frame rate, so the renderer always sees the source at the canvas fps and
     a sourceFps would only mis-convert trim's seconds.
"""
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)

from core.schema import validate

_spec = importlib.util.spec_from_file_location(
    "s4_gate", os.path.join(ROOT, "stages", "04_gate.py")
)
s4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s4)


def _spec(layers):
    return {
        "id": "hint-test",
        "canvas": {"w": 1080, "h": 1920},
        "fps": 30,
        "durationInFrames": 60,
        "layers": layers,
        "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                   "lo": 0.0001, "hi": 0.15}],
    }


class TestVideoHint(unittest.TestCase):
    def test_00_no_video_layer_means_no_hint(self):
        spec = _spec([{"id": "bg", "type": "code", "draw": "grid",
                        "rect": [0, 0, 1080, 1920], "z": 0}])
        self.assertEqual(s4._video_hint(spec), "",
                         "a shot without a video layer must not get a hint")

    def test_01_video_layer_produces_a_hint(self):
        spec = _spec([{"id": "clip", "type": "video", "asset": "my-clip",
                        "rect": [0, 0, 1080, 1920], "z": 0}])
        hint = s4._video_hint(spec)
        self.assertIn("video layer", hint)
        self.assertIn("my-clip", hint)

    def test_02_hint_explains_the_source_footage(self):
        spec = _spec([{"id": "clip", "type": "video", "asset": "my-clip",
                        "rect": [0, 0, 1080, 1920], "z": 0}])
        hint = s4._video_hint(spec)
        self.assertIn("SOURCE", hint.upper(),
                      "the hint must say the failure is in the source footage")


class TestSourceFpsRejected(unittest.TestCase):
    def test_00_source_fps_is_rejected(self):
        spec = _spec([{"id": "clip", "type": "video", "asset": "a",
                        "rect": [0, 0, 1080, 1920], "z": 0, "sourceFps": 24}])
        errs = validate(spec)
        self.assertTrue(any("sourceFps" in e for e in errs), errs)

    def test_01_the_message_explains_why(self):
        spec = _spec([{"id": "clip", "type": "video", "asset": "a",
                        "rect": [0, 0, 1080, 1920], "z": 0, "sourceFps": 24}])
        errs = validate(spec)
        self.assertTrue(any("frame rate" in e for e in errs), errs)

    def test_02_a_spec_without_it_still_validates(self):
        spec = _spec([{"id": "clip", "type": "video", "asset": "a",
                        "rect": [0, 0, 1080, 1920], "z": 0, "trim": [1, 4]}])
        self.assertEqual(validate(spec), [])


if __name__ == "__main__":
    unittest.main()
