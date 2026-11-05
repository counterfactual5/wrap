"""Generation parameters validated before a paid call, and image-to-image.

Two things this covers:

  1. The spec validator rejects an unknown video model, an out-of-range
     duration, an unsupported resolution or ratio, and a malformed
     image-to-image reference — before S1 spends anything on a call.
  2. Image-to-image works end to end: the frozen source asset is uploaded,
     its temp_url is handed to the backend as input_urls, and the derived
     image is normalized and frozen like any other asset.

The backend is stubbed in these tests; no generation credits are spent.
"""
import importlib.util
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)

from core import models
from core.schema import validate

_spec = importlib.util.spec_from_file_location(
    "s1_gen_params", os.path.join(ROOT, "stages", "01_generate.py")
)
s1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s1)


def _spec(layer=None):
    base = {"id": "clip", "type": "video", "asset": "clip-a",
            "rect": [0, 0, 1080, 1920], "z": 0}
    if layer:
        base.update(layer)
    return {
        "id": "params-test",
        "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
        "fps": 30,
        "durationInFrames": 60,
        "layers": [base],
        "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                   "lo": 0.0001, "hi": 0.15}],
    }


class TestVideoParamValidation(unittest.TestCase):
    """The validator must agree with the backend catalog."""

    def test_00_known_model_and_duration_pass(self):
        self.assertEqual(validate(_spec({"model": "MiniMax-H3-Max",
                                         "duration": 6})), [])

    def test_01_unknown_model_is_rejected(self):
        errs = validate(_spec({"model": "MiniMax-H3-Maxx"}))
        self.assertTrue(any("unknown" in e for e in errs), errs)

    def test_02_duration_below_model_minimum_is_rejected(self):
        # H3-Max accepts 5-15s; 3s would be rejected by the backend.
        errs = validate(_spec({"model": "MiniMax-H3-Max", "duration": 3}))
        self.assertTrue(any("duration" in e for e in errs), errs)

    def test_03_duration_above_model_maximum_is_rejected(self):
        errs = validate(_spec({"model": "MiniMax-H3-Max", "duration": 20}))
        self.assertTrue(any("duration" in e for e in errs), errs)

    def test_04_duration_at_the_boundaries_passes(self):
        for d in (5, 15):
            with self.subTest(d=d):
                self.assertEqual(validate(_spec({"model": "MiniMax-H3-Max",
                                                 "duration": d})), [])

    def test_05_unsupported_resolution_is_rejected(self):
        errs = validate(_spec({"model": "MiniMax-H3-Max", "resolution": "2K"}))
        self.assertTrue(any("resolution" in e for e in errs), errs)

    def test_06_unsupported_ratio_is_rejected(self):
        errs = validate(_spec({"ratio": "5:4"}))
        self.assertTrue(any("ratio" in e for e in errs), errs)

    def test_07_catalog_matches_the_backend_contract(self):
        self.assertEqual(models.video_duration_range("MiniMax-H3"), (4, 15))
        self.assertEqual(models.video_duration_range("MiniMax-H3-Max"), (5, 15))
        self.assertEqual(models.video_duration_range("MiniMax-Hailuo-2.3"), (6, 10))


class TestImageToImageValidation(unittest.TestCase):
    def _ai_spec(self, **layer):
        base = {"id": "hero", "type": "ai", "asset": "hero-a",
                "keyColor": "#070512", "blend": "normal",
                "rect": [0, 0, 1080, 1920], "z": 0}
        base.update(layer)
        return {
            "id": "i2i-test",
            "canvas": {"w": 1080, "h": 1920, "bg": "#070512"},
            "fps": 30,
            "durationInFrames": 60,
            "layers": [base],
            "gates": [{"id": "motion", "metric": "changed_pixel_ratio",
                       "lo": 0.0001, "hi": 0.15}],
        }

    def test_00_valid_input_asset_passes(self):
        self.assertEqual(validate(self._ai_spec(input_asset="base-a")), [])

    def test_01_non_string_input_asset_is_rejected(self):
        errs = validate(self._ai_spec(input_asset=42))
        self.assertTrue(any("input_asset" in e for e in errs), errs)

    def test_02_path_like_input_asset_is_rejected(self):
        errs = validate(self._ai_spec(input_asset="assets/base-a.png"))
        self.assertTrue(any("input_asset" in e for e in errs), errs)

    def test_03_non_string_prompt_is_rejected(self):
        errs = validate(self._ai_spec(prompt=123))
        self.assertTrue(any("prompt" in e for e in errs), errs)


class TestImageToImageTransport(unittest.TestCase):
    """The upload hop and the request shape."""

    def test_00_upload_returns_temp_url(self):
        payload = {"file": "x.png", "temp_url": "https://example.invalid/tmp/x.png",
                   "expires_in_seconds": 3600}
        with mock.patch.object(s1.subprocess, "run") as run:
            run.return_value = type(
                "R", (), {"returncode": 0, "stdout": json.dumps(payload),
                          "stderr": ""})()
            url = s1.upload_temp_url("/tmp/x.png")
        self.assertEqual(url, "https://example.invalid/tmp/x.png")

    def test_01_upload_without_temp_url_raises(self):
        with mock.patch.object(s1.subprocess, "run") as run:
            run.return_value = type(
                "R", (), {"returncode": 0, "stdout": json.dumps({"file": "x"}),
                          "stderr": ""})()
            with self.assertRaises(RuntimeError) as ctx:
                s1.upload_temp_url("/tmp/x.png")
        self.assertIn("temp_url", str(ctx.exception))

    def test_02_request_carries_input_urls(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            args_file = cmd[cmd.index("--args-file") + 1]
            with open(args_file) as f:
                captured["payload"] = json.load(f)
            return type("R", (), {
                "returncode": 0,
                "stdout": json.dumps({"success_items": [{"node_id": "9"}]}),
                "stderr": ""})()

        with mock.patch.object(s1.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("make it snowy", "derived", aspect_ratio="9:16",
                                   resolution="2K",
                                   input_urls=["https://example.invalid/a.png"])
        req = captured["payload"]["requests"][0]
        self.assertEqual(req["input_urls"], ["https://example.invalid/a.png"])

    def test_03_request_without_input_urls_omits_the_key(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            args_file = cmd[cmd.index("--args-file") + 1]
            with open(args_file) as f:
                captured["payload"] = json.load(f)
            return type("R", (), {
                "returncode": 0,
                "stdout": json.dumps({"success_items": [{"node_id": "9"}]}),
                "stderr": ""})()

        with mock.patch.object(s1.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("plain", "fresh")
        self.assertNotIn("input_urls", captured["payload"]["requests"][0])


class TestPromptComposition(unittest.TestCase):
    """A layer prompt describes THIS asset; the style describes the episode.

    Appending them would hand the backend two conflicting descriptions of the
    same image, so a layer prompt replaces the style's subject/composition
    while the style's background/exclude constraints remain.
    """

    STYLE = {
        "promptFields": {
            "subject": "a quantum tunneling wave",
            "composition": "centered wave function",
            "background": "deep dark indigo background",
            "exclude": "no text, no watermark",
        }
    }

    def test_00_style_only_uses_all_style_fields(self):
        prompt = s1.build_prompt(self.STYLE)
        self.assertIn("a quantum tunneling wave", prompt)
        self.assertIn("centered wave function", prompt)
        self.assertIn("deep dark indigo background", prompt)
        self.assertIn("no text, no watermark", prompt)

    def test_01_layer_prompt_replaces_subject_and_composition(self):
        prompt = s1.build_prompt(self.STYLE, "a snowy skyline, cold blue light")
        self.assertIn("a snowy skyline, cold blue light", prompt)
        self.assertNotIn("quantum tunneling", prompt)
        self.assertNotIn("wave function", prompt)

    def test_02_layer_prompt_keeps_background_and_exclude(self):
        prompt = s1.build_prompt(self.STYLE, "a snowy skyline")
        self.assertIn("deep dark indigo background", prompt)
        self.assertIn("no text, no watermark", prompt)

    def test_03_blank_layer_prompt_falls_back_to_style(self):
        prompt = s1.build_prompt(self.STYLE, "   ")
        self.assertIn("a quantum tunneling wave", prompt)


if __name__ == "__main__":
    unittest.main()
