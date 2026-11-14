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
import contextlib
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.spec.shot import validate

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


class TestFrozenWindowHint(unittest.TestCase):
    """A freeze with a PASSING motion gate has a different cause.

    The clip moved, but what moved stayed outside the window the composition
    shows: fit:'cover' keeps the CENTRE of the clip, so a 9:16 clip in a 16:9
    rect hides 86% of its width. The raw metrics cannot tell that apart from
    dead footage — and the wrong diagnosis sends the author to the wrong file.
    """

    @contextlib.contextmanager
    def _prepared_clip(self, source_size=(270, 480)):
        """Register a prepared clip row with a known source size."""
        from core.runtime import manifest
        from tests.helpers import preserve_manifest
        with preserve_manifest():
            rel = ".tmp/hint-test/my-clip.mp4"
            path = os.path.join(ROOT, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"not really an mp4 - the hint only reads the ledger")
            manifest.register("prepared", "hint-test/my-clip", rel,
                              source="video", source_size=list(source_size))
            yield

    def _landscape_spec(self, fit=None):
        layer = {"id": "clip", "type": "video", "asset": "my-clip",
                 "rect": [0, 0, 1920, 1080], "z": 0}
        if fit:
            layer["fit"] = fit
        spec = _spec([layer])
        spec["canvas"] = {"w": 1920, "h": 1080}
        return spec

    def test_00_the_crop_is_named_with_numbers(self):
        with self._prepared_clip():
            hint = s4._video_hint(self._landscape_spec(), reason="frozen_window")
        self.assertIn("OUTSIDE the visible crop", hint)
        self.assertIn("270x480", hint)
        self.assertIn("1920x1080", hint)

    def test_01_contain_is_not_blamed_for_the_crop(self):
        """fit:'contain' shows the whole clip — nothing is cropped away."""
        with self._prepared_clip():
            hint = s4._video_hint(self._landscape_spec(fit="contain"),
                                   reason="frozen_window")
        self.assertNotIn("270x480", hint)
        self.assertIn("OUTSIDE the visible crop", hint)

    def test_02_a_matching_aspect_is_not_blamed(self):
        """A clip that matches the rect is cropped nowhere; say so plainly."""
        with self._prepared_clip(source_size=(1920, 1080)):
            hint = s4._video_hint(self._landscape_spec(), reason="frozen_window")
        self.assertNotIn("1920x1080, but the rect", hint)
        self.assertIn("OUTSIDE the visible crop", hint)


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
