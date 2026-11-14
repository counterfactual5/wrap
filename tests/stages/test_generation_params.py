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
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.generation import models
from core.spec.layers import validate_video_generation
from core.spec.shot import validate
from tests.helpers import TEST_IMAGE_MODELS, TEST_VIDEO_MODELS

_spec = importlib.util.spec_from_file_location(
    "s1_gen_params", os.path.join(ROOT, "stages", "01_generate.py")
)
s1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s1)

# The transport lives in core/generation/; `subprocess` is a singleton stdlib
# module, so patching it through any importing module intercepts every
# connector call the generation package makes.
from core.generation import connector as gen_connector


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
    """Structural `validate` is model-agnostic (a frozen asset must validate
    with no declared model at all); the capability table is consulted ONCE,
    at generation time, by core.spec.layers.validate_video_generation —
    before S1 spends anything on a call."""

    def setUp(self):
        self._patch = mock.patch.dict(models.VIDEO_MODELS, TEST_VIDEO_MODELS)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_00_a_declared_model_with_an_in_range_duration_passes_both_gates(self):
        layer = _spec({"model": "Test-Max", "duration": 6, "resolution": "768P"})["layers"][0]
        self.assertEqual(validate(_spec(layer)), [])
        self.assertEqual(validate_video_generation(layer, "Test-Max"), [])

    def test_01_structural_validate_accepts_any_model_name(self):
        self.assertEqual(validate(_spec({"model": "Not-Declared-Anywhere"})), [])

    def test_02_the_generation_time_check_refuses_an_undeclared_model(self):
        errs = validate_video_generation({"id": "clip", "asset": "a"}, "MiniMax-H3-Maxx")
        self.assertTrue(any("No configured video capabilities" in e for e in errs), errs)

    def test_03_duration_below_model_minimum_is_rejected(self):
        layer = _spec({"model": "Test-Max", "duration": 3, "resolution": "768P"})["layers"][0]
        errs = validate_video_generation(layer, "Test-Max")
        self.assertTrue(any("duration" in e for e in errs), errs)

    def test_04_duration_above_model_maximum_is_rejected(self):
        layer = _spec({"model": "Test-Max", "duration": 20, "resolution": "768P"})["layers"][0]
        errs = validate_video_generation(layer, "Test-Max")
        self.assertTrue(any("duration" in e for e in errs), errs)

    def test_05_unsupported_resolution_is_rejected(self):
        layer = _spec({"model": "Test-Max", "resolution": "2K"})["layers"][0]
        errs = validate_video_generation(layer, "Test-Max")
        self.assertTrue(any("resolution" in e for e in errs), errs)

    def test_06_unsupported_ratio_is_rejected(self):
        errs = validate(_spec({"ratio": "5:4"}))
        self.assertTrue(any("ratio" in e for e in errs), errs)


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
        with mock.patch.object(gen_connector.subprocess, "run") as run:
            run.return_value = type(
                "R", (), {"returncode": 0, "stdout": json.dumps(payload),
                          "stderr": ""})()
            url = s1.upload_temp_url("/tmp/x.png")
        self.assertEqual(url, "https://example.invalid/tmp/x.png")

    def test_01_upload_without_temp_url_raises(self):
        with mock.patch.object(gen_connector.subprocess, "run") as run:
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

        with mock.patch.object(models, "IMAGE_MODELS", TEST_IMAGE_MODELS), \
                mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("make it snowy", "derived", model="Test-Image",
                                   aspect_ratio="9:16", resolution="2K",
                                   input_urls=["https://example.invalid/a.png"])
        req = captured["payload"]["requests"][0]
        self.assertEqual(req["reference_images"], [{"url": "https://example.invalid/a.png"}])
        self.assertNotIn("input_urls", req)

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

        with mock.patch.object(models, "IMAGE_MODELS", TEST_IMAGE_MODELS), \
                mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("plain", "fresh", model="Test-Image",
                                   aspect_ratio="1:1", resolution="1K")
        req = captured["payload"]["requests"][0]
        self.assertNotIn("reference_images", req)
        self.assertNotIn("input_urls", req)


class TestPromptComposition(unittest.TestCase):
    """Prompts are EXPLICIT per layer: the engine injects no design brief.
    Style files no longer contribute subject/composition/background/exclude
    text — a blank layer prompt is refused at the call (see
    test_first_run), never silently replaced by a built-in description."""

    STYLE = {
        "promptFields": {
            "subject": "a quantum tunneling wave",
            "composition": "centered wave function",
            "background": "deep dark indigo background",
            "exclude": "no text, no watermark",
        }
    }

    def test_00_a_layer_prompt_is_carried_verbatim(self):
        self.assertEqual(s1.build_prompt(self.STYLE, "a snowy skyline, cold blue light"),
                         "a snowy skyline, cold blue light")

    def test_01_the_style_injects_nothing(self):
        self.assertEqual(s1.build_prompt(self.STYLE), "")
        self.assertNotIn("quantum", s1.build_prompt(self.STYLE, "a plain wall"))


class TestEnvModelOverrides(unittest.TestCase):
    """POSTER_MODELS_JSON fully replaces the (empty) built-in catalog and is
    STRICT: a malformed or incomplete manifest is a loud import failure, not
    a warning beside a stale catalog. Each case runs in a subprocess so the
    import-time state cannot leak into the other tests."""

    def _run(self, env, code):
        full = dict(os.environ)
        full.pop("POSTER_MODELS_JSON", None)
        full.pop("POSTER_VIDEO_MODEL", None)
        full.update(env)
        return subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, env=full, timeout=60, cwd=ROOT)

    def test_00_malformed_json_fails_the_import(self):
        proc = self._run(
            {"POSTER_MODELS_JSON": "{ not json"},
            "from core.generation import models\n"
            "print(models.VIDEO_MODELS)\n")
        self.assertNotEqual(proc.returncode, 0,
                            "a malformed manifest must not silently keep a stale catalog")

    def test_01_incomplete_override_is_refused(self):
        proc = self._run(
            {"POSTER_MODELS_JSON": '{"MyCustom": {"audio": true}}'},
            "from core.generation import models\n"
            "print('MyCustom' in models.VIDEO_MODELS)\n")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing required capabilities", proc.stderr)

    def test_02_complete_override_is_applied(self):
        proc = self._run(
            {"POSTER_MODELS_JSON": json.dumps(
                {"MyCustom": {"min_dur": 3, "max_dur": 12,
                              "resolutions": ["768P"], "audio": False}})},
            "from core.generation import models\n"
            "print(models.video_has_audio('MyCustom'))\n"
            "print(models.video_duration_range('MyCustom'))\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("False", proc.stdout)
        self.assertIn("(3, 12)", proc.stdout)

    def test_03_discrete_durations_must_stay_within_the_declared_range(self):
        proc = self._run(
            {"POSTER_MODELS_JSON": json.dumps(
                {"MyCustom": {"min_dur": 5, "max_dur": 8,
                              "resolutions": ["768P"], "durations": [4, 12]}})},
            "from core.generation import models\n"
            "print(models.VIDEO_MODELS)\n")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("must stay within min_dur/max_dur", proc.stderr)

    def test_04_an_invalid_default_model_fails_the_import(self):
        """POSTER_VIDEO_MODEL naming an undeclared model is a contradictory
        configuration: it fails at import, before any stage runs."""
        proc = self._run(
            {"POSTER_VIDEO_MODEL": "Bogus-Model"},
            "from core.generation import models\nprint(models.DEFAULT_VIDEO_MODEL)\n")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Bogus-Model", proc.stderr)

    def test_06_loads_from_project_models_json(self):
        """When env vars are not set, models.py loads models.json from project root."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            models_file = os.path.join(tmp_dir, "models.json")
            with open(models_file, "w") as f:
                json.dump({
                    "video_models": {
                        "ProjectModel": {"min_dur": 4, "max_dur": 10, "resolutions": ["1080P"]}
                    },
                    "image_models": {
                        "ProjectImage": {"aspect_ratios": ["16:9"], "areas": ["2K"]}
                    },
                    "default_video_model": "ProjectModel",
                    "default_image_model": "ProjectImage",
                    "default_image_area": "2K"
                }, f)
            proc = self._run(
                {"POSTER_ROOT": tmp_dir, "POSTER_MODELS_JSON": "", "POSTER_IMAGE_CAPABILITIES_JSON": ""},
                "from core.generation import models\n"
                "print('ProjectModel' in models.VIDEO_MODELS)\n"
                "print('ProjectImage' in models.IMAGE_MODELS)\n"
                "print(models.DEFAULT_VIDEO_MODEL)\n"
                "print(models.DEFAULT_IMAGE_MODEL)\n"
                "print(models.DEFAULT_IMAGE_AREA)\n")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("True", proc.stdout)
            self.assertIn("ProjectModel", proc.stdout)
            self.assertIn("ProjectImage", proc.stdout)
            self.assertIn("2K", proc.stdout)


if __name__ == "__main__":
    unittest.main()
