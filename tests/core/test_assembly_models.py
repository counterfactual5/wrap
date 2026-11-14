"""Assembly package API and generation catalog state remain consistent."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from core import assembly
from core.generation import models
from core.assembly import timeline


class TestAssemblyPackage(unittest.TestCase):
    def test_package_is_not_an_alias_of_timeline(self):
        self.assertIsNot(assembly, timeline)
        self.assertIs(importlib.import_module("core.assembly.timeline"), timeline)
        # The API lives on the defining submodule only — the package carries
        # no copied export table and no sys.modules alias.
        for name in ("AssemblyError", "missing_assets", "referenced_assets",
                     "spec_references_asset", "extract_frame_asset", "load_timeline",
                     "concat_stream_problem", "gate_full_video"):
            self.assertTrue(hasattr(timeline, name))
            self.assertFalse(hasattr(assembly, name))

    def test_patches_target_defining_module_and_restore(self):
        original = timeline.referenced_assets
        original_root = timeline.ROOT
        target = "core.assembly.timeline"
        with self.subTest(target=target), tempfile.TemporaryDirectory() as root:
            with mock.patch(target + ".referenced_assets", return_value=["seam"]) as refs:
                self.assertTrue(timeline.spec_references_asset({}, "seam"))
                refs.assert_called_once_with({})
            with mock.patch(target + ".ROOT", root):
                self.assertEqual(timeline.load_timeline("nested/timeline.json", True),
                                 {"id": "full-sequence",
                                  "shots": ["tests/fixtures/shot-01.poster.json"]})
                self.assertTrue(Path(root, "nested/timeline.json").is_file())
                with self.assertRaises(timeline.AssemblyError):
                    timeline.load_timeline("missing.json")
            self.assertIs(timeline.referenced_assets, original)
            self.assertEqual(timeline.ROOT, original_root)


class TestGenerationModels(unittest.TestCase):
    def test_consumers_and_patches(self):
        from core.spec import layers
        from core.generation import video

        self.assertIs(layers.models, models)
        self.assertIs(video.models, models)
        self.assertIs(video.VIDEO_MODELS, models.VIDEO_MODELS)
        original = models.VIDEO_MODELS
        original_default = models.DEFAULT_VIDEO_MODEL
        original_range = models.video_duration_range
        for target, caller in (("core.generation.models", models),):
            with self.subTest(target=target):
                with mock.patch(target + ".VIDEO_MODELS", {"custom": {
                        "min_dur": 2, "max_dur": 9, "resolutions": ("2K",)}}), \
                        mock.patch(target + ".DEFAULT_VIDEO_MODEL", "custom"):
                    self.assertEqual(caller.video_duration_range("custom"), (2, 9))
                    self.assertEqual(layers.models.DEFAULT_VIDEO_MODEL, "custom")
                    self.assertEqual(video.models.DEFAULT_VIDEO_MODEL, "custom")
                with mock.patch(target + ".video_duration_range", return_value=(1, 3)) as duration:
                    self.assertEqual(layers.models.video_duration_range("custom"), (1, 3))
                    duration.assert_called_once_with("custom")
                self.assertIs(caller.VIDEO_MODELS, original)
                self.assertEqual(caller.DEFAULT_VIDEO_MODEL, original_default)
                self.assertIs(caller.video_duration_range, original_range)
        with mock.patch.dict(models.VIDEO_MODELS, {}):
            models.VIDEO_MODELS["shared"] = {"min_dur": 1, "max_dur": 2}
            self.assertIs(video.VIDEO_MODELS["shared"], models.VIDEO_MODELS["shared"])
        self.assertNotIn("shared", models.VIDEO_MODELS)

    def test_runtime_manifest_is_strict(self):
        """POSTER_MODELS_JSON replaces the catalog and is VALIDATED: a
        complete manifest applies verbatim; a discrete duration outside the
        declared range or malformed JSON is a loud ValueError, never a
        warning beside a stale catalog."""
        original = models.VIDEO_MODELS
        for target, caller in (("core.generation.models", models),):
            with self.subTest(target=target), mock.patch(target + ".VIDEO_MODELS", {}):
                with mock.patch.dict(os.environ, {"POSTER_MODELS_JSON": json.dumps({
                        "custom": {"min_dur": 3, "max_dur": 8,
                                   "resolutions": ["2K"], "durations": [4, 8]}})}):
                    caller._load_env_models()
                self.assertEqual(caller.video_duration_range("custom"), (3, 8))
                self.assertEqual(caller.video_allowed_durations("custom"), (4, 8))
                self.assertEqual(caller.video_resolutions("custom"), ("2K",))
                with mock.patch.dict(os.environ, {"POSTER_MODELS_JSON": json.dumps({
                        "custom": {"min_dur": 3, "max_dur": 8,
                                   "resolutions": ["2K"], "durations": [2, 9]}})}):
                    with self.assertRaises(ValueError) as ctx:
                        caller._load_env_models()
                self.assertIn("must stay within min_dur/max_dur", str(ctx.exception))
                with mock.patch.dict(os.environ, {"POSTER_MODELS_JSON": "{broken"}):
                    with self.assertRaises(ValueError):
                        caller._load_env_models()
            self.assertIs(models.VIDEO_MODELS, original)

    def test_cold_import_orders_and_reload(self):
        script = '''
import importlib
import os
import sys
first = sys.argv[1]
importlib.import_module(first)
# Loading the catalog from spec must not pull in generation transports.
if first != "core.generation.video":
    assert "core.generation.video" not in sys.modules
    assert "core.generation.connector" not in sys.modules
from core import assembly
from core.generation import models
from core.assembly import timeline
from core.spec import layers
assert models is layers.models
assert assembly is not timeline
assert assembly.timeline is timeline
assert models.video_duration_range("custom") == (2, 7)
assert models.DEFAULT_VIDEO_MODEL == "custom"
assert models.DEFAULT_IMAGE_AREA == "4K"
for path in ("core.generation.models",):
    os.environ["POSTER_MODELS_JSON"] = '{"custom": {"min_dur": 3, "max_dur": 9, "resolutions": ["2K"]}}'
    assert importlib.reload(importlib.import_module(path)) is models
    assert layers.models.video_duration_range("custom") == (3, 9)
for path, module in (("core.assembly", assembly),
                     ("core.assembly.timeline", timeline)):
    assert importlib.reload(importlib.import_module(path)) is module
assert importlib.import_module("core.assembly.timeline") is timeline
'''
        env = dict(os.environ)
        env.update(POSTER_MODELS_JSON=json.dumps({"custom": {
            "min_dur": 2, "max_dur": 7, "resolutions": ["2K"]}}),
            POSTER_VIDEO_MODEL="custom", POSTER_IMAGE_AREA="4K")
        for first in ("core.generation.models", "core.spec",
                      "core.spec.layers", "core.generation.video",
                      "core.assembly", "core.assembly.timeline"):
            with self.subTest(first=first):
                result = subprocess.run([sys.executable, "-c", script, first],
                                        cwd=Path(__file__).resolve().parents[2],
                                        env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
