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
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, ROOT)

from core.generation import models
from core.spec.shot import validate

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

        with mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("make it snowy", "derived", aspect_ratio="9:16",
                                   resolution="2K",
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

        with mock.patch.object(gen_connector.subprocess, "run", side_effect=fake_run):
            s1.call_generate_image("plain", "fresh")
        req = captured["payload"]["requests"][0]
        self.assertNotIn("reference_images", req)
        self.assertNotIn("input_urls", req)


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


class TestEnvModelOverrides(unittest.TestCase):
    """POSTER_MODELS_JSON / POSTER_VIDEO_MODEL must fail loudly, not silently.

    The override exists to adapt the catalog to the environment. A typo that
    leaves the defaults in place is indistinguishable from an override that
    did nothing, and a half-populated entry crashes the very validator that
    is supposed to report it. Each case runs in a subprocess so the module
    reload cannot leak into the other tests.
    """

    def _run(self, env, code):
        full = dict(os.environ)
        full.pop("POSTER_MODELS_JSON", None)
        full.pop("POSTER_VIDEO_MODEL", None)
        full.update(env)
        return subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, env=full, timeout=60, cwd=ROOT)

    def test_00_malformed_json_warns_and_keeps_the_builtin_catalog(self):
        proc = self._run(
            {"POSTER_MODELS_JSON": "{ not json"},
            "from core.generation import models\n"
            "print(models.video_duration_range('MiniMax-Hailuo-2.3'))\n"
            "print(models.video_allowed_durations('MiniMax-Hailuo-2.3'))\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("could not be parsed", proc.stderr)
        self.assertIn("(6, 10)", proc.stdout)

    def test_01_incomplete_override_is_refused_with_a_warning(self):
        proc = self._run(
            {"POSTER_MODELS_JSON": '{"MyCustom": {"audio": true}}'},
            "from core.generation import models\n"
            "print('MyCustom' in models.VIDEO_MODELS)\n"
            "print(models.video_duration_range('MyCustom'))\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("missing", proc.stderr)
        self.assertIn("False", proc.stdout)
        self.assertIn("None", proc.stdout)

    def test_02_complete_override_is_applied(self):
        proc = self._run(
            {"POSTER_MODELS_JSON": '{"MiniMax-H3": {"audio": false}}'},
            "from core.generation import models\n"
            "print(models.video_has_audio('MiniMax-H3'))\n"
            "print(models.video_duration_range('MiniMax-H3'))\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("False", proc.stdout)
        self.assertIn("(4, 15)", proc.stdout)

    def test_03_new_model_with_full_capabilities_is_accepted(self):
        proc = self._run(
            {"POSTER_MODELS_JSON": '{"MyCustom": {"min_dur": 3, "max_dur": 12,'
                                    ' "resolutions": ["768P"], "audio": true}}'},
            "from core.generation import models\n"
            "print(models.video_duration_range('MyCustom'))\n"
            "print(models.video_resolutions('MyCustom'))\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("(3, 12)", proc.stdout)
        self.assertIn("('768P',)", proc.stdout)

    def test_04_invalid_default_model_is_reported_not_crashed(self):
        """A bad POSTER_VIDEO_MODEL must produce a readable error.

        The validator is the user's first door; it must report the problem,
        not raise a TypeError from an unpack of None.
        """
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from core.spec.shot import validate\n"
            "spec = {'id':'s','canvas':{'w':1080,'h':1920},'fps':30,'durationInFrames':180,\n"
            "  'layers':[{'id':'c','type':'video','asset':'a','rect':[0,0,1080,1920],"
            "'z':0,'duration':6}],\n"
            "  'gates':[{'id':'m','metric':'changed_pixel_ratio','lo':0.001,'hi':0.1}]}\n"
            "print(validate(spec))\n"
        ) % ROOT
        proc = self._run({"POSTER_VIDEO_MODEL": "Bogus-Model"}, code)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("default video model", proc.stdout)
        self.assertIn("Bogus-Model", proc.stdout)

    def test_05_discrete_durations_widen_a_conflicting_range(self):
        proc = self._run(
            {"POSTER_MODELS_JSON": '{"MiniMax-Hailuo-2.3": {"durations": [4, 12]}}'},
            "from core.generation import models\n"
            "print(models.video_duration_range('MiniMax-Hailuo-2.3'))\n"
            "print(models.video_allowed_durations('MiniMax-Hailuo-2.3'))\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("(4, 12)", proc.stdout)


if __name__ == "__main__":
    unittest.main()
